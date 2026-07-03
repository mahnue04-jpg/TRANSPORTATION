"""
Service layer for Health ISF module.
Persists provider/driver/ride operations with audit timeline entries.
"""

import logging
import json
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from sqlalchemy import and_, case, desc, func, or_, text
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    CustomerRequestStatus,
    DispatchAssignmentState,
    HealthISFCustomerRideRequest,
    HealthISFDispatchAssignment,
    HealthISFDriverSession,
    DriverStatus,
    HealthISFDispatchLog,
    HealthISFDriverApplication,
    HealthISFDriver,
    HealthISFRecurringRideSchedule,
    HealthISFOrganization,
    HealthISFPayout,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideExecutionAction,
    HealthISFWorkflowEscalation,
    HealthISFWorkflowIncident,
    RideAssignmentLock,
    HealthISFRideStatusHistory,
    HealthISFTrip,
    HealthISFVehicle,
    RideStatus,
    TripStatus,
)
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager
from app.modules.health_isf.schemas import DashboardMetrics
from app.modules.health_isf.runtime_governor import get_runtime_governor
from app.modules.health_isf.service_categories import serialize_service_category

logger = logging.getLogger("amicor.health_isf.service")

WEEKDAY_INDEX = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


VALID_DRIVER_APPLICATION_STATUSES = {
    "applied",
    "pending_review",
    "approved",
    "active",
    "suspended",
}

VALID_CUSTOMER_REQUEST_STATUSES = {
    CustomerRequestStatus.PENDING.value,
    CustomerRequestStatus.APPROVED.value,
    CustomerRequestStatus.DISPATCHABLE.value,
    CustomerRequestStatus.BROADCASTED.value,
    CustomerRequestStatus.ACCEPTED.value,
    CustomerRequestStatus.ASSIGNED.value,
    CustomerRequestStatus.IN_PROGRESS.value,
    CustomerRequestStatus.COMPLETED.value,
    CustomerRequestStatus.CANCELLED.value,
}

VALID_CUSTOMER_RIDE_TYPES = {
    "healthcare",
    "work",
    "grocery",
    "church",
    "personal",
}

VALID_DRIVER_AVAILABILITY_STATES = {
    "available",
    "unavailable",
    "on_trip",
    "offline",
}

ACTIVE_RIDE_STATUSES_FOR_ASSIGNMENT = {
    RideStatus.PENDING.value,
    RideStatus.ASSIGNED.value,
    RideStatus.ACCEPTED.value,
    RideStatus.DRIVER_EN_ROUTE.value,
    RideStatus.ARRIVED.value,
    RideStatus.RIDER_ONBOARD.value,
    RideStatus.ESCALATED.value,
    RideStatus.IN_PROGRESS.value,
    RideStatus.IN_TRANSIT.value,
}

ACTIVE_DISPATCH_ASSIGNMENT_STATES = {
    DispatchAssignmentState.OFFERED.value,
    DispatchAssignmentState.ASSIGNED.value,
    DispatchAssignmentState.ACCEPTED.value,
    DispatchAssignmentState.EN_ROUTE_PICKUP.value,
    DispatchAssignmentState.PICKUP_COMPLETE.value,
}


def _runtime_workflow_id(ride_id: str) -> str:
    return f"ride:{ride_id}"


def _safe_runtime_register(ride: HealthISFRide, state: str, source: str, driver_id: Optional[str] = None) -> None:
    try:
        governor = get_runtime_governor()
        governor.register_workflow(
            workflow_id=_runtime_workflow_id(ride.id),
            ride_id=ride.id,
            organization_id=ride.organization_id,
            lifecycle_state=state,
            driver_id=str(driver_id or ride.driver_id) if (driver_id or ride.driver_id) else None,
            metadata={
                "source": source,
                "status": str(ride.status),
                "lifecycle_state": str(getattr(ride, "lifecycle_state", state) or state),
            },
        )
    except Exception as exc:
        logger.warning({
            "event": "runtime_governor_register_failed",
            "ride_id": ride.id,
            "source": source,
            "error": str(exc),
        })


def _safe_runtime_update(ride: HealthISFRide, state: str, source: str, driver_id: Optional[str] = None) -> None:
    try:
        governor = get_runtime_governor()
        governor.update_workflow(
            workflow_id=_runtime_workflow_id(ride.id),
            lifecycle_state=state,
            driver_id=str(driver_id or ride.driver_id) if (driver_id or ride.driver_id) else None,
            metadata={
                "source": source,
                "status": str(ride.status),
                "lifecycle_state": str(getattr(ride, "lifecycle_state", state) or state),
            },
        )
    except Exception as exc:
        logger.warning({
            "event": "runtime_governor_update_failed",
            "ride_id": ride.id,
            "source": source,
            "error": str(exc),
        })


def _safe_runtime_unregister(ride_id: str, reason: str) -> None:
    try:
        governor = get_runtime_governor()
        governor.unregister_workflow(
            workflow_id=_runtime_workflow_id(ride_id),
            reason=reason,
        )
    except Exception as exc:
        logger.warning({
            "event": "runtime_governor_unregister_failed",
            "ride_id": ride_id,
            "reason": reason,
            "error": str(exc),
        })


def _safe_runtime_record_lifecycle_reject() -> None:
    try:
        governor = get_runtime_governor()
        governor.record_lifecycle_transition_reject()
    except Exception as exc:
        logger.warning({
            "event": "runtime_governor_lifecycle_reject_record_failed",
            "error": str(exc),
        })


def _safe_json_parse(payload: Optional[str]) -> Optional[dict]:
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_driver_application_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if value not in VALID_DRIVER_APPLICATION_STATUSES:
        raise ValueError(
            "Invalid onboarding status. Expected one of: "
            + ", ".join(sorted(VALID_DRIVER_APPLICATION_STATUSES))
        )
    return value


def _normalize_customer_request_status(status: str) -> str:
    value = str(status or "").strip().lower()
    if value not in VALID_CUSTOMER_REQUEST_STATUSES:
        raise ValueError(
            "Invalid request status. Expected one of: "
            + ", ".join(sorted(VALID_CUSTOMER_REQUEST_STATUSES))
        )
    return value


def _normalize_customer_ride_type(ride_type: str) -> str:
    value = str(ride_type or "").strip().lower()
    if value not in VALID_CUSTOMER_RIDE_TYPES:
        raise ValueError(
            "Invalid ride type. Expected one of: "
            + ", ".join(sorted(VALID_CUSTOMER_RIDE_TYPES))
        )
    return value


def _normalize_schedule_frequency(frequency: str) -> str:
    value = str(frequency or "").strip().lower()
    if value not in {"daily", "weekly", "monthly", "custom"}:
        raise ValueError("frequency must be one of daily, weekly, monthly, custom")
    return value


def _normalize_weekdays(weekdays: Optional[list[str]]) -> list[int]:
    if not weekdays:
        return []
    normalized: set[int] = set()
    for token in weekdays:
        key = str(token or "").strip().lower()
        if key not in WEEKDAY_INDEX:
            raise ValueError(f"Invalid weekday token: {token}")
        normalized.add(WEEKDAY_INDEX[key])
    return sorted(normalized)


def _parse_pickup_time_local(raw: str) -> tuple[int, int]:
    value = str(raw or "").strip()
    if ":" not in value:
        raise ValueError("pickup_time_local must be in HH:MM format")
    hh, mm = value.split(":", 1)
    try:
        hour = int(hh)
        minute = int(mm)
    except ValueError as exc:
        raise ValueError("pickup_time_local must be in HH:MM format") from exc
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise ValueError("pickup_time_local must be a valid 24h time")
    return hour, minute


def _coerce_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _combine_date_with_pickup_time(day: datetime, pickup_time_local: str) -> datetime:
    hour, minute = _parse_pickup_time_local(pickup_time_local)
    base = _coerce_utc(day) or now()
    return datetime(
        year=base.year,
        month=base.month,
        day=base.day,
        hour=hour,
        minute=minute,
        tzinfo=timezone.utc,
    )


def _matches_schedule_date(schedule: HealthISFRecurringRideSchedule, current_day: datetime) -> bool:
    freq = str(schedule.frequency or "").lower()
    weekdays = _safe_json_parse(schedule.weekday_mask_json) or {}
    weekday_values = set(int(item) for item in list(weekdays.get("weekdays") or []) if str(item).isdigit())
    start_day = (_coerce_utc(schedule.start_date) or now()).date()
    current_date = (_coerce_utc(current_day) or now()).date()
    delta_days = (current_date - start_day).days
    if delta_days < 0:
        return False

    interval = max(int(schedule.interval_count or 1), 1)
    if freq == "daily":
        return delta_days % interval == 0
    if freq == "weekly":
        return (delta_days // 7) % interval == 0 and current_date.weekday() == start_day.weekday()
    if freq == "monthly":
        return current_date.day == start_day.day and ((current_date.year - start_day.year) * 12 + (current_date.month - start_day.month)) % interval == 0
    if freq == "custom":
        if not weekday_values:
            return False
        return current_date.weekday() in weekday_values
    return False


def create_recurring_ride_schedule(
    db: Session,
    *,
    organization_id: str,
    provider_id: str,
    passenger_name: str,
    passenger_phone: str,
    pickup_address: str,
    dropoff_address: str,
    service_type: str,
    pickup_time_local: str,
    frequency: str,
    interval_count: int,
    weekdays: Optional[list[str]],
    start_date: datetime,
    end_date: Optional[datetime],
    actor_user_id: Optional[str],
) -> HealthISFRecurringRideSchedule:
    normalized_frequency = _normalize_schedule_frequency(frequency)
    normalized_weekdays = _normalize_weekdays(weekdays)
    if normalized_frequency == "custom" and not normalized_weekdays:
        raise ValueError("custom frequency requires at least one weekday")
    if normalized_frequency != "custom" and normalized_weekdays:
        raise ValueError("weekdays are only supported for custom frequency")
    _parse_pickup_time_local(pickup_time_local)

    normalized_start = _coerce_utc(start_date)
    normalized_end = _coerce_utc(end_date)
    if not normalized_start:
        raise ValueError("start_date is required")
    if normalized_end and normalized_end < normalized_start:
        raise ValueError("end_date must be on or after start_date")

    schedule = HealthISFRecurringRideSchedule(
        id=uuid4(),
        organization_id=organization_id,
        provider_id=provider_id,
        passenger_name=passenger_name,
        passenger_phone=passenger_phone,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        service_type=serialize_service_category(service_type),
        pickup_time_local=pickup_time_local,
        frequency=normalized_frequency,
        interval_count=max(int(interval_count or 1), 1),
        weekday_mask_json=json.dumps({"weekdays": normalized_weekdays}) if normalized_weekdays else None,
        start_date=normalized_start,
        end_date=normalized_end,
        is_active=True,
        created_by_user_id=actor_user_id,
        created_at=now(),
        updated_at=now(),
    )
    db.add(schedule)
    _commit_or_rollback(db)
    db.refresh(schedule)
    return schedule


def get_recurring_ride_schedule_by_id(
    db: Session,
    *,
    schedule_id: str,
) -> Optional[HealthISFRecurringRideSchedule]:
    return db.query(HealthISFRecurringRideSchedule).filter(HealthISFRecurringRideSchedule.id == schedule_id).first()


def list_recurring_ride_schedules(
    db: Session,
    *,
    organization_id: str,
    active_only: bool = False,
    limit: int = 200,
) -> list[HealthISFRecurringRideSchedule]:
    query = db.query(HealthISFRecurringRideSchedule).filter(HealthISFRecurringRideSchedule.organization_id == organization_id)
    if active_only:
        query = query.filter(HealthISFRecurringRideSchedule.is_active.is_(True))
    return query.order_by(desc(HealthISFRecurringRideSchedule.created_at)).limit(limit).all()


def set_recurring_ride_schedule_active(
    db: Session,
    *,
    schedule_id: str,
    is_active: bool,
) -> Optional[HealthISFRecurringRideSchedule]:
    schedule = get_recurring_ride_schedule_by_id(db, schedule_id=schedule_id)
    if not schedule:
        return None
    schedule.is_active = bool(is_active)
    schedule.updated_at = now()
    _commit_or_rollback(db)
    db.refresh(schedule)
    return schedule


def generate_recurring_rides_for_schedule(
    db: Session,
    *,
    schedule: HealthISFRecurringRideSchedule,
    horizon_days: int = 30,
    actor_user_id: Optional[str] = None,
) -> list[HealthISFRide]:
    if not schedule.is_active:
        return []

    horizon = max(int(horizon_days or 1), 1)
    start_dt = _coerce_utc(schedule.start_date) or now()
    now_dt = _coerce_utc(now()) or now()
    window_start = max(start_dt, now_dt.replace(hour=0, minute=0, second=0, microsecond=0))
    window_end = window_start + timedelta(days=horizon)
    if schedule.end_date:
        schedule_end = _coerce_utc(schedule.end_date)
        if schedule_end and schedule_end < window_end:
            window_end = schedule_end

    created: list[HealthISFRide] = []
    current = window_start
    while current <= window_end:
        if _matches_schedule_date(schedule, current):
            instance_at = _combine_date_with_pickup_time(current, schedule.pickup_time_local)
            duplicate = (
                db.query(HealthISFRide)
                .filter(
                    HealthISFRide.organization_id == schedule.organization_id,
                    HealthISFRide.recurring_schedule_id == schedule.id,
                    HealthISFRide.appointment_time == instance_at,
                )
                .first()
            )
            if not duplicate:
                ride = create_ride(
                    db,
                    passenger_name=schedule.passenger_name,
                    passenger_phone=schedule.passenger_phone,
                    pickup_address=schedule.pickup_address,
                    dropoff_address=schedule.dropoff_address,
                    service_type=schedule.service_type,
                    provider_id=schedule.provider_id,
                    organization_id=schedule.organization_id,
                    appointment_time=instance_at,
                    recurring_trip_pattern={
                        "schedule_id": schedule.id,
                        "frequency": schedule.frequency,
                        "pickup_time_local": schedule.pickup_time_local,
                    },
                    notes="Generated from recurring schedule",
                    actor_user_id=actor_user_id,
                )
                ride.recurring_schedule_id = schedule.id
                ride.recurring_instance_date = instance_at
                created.append(ride)
        current = current + timedelta(days=1)

    schedule.last_generated_at = now()
    schedule.generated_until = window_end
    schedule.updated_at = now()
    _commit_or_rollback(db)
    return created


def list_generated_rides_for_schedule(
    db: Session,
    *,
    organization_id: str,
    schedule_id: str,
    limit: int = 500,
) -> list[HealthISFRide]:
    return (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.recurring_schedule_id == schedule_id,
        )
        .order_by(desc(HealthISFRide.appointment_time), desc(HealthISFRide.created_at))
        .limit(limit)
        .all()
    )


def _normalize_phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _phones_match_for_driver_login(stored_phone: str | None, provided_phone: str | None) -> bool:
    stored_digits = _normalize_phone_digits(stored_phone)
    provided_digits = _normalize_phone_digits(provided_phone)
    if not stored_digits or not provided_digits:
        return False
    if stored_digits == provided_digits:
        return True
    if len(stored_digits) >= 10 and len(provided_digits) >= 10:
        return stored_digits[-10:] == provided_digits[-10:]
    return False


def _normalize_driver_availability_state(state: str) -> str:
    value = str(state or "").strip().lower()
    if value not in VALID_DRIVER_AVAILABILITY_STATES:
        raise ValueError(
            "Invalid availability_state. Expected one of: "
            + ", ".join(sorted(VALID_DRIVER_AVAILABILITY_STATES))
        )
    return value


def _driver_status_from_availability(availability_state: str) -> DriverStatus:
    normalized = _normalize_driver_availability_state(availability_state)
    if normalized == "available":
        return DriverStatus.AVAILABLE
    if normalized == "unavailable":
        return DriverStatus.UNAVAILABLE
    if normalized == "on_trip":
        return DriverStatus.IN_TRANSIT
    return DriverStatus.OFFLINE


def _hash_driver_session_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _issue_driver_session_token() -> str:
    return "drv_" + secrets.token_urlsafe(32)


def _active_ride_for_driver(db: Session, driver_id: str) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None
    rides = list_driver_assigned_rides(db, organization_id=driver.organization_id, driver_id=driver_id, limit=1)
    return rides[0] if rides else None


def _driver_active_workload_count(db: Session, driver_id: str) -> int:
    return int(
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.driver_id == driver_id,
            HealthISFRide.status.in_(list(ACTIVE_RIDE_STATUSES_FOR_ASSIGNMENT)),
        )
        .count()
    )


def _seconds_since(ts: Optional[datetime], now_ts: datetime) -> int:
    if not ts:
        return 10**9
    try:
        normalized_now = _as_utc_datetime(now_ts)
        normalized_ts = _as_utc_datetime(ts)
        return max(0, int((normalized_now - normalized_ts).total_seconds()))
    except Exception:
        return 10**9


def _as_utc_datetime(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def _normalized_timestamp_token(ts: Optional[datetime]) -> str:
    if not ts:
        return "1970-01-01T00:00:00+00:00"
    return _as_utc_datetime(ts).replace(microsecond=0).isoformat()


def snapshot_dispatch_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Capture immutable deterministic ranking evidence for replay/debug."""
    snapshot_at = now().isoformat()
    snapshot: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates, start=1):
        driver = item.get("driver")
        breakdown = dict(item.get("breakdown") or {})
        snapshot.append(
            {
                "rank": idx,
                "driver_id": str(getattr(driver, "id", "") or ""),
                "score": float(item.get("score") or 0.0),
                "score_breakdown": breakdown,
                "score_snapshot": {
                    "heartbeat_age_seconds": int(breakdown.get("heartbeat_age_seconds") or 0),
                    "availability_age_seconds": int(breakdown.get("availability_age_seconds") or 0),
                    "updated_at_token": _normalized_timestamp_token(getattr(driver, "updated_at", None)),
                },
                "snapshot_at": snapshot_at,
            }
        )
    return snapshot


def validate_candidate_order(snapshot: list[dict[str, Any]]) -> bool:
    """Validate ordering is strictly deterministic for parity checks."""
    if not snapshot:
        return True
    for idx, row in enumerate(snapshot, start=1):
        if int(row.get("rank") or 0) != idx:
            return False
    ordered = sorted(
        snapshot,
        key=lambda row: (
            -float(row.get("score") or 0.0),
            int((row.get("score_snapshot") or {}).get("heartbeat_age_seconds") or 0),
            str(row.get("driver_id") or ""),
        ),
    )
    return [str(item.get("driver_id") or "") for item in ordered] == [
        str(item.get("driver_id") or "") for item in snapshot
    ]


def compare_selection_parity(first_snapshot: list[dict[str, Any]], second_snapshot: list[dict[str, Any]]) -> bool:
    """Compare two deterministic candidate snapshots for reproducible ordering."""
    first_ids = [str(item.get("driver_id") or "") for item in first_snapshot]
    second_ids = [str(item.get("driver_id") or "") for item in second_snapshot]
    return first_ids == second_ids


def _next_assignment_attempt_index(db: Session, ride_id: str) -> int:
    current = (
        db.query(func.max(HealthISFDispatchAssignment.attempt_index))
        .filter(HealthISFDispatchAssignment.ride_id == ride_id)
        .scalar()
    )
    return int(current or 0) + 1


def _latest_assignment_for_ride(db: Session, ride_id: str) -> Optional[HealthISFDispatchAssignment]:
    return (
        db.query(HealthISFDispatchAssignment)
        .filter(HealthISFDispatchAssignment.ride_id == ride_id)
        .order_by(desc(HealthISFDispatchAssignment.created_at), desc(HealthISFDispatchAssignment.attempt_index))
        .first()
    )


def _mark_dispatch_assignment_state(
    db: Session,
    *,
    ride_id: str,
    assignment_state: str,
    note: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    row = _latest_assignment_for_ride(db, ride_id)
    if not row:
        return None
    now_ts = now()
    row.assignment_state = assignment_state
    row.updated_at = now_ts
    if assignment_state == DispatchAssignmentState.SEARCHING.value:
        row.search_started_at = row.search_started_at or now_ts
    elif assignment_state == DispatchAssignmentState.OFFERED.value:
        row.offered_at = row.offered_at or now_ts
    elif assignment_state == DispatchAssignmentState.ASSIGNED.value:
        row.assigned_at = row.assigned_at or now_ts
    elif assignment_state == DispatchAssignmentState.ACCEPTED.value:
        row.accepted_at = row.accepted_at or now_ts
    elif assignment_state == DispatchAssignmentState.EN_ROUTE_PICKUP.value:
        row.en_route_pickup_at = row.en_route_pickup_at or now_ts
    elif assignment_state == DispatchAssignmentState.PICKUP_COMPLETE.value:
        row.pickup_complete_at = row.pickup_complete_at or now_ts
    elif assignment_state == DispatchAssignmentState.DROPOFF_COMPLETE.value:
        row.dropoff_complete_at = row.dropoff_complete_at or now_ts
    elif assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
        row.reassignment_pending_at = row.reassignment_pending_at or now_ts
    if note:
        row.metadata_json = json.dumps({"note": note[:512]})
    return row


def _driver_mobile_dispatch_ready(driver: HealthISFDriver) -> bool:
    return (
        str(driver.auth_state or "inactive").lower() == "active"
        and bool(driver.is_online)
        and str(driver.availability_state or "offline").lower() == "available"
    )


def _driver_status_dispatch_ready(driver: HealthISFDriver) -> bool:
    return _coerce_driver_status(driver.status) == DriverStatus.AVAILABLE


def _driver_is_dispatch_candidate(
    db: Session,
    driver: HealthISFDriver,
    *,
    exclude_driver_ids: Optional[set[str]] = None,
) -> bool:
    exclude_ids = {str(item) for item in (exclude_driver_ids or set()) if str(item).strip()}
    if str(driver.id) in exclude_ids:
        return False
    if not bool(driver.is_active):
        return False
    if _driver_active_workload_count(db, driver.id) > 0:
        return False
    if _is_driver_busy(driver.status):
        return False
    return _driver_mobile_dispatch_ready(driver) or _driver_status_dispatch_ready(driver)


def evaluate_dispatch_candidates(
    db: Session,
    *,
    organization_id: str,
    ride: HealthISFRide,
    exclude_driver_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Score active drivers for AI dispatch recommendation and auto-assignment."""
    _normalize_legacy_driver_status_rows(db)
    exclude_ids = {str(item) for item in (exclude_driver_ids or set()) if str(item).strip()}
    rows = (
        db.query(HealthISFDriver)
        .filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.is_active == True,
        )
        .order_by(HealthISFDriver.updated_at.desc(), HealthISFDriver.id.asc())
        .all()
    )

    now_ts = now()
    ride_distance = float(ride.estimated_distance_miles or 10.0)
    candidates: list[dict[str, Any]] = []
    for driver in rows:
        if str(driver.id) in exclude_ids:
            continue
        if not _driver_is_dispatch_candidate(db, driver, exclude_driver_ids=exclude_ids):
            continue

        active_workload = _driver_active_workload_count(db, driver.id)
        mobile_ready = _driver_mobile_dispatch_ready(driver)
        status_ready = _driver_status_dispatch_ready(driver)
        heartbeat_age = _seconds_since(driver.last_seen_at, now_ts)
        availability_age = _seconds_since(driver.updated_at, now_ts)
        distance_priority = 1.0 / max(1.0, ride_distance)
        availability_freshness = 1.0 / (1.0 + (availability_age / 120.0))
        heartbeat_freshness = 1.0 / (1.0 + (heartbeat_age / 60.0))
        acceptance_history_placeholder = max(0.2, min(1.0, float(driver.rating or 0.0) / 5.0))
        workload_weighting = 1.0 - min(0.8, active_workload * 0.25)
        mobile_bonus = 0.08 if mobile_ready else (0.03 if status_ready else 0.0)

        score = (
            (distance_priority * 0.30)
            + (availability_freshness * 0.20)
            + (heartbeat_freshness * 0.25)
            + (acceptance_history_placeholder * 0.15)
            + (workload_weighting * 0.10)
            + mobile_bonus
        )

        candidates.append(
            {
                "driver": driver,
                "score": round(float(score), 6),
                "breakdown": {
                    "distance_priority_placeholder": round(distance_priority, 6),
                    "availability_freshness": round(availability_freshness, 6),
                    "heartbeat_freshness": round(heartbeat_freshness, 6),
                    "acceptance_history_placeholder": round(acceptance_history_placeholder, 6),
                    "active_workload_weighting": round(workload_weighting, 6),
                    "active_workload": active_workload,
                    "heartbeat_age_seconds": heartbeat_age,
                    "availability_age_seconds": availability_age,
                    "mobile_dispatch_ready": mobile_ready,
                    "status_dispatch_ready": status_ready,
                },
            }
        )

    candidates.sort(
        key=lambda item: (
            -float(item["score"]),
            0 if item["breakdown"].get("mobile_dispatch_ready") else 1,
            int(item["breakdown"].get("heartbeat_age_seconds", 10**9)),
            _normalized_timestamp_token(getattr(item["driver"], "updated_at", None)),
            str(item["driver"].id),
        )
    )
    return candidates


