"""Read-only, driver-scoped queries for Driver Mobile polling endpoints."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.modules.health_isf.driver_request_timing_log import DriverReadStageTimer
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager

_DRIVER_ASSIGNMENT_ROW_LIMIT = 30
_DRIVER_RIDE_ROW_LIMIT = 30


def _load_rides_by_ids(db: Session, ride_ids: list[str]) -> dict[str, HealthISFRide]:
    if not ride_ids:
        return {}
    unique_ids = list(dict.fromkeys(str(rid) for rid in ride_ids if rid))
    if not unique_ids:
        return {}
    rows = db.query(HealthISFRide).filter(HealthISFRide.id.in_(unique_ids)).all()
    return {str(row.id): row for row in rows}


def _offer_is_readable(
    assignment: HealthISFDispatchAssignment,
    *,
    now_ts,
    as_utc_datetime,
) -> bool:
    state = str(assignment.assignment_state or "").lower()
    if state not in {
        DispatchAssignmentState.OFFERED.value,
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
    }:
        return False
    if assignment.offer_expires_at and as_utc_datetime(assignment.offer_expires_at) < as_utc_datetime(now_ts):
        return False
    return True


def build_driver_mobile_read_snapshot(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    timer: DriverReadStageTimer | None = None,
    include_assigned_limit: int = 0,
) -> dict[str, Any]:
    """Build one driver-scoped workflow snapshot without org-wide maintenance or writes."""
    from app.modules.health_isf import service

    stages = timer or DriverReadStageTimer()

    with stages.stage("driver_lookup"):
        driver, organization_id = service._ensure_driver_organization_scope(
            db,
            driver_id=driver_id,
            organization_id=organization_id,
            persist_missing=False,
        )

    with stages.stage("assignment_query"):
        assignment_rows = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.organization_id == organization_id,
                HealthISFDispatchAssignment.driver_id == driver_id,
                HealthISFDispatchAssignment.assignment_state.in_(
                    list(service.DRIVER_APP_ASSIGNMENT_STATES)
                    + [
                        DispatchAssignmentState.OFFERED.value,
                        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                        DispatchAssignmentState.AWAITING_APPROVAL.value,
                    ]
                ),
            )
            .order_by(
                desc(HealthISFDispatchAssignment.updated_at),
                desc(HealthISFDispatchAssignment.created_at),
            )
            .limit(_DRIVER_ASSIGNMENT_ROW_LIMIT)
            .all()
        )

    ride_ids = [str(row.ride_id) for row in assignment_rows if row.ride_id]
    with stages.stage("ride_batch_load"):
        rides_by_id = _load_rides_by_ids(db, ride_ids)

    now_ts = service.now()
    terminal_ride_states = {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
    }

    with stages.stage("workspace_assembly"):
        ranked_candidates: list[tuple[tuple[int, str], HealthISFDispatchAssignment, HealthISFRide]] = []
        readable_offers: list[tuple[HealthISFDispatchAssignment, HealthISFRide]] = []

        for row in assignment_rows:
            ride = rides_by_id.get(str(row.ride_id or ""))
            if not ride or not service._ride_is_driver_mobile_eligible(ride):
                continue
            if service.is_operational_excluded_ride(ride):
                continue
            if _offer_is_readable(row, now_ts=now_ts, as_utc_datetime=service._as_utc_datetime):
                readable_offers.append((row, ride))
            if not service._driver_ride_is_active_for_driver_app(
                db,
                ride=ride,
                driver_id=driver_id,
                assignment=row,
            ):
                continue
            ranked_candidates.append(
                (service._rank_driver_assignment_candidate(row, ride), row, ride)
            )

        assignment: Optional[HealthISFDispatchAssignment] = None
        ride: Optional[HealthISFRide] = None

        if ranked_candidates:
            ranked_candidates.sort(key=lambda item: item[0], reverse=True)
            non_excluded = [item for item in ranked_candidates if not service.is_operational_excluded_ride(item[2])]
            if non_excluded:
                assignment, ride = non_excluded[0][1], non_excluded[0][2]

        active_offer: Optional[HealthISFDispatchAssignment] = None
        if readable_offers:
            readable_offers.sort(
                key=lambda item: (
                    service._assignment_recency_token(item[0]),
                    service._normalized_timestamp_token(item[1].requested_at),
                ),
                reverse=True,
            )
            active_offer = readable_offers[0][0]
            if not ride:
                offer_ride = readable_offers[0][1]
                op = service.evaluate_driver_ride_operational_state(
                    db,
                    ride=offer_ride,
                    driver_id=driver_id,
                    assignment=active_offer,
                )
                if op.is_active or op.has_active_offer:
                    ride = offer_ride
                    assignment = active_offer

        if not ride:
            fallback = (
                db.query(HealthISFRide)
                .filter(
                    HealthISFRide.organization_id == organization_id,
                    HealthISFRide.driver_id == driver_id,
                )
                .order_by(desc(HealthISFRide.updated_at), desc(HealthISFRide.requested_at))
                .limit(1)
                .first()
            )
            if fallback and service._ride_is_driver_mobile_eligible(fallback):
                assignment = service._authoritative_assignment_for_ride(db, fallback, driver_id=driver_id)
                op = service.evaluate_driver_ride_operational_state(
                    db,
                    ride=fallback,
                    driver_id=driver_id,
                    assignment=assignment,
                )
                if op.is_active or op.has_active_offer:
                    ride = fallback

        if ride:
            assignment = assignment or service._authoritative_assignment_for_ride(db, ride, driver_id=driver_id)
            op = service.evaluate_driver_ride_operational_state(
                db,
                ride=ride,
                driver_id=driver_id,
                assignment=assignment,
            )
            ride_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            if ride_state in terminal_ride_states or not (op.is_active or op.has_active_offer):
                ride = None
                assignment = None

        provider_name = ""
        if ride and ride.provider_id:
            provider = service.get_provider_by_id(db, str(ride.provider_id))
            if provider:
                provider_name = str(
                    getattr(provider, "name", None) or getattr(provider, "provider_name", None) or ""
                )

        assignment_state = ""
        active_for_driver = False
        eta_minutes = None
        if ride:
            op = service.evaluate_driver_ride_operational_state(
                db,
                ride=ride,
                driver_id=driver_id,
                assignment=assignment,
            )
            active_for_driver = op.is_active or op.has_active_offer
            assignment_state = op.effective_assignment_state or (
                str(assignment.assignment_state) if assignment and assignment.assignment_state else ""
            )
            if not assignment_state:
                assignment_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            eta_minutes = service._estimated_eta_minutes(ride)

        countdown = None
        if assignment and assignment.offer_expires_at:
            countdown = max(
                0,
                int(
                    (
                        service._as_utc_datetime(assignment.offer_expires_at)
                        - service._as_utc_datetime(now_ts)
                    ).total_seconds()
                ),
            )

        stale_heartbeat = False
        if driver.last_seen_at:
            stale_heartbeat = (
                service._as_utc_datetime(now_ts) - service._as_utc_datetime(driver.last_seen_at)
            ).total_seconds() > 300
        safety_status = "ok"
        if stale_heartbeat:
            safety_status = "reconnect_required"
        if str(driver.availability_state or "").lower() == "offline":
            safety_status = "offline"

    with stages.stage("runtime_status"):
        active_session = service._get_driver_active_session(db, driver_id)
        session_valid = bool(
            active_session
            and active_session.session_state == "active"
            and active_session.revoked_at is None
            and service._as_utc_datetime(active_session.expires_at) >= service._as_utc_datetime(now_ts)
        )
        runtime = {"session_valid": session_valid}

    assigned_rides: list[HealthISFRide] = []
    if include_assigned_limit > 0:
        with stages.stage("assigned_rides_query"):
            assigned_rides = list_driver_assigned_rides_readonly(
                db,
                organization_id=organization_id,
                driver_id=driver_id,
                limit=include_assigned_limit,
                preloaded_assignments=assignment_rows,
                preloaded_rides=rides_by_id,
            )

    return {
        "driver": driver,
        "organization_id": organization_id,
        "driver_id": driver_id,
        "ride": ride if active_for_driver else None,
        "assignment": assignment if active_for_driver else None,
        "active_offer": active_offer,
        "has_active_ride": bool(ride and active_for_driver),
        "assignment_state": assignment_state,
        "driver_name": str(getattr(driver, "name", None) or ""),
        "provider_name": provider_name,
        "eta_minutes": eta_minutes,
        "countdown": countdown,
        "safety_status": safety_status,
        "reconnect_safe": bool(runtime and runtime.get("session_valid")),
        "timeline_states": [
            "assigned",
            "en_route_pickup",
            "arrived_pickup",
            "rider_loaded",
            "trip_in_progress",
            "arrived_destination",
            "completed",
        ],
        "assigned_rides": assigned_rides,
        "timing_stages_ms": dict(stages.stages),
    }


def list_driver_assigned_rides_readonly(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    limit: int = 15,
    preloaded_assignments: list[HealthISFDispatchAssignment] | None = None,
    preloaded_rides: dict[str, HealthISFRide] | None = None,
) -> list[HealthISFRide]:
    """Return capped assigned rides for one driver without maintenance side effects."""
    from app.modules.health_isf import service

    safe_limit = max(1, min(int(limit or 15), 100))
    _, organization_id = service._ensure_driver_organization_scope(
        db,
        driver_id=driver_id,
        organization_id=organization_id,
        persist_missing=False,
    )

    assignment_rows = preloaded_assignments
    if assignment_rows is None:
        assignment_rows = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.organization_id == organization_id,
                HealthISFDispatchAssignment.driver_id == driver_id,
                HealthISFDispatchAssignment.assignment_state.in_(list(service.DRIVER_APP_ASSIGNMENT_STATES)),
            )
            .order_by(
                desc(HealthISFDispatchAssignment.updated_at),
                desc(HealthISFDispatchAssignment.created_at),
            )
            .limit(_DRIVER_ASSIGNMENT_ROW_LIMIT)
            .all()
        )

    ride_ids = [str(row.ride_id) for row in assignment_rows if row.ride_id]
    rides_by_id = preloaded_rides if preloaded_rides is not None else _load_rides_by_ids(db, ride_ids)

    merged: dict[str, HealthISFRide] = {}
    for assignment in assignment_rows:
        ride = rides_by_id.get(str(assignment.ride_id or ""))
        if not ride or not service._ride_is_driver_mobile_eligible(ride):
            continue
        if not service._driver_ride_is_active_for_driver_app(
            db,
            ride=ride,
            driver_id=driver_id,
            assignment=assignment,
        ):
            continue
        merged[str(ride.id)] = ride

    bound_rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id == driver_id,
        )
        .order_by(desc(HealthISFRide.requested_at), desc(HealthISFRide.updated_at))
        .limit(min(safe_limit, _DRIVER_RIDE_ROW_LIMIT))
        .all()
    )
    for ride in bound_rows:
        if service._is_ai_proof_ride(ride) or not service._ride_is_driver_mobile_eligible(ride):
            continue
        assignment = service._authoritative_assignment_for_ride(db, ride, driver_id=driver_id)
        if not service._driver_ride_is_active_for_driver_app(
            db,
            ride=ride,
            driver_id=driver_id,
            assignment=assignment,
        ):
            continue
        merged[str(ride.id)] = ride

    scheduled_rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id == driver_id,
            HealthISFRide.lifecycle_state == "scheduled",
        )
        .order_by(HealthISFRide.appointment_time.asc(), HealthISFRide.pickup_time.asc())
        .limit(safe_limit)
        .all()
    )
    for ride in scheduled_rows:
        if (
            service._is_ai_proof_ride(ride)
            or service.is_operational_excluded_ride(ride)
            or service._ride_is_terminal(ride)
        ):
            continue
        merged[str(ride.id)] = ride

    active_rows = list(merged.values())
    active_rows.sort(key=lambda row: service._normalized_timestamp_token(row.requested_at), reverse=True)
    non_proof = [row for row in active_rows if not service._is_ai_proof_ride(row)]
    return (non_proof or active_rows)[:safe_limit]
