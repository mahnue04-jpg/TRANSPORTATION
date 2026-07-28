"""Advance scheduling: future ride reservations separate from immediate active workload."""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.modules.health_isf.models import (
    CustomerRequestStatus,
    DispatchAssignmentState,
    DriverStatus,
    HealthISFCustomerRideRequest,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.scheduling import (
    format_scheduling_summary,
    is_dispatch_eligible,
    is_immediate_ride,
    is_protected_scheduled_reservation,
)

SCHEDULED_DISPATCH_ASSIGNMENT_STATES = {
    DispatchAssignmentState.SCHEDULED_OFFERED.value,
    DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
}

SCHEDULED_OFFER_TIMEOUT_SECONDS = int(
    os.getenv("HEALTH_ISF_SCHEDULED_OFFER_TIMEOUT_SECONDS", str(7 * 24 * 3600))
)


def is_scheduled_assignment_state(state: Optional[str]) -> bool:
    return str(state or "").lower() in SCHEDULED_DISPATCH_ASSIGNMENT_STATES


def _rides_for_customer_request(db: Session, request_obj: HealthISFCustomerRideRequest) -> list[HealthISFRide]:
    from app.modules.health_isf.service import get_ride_by_id

    linked_ids: list[str] = []
    raw = getattr(request_obj, "linked_ride_ids_json", None)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                linked_ids = [str(x) for x in parsed if x]
        except (TypeError, json.JSONDecodeError):
            linked_ids = []
    if not linked_ids and request_obj.ride_id:
        linked_ids = [str(request_obj.ride_id)]

    rides: list[HealthISFRide] = []
    for ride_id in linked_ids:
        ride = get_ride_by_id(db, ride_id)
        if ride:
            rides.append(ride)
    if not rides and request_obj.ride_id:
        primary = get_ride_by_id(db, str(request_obj.ride_id))
        if primary:
            rides = [primary]
    return rides


def _record_scheduled_audit(
    db: Session,
    *,
    ride_id: str,
    action: str,
    request_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    assignment_id: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    from app.modules.health_isf.service import _record_dispatch, now

    ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
    lifecycle = str(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", "") or "")
    _record_dispatch(
        db,
        ride_id=ride_id,
        action=action,
        acted_by_user_id=actor_user_id,
        driver_id=driver_id,
        note=note,
        request_id=request_id,
        assignment_id=assignment_id,
        lifecycle_state=lifecycle,
        transition_reason=action,
        transition_timestamp=now(),
        assignment_transition_source="advance_scheduling",
    )


def evaluate_advance_scheduling_candidates(
    db: Session,
    *,
    organization_id: str,
    ride: HealthISFRide,
    exclude_driver_ids: Optional[set[str]] = None,
    preferred_driver_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Score drivers for advance scheduling; allows drivers with only future reservations."""
    from app.modules.health_isf.service import (
        _coerce_driver_status,
        _driver_active_workload_count,
        _driver_mobile_dispatch_ready,
        _driver_status_dispatch_ready,
        _is_driver_busy,
        _normalized_timestamp_token,
        _seconds_since,
        evaluate_dispatch_candidates,
        get_driver_by_id,
        now,
    )

    if preferred_driver_id:
        preferred = get_driver_by_id(db, preferred_driver_id)
        if preferred and str(preferred.organization_id) == str(organization_id):
            from app.modules.health_isf.scheduling import driver_has_schedule_conflict

            if (
                bool(preferred.is_active)
                and bool(preferred.is_online)
                and str(preferred.availability_state or "").lower() == "available"
                and _coerce_driver_status(preferred.status) == DriverStatus.AVAILABLE
                and _driver_active_workload_count(db, preferred.id) == 0
                and not _is_driver_busy(preferred.status)
                and not driver_has_schedule_conflict(db, str(preferred.id), ride)
            ):
                return [
                    {
                        "driver": preferred,
                        "score": 1.0,
                        "breakdown": {"preferred_same_driver": True},
                    }
                ]

    candidates = evaluate_dispatch_candidates(
        db,
        organization_id=organization_id,
        ride=ride,
        exclude_driver_ids=exclude_driver_ids,
    )
    if candidates:
        return candidates

    exclude_ids = {str(x) for x in (exclude_driver_ids or set()) if x}
    rows = (
        db.query(HealthISFDriver)
        .filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.is_active == True,
        )
        .order_by(desc(HealthISFDriver.updated_at), HealthISFDriver.id.asc())
        .all()
    )
    now_ts = now()
    fallback: list[dict[str, Any]] = []
    for driver in rows:
        if str(driver.id) in exclude_ids:
            continue
        if _driver_active_workload_count(db, driver.id) > 0:
            continue
        if _is_driver_busy(driver.status):
            continue
        if not bool(driver.is_online):
            continue
        if str(driver.availability_state or "").lower() != "available":
            continue
        if _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
            continue
        from app.modules.health_isf.scheduling import driver_has_schedule_conflict

        if driver_has_schedule_conflict(db, str(driver.id), ride):
            continue
        heartbeat_age = _seconds_since(driver.last_seen_at, now_ts)
        fallback.append(
            {
                "driver": driver,
                "score": round(0.5 + (1.0 / (1.0 + heartbeat_age / 120.0)), 6),
                "breakdown": {
                    "advance_scheduling_fallback": True,
                    "heartbeat_age_seconds": heartbeat_age,
                    "mobile_dispatch_ready": _driver_mobile_dispatch_ready(driver),
                    "status_dispatch_ready": _driver_status_dispatch_ready(driver),
                },
            }
        )
    fallback.sort(
        key=lambda item: (
            -float(item["score"]),
            _normalized_timestamp_token(getattr(item["driver"], "updated_at", None)),
            str(item["driver"].id),
        )
    )
    return fallback


def assign_driver_to_scheduled_ride(
    db: Session,
    *,
    ride_id: str,
    driver_id: str,
    actor_user_id: Optional[str] = None,
    score: Optional[float] = None,
    score_breakdown: Optional[dict[str, Any]] = None,
) -> tuple[HealthISFRide, HealthISFDispatchAssignment]:
    """Reserve a future ride with a driver without entering immediate active workload."""
    from app.helpers import uuid4
    from app.modules.health_isf.service import (
        _coerce_driver_status,
        _commit_or_rollback,
        _driver_active_workload_count,
        _next_assignment_attempt_index,
        _set_driver_status,
        get_driver_by_id,
        get_ride_by_id,
        now,
    )
    from app.modules.health_isf.scheduling import driver_has_schedule_conflict

    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        raise ValueError("Driver not found")
    if str(ride.organization_id) != str(driver.organization_id):
        raise ValueError("Driver must belong to the same organization as ride")
    if _driver_active_workload_count(db, driver.id) > 0:
        raise ValueError("Driver has an immediate active ride")
    if driver_has_schedule_conflict(db, str(driver.id), ride, exclude_ride_ids={str(ride.id)}):
        raise ValueError("Driver has a conflicting scheduled reservation")

    existing = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state.in_(list(SCHEDULED_DISPATCH_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    if existing and str(existing.driver_id or "") == str(driver.id):
        db.refresh(ride)
        return ride, existing

    now_ts = now()
    ride.driver_id = driver.id
    ride.assigned_by_user_id = actor_user_id
    if str(getattr(ride, "lifecycle_state", "") or ride.status) not in {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
    }:
        ride.lifecycle_state = "scheduled"
        ride.status = RideStatus.PENDING
    ride.updated_at = now_ts
    db.add(ride)

    if _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
        _set_driver_status(db, driver, DriverStatus.AVAILABLE)
    driver.availability_state = "available"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now_ts
    driver.updated_at = now_ts

    assignment = HealthISFDispatchAssignment(
        id=uuid4(),
        organization_id=ride.organization_id,
        ride_id=ride.id,
        driver_id=driver.id,
        assignment_state=DispatchAssignmentState.SCHEDULED_OFFERED.value,
        attempt_index=_next_assignment_attempt_index(db, ride.id),
        timeout_seconds=SCHEDULED_OFFER_TIMEOUT_SECONDS,
        queued_at=now_ts,
        search_started_at=now_ts,
        offered_at=now_ts,
        offer_expires_at=now_ts + timedelta(seconds=SCHEDULED_OFFER_TIMEOUT_SECONDS),
        score=float(score) if score is not None else None,
        score_breakdown_json=json.dumps(score_breakdown or {}),
        metadata_json=json.dumps({"stage": "advance_scheduling", "reservation": True}),
        created_by_user_id=actor_user_id,
        created_at=now_ts,
        updated_at=now_ts,
    )
    db.add(assignment)
    _commit_or_rollback(db)
    db.refresh(ride)
    db.refresh(assignment)
    return ride, assignment


def run_advance_scheduling_for_ride(
    db: Session,
    *,
    ride_id: str,
    organization_id: str,
    actor_user_id: Optional[str] = None,
    request_id: Optional[str] = None,
    preferred_driver_id: Optional[str] = None,
) -> dict[str, Any]:
    from app.modules.health_isf.service import (
        _commit_or_rollback,
        _latest_assignment_for_ride,
        _ride_is_terminal,
        get_ride_by_id,
        is_operational_excluded_ride,
    )

    ride = get_ride_by_id(db, ride_id)
    if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
        return {"ride": ride, "offer": None, "selected_driver": None, "mode": "skipped"}

    if is_immediate_ride(ride) and is_dispatch_eligible(ride):
        return {"ride": ride, "offer": None, "selected_driver": None, "mode": "immediate_ride"}

    existing = _latest_assignment_for_ride(db, ride.id)
    if existing and is_scheduled_assignment_state(existing.assignment_state):
        from app.modules.health_isf.service import get_driver_by_id

        return {
            "ride": ride,
            "offer": existing,
            "selected_driver": get_driver_by_id(db, existing.driver_id) if existing.driver_id else None,
            "mode": "existing_scheduled_offer",
        }

    if existing and str(existing.assignment_state or "") in {
        DispatchAssignmentState.OFFERED.value,
        DispatchAssignmentState.ACCEPTED.value,
        DispatchAssignmentState.ASSIGNED.value,
    }:
        return {"ride": ride, "offer": existing, "selected_driver": None, "mode": "already_assigned"}

    _record_scheduled_audit(
        db,
        ride_id=str(ride.id),
        action="scheduled_dispatch_requested",
        request_id=request_id,
        actor_user_id=actor_user_id,
    )
    _commit_or_rollback(db)

    candidates = evaluate_advance_scheduling_candidates(
        db,
        organization_id=organization_id,
        ride=ride,
        preferred_driver_id=preferred_driver_id,
    )
    if not candidates:
        _record_scheduled_audit(
            db,
            ride_id=str(ride.id),
            action="scheduled_dispatch_skipped",
            request_id=request_id,
            actor_user_id=actor_user_id,
            note="no_eligible_driver",
        )
        _commit_or_rollback(db)
        return {"ride": ride, "offer": None, "selected_driver": None, "mode": "no_candidates"}

    selected = candidates[0]
    driver = selected["driver"]
    _record_scheduled_audit(
        db,
        ride_id=str(ride.id),
        action="scheduled_driver_selected",
        request_id=request_id,
        actor_user_id=actor_user_id,
        driver_id=str(driver.id),
        note=json.dumps({"score": selected.get("score"), "eligible_count": len(candidates)})[:512],
    )
    _commit_or_rollback(db)

    ride, offer = assign_driver_to_scheduled_ride(
        db,
        ride_id=str(ride.id),
        driver_id=str(driver.id),
        actor_user_id=actor_user_id,
        score=float(selected.get("score") or 0.0),
        score_breakdown=dict(selected.get("breakdown") or {}),
    )
    _record_scheduled_audit(
        db,
        ride_id=str(ride.id),
        action="scheduled_offer_created",
        request_id=request_id,
        actor_user_id=actor_user_id,
        driver_id=str(driver.id),
        assignment_id=str(offer.id),
    )
    _commit_or_rollback(db)
    return {
        "ride": ride,
        "offer": offer,
        "selected_driver": driver,
        "mode": "scheduled_offered",
    }


def run_advance_scheduling_for_customer_request(
    db: Session,
    *,
    request_id: str,
    organization_id: str,
    actor_user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    from app.modules.health_isf.service import get_customer_ride_request_by_id

    request_obj = get_customer_ride_request_by_id(db, request_id)
    if not request_obj:
        return []
    rides = _rides_for_customer_request(db, request_obj)
    rides.sort(
        key=lambda row: (
            0 if str(getattr(row, "trip_leg", "") or "") == "outbound" else 1,
            str(getattr(row, "pickup_time", "") or ""),
        )
    )
    preferred_driver_id: Optional[str] = None
    outcomes: list[dict[str, Any]] = []
    same_driver = any(bool(getattr(r, "same_driver_preference", False)) for r in rides)
    for ride in rides:
        if str(getattr(ride, "trip_leg", "") or "") == "return" and bool(getattr(ride, "call_when_ready", False)):
            continue
        result = run_advance_scheduling_for_ride(
            db,
            ride_id=str(ride.id),
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            request_id=str(request_obj.id),
            preferred_driver_id=preferred_driver_id if same_driver else None,
        )
        outcomes.append(result)
        if same_driver and result.get("selected_driver"):
            preferred_driver_id = str(result["selected_driver"].id)
    return outcomes


def accept_scheduled_ride(
    db: Session,
    *,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
) -> HealthISFDispatchAssignment:
    from app.modules.health_isf.service import (
        _commit_or_rollback,
        _set_driver_status,
        get_driver_by_id,
        get_ride_by_id,
        now,
        sync_customer_request_from_ride,
    )

    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")
    if str(ride.driver_id or "") != str(driver_id):
        raise ValueError("Ride is not reserved for this driver")

    offer = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.SCHEDULED_OFFERED.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    if not offer:
        accepted = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride.id,
                HealthISFDispatchAssignment.driver_id == driver_id,
                HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
            )
            .first()
        )
        if accepted:
            return accepted
        raise ValueError("No scheduled offer found for this ride")

    now_ts = now()
    offer.assignment_state = DispatchAssignmentState.SCHEDULED_ACCEPTED.value
    offer.accepted_at = now_ts
    offer.assigned_at = offer.assigned_at or now_ts
    offer.updated_at = now_ts
    ride.lifecycle_state = "scheduled"
    ride.status = RideStatus.PENDING
    ride.updated_at = now_ts

    driver = get_driver_by_id(db, driver_id)
    if driver:
        _set_driver_status(db, driver, DriverStatus.AVAILABLE)
        driver.availability_state = "available"
        driver.is_online = True
        driver.auth_state = "active"
        driver.last_seen_at = now_ts

    _record_scheduled_audit(
        db,
        ride_id=str(ride.id),
        action="scheduled_offer_accepted",
        actor_user_id=actor_user_id,
        driver_id=str(driver_id),
        assignment_id=str(offer.id),
    )
    _record_scheduled_audit(
        db,
        ride_id=str(ride.id),
        action="scheduled_reservation_confirmed",
        actor_user_id=actor_user_id,
        driver_id=str(driver_id),
        assignment_id=str(offer.id),
    )
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)
    db.refresh(offer)
    return offer


def serialize_upcoming_schedule_entry(
    db: Session,
    *,
    assignment: HealthISFDispatchAssignment,
    ride: HealthISFRide,
) -> dict[str, Any]:
    from app.modules.health_isf.service import _as_utc_datetime

    pickup = getattr(ride, "pickup_time", None)
    arrival = getattr(ride, "appointment_time", None)
    return_pickup = None
    return_time = None
    group_id = str(getattr(ride, "round_trip_group_id", "") or "")
    if group_id:
        return_leg = (
            db.query(HealthISFRide)
            .filter(
                HealthISFRide.round_trip_group_id == group_id,
                HealthISFRide.trip_leg == "return",
            )
            .first()
        )
        if return_leg:
            return_pickup = getattr(return_leg, "pickup_time", None)
            return_time = return_pickup or getattr(return_leg, "appointment_time", None)

    state = str(assignment.assignment_state or "")
    return {
        "ride_id": str(ride.id),
        "assignment_id": str(assignment.id),
        "assignment_state": state,
        "trip_leg": str(getattr(ride, "trip_leg", "") or "one_way"),
        "round_trip_group_id": group_id or None,
        "rider_name": str(ride.passenger_name or ""),
        "rider_phone": str(ride.passenger_phone or ""),
        "pickup_address": str(ride.pickup_address or ""),
        "dropoff_address": str(ride.dropoff_address or ""),
        "service_date": pickup.date().isoformat() if pickup else None,
        "pickup_time": _as_utc_datetime(pickup).isoformat() if pickup else None,
        "arrival_time": _as_utc_datetime(arrival).isoformat() if arrival else None,
        "return_pickup_time": _as_utc_datetime(return_time).isoformat() if return_time else None,
        "scheduling_summary": format_scheduling_summary(ride),
        "reminder_status": "pending" if state == DispatchAssignmentState.SCHEDULED_ACCEPTED.value else "offer_pending",
        "can_accept": state == DispatchAssignmentState.SCHEDULED_OFFERED.value,
        "dispatch_eligible_at": (
            _as_utc_datetime(getattr(ride, "dispatch_eligible_at", None)).isoformat()
            if getattr(ride, "dispatch_eligible_at", None)
            else None
        ),
    }


def list_upcoming_schedule_for_driver(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> list[dict[str, Any]]:
    from app.modules.health_isf.service import (
        _ride_is_terminal,
        get_ride_by_id,
        is_operational_excluded_ride,
    )

    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(SCHEDULED_DISPATCH_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(30)
        .all()
    )
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        ride = get_ride_by_id(db, str(row.ride_id or ""))
        if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        if is_dispatch_eligible(ride):
            continue
        ride_id = str(ride.id)
        if ride_id in seen:
            continue
        seen.add(ride_id)
        entries.append(serialize_upcoming_schedule_entry(db, assignment=row, ride=ride))
    entries.sort(key=lambda item: str(item.get("pickup_time") or ""))
    return entries


def list_scheduled_offers_for_driver(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> list[dict[str, Any]]:
    return [
        item
        for item in list_upcoming_schedule_for_driver(
            db,
            organization_id=organization_id,
            driver_id=driver_id,
        )
        if item.get("can_accept")
    ]


def promote_scheduled_reservations(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Activate accepted future reservations when inside the dispatch window."""
    from app.modules.health_isf.ride_execution_engine import RideLifecycleManager
    from app.modules.health_isf.service import (
        _commit_or_rollback,
        get_ride_by_id,
        now,
    )

    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
        )
        .limit(200)
        .all()
    )
    activated: list[dict[str, Any]] = []
    now_ts = now()
    for row in rows:
        ride = get_ride_by_id(db, str(row.ride_id or ""))
        if not ride or not is_dispatch_eligible(ride):
            continue
        row.assignment_state = DispatchAssignmentState.ACCEPTED.value
        row.accepted_at = row.accepted_at or now_ts
        row.updated_at = now_ts
        RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=RideStatus.QUEUED.value,
            action_type="scheduled_ride_activated",
            actor_user_id=actor_user_id,
            note="Scheduled reservation entered dispatch activation window",
        )
        ride.lifecycle_state = RideStatus.QUEUED.value
        ride.status = RideStatus.PENDING
        ride.updated_at = now_ts
        _record_scheduled_audit(
            db,
            ride_id=str(ride.id),
            action="scheduled_ride_activated",
            actor_user_id=actor_user_id,
            driver_id=str(row.driver_id or ""),
            assignment_id=str(row.id),
        )
        activated.append({"ride_id": str(ride.id), "assignment_id": str(row.id)})
    if activated:
        _commit_or_rollback(db)
    return activated


def send_scheduled_reminders(
    db: Session,
    *,
    organization_id: str,
    lead_minutes: int = 1440,
) -> list[dict[str, Any]]:
    """Emit reminder audit events for accepted reservations approaching service time."""
    from app.modules.health_isf.service import _commit_or_rollback, get_ride_by_id, now

    now_ts = now()
    horizon = now_ts + timedelta(minutes=max(30, int(lead_minutes)))
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
        )
        .limit(200)
        .all()
    )
    sent: list[dict[str, Any]] = []
    for row in rows:
        ride = get_ride_by_id(db, str(row.ride_id or ""))
        if not ride:
            continue
        pickup = getattr(ride, "pickup_time", None)
        if not pickup:
            continue
        if pickup.tzinfo is None:
            pickup = pickup.replace(tzinfo=timezone.utc)
        else:
            pickup = pickup.astimezone(timezone.utc)
        if pickup <= now_ts or pickup > horizon:
            continue
        meta = {}
        raw = getattr(row, "metadata_json", None)
        if raw:
            try:
                meta = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                meta = {}
        if meta.get("reminder_sent_at"):
            continue
        _record_scheduled_audit(
            db,
            ride_id=str(ride.id),
            action="scheduled_reminder_sent",
            driver_id=str(row.driver_id or ""),
            assignment_id=str(row.id),
            note=f"pickup_at={pickup.isoformat()}",
        )
        meta["reminder_sent_at"] = now_ts.isoformat()
        row.metadata_json = json.dumps(meta)
        row.updated_at = now_ts
        sent.append({"ride_id": str(ride.id), "assignment_id": str(row.id)})
    if sent:
        _commit_or_rollback(db)
    return sent