def evaluate_available_drivers(
    db: Session,
    *,
    organization_id: str,
    ride: HealthISFRide,
    exclude_driver_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Deterministic driver scoring for auto-assignment candidate selection."""
    return evaluate_dispatch_candidates(
        db,
        organization_id=organization_id,
        ride=ride,
        exclude_driver_ids=exclude_driver_ids,
    )


def recommend_driver_for_ride(
    db: Session,
    *,
    ride_id: str,
    actor_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Evaluate a new ride and persist an AI dispatch recommendation awaiting human approval."""
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")

    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
        return {"ride": ride, "recommendation": None, "selected_driver": None, "candidates": []}

    if ride.driver_id:
        return {"ride": ride, "recommendation": None, "selected_driver": None, "candidates": []}

    existing_recommendation = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    if existing_recommendation:
        selected_driver = get_driver_by_id(db, existing_recommendation.driver_id) if existing_recommendation.driver_id else None
        return {
            "ride": ride,
            "recommendation": existing_recommendation,
            "selected_driver": selected_driver,
            "selected_score": float(existing_recommendation.score) if existing_recommendation.score is not None else None,
            "selected_breakdown": _safe_json_parse(existing_recommendation.score_breakdown_json) or {},
            "candidates": [],
        }

    candidates = evaluate_dispatch_candidates(
        db,
        organization_id=ride.organization_id,
        ride=ride,
    )
    if not candidates:
        _record_dispatch(
            db,
            ride_id=ride.id,
            action="dispatch_recommendation_no_candidates",
            acted_by_user_id=actor_user_id,
            note="No dispatch-ready drivers after AI intake evaluation",
        )
        _commit_or_rollback(db)
        return {"ride": ride, "recommendation": None, "selected_driver": None, "candidates": []}

    selected = candidates[0]
    driver = selected["driver"]
    intelligence_summary = None
    try:
        from app.modules.health_isf.intelligence import OperationalIntelligenceService

        recommendations = OperationalIntelligenceService.build_recommendations(
            db,
            ride.organization_id,
            ride_id=ride.id,
        )
        recommendation_items = recommendations.get("recommendations") or []
        for item in recommendation_items:
            if str(item.get("entity_type") or "") == "driver" and str(item.get("entity_id") or "") == str(driver.id):
                intelligence_summary = str(item.get("explanation_summary") or "")
                break
        if not intelligence_summary and recommendation_items:
            intelligence_summary = str(recommendation_items[0].get("explanation_summary") or "")
    except Exception:
        intelligence_summary = f"AI selected {driver.name} as best available driver"

    now_ts = now()
    attempt_index = _next_assignment_attempt_index(db, ride.id)
    latest = _latest_assignment_for_ride(db, ride.id)
    reassignment_chain_id = str(latest.reassignment_chain_id) if latest and latest.reassignment_chain_id else str(uuid4())
    recommendation = HealthISFDispatchAssignment(
        id=uuid4(),
        organization_id=ride.organization_id,
        ride_id=ride.id,
        driver_id=driver.id,
        assignment_state=DispatchAssignmentState.AWAITING_APPROVAL.value,
        attempt_index=attempt_index,
        score=float(selected["score"]),
        score_breakdown_json=json.dumps(selected["breakdown"]),
        timeout_seconds=0,
        queued_at=now_ts,
        search_started_at=now_ts,
        reassignment_chain_id=reassignment_chain_id,
        metadata_json=json.dumps(
            {
                "stage": "ai_recommendation",
                "source": "intake_auto_recommend",
                "intelligence_summary": intelligence_summary,
                "candidate_count": len(candidates),
            }
        ),
        created_by_user_id=actor_user_id,
        created_at=now_ts,
        updated_at=now_ts,
    )
    db.add(recommendation)
    _record_dispatch(
        db,
        ride_id=ride.id,
        action="dispatch_recommendation_created",
        acted_by_user_id=actor_user_id,
        driver_id=driver.id,
        note=intelligence_summary or f"AI recommended driver {driver.name}",
        assignment_id=recommendation.id,
        lifecycle_state=DispatchAssignmentState.AWAITING_APPROVAL.value,
        transition_reason="intake_ai_recommendation",
        transition_timestamp=now_ts,
        assignment_transition_source="recommend_driver_for_ride",
    )
    _commit_or_rollback(db)
    db.refresh(recommendation)
    db.refresh(ride)
    return {
        "ride": ride,
        "recommendation": recommendation,
        "selected_driver": driver,
        "selected_score": selected["score"],
        "selected_breakdown": selected["breakdown"],
        "candidates": candidates,
        "intelligence_summary": intelligence_summary,
    }


def approve_dispatch_recommendation(
    db: Session,
    *,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    offer_timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Finalize dispatcher approval of an AI recommendation and issue the driver offer."""
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")

    recommendation = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    if not recommendation:
        raise ValueError("No AI dispatch recommendation awaiting approval")

    target_driver_id = str(driver_id or recommendation.driver_id or "").strip()
    if not target_driver_id:
        raise ValueError("No recommended driver available for approval")

    assigned_ride = assign_driver_to_ride(
        db,
        ride_id=ride.id,
        driver_id=target_driver_id,
        actor_user_id=actor_user_id,
    )
    if not assigned_ride:
        raise ValueError("Ride not found")

    offer = _latest_assignment_for_ride(db, ride.id)
    if not offer:
        raise ValueError("Assignment offer was not created")

    now_ts = now()
    offer.timeout_seconds = max(10, int(offer_timeout_seconds or 90))
    offer.offered_at = offer.offered_at or now_ts
    offer.offer_expires_at = now_ts + timedelta(seconds=offer.timeout_seconds)
    offer.assigned_at = offer.assigned_at or getattr(assigned_ride, "assigned_at", None) or now_ts
    offer.updated_at = now_ts
    _record_dispatch(
        db,
        ride_id=ride.id,
        action="dispatch_recommendation_approved",
        acted_by_user_id=actor_user_id,
        driver_id=target_driver_id,
        note="Dispatcher approved AI dispatch recommendation",
        assignment_id=offer.id,
        lifecycle_state=str(offer.assignment_state),
        transition_reason="dispatcher_approved_recommendation",
        transition_timestamp=now_ts,
        assignment_transition_source="approve_dispatch_recommendation",
    )
    _commit_or_rollback(db)
    db.refresh(offer)
    db.refresh(assigned_ride)
    return {
        "ride": assigned_ride,
        "offer": offer,
        "selected_driver": get_driver_by_id(db, target_driver_id),
        "recommendation_id": recommendation.id,
    }


def expire_stale_dispatch_offers(
    db: Session,
    *,
    organization_id: str,
    ride_id: Optional[str] = None,
) -> list[HealthISFDispatchAssignment]:
    now_ts = now()
    query = db.query(HealthISFDispatchAssignment).filter(
        HealthISFDispatchAssignment.organization_id == organization_id,
        HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        HealthISFDispatchAssignment.offer_expires_at.is_not(None),
        HealthISFDispatchAssignment.offer_expires_at < now_ts,
    )
    if ride_id:
        query = query.filter(HealthISFDispatchAssignment.ride_id == ride_id)
    rows = query.order_by(HealthISFDispatchAssignment.offer_expires_at.asc()).all()
    expired: list[HealthISFDispatchAssignment] = []
    for row in rows:
        row.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        row.expired_at = now_ts
        row.reassignment_pending_at = now_ts
        row.closed_reason = "offer_timeout"
        row.updated_at = now_ts
        if row.driver_id:
            driver = get_driver_by_id(db, row.driver_id)
            if driver and _driver_active_workload_count(db, driver.id) == 0:
                driver.availability_state = "available"
                driver.is_online = True
                driver.auth_state = "active"
                driver.last_seen_at = now_ts
                _set_driver_status(db, driver, DriverStatus.AVAILABLE)
        _record_dispatch(
            db,
            ride_id=row.ride_id,
            action="driver_offer_expired",
            driver_id=row.driver_id,
            note="Driver offer expired and moved to reassignment_pending",
        )
        expired.append(row)
    if expired:
        _commit_or_rollback(db)
    return expired


def reserve_driver_assignment(
    db: Session,
    *,
    ride_id: str,
    driver_id: str,
    actor_user_id: Optional[str] = None,
    score: Optional[float] = None,
    score_breakdown: Optional[dict[str, Any]] = None,
    timeout_seconds: int = 90,
) -> HealthISFDispatchAssignment:
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        raise ValueError("Driver not found")
    if ride.organization_id != driver.organization_id:
        raise ValueError("Driver must belong to the same organization as ride")
    if str(driver.auth_state or "inactive").lower() != "active" or not bool(driver.is_online):
        raise ValueError("Driver must be online and authenticated")
    if str(driver.availability_state or "offline").lower() != "available":
        raise ValueError("Driver availability_state must be available")
    if _driver_active_workload_count(db, driver.id) > 0:
        raise ValueError("Driver already has an active trip")

    now_ts = now()
    attempt_index = _next_assignment_attempt_index(db, ride.id)
    offer_expires_at = now_ts + timedelta(seconds=max(10, int(timeout_seconds or 90)))
    latest = _latest_assignment_for_ride(db, ride.id)
    reassignment_chain_id = str(latest.reassignment_chain_id) if latest and latest.reassignment_chain_id else str(uuid4())
    assignment = HealthISFDispatchAssignment(
        id=uuid4(),
        organization_id=ride.organization_id,
        ride_id=ride.id,
        driver_id=driver.id,
        assignment_state=DispatchAssignmentState.OFFERED.value,
        attempt_index=attempt_index,
        score=score,
        score_breakdown_json=json.dumps(score_breakdown or {}),
        timeout_seconds=max(10, int(timeout_seconds or 90)),
        queued_at=now_ts,
        search_started_at=now_ts,
        offered_at=now_ts,
        offer_expires_at=offer_expires_at,
        assigned_at=None,
        accepted_at=None,
        reassignment_pending_at=None,
        reassignment_started_at=None,
        reassignment_completed_at=None,
        reassignment_attempt_count=max(0, int(attempt_index - 1)),
        reassignment_reason=None,
        reassignment_chain_id=reassignment_chain_id,
        closed_reason=None,
        metadata_json=json.dumps({"stage": "offer_issued", "reassignment_chain_id": reassignment_chain_id}),
        created_by_user_id=actor_user_id,
        created_at=now_ts,
        updated_at=now_ts,
    )
    db.add(assignment)

    driver.availability_state = "unavailable"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now_ts
    _set_driver_status(db, driver, DriverStatus.UNAVAILABLE)

    _record_dispatch(
        db,
        ride_id=ride.id,
        action="driver_offer_issued",
        acted_by_user_id=actor_user_id,
        driver_id=driver.id,
        note=f"Offer issued (attempt {attempt_index})",
    )
    _commit_or_rollback(db)
    db.refresh(assignment)
    return assignment


def release_driver_assignment(
    db: Session,
    *,
    offer_id: str,
    reason: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    assignment = db.query(HealthISFDispatchAssignment).filter(HealthISFDispatchAssignment.id == offer_id).first()
    if not assignment:
        return None

    now_ts = now()
    normalized_reason = str(reason or "released").strip().lower()
    if normalized_reason in {"expired", "timeout", "offer_timeout"}:
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        assignment.expired_at = assignment.expired_at or now_ts
        assignment.reassignment_pending_at = assignment.reassignment_pending_at or now_ts
        assignment.closed_reason = "offer_timeout"
    elif normalized_reason in {"rejected", "declined"}:
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        assignment.rejected_at = assignment.rejected_at or now_ts
        assignment.reassignment_pending_at = assignment.reassignment_pending_at or now_ts
        assignment.closed_reason = "driver_rejected"
    else:
        assignment.closed_reason = normalized_reason[:120]
    assignment.updated_at = now_ts

    if assignment.driver_id:
        driver = get_driver_by_id(db, assignment.driver_id)
        if driver and _driver_active_workload_count(db, driver.id) == 0:
            driver.availability_state = "available"
            driver.is_online = True
            driver.auth_state = "active"
            driver.last_seen_at = now_ts
            _set_driver_status(db, driver, DriverStatus.AVAILABLE)

    _record_dispatch(
        db,
        ride_id=assignment.ride_id,
        action="driver_offer_released",
        acted_by_user_id=actor_user_id,
        driver_id=assignment.driver_id,
        note=f"Offer released: {assignment.closed_reason}",
    )
    _commit_or_rollback(db)
    db.refresh(assignment)
    return assignment


def auto_assign_request(
    db: Session,
    *,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    offer_timeout_seconds: int = 90,
    exclude_driver_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
        raise ValueError("Cannot auto-assign terminal ride")

    expire_stale_dispatch_offers(db, organization_id=ride.organization_id, ride_id=ride.id)

    existing_offer = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
            HealthISFDispatchAssignment.offer_expires_at.is_not(None),
            HealthISFDispatchAssignment.offer_expires_at >= now(),
        )
        .order_by(desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    if existing_offer:
        _record_dispatch(
            db,
            ride_id=ride.id,
            action="dispatch_search_idempotent_offer_reused",
            acted_by_user_id=actor_user_id,
            driver_id=existing_offer.driver_id,
            note="Existing active offer reused for idempotent auto-assign retry",
            assignment_id=existing_offer.id,
            lifecycle_state=str(existing_offer.assignment_state),
            transition_reason="retry_safe_idempotent",
            transition_timestamp=now(),
            assignment_transition_source="auto_assign_request",
        )
        _commit_or_rollback(db)
        return {
            "ride": ride,
            "offer": existing_offer,
            "selected_driver": get_driver_by_id(db, existing_offer.driver_id) if existing_offer.driver_id else None,
            "selected_score": float(existing_offer.score) if existing_offer.score is not None else None,
            "selected_breakdown": _safe_json_parse(existing_offer.score_breakdown_json) or {},
            "candidates": [],
            "candidate_snapshot": [],
            "candidate_order_valid": True,
            "selection_parity_ok": True,
        }

    candidates = evaluate_available_drivers(
        db,
        organization_id=ride.organization_id,
        ride=ride,
        exclude_driver_ids=exclude_driver_ids,
    )
    if not candidates:
        _record_dispatch(
            db,
            ride_id=ride.id,
            action="dispatch_search_no_candidates",
            acted_by_user_id=actor_user_id,
            note="No online/available drivers after deterministic filtering",
        )
        _commit_or_rollback(db)
        return {
            "ride": ride,
            "offer": None,
            "candidates": [],
            "candidate_snapshot": [],
            "candidate_order_valid": True,
            "selection_parity_ok": True,
        }

    candidate_snapshot = snapshot_dispatch_candidates(candidates)
    candidate_order_valid = validate_candidate_order(candidate_snapshot)

    selected = candidates[0]
    assigned_ride = assign_driver_to_ride(
        db,
        ride_id=ride.id,
        driver_id=selected["driver"].id,
        actor_user_id=actor_user_id,
    )
    if not assigned_ride:
        raise ValueError("Ride not found")

    offer = _latest_assignment_for_ride(db, ride.id)
    if not offer:
        raise ValueError("Assignment offer was not created")

    now_ts = now()
    offer.score = float(selected["score"])
    offer.score_breakdown_json = json.dumps(selected["breakdown"])
    offer.timeout_seconds = max(10, int(offer_timeout_seconds or 90))
    offer.offered_at = offer.offered_at or now_ts
    offer.offer_expires_at = now_ts + timedelta(seconds=offer.timeout_seconds)
    offer.assigned_at = offer.assigned_at or getattr(assigned_ride, "assigned_at", None) or now_ts
    offer.updated_at = now_ts
    _commit_or_rollback(db)
    db.refresh(offer)
    db.refresh(assigned_ride)

    return {
        "ride": assigned_ride,
        "offer": offer,
        "selected_driver": selected["driver"],
        "selected_score": selected["score"],
        "selected_breakdown": selected["breakdown"],
        "candidate_snapshot": candidate_snapshot,
        "candidate_order_valid": candidate_order_valid,
        "selection_parity_ok": True,
        "candidates": [
            {
                "driver_id": item["driver"].id,
                "score": item["score"],
                "breakdown": item["breakdown"],
            }
            for item in candidates
        ],
    }


def _is_intake_auto_dispatch_enabled(db: Session, organization_id: str) -> bool:
    """Return True when intake should auto-assign instead of awaiting dispatcher approval."""
    env_override = os.getenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED")
    if env_override is not None:
        normalized = str(env_override).strip().lower()
        if normalized in {"0", "false", "no", "off"}:
            return False
        if normalized in {"1", "true", "yes", "on"}:
            return True

    from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService

    policy = WorkflowOrchestrationService.ensure_policy(db, organization_id)
    return bool(policy.is_enabled) and not bool(policy.approval_required)


def run_intake_dispatch_automation(
    db: Session,
    *,
    ride_id: str,
    organization_id: str,
    actor_user_id: Optional[str] = None,
    offer_timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Auto-assign on intake when enabled; otherwise persist an AI recommendation for approval."""
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")

    if ride.driver_id:
        selected_driver = get_driver_by_id(db, ride.driver_id)
        return {
            "ride": ride,
            "mode": "already_assigned",
            "recommendation": None,
            "offer": _latest_assignment_for_ride(db, ride.id),
            "selected_driver": selected_driver,
            "candidates": [],
        }

    if _is_intake_auto_dispatch_enabled(db, organization_id):
        auto_result = auto_assign_request(
            db,
            ride_id=ride_id,
            actor_user_id=actor_user_id,
            offer_timeout_seconds=offer_timeout_seconds,
        )
        if auto_result.get("offer"):
            db.refresh(ride)
            return {
                **auto_result,
                "mode": "auto_assigned",
                "recommendation": None,
            }

    recommendation_result = recommend_driver_for_ride(
        db,
        ride_id=ride_id,
        actor_user_id=actor_user_id,
    )
    recommendation_result["mode"] = "recommendation"
    recommendation_result["offer"] = None
    return recommendation_result


def reassign_expired_request(
    db: Session,
    *,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    offer_timeout_seconds: int = 90,
    reason: Optional[str] = None,
) -> dict[str, Any]:
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        raise ValueError("Ride not found")

    now_ts = now()
    expire_stale_dispatch_offers(db, organization_id=ride.organization_id, ride_id=ride.id)
    active_offers = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        )
        .all()
    )
    for row in active_offers:
        row.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        row.reassignment_pending_at = row.reassignment_pending_at or now_ts
        row.reassignment_started_at = row.reassignment_started_at or now_ts
        row.closed_reason = "reassignment_invalidated"
        row.reassignment_reason = str(reason or "reassign_requested")[:128]
        row.updated_at = now_ts
    prior_driver_ids = {
        str(row.driver_id)
        for row in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.driver_id.is_not(None),
        ).all()
        if row.driver_id
    }
    chain_row = _latest_assignment_for_ride(db, ride.id)
    reassignment_chain_id = str(chain_row.reassignment_chain_id) if chain_row and chain_row.reassignment_chain_id else str(uuid4())
    _record_dispatch(
        db,
        ride_id=ride.id,
        action="dispatch_reassignment_started",
        acted_by_user_id=actor_user_id,
        note=f"Reassignment started after excluding {len(prior_driver_ids)} prior offers",
        lifecycle_state=DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        transition_reason=str(reason or "reassign_requested")[:256],
        transition_timestamp=now_ts,
        assignment_transition_source="reassign_expired_request",
    )
    _commit_or_rollback(db)

    result = auto_assign_request(
        db,
        ride_id=ride.id,
        actor_user_id=actor_user_id,
        offer_timeout_seconds=offer_timeout_seconds,
        exclude_driver_ids=prior_driver_ids,
    )
    new_offer = result.get("offer")
    if new_offer:
        new_offer.reassignment_chain_id = reassignment_chain_id
        new_offer.reassignment_started_at = new_offer.reassignment_started_at or now_ts
        new_offer.reassignment_completed_at = now()
        new_offer.reassignment_attempt_count = max(1, int(new_offer.attempt_index or 1) - 1)
        new_offer.reassignment_reason = str(reason or "reassign_requested")[:128]
        new_offer.updated_at = now()
        _record_dispatch(
            db,
            ride_id=ride.id,
            action="dispatch_reassignment_completed",
            acted_by_user_id=actor_user_id,
            driver_id=new_offer.driver_id,
            note="Reassignment produced deterministic replacement offer",
            assignment_id=new_offer.id,
            lifecycle_state=str(new_offer.assignment_state),
            transition_reason=str(reason or "reassign_requested")[:256],
            transition_timestamp=now(),
            assignment_transition_source="reassign_expired_request",
        )
        _commit_or_rollback(db)
        db.refresh(new_offer)
    return result


