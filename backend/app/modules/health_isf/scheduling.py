"""Rider scheduling: round-trip legs, recurrence, dispatch windows, protected reservations."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from app.modules.health_isf.models import (
    CustomerRequestStatus,
    HealthISFCustomerRideRequest,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager

DISPATCH_WINDOW_MINUTES = int(os.getenv("HEALTH_ISF_DISPATCH_WINDOW_MINUTES", "60"))
TRIP_DURATION_BUFFER_MINUTES = 90
WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
WEEKDAY_INDEX = {key: idx for idx, key in enumerate(WEEKDAY_KEYS)}


def _coerce_utc(ts: Optional[datetime]) -> Optional[datetime]:
    if ts is None:
        return None
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _now() -> datetime:
    from app.modules.health_isf.service import now

    return now()


def compute_dispatch_eligible_at(
    *,
    pickup_time: Optional[datetime],
    arrival_time: Optional[datetime],
) -> Optional[datetime]:
    """When a ride becomes eligible for dispatch offers (default: 60 min before arrival)."""
    anchor = _coerce_utc(arrival_time) or _coerce_utc(pickup_time)
    if not anchor:
        return None
    return anchor - timedelta(minutes=DISPATCH_WINDOW_MINUTES)


def is_immediate_ride(ride: HealthISFRide) -> bool:
    eligible_at = _coerce_utc(getattr(ride, "dispatch_eligible_at", None))
    if eligible_at is None:
        pickup = _coerce_utc(getattr(ride, "pickup_time", None))
        arrival = _coerce_utc(getattr(ride, "appointment_time", None))
        eligible_at = compute_dispatch_eligible_at(pickup_time=pickup, arrival_time=arrival)
    if eligible_at is None:
        return True
    return eligible_at <= _now() + timedelta(minutes=5)


def is_dispatch_eligible(ride: HealthISFRide, *, at: Optional[datetime] = None) -> bool:
    """Return True when ride may enter auto-assign / driver offer pool."""
    if bool(getattr(ride, "call_when_ready", False)) and str(getattr(ride, "trip_leg", "") or "") == "return":
        activated = _coerce_utc(getattr(ride, "pickup_time", None))
        if not activated:
            return False

    eligible_at = _coerce_utc(getattr(ride, "dispatch_eligible_at", None))
    if eligible_at is None:
        pickup = _coerce_utc(getattr(ride, "pickup_time", None))
        arrival = _coerce_utc(getattr(ride, "appointment_time", None))
        eligible_at = compute_dispatch_eligible_at(pickup_time=pickup, arrival_time=arrival)
    if eligible_at is None:
        return True
    return _coerce_utc(at or _now()) >= eligible_at


def is_protected_scheduled_reservation(
    ride: Optional[HealthISFRide],
    assignment: Any = None,
) -> bool:
    """Future-bound assignment that must not be superseded by unrelated dispatch."""
    if not ride:
        return False
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle in {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
    }:
        return False
    if is_dispatch_eligible(ride):
        return False
    pickup = _coerce_utc(getattr(ride, "pickup_time", None))
    arrival = _coerce_utc(getattr(ride, "appointment_time", None))
    anchor = arrival or pickup
    if anchor and anchor <= _now():
        return False
    if lifecycle == "scheduled":
        return True
    if anchor and anchor > _now() + timedelta(minutes=5):
        return True
    if assignment and str(getattr(assignment, "driver_id", "") or "") and str(ride.driver_id or ""):
        if not is_dispatch_eligible(ride):
            return True
    return False


def ride_time_window(ride: HealthISFRide) -> tuple[datetime, datetime]:
    """Return [start, end) window for overlap checks."""
    start = _coerce_utc(getattr(ride, "pickup_time", None)) or _coerce_utc(getattr(ride, "appointment_time", None))
    if not start:
        start = _coerce_utc(getattr(ride, "requested_at", None)) or _now()
    duration = int(getattr(ride, "estimated_duration_minutes", None) or TRIP_DURATION_BUFFER_MINUTES)
    end = _coerce_utc(getattr(ride, "appointment_time", None))
    if end and end > start:
        end = end + timedelta(minutes=max(30, duration // 2))
    else:
        end = start + timedelta(minutes=duration)
    return start, end


def rides_time_overlap(ride_a: HealthISFRide, ride_b: HealthISFRide) -> bool:
    a0, a1 = ride_time_window(ride_a)
    b0, b1 = ride_time_window(ride_b)
    return a0 < b1 and b0 < a1


def format_scheduling_summary(ride: HealthISFRide) -> str:
    leg = str(getattr(ride, "trip_leg", "") or "one_way")
    pickup = _coerce_utc(getattr(ride, "pickup_time", None))
    arrival = _coerce_utc(getattr(ride, "appointment_time", None))
    parts: list[str] = []
    if leg != "one_way":
        parts.append(leg.replace("_", " ").title())
    if pickup:
        parts.append(f"Pickup {pickup.strftime('%Y-%m-%d %H:%M')} UTC")
    if arrival:
        parts.append(f"Arrival {arrival.strftime('%Y-%m-%d %H:%M')} UTC")
    if bool(getattr(ride, "call_when_ready", False)):
        parts.append("Return: Call when ready")
    elif str(getattr(ride, "return_pickup_type", "") or "") == "call_when_ready":
        parts.append("Return: Call when ready")
    eligible = _coerce_utc(getattr(ride, "dispatch_eligible_at", None))
    if eligible and not is_dispatch_eligible(ride):
        parts.append(f"Dispatch opens {eligible.strftime('%Y-%m-%d %H:%M')} UTC")
    group = str(getattr(ride, "round_trip_group_id", "") or "")
    if group:
        parts.append(f"Group {group[:8]}")
    return " · ".join(parts) if parts else "Immediate ride"


def expand_weekly_instances(
    service_date: date,
    end_date: date,
    weekdays: list[str],
) -> list[date]:
    normalized = {str(d).lower()[:3] for d in weekdays if d}
    if not normalized:
        return [service_date]
    if end_date < service_date:
        return []
    out: list[date] = []
    cursor = service_date
    while cursor <= end_date:
        key = WEEKDAY_KEYS[cursor.weekday()]
        if key in normalized:
            out.append(cursor)
        cursor += timedelta(days=1)
    return out


def apply_scheduling_fields_to_ride(
    ride: HealthISFRide,
    *,
    trip_leg: str = "one_way",
    round_trip_group_id: Optional[str] = None,
    scheduling_series_id: Optional[str] = None,
    pickup_time: Optional[datetime] = None,
    arrival_time: Optional[datetime] = None,
    return_pickup_type: Optional[str] = None,
    same_driver_preference: bool = False,
    call_when_ready: bool = False,
) -> None:
    ride.trip_leg = trip_leg
    ride.round_trip_group_id = round_trip_group_id
    ride.scheduling_series_id = scheduling_series_id
    ride.pickup_time = _coerce_utc(pickup_time)
    if arrival_time is not None:
        ride.appointment_time = _coerce_utc(arrival_time)
    ride.return_pickup_type = return_pickup_type
    ride.same_driver_preference = bool(same_driver_preference)
    ride.call_when_ready = bool(call_when_ready)
    if call_when_ready and trip_leg == "return":
        ride.dispatch_eligible_at = None
        ride.pickup_time = None
    else:
        ride.dispatch_eligible_at = compute_dispatch_eligible_at(
            pickup_time=ride.pickup_time,
            arrival_time=ride.appointment_time,
        )
    if ride.dispatch_eligible_at and not is_dispatch_eligible(ride):
        ride.lifecycle_state = "scheduled"
        ride.status = RideStatus.PENDING


def promote_dispatch_eligible_rides(db: Session, *, organization_id: str) -> int:
    """Transition scheduled rides into queued when inside dispatch window."""
    from app.modules.health_isf.service import _commit_or_rollback

    promoted = 0
    rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.lifecycle_state == "scheduled",
        )
        .limit(500)
        .all()
    )
    for ride in rows:
        if not is_dispatch_eligible(ride):
            continue
        try:
            RideLifecycleManager.transition_ride(
                db,
                ride,
                target_state=RideStatus.QUEUED.value,
                action_type="dispatch_window_opened",
                note="Ride entered dispatch eligibility window",
            )
            promoted += 1
        except Exception:
            ride.lifecycle_state = RideStatus.QUEUED.value
            ride.status = RideStatus.PENDING.value
            promoted += 1
    if promoted:
        _commit_or_rollback(db)
    return promoted


def driver_has_schedule_conflict(
    db: Session,
    driver_id: str,
    candidate_ride: HealthISFRide,
    *,
    exclude_ride_ids: Optional[set[str]] = None,
) -> bool:
    """True when candidate overlaps an active or protected reservation for the driver."""
    from app.modules.health_isf.advance_scheduling import SCHEDULED_DISPATCH_ASSIGNMENT_STATES
    from app.modules.health_isf.service import (
        ACTIVE_DISPATCH_ASSIGNMENT_STATES,
        get_ride_by_id,
        is_operational_excluded_ride,
        _ride_is_terminal,
    )
    from app.modules.health_isf.models import HealthISFDispatchAssignment

    exclude = {str(x) for x in (exclude_ride_ids or set()) if x}
    conflict_states = set(ACTIVE_DISPATCH_ASSIGNMENT_STATES) | set(SCHEDULED_DISPATCH_ASSIGNMENT_STATES)
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(conflict_states)),
        )
        .all()
    )
    for row in rows:
        ride_id = str(row.ride_id or "")
        if not ride_id or ride_id in exclude or ride_id == str(candidate_ride.id):
            continue
        other = get_ride_by_id(db, ride_id)
        if not other or _ride_is_terminal(other) or is_operational_excluded_ride(other):
            continue
        if str(other.driver_id or "") != str(driver_id):
            continue
        if rides_time_overlap(candidate_ride, other):
            return True
    bound = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.driver_id == driver_id,
            HealthISFRide.id != candidate_ride.id,
        )
        .limit(50)
        .all()
    )
    for other in bound:
        if str(other.id) in exclude or _ride_is_terminal(other) or is_operational_excluded_ride(other):
            continue
        if rides_time_overlap(candidate_ride, other):
            return True
    return False


def activate_call_when_ready_return(
    db: Session,
    *,
    organization_id: str,
    round_trip_group_id: str,
    actor_user_id: Optional[str] = None,
) -> list[HealthISFRide]:
    """Activate return leg(s) after patient/provider marks ready."""
    from app.modules.health_isf.service import _commit_or_rollback

    rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.round_trip_group_id == round_trip_group_id,
            HealthISFRide.trip_leg == "return",
        )
        .all()
    )
    activated: list[HealthISFRide] = []
    now_ts = _now()
    for ride in rows:
        if not bool(getattr(ride, "call_when_ready", False)):
            continue
        ride.pickup_time = now_ts
        ride.dispatch_eligible_at = now_ts
        ride.call_when_ready = False
        ride.lifecycle_state = RideStatus.QUEUED.value
        ride.status = RideStatus.PENDING.value
        ride.updated_at = now_ts
        db.add(ride)
        activated.append(ride)
    if activated:
        _commit_or_rollback(db)
        for ride in activated:
            db.refresh(ride)
    return activated


def build_scheduling_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in (
        "service_date",
        "pickup_time",
        "arrival_time",
        "scheduled_time",
        "trip_type",
        "return_pickup_type",
        "return_pickup_time",
        "recurrence",
        "recurrence_weekdays",
        "recurrence_start_date",
        "recurrence_end_date",
        "return_pickup_address",
        "return_dropoff_address",
        "same_driver_preference",
    ):
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, date):
            out[key] = value.isoformat()
        else:
            out[key] = value
    return out


def parse_scheduling_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize rider scheduling fields from API payload."""
    trip_type = str(payload.get("trip_type") or "one_way").lower()
    recurrence = str(payload.get("recurrence") or ("weekly" if payload.get("recurring") else "none")).lower()
    arrival = payload.get("arrival_time") or payload.get("scheduled_time")
    pickup = payload.get("pickup_time")
    service_date_raw = payload.get("service_date")
    weekdays = payload.get("recurrence_weekdays") or []
    if not weekdays and isinstance(payload.get("recurring_pattern"), dict):
        weekdays = payload["recurring_pattern"].get("days") or []
    end_raw = payload.get("recurrence_end_date")
    start_raw = payload.get("recurrence_start_date") or service_date_raw
    service_date = _parse_date(service_date_raw)
    recurrence_start = _parse_date(start_raw) or service_date
    return {
        "trip_type": trip_type if trip_type in {"one_way", "round_trip"} else "one_way",
        "recurrence": recurrence if recurrence in {"none", "weekly"} else "none",
        "pickup_time": _parse_dt(pickup),
        "arrival_time": _parse_dt(arrival),
        "service_date": service_date,
        "return_pickup_type": str(payload.get("return_pickup_type") or "scheduled_time"),
        "return_pickup_time": _parse_dt(payload.get("return_pickup_time")),
        "return_pickup_address": str(payload.get("return_pickup_address") or "").strip() or None,
        "return_dropoff_address": str(payload.get("return_dropoff_address") or "").strip() or None,
        "recurrence_weekdays": [str(d).lower()[:3] for d in weekdays],
        "recurrence_start_date": recurrence_start,
        "recurrence_end_date": _parse_date(end_raw),
        "same_driver_preference": bool(payload.get("same_driver_preference")),
    }


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return _coerce_utc(value)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return _coerce_utc(datetime.fromisoformat(text))
    except ValueError:
        return None