def sweep_pending_advance_scheduling(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: Optional[str] = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Offer advance scheduling for future rides that have no reservation yet."""
    from app.modules.health_isf.service import (
        _latest_assignment_for_ride,
        _ride_is_terminal,
        get_ride_by_id,
        is_operational_excluded_ride,
    )

    rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id.is_(None),
        )
        .order_by(HealthISFRide.pickup_time.asc())
        .limit(max(1, int(limit)))
        .all()
    )
    outcomes: list[dict[str, Any]] = []
    for ride in rows:
        if _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        if is_immediate_ride(ride) and is_dispatch_eligible(ride):
            continue
        if not is_immediate_ride(ride) or not is_dispatch_eligible(ride):
            assignment = _latest_assignment_for_ride(db, ride.id)
            if assignment and str(getattr(assignment, "assignment_state", "") or "") in {
                DispatchAssignmentState.SCHEDULED_OFFERED.value,
                DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
                DispatchAssignmentState.OFFERED.value,
                DispatchAssignmentState.ACCEPTED.value,
            }:
                continue
            result = run_advance_scheduling_for_ride(
                db,
                ride_id=str(ride.id),
                organization_id=organization_id,
                actor_user_id=actor_user_id,
            )
            outcomes.append(result)
    return outcomes


def assignment_is_upcoming_reservation(
    ride: Optional[HealthISFRide],
    assignment: Optional[HealthISFDispatchAssignment],
) -> bool:
    if not ride or not assignment:
        return False
    if not is_scheduled_assignment_state(assignment.assignment_state):
        return False
    if is_dispatch_eligible(ride):
        return False
    return is_protected_scheduled_reservation(ride, assignment)