def accept_assignment_offer(
    db: Session,
    *,
    offer_id: str,
    actor_user_id: Optional[str] = None,
) -> HealthISFDispatchAssignment:
    offer = db.query(HealthISFDispatchAssignment).filter(HealthISFDispatchAssignment.id == offer_id).first()
    if not offer:
        raise ValueError("Offer not found")
    if offer.assignment_state == DispatchAssignmentState.ACCEPTED.value:
        return offer
    if offer.assignment_state != DispatchAssignmentState.OFFERED.value:
        raise ValueError("Offer is not active")
    if offer.offer_expires_at and _as_utc_datetime(offer.offer_expires_at) < _as_utc_datetime(now()):
        release_driver_assignment(db, offer_id=offer.id, reason="offer_timeout", actor_user_id=actor_user_id)
        raise ValueError("Offer expired")
    if not offer.driver_id:
        raise ValueError("Offer has no driver")

    conflicting = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == offer.ride_id,
            HealthISFDispatchAssignment.id != offer.id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.ACCEPTED.value,
                    DispatchAssignmentState.EN_ROUTE_PICKUP.value,
                    DispatchAssignmentState.PICKUP_COMPLETE.value,
                    DispatchAssignmentState.DROPOFF_COMPLETE.value,
                ]
            ),
        )
        .first()
    )
    if conflicting:
        raise ValueError("Ride already has an active accepted assignment")

    current_ride = get_ride_by_id(db, offer.ride_id)
    if current_ride and current_ride.driver_id and str(current_ride.driver_id) != str(offer.driver_id):
        raise ValueError("Stale offer cannot be accepted after ownership change")

    assigned_ride = assign_driver_to_ride(
        db,
        ride_id=offer.ride_id,
        driver_id=offer.driver_id,
        actor_user_id=actor_user_id,
        allow_assigned_driver=True,
        allow_existing_assignment=True,
    )
    if not assigned_ride:
        raise ValueError("Ride not found")

    now_ts = now()
    offer.assignment_state = DispatchAssignmentState.ACCEPTED.value
    offer.assigned_at = offer.assigned_at or now_ts
    offer.accepted_at = now_ts
    offer.updated_at = now_ts
    driver = get_driver_by_id(db, offer.driver_id)
    if driver:
        driver.availability_state = "on_trip"
        driver.is_online = True
        driver.auth_state = "active"
        driver.last_seen_at = now_ts
        _set_driver_status(db, driver, DriverStatus.ASSIGNED)

    _record_dispatch(
        db,
        ride_id=offer.ride_id,
        action="driver_offer_accepted",
        acted_by_user_id=actor_user_id,
        driver_id=offer.driver_id,
        note="Driver accepted assignment offer",
        assignment_id=offer.id,
        lifecycle_state=DispatchAssignmentState.ACCEPTED.value,
        transition_reason="offer_accepted",
        transition_timestamp=now_ts,
        assignment_transition_source="accept_assignment_offer",
    )
    prior_offers = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == offer.ride_id,
            HealthISFDispatchAssignment.id != offer.id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        )
        .all()
    )
    for row in prior_offers:
        row.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        row.closed_reason = "superseded_by_acceptance"
        row.reassignment_pending_at = row.reassignment_pending_at or now_ts
        row.reassignment_reason = "superseded"
        row.updated_at = now_ts
    _commit_or_rollback(db)
    db.refresh(offer)
    return offer


def reject_assignment_offer(
    db: Session,
    *,
    offer_id: str,
    actor_user_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> HealthISFDispatchAssignment:
    offer = db.query(HealthISFDispatchAssignment).filter(HealthISFDispatchAssignment.id == offer_id).first()
    if not offer:
        raise ValueError("Offer not found")
    if offer.assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value and offer.closed_reason in {"driver_rejected", "offer_timeout"}:
        return offer
    if offer.assignment_state != DispatchAssignmentState.OFFERED.value:
        raise ValueError("Offer is not active")
    released = release_driver_assignment(
        db,
        offer_id=offer_id,
        reason="rejected",
        actor_user_id=actor_user_id,
    )
    if not released:
        raise ValueError("Offer not found")
    if reason:
        released.metadata_json = json.dumps({"reject_reason": str(reason)[:512]})
        released.reassignment_reason = str(reason)[:128]
        released.updated_at = now()
        _record_dispatch(
            db,
            ride_id=released.ride_id,
            action="driver_offer_rejected",
            acted_by_user_id=actor_user_id,
            driver_id=released.driver_id,
            note=f"Offer rejected: {str(reason)[:256]}",
            assignment_id=released.id,
            lifecycle_state=str(released.assignment_state),
            transition_reason=str(reason)[:256],
            transition_timestamp=now(),
            assignment_transition_source="reject_assignment_offer",
        )
        _commit_or_rollback(db)
        db.refresh(released)
    return released

def get_dispatch_offer_by_id(db: Session, offer_id: str) -> Optional[HealthISFDispatchAssignment]:
    return db.query(HealthISFDispatchAssignment).filter(HealthISFDispatchAssignment.id == offer_id).first()


def get_dispatch_queue(
    db: Session,
    *,
    organization_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rides = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
        )
        .order_by(HealthISFRide.requested_at.desc(), HealthISFRide.created_at.desc())
        .limit(limit)
        .all()
    )

    rows: list[dict[str, Any]] = []
    for ride in rides:
        assignment = _latest_assignment_for_ride(db, ride.id)
        assignment_state = str(assignment.assignment_state) if assignment else (
            "pending_assignment" if not ride.driver_id else DispatchAssignmentState.QUEUED.value
        )
        recommended_driver_id = str(assignment.driver_id) if assignment and assignment.driver_id else None
        recommended_driver_name = None
        recommendation_text = None
        dispatcher_message = None
        if assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value and recommended_driver_id:
            recommended_driver = get_driver_by_id(db, recommended_driver_id)
            recommended_driver_name = recommended_driver.name if recommended_driver else None
            metadata = _safe_json_parse(getattr(assignment, "metadata_json", None)) or {}
            recommendation_text = str(metadata.get("intelligence_summary") or "").strip() or None
            if recommended_driver_name:
                dispatcher_message = f"AI recommended {recommended_driver_name} — awaiting dispatcher approval"
            else:
                dispatcher_message = "AI dispatch recommendation awaiting dispatcher approval"
        elif assignment_state == "pending_assignment":
            dispatcher_message = "No available driver"
        rows.append(
            {
                "ride_id": ride.id,
                "passenger_name": ride.passenger_name,
                "requested_at": ride.requested_at,
                "ride_status": str(ride.status),
                "assignment_state": assignment_state,
                "attempt_index": int(assignment.attempt_index) if assignment else 0,
                "offered_driver_id": recommended_driver_id,
                "recommended_driver_id": recommended_driver_id,
                "recommended_driver_name": recommended_driver_name,
                "recommendation": recommendation_text,
                "offer_expires_at": assignment.offer_expires_at if assignment else None,
                "score": float(assignment.score) if assignment and assignment.score is not None else None,
                "queued_at": assignment.queued_at if assignment else ride.requested_at,
                "search_started_at": assignment.search_started_at if assignment else None,
                "offered_at": assignment.offered_at if assignment else None,
                "assigned_at": assignment.assigned_at if assignment else None,
                "accepted_at": assignment.accepted_at if assignment else None,
                "reassignment_pending_at": assignment.reassignment_pending_at if assignment else None,
                "reassignment_started_at": assignment.reassignment_started_at if assignment else None,
                "reassignment_completed_at": assignment.reassignment_completed_at if assignment else None,
                "reassignment_attempt_count": int(assignment.reassignment_attempt_count) if assignment else 0,
                "reassignment_reason": assignment.reassignment_reason if assignment else None,
                "reassignment_chain_id": assignment.reassignment_chain_id if assignment else None,
                "dispatcher_message": dispatcher_message,
            }
        )
    return rows


def get_dispatch_active_assignments(
    db: Session,
    *,
    organization_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(limit)
        .all()
    )
    active: list[dict[str, Any]] = []
    ride_ids = [str(row.ride_id) for row in rows if row.ride_id]
    lock_map: dict[str, RideAssignmentLock] = {}
    if ride_ids:
        now_ts = _as_utc_datetime(now())
        lock_rows = (
            db.query(RideAssignmentLock)
            .filter(
                RideAssignmentLock.ride_id.in_(ride_ids),
                RideAssignmentLock.expires_at > now_ts,
            )
            .all()
        )
        lock_map = {str(lock.ride_id): lock for lock in lock_rows}
    for row in rows:
        ride = get_ride_by_id(db, row.ride_id)
        driver = get_driver_by_id(db, row.driver_id) if row.driver_id else None
        if not ride:
            continue
        lock = lock_map.get(str(row.ride_id))
        active.append(
            {
                "offer_id": row.id,
                "ride_id": row.ride_id,
                "driver_id": row.driver_id,
                "driver_name": driver.name if driver else None,
                "assignment_state": row.assignment_state,
                "attempt_index": row.attempt_index,
                "offered_at": row.offered_at,
                "offer_expires_at": row.offer_expires_at,
                "assigned_at": row.assigned_at,
                "accepted_at": row.accepted_at,
                "en_route_pickup_at": row.en_route_pickup_at,
                "pickup_complete_at": row.pickup_complete_at,
                "dropoff_complete_at": row.dropoff_complete_at,
                "reassignment_pending_at": row.reassignment_pending_at,
                "reassignment_started_at": row.reassignment_started_at,
                "reassignment_completed_at": row.reassignment_completed_at,
                "reassignment_attempt_count": int(row.reassignment_attempt_count or 0),
                "reassignment_reason": row.reassignment_reason,
                "reassignment_chain_id": row.reassignment_chain_id,
                "score": row.score,
                "passenger_name": ride.passenger_name,
                "ride_status": str(ride.status),
                "ownership_locked": bool(lock),
                "ownership_locked_by_user_id": lock.locked_by_user_id if lock else None,
                "ownership_locked_at": lock.locked_at if lock else None,
                "ownership_lock_expires_at": lock.expires_at if lock else None,
            }
        )
    return active


def _get_driver_active_session(db: Session, driver_id: str) -> Optional[HealthISFDriverSession]:
    now_ts = now()
    return (
        db.query(HealthISFDriverSession)
        .filter(
            HealthISFDriverSession.driver_id == driver_id,
            HealthISFDriverSession.session_state == "active",
            HealthISFDriverSession.expires_at >= now_ts,
            HealthISFDriverSession.revoked_at.is_(None),
        )
        .order_by(desc(HealthISFDriverSession.issued_at))
        .first()
    )


def validate_driver_session_token(
    db: Session,
    *,
    driver_id: str,
    session_token: str,
) -> Optional[HealthISFDriverSession]:
    token_hash = _hash_driver_session_token(session_token)
    now_ts = _as_utc_datetime(now())
    session = (
        db.query(HealthISFDriverSession)
        .filter(
            HealthISFDriverSession.driver_id == driver_id,
            HealthISFDriverSession.session_token_hash == token_hash,
        )
        .order_by(desc(HealthISFDriverSession.issued_at))
        .first()
    )
    if not session:
        return None
    session_expires_at = _as_utc_datetime(session.expires_at)
    if session.session_state != "active" or session.revoked_at is not None or session_expires_at < now_ts:
        return None
    return session


def driver_login(
    db: Session,
    *,
    driver_id: str,
    phone: str,
    session_duration_hours: int = 12,
) -> dict[str, Any]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        raise ValueError("Driver not found")
    if not driver.is_active:
        raise ValueError("Driver is inactive")
    if not _phones_match_for_driver_login(driver.phone, phone):
        raise ValueError("Driver credentials invalid")

    existing_sessions = (
        db.query(HealthISFDriverSession)
        .filter(
            HealthISFDriverSession.driver_id == driver.id,
            HealthISFDriverSession.session_state == "active",
            HealthISFDriverSession.revoked_at.is_(None),
        )
        .all()
    )
    for session in existing_sessions:
        session.session_state = "revoked"
        session.revoked_at = now()
        session.updated_at = now()

    token = _issue_driver_session_token()
    issued_at = now()
    expires_at = issued_at + timedelta(hours=max(1, int(session_duration_hours or 12)))
    session = HealthISFDriverSession(
        id=uuid4(),
        organization_id=driver.organization_id,
        driver_id=driver.id,
        session_token_hash=_hash_driver_session_token(token),
        session_state="active",
        issued_at=issued_at,
        expires_at=expires_at,
        last_seen_at=issued_at,
        created_at=issued_at,
        updated_at=issued_at,
    )
    db.add(session)

    driver.auth_state = "active"
    driver.is_online = True
    driver.last_seen_at = issued_at
    if str(driver.availability_state or "offline").lower() == "offline":
        driver.availability_state = "available"
    _set_driver_status(db, driver, _driver_status_from_availability(driver.availability_state))

    _commit_or_rollback(db)
    db.refresh(driver)
    db.refresh(session)

    return {
        "driver": driver,
        "session": session,
        "session_token": token,
    }


def driver_logout(
    db: Session,
    *,
    driver_id: str,
    session_token: str,
) -> Optional[HealthISFDriver]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None
    session = validate_driver_session_token(db, driver_id=driver_id, session_token=session_token)
    if not session:
        raise ValueError("Driver session invalid or expired")

    session.session_state = "revoked"
    session.revoked_at = now()
    session.updated_at = now()

    driver.auth_state = "inactive"
    driver.is_online = False
    driver.availability_state = "offline"
    driver.last_seen_at = now()
    _set_driver_status(db, driver, DriverStatus.OFFLINE)

    _commit_or_rollback(db)
    db.refresh(driver)
    return driver


def set_driver_live_availability(
    db: Session,
    *,
    driver_id: str,
    availability_state: str,
    session_token: Optional[str] = None,
) -> Optional[HealthISFDriver]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None
    if session_token:
        session = validate_driver_session_token(db, driver_id=driver_id, session_token=session_token)
        if not session:
            raise ValueError("Driver session invalid or expired")
        session.last_seen_at = now()
        session.updated_at = now()

    normalized = _normalize_driver_availability_state(availability_state)
    driver.availability_state = normalized
    driver.is_online = normalized != "offline"
    driver.auth_state = "active" if driver.is_online else "inactive"
    driver.last_seen_at = now()
    _set_driver_status(db, driver, _driver_status_from_availability(normalized))

    _commit_or_rollback(db)
    db.refresh(driver)
    return driver


def driver_heartbeat(
    db: Session,
    *,
    driver_id: str,
    session_token: str,
) -> Optional[HealthISFDriver]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None
    session = validate_driver_session_token(db, driver_id=driver_id, session_token=session_token)
    if not session:
        raise ValueError("Driver session invalid or expired")

    now_ts = now()
    session.last_seen_at = now_ts
    session.updated_at = now_ts
    driver.last_seen_at = now_ts
    driver.is_online = True
    if str(driver.auth_state or "inactive").lower() != "active":
        driver.auth_state = "active"
    if str(driver.availability_state or "offline").lower() == "offline":
        driver.availability_state = "available"
    _set_driver_status(db, driver, _driver_status_from_availability(driver.availability_state))

    _commit_or_rollback(db)
    db.refresh(driver)
    return driver


def get_active_drivers(
    db: Session,
    *,
    organization_id: str,
    available_only: bool = False,
    limit: int = 200,
) -> list[HealthISFDriver]:
    query = db.query(HealthISFDriver).filter(
        HealthISFDriver.organization_id == organization_id,
        HealthISFDriver.is_active == True,
        HealthISFDriver.auth_state == "active",
        HealthISFDriver.is_online == True,
    )
    if available_only:
        query = query.filter(HealthISFDriver.availability_state == "available")
    return query.order_by(HealthISFDriver.updated_at.desc()).limit(limit).all()


def get_driver_runtime_status(
    db: Session,
    *,
    driver_id: str,
    session_token: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None
    active_session = _get_driver_active_session(db, driver_id)
    session_valid = False
    session_state = active_session.session_state if active_session else "inactive"
    expires_at = active_session.expires_at if active_session else None
    if session_token:
        session_valid = validate_driver_session_token(db, driver_id=driver_id, session_token=session_token) is not None
    else:
        session_valid = active_session is not None

    active_ride = _active_ride_for_driver(db, driver_id)
    return {
        "driver": driver,
        "session_valid": session_valid,
        "session_state": session_state,
        "expires_at": expires_at,
        "active_ride_id": active_ride.id if active_ride else None,
    }


def get_active_driver_pool_metrics(
    db: Session,
    *,
    organization_id: str,
) -> dict[str, int]:
    rows = db.query(HealthISFDriver).filter(
        HealthISFDriver.organization_id == organization_id,
        HealthISFDriver.is_active == True,
    ).all()
    metrics = {
        "total_active": len(rows),
        "online": 0,
        "available": 0,
        "assigned": 0,
        "on_trip": 0,
        "unavailable": 0,
        "offline": 0,
    }
    for row in rows:
        availability = str(getattr(row, "availability_state", "offline") or "offline").lower()
        if bool(getattr(row, "is_online", False)):
            metrics["online"] += 1
        if availability == "available":
            metrics["available"] += 1
        elif availability == "on_trip":
            metrics["on_trip"] += 1
            metrics["assigned"] += 1
        elif availability == "unavailable":
            metrics["unavailable"] += 1
        else:
            metrics["offline"] += 1
    return metrics


def _set_customer_request_status(
    request_obj: HealthISFCustomerRideRequest,
    status: str,
    *,
    ts: Optional[datetime] = None,
) -> None:
    current_ts = ts or now()
    normalized = _normalize_customer_request_status(status)
    request_obj.dispatch_status = normalized

    if normalized == CustomerRequestStatus.PENDING.value:
        request_obj.pending_at = request_obj.pending_at or current_ts
    elif normalized == CustomerRequestStatus.APPROVED.value:
        request_obj.broadcasted_at = request_obj.broadcasted_at or current_ts
    elif normalized == CustomerRequestStatus.DISPATCHABLE.value:
        request_obj.accepted_at = request_obj.accepted_at or current_ts
    elif normalized == CustomerRequestStatus.BROADCASTED.value:
        request_obj.broadcasted_at = request_obj.broadcasted_at or current_ts
    elif normalized == CustomerRequestStatus.ACCEPTED.value:
        request_obj.accepted_at = request_obj.accepted_at or current_ts
    elif normalized == CustomerRequestStatus.ASSIGNED.value:
        request_obj.assigned_at = request_obj.assigned_at or current_ts
    elif normalized == CustomerRequestStatus.IN_PROGRESS.value:
        request_obj.in_progress_at = request_obj.in_progress_at or current_ts
    elif normalized == CustomerRequestStatus.COMPLETED.value:
        request_obj.completed_at = request_obj.completed_at or current_ts
    elif normalized == CustomerRequestStatus.CANCELLED.value:
        request_obj.cancelled_at = request_obj.cancelled_at or current_ts


def _request_status_from_lifecycle(lifecycle_state: str) -> str:
    state = RideLifecycleManager.normalize_state(lifecycle_state)
    if state in {RideStatus.REQUESTED.value}:
        return CustomerRequestStatus.PENDING.value
    if state in {RideStatus.QUEUED.value}:
        return CustomerRequestStatus.DISPATCHABLE.value
    if state in {RideStatus.ASSIGNED.value}:
        return CustomerRequestStatus.ASSIGNED.value
    if state in {
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.ESCALATED.value,
    }:
        return CustomerRequestStatus.IN_PROGRESS.value
    if state == RideStatus.COMPLETED.value:
        return CustomerRequestStatus.COMPLETED.value
    if state in {RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
        return CustomerRequestStatus.CANCELLED.value
    return CustomerRequestStatus.PENDING.value


def get_customer_ride_request_by_id(db: Session, request_id: str) -> Optional[HealthISFCustomerRideRequest]:
    return (
        db.query(HealthISFCustomerRideRequest)
        .filter(HealthISFCustomerRideRequest.id == request_id)
        .first()
    )


def get_customer_request_by_ride_id(db: Session, ride_id: str) -> Optional[HealthISFCustomerRideRequest]:
    return (
        db.query(HealthISFCustomerRideRequest)
        .filter(HealthISFCustomerRideRequest.ride_id == ride_id)
        .first()
    )


def sync_customer_request_from_ride(
    db: Session,
    ride: HealthISFRide,
    *,
    explicit_status: Optional[str] = None,
) -> Optional[HealthISFCustomerRideRequest]:
    request_obj = get_customer_request_by_ride_id(db, ride.id)
    if not request_obj:
        return None

    status_to_apply = explicit_status or _request_status_from_lifecycle(getattr(ride, "lifecycle_state", None) or str(ride.status))
    _set_customer_request_status(request_obj, status_to_apply)
    request_obj.updated_at = now()
    db.flush()
    return request_obj


def _ensure_completion_billing_records(db: Session, ride: HealthISFRide) -> None:
    if not ride.driver_id:
        return

    trip = (
        db.query(HealthISFTrip)
        .filter(HealthISFTrip.ride_id == ride.id)
        .order_by(desc(HealthISFTrip.created_at))
        .first()
    )
    end_time = ride.completed_at or now()
    start_time = ride.accepted_at or ride.assigned_at or ride.requested_at or end_time
    duration_minutes: int | None = None
    if start_time and end_time:
        norm_start = start_time.replace(tzinfo=timezone.utc) if start_time.tzinfo is None else start_time.astimezone(timezone.utc)
        norm_end = end_time.replace(tzinfo=timezone.utc) if end_time.tzinfo is None else end_time.astimezone(timezone.utc)
        if norm_end >= norm_start:
            duration_minutes = int((norm_end - norm_start).total_seconds() // 60)

    if not trip:
        trip = HealthISFTrip(
            id=uuid4(),
            ride_id=ride.id,
            driver_id=ride.driver_id,
            status=TripStatus.COMPLETED,
            start_time=start_time,
            end_time=end_time,
            distance_miles=float(ride.estimated_distance_miles or 0.0) or None,
            duration_minutes=duration_minutes,
            created_at=now(),
            updated_at=now(),
        )
        db.add(trip)
        db.flush()
    else:
        trip.status = TripStatus.COMPLETED
        trip.end_time = trip.end_time or end_time
        if trip.start_time is None:
            trip.start_time = start_time
        if trip.distance_miles is None and ride.estimated_distance_miles is not None:
            trip.distance_miles = float(ride.estimated_distance_miles)
        if trip.duration_minutes is None and duration_minutes is not None:
            trip.duration_minutes = duration_minutes

    existing_payout = (
        db.query(HealthISFPayout)
        .filter(HealthISFPayout.trip_id == trip.id)
        .first()
    )
    if existing_payout:
        return

    estimated_miles = float(ride.estimated_distance_miles or 0.0)
    amount_usd = round(max(10.0, estimated_miles * 2.5 if estimated_miles > 0 else 25.0), 2)
    payout = HealthISFPayout(
        id=uuid4(),
        driver_id=ride.driver_id,
        trip_id=trip.id,
        amount_usd=amount_usd,
        status="pending",
        description=f"Auto-generated payout for completed ride {ride.id[:8]}",
        created_at=now(),
        updated_at=now(),
    )
    db.add(payout)
    db.flush()


def list_customer_ride_requests(
    db: Session,
    *,
    organization_id: str,
    dispatch_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 200,
    prioritize: bool = True,
) -> list[HealthISFCustomerRideRequest]:
    query = db.query(HealthISFCustomerRideRequest).filter(
        HealthISFCustomerRideRequest.organization_id == organization_id
    )
    if dispatch_status and dispatch_status != "all":
        query = query.filter(
            HealthISFCustomerRideRequest.dispatch_status == _normalize_customer_request_status(dispatch_status)
        )
    if not prioritize:
        return query.order_by(desc(HealthISFCustomerRideRequest.created_at)).offset(skip).limit(limit).all()

    status_rank = {
        CustomerRequestStatus.APPROVED.value: 0,
        CustomerRequestStatus.DISPATCHABLE.value: 1,
        CustomerRequestStatus.BROADCASTED.value: 2,
        CustomerRequestStatus.ACCEPTED.value: 3,
        CustomerRequestStatus.ASSIGNED.value: 4,
        CustomerRequestStatus.IN_PROGRESS.value: 5,
        CustomerRequestStatus.PENDING.value: 6,
        CustomerRequestStatus.COMPLETED.value: 7,
        CustomerRequestStatus.CANCELLED.value: 8,
    }

    rows = query.all()

    def _sort_key(row: HealthISFCustomerRideRequest) -> tuple[int, datetime, float]:
        rank = status_rank.get(str(row.dispatch_status or "").lower(), 50)
        scheduled = _coerce_utc(row.scheduled_time) or datetime.max.replace(tzinfo=timezone.utc)
        created = _coerce_utc(row.created_at) or now()
        return (rank, scheduled, -created.timestamp())

    ordered = sorted(rows, key=_sort_key)
    end = skip + limit
    return ordered[skip:end]


def list_customer_ride_requests_by_phone(
    db: Session,
    *,
    organization_id: str,
    rider_phone: str,
    limit: int = 100,
) -> list[HealthISFCustomerRideRequest]:
    normalized_phone = str(rider_phone or "").strip()
    if not normalized_phone:
        return []
    return (
        db.query(HealthISFCustomerRideRequest)
        .filter(
            HealthISFCustomerRideRequest.organization_id == organization_id,
            HealthISFCustomerRideRequest.rider_phone == normalized_phone,
        )
        .order_by(desc(HealthISFCustomerRideRequest.created_at))
        .limit(limit)
        .all()
    )


def _phone_digits(value: str | None) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def list_rides_for_passenger_phone(
    db: Session,
    *,
    organization_id: str,
    rider_phone: str,
    limit: int = 100,
) -> list[HealthISFRide]:
    target_digits = _phone_digits(rider_phone)
    if len(target_digits) < 7:
        return []
    scan_limit = max(limit * 6, 240)
    rows = (
        db.query(HealthISFRide)
        .filter(HealthISFRide.organization_id == organization_id)
        .order_by(desc(HealthISFRide.created_at))
        .limit(scan_limit)
        .all()
    )
    matched = [row for row in rows if _phone_digits(row.passenger_phone) == target_digits]
    return matched[:limit]


def get_customer_active_ride_for_phone(
    db: Session,
    *,
    organization_id: str,
    rider_phone: str,
) -> Optional[HealthISFRide]:
    requests = list_customer_ride_requests_by_phone(
        db,
        organization_id=organization_id,
        rider_phone=rider_phone,
        limit=120,
    )
    for request_row in requests:
        ride = get_ride_by_id(db, request_row.ride_id)
        if not ride or ride.organization_id != organization_id:
            continue
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(ride.status))
        if lifecycle_state not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
            return ride
    for ride in list_rides_for_passenger_phone(
        db,
        organization_id=organization_id,
        rider_phone=rider_phone,
        limit=40,
    ):
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(ride.status))
        if lifecycle_state not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
            return ride
    return None


def get_provider_transport_queue(
    db: Session,
    *,
    organization_id: str,
    provider_id: str,
    include_completed: bool = False,
    limit: int = 200,
) -> list[dict[str, Any]]:
    rows = (
        db.query(HealthISFCustomerRideRequest)
        .join(HealthISFRide, HealthISFRide.id == HealthISFCustomerRideRequest.ride_id)
        .filter(
            HealthISFCustomerRideRequest.organization_id == organization_id,
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.provider_id == provider_id,
        )
        .order_by(desc(HealthISFCustomerRideRequest.updated_at))
        .limit(limit)
        .all()
    )

    queue: list[dict[str, Any]] = []
    for request_row in rows:
        ride = get_ride_by_id(db, request_row.ride_id)
        if not ride:
            continue
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(ride.status))
        if not include_completed and lifecycle_state in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
            continue
        queue.append(
            {
                "request_id": request_row.id,
                "ride_id": ride.id,
                "rider_name": request_row.rider_name,
                "rider_phone": request_row.rider_phone,
                "pickup_address": request_row.pickup_address,
                "dropoff_address": request_row.dropoff_address,
                "scheduled_time": request_row.scheduled_time,
                "dispatch_status": request_row.dispatch_status,
                "ride_status": str(ride.status),
                "lifecycle_state": lifecycle_state,
                "driver_id": ride.driver_id,
                "notes": request_row.notes,
                "updated_at": request_row.updated_at,
            }
        )
    return queue