def _parse_date(value: Any) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def combine_date_time(service_date: Optional[date], dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None:
        return _coerce_utc(dt)
    if service_date is None:
        return None
    return datetime.combine(service_date, datetime.min.time(), tzinfo=timezone.utc)


def create_scheduled_ride_request(
    db: Session,
    *,
    organization_id: str,
    rider_name: str,
    rider_phone: str,
    pickup_address: str,
    dropoff_address: str,
    ride_type: str,
    notes: Optional[str],
    submitted_by_user_id: Optional[str],
    scheduling: dict[str, Any],
    create_ride_fn: Any,
    create_request_fn: Any,
) -> tuple[HealthISFCustomerRideRequest, HealthISFRide, list[HealthISFRide]]:
    """
    Orchestrate one-way, round-trip, and weekly recurring ride creation.
    Returns (primary_request, primary_ride, all_created_rides).
    """
    trip_type = scheduling["trip_type"]
    recurrence = scheduling["recurrence"]
    service_date = scheduling["recurrence_start_date"] or scheduling["service_date"] or (_now().date())
    return_pickup_address = scheduling.get("return_pickup_address") or dropoff_address
    return_dropoff_address = scheduling.get("return_dropoff_address") or pickup_address
    pickup_time = combine_date_time(service_date, scheduling["pickup_time"])
    arrival_time = combine_date_time(service_date, scheduling["arrival_time"])
    same_driver = scheduling["same_driver_preference"]
    return_type = scheduling["return_pickup_type"]
    return_time = combine_date_time(service_date, scheduling["return_pickup_time"])
    end_date = scheduling["recurrence_end_date"] or service_date

    dates = [service_date]
    if recurrence == "weekly":
        dates = expand_weekly_instances(service_date, end_date, scheduling["recurrence_weekdays"])
        if not dates:
            dates = [service_date]

    series_id = str(uuid4()) if len(dates) > 1 or recurrence == "weekly" else None
    all_rides: list[HealthISFRide] = []

    for instance_date in dates:
        inst_pickup = pickup_time
        inst_arrival = arrival_time
        if inst_pickup and instance_date != inst_pickup.date():
            inst_pickup = datetime.combine(instance_date, inst_pickup.timetz(), tzinfo=timezone.utc)
        if inst_arrival and instance_date != inst_arrival.date():
            inst_arrival = datetime.combine(instance_date, inst_arrival.timetz(), tzinfo=timezone.utc)
        inst_return = return_time
        if inst_return and instance_date != inst_return.date() and trip_type == "round_trip":
            inst_return = datetime.combine(instance_date, inst_return.timetz(), tzinfo=timezone.utc)

        group_id = str(uuid4()) if trip_type == "round_trip" else None

        outbound = create_ride_fn(
            db,
            organization_id=organization_id,
            passenger_name=rider_name,
            passenger_phone=rider_phone,
            pickup_address=pickup_address,
            dropoff_address=dropoff_address,
            service_type=ride_type,
            appointment_time=inst_arrival,
            notes=notes,
            actor_user_id=submitted_by_user_id,
        )
        apply_scheduling_fields_to_ride(
            outbound,
            trip_leg="outbound" if trip_type == "round_trip" else "one_way",
            round_trip_group_id=group_id,
            scheduling_series_id=series_id,
            pickup_time=inst_pickup,
            arrival_time=inst_arrival,
            same_driver_preference=same_driver,
        )
        all_rides.append(outbound)
        db.add(outbound)

        linked: list[str] = [str(outbound.id)]
        if trip_type == "round_trip":
            call_ready = return_type == "call_when_ready"
            return_pickup = None if call_ready else inst_return
            return_leg = create_ride_fn(
                db,
                organization_id=organization_id,
                passenger_name=rider_name,
                passenger_phone=rider_phone,
                pickup_address=return_pickup_address,
                dropoff_address=return_dropoff_address,
                service_type=ride_type,
                appointment_time=None if call_ready else return_pickup,
                notes=notes,
                actor_user_id=submitted_by_user_id,
            )
            apply_scheduling_fields_to_ride(
                return_leg,
                trip_leg="return",
                round_trip_group_id=group_id,
                scheduling_series_id=series_id,
                pickup_time=return_pickup,
                arrival_time=None if call_ready else return_pickup,
                return_pickup_type=return_type,
                same_driver_preference=same_driver,
                call_when_ready=call_ready,
            )
            all_rides.append(return_leg)
            linked.append(str(return_leg.id))
            db.add(return_leg)

    db.flush()
    if not all_rides:
        raise ValueError("No rides created for scheduling request")
    primary = all_rides[0]
    metadata = build_scheduling_metadata({**scheduling, "trip_type": trip_type, "recurrence": recurrence})
    request_row = create_request_fn(
        db,
        organization_id=organization_id,
        ride=primary,
        rider_name=rider_name,
        rider_phone=rider_phone,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        scheduled_time=primary.appointment_time or primary.pickup_time,
        ride_type=ride_type,
        is_recurring=recurrence == "weekly",
        recurring_pattern={"type": "weekly", "days": scheduling["recurrence_weekdays"]} if recurrence == "weekly" else None,
        notes=notes,
        submitted_by_user_id=submitted_by_user_id,
        trip_type=trip_type,
        scheduling_metadata=metadata,
        linked_ride_ids=[str(r.id) for r in all_rides],
    )
    return request_row, primary, all_rides