def append_provider_request_note(
    db: Session,
    *,
    organization_id: str,
    request_id: str,
    note: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFCustomerRideRequest]:
    request_row = get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != organization_id:
        return None

    note_line = str(note or "").strip()
    if not note_line:
        raise ValueError("Provider note is required")

    existing = str(request_row.notes or "").strip()
    timestamp = now().isoformat()
    appended = f"[{timestamp}] provider_note: {note_line}"
    request_row.notes = (existing + "\n" + appended).strip() if existing else appended
    request_row.updated_at = now()
    db.flush()

    _record_dispatch(
        db,
        ride_id=request_row.ride_id,
        action="provider_request_note",
        acted_by_user_id=actor_user_id,
        note=note_line[:512],
        request_id=request_row.id,
        lifecycle_state=str(request_row.dispatch_status or "pending"),
        transition_reason="provider_note",
        transition_timestamp=now(),
        assignment_transition_source="provider_workspace",
    )
    _commit_or_rollback(db)
    db.refresh(request_row)
    return request_row


def get_driver_active_offer(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> Optional[HealthISFDispatchAssignment]:
    return (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .first()
    )


def get_admin_command_center_summary(db: Session, *, organization_id: str) -> dict[str, Any]:
    queue_metrics = get_customer_ride_queue_metrics(db, organization_id=organization_id)
    dispatch_queue = get_dispatch_queue(db, organization_id=organization_id, limit=300)
    active_assignments = get_dispatch_active_assignments(db, organization_id=organization_id, limit=300)

    assignment_states = (
        db.query(
            HealthISFDispatchAssignment.assignment_state,
            func.count(HealthISFDispatchAssignment.id),
        )
        .filter(HealthISFDispatchAssignment.organization_id == organization_id)
        .group_by(HealthISFDispatchAssignment.assignment_state)
        .all()
    )
    assignment_breakdown = {str(state): int(count) for state, count in assignment_states}

    recent_dispatch_events = (
        db.query(HealthISFDispatchLog)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchLog.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
        .order_by(desc(HealthISFDispatchLog.created_at))
        .limit(40)
        .all()
    )

    rejected_offers = assignment_breakdown.get(DispatchAssignmentState.REJECTED.value, 0)
    reassignment_events = sum(
        1
        for item in recent_dispatch_events
        if str(item.action or "").lower() in {
            "assignment-reassigned",
            "reassignment-started",
            "reassignment-completed",
            "dispatcher_request_reassign",
        }
    )

    return {
        "organization_id": organization_id,
        "generated_at": now().isoformat(),
        "queue_metrics": queue_metrics,
        "dispatch_queue_count": len(dispatch_queue),
        "active_assignment_count": len(active_assignments),
        "assignment_state_breakdown": assignment_breakdown,
        "rejected_offer_count": rejected_offers,
        "reassignment_event_count": reassignment_events,
        "recent_dispatch_actions": [
            {
                "ride_id": row.ride_id,
                "action": row.action,
                "note": row.note,
                "lifecycle_state": row.lifecycle_state,
                "created_at": row.created_at,
            }
            for row in recent_dispatch_events[:12]
        ],
    }


def _estimated_eta_minutes(ride: Optional[HealthISFRide]) -> Optional[int]:
    if not ride:
        return None
    duration = int(ride.estimated_duration_minutes or 0)
    if duration <= 0:
        return None
    anchor = ride.accepted_at or ride.requested_at or now()
    elapsed = max(0, int(((_as_utc_datetime(now()) - _as_utc_datetime(anchor)).total_seconds()) / 60))
    return max(1, duration - elapsed)


def get_driver_live_workspace_data(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> dict[str, Any]:
    driver = get_driver_by_id(db, driver_id)
    if not driver or driver.organization_id != organization_id:
        raise ValueError("Driver not found")

    assignment = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.ACCEPTED.value,
                    DispatchAssignmentState.EN_ROUTE_PICKUP.value,
                    DispatchAssignmentState.PICKUP_COMPLETE.value,
                ]
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .first()
    )
    ride = get_ride_by_id(db, assignment.ride_id) if assignment and assignment.ride_id else None
    runtime = get_driver_runtime_status(db, driver_id=driver_id, session_token=None)

    countdown = None
    if assignment and assignment.offer_expires_at:
        countdown = max(0, int((_as_utc_datetime(assignment.offer_expires_at) - _as_utc_datetime(now())).total_seconds()))

    stale_heartbeat = False
    if driver.last_seen_at:
        stale_heartbeat = (_as_utc_datetime(now()) - _as_utc_datetime(driver.last_seen_at)).total_seconds() > 300
    safety_status = "ok"
    if stale_heartbeat:
        safety_status = "reconnect_required"
    if str(driver.availability_state or "").lower() == "offline":
        safety_status = "offline"

    return {
        "driver": driver,
        "assignment": assignment,
        "ride": ride,
        "countdown": countdown,
        "eta_minutes": _estimated_eta_minutes(ride),
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
    }


def list_rider_event_feed(
    db: Session,
    *,
    organization_id: str,
    rider_phone: str,
    limit: int = 120,
) -> list[dict[str, Any]]:
    requests = list_customer_ride_requests_by_phone(
        db,
        organization_id=organization_id,
        rider_phone=rider_phone,
        limit=limit,
    )
    ride_ids = [row.ride_id for row in requests if row.ride_id]
    if not ride_ids:
        return []

    action_to_event = {
        "assignment-issued": "driver-assigned",
        "driver_offer_issued": "driver-assigned",
        "assignment-accepted": "driver-arriving",
        "driver_offer_accepted": "driver-arriving",
        "pickup-arrived": "pickup-arrived",
        "rider-loaded": "trip-started",
        "trip-started": "trip-started",
        "trip-progress": "approaching-destination",
        "trip-completed": "trip-completed",
        "assignment-completed": "trip-completed",
    }

    logs = (
        db.query(HealthISFDispatchLog)
        .filter(HealthISFDispatchLog.ride_id.in_(ride_ids))
        .order_by(desc(HealthISFDispatchLog.created_at))
        .limit(limit)
        .all()
    )
    feed: list[dict[str, Any]] = []
    for row in logs:
        action = str(row.action or "").lower()
        event_name = action_to_event.get(action)
        if not event_name:
            continue
        feed.append(
            {
                "event_name": event_name,
                "timestamp": row.created_at,
                "ride_id": row.ride_id,
                "driver_id": row.driver_id,
                "message": row.note or action.replace("_", " "),
            }
        )
    feed.reverse()
    return feed


def get_admin_live_operations_data(db: Session, *, organization_id: str) -> dict[str, Any]:
    now_ts = _as_utc_datetime(now())
    active_assignments = get_dispatch_active_assignments(db, organization_id=organization_id, limit=300)
    dispatch_queue = get_dispatch_queue(db, organization_id=organization_id, limit=300)
    drivers = get_all_drivers(db, skip=0, limit=500)

    active_rides: list[dict[str, Any]] = []
    awaiting_assignment: list[dict[str, Any]] = []
    stale_assignments: list[dict[str, Any]] = []

    active_map: dict[str, dict[str, Any]] = {str(item.get("ride_id")): item for item in active_assignments}
    for row in dispatch_queue:
        ride_id = str(row.get("ride_id") or "")
        item = {
            "ride_id": ride_id,
            "passenger_name": row.get("passenger_name") or "Unknown passenger",
            "ride_status": str(row.get("ride_status") or "pending"),
            "assignment_state": str(row.get("assignment_state") or "queued"),
            "driver_id": row.get("offered_driver_id"),
            "driver_name": None,
            "provider_id": None,
            "requested_at": row.get("requested_at"),
            "offer_expires_at": row.get("offer_expires_at"),
            "stale_assignment": False,
        }
        offer_expires_at = row.get("offer_expires_at")
        if offer_expires_at:
            item["stale_assignment"] = _as_utc_datetime(offer_expires_at) <= now_ts
        if item["assignment_state"] in {"queued", "reassignment_pending", "expired", "rejected"}:
            awaiting_assignment.append(item)
        else:
            active_rides.append(item)
        if item["stale_assignment"]:
            stale_assignments.append(item)

    for item in active_rides:
        linked = active_map.get(str(item.get("ride_id") or ""))
        if linked and linked.get("driver_name"):
            item["driver_name"] = linked.get("driver_name")

    availability = {
        "available": 0,
        "assigned": 0,
        "busy": 0,
        "unavailable": 0,
        "offline": 0,
    }
    for driver in drivers:
        if driver.organization_id != organization_id:
            continue
        status = str(driver.status or "offline").lower()
        if status in availability:
            availability[status] += 1
        elif status in {"en_route_pickup", "waiting_at_pickup", "in_transit"}:
            availability["busy"] += 1
        else:
            availability["unavailable"] += 1

    recent_logs = (
        db.query(HealthISFDispatchLog)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchLog.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
        .order_by(desc(HealthISFDispatchLog.created_at))
        .limit(200)
        .all()
    )
    counters: dict[str, int] = {}
    provider_alerts: list[dict[str, Any]] = []
    for row in recent_logs:
        key = str(row.action or "unknown")
        counters[key] = counters.get(key, 0) + 1
        if key in {"provider-ready", "provider-delay", "provider-note-added", "provider_request_note"}:
            provider_alerts.append(
                {
                    "severity": "warn" if key == "provider-delay" else "info",
                    "alert_type": key,
                    "ride_id": row.ride_id,
                    "driver_id": row.driver_id,
                    "message": row.note or key,
                    "created_at": row.created_at,
                }
            )

    return {
        "organization_id": organization_id,
        "generated_at": now(),
        "active_rides": active_rides,
        "awaiting_assignment": awaiting_assignment,
        "stale_assignments": stale_assignments,
        "driver_availability_board": availability,
        "provider_coordination_alerts": provider_alerts[:50],
        "dispatch_event_counters": counters,
    }


def get_admin_dispatch_alerts_data(db: Session, *, organization_id: str) -> dict[str, Any]:
    now_ts = _as_utc_datetime(now())
    alerts: list[dict[str, Any]] = []
    emitted_keys: set[str] = set()

    def _emit_alert(
        *,
        severity: str,
        alert_type: str,
        message: str,
        created_at: datetime,
        ride_id: Optional[str] = None,
        driver_id: Optional[str] = None,
    ) -> None:
        normalized_severity = str(severity or "warn").lower()
        if normalized_severity not in {"info", "warn", "high", "critical"}:
            normalized_severity = "warn"
        key = f"{alert_type}:{ride_id or ''}:{driver_id or ''}"
        if key in emitted_keys:
            return
        emitted_keys.add(key)
        alerts.append(
            {
                "severity": normalized_severity,
                "alert_type": str(alert_type),
                "ride_id": ride_id,
                "driver_id": driver_id,
                "message": str(message),
                "created_at": _as_utc_datetime(created_at),
                "replay_safe": True,
                "replay_safe_key": hashlib.sha256(
                    f"{alert_type}:{ride_id or ''}:{driver_id or ''}:{_as_utc_datetime(created_at).isoformat()}".encode("utf-8")
                ).hexdigest(),
            }
        )

    counters = {
        "stale_assignment": 0,
        "awaiting_assignment": 0,
        "provider_delay": 0,
        "dispatch_exception": 0,
        "expired_assignment": 0,
        "driver_overload": 0,
        "orphaned_ride": 0,
        "duplicate_active_assignment": 0,
        "assignment_pending_timeout": 0,
        "accepted_without_dispatch_continuity": 0,
        "driver_ack_timeout": 0,
        "stalled_pickup_transition": 0,
        "unresolved_escalation_loop": 0,
    }

    active_assignment_count_rows = (
        db.query(
            HealthISFDispatchAssignment.ride_id.label("ride_id"),
            func.count(HealthISFDispatchAssignment.id).label("active_count"),
            func.max(HealthISFDispatchAssignment.updated_at).label("latest_updated_at"),
        )
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .group_by(HealthISFDispatchAssignment.ride_id)
        .all()
    )
    active_assignment_counts: dict[str, int] = {
        str(getattr(row, "ride_id", "") or ""): int(getattr(row, "active_count", 0) or 0)
        for row in active_assignment_count_rows
        if str(getattr(row, "ride_id", "") or "")
    }
    latest_assignment_updates: dict[str, datetime] = {
        str(getattr(row, "ride_id", "") or ""): _as_utc_datetime(getattr(row, "latest_updated_at", None) or now_ts)
        for row in active_assignment_count_rows
        if str(getattr(row, "ride_id", "") or "")
    }
    for ride_id, active_count in active_assignment_counts.items():
        if active_count <= 1:
            continue
        counters["duplicate_active_assignment"] += 1
        _emit_alert(
            severity="critical" if active_count >= 3 else "high",
            alert_type="duplicate_active_assignment",
            ride_id=ride_id,
            driver_id=None,
            message=f"Ride has {active_count} concurrent active assignment records and requires dispatch reconciliation.",
            created_at=latest_assignment_updates.get(ride_id, now_ts),
        )

    expired_assignments = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.EXPIRED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                ]
            ),
            or_(
                and_(
                    HealthISFDispatchAssignment.offer_expires_at.is_not(None),
                    HealthISFDispatchAssignment.offer_expires_at <= now_ts,
                ),
                and_(
                    HealthISFDispatchAssignment.expired_at.is_not(None),
                    HealthISFDispatchAssignment.expired_at <= now_ts,
                ),
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(300)
        .all()
    )
    for assignment in expired_assignments:
        counters["expired_assignment"] += 1
        counters["stale_assignment"] += 1
        _emit_alert(
            severity="high",
            alert_type="expired_assignment",
            ride_id=assignment.ride_id,
            driver_id=assignment.driver_id,
            message="Assignment offer expired and requires reassignment intervention.",
            created_at=assignment.expired_at or assignment.offer_expires_at or assignment.updated_at or now_ts,
        )

    offered_assignments = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.offered_at), desc(HealthISFDispatchAssignment.updated_at))
        .limit(300)
        .all()
    )
    for assignment in offered_assignments:
        offered_at = getattr(assignment, "offered_at", None)
        if not offered_at:
            continue
        expires_at = getattr(assignment, "offer_expires_at", None)
        if expires_at and _as_utc_datetime(expires_at) <= now_ts:
            continue
        timeout_seconds = max(60, min(300, int(getattr(assignment, "timeout_seconds", 90) or 90)))
        if (_as_utc_datetime(offered_at) + timedelta(seconds=timeout_seconds)) > now_ts:
            continue
        counters["driver_ack_timeout"] += 1
        _emit_alert(
            severity="high",
            alert_type="driver_ack_timeout",
            ride_id=assignment.ride_id,
            driver_id=assignment.driver_id,
            message="Driver acknowledgment SLA exceeded for active assignment offer.",
            created_at=offered_at,
        )

    pending_timeout_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.reassignment_pending_at), desc(HealthISFDispatchAssignment.updated_at))
        .limit(300)
        .all()
    )
    for assignment in pending_timeout_rows:
        pending_since = (
            getattr(assignment, "reassignment_pending_at", None)
            or getattr(assignment, "updated_at", None)
            or getattr(assignment, "created_at", None)
            or now_ts
        )
        if (_as_utc_datetime(now_ts) - _as_utc_datetime(pending_since)).total_seconds() < 900:
            continue
        counters["assignment_pending_timeout"] += 1
        _emit_alert(
            severity="high",
            alert_type="assignment_pending_timeout",
            ride_id=assignment.ride_id,
            driver_id=assignment.driver_id,
            message="Ride remains in reassignment_pending beyond operational SLA.",
            created_at=pending_since,
        )

    active_statuses = [
        RideStatus.ACCEPTED.value,
        RideStatus.ASSIGNED.value,
        RideStatus.IN_TRANSIT.value,
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
    ]
    overloaded_driver_rows = (
        db.query(HealthISFRide.driver_id, func.count(HealthISFRide.id).label("active_count"))
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id.is_not(None),
            HealthISFRide.status.in_(active_statuses),
        )
        .group_by(HealthISFRide.driver_id)
        .having(func.count(HealthISFRide.id) >= 3)
        .all()
    )
    for row in overloaded_driver_rows:
        active_count = int(getattr(row, "active_count", 0) or 0)
        driver_id = str(getattr(row, "driver_id", "") or "")
        counters["driver_overload"] += 1
        _emit_alert(
            severity="critical" if active_count >= 4 else "high",
            alert_type="driver_overload",
            ride_id=None,
            driver_id=driver_id,
            message=f"Driver has {active_count} concurrent active rides; redistribution recommended.",
            created_at=now_ts,
        )

    orphan_candidate_rides = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_(
                [
                    RideStatus.ASSIGNED.value,
                    RideStatus.DRIVER_EN_ROUTE.value,
                    RideStatus.ARRIVED.value,
                    RideStatus.RIDER_ONBOARD.value,
                    RideStatus.IN_PROGRESS.value,
                    RideStatus.IN_TRANSIT.value,
                ]
            ),
        )
        .order_by(desc(HealthISFRide.updated_at))
        .limit(300)
        .all()
    )
    for ride in orphan_candidate_rides:
        ride_id = str(ride.id)
        active_assignment_count = int(active_assignment_counts.get(ride_id, 0) or 0)
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
        if lifecycle_state not in {
            RideStatus.ASSIGNED.value,
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ARRIVED.value,
            RideStatus.RIDER_ONBOARD.value,
            RideStatus.IN_PROGRESS.value,
        }:
            continue
        if ride.driver_id and active_assignment_count > 0:
            continue
        counters["orphaned_ride"] += 1
        _emit_alert(
            severity="high",
            alert_type="orphaned_ride",
            ride_id=ride_id,
            driver_id=str(ride.driver_id) if ride.driver_id else None,
            message="Ride lifecycle is active without a consistent active assignment record.",
            created_at=getattr(ride, "updated_at", None) or getattr(ride, "requested_at", None) or now_ts,
        )

    accepted_continuity_rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_(
                [
                    RideStatus.ACCEPTED.value,
                    RideStatus.DRIVER_EN_ROUTE.value,
                    RideStatus.ARRIVED.value,
                    RideStatus.RIDER_ONBOARD.value,
                    RideStatus.IN_PROGRESS.value,
                    RideStatus.IN_TRANSIT.value,
                ]
            ),
            HealthISFRide.accepted_at.is_not(None),
        )
        .order_by(desc(HealthISFRide.updated_at))
        .limit(300)
        .all()
    )
    for ride in accepted_continuity_rows:
        ride_id = str(ride.id)
        if int(active_assignment_counts.get(ride_id, 0) or 0) > 0:
            continue
        counters["accepted_without_dispatch_continuity"] += 1
        _emit_alert(
            severity="critical",
            alert_type="accepted_without_dispatch_continuity",
            ride_id=ride_id,
            driver_id=str(ride.driver_id) if ride.driver_id else None,
            message="Ride is accepted but missing active dispatch assignment continuity.",
            created_at=getattr(ride, "accepted_at", None) or getattr(ride, "updated_at", None) or now_ts,
        )

    stalled_pickup_rows = (
        db.query(HealthISFDispatchAssignment, HealthISFRide)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchAssignment.ride_id)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.ACCEPTED.value,
                    DispatchAssignmentState.EN_ROUTE_PICKUP.value,
                ]
            ),
            HealthISFRide.status.in_(
                [
                    RideStatus.ACCEPTED.value,
                    RideStatus.DRIVER_EN_ROUTE.value,
                ]
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(300)
        .all()
    )
    for assignment, ride in stalled_pickup_rows:
        transition_at = (
            assignment.en_route_pickup_at
            or assignment.accepted_at
            or assignment.assigned_at
            or assignment.updated_at
            or now_ts
        )
        if (_as_utc_datetime(now_ts) - _as_utc_datetime(transition_at)).total_seconds() < 1200:
            continue
        counters["stalled_pickup_transition"] += 1
        _emit_alert(
            severity="high",
            alert_type="stalled_pickup_transition",
            ride_id=assignment.ride_id,
            driver_id=assignment.driver_id,
            message="Ride remains in accepted/en_route_pickup without pickup progression beyond SLA.",
            created_at=transition_at,
        )

    unresolved_escalations = (
        db.query(HealthISFWorkflowEscalation)
        .filter(
            HealthISFWorkflowEscalation.organization_id == organization_id,
            HealthISFWorkflowEscalation.resolved_at.is_(None),
        )
        .order_by(desc(HealthISFWorkflowEscalation.created_at))
        .limit(300)
        .all()
    )
    escalation_loop_state: dict[str, dict[str, Any]] = {}
    for escalation in unresolved_escalations:
        incident_id = str(getattr(escalation, "incident_id", "") or "")
        if not incident_id:
            continue
        state = escalation_loop_state.setdefault(
            incident_id,
            {
                "count": 0,
                "max_level": 0,
                "created_at": getattr(escalation, "created_at", None) or now_ts,
                "target_role": str(getattr(escalation, "target_role", "") or "operations"),
            },
        )
        state["count"] = int(state["count"]) + 1
        state["max_level"] = max(int(state["max_level"]), int(getattr(escalation, "escalation_level", 0) or 0))
        created_at = getattr(escalation, "created_at", None)
        if created_at and _as_utc_datetime(created_at) < _as_utc_datetime(state["created_at"]):
            state["created_at"] = created_at

    loop_incident_ids = [incident_id for incident_id, state in escalation_loop_state.items() if int(state["count"]) > 1 or int(state["max_level"]) > 1]
    incident_ride_map: dict[str, str | None] = {}
    if loop_incident_ids:
        incident_rows = (
            db.query(HealthISFWorkflowIncident.id, HealthISFWorkflowIncident.ride_id)
            .filter(HealthISFWorkflowIncident.id.in_(loop_incident_ids))
            .all()
        )
        incident_ride_map = {str(row.id): (str(row.ride_id) if row.ride_id else None) for row in incident_rows}
    for incident_id in loop_incident_ids:
        state = escalation_loop_state[incident_id]
        counters["unresolved_escalation_loop"] += 1
        _emit_alert(
            severity="critical" if int(state["max_level"]) >= 3 else "high",
            alert_type="unresolved_escalation_loop",
            ride_id=incident_ride_map.get(incident_id),
            driver_id=None,
            message=(
                f"Incident escalation loop remains unresolved across {int(state['count'])} escalation records "
                f"for target role {state['target_role']}."
            ),
            created_at=state["created_at"],
        )

    queue_rows = get_dispatch_queue(db, organization_id=organization_id, limit=300)
    for row in queue_rows:
        offer_expires_at = row.get("offer_expires_at")
        requested_at = row.get("requested_at")
        assignment_state = str(row.get("assignment_state") or "queued")
        ride_id = str(row.get("ride_id") or "")
        if offer_expires_at and _as_utc_datetime(offer_expires_at) <= now_ts:
            counters["stale_assignment"] += 1
            _emit_alert(
                severity="high",
                alert_type="stale_assignment",
                ride_id=ride_id,
                driver_id=row.get("offered_driver_id"),
                message="Assignment offer expired and requires reassignment intervention.",
                created_at=now_ts,
            )
        if assignment_state in {"queued", "reassignment_pending", "expired", "rejected"}:
            counters["awaiting_assignment"] += 1
            if requested_at and (_as_utc_datetime(now()) - _as_utc_datetime(requested_at)).total_seconds() > 900:
                _emit_alert(
                    severity="warn",
                    alert_type="awaiting_assignment",
                    ride_id=ride_id,
                    driver_id=None,
                    message="Ride is waiting for assignment longer than SLA threshold.",
                    created_at=now_ts,
                )

    recent_logs = (
        db.query(HealthISFDispatchLog)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchLog.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
        .order_by(desc(HealthISFDispatchLog.created_at))
        .limit(200)
        .all()
    )
    for row in recent_logs:
        action = str(row.action or "").lower()
        if action in {"provider-delay", "dispatch_exception", "assignment-expired"}:
            if action == "provider-delay":
                counters["provider_delay"] += 1
            else:
                counters["dispatch_exception"] += 1
            _emit_alert(
                severity="warn" if action == "provider-delay" else "high",
                alert_type=action,
                ride_id=row.ride_id,
                driver_id=row.driver_id,
                message=row.note or action,
                created_at=row.created_at,
            )

    alerts.sort(key=lambda item: _as_utc_datetime(item["created_at"]), reverse=True)
    return {
        "organization_id": organization_id,
        "generated_at": now_ts,
        "alerts": alerts[:100],
        "counters": counters,
    }


def admin_force_expire_assignment(
    db: Session,
    *,
    organization_id: str,
    offer_id: str,
    reason: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    offer = get_dispatch_offer_by_id(db, offer_id)
    if not offer:
        return None
    ride = get_ride_by_id(db, offer.ride_id)
    if not ride or ride.organization_id != organization_id:
        raise ValueError("Offer outside tenant scope")

    released = release_driver_assignment(
        db,
        offer_id=offer_id,
        reason="expired",
        actor_user_id=actor_user_id,
    )
    if released:
        released.reassignment_reason = str(reason or "admin_forced_expire")[:128]
        released.updated_at = now()
        _record_dispatch(
            db,
            ride_id=released.ride_id,
            action="assignment-expired",
            acted_by_user_id=actor_user_id,
            driver_id=released.driver_id,
            note=str(reason or "Admin force-expired stale assignment")[:512],
            assignment_id=released.id,
            lifecycle_state=str(released.assignment_state),
            transition_reason="admin_force_expire_assignment",
            transition_timestamp=now(),
            assignment_transition_source="admin_command_center",
        )
        _commit_or_rollback(db)
        db.refresh(released)
    return released


def admin_reassign_driver(
    db: Session,
    *,
    organization_id: str,
    ride_id: str,
    driver_id: str,
    reason: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    ride = get_ride_by_id(db, ride_id)
    if not ride or ride.organization_id != organization_id:
        return None
    driver = get_driver_by_id(db, driver_id)
    if not driver or driver.organization_id != organization_id:
        raise ValueError("Driver not found")

    lifecycle = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(ride.status))
    if lifecycle in {RideStatus.IN_PROGRESS.value, RideStatus.RIDER_ONBOARD.value, RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
        raise ValueError("Ride is not eligible for reassignment")

    if ride.driver_id and str(ride.driver_id) != str(driver_id):
        old_driver = get_driver_by_id(db, str(ride.driver_id))
        if old_driver:
            old_driver.availability_state = "available"
            old_driver.is_online = True
            old_driver.auth_state = "active"
            old_driver.last_seen_at = now()
            _set_driver_status(db, old_driver, DriverStatus.AVAILABLE)
        ride.driver_id = None
        ride.status = RideStatus.PENDING
        ride.lifecycle_state = RideStatus.QUEUED.value
        ride.updated_at = now()

    assigned = assign_driver_to_ride(
        db,
        ride_id=ride_id,
        driver_id=driver_id,
        actor_user_id=actor_user_id,
    )
    if assigned:
        _record_dispatch(
            db,
            ride_id=ride_id,
            action="admin-driver-reassigned",
            acted_by_user_id=actor_user_id,
            driver_id=driver_id,
            note=str(reason or "Admin reassigned driver")[:512],
            lifecycle_state=str(getattr(assigned, "lifecycle_state", None) or assigned.status),
            transition_reason="admin_reassign_driver",
            transition_timestamp=now(),
            assignment_transition_source="admin_command_center",
        )
        _commit_or_rollback(db)
        db.refresh(assigned)
    return assigned


def update_customer_ride_request_status(
    db: Session,
    *,
    organization_id: str,
    request_id: str,
    dispatch_status: str,
) -> Optional[HealthISFCustomerRideRequest]:
    request_obj = get_customer_ride_request_by_id(db, request_id)
    if not request_obj or request_obj.organization_id != organization_id:
        return None
    _set_customer_request_status(request_obj, dispatch_status)
    request_obj.updated_at = now()
    _commit_or_rollback(db)
    db.refresh(request_obj)
    return request_obj


def get_customer_ride_queue_metrics(db: Session, *, organization_id: str) -> dict[str, int]:
    rows = list_customer_ride_requests(db, organization_id=organization_id, limit=1000)
    counters = {
        "pending": 0,
        "approved": 0,
        "dispatchable": 0,
        "broadcasted": 0,
        "accepted": 0,
        "assigned": 0,
        "in_progress": 0,
        "completed": 0,
        "cancelled": 0,
        "total": len(rows),
    }
    for row in rows:
        key = str(row.dispatch_status or "pending").lower()
        if key in counters:
            counters[key] += 1
    return counters


def create_customer_ride_request(
    db: Session,
    *,
    organization_id: str,
    rider_name: str,
    rider_phone: str,
    pickup_address: str,
    dropoff_address: str,
    scheduled_time: Optional[datetime],
    ride_type: str,
    recurring: bool,
    recurring_pattern: Optional[dict[str, Any]],
    notes: Optional[str] = None,
    submitted_by_user_id: Optional[str] = None,
) -> tuple[HealthISFCustomerRideRequest, HealthISFRide]:
    pickup_norm = str(pickup_address or "").strip().lower()
    dropoff_norm = str(dropoff_address or "").strip().lower()
    if pickup_norm and dropoff_norm and pickup_norm == dropoff_norm:
        raise ValueError("pickup_address and dropoff_address must be different")

    normalized_scheduled = _coerce_utc(scheduled_time)
    if normalized_scheduled and normalized_scheduled < (now() - timedelta(minutes=5)):
        raise ValueError("scheduled_time cannot be in the past")

    normalized_ride_type = _normalize_customer_ride_type(ride_type)
    normalized_service_type = serialize_service_category(normalized_ride_type)
    provider = (
        db.query(HealthISFProvider)
        .filter(
            HealthISFProvider.organization_id == organization_id,
            HealthISFProvider.is_active == True,
        )
        .order_by(HealthISFProvider.created_at.asc())
        .first()
    )
    if not provider:
        raise ValueError("No active provider available for this organization")

    recurring_payload = recurring_pattern if recurring else None
    if recurring and not recurring_payload:
        recurring_payload = {
            "type": "weekly",
            "days": ["mon", "wed", "fri"],
            "category": normalized_ride_type,
        }
    if recurring_payload and isinstance(recurring_payload, dict):
        recurring_payload.setdefault("category", normalized_ride_type)
        recurring_payload.setdefault("requested_by", "customer_request")

    ride = create_ride(
        db,
        organization_id=organization_id,
        passenger_name=rider_name,
        passenger_phone=rider_phone,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        service_type=normalized_service_type,
        provider_id=provider.id,
        appointment_time=normalized_scheduled,
        recurring_trip_pattern=recurring_payload,
        notes=notes,
        actor_user_id=submitted_by_user_id,
    )

    request_obj = HealthISFCustomerRideRequest(
        id=uuid4(),
        organization_id=organization_id,
        ride_id=ride.id,
        submitted_by_user_id=submitted_by_user_id,
        rider_name=rider_name,
        rider_phone=rider_phone,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        scheduled_time=normalized_scheduled,
        ride_type=normalized_ride_type,
        is_recurring=bool(recurring),
        recurring_pattern_json=json.dumps(recurring_payload) if recurring_payload else None,
        notes=notes,
        dispatch_status=CustomerRequestStatus.PENDING.value,
        pending_at=now(),
        created_at=now(),
        updated_at=now(),
    )
    db.add(request_obj)
    _commit_or_rollback(db)
    db.refresh(request_obj)
    db.refresh(ride)
    return request_obj, ride


def list_driver_assigned_rides(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    limit: int = 100,
) -> list[HealthISFRide]:
    return (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id == driver_id,
        )
        .order_by(desc(HealthISFRide.updated_at))
        .limit(limit)
        .all()
    )

DEFAULT_ORGANIZATION = {
    "name": "Amicor Health ISF",
    "code": "AMICOR-DEFAULT",
    "address": "100 Operations Ave, New York, NY 10001",
    "phone": "212-555-0000",
}

LEGACY_ORG_CODES = ("AMICOR-DEFAULT", "AMICOR-ISF")

SAMPLE_PROVIDERS = [
    {
        "name": "Lincoln Medical Center",
        "address": "123 Health St, Brooklyn, NY 11201",
        "phone": "718-555-0100",
        "service_type": "clinic",
    },
    {
        "name": "Queens Dialysis Facility",
        "address": "456 Care Ave, Queens, NY 11375",
        "phone": "718-555-0200",
        "service_type": "facility",
    },
    {
        "name": "Manhattan Health Hub",
        "address": "789 Medical Pkwy, New York, NY 10001",
        "phone": "212-555-0300",
        "service_type": "clinic",
    },
]

SAMPLE_DRIVERS = [
    {
        "name": "James Smith",
        "phone": "917-555-1001",
        "vehicle_type": "sedan",
        "vehicle_plate": "NYC-1001",
        "status": DriverStatus.AVAILABLE,
        "rating": 4.8,
    },
    {
        "name": "Maria Garcia",
        "phone": "917-555-1002",
        "vehicle_type": "van",
        "vehicle_plate": "NYC-1002",
        "status": DriverStatus.BUSY,
        "rating": 4.9,
    },
    {
        "name": "David Chen",
        "phone": "917-555-1003",
        "vehicle_type": "sedan",
        "vehicle_plate": "NYC-1003",
        "status": DriverStatus.OFFLINE,
        "rating": 4.7,
    },
]

SAMPLE_RIDES = [
    {
        "passenger_name": "Patricia Johnson",
        "passenger_phone": "646-555-2001",
        "pickup_address": "1000 Park Ave, New York, NY 10028",
        "dropoff_address": "456 Care Ave, Queens, NY 11375",
        "service_type": "dialysis",
        "status": RideStatus.COMPLETED,
        "estimated_distance_miles": 8.5,
        "estimated_duration_minutes": 25,
    },
    {
        "passenger_name": "Robert Williams",
        "passenger_phone": "646-555-2002",
        "pickup_address": "500 East St, Brooklyn, NY 11201",
        "dropoff_address": "123 Health St, Brooklyn, NY 11201",
        "service_type": "medical_appointment",
        "status": RideStatus.ACCEPTED,
        "estimated_distance_miles": 3.2,
        "estimated_duration_minutes": 12,
    },
    {
        "passenger_name": "Jennifer Brown",
        "passenger_phone": "646-555-2003",
        "pickup_address": "200 Queens Blvd, Queens, NY 11375",
        "dropoff_address": "789 Medical Pkwy, New York, NY 10001",
        "service_type": "medical_transport",
        "status": RideStatus.PENDING,
        "estimated_distance_miles": 10.1,
        "estimated_duration_minutes": 30,
    },
]


def _org_operational_score(db: Session, org: HealthISFOrganization) -> int:
    provider_count = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org.id).count()
    driver_count = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).count()
    ride_count = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org.id).count()
    return provider_count * 1000 + driver_count * 100 + ride_count


def _get_or_create_default_org(db: Session) -> HealthISFOrganization:
    candidates = (
        db.query(HealthISFOrganization)
        .filter(HealthISFOrganization.code.in_(LEGACY_ORG_CODES))
        .all()
    )
    if candidates:
        canonical = max(candidates, key=lambda org: _org_operational_score(db, org))
        if canonical.code != DEFAULT_ORGANIZATION["code"]:
            conflict = (
                db.query(HealthISFOrganization)
                .filter(
                    HealthISFOrganization.code == DEFAULT_ORGANIZATION["code"],
                    HealthISFOrganization.id != canonical.id,
                )
                .first()
            )
            if not conflict:
                canonical.code = DEFAULT_ORGANIZATION["code"]
                canonical.updated_at = now()
        return canonical

    org = HealthISFOrganization(
        id=uuid4(),
        name=DEFAULT_ORGANIZATION["name"],
        code=DEFAULT_ORGANIZATION["code"],
        address=DEFAULT_ORGANIZATION["address"],
        phone=DEFAULT_ORGANIZATION["phone"],
        is_active=True,
    )
    db.add(org)
    db.flush()
    return org


def _get_organization_by_id(db: Session, organization_id: str) -> Optional[HealthISFOrganization]:
    return db.query(HealthISFOrganization).filter(HealthISFOrganization.id == organization_id).first()


def _record_dispatch(
    db: Session,
    ride_id: str,
    action: str,
    acted_by_user_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    note: Optional[str] = None,
    request_id: Optional[str] = None,
    assignment_id: Optional[str] = None,
    lifecycle_state: Optional[str] = None,
    transition_reason: Optional[str] = None,
    transition_timestamp: Optional[datetime] = None,
    emitted_event_name: Optional[str] = None,
    emitted_timestamp: Optional[datetime] = None,
    websocket_delivery_target: Optional[str] = None,
    assignment_transition_source: Optional[str] = None,
) -> None:
    db.add(
        HealthISFDispatchLog(
            id=uuid4(),
            ride_id=ride_id,
            driver_id=driver_id,
            action=action,
            note=note,
            request_id=request_id,
            assignment_id=assignment_id,
            lifecycle_state=lifecycle_state,
            transition_reason=transition_reason,
            transition_timestamp=transition_timestamp,
            emitted_event_name=emitted_event_name,
            emitted_timestamp=emitted_timestamp,
            websocket_delivery_target=websocket_delivery_target,
            assignment_transition_source=assignment_transition_source,
            acted_by_user_id=acted_by_user_id,
            created_at=now(),
        )
    )


def record_dispatch_event_emission(
    db: Session,
    *,
    ride_id: str,
    event_name: str,
    assignment_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    request_id: Optional[str] = None,
    lifecycle_state: Optional[str] = None,
    transition_reason: Optional[str] = None,
    websocket_delivery_target: Optional[str] = None,
    assignment_transition_source: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> None:
    ts = now()
    _record_dispatch(
        db,
        ride_id=ride_id,
        action="dispatch_event_emitted",
        acted_by_user_id=actor_user_id,
        driver_id=driver_id,
        note=f"event={event_name}",
        request_id=request_id,
        assignment_id=assignment_id,
        lifecycle_state=lifecycle_state,
        transition_reason=transition_reason,
        transition_timestamp=ts,
        emitted_event_name=event_name,
        emitted_timestamp=ts,
        websocket_delivery_target=websocket_delivery_target,
        assignment_transition_source=assignment_transition_source,
    )


def _record_status_history(
    db: Session,
    ride_id: str,
    from_status: Optional[str],
    to_status: str,
    changed_by_user_id: Optional[str] = None,
    note: Optional[str] = None,
) -> None:
    db.add(
        HealthISFRideStatusHistory(
            id=uuid4(),
            ride_id=ride_id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            changed_by_user_id=changed_by_user_id,
            created_at=now(),
        )
    )


def _commit_or_rollback(db: Session) -> None:
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise


def _normalize_legacy_driver_status_rows(db: Session) -> None:
    """Normalize pre-existing uppercase or corrupted driver status values before ORM hydration."""
    try:
        db.execute(
            text(
                "UPDATE health_isf_drivers "
                "SET status = lower(status) "
                "WHERE status IS NOT NULL AND status <> lower(status)"
            )
        )
        db.execute(
            text(
                "UPDATE health_isf_drivers "
                "SET status = substr(status, instr(status, '.') + 1) "
                "WHERE status LIKE 'driverstatus.%'"
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        return


_DRIVER_WORKFLOW_STATUSES = {
    DriverStatus.OFFLINE,
    DriverStatus.AVAILABLE,
    DriverStatus.ASSIGNED,
    DriverStatus.BUSY,
    DriverStatus.EN_ROUTE_PICKUP,
    DriverStatus.WAITING_AT_PICKUP,
    DriverStatus.IN_TRANSIT,
    DriverStatus.COMPLETED,
    DriverStatus.UNAVAILABLE,
}


def _coerce_driver_status(status: str | DriverStatus) -> DriverStatus:
    if isinstance(status, DriverStatus):
        return status
    raw = str(status).strip().lower()
    if raw.startswith("driverstatus."):
        raw = raw.split(".", 1)[-1]
    return DriverStatus(raw)


def _is_driver_busy(status: str | DriverStatus) -> bool:
    value = _coerce_driver_status(status)
    return value in {
        DriverStatus.ASSIGNED,
        DriverStatus.BUSY,
        DriverStatus.EN_ROUTE_PICKUP,
        DriverStatus.WAITING_AT_PICKUP,
        DriverStatus.IN_TRANSIT,
    }


def _allowed_driver_transitions(current: DriverStatus) -> set[DriverStatus]:
    current = _coerce_driver_status(current)
    if current == DriverStatus.OFFLINE:
        return {DriverStatus.AVAILABLE, DriverStatus.UNAVAILABLE, DriverStatus.OFFLINE}
    if current == DriverStatus.AVAILABLE:
        return {DriverStatus.ASSIGNED, DriverStatus.BUSY, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE, DriverStatus.AVAILABLE}
    if current in (DriverStatus.ASSIGNED, DriverStatus.BUSY):
        return {
            DriverStatus.EN_ROUTE_PICKUP,
            DriverStatus.WAITING_AT_PICKUP,
            DriverStatus.COMPLETED,
            DriverStatus.AVAILABLE,
            DriverStatus.OFFLINE,
            DriverStatus.UNAVAILABLE,
            DriverStatus.ASSIGNED,
            DriverStatus.BUSY,
        }
    if current == DriverStatus.EN_ROUTE_PICKUP:
        return {DriverStatus.WAITING_AT_PICKUP, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE, DriverStatus.EN_ROUTE_PICKUP}
    if current == DriverStatus.WAITING_AT_PICKUP:
        return {DriverStatus.IN_TRANSIT, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE, DriverStatus.WAITING_AT_PICKUP}
    if current == DriverStatus.IN_TRANSIT:
        return {DriverStatus.COMPLETED, DriverStatus.AVAILABLE, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE, DriverStatus.IN_TRANSIT}
    if current == DriverStatus.COMPLETED:
        return {DriverStatus.AVAILABLE, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE, DriverStatus.COMPLETED}
    if current == DriverStatus.UNAVAILABLE:
        return {DriverStatus.AVAILABLE, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE}
    return {_coerce_driver_status(current)}


def _validate_driver_transition(current: DriverStatus, target: DriverStatus) -> None:
    if target not in _allowed_driver_transitions(current):
        raise ValueError(f"Cannot change driver from '{current.value}' to '{target.value}'")


def _set_driver_status(db: Session, driver: HealthISFDriver, target_status: str | DriverStatus) -> HealthISFDriver:
    next_status = _coerce_driver_status(target_status)
    current_status = _coerce_driver_status(driver.status)
    if current_status != next_status:
        _validate_driver_transition(current_status, next_status)
        driver.status = next_status
        driver.updated_at = now()
    return driver


def _current_active_rides_for_driver(db: Session, driver_id: str) -> list[HealthISFRide]:
    return db.query(HealthISFRide).filter(
        HealthISFRide.driver_id == driver_id,
        HealthISFRide.status.in_([
            RideStatus.PENDING,
            RideStatus.ACCEPTED,
            RideStatus.IN_TRANSIT,
        ]),
    ).all()


def _record_driver_state_change(
    db: Session,
    ride: HealthISFRide,
    driver: HealthISFDriver,
    action: str,
    actor_user_id: Optional[str],
    note: Optional[str] = None,
    status_from: Optional[str] = None,
    status_to: Optional[str] = None,
) -> None:
    _record_dispatch(
        db,
        ride_id=ride.id,
        action=action,
        acted_by_user_id=actor_user_id,
        driver_id=driver.id,
        note=note,
    )
    if status_from is not None and status_to is not None:
        _record_status_history(
            db,
            ride_id=ride.id,
            from_status=status_from,
            to_status=status_to,
            changed_by_user_id=actor_user_id,
            note=note,
        )


def _normalize_target_ride_state(status: str | RideStatus) -> str:
    value = str(status.value if isinstance(status, RideStatus) else status).strip().lower()
    if value == RideStatus.PENDING.value:
        return RideStatus.QUEUED.value
    if value == RideStatus.ACCEPTED.value:
        return RideStatus.ASSIGNED.value
    if value == RideStatus.IN_TRANSIT.value:
        return RideStatus.IN_PROGRESS.value
    return RideLifecycleManager.normalize_state(value)


def accept_driver_ride(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")
    if RideStatus(ride.status) in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise ValueError("Cannot accept a terminal ride")

    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    if RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) == RideStatus.QUEUED.value:
        accepted = RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=RideStatus.ASSIGNED.value,
            action_type="driver_assignment_confirmed",
            actor_user_id=actor_user_id,
            note="Driver assignment confirmed",
            payload={"driver_id": driver.id},
            event_id=event_id,
            sequence_number=sequence_number,
            monotonic_ts=monotonic_ts,
            source="accept_driver_ride",
        )
        if not accepted:
            logger.info({"event": "duplicate_or_stale_assignment_rejected", "ride_id": ride.id, "driver_id": driver.id})
    accepted2 = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.DRIVER_EN_ROUTE.value,
        action_type="driver_accepted_ride",
        actor_user_id=actor_user_id,
        note="Driver accepted assignment",
        payload={"driver_id": driver.id},
        event_id=str(uuid4()),
        sequence_number=sequence_number+1,
        monotonic_ts=monotonic_ts+0.0001,
        source="accept_driver_ride",
    )
    if not accepted2:
        logger.info({"event": "duplicate_or_stale_accept_rejected", "ride_id": ride.id, "driver_id": driver.id})
    _set_driver_status(db, driver, DriverStatus.EN_ROUTE_PICKUP)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.ACCEPTED.value,
        note="Driver accepted assignment",
    )
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.EN_ROUTE_PICKUP.value,
        note="Driver en route to pickup",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ACCEPTED.value)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_update(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="driver_accept_ride",
        driver_id=driver.id,
    )
    return ride


def decline_driver_ride(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")
    if RideStatus(ride.status) in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise ValueError("Cannot decline a terminal ride")

    ride.driver_id = None
    ride.assigned_by_user_id = actor_user_id
    ride.accepted_at = None
    _set_driver_status(db, driver, DriverStatus.AVAILABLE)
    driver.availability_state = "available"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.QUEUED.value,
        action_type="driver_declined_ride",
        actor_user_id=actor_user_id,
        note=note or "Driver declined ride",
        payload={"driver_id": driver.id},
    )
    assignment = _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        note=note or "Driver declined assignment",
    )
    if assignment:
        assignment.rejected_at = assignment.rejected_at or now()
        assignment.reassignment_pending_at = assignment.reassignment_pending_at or now()
        assignment.reassignment_reason = str(note or "driver_rejected")[:128]
        assignment.closed_reason = assignment.closed_reason or "driver_rejected"
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.BROADCASTED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_update(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="driver_decline_ride",
        driver_id=None,
    )
    return ride


def driver_no_show(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[HealthISFRide]:
    """Mark rider no-show, release driver, and return ride to dispatch queue."""
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state in (RideStatus.COMPLETED.value, RideStatus.CANCELLED.value):
        raise ValueError("Cannot mark no-show on a terminal ride")

    ride.driver_id = None
    ride.assigned_by_user_id = actor_user_id
    ride.accepted_at = None
    ride.arrived_at = None
    _set_driver_status(db, driver, DriverStatus.AVAILABLE)
    driver.availability_state = "available"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()

    RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.CANCELLED.value,
        action_type="rider_no_show",
        actor_user_id=actor_user_id,
        note=note or "Rider no-show reported by driver",
        payload={"driver_id": driver.id, "no_show": True},
    )
    assignment = _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.REJECTED.value,
        note=note or "Rider no-show",
    )
    if assignment:
        assignment.closed_reason = "rider_no_show"
        assignment.closed_at = assignment.closed_at or now()
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.CANCELLED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_update(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="driver_no_show",
        driver_id=None,
    )
    return ride


def driver_arrived_pickup(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state not in (RideStatus.ASSIGNED.value, RideStatus.DRIVER_EN_ROUTE.value):
        raise ValueError("Driver cannot arrive before assignment and en-route state")

    _set_driver_status(db, driver, DriverStatus.WAITING_AT_PICKUP)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.ARRIVED.value,
        action_type="driver_arrived_pickup",
        actor_user_id=actor_user_id,
        note="Driver arrived at pickup",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_arrived_pickup",
    )
    if not accepted:
        logger.info({"event": "duplicate_or_stale_arrived_rejected", "ride_id": ride.id, "driver_id": driver.id})
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.EN_ROUTE_PICKUP.value,
        note="Driver arrived at pickup",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    return ride


def driver_pickup_complete(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state not in (RideStatus.ARRIVED.value, RideStatus.RIDER_ONBOARD.value):
        raise ValueError("Pickup can only be completed once driver has arrived")

    _set_driver_status(db, driver, DriverStatus.IN_TRANSIT)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.RIDER_ONBOARD.value,
        action_type="pickup_completed",
        actor_user_id=actor_user_id,
        note="Pickup completed",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_pickup_complete",
    )
    if not accepted:
        logger.info({"event": "duplicate_or_stale_pickup_rejected", "ride_id": ride.id, "driver_id": driver.id})

    # Move into active transport immediately after confirmed pickup so dropoff completion
    # can follow the strict lifecycle chain without an extra hidden transition call.
    progress_monotonic_ts = time.monotonic()
    progress_event_id = str(uuid4())
    progress_sequence_number = int(progress_monotonic_ts * 1000)
    progressed = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.IN_PROGRESS.value,
        action_type="transport_started",
        actor_user_id=actor_user_id,
        note="Transport started after pickup completed",
        payload={"driver_id": driver.id},
        event_id=progress_event_id,
        sequence_number=progress_sequence_number,
        monotonic_ts=progress_monotonic_ts,
        source="driver_pickup_complete",
    )
    if not progressed:
        logger.info({"event": "duplicate_or_stale_transport_start_rejected", "ride_id": ride.id, "driver_id": driver.id})

    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.PICKUP_COMPLETE.value,
        note="Pickup completed",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.IN_PROGRESS.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    return ride


def driver_dropoff_complete(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state not in (RideStatus.RIDER_ONBOARD.value, RideStatus.IN_PROGRESS.value):
        raise ValueError("Dropoff can only be completed after rider is onboard")

    driver.total_trips = int(driver.total_trips or 0) + 1
    _set_driver_status(db, driver, DriverStatus.AVAILABLE)
    driver.availability_state = "available"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.COMPLETED.value,
        action_type="dropoff_completed",
        actor_user_id=actor_user_id,
        note="Dropoff completed",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_dropoff_complete",
    )
    if not accepted:
        logger.info({"event": "duplicate_or_stale_dropoff_rejected", "ride_id": ride.id, "driver_id": driver.id})
    _ensure_completion_billing_records(db, ride)
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
        note="Dropoff completed",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.COMPLETED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_unregister(ride_id=ride.id, reason="driver_dropoff_complete")
    return ride


def set_driver_operational_status(
    db: Session,
    driver_id: str,
    status: str,
    actor_user_id: Optional[str] = None,
    note: Optional[str] = None,
) -> Optional[HealthISFDriver]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None

    target_status = _coerce_driver_status(status)
    current_status = _coerce_driver_status(driver.status)
    active_rides = _current_active_rides_for_driver(db, driver.id)
    if active_rides and target_status in {DriverStatus.AVAILABLE, DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE}:
        raise ValueError("Cannot move driver to an idle state while the driver has active rides")

    _set_driver_status(db, driver, target_status)
    if target_status != current_status and active_rides:
        _record_dispatch(
            db,
            ride_id=active_rides[0].id,
            action="driver_status_changed",
            acted_by_user_id=actor_user_id,
            driver_id=driver.id,
            note=note or f"Driver status changed from {current_status.value} to {target_status.value}",
        )
    _commit_or_rollback(db)
    db.refresh(driver)
    return driver


def _resolve_unique_vehicle_plate(db: Session, base_plate: str, organization_id: str) -> str:
    base = str(base_plate or "VEH").strip() or "VEH"
    candidates = [
        base,
        f"{base}-{organization_id.replace('-', '')[:6].upper()}",
        f"{base}-{uuid4()[:6].upper()}",
    ]
    for candidate in candidates:
        exists = (
            db.query(HealthISFVehicle.id)
            .filter(HealthISFVehicle.vehicle_plate == candidate)
            .first()
        )
        if not exists:
            return candidate
    return f"{base}-{uuid4()[:8].upper()}"


def _create_canonical_sample_driver(db: Session, org: HealthISFOrganization, item: dict[str, Any]) -> HealthISFDriver:
    """Create a baseline seed driver with vehicle for check-in and dispatch testing."""
    vehicle_plate = _resolve_unique_vehicle_plate(db, str(item["vehicle_plate"]), str(org.id))
    vehicle = HealthISFVehicle(
        id=uuid4(),
        organization_id=org.id,
        vehicle_type=item["vehicle_type"],
        vehicle_plate=vehicle_plate,
        capacity=4,
        is_active=True,
        created_at=now(),
        updated_at=now(),
    )
    db.add(vehicle)
    db.flush()

    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=org.id,
        vehicle_id=vehicle.id,
        name=item["name"],
        phone=item["phone"],
        vehicle_type=item["vehicle_type"],
        vehicle_plate=vehicle_plate,
        status=item["status"],
        availability_state=(
            "available"
            if item["status"] == DriverStatus.AVAILABLE
            else "offline"
        ),
        auth_state="inactive",
        is_online=False,
        is_active=True,
        total_trips=0,
        rating=item["rating"],
        created_at=now(),
        updated_at=now(),
    )
    db.add(driver)
    db.flush()
    return driver


def ensure_sample_driver_credentials(db: Session, organization_id: str | None = None) -> dict[str, str]:
    """Ensure baseline seed drivers exist with canonical phone numbers for check-in testing."""
    org = _get_organization_by_id(db, organization_id) if organization_id else _get_or_create_default_org(db)
    if not org:
        return {}
    ensured: dict[str, str] = {}
    for item in SAMPLE_DRIVERS:
        canonical_phone = str(item["phone"]).strip()
        canonical_name = str(item["name"]).strip()
        row = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == org.id,
                func.lower(HealthISFDriver.name) == canonical_name.lower(),
            )
            .order_by(HealthISFDriver.created_at.asc())
            .first()
        )
        if not row:
            row = (
                db.query(HealthISFDriver)
                .filter(HealthISFDriver.phone == canonical_phone)
                .order_by(HealthISFDriver.created_at.asc())
                .first()
            )
            if row and str(row.organization_id) != str(org.id):
                row.organization_id = org.id
                row.name = canonical_name
                row.is_active = True
                row.updated_at = now()
                if row.vehicle_id:
                    vehicle = (
                        db.query(HealthISFVehicle)
                        .filter(HealthISFVehicle.id == row.vehicle_id)
                        .first()
                    )
                    if vehicle:
                        vehicle.organization_id = org.id
                        vehicle.updated_at = now()
                ensured[str(row.id)] = canonical_phone
                continue
        if not row:
            row = _create_canonical_sample_driver(db, org, item)
            ensured[str(row.id)] = canonical_phone
            continue
        current_phone = str(row.phone or "").strip()
        if not _phones_match_for_driver_login(canonical_phone, current_phone):
            row.phone = canonical_phone
            row.updated_at = now()
            ensured[str(row.id)] = canonical_phone
        if not row.is_active:
            row.is_active = True
            row.updated_at = now()
            ensured[str(row.id)] = canonical_phone
    if ensured:
        _commit_or_rollback(db)
    return ensured


def init_sample_data(db: Session) -> dict:
    summary = {
        "organizations": 0,
        "providers": 0,
        "drivers": 0,
        "vehicles": 0,
        "rides": 0,
        "already_exists": False,
    }

    org = _get_or_create_default_org(db)
    existing = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org.id).count()
    if existing > 0:
        summary["already_exists"] = True
        return summary

    summary["organizations"] = 1

    providers_map = {}
    for item in SAMPLE_PROVIDERS:
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org.id,
            name=item["name"],
            address=item["address"],
            phone=item["phone"],
            service_type=item["service_type"],
            is_active=True,
            created_at=now(),
            updated_at=now(),
        )
        db.add(provider)
        db.flush()
        providers_map[provider.name] = provider
        summary["providers"] += 1

    drivers: list[HealthISFDriver] = []
    for item in SAMPLE_DRIVERS:
        vehicle = HealthISFVehicle(
            id=uuid4(),
            organization_id=org.id,
            vehicle_type=item["vehicle_type"],
            vehicle_plate=item["vehicle_plate"],
            capacity=4,
            is_active=True,
            created_at=now(),
            updated_at=now(),
        )
        db.add(vehicle)
        db.flush()
        summary["vehicles"] += 1

        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org.id,
            vehicle_id=vehicle.id,
            name=item["name"],
            phone=item["phone"],
            vehicle_type=item["vehicle_type"],
            vehicle_plate=item["vehicle_plate"],
            status=item["status"],
            is_active=True,
            total_trips=0,
            rating=item["rating"],
            created_at=now(),
            updated_at=now(),
        )
        db.add(driver)
        db.flush()
        drivers.append(driver)
        summary["drivers"] += 1

    providers = list(providers_map.values())
    seed_demo_rides = os.environ.get("AMICOR_SEED_SAMPLE_RIDES", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    if not seed_demo_rides:
        db.commit()
        return summary

    for idx, ride_item in enumerate(SAMPLE_RIDES):
        assigned_driver = drivers[idx % len(drivers)] if ride_item["status"] != RideStatus.PENDING else None
        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org.id,
            provider_id=providers[idx % len(providers)].id,
            driver_id=assigned_driver.id if assigned_driver else None,
            passenger_name=ride_item["passenger_name"],
            passenger_phone=ride_item["passenger_phone"],
            pickup_address=ride_item["pickup_address"],
            dropoff_address=ride_item["dropoff_address"],
            service_type=ride_item["service_type"],
            status=ride_item["status"],
            lifecycle_state=(
                RideStatus.COMPLETED.value
                if ride_item["status"] == RideStatus.COMPLETED
                else RideStatus.ASSIGNED.value
                if ride_item["status"] == RideStatus.ACCEPTED
                else RideStatus.QUEUED.value
            ),
            estimated_distance_miles=ride_item["estimated_distance_miles"],
            estimated_duration_minutes=ride_item["estimated_duration_minutes"],
            requested_at=now(),
            accepted_at=now() if ride_item["status"] in (RideStatus.ACCEPTED, RideStatus.IN_TRANSIT, RideStatus.COMPLETED) else None,
            completed_at=now() if ride_item["status"] == RideStatus.COMPLETED else None,
            created_at=now(),
            updated_at=now(),
        )
        db.add(ride)
        db.flush()
        summary["rides"] += 1

        _record_dispatch(
            db,
            ride_id=ride.id,
            action="ride_created",
            note="Seed data ride creation",
            driver_id=ride.driver_id,
        )
        _record_status_history(db, ride.id, None, str(ride.status))

        if ride_item["status"] == RideStatus.COMPLETED and assigned_driver:
            trip = HealthISFTrip(
                id=uuid4(),
                ride_id=ride.id,
                driver_id=assigned_driver.id,
                status=TripStatus.COMPLETED,
                start_time=now(),
                end_time=now(),
                distance_miles=ride_item["estimated_distance_miles"],
                duration_minutes=ride_item["estimated_duration_minutes"],
                created_at=now(),
                updated_at=now(),
            )
            db.add(trip)
            db.flush()

            payout = HealthISFPayout(
                id=uuid4(),
                driver_id=assigned_driver.id,
                trip_id=trip.id,
                amount_usd=17.0 + idx,
                status="processed",
                description=f"Seed payout for trip {trip.id[:8]}",
                created_at=now(),
                updated_at=now(),
            )
            db.add(payout)

    db.commit()
    logger.info("Health ISF seed complete: %s", summary)
    return summary


PILOT_RESET_PASSENGER_MARKERS = (
    "cert audit",
    "prod verify",
    "patricia johnson",
    "robert williams",
    "jennifer brown",
    "audit patient",
    "audit rider",
    "browser e2e",
    "pilot e2e",
)

DEMO_SEED_PASSENGER_NAMES = {
    str(item["passenger_name"]).strip().lower()
    for item in SAMPLE_RIDES
}


def reset_pilot_environment(db: Session, organization_id: str) -> dict[str, Any]:
    """Cancel all ride records for the org and restore canonical drivers for pilot operations."""
    org = _get_organization_by_id(db, organization_id) or _get_or_create_default_org(db)
    if str(org.id) != str(organization_id):
        raise ValueError("Organization scope mismatch")

    now_ts = now()
    active_ride_rows = (
        db.query(HealthISFRide.id, HealthISFRide.passenger_name)
        .filter(
            HealthISFRide.organization_id == org.id,
            HealthISFRide.status != RideStatus.CANCELLED.value,
        )
        .all()
    )
    cleared_rides = len(active_ride_rows)
    archived_demo_rides = 0
    for _, passenger_name in active_ride_rows:
        passenger = str(passenger_name or "").strip().lower()
        if passenger in DEMO_SEED_PASSENGER_NAMES or any(
            marker in passenger for marker in PILOT_RESET_PASSENGER_MARKERS
        ):
            archived_demo_rides += 1

    if cleared_rides:
        db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == org.id,
            HealthISFRide.status != RideStatus.CANCELLED.value,
        ).update(
            {
                "status": RideStatus.CANCELLED.value,
                "lifecycle_state": RideStatus.CANCELLED.value,
                "driver_id": None,
                "updated_at": now_ts,
            },
            synchronize_session=False,
        )

    open_assignments = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == org.id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .all()
    )
    for assignment in open_assignments:
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        assignment.closed_reason = "pilot_reset"
        assignment.updated_at = now_ts

    canonical_names = [str(item["name"]).strip().lower() for item in SAMPLE_DRIVERS]
    drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).all()
    reset_drivers = 0
    for driver in drivers:
        name = str(driver.name or "").strip().lower()
        if name == canonical_names[0]:
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_active = True
            driver.is_online = False
            driver.auth_state = "inactive"
            driver.last_seen_at = None
            reset_drivers += 1
        elif name in canonical_names[1:]:
            driver.status = DriverStatus.OFFLINE
            driver.availability_state = "offline"
            driver.is_online = False
        else:
            driver.status = DriverStatus.OFFLINE
            driver.availability_state = "offline"
            driver.is_online = False
        driver.updated_at = now_ts

    db.commit()
    terminal_values = {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
    }
    remaining_open = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == org.id,
            HealthISFRide.status.notin_(list(terminal_values)),
        )
        .count()
    )
    return {
        "organization_id": str(org.id),
        "cleared_rides": cleared_rides,
        "cancelled_open_rides": cleared_rides,
        "archived_demo_rides": archived_demo_rides,
        "closed_assignments": len(open_assignments),
        "drivers_reset": reset_drivers,
        "remaining_open_rides": remaining_open,
    }


def get_all_providers(db: Session, skip: int = 0, limit: int = 100) -> list[HealthISFProvider]:
    return db.query(HealthISFProvider).filter(
        HealthISFProvider.is_active == True
    ).offset(skip).limit(limit).all()


def get_provider_by_id(db: Session, provider_id: str) -> Optional[HealthISFProvider]:
    return db.query(HealthISFProvider).filter(HealthISFProvider.id == provider_id).first()


def create_provider(
    db: Session,
    *,
    organization_id: str,
    name: str,
    address: str,
    phone: str,
    service_type: str,
) -> HealthISFProvider:
    normalized_name = str(name or "").strip()
    normalized_address = str(address or "").strip()
    normalized_phone = str(phone or "").strip()
    normalized_service_type = str(service_type or "").strip()
    duplicate = db.query(HealthISFProvider).filter(
        HealthISFProvider.organization_id == organization_id,
        func.lower(HealthISFProvider.name) == normalized_name.lower(),
        func.lower(HealthISFProvider.phone) == normalized_phone.lower(),
    ).first()
    if duplicate:
        raise ValueError("Provider already exists for this organization")

    provider = HealthISFProvider(
        id=uuid4(),
        organization_id=organization_id,
        name=normalized_name,
        address=normalized_address,
        phone=normalized_phone,
        service_type=normalized_service_type,
        is_active=True,
    )
    db.add(provider)
    _commit_or_rollback(db)
    db.refresh(provider)
    return provider


def update_provider(
    db: Session,
    provider_id: str,
    actor_user_id: Optional[str] = None,
    **changes,
) -> Optional[HealthISFProvider]:
    provider = get_provider_by_id(db, provider_id)
    if not provider:
        return None

    allowed = {"name", "address", "phone", "service_type", "is_active"}
    changed_fields = []
    for key, value in changes.items():
        if key in allowed and value is not None:
            setattr(provider, key, value)
            changed_fields.append(key)

    if changed_fields:
        rides = db.query(HealthISFRide).filter(HealthISFRide.provider_id == provider.id).all()
        for ride in rides:
            _record_dispatch(
                db,
                ride_id=ride.id,
                action="provider_updated",
                acted_by_user_id=actor_user_id,
                note="Updated provider fields: " + ", ".join(changed_fields),
            )

    _commit_or_rollback(db)
    db.refresh(provider)
    return provider


def get_all_drivers(db: Session, skip: int = 0, limit: int = 100) -> list[HealthISFDriver]:
    _normalize_legacy_driver_status_rows(db)
    return db.query(HealthISFDriver).filter(
        HealthISFDriver.is_active == True
    ).offset(skip).limit(limit).all()


def get_drivers_for_organization(
    db: Session,
    *,
    organization_id: str,
    skip: int = 0,
    limit: int = 100,
) -> list[HealthISFDriver]:
    _normalize_legacy_driver_status_rows(db)
    canonical_names = [str(item["name"]).strip().lower() for item in SAMPLE_DRIVERS]
    sample_priority = case(
        (func.lower(HealthISFDriver.name).in_(canonical_names), 0),
        else_=1,
    )
    return (
        db.query(HealthISFDriver)
        .filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.is_active == True,
        )
        .order_by(sample_priority, desc(HealthISFDriver.updated_at), HealthISFDriver.name.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_available_drivers(db: Session) -> list[HealthISFDriver]:
    _normalize_legacy_driver_status_rows(db)
    return db.query(HealthISFDriver).filter(
        and_(
            HealthISFDriver.is_active == True,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        )
    ).all()


def get_driver_by_id(db: Session, driver_id: str) -> Optional[HealthISFDriver]:
    _normalize_legacy_driver_status_rows(db)
    return db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()


def create_driver(
    db: Session,
    *,
    organization_id: str,
    name: str,
    phone: str,
    vehicle_type: str,
    vehicle_plate: str,
) -> HealthISFDriver:
    normalized_name = str(name or "").strip()
    normalized_phone = str(phone or "").strip()
    normalized_vehicle_type = str(vehicle_type or "").strip()
    normalized_vehicle_plate = str(vehicle_plate or "").strip().upper()

    phone_duplicate = db.query(HealthISFDriver).filter(
        func.lower(HealthISFDriver.phone) == normalized_phone.lower()
    ).first()
    if phone_duplicate:
        raise ValueError("Driver phone already exists")

    plate_duplicate = db.query(HealthISFDriver).filter(
        func.lower(HealthISFDriver.vehicle_plate) == normalized_vehicle_plate.lower()
    ).first()
    if plate_duplicate:
        raise ValueError("Driver vehicle plate already exists")

    driver = HealthISFDriver(
        id=uuid4(),
        organization_id=organization_id,
        name=normalized_name,
        phone=normalized_phone,
        vehicle_type=normalized_vehicle_type,
        vehicle_plate=normalized_vehicle_plate,
        status=DriverStatus.OFFLINE,
        is_active=True,
    )
    db.add(driver)
    _commit_or_rollback(db)
    db.refresh(driver)
    return driver


def get_vehicle_by_id(db: Session, vehicle_id: str) -> Optional[HealthISFVehicle]:
    return db.query(HealthISFVehicle).filter(HealthISFVehicle.id == vehicle_id).first()


def create_vehicle(
    db: Session,
    *,
    organization_id: str,
    vehicle_type: str,
    vehicle_plate: str,
    capacity: int,
) -> HealthISFVehicle:
    normalized_vehicle_type = str(vehicle_type or "").strip()
    normalized_vehicle_plate = str(vehicle_plate or "").strip().upper()
    plate_duplicate = db.query(HealthISFVehicle).filter(
        func.lower(HealthISFVehicle.vehicle_plate) == normalized_vehicle_plate.lower()
    ).first()
    if plate_duplicate:
        raise ValueError("Vehicle plate already exists")

    vehicle = HealthISFVehicle(
        id=uuid4(),
        organization_id=organization_id,
        vehicle_type=normalized_vehicle_type,
        vehicle_plate=normalized_vehicle_plate,
        capacity=max(1, int(capacity)),
        is_active=True,
    )
    db.add(vehicle)
    _commit_or_rollback(db)
    db.refresh(vehicle)
    return vehicle


def get_active_vehicles(
    db: Session,
    *,
    organization_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[HealthISFVehicle]:
    query = db.query(HealthISFVehicle).filter(HealthISFVehicle.is_active == True)
    if organization_id:
        query = query.filter(HealthISFVehicle.organization_id == organization_id)
    return query.offset(skip).limit(limit).all()


def update_driver(
    db: Session,
    driver_id: str,
    actor_user_id: Optional[str] = None,
    **changes,
) -> Optional[HealthISFDriver]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return None

    allowed = {"name", "phone", "status", "is_active", "rating"}
    changed_fields = []
    for key, value in changes.items():
        if key in allowed and value is not None:
            setattr(driver, key, value)
            changed_fields.append(key)

    if changed_fields:
        active_rides = db.query(HealthISFRide).filter(HealthISFRide.driver_id == driver.id).all()
        for ride in active_rides:
            _record_dispatch(
                db,
                ride_id=ride.id,
                action="driver_updated",
                acted_by_user_id=actor_user_id,
                driver_id=driver.id,
                note="Updated driver fields: " + ", ".join(changed_fields),
            )

    _commit_or_rollback(db)
    db.refresh(driver)
    return driver


def create_driver_application(
    db: Session,
    *,
    organization_id: str,
    applicant_name: str,
    applicant_phone: str,
    applicant_email: Optional[str] = None,
    license_number: Optional[str] = None,
    insurance_policy_number: Optional[str] = None,
    vehicle_make: Optional[str] = None,
    vehicle_model: Optional[str] = None,
    vehicle_year: Optional[int] = None,
    vehicle_plate: Optional[str] = None,
    vehicle_color: Optional[str] = None,
    availability_summary: Optional[str] = None,
    availability: Optional[dict] = None,
    preferred_service_categories: Optional[list[str]] = None,
    background_check_authorized: bool = False,
    license_document_ref: Optional[str] = None,
    insurance_document_ref: Optional[str] = None,
    registration_document_ref: Optional[str] = None,
    notes: Optional[str] = None,
) -> HealthISFDriverApplication:
    application = HealthISFDriverApplication(
        id=uuid4(),
        organization_id=organization_id,
        applicant_name=applicant_name,
        applicant_phone=applicant_phone,
        applicant_email=applicant_email,
        license_number=license_number,
        insurance_policy_number=insurance_policy_number,
        vehicle_make=vehicle_make,
        vehicle_model=vehicle_model,
        vehicle_year=vehicle_year,
        vehicle_plate=vehicle_plate,
        vehicle_color=vehicle_color,
        availability_summary=availability_summary,
        availability_json=json.dumps(availability) if availability else None,
        preferred_service_categories=json.dumps(preferred_service_categories or []),
        background_check_authorized=bool(background_check_authorized),
        license_document_ref=license_document_ref,
        insurance_document_ref=insurance_document_ref,
        registration_document_ref=registration_document_ref,
        onboarding_status="applied",
        review_notes=notes,
        created_at=now(),
        updated_at=now(),
    )
    db.add(application)
    _commit_or_rollback(db)
    db.refresh(application)
    return application


def get_driver_application_by_id(db: Session, application_id: str) -> Optional[HealthISFDriverApplication]:
    return (
        db.query(HealthISFDriverApplication)
        .filter(HealthISFDriverApplication.id == application_id)
        .first()
    )


def list_driver_applications(
    db: Session,
    *,
    organization_id: str,
    onboarding_status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
) -> list[HealthISFDriverApplication]:
    query = db.query(HealthISFDriverApplication).filter(
        HealthISFDriverApplication.organization_id == organization_id
    )
    if onboarding_status and onboarding_status != "all":
        query = query.filter(
            HealthISFDriverApplication.onboarding_status == _normalize_driver_application_status(onboarding_status)
        )
    return query.order_by(desc(HealthISFDriverApplication.created_at)).offset(skip).limit(limit).all()


def update_driver_application_status(
    db: Session,
    *,
    organization_id: str,
    application_id: str,
    onboarding_status: str,
    review_notes: Optional[str] = None,
    reviewed_by_user_id: Optional[str] = None,
) -> Optional[HealthISFDriverApplication]:
    application = get_driver_application_by_id(db, application_id)
    if not application or application.organization_id != organization_id:
        return None

    application.onboarding_status = _normalize_driver_application_status(onboarding_status)
    application.review_notes = review_notes
    application.reviewed_by_user_id = reviewed_by_user_id
    application.reviewed_at = now()
    application.updated_at = now()

    _commit_or_rollback(db)
    db.refresh(application)
    return application


def get_recurring_ride_templates(
    db: Session,
    *,
    organization_id: str,
    limit: int = 100,
) -> list[dict]:
    rides = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.recurring_trip_pattern.is_not(None),
        )
        .order_by(desc(HealthISFRide.updated_at))
        .limit(limit)
        .all()
    )
    templates: list[dict] = []
    for ride in rides:
        recurrence = _safe_json_parse(ride.recurring_trip_pattern) or {}
        if not recurrence:
            continue
        templates.append({
            "template_id": ride.id,
            "rider_name": ride.passenger_name,
            "service_type": ride.service_type,
            "category": str(recurrence.get("category") or ride.service_type),
            "pickup_address": ride.pickup_address,
            "dropoff_address": ride.dropoff_address,
            "preferred_pickup_time": recurrence.get("preferred_pickup_time"),
            "recurrence": recurrence,
            "preferred_driver_id": ride.driver_id,
            "preferred_driver_name": ride.driver.name if ride.driver else None,
            "next_scheduled_at": recurrence.get("next_scheduled_at") or (ride.appointment_time.isoformat() if ride.appointment_time else None),
            "last_status": str(ride.status),
        })
    return templates


def seed_phase43_mvp(db: Session, *, organization_id: Optional[str] = None) -> dict:
    base_summary = init_sample_data(db)
    org = _get_or_create_default_org(db) if not organization_id else _get_organization_by_id(db, organization_id)
    if not org:
        raise ValueError("Organization not found for Phase 43 seeding")

    providers = get_all_providers(db, limit=10)
    provider_id = providers[0].id if providers else None
    now_ts = now()
    recurring_templates = [
        {
            "passenger_name": "June Grant Commuter",
            "passenger_phone": "212-555-3101",
            "pickup_address": "70 Rural Route Rd, Hudson, NY",
            "dropoff_address": "Hudson Community Health Center, Hudson, NY",
            "service_type": "work_commute",
            "pattern": {
                "type": "weekly",
                "days": ["mon", "tue", "wed", "thu", "fri"],
                "preferred_pickup_time": "07:30",
                "category": "work",
                "next_scheduled_at": now_ts.isoformat(),
            },
        },
        {
            "passenger_name": "Dialysis Recurring Rider",
            "passenger_phone": "212-555-3102",
            "pickup_address": "15 Maple St, Catskill, NY",
            "dropoff_address": "Catskill Dialysis Center, Catskill, NY",
            "service_type": "dialysis_transport",
            "pattern": {
                "type": "weekly",
                "days": ["mon", "wed", "fri"],
                "preferred_pickup_time": "05:45",
                "category": "appointment",
                "next_scheduled_at": now_ts.isoformat(),
            },
        },
    ]

    created_recurring = 0
    for template in recurring_templates:
        duplicate = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == org.id,
            HealthISFRide.passenger_name == template["passenger_name"],
            HealthISFRide.service_type == template["service_type"],
            HealthISFRide.recurring_trip_pattern.is_not(None),
        ).first()
        if duplicate:
            continue
        create_ride(
            db,
            passenger_name=template["passenger_name"],
            passenger_phone=template["passenger_phone"],
            pickup_address=template["pickup_address"],
            dropoff_address=template["dropoff_address"],
            service_type=template["service_type"],
            provider_id=provider_id,
            organization_id=org.id,
            appointment_time=now_ts,
            recurring_trip_pattern=template["pattern"],
            notes="Phase 43 recurring transportation seed",
        )
        created_recurring += 1

    seeded_applications = [
        {
            "applicant_name": "Caleb Morgan",
            "applicant_phone": "212-555-4401",
            "applicant_email": "caleb.morgan@pilot.example",
            "license_number": "NY-CM-4401",
            "vehicle_make": "Toyota",
            "vehicle_model": "Sienna",
            "vehicle_year": 2020,
            "vehicle_plate": "AMI-4401",
            "availability_summary": "Weekday early mornings",
            "preferred_service_categories": ["appointment", "work"],
            "background_check_authorized": True,
            "onboarding_status": "pending_review",
        },
        {
            "applicant_name": "Nina Carter",
            "applicant_phone": "212-555-4402",
            "applicant_email": "nina.carter@pilot.example",
            "license_number": "NY-NC-4402",
            "vehicle_make": "Honda",
            "vehicle_model": "CR-V",
            "vehicle_year": 2019,
            "vehicle_plate": "AMI-4402",
            "availability_summary": "Weekend daytime",
            "preferred_service_categories": ["church", "grocery"],
            "background_check_authorized": True,
            "onboarding_status": "applied",
        },
    ]

    created_applications = 0
    for item in seeded_applications:
        exists = db.query(HealthISFDriverApplication).filter(
            HealthISFDriverApplication.organization_id == org.id,
            HealthISFDriverApplication.applicant_name == item["applicant_name"],
        ).first()
        if exists:
            continue
        app = create_driver_application(
            db,
            organization_id=org.id,
            applicant_name=item["applicant_name"],
            applicant_phone=item["applicant_phone"],
            applicant_email=item["applicant_email"],
            license_number=item["license_number"],
            vehicle_make=item["vehicle_make"],
            vehicle_model=item["vehicle_model"],
            vehicle_year=item["vehicle_year"],
            vehicle_plate=item["vehicle_plate"],
            availability_summary=item["availability_summary"],
            preferred_service_categories=item["preferred_service_categories"],
            background_check_authorized=item["background_check_authorized"],
            notes="Phase 43 onboarding seed",
        )
        if item["onboarding_status"] != "applied":
            update_driver_application_status(
                db,
                organization_id=org.id,
                application_id=app.id,
                onboarding_status=item["onboarding_status"],
                review_notes="Seeded review state for MVP launch.",
            )
        created_applications += 1

    return {
        "seed": "phase43",
        "organization_id": org.id,
        "base_seed": base_summary,
        "created_recurring_templates": created_recurring,
        "created_driver_applications": created_applications,
    }


def driver_contact_rider(
    db: Session,
    *,
    driver_id: str,
    ride_id: str,
    channel: str = "sms",
    message: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Notify rider via SMS/email or return dial target for voice contact."""
    from app.modules.health_isf import notifications as notify

    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        raise ValueError("Driver or ride not found")
    if ride.driver_id and ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")

    rider_phone = str(ride.passenger_phone or "").strip()
    normalized_channel = str(channel or "sms").strip().lower()
    if normalized_channel in {"call", "voice", "phone"}:
        if not rider_phone:
            raise ValueError("Rider phone number is unavailable for this ride")
        return {
            "ok": True,
            "channel": "call",
            "dial_target": rider_phone,
            "message": "Use device dialer to contact rider",
        }

    if not rider_phone:
        raise ValueError("Rider phone number is unavailable for this ride")

    if not notify.sms_provider_configured():
        raise ValueError("SMS/contact provider not configured yet")

    default_message = (
        f"Amicor driver {driver.name} is en route for your transport to "
        f"{ride.dropoff_address or 'your destination'}. Reply if you need assistance."
    )
    sms_body = str(message or default_message).strip()
    result = notify.send_sms(
        db,
        to_phone=rider_phone,
        message=sms_body,
        ride_id=ride.id,
        driver_id=driver.id,
        metadata={"actor_user_id": actor_user_id, "ride_id": ride.id},
    )
    result["dial_target"] = rider_phone
    return result


def seed_production_demo_data(
    db: Session,
    *,
    organization_id: Optional[str] = None,
    force: bool = False,
    target_drivers: int = 50,
    target_rides: int = 200,
    target_patients: int = 100,
) -> dict[str, Any]:
    """Populate realistic demo volume for sales, QA, and pilot operations."""
    org = _get_or_create_default_org(db) if not organization_id else _get_organization_by_id(db, organization_id)
    if not org:
        raise ValueError("Organization not found for production demo seeding")

    init_sample_data(db)

    existing_drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).count()
    existing_rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org.id).count()
    existing_providers = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org.id).count()

    if existing_rides >= target_rides and existing_drivers >= target_drivers and not force:
        return {
            "seed": "production_demo",
            "organization_id": org.id,
            "already_sufficient": True,
            "drivers": existing_drivers,
            "rides": existing_rides,
            "providers": existing_providers,
        }

    provider_names = [
        "Lincoln Medical Center",
        "Queens Dialysis Facility",
        "Manhattan Health Hub",
        "Brooklyn Community Clinic",
        "Bronx Care Network",
        "Staten Island Rehab Center",
        "Harlem Wellness Center",
        "Jamaica NEMT Hub",
        "Flushing Medical Plaza",
        "Yonkers Senior Care",
    ]
    providers = get_all_providers(db, limit=100)
    providers_map = {p.name: p for p in providers}
    created_providers = 0
    for idx, name in enumerate(provider_names):
        if name in providers_map:
            continue
        provider = create_provider(
            db,
            organization_id=org.id,
            name=name,
            address=f"{100 + idx} Care Blvd, New York, NY 100{idx % 10}",
            phone=f"212-555-{3100 + idx}",
            service_type="clinic" if idx % 2 == 0 else "facility",
        )
        providers_map[name] = provider
        created_providers += 1
    providers = list(providers_map.values())

    first_names = [
        "Patricia", "Robert", "Jennifer", "Michael", "Linda", "William", "Elizabeth", "David",
        "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Charles",
        "Karen", "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty", "Anthony",
        "Margaret", "Donald", "Sandra", "Mark", "Ashley", "Paul", "Kimberly", "Steven",
        "Emily", "Andrew", "Donna", "Joshua", "Michelle", "Kenneth", "Carol", "Kevin",
        "Amanda", "Brian", "Melissa", "George", "Deborah", "Edward", "Stephanie", "Ronald",
        "Rebecca", "Timothy", "Laura", "Jason", "Sharon", "Jeffrey", "Cynthia", "Ryan",
        "Kathleen", "Jacob", "Amy", "Gary", "Angela", "Nicholas", "Shirley", "Eric",
        "Anna", "Jonathan", "Brenda", "Stephen", "Pamela", "Larry", "Emma", "Justin",
        "Nicole", "Scott", "Helen", "Brandon", "Samantha", "Benjamin", "Katherine", "Samuel",
        "Christine", "Gregory", "Debra", "Alexander", "Rachel", "Patrick", "Carolyn", "Frank",
        "Janet", "Raymond", "Catherine", "Jack", "Maria", "Dennis", "Heather", "Jerry",
        "Diane", "Tyler", "Julie", "Aaron", "Joyce", "Jose", "Victoria", "Adam",
    ]
    last_names = [
        "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez",
        "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor",
        "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris",
        "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen",
    ]
    driver_first = ["James", "Maria", "David", "Sarah", "Carlos", "Aisha", "Brian", "Nina"]
    driver_last = ["Smith", "Garcia", "Chen", "Patel", "Johnson", "Williams", "Brown", "Davis"]
    vehicle_types = ["sedan", "van", "wheelchair_van", "sedan", "van"]
    driver_statuses = [DriverStatus.AVAILABLE, DriverStatus.BUSY, DriverStatus.OFFLINE]
    ride_statuses = [
        RideStatus.PENDING,
        RideStatus.ACCEPTED,
        RideStatus.IN_TRANSIT,
        RideStatus.COMPLETED,
        RideStatus.CANCELLED,
    ]
    service_types = ["dialysis", "medical_appointment", "medical_transport", "discharge", "recurring"]

    created_drivers = 0
    drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).all()
    driver_target = max(target_drivers, existing_drivers)
    while len(drivers) < driver_target:
        idx = len(drivers)
        vehicle = HealthISFVehicle(
            id=uuid4(),
            organization_id=org.id,
            vehicle_type=vehicle_types[idx % len(vehicle_types)],
            vehicle_plate=f"NYC-{4000 + idx}",
            capacity=4 if vehicle_types[idx % len(vehicle_types)] != "wheelchair_van" else 2,
            is_active=True,
            created_at=now(),
            updated_at=now(),
        )
        db.add(vehicle)
        db.flush()
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org.id,
            vehicle_id=vehicle.id,
            name=f"{driver_first[idx % len(driver_first)]} {driver_last[idx % len(driver_last)]}",
            phone=f"917-555-{5000 + idx}",
            vehicle_type=vehicle.vehicle_type,
            vehicle_plate=vehicle.vehicle_plate,
            status=driver_statuses[idx % len(driver_statuses)],
            is_active=True,
            total_trips=idx % 40,
            rating=round(4.5 + ((idx % 5) * 0.1), 1),
            created_at=now(),
            updated_at=now(),
        )
        db.add(driver)
        db.flush()
        drivers.append(driver)
        created_drivers += 1

    created_rides = 0
    ride_target = max(target_rides, existing_rides)
    for idx in range(existing_rides, ride_target):
        status = ride_statuses[idx % len(ride_statuses)]
        assigned_driver = drivers[idx % len(drivers)] if status != RideStatus.PENDING else None
        if status == RideStatus.PENDING:
            assigned_driver = None
        passenger = f"{first_names[idx % len(first_names)]} {last_names[idx % len(last_names)]}"
        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org.id,
            provider_id=providers[idx % len(providers)].id,
            driver_id=assigned_driver.id if assigned_driver else None,
            passenger_name=passenger,
            passenger_phone=f"646-555-{6000 + (idx % target_patients)}",
            pickup_address=f"{100 + (idx % 900)} Main St, New York, NY 100{idx % 10}",
            dropoff_address=f"{200 + (idx % 800)} Health Ave, Brooklyn, NY 112{idx % 10}",
            service_type=service_types[idx % len(service_types)],
            status=status,
            lifecycle_state=(
                RideStatus.COMPLETED.value
                if status == RideStatus.COMPLETED
                else RideStatus.ASSIGNED.value
                if status in (RideStatus.ACCEPTED, RideStatus.IN_TRANSIT)
                else RideStatus.QUEUED.value
            ),
            estimated_distance_miles=round(2.5 + (idx % 18) * 0.5, 1),
            estimated_duration_minutes=10 + (idx % 45),
            requested_at=now() - timedelta(hours=idx % 72),
            accepted_at=now() - timedelta(hours=max(0, (idx % 72) - 1)) if assigned_driver else None,
            completed_at=now() - timedelta(hours=max(0, (idx % 72) - 2)) if status == RideStatus.COMPLETED else None,
            created_at=now(),
            updated_at=now(),
        )
        db.add(ride)
        db.flush()
        _record_dispatch(db, ride_id=ride.id, action="ride_created", note="Production demo seed", driver_id=ride.driver_id)
        _record_status_history(db, ride.id, None, str(ride.status))
        created_rides += 1

        if status == RideStatus.COMPLETED and assigned_driver:
            trip = HealthISFTrip(
                id=uuid4(),
                ride_id=ride.id,
                driver_id=assigned_driver.id,
                status=TripStatus.COMPLETED,
                start_time=now(),
                end_time=now(),
                distance_miles=ride.estimated_distance_miles,
                duration_minutes=ride.estimated_duration_minutes,
                created_at=now(),
                updated_at=now(),
            )
            db.add(trip)
            db.flush()
            payout = HealthISFPayout(
                id=uuid4(),
                driver_id=assigned_driver.id,
                trip_id=trip.id,
                amount_usd=round(15.0 + (idx % 25), 2),
                status="processed",
                description=f"Demo payout for trip {trip.id[:8]}",
                created_at=now(),
                updated_at=now(),
            )
            db.add(payout)

    db.commit()
    return {
        "seed": "production_demo",
        "organization_id": org.id,
        "created_providers": created_providers,
        "created_drivers": created_drivers,
        "created_rides": created_rides,
        "totals": {
            "drivers": db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).count(),
            "rides": db.query(HealthISFRide).filter(HealthISFRide.organization_id == org.id).count(),
            "providers": db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org.id).count(),
            "unique_patients": min(target_patients, target_rides),
        },
    }


def get_all_rides(db: Session, skip: int = 0, limit: int = 100) -> list[HealthISFRide]:
    return db.query(HealthISFRide).order_by(
        desc(HealthISFRide.requested_at)
    ).offset(skip).limit(limit).all()


def get_ride_by_id(db: Session, ride_id: str) -> Optional[HealthISFRide]:
    return db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()


def get_latest_ride_execution_action(
    db: Session,
    *,
    ride_id: str,
    action_types: list[str],
) -> Optional[HealthISFRideExecutionAction]:
    if not action_types:
        return None
    return (
        db.query(HealthISFRideExecutionAction)
        .filter(
            HealthISFRideExecutionAction.ride_id == ride_id,
            HealthISFRideExecutionAction.action_type.in_(action_types),
            HealthISFRideExecutionAction.action_status == "success",
        )
        .order_by(desc(HealthISFRideExecutionAction.created_at))
        .first()
    )


def get_latest_trip_for_ride(db: Session, *, ride_id: str) -> Optional[HealthISFTrip]:
    return (
        db.query(HealthISFTrip)
        .filter(HealthISFTrip.ride_id == ride_id)
        .order_by(desc(HealthISFTrip.created_at))
        .first()
    )


def get_payout_for_trip(db: Session, *, trip_id: str) -> Optional[HealthISFPayout]:
    return (
        db.query(HealthISFPayout)
        .filter(HealthISFPayout.trip_id == trip_id)
        .order_by(desc(HealthISFPayout.created_at))
        .first()
    )


def get_ride_dispatch_history(db: Session, ride_id: str) -> list[HealthISFDispatchLog]:
    return db.query(HealthISFDispatchLog).filter(
        HealthISFDispatchLog.ride_id == ride_id
    ).order_by(HealthISFDispatchLog.created_at.asc()).all()


def get_ride_status_history(db: Session, ride_id: str) -> list[HealthISFRideStatusHistory]:
    return db.query(HealthISFRideStatusHistory).filter(
        HealthISFRideStatusHistory.ride_id == ride_id
    ).order_by(HealthISFRideStatusHistory.created_at.asc()).all()


def find_recent_duplicate_ride(
    db: Session,
    *,
    organization_id: str,
    intake_fingerprint: str,
    within_seconds: int = 2,
) -> Optional[HealthISFRide]:
    cutoff = now() - timedelta(seconds=max(within_seconds, 1))
    return (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.intake_fingerprint == intake_fingerprint,
            HealthISFRide.created_at >= cutoff,
        )
        .order_by(desc(HealthISFRide.created_at))
        .first()
    )


def create_ride(
    db: Session,
    passenger_name: str,
    passenger_phone: str,
    pickup_address: str,
    dropoff_address: str,
    service_type: str,
    provider_id: Optional[str] = None,
    organization_id: Optional[str] = None,
    estimated_distance_miles: Optional[float] = None,
    estimated_duration_minutes: Optional[int] = None,
    priority_score: Optional[float] = None,
    priority_tag: Optional[str] = None,
    is_emergency: bool = False,
    appointment_time: Optional[datetime] = None,
    recurring_trip_pattern: Optional[dict] = None,
    ai_dispatch_context: Optional[dict] = None,
    intake_fingerprint: Optional[str] = None,
    notes: Optional[str] = None,
    actor_user_id: Optional[str] = None,
) -> HealthISFRide:
    normalized_service_type = serialize_service_category(service_type)
    org = _get_or_create_default_org(db)
    if provider_id:
        provider = get_provider_by_id(db, provider_id)
        if not provider:
            raise ValueError("Provider not found")
        provider_org_id = provider.organization_id
        if organization_id and organization_id != provider_org_id:
            raise ValueError("Provider organization mismatch")
        organization_id = provider_org_id
    else:
        organization_id = organization_id or org.id

    ride = HealthISFRide(
        id=uuid4(),
        organization_id=organization_id,
        provider_id=provider_id,
        passenger_name=passenger_name,
        passenger_phone=passenger_phone,
        pickup_address=pickup_address,
        dropoff_address=dropoff_address,
        service_type=normalized_service_type,
        status=RideStatus.PENDING,
        lifecycle_state=RideStatus.REQUESTED.value,
        estimated_distance_miles=estimated_distance_miles,
        estimated_duration_minutes=estimated_duration_minutes,
        priority_score=priority_score,
        priority_tag=priority_tag,
        is_emergency=is_emergency,
        appointment_time=appointment_time,
        recurring_trip_pattern=json.dumps(recurring_trip_pattern) if recurring_trip_pattern else None,
        ai_dispatch_context=json.dumps(ai_dispatch_context) if ai_dispatch_context else None,
        intake_fingerprint=intake_fingerprint,
        notes=notes,
        created_by_user_id=actor_user_id,
        requested_at=now(),
        created_at=now(),
        updated_at=now(),
    )
    try:
        db.add(ride)
        db.flush()
    except Exception as e:
        logger.error({
            "event": "uniqueness_collision",
            "context": "create_ride",
            "ride_id": ride.id,
            "error": str(e)
        })
        db.rollback()
        raise

    try:
        RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=RideStatus.QUEUED.value,
            action_type="ride_created",
            actor_user_id=actor_user_id,
            note="Ride created and queued for dispatch",
            payload={"service_type": normalized_service_type, "is_emergency": is_emergency},
        )
        _commit_or_rollback(db)
    except Exception as e:
        logger.error({
            "event": "lifecycle_transition_error",
            "context": "create_ride",
            "ride_id": ride.id,
            "error": str(e)
        })
        db.rollback()
        raise
    db.refresh(ride)
    _safe_runtime_register(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="create_ride",
    )
    if not ride.driver_id:
        run_intake_dispatch_automation(
            db,
            ride_id=ride.id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        db.refresh(ride)
    return ride


def cancel_ride(
    db: Session,
    *,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    reason: Optional[str] = None,
) -> Optional[HealthISFRide]:
    """Cancel a ride using the canonical lifecycle engine."""
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        return None

    current_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if current_state in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
        raise ValueError("Ride is already terminal")

    if ride.driver_id:
        driver = get_driver_by_id(db, ride.driver_id)
        if driver and _driver_active_workload_count(db, driver.id) <= 1:
            _set_driver_status(db, driver, DriverStatus.AVAILABLE)
            driver.availability_state = "available"
            driver.is_online = True
            driver.auth_state = "active"
            driver.last_seen_at = now()

    RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.CANCELLED.value,
        action_type="ride_cancelled",
        actor_user_id=actor_user_id,
        note=reason or "Ride cancelled",
        payload={"reason": reason or "Ride cancelled"},
    )
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        note=reason or "Ride cancelled",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.CANCELLED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_unregister(ride_id=ride.id, reason="ride_cancelled")
    return ride


def update_ride_status(
    db: Session,
    ride_id: str,
    status: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        _safe_runtime_record_lifecycle_reject()
        logger.warning({
            "event": "lifecycle_transition_rejected",
            "ride_id": ride_id,
            "requested_status": status,
            "reason": "Ride not found"
        })
        return None

    current_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    target_state = _normalize_target_ride_state(status)

    allowed_targets = {
        RideStatus.REQUESTED.value,
        RideStatus.QUEUED.value,
        RideStatus.ASSIGNED.value,
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.COMPLETED.value,
    }
    if target_state not in allowed_targets:
        _safe_runtime_record_lifecycle_reject()
        logger.warning({
            "event": "lifecycle_transition_rejected",
            "ride_id": ride_id,
            "current_state": current_state,
            "requested_state": target_state,
            "actor_user_id": actor_user_id,
            "reason": "Target state outside strict lifecycle workflow"
        })
        raise ValueError(f"Invalid target state: {target_state}")

    # Strict workflow progression (compat: requested/queued -> assigned)
    allowed_transitions: dict[str, set[str]] = {
        RideStatus.REQUESTED.value: {RideStatus.ASSIGNED.value},
        RideStatus.QUEUED.value: {RideStatus.ASSIGNED.value},
        RideStatus.ASSIGNED.value: {RideStatus.DRIVER_EN_ROUTE.value},
        RideStatus.DRIVER_EN_ROUTE.value: {RideStatus.ARRIVED.value},
        RideStatus.ARRIVED.value: {RideStatus.RIDER_ONBOARD.value},
        RideStatus.RIDER_ONBOARD.value: {RideStatus.IN_PROGRESS.value},
        RideStatus.IN_PROGRESS.value: {RideStatus.COMPLETED.value},
        RideStatus.COMPLETED.value: set(),
    }

    if target_state == current_state:
        logger.info({
            "event": "lifecycle_transition_idempotent",
            "ride_id": ride_id,
            "state": current_state,
            "actor_user_id": actor_user_id
        })
        return ride

    allowed_next = allowed_transitions.get(current_state, set())
    if target_state not in allowed_next:
        _safe_runtime_record_lifecycle_reject()
        rejection_reason = f"Invalid lifecycle transition: {current_state} -> {target_state}"
        logger.warning({
            "event": "lifecycle_transition_rejected",
            "ride_id": ride_id,
            "current_state": current_state,
            "requested_state": target_state,
            "actor_user_id": actor_user_id,
            "reason": rejection_reason
        })
        raise ValueError(rejection_reason)

    if target_state in {
        RideStatus.ASSIGNED.value,
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
    } and not ride.driver_id:
        _safe_runtime_record_lifecycle_reject()
        logger.warning({
            "event": "lifecycle_transition_rejected",
            "ride_id": ride_id,
            "requested_state": target_state,
            "actor_user_id": actor_user_id,
            "reason": "Ride must have an assigned driver before progressing"
        })
        raise ValueError("Ride must have an assigned driver before progressing to active execution")

    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    try:
        accepted = RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=target_state,
            action_type="status_changed",
            actor_user_id=actor_user_id,
            note=f"Lifecycle changed from {current_state} to {target_state}",
            payload={"requested_status": str(status)},
            event_id=event_id,
            sequence_number=sequence_number,
            monotonic_ts=monotonic_ts,
            source="update_ride_status",
        )
        if not accepted:
            logger.info({"event": "duplicate_or_stale_status_rejected", "ride_id": ride.id, "requested_state": target_state})
        if accepted and target_state == RideStatus.COMPLETED.value and ride.driver_id:
            driver = get_driver_by_id(db, ride.driver_id)
            if driver:
                driver.total_trips = int(driver.total_trips or 0) + 1
                _set_driver_status(db, driver, DriverStatus.AVAILABLE)
                driver.availability_state = "available"
                driver.is_online = True
                driver.auth_state = "active"
                driver.last_seen_at = now()
            _ensure_completion_billing_records(db, ride)
        _commit_or_rollback(db)
    except Exception as e:
        logger.error({
            "event": "lifecycle_transition_error",
            "ride_id": ride_id,
            "current_state": current_state,
            "requested_state": target_state,
            "actor_user_id": actor_user_id,
            "error": str(e)
        })
        raise
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride)
    _commit_or_rollback(db)
    db.refresh(ride)
    if target_state in {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
    }:
        _safe_runtime_unregister(ride_id=ride.id, reason=f"status_transition:{target_state}")
    else:
        _safe_runtime_update(
            ride=ride,
            state=target_state,
            source="update_ride_status",
            driver_id=str(ride.driver_id) if ride.driver_id else None,
        )
    logger.info({
        "event": "lifecycle_transition_success",
        "ride_id": ride_id,
        "from_state": current_state,
        "to_state": target_state,
        "actor_user_id": actor_user_id
    })
    return ride


def assign_driver_to_ride(
    db: Session,
    ride_id: str,
    driver_id: str,
    actor_user_id: Optional[str] = None,
    allow_assigned_driver: bool = False,
    allow_existing_assignment: bool = False,
    allow_reassignment: bool = False,
) -> Optional[HealthISFRide]:
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "reason": "Ride not found"
        })
        return None

    driver = get_driver_by_id(db, driver_id)
    if not driver:
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "reason": "Driver not found"
        })
        raise ValueError("Driver not found")

    if not driver.is_active:
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "driver_status": driver.status,
            "reason": "Driver inactive"
        })
        raise ValueError("Cannot assign inactive driver")

    if ride.organization_id != driver.organization_id:
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "reason": "Driver org mismatch"
        })
        raise ValueError("Driver must belong to the same organization as ride")

    ride_status = RideStatus(ride.status)
    if ride_status in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "ride_status": ride.status,
            "reason": "Ride is terminal"
        })
        raise ValueError("Cannot assign driver to completed or cancelled ride")

    if driver.status not in {DriverStatus.AVAILABLE, DriverStatus.UNAVAILABLE} and not (
        allow_assigned_driver and driver.status == DriverStatus.ASSIGNED
    ):
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "driver_status": driver.status,
            "reason": "Driver unavailable"
        })
        raise ValueError("Cannot assign unavailable driver")

    if ride.driver_id is not None and str(ride.driver_id) != str(driver.id):
        if not allow_reassignment:
            logger.warning({
                "event": "assignment_rejected",
                "ride_id": ride_id,
                "driver_id": driver_id,
                "current_driver_id": ride.driver_id,
                "reason": "Ride already assigned"
            })
            raise ValueError("Ride already has an assigned driver")
        previous_driver = get_driver_by_id(db, ride.driver_id)
        if previous_driver and _driver_active_workload_count(db, previous_driver.id) <= 1:
            _set_driver_status(db, previous_driver, DriverStatus.AVAILABLE)
            previous_driver.availability_state = "available"
            previous_driver.is_online = True
            previous_driver.auth_state = "active"
            previous_driver.last_seen_at = now()
    elif ride.driver_id is not None and not (
        allow_existing_assignment and str(ride.driver_id) == str(driver.id)
    ):
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "current_driver_id": ride.driver_id,
            "reason": "Ride already assigned"
        })
        raise ValueError("Ride already has an assigned driver")

    old_driver = ride.driver_id if str(ride.driver_id or "") != str(driver.id) else None
    now_ts = now()
    latest_assignment = _latest_assignment_for_ride(db, ride.id)
    reassignment_chain_id = (
        str(latest_assignment.reassignment_chain_id)
        if latest_assignment and latest_assignment.reassignment_chain_id
        else str(uuid4())
    )
    ride.driver_id = driver.id
    ride.assigned_by_user_id = actor_user_id
    _set_driver_status(db, driver, DriverStatus.ASSIGNED)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()

    current_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if current_state == RideStatus.REQUESTED.value:
        RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=RideStatus.QUEUED.value,
            action_type="ride_queued",
            actor_user_id=actor_user_id,
            note="Ride queued before assignment",
        )
    RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.ASSIGNED.value,
        action_type="driver_assigned",
        actor_user_id=actor_user_id,
        note=("Driver reassigned" if old_driver else "Driver assigned"),
        payload={"driver_id": driver.id, "previous_driver_id": old_driver},
    )

    active_assignment = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.driver_id == driver.id,
        )
        .order_by(desc(HealthISFDispatchAssignment.created_at), desc(HealthISFDispatchAssignment.attempt_index))
        .first()
    )
    if active_assignment is None or str(active_assignment.assignment_state or "") in {
        DispatchAssignmentState.REJECTED.value,
        DispatchAssignmentState.EXPIRED.value,
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        DispatchAssignmentState.DROPOFF_COMPLETE.value,
    }:
        active_assignment = HealthISFDispatchAssignment(
            organization_id=ride.organization_id,
            ride_id=ride.id,
            driver_id=driver.id,
            assignment_state=DispatchAssignmentState.OFFERED.value,
            attempt_index=_next_assignment_attempt_index(db, ride.id),
            timeout_seconds=0,
            queued_at=now_ts,
            search_started_at=now_ts,
            assigned_at=None,
            reassignment_attempt_count=max(0, int((latest_assignment.attempt_index if latest_assignment else 0) or 0)),
            reassignment_chain_id=reassignment_chain_id,
            metadata_json=json.dumps({"stage": "direct_assignment", "source": "assign_driver_to_ride"}),
            created_by_user_id=actor_user_id,
            created_at=now_ts,
            updated_at=now_ts,
        )
        db.add(active_assignment)
    else:
        active_assignment.assignment_state = DispatchAssignmentState.OFFERED.value
        active_assignment.assigned_at = active_assignment.assigned_at or now_ts
        active_assignment.reassignment_chain_id = active_assignment.reassignment_chain_id or reassignment_chain_id
        active_assignment.updated_at = now_ts
        active_assignment.metadata_json = json.dumps(
            {
                "note": "Driver offer issued to ride",
                "reassignment_chain_id": active_assignment.reassignment_chain_id,
            }
        )

    superseded_assignments = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.id != active_assignment.id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.QUEUED.value,
                    DispatchAssignmentState.SEARCHING.value,
                    DispatchAssignmentState.AWAITING_APPROVAL.value,
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.ACCEPTED.value,
                    DispatchAssignmentState.EN_ROUTE_PICKUP.value,
                    DispatchAssignmentState.PICKUP_COMPLETE.value,
                ]
            ),
        )
        .all()
    )
    for row in superseded_assignments:
        row.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        row.reassignment_pending_at = row.reassignment_pending_at or now_ts
        row.reassignment_reason = (
            "duplicate_assignment_suppressed"
            if str(getattr(row, "driver_id", "") or "") == str(driver.id)
            else "superseded_by_assignment"
        )
        row.closed_reason = row.closed_reason or "superseded_by_assignment"
        row.updated_at = now_ts

    try:
        _commit_or_rollback(db)
    except Exception as e:
        logger.error({
            "event": "assignment_persistence_error",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "error": str(e)
        })
        raise
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.BROADCASTED.value)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_register(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="assign_driver_to_ride",
        driver_id=driver.id,
    )
    logger.info({
        "event": "assignment_success",
        "ride_id": ride_id,
        "driver_id": driver_id,
        "actor_user_id": actor_user_id
    })
    return ride


def assign_vehicle_to_ride(
    db: Session,
    ride_id: str,
    vehicle_id: str,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFRide]:
    ride = get_ride_by_id(db, ride_id)
    if not ride:
        return None

    vehicle = get_vehicle_by_id(db, vehicle_id)
    if not vehicle:
        raise ValueError("Vehicle not found")
    if not vehicle.is_active:
        raise ValueError("Cannot assign inactive vehicle")
    if str(ride.organization_id) != str(vehicle.organization_id):
        raise ValueError("Vehicle must belong to the same organization as ride")

    ride_status = RideStatus(ride.status)
    if ride_status in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise ValueError("Cannot assign vehicle to completed or cancelled ride")

    ride.vehicle_id = vehicle.id
    ride.assigned_by_user_id = actor_user_id
    _commit_or_rollback(db)
    db.refresh(ride)
    return ride


def get_dashboard_metrics(db: Session) -> DashboardMetrics:
    rides = db.query(HealthISFRide).all()
    drivers = db.query(HealthISFDriver).all()
    payouts = db.query(HealthISFPayout).all()
    completed_trips = db.query(HealthISFTrip).filter(HealthISFTrip.status == TripStatus.COMPLETED).all()

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    rides_today = [ride for ride in rides if ride.requested_at and ride.requested_at.replace(tzinfo=None) >= today_start]
    lifecycle = [RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status) for ride in rides]
    pending_rides = [ride for ride, state in zip(rides, lifecycle) if state in {RideStatus.REQUESTED.value, RideStatus.QUEUED.value}]
    assigned_rides = [
        ride for ride, state in zip(rides, lifecycle)
        if state in {RideStatus.ASSIGNED.value, RideStatus.DRIVER_EN_ROUTE.value, RideStatus.ARRIVED.value} and ride.driver_id
    ]
    active_rides = [
        ride for ride, state in zip(rides, lifecycle)
        if state in {
            RideStatus.ASSIGNED.value,
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ARRIVED.value,
            RideStatus.RIDER_ONBOARD.value,
            RideStatus.IN_PROGRESS.value,
            RideStatus.ESCALATED.value,
        }
    ]
    completed_rides = [ride for ride, state in zip(rides, lifecycle) if state == RideStatus.COMPLETED.value]
    cancelled_rides = [ride for ride, state in zip(rides, lifecycle) if state in {RideStatus.CANCELLED.value, RideStatus.FAILED.value}]

    available_drivers = [driver for driver in drivers if _coerce_driver_status(driver.status) == DriverStatus.AVAILABLE]
    busy_drivers = [driver for driver in drivers if _is_driver_busy(driver.status)]
    offline_drivers = [driver for driver in drivers if _coerce_driver_status(driver.status) == DriverStatus.OFFLINE]

    avg_rating = sum(driver.rating for driver in drivers) / len(drivers) if drivers else 5.0
    pending_payouts_usd = sum(payout.amount_usd for payout in payouts if payout.status == "pending")
    total_payouts_usd = sum(payout.amount_usd for payout in payouts)
    ride_durations = [
        (ride.completed_at - ride.requested_at).total_seconds() / 60.0
        for ride in completed_rides
        if ride.completed_at and ride.requested_at
    ]
    avg_duration = sum(ride_durations) / len(ride_durations) if ride_durations else 0.0

    return DashboardMetrics(
        total_rides=len(rides),
        total_rides_today=len(rides_today),
        pending_rides=len(pending_rides),
        assigned_rides=len(assigned_rides),
        active_rides=len(active_rides),
        completed_rides=len(completed_rides),
        cancelled_rides=len(cancelled_rides),
        total_drivers=len(drivers),
        available_drivers=len(available_drivers),
        busy_drivers=len(busy_drivers),
        offline_drivers=len(offline_drivers),
        total_providers=db.query(HealthISFProvider).filter(HealthISFProvider.is_active == True).count(),
        total_trips_completed=len(completed_trips),
        avg_driver_rating=round(avg_rating, 2),
        average_ride_duration_minutes=round(avg_duration, 2),
        cancellation_count=len(cancelled_rides),
        pending_payouts_usd=round(pending_payouts_usd, 2),
        total_payouts_usd=round(total_payouts_usd, 2),
        timestamp=now(),
    )
