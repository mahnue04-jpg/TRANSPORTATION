"""
Service layer for Health ISF module.
Persists provider/driver/ride operations with audit timeline entries.
"""

import contextvars
import logging
import json
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Any

from sqlalchemy import and_, case, desc, func, or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    CustomerRequestStatus,
    DispatchAssignmentState,
    DispatchEventRetry,
    DispatcherActivityLog,
    HealthISFBillingHandoff,
    HealthISFClaim,
    HealthISFCustomerRideRequest,
    HealthISFDispatchAssignment,
    DispatchDeadLetterEvent,
    HealthISFDriverLocationPing,
    HealthISFDriverSession,
    DriverStatus,
    HealthISFDispatchLog,
    HealthISFDriverApplication,
    HealthISFDriver,
    HealthISFPaymentTransaction,
    HealthISFRecurringRideSchedule,
    HealthISFSettlementLedger,
    HealthISFOrganization,
    HealthISFPayout,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideExecutionAction,
    HealthISFRideRoutePlan,
    HealthISFTripDocument,
    HealthISFTripFinancialRecord,
    HealthISFWorkflowAuditLog,
    HealthISFWorkflowEscalation,
    HealthISFWorkflowExecution,
    HealthISFWorkflowIncident,
    OperationalAlertLog,
    RealTimeEvent,
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


class RideLifecycleConflictError(ValueError):
    """Raised when a duplicate or out-of-order lifecycle action is attempted."""

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

LEGACY_DRIVER_AVAILABILITY_ALIASES = {
    "offer_pending": "available",
    "assigned": "available",
    "busy": "on_trip",
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
    RideStatus.ARRIVED_DESTINATION.value,
}

ACTIVE_DISPATCH_ASSIGNMENT_STATES = {
    DispatchAssignmentState.OFFERED.value,
    DispatchAssignmentState.ASSIGNED.value,
    DispatchAssignmentState.ACCEPTED.value,
    DispatchAssignmentState.EN_ROUTE_PICKUP.value,
    DispatchAssignmentState.PICKUP_COMPLETE.value,
    DispatchAssignmentState.ARRIVED_DESTINATION.value,
}

SCHEDULED_DISPATCH_ASSIGNMENT_STATES = {
    DispatchAssignmentState.SCHEDULED_OFFERED.value,
    DispatchAssignmentState.SCHEDULED_ACCEPTED.value,
}

DRIVER_APP_ASSIGNMENT_STATES = tuple(ACTIVE_DISPATCH_ASSIGNMENT_STATES) + (
    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
)

DRIVER_MOBILE_ELIGIBLE_LIFECYCLE = ACTIVE_RIDE_STATUSES_FOR_ASSIGNMENT | {
    RideStatus.QUEUED.value,
    RideStatus.REQUESTED.value,
}

CLOSED_DISPATCH_ASSIGNMENT_STATES = {
    DispatchAssignmentState.REJECTED.value,
    DispatchAssignmentState.DROPOFF_COMPLETE.value,
    "expired",
}

AI_PROOF_RIDE_NAME_MARKERS = (
    "driver ai proof",
    "production proof",
    "proof driver",
    "live dispatch driver",
    "hydration proof",
    "proof rider",
)
AI_PROOF_RIDE_ADDRESS_MARKERS = (
    "live pickup",
    "live dropoff",
    "rider browser pickup",
    "rider browser dropoff",
    "rider app verify",
    "ops verify",
    "flow pickup",
    "flow dropoff",
    "proof pickup",
    "proof dropoff",
)

_reconcile_coherence_depth: contextvars.ContextVar[int] = contextvars.ContextVar(
    "reconcile_coherence_depth",
    default=0,
)
MAX_RECONCILE_COHERENCE_DEPTH = 2


def _normalize_status_token(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("ridestatus."):
        raw = raw.split(".", 1)[1]
    if raw.startswith("driverstatus."):
        raw = raw.split(".", 1)[1]
    return raw


def _is_ai_proof_ride(ride: Optional[HealthISFRide]) -> bool:
    if not ride:
        return False
    blob = " ".join(
        [
            str(ride.passenger_name or ""),
            str(ride.pickup_address or ""),
            str(ride.dropoff_address or ""),
            str(ride.notes or ""),
        ]
    ).strip().lower()
    if any(marker in blob for marker in AI_PROOF_RIDE_NAME_MARKERS):
        return True
    return any(marker in blob for marker in AI_PROOF_RIDE_ADDRESS_MARKERS)


def _ride_is_terminal(ride: Optional[HealthISFRide]) -> bool:
    if not ride:
        return True
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle in {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
        "no_show",
        "declined",
    }:
        return True
    return bool(ride.completed_at)


def _ride_is_driver_mobile_eligible(ride: Optional[HealthISFRide]) -> bool:
    """Only pending/queued/assigned/in-progress rides may surface on Driver Mobile."""
    if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
        return False
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    return lifecycle in DRIVER_MOBILE_ELIGIBLE_LIFECYCLE


@dataclass
class DriverRideOperationalState:
    is_active: bool
    has_active_offer: bool
    is_dispatch_eligible: bool
    effective_assignment_state: str
    reason: str
    assignment: Optional[HealthISFDispatchAssignment] = None


def is_operational_excluded_ride(ride: Optional[HealthISFRide]) -> bool:
    """Shared proof/demo filter for dispatch, driver app, AI, billing active views."""
    if not ride:
        return True
    return _is_ai_proof_ride(ride) or _is_test_ride_row(ride)


def evaluate_driver_ride_operational_state(
    db: Session,
    *,
    ride: HealthISFRide,
    driver_id: str,
    assignment: Optional[HealthISFDispatchAssignment] = None,
) -> DriverRideOperationalState:
    """Authoritative rule: whether a ride is active for a driver across all surfaces."""
    target_driver = str(driver_id or "")
    if not target_driver or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
        return DriverRideOperationalState(
            is_active=False,
            has_active_offer=False,
            is_dispatch_eligible=False,
            effective_assignment_state="",
            reason="terminal_or_excluded",
        )
    if str(ride.driver_id or "") != target_driver:
        row_check = assignment or _latest_driver_assignment_for_ride(
            db,
            ride_id=str(ride.id),
            driver_id=target_driver,
        )
        if str(ride.driver_id or "") and str(ride.driver_id or "") != target_driver:
            return DriverRideOperationalState(
                is_active=False,
                has_active_offer=False,
                is_dispatch_eligible=False,
                effective_assignment_state="",
                reason="driver_mismatch",
            )
        if not row_check or str(row_check.driver_id or "") != target_driver:
            return DriverRideOperationalState(
                is_active=False,
                has_active_offer=False,
                is_dispatch_eligible=False,
                effective_assignment_state="",
                reason="driver_mismatch",
            )
        row = row_check
        assignment = row_check
    else:
        row = assignment or _latest_driver_assignment_for_ride(
            db,
            ride_id=str(ride.id),
            driver_id=target_driver,
        )
    assignment_state = str(getattr(row, "assignment_state", "") or "")
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    pre_accept_lifecycle = {
        RideStatus.QUEUED.value,
        RideStatus.REQUESTED.value,
        RideStatus.PENDING.value,
        RideStatus.ASSIGNED.value,
    }

    if row and assignment_state in SCHEDULED_DISPATCH_ASSIGNMENT_STATES:
        from app.modules.health_isf.scheduling import is_dispatch_eligible

        if not is_dispatch_eligible(ride):
            return DriverRideOperationalState(
                is_active=False,
                has_active_offer=False,
                is_dispatch_eligible=False,
                effective_assignment_state=assignment_state,
                reason="scheduled_reservation",
                assignment=row,
            )

    if row and assignment_state in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
        offer_open = assignment_state in {
            DispatchAssignmentState.OFFERED.value,
            DispatchAssignmentState.ASSIGNED.value,
            DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        }
        offer_expired = False
        if row.offer_expires_at and assignment_state == DispatchAssignmentState.OFFERED.value:
            if _as_utc_datetime(row.offer_expires_at) < _as_utc_datetime(now()):
                offer_open = False
                offer_expired = True
        if offer_expired and lifecycle in pre_accept_lifecycle:
            return DriverRideOperationalState(
                is_active=False,
                has_active_offer=False,
                is_dispatch_eligible=True,
                effective_assignment_state=assignment_state,
                reason="expired_bound_needs_reconcile",
                assignment=row,
            )
        return DriverRideOperationalState(
            is_active=True,
            has_active_offer=offer_open and assignment_state == DispatchAssignmentState.OFFERED.value,
            is_dispatch_eligible=lifecycle in pre_accept_lifecycle
            and not ride.accepted_at,
            effective_assignment_state=assignment_state,
            reason="active_assignment",
            assignment=row,
        )

    if row and assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
        if str(ride.driver_id or "") == target_driver:
            closed_reason = str(getattr(row, "closed_reason", "") or "").lower()
            if any(
                marker in closed_reason
                for marker in (
                    "superseded",
                    "duplicate",
                    "terminal_ride",
                    "orphaned",
                    "executive_phase4",
                )
            ):
                return DriverRideOperationalState(
                    is_active=False,
                    has_active_offer=False,
                    is_dispatch_eligible=False,
                    effective_assignment_state=assignment_state,
                    reason="superseded_offer_not_restored",
                    assignment=row,
                )
            coerced_state = (
                DispatchAssignmentState.ACCEPTED.value
                if ride.accepted_at
                else DispatchAssignmentState.OFFERED.value
            )
            return DriverRideOperationalState(
                is_active=True,
                has_active_offer=coerced_state == DispatchAssignmentState.OFFERED.value,
                is_dispatch_eligible=lifecycle in pre_accept_lifecycle and not ride.accepted_at,
                effective_assignment_state=coerced_state,
                reason="bound_reassignment_pending_coerced",
                assignment=row,
            )

    expired_bound_states = {
        DispatchAssignmentState.EXPIRED.value,
        "expired",
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
    }
    if row and assignment_state in expired_bound_states and lifecycle in pre_accept_lifecycle:
        closed_reason = str(getattr(row, "closed_reason", "") or "").lower()
        if any(
            marker in closed_reason
            for marker in (
                "superseded",
                "duplicate",
                "terminal_ride",
                "orphaned",
                "executive_phase4",
            )
        ):
            return DriverRideOperationalState(
                is_active=False,
                has_active_offer=False,
                is_dispatch_eligible=False,
                effective_assignment_state=assignment_state,
                reason="superseded_offer_not_restored",
                assignment=row,
            )
        return DriverRideOperationalState(
            is_active=False,
            has_active_offer=False,
            is_dispatch_eligible=True,
            effective_assignment_state=assignment_state,
            reason="expired_bound_needs_reconcile",
            assignment=row,
        )

    if lifecycle in ACTIVE_RIDE_STATUSES_FOR_ASSIGNMENT and row and assignment_state not in CLOSED_DISPATCH_ASSIGNMENT_STATES:
        return DriverRideOperationalState(
            is_active=True,
            has_active_offer=False,
            is_dispatch_eligible=False,
            effective_assignment_state=assignment_state,
            reason="in_progress_lifecycle",
            assignment=row,
        )

    return DriverRideOperationalState(
        is_active=False,
        has_active_offer=False,
        is_dispatch_eligible=False,
        effective_assignment_state=assignment_state,
        reason="inactive",
        assignment=row,
    )


def reconcile_expired_bound_driver_assignment(
    db: Session,
    ride: HealthISFRide,
    *,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    """Idempotently restore expired-but-bound assignments to offered for the same driver."""
    if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
        return None

    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle not in {
        RideStatus.QUEUED.value,
        RideStatus.REQUESTED.value,
        RideStatus.PENDING.value,
        RideStatus.ASSIGNED.value,
    }:
        return None

    driver_id = str(ride.driver_id or "")
    assignment = None
    if driver_id:
        open_for_other = _active_assignment_for_ride(db, str(ride.id))
        if open_for_other and str(open_for_other.driver_id or "") != driver_id:
            return None
        assignment = _latest_driver_assignment_for_ride(db, ride_id=str(ride.id), driver_id=driver_id)
    if not assignment:
        assignment = _authoritative_assignment_for_ride(db, ride)
        if assignment and not driver_id:
            driver_id = str(assignment.driver_id or "")
        if not assignment or not driver_id:
            assignment = (
                db.query(HealthISFDispatchAssignment)
                .filter(HealthISFDispatchAssignment.ride_id == str(ride.id))
                .order_by(desc(HealthISFDispatchAssignment.updated_at))
                .first()
            )
            if assignment and not driver_id:
                driver_id = str(assignment.driver_id or "")
    if not assignment or not driver_id:
        return None

    if str(assignment.driver_id or "") != driver_id:
        return None

    assignment_state = str(assignment.assignment_state or "")
    closed_reason = str(getattr(assignment, "closed_reason", "") or "").lower()
    if closed_reason and any(
        marker in closed_reason
        for marker in (
            "superseded",
            "duplicate",
            "terminal_ride",
            "terminal_reassignment",
            "orphaned",
            "executive_phase4",
            "sweep",
            "dropoff_complete",
            "dropoff_completed",
            "offer_timeout",
            "driver_rejected",
        )
    ):
        return None

    other_active = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.ride_id != str(ride.id),
            HealthISFDispatchAssignment.assignment_state.in_(
                list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .first()
    )
    if other_active:
        other_ride = get_ride_by_id(db, str(other_active.ride_id or ""))
        if other_ride and _ride_is_driver_mobile_eligible(other_ride):
            other_expired = bool(
                other_active.offer_expires_at
                and _as_utc_datetime(other_active.offer_expires_at) < _as_utc_datetime(now())
            )
            if str(other_active.assignment_state or "") != DispatchAssignmentState.OFFERED.value or not other_expired:
                return None
    now_ts = now()
    offer_expired = bool(
        assignment.offer_expires_at
        and _as_utc_datetime(assignment.offer_expires_at) < _as_utc_datetime(now_ts)
    )
    if assignment_state == DispatchAssignmentState.OFFERED.value and not offer_expired:
        if str(ride.driver_id or "") != driver_id:
            ride.driver_id = driver_id
            ride.updated_at = now_ts
        return assignment

    needs_restore = assignment_state in {
        DispatchAssignmentState.EXPIRED.value,
        "expired",
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
    } or (assignment_state == DispatchAssignmentState.OFFERED.value and offer_expired)
    if not needs_restore:
        if assignment_state in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
            return assignment
        return None

    driver = get_driver_by_id(db, driver_id)
    if not driver or not driver.is_active:
        return None

    assignment.assignment_state = DispatchAssignmentState.OFFERED.value
    assignment.offered_at = assignment.offered_at or now_ts
    assignment.offer_expires_at = now_ts + timedelta(seconds=120)
    assignment.expired_at = None
    assignment.reassignment_pending_at = None
    assignment.closed_reason = None
    assignment.updated_at = now_ts
    ride.driver_id = driver_id
    ride.updated_at = now_ts

    _record_dispatch(
        db,
        ride_id=ride.id,
        action="expired_bound_assignment_restored",
        driver_id=driver_id,
        acted_by_user_id=actor_user_id,
        note="Expired assignment restored to offered for bound driver",
        assignment_id=assignment.id,
        lifecycle_state=str(ride.lifecycle_state or ride.status),
        transition_reason="expired_bound_reconcile",
        assignment_transition_source="reconcile_expired_bound_driver_assignment",
    )
    sync_customer_request_from_ride(db, ride)
    return assignment


def _assignment_recency_token(row: HealthISFDispatchAssignment) -> str:
    return _normalized_timestamp_token(
        row.updated_at or row.offered_at or row.assigned_at or row.created_at
    )


def _reconcile_conflicting_driver_preaccept_assignments(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    prefer_ride_id: Optional[str] = None,
    reason: str = "superseded_by_newer_driver_assignment",
) -> int:
    """Keep one pre-accept offer per driver; expire older conflicting assignments."""
    now_ts = now()
    closed = 0
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                ]
            ),
        )
        .all()
    )
    candidates: list[tuple[HealthISFDispatchAssignment, HealthISFRide, str]] = []
    for row in rows:
        if row.offer_expires_at and _as_utc_datetime(row.offer_expires_at) <= _as_utc_datetime(now_ts):
            continue
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            if ride and is_operational_excluded_ride(ride):
                _close_excluded_driver_binding(
                    db,
                    row,
                    ride,
                    reason="excluded_preaccept_reconcile",
                )
                closed += 1
            continue
        lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if (
            str(row.assignment_state or "") == DispatchAssignmentState.OFFERED.value
            and ride.accepted_at
            and not row.accepted_at
        ):
            _sync_offered_assignment_with_accepted_ride(db, row, ride)
            continue
        if ride.accepted_at or lifecycle in {
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ARRIVED.value,
            RideStatus.RIDER_ONBOARD.value,
            RideStatus.IN_PROGRESS.value,
            RideStatus.ARRIVED_DESTINATION.value,
        }:
            continue
        if not _ride_is_driver_mobile_eligible(ride):
            continue
        candidates.append((row, ride, _assignment_recency_token(row)))

    if len(candidates) <= 1:
        if closed:
            _commit_or_rollback(db)
        return closed

    def rank(item: tuple[HealthISFDispatchAssignment, HealthISFRide, str]) -> tuple[Any, str, str]:
        row, ride, recency = item
        preferred = 1 if prefer_ride_id and str(row.ride_id) == str(prefer_ride_id) else 0
        return (preferred, recency, _normalized_timestamp_token(ride.requested_at))

    candidates.sort(key=rank, reverse=True)
    keeper = candidates[0][0]
    for row, ride, _ in candidates[1:]:
        if str(row.id) == str(keeper.id):
            continue
        _release_orphaned_dispatch_assignment(db, row, ride, reason=reason)
        closed += 1
    if closed:
        _commit_or_rollback(db)
    return closed


def reconcile_expired_bound_assignments_for_driver(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    actor_user_id: Optional[str] = None,
    limit: int = 8,
) -> list[HealthISFDispatchAssignment]:
    """Reconcile all expired-bound rides for one driver (idempotent, bounded)."""
    repaired: list[HealthISFDispatchAssignment] = []
    ride_ids: set[str] = set()
    rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id == driver_id,
        )
        .order_by(desc(HealthISFRide.requested_at), desc(HealthISFRide.updated_at))
        .limit(max(1, min(int(limit or 8), 20)))
        .all()
    )
    for ride in rows:
        ride_ids.add(str(ride.id))
    assignment_rows = (
        db.query(HealthISFDispatchAssignment)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchAssignment.ride_id)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFRide.organization_id == organization_id,
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(max(1, min(int(limit or 8), 20)))
        .all()
    )
    for assignment in assignment_rows:
        ride_id = str(assignment.ride_id or "")
        if ride_id and ride_id not in ride_ids:
            ride = get_ride_by_id(db, ride_id)
            if ride:
                rows.append(ride)
                ride_ids.add(ride_id)
    for ride in rows:
        if _ride_is_terminal(ride):
            continue
        if len(repaired) >= 1:
            break
        op = evaluate_driver_ride_operational_state(db, ride=ride, driver_id=driver_id)
        if op.reason != "expired_bound_needs_reconcile":
            continue
        fixed = reconcile_expired_bound_driver_assignment(db, ride, actor_user_id=actor_user_id)
        if fixed:
            repaired.append(fixed)
    if repaired:
        _commit_or_rollback(db)
        for item in repaired:
            db.refresh(item)
    return repaired


def _close_terminal_open_assignments_for_driver(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> int:
    """Close open assignment rows tied to completed/cancelled/ineligible rides for one driver."""
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(200)
        .all()
    )
    closed = 0
    for row in rows:
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if not ride:
            _close_dispatch_assignment_record(
                db,
                row,
                target_state=DispatchAssignmentState.EXPIRED.value,
                reason="missing_ride_driver_mobile_sweep",
            )
            closed += 1
            continue
        if _ride_is_driver_mobile_eligible(ride):
            continue
        lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if lifecycle in {RideStatus.COMPLETED.value} or ride.completed_at:
            target_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
        else:
            target_state = DispatchAssignmentState.EXPIRED.value
        _close_dispatch_assignment_record(
            db,
            row,
            target_state=target_state,
            reason="terminal_ride_driver_mobile_sweep",
        )
        closed += 1
    if closed:
        _commit_or_rollback(db)
    return closed


def _prepare_driver_mobile_workspace_read(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    actor_user_id: Optional[str] = None,
) -> None:
    """Sweep stale rows, close terminal assignments, then reconcile valid expired-bound offers."""
    _sweep_stale_assignment_rows_for_organization(db, organization_id=organization_id)
    _reconcile_conflicting_driver_preaccept_assignments(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    _close_terminal_open_assignments_for_driver(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    reconcile_expired_bound_assignments_for_driver(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
        actor_user_id=actor_user_id,
    )


def _active_assignment_for_ride(db: Session, ride_id: str) -> Optional[HealthISFDispatchAssignment]:
    return (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .first()
    )


def _coerce_assigned_ride_queue_assignment_state(
    ride: HealthISFRide,
    assignment_state: str,
) -> str:
    """When ride.driver_id is set, stale assignment rows must not hide an actionable offer."""
    if not ride.driver_id:
        return assignment_state
    normalized = str(assignment_state or "").lower()
    if normalized in {
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        DispatchAssignmentState.EXPIRED.value,
        "expired",
        "pending_assignment",
    }:
        return (
            DispatchAssignmentState.ACCEPTED.value
            if ride.accepted_at
            else DispatchAssignmentState.OFFERED.value
        )
    return assignment_state


def _actionable_queue_assignment_state_for_bound_driver(
    db: Session,
    ride: HealthISFRide,
) -> Optional[str]:
    """Resolve queue-visible state from the ride's bound driver assignment rows."""
    candidate_driver_ids: list[str] = []
    if ride.driver_id:
        candidate_driver_ids.append(str(ride.driver_id))
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.ACCEPTED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                ]
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    for row in rows:
        driver_id = str(row.driver_id or "")
        if driver_id and driver_id not in candidate_driver_ids:
            candidate_driver_ids.append(driver_id)
    for driver_id in candidate_driver_ids:
        assignment = _latest_driver_assignment_for_ride(
            db,
            ride_id=str(ride.id),
            driver_id=driver_id,
        )
        if not assignment:
            continue
        state = str(assignment.assignment_state or "")
        if state in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
            return state
        if state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
            return (
                DispatchAssignmentState.ACCEPTED.value
                if ride.accepted_at
                else DispatchAssignmentState.OFFERED.value
            )
    return None


def _read_dispatch_queue_assignment_state(
    db: Session,
    ride: HealthISFRide,
) -> str:
    """Read-only dispatcher-visible queue state (no reconciliation side effects)."""
    inferred = _infer_active_assignment_state(ride)
    if inferred:
        return inferred

    bound_state = _actionable_queue_assignment_state_for_bound_driver(db, ride)
    if bound_state:
        return bound_state

    hint_row = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.ACCEPTED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                ]
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    if hint_row:
        inferred_from_assignment = _infer_active_assignment_state(
            ride,
            driver_id=str(getattr(hint_row, "driver_id", "") or ""),
        )
        if inferred_from_assignment:
            return inferred_from_assignment

    active = _authoritative_assignment_for_ride(db, ride)
    if active:
        active_state = str(active.assignment_state or "")
        if active_state in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
            return active_state
        if active_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
            bound_driver_id = str(ride.driver_id or active.driver_id or "")
            if bound_driver_id and str(active.driver_id or "") == bound_driver_id:
                return (
                    DispatchAssignmentState.ACCEPTED.value
                    if ride.accepted_at
                    else DispatchAssignmentState.OFFERED.value
                )

    if ride.driver_id:
        lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if lifecycle in {RideStatus.DRIVER_EN_ROUTE.value, RideStatus.ARRIVED.value}:
            return DispatchAssignmentState.EN_ROUTE_PICKUP.value
        if lifecycle in {RideStatus.RIDER_ONBOARD.value, RideStatus.IN_PROGRESS.value, RideStatus.ARRIVED_DESTINATION.value}:
            return DispatchAssignmentState.PICKUP_COMPLETE.value
        if lifecycle in {RideStatus.ACCEPTED.value, RideStatus.ASSIGNED.value}:
            return DispatchAssignmentState.ACCEPTED.value if ride.accepted_at else DispatchAssignmentState.OFFERED.value
        if lifecycle in {RideStatus.QUEUED.value, RideStatus.REQUESTED.value}:
            latest = _latest_driver_assignment_for_ride(
                db,
                ride_id=str(ride.id),
                driver_id=str(ride.driver_id),
            )
            latest_state = str(getattr(latest, "assignment_state", "") or "")
            if latest_state in {
                DispatchAssignmentState.EXPIRED.value,
                "expired",
                DispatchAssignmentState.REASSIGNMENT_PENDING.value,
            }:
                return _coerce_assigned_ride_queue_assignment_state(ride, "pending_assignment")
            return DispatchAssignmentState.OFFERED.value
        return _coerce_assigned_ride_queue_assignment_state(
            ride,
            DispatchAssignmentState.ACCEPTED.value if ride.accepted_at else DispatchAssignmentState.OFFERED.value,
        )

    latest = _latest_assignment_for_ride(db, ride.id)
    if latest:
        latest_state = str(latest.assignment_state or "")
        if latest_state == DispatchAssignmentState.AWAITING_APPROVAL.value:
            return latest_state
        if latest_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
            bound_driver_id = str(ride.driver_id or getattr(latest, "driver_id", "") or "")
            if bound_driver_id and str(getattr(latest, "driver_id", "") or "") == bound_driver_id:
                return _coerce_assigned_ride_queue_assignment_state(
                    ride,
                    DispatchAssignmentState.ACCEPTED.value if ride.accepted_at else DispatchAssignmentState.OFFERED.value,
                )
            if not ride.driver_id:
                return latest_state
        if latest_state in {DispatchAssignmentState.REJECTED.value, "expired"}:
            return "pending_assignment"

    bound_state = _actionable_queue_assignment_state_for_bound_driver(db, ride)
    if bound_state:
        return bound_state

    return "pending_assignment"


def _resolve_dispatch_queue_assignment_state(
    db: Session,
    ride: HealthISFRide,
) -> str:
    """Return the dispatcher-visible queue state for a ride."""
    return _read_dispatch_queue_assignment_state(db, ride)


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
    value = LEGACY_DRIVER_AVAILABILITY_ALIASES.get(value, value)
    if value not in VALID_DRIVER_AVAILABILITY_STATES:
        raise ValueError(
            "Invalid availability_state. Expected one of: "
            + ", ".join(sorted(VALID_DRIVER_AVAILABILITY_STATES))
        )
    return value


def _sanitize_driver_availability_state(driver: HealthISFDriver) -> None:
    """Map legacy/non-schema availability tokens before login or API validation."""
    raw = str(driver.availability_state or "offline").strip().lower()
    mapped = LEGACY_DRIVER_AVAILABILITY_ALIASES.get(raw, raw)
    if mapped not in VALID_DRIVER_AVAILABILITY_STATES:
        mapped = "available" if bool(driver.is_online) else "offline"
    if mapped != raw:
        driver.availability_state = mapped
        driver.updated_at = now()


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


def _assignment_counts_as_active_workload(
    db: Session,
    row: HealthISFDispatchAssignment,
    ride: Optional[HealthISFRide],
    *,
    driver_id: str,
) -> bool:
    """Return True only when an assignment should block new dispatch for the driver."""
    if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
        return False
    if str(ride.driver_id or "") != str(driver_id):
        return False
    assignment_state = str(row.assignment_state or "")
    if assignment_state not in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
        return False
    if _is_orphaned_dispatch_assignment(row, ride):
        return False
    from app.modules.health_isf.scheduling import is_protected_scheduled_reservation

    if is_protected_scheduled_reservation(ride, row):
        return False
    from app.modules.health_isf.advance_scheduling import is_scheduled_assignment_state

    if is_scheduled_assignment_state(assignment_state):
        return False
    return True


def _is_orphaned_dispatch_assignment(
    row: HealthISFDispatchAssignment,
    ride: Optional[HealthISFRide],
) -> bool:
    """Detect assignments that are open in DB but not actually active."""
    if not ride:
        return True
    if _ride_is_terminal(ride):
        return True
    if is_operational_excluded_ride(ride):
        return True

    assignment_state = str(row.assignment_state or "")
    driver_id = str(row.driver_id or "")
    ride_driver_id = str(ride.driver_id or "")
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    now_ts = _as_utc_datetime(now())

    if driver_id and ride_driver_id and driver_id != ride_driver_id:
        return True

    if assignment_state == DispatchAssignmentState.OFFERED.value:
        if ride.accepted_at and not row.accepted_at:
            return True
        if lifecycle in {RideStatus.ASSIGNED.value, RideStatus.ACCEPTED.value} and not row.accepted_at and not ride.accepted_at:
            # Dispatcher-assigned offers waiting for driver accept are valid when bound.
            if str(ride.driver_id or "") == str(driver_id or ""):
                return False
            return True
        if row.offer_expires_at and _as_utc_datetime(row.offer_expires_at) <= now_ts and not ride.accepted_at:
            return True
        if not row.offer_expires_at and row.queued_at:
            offer_age_seconds = (now_ts - _as_utc_datetime(row.queued_at)).total_seconds()
            if offer_age_seconds > 86400 and not ride.accepted_at:
                return True
        if lifecycle in {RideStatus.QUEUED.value, RideStatus.PENDING.value, RideStatus.REQUESTED.value} and ride_driver_id != driver_id:
            return True

    if assignment_state in ACTIVE_DISPATCH_ASSIGNMENT_STATES and not ride_driver_id and not ride.accepted_at:
        if lifecycle in {RideStatus.QUEUED.value, RideStatus.PENDING.value, RideStatus.REQUESTED.value}:
            return True

    return False


def _close_excluded_driver_binding(
    db: Session,
    row: HealthISFDispatchAssignment,
    ride: HealthISFRide,
    *,
    reason: str,
) -> None:
    """Cancel excluded/test rides and release the bound driver without touching billing proofs."""
    now_ts = now()
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    target_state = (
        DispatchAssignmentState.DROPOFF_COMPLETE.value
        if lifecycle == RideStatus.COMPLETED.value or ride.completed_at
        else DispatchAssignmentState.EXPIRED.value
    )
    _close_dispatch_assignment_record(
        db,
        row,
        target_state=target_state,
        reason=reason,
    )
    if not _ride_is_terminal(ride):
        ride.lifecycle_state = RideStatus.CANCELLED.value
        ride.status = RideStatus.CANCELLED.value
        ride.completed_at = ride.completed_at or now_ts
        ride.driver_id = None
        ride.updated_at = now_ts
        db.add(ride)
    driver = get_driver_by_id(db, str(row.driver_id or "")) if row.driver_id else None
    if driver:
        _release_driver_after_trip_completion(db, driver, increment_trip_count=False)


def _sync_offered_assignment_with_accepted_ride(
    db: Session,
    row: HealthISFDispatchAssignment,
    ride: HealthISFRide,
) -> None:
    """Repair OFFERED assignment rows after the ride was already accepted."""
    accepted_at = ride.accepted_at or now()
    row.assignment_state = DispatchAssignmentState.ACCEPTED.value
    row.accepted_at = row.accepted_at or accepted_at
    row.assigned_at = row.assigned_at or accepted_at
    row.updated_at = now()
    db.add(row)


def _release_orphaned_dispatch_assignment(
    db: Session,
    row: HealthISFDispatchAssignment,
    ride: Optional[HealthISFRide],
    *,
    reason: str,
) -> None:
    """Close orphaned assignments without deleting rides, billing, or completed trips."""
    now_ts = now()
    if not ride:
        _close_dispatch_assignment_record(
            db,
            row,
            target_state=DispatchAssignmentState.EXPIRED.value,
            reason=reason,
        )
        return

    if is_operational_excluded_ride(ride):
        _close_excluded_driver_binding(db, row, ride, reason=reason)
        return

    from app.modules.health_isf.scheduling import is_protected_scheduled_reservation

    if is_protected_scheduled_reservation(ride, row):
        return

    if (
        str(row.assignment_state or "") == DispatchAssignmentState.OFFERED.value
        and ride.accepted_at
        and not row.accepted_at
    ):
        _sync_offered_assignment_with_accepted_ride(db, row, ride)
        return

    if _ride_is_terminal(ride):
        _close_dispatch_assignment_record(
            db,
            row,
            target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            reason=reason,
        )
        return

    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    _close_dispatch_assignment_record(
        db,
        row,
        target_state=DispatchAssignmentState.EXPIRED.value,
        reason=reason,
    )
    if str(ride.driver_id or "") == str(row.driver_id or ""):
        ride.driver_id = None
        if lifecycle in {RideStatus.ASSIGNED.value, RideStatus.ACCEPTED.value} and not ride.accepted_at:
            ride.lifecycle_state = RideStatus.QUEUED.value
            ride.status = RideStatus.PENDING.value
        ride.updated_at = now_ts
        db.add(ride)


def reconcile_organization_driver_workloads(
    db: Session,
    *,
    organization_id: str,
) -> dict[str, Any]:
    """Detect stale assignments, release orphans, recalculate workloads, rebuild eligibility."""
    counts = dict(_sweep_stale_assignment_rows_for_organization(db, organization_id=organization_id))
    eligible = [
        driver
        for driver in get_drivers_for_organization(db, organization_id=organization_id, limit=500)
        if _driver_is_dispatch_candidate(db, driver)
    ]
    counts["dispatch_eligible_drivers"] = len(eligible)
    counts["available_drivers"] = len(
        [
            driver
            for driver in eligible
            if _coerce_driver_status(driver.status) == DriverStatus.AVAILABLE
            and str(driver.availability_state or "").lower() == "available"
            and bool(driver.is_online)
        ]
    )
    return counts


def _driver_active_workload_count(db: Session, driver_id: str) -> int:
    """Count only open dispatch assignments on active, non-demo rides."""
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .all()
    )
    count = 0
    for row in rows:
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if _assignment_counts_as_active_workload(db, row, ride, driver_id=str(driver_id)):
            count += 1
    return count


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


def _authoritative_assignment_for_ride(
    db: Session,
    ride: HealthISFRide,
    *,
    driver_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    """Prefer the active/open assignment for the ride's assigned driver."""
    target_driver = str(driver_id or ride.driver_id or "")
    active = _active_assignment_for_ride(db, ride.id)
    if active and (not target_driver or str(active.driver_id or "") == target_driver):
        return active
    if target_driver:
        latest_for_driver = _latest_driver_assignment_for_ride(
            db,
            ride_id=str(ride.id),
            driver_id=target_driver,
        )
        if latest_for_driver:
            state = str(latest_for_driver.assignment_state or "")
            if state in DRIVER_APP_ASSIGNMENT_STATES:
                return latest_for_driver
    return _latest_assignment_for_ride(db, ride.id)


def _close_dispatch_assignment_record(
    db: Session,
    assignment: HealthISFDispatchAssignment,
    *,
    target_state: str,
    reason: str,
) -> None:
    now_ts = now()
    assignment.assignment_state = target_state
    assignment.closed_reason = str(reason or "closed")[:512]
    assignment.updated_at = now_ts
    if target_state == DispatchAssignmentState.DROPOFF_COMPLETE.value:
        assignment.dropoff_complete_at = assignment.dropoff_complete_at or now_ts
    elif target_state in {DispatchAssignmentState.EXPIRED.value, "expired"}:
        assignment.expired_at = assignment.expired_at or now_ts


def _lifecycle_progress_rank(lifecycle: str) -> int:
    order = {
        RideStatus.REQUESTED.value: 0,
        RideStatus.QUEUED.value: 1,
        RideStatus.PENDING.value: 1,
        RideStatus.ASSIGNED.value: 2,
        RideStatus.ACCEPTED.value: 3,
        RideStatus.DRIVER_EN_ROUTE.value: 4,
        RideStatus.ARRIVED.value: 5,
        RideStatus.RIDER_ONBOARD.value: 6,
        RideStatus.IN_PROGRESS.value: 7,
        RideStatus.IN_TRANSIT.value: 7,
        RideStatus.ARRIVED_DESTINATION.value: 8,
    }
    return int(order.get(str(lifecycle or "").lower(), 0))


def _rank_driver_assignment_candidate(
    assignment: HealthISFDispatchAssignment,
    ride: HealthISFRide,
) -> tuple[int, str]:
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    assignment_state = str(assignment.assignment_state or "")
    post_accept = {
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.IN_TRANSIT.value,
        RideStatus.ARRIVED_DESTINATION.value,
    }
    tier = 0
    if lifecycle in post_accept:
        tier = 4
    elif assignment_state in ACTIVE_DISPATCH_ASSIGNMENT_STATES and assignment_state != DispatchAssignmentState.OFFERED.value:
        tier = 3
    elif assignment_state == DispatchAssignmentState.OFFERED.value:
        tier = 2
    elif assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value and ride.accepted_at:
        tier = 3
    elif assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
        tier = 1
    return (tier, _normalized_timestamp_token(ride.requested_at))


def _close_active_assignments_for_ride(
    db: Session,
    *,
    ride_id: str,
    target_state: str,
    reason: str,
    keep_assignment_id: Optional[str] = None,
) -> int:
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    closed = 0
    for row in rows:
        if keep_assignment_id and str(row.id) == str(keep_assignment_id):
            continue
        _close_dispatch_assignment_record(db, row, target_state=target_state, reason=reason)
        closed += 1
    return closed


def _sweep_stale_assignment_rows_for_organization(
    db: Session,
    *,
    organization_id: str,
) -> dict[str, int]:
    """Lightweight idempotent cleanup before dispatch/driver reads."""
    counts = {
        "closed_terminal_assignments": 0,
        "closed_duplicate_assignments": 0,
        "cleared_stale_offered_assigned": 0,
        "cleared_expired_driver_links": 0,
        "released_orphaned_assignments": 0,
        "released_excluded_bindings": 0,
        "synced_offered_accepted": 0,
        "released_drivers": 0,
    }
    now_ts = now()
    active_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(1000)
        .all()
    )

    for row in active_rows:
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if ride and is_operational_excluded_ride(ride) and str(row.driver_id or ""):
            _close_excluded_driver_binding(
                db,
                row,
                ride,
                reason="excluded_test_ride_assignment_sweep",
            )
            counts["released_excluded_bindings"] += 1
            continue
        if (
            ride
            and str(row.assignment_state or "") == DispatchAssignmentState.OFFERED.value
            and ride.accepted_at
            and not row.accepted_at
        ):
            _sync_offered_assignment_with_accepted_ride(db, row, ride)
            counts["synced_offered_accepted"] += 1
            continue
        if _is_orphaned_dispatch_assignment(row, ride):
            _release_orphaned_dispatch_assignment(
                db,
                row,
                ride,
                reason="orphaned_assignment_workload_reconcile",
            )
            counts["released_orphaned_assignments"] += 1

    active_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(1000)
        .all()
    )
    seen_active_ride: dict[str, str] = {}
    for row in active_rows:
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if ride and _ride_is_terminal(ride):
            _close_dispatch_assignment_record(
                db,
                row,
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="terminal_ride_assignment_sweep",
            )
            counts["closed_terminal_assignments"] += 1
            continue
        ride_id = str(row.ride_id or "")
        if not ride_id:
            continue
        keeper_id = seen_active_ride.get(ride_id)
        if keeper_id and keeper_id != str(row.id):
            _close_dispatch_assignment_record(
                db,
                row,
                target_state=DispatchAssignmentState.EXPIRED.value,
                reason="duplicate_active_assignment_sweep",
            )
            counts["closed_duplicate_assignments"] += 1
        else:
            seen_active_ride[ride_id] = str(row.id)
        if str(row.assignment_state) == DispatchAssignmentState.OFFERED.value and ride:
            lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            if lifecycle in {RideStatus.ASSIGNED.value, RideStatus.ACCEPTED.value} and not row.accepted_at and not ride.accepted_at:
                if str(ride.driver_id or "") == str(row.driver_id or ""):
                    continue
                _close_dispatch_assignment_record(
                    db,
                    row,
                    target_state=DispatchAssignmentState.EXPIRED.value,
                    reason="stale_offered_assigned_sweep",
                )
                if str(ride.driver_id or "") == str(row.driver_id or ""):
                    ride.driver_id = None
                ride.lifecycle_state = RideStatus.QUEUED.value
                ride.status = RideStatus.PENDING.value
                ride.updated_at = now_ts
                db.add(ride)
                counts["cleared_stale_offered_assigned"] += 1
                continue

    expired_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(500)
        .all()
    )
    for row in expired_rows:
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if not ride:
            _close_dispatch_assignment_record(
                db,
                row,
                target_state=DispatchAssignmentState.EXPIRED.value,
                reason="missing_ride_reassignment_pending_sweep",
            )
            counts["closed_terminal_assignments"] += 1
            continue
        if _ride_is_terminal(ride):
            lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            target_state = (
                DispatchAssignmentState.DROPOFF_COMPLETE.value
                if lifecycle == RideStatus.COMPLETED.value or ride.completed_at
                else DispatchAssignmentState.EXPIRED.value
            )
            _close_dispatch_assignment_record(
                db,
                row,
                target_state=target_state,
                reason="terminal_reassignment_pending_sweep",
            )
            counts["closed_terminal_assignments"] += 1
            continue
        if ride.accepted_at:
            continue
        if str(ride.driver_id or "") != str(row.driver_id or ""):
            continue
        closed_reason = str(getattr(row, "closed_reason", "") or "").lower()
        if any(
            marker in closed_reason
            for marker in (
                "superseded",
                "duplicate",
                "terminal_reassignment",
                "orphaned",
            )
        ):
            ride.driver_id = None
            ride.updated_at = now_ts
            counts["cleared_expired_driver_links"] += 1

    drivers = get_drivers_for_organization(db, organization_id=organization_id, limit=500)
    for driver in drivers:
        if _driver_active_workload_count(db, driver.id) > 0:
            continue
        busy_statuses = {
            DriverStatus.EN_ROUTE_PICKUP,
            DriverStatus.IN_TRANSIT,
            DriverStatus.ASSIGNED,
            DriverStatus.UNAVAILABLE,
        }
        if (
            _coerce_driver_status(driver.status) in busy_statuses
            or str(driver.availability_state or "").lower() == "on_trip"
        ):
            _release_driver_after_trip_completion(db, driver, increment_trip_count=False)
            counts["released_drivers"] += 1

    if any(counts.values()):
        _commit_or_rollback(db)
    return counts


def audit_organization_assignment_state(
    db: Session,
    *,
    organization_id: str,
) -> dict[str, Any]:
    """Report stale rides/assignments without mutating production records."""
    stale_rides: list[dict[str, Any]] = []
    stale_assignments: list[dict[str, Any]] = []
    blocked_drivers: list[dict[str, Any]] = []
    now_ts = _as_utc_datetime(now())

    active_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(1000)
        .all()
    )
    active_by_ride: dict[str, list[HealthISFDispatchAssignment]] = {}
    for row in active_rows:
        ride_id = str(row.ride_id or "")
        if not ride_id:
            continue
        active_by_ride.setdefault(ride_id, []).append(row)

    for ride_id, rows in active_by_ride.items():
        ride = get_ride_by_id(db, ride_id)
        if not ride:
            stale_assignments.append({"ride_id": ride_id, "issue": "missing_ride", "assignment_count": len(rows)})
            continue
        lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if _ride_is_terminal(ride):
            stale_rides.append(
                {
                    "ride_id": ride_id,
                    "issue": "terminal_ride_with_open_assignment",
                    "lifecycle_state": lifecycle,
                    "assignment_count": len(rows),
                }
            )
        elif len(rows) > 1:
            stale_assignments.append(
                {
                    "ride_id": ride_id,
                    "issue": "duplicate_active_assignments",
                    "assignment_count": len(rows),
                    "lifecycle_state": lifecycle,
                }
            )
        for row in rows:
            if row.offer_expires_at and _as_utc_datetime(row.offer_expires_at) <= now_ts:
                if str(row.assignment_state) in {
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                }:
                    stale_assignments.append(
                        {
                            "ride_id": ride_id,
                            "assignment_id": str(row.id),
                            "issue": "expired_offer_still_active",
                            "driver_id": str(row.driver_id or ""),
                            "assignment_state": str(row.assignment_state),
                        }
                    )
            if _is_orphaned_dispatch_assignment(row, ride):
                stale_assignments.append(
                    {
                        "ride_id": ride_id,
                        "assignment_id": str(row.id),
                        "issue": "orphaned_active_assignment",
                        "driver_id": str(row.driver_id or ""),
                        "assignment_state": str(row.assignment_state),
                        "lifecycle_state": lifecycle,
                    }
                )

    bound_rides = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id.is_not(None),
            HealthISFRide.lifecycle_state.in_(
                [
                    RideStatus.QUEUED.value,
                    RideStatus.REQUESTED.value,
                    RideStatus.PENDING.value,
                    RideStatus.ASSIGNED.value,
                ]
            ),
        )
        .order_by(desc(HealthISFRide.requested_at))
        .limit(500)
        .all()
    )
    for ride in bound_rides:
        if _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        driver_id = str(ride.driver_id or "")
        op = evaluate_driver_ride_operational_state(db, ride=ride, driver_id=driver_id)
        if op.reason == "expired_bound_needs_reconcile" and op.assignment:
            stale_assignments.append(
                {
                    "ride_id": str(ride.id),
                    "assignment_id": str(op.assignment.id),
                    "issue": "expired_bound_assignment",
                    "driver_id": driver_id,
                    "assignment_state": str(op.assignment.assignment_state or ""),
                    "lifecycle_state": RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
                }
            )

    drivers = get_drivers_for_organization(db, organization_id=organization_id, limit=500)
    for driver in drivers:
        workload = _driver_active_workload_count(db, driver.id)
        if workload > 1:
            blocked_drivers.append(
                {
                    "driver_id": str(driver.id),
                    "driver_name": str(driver.name or ""),
                    "issue": "multiple_active_rides",
                    "active_ride_count": workload,
                }
            )
        elif workload == 0 and _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
            blocked_drivers.append(
                {
                    "driver_id": str(driver.id),
                    "driver_name": str(driver.name or ""),
                    "issue": "driver_status_not_available_without_workload",
                    "status": str(driver.status),
                    "availability_state": str(driver.availability_state or ""),
                }
            )

    return {
        "organization_id": organization_id,
        "generated_at": now_ts,
        "stale_ride_count": len(stale_rides),
        "stale_assignment_count": len(stale_assignments),
        "blocked_driver_count": len(blocked_drivers),
        "stale_rides": stale_rides,
        "stale_assignments": stale_assignments,
        "blocked_drivers": blocked_drivers,
        "dispatch_queue_count": len(get_dispatch_queue(db, organization_id=organization_id, limit=500)),
        "active_assignment_count": len(get_dispatch_active_assignments(db, organization_id=organization_id, limit=500)),
    }


def repair_organization_assignment_state(
    db: Session,
    *,
    organization_id: str,
    dry_run: bool = True,
    ride_ids: Optional[list[str]] = None,
    actor_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Report and optionally repair inconsistent ride/assignment rows."""
    audit_before = audit_organization_assignment_state(db, organization_id=organization_id)
    repairs: list[dict[str, Any]] = []
    if dry_run:
        return {
            **audit_before,
            "dry_run": True,
            "repairs_applied": 0,
            "repairs": repairs,
        }

    target_ride_ids = {str(item) for item in (ride_ids or []) if str(item).strip()}
    now_ts = now()

    if target_ride_ids:
        for ride_id in sorted(target_ride_ids):
            ride = get_ride_by_id(db, ride_id)
            if not ride:
                continue
            restored = reconcile_expired_bound_driver_assignment(db, ride, actor_user_id=actor_user_id)
            if restored:
                repairs.append(
                    {
                        "ride_id": ride_id,
                        "action": "expired_bound_restored_to_offered",
                        "assignment_id": str(restored.id),
                    }
                )
        if repairs:
            _commit_or_rollback(db)

    for item in audit_before.get("stale_rides") or []:
        ride_id = str(item.get("ride_id") or "")
        if target_ride_ids and ride_id not in target_ride_ids:
            continue
        ride = get_ride_by_id(db, ride_id)
        if not ride:
            continue
        closed = _close_active_assignments_for_ride(
            db,
            ride_id=ride_id,
            target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            reason="assignment_state_reconcile_terminal_ride",
        )
        pending_rows = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.assignment_state
                == DispatchAssignmentState.REASSIGNMENT_PENDING.value,
            )
            .all()
        )
        for row in pending_rows:
            _close_dispatch_assignment_record(
                db,
                row,
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="assignment_state_reconcile_terminal_ride",
            )
            closed += 1
        if closed:
            repairs.append({"ride_id": ride_id, "action": "closed_terminal_assignments", "count": closed})

    for item in audit_before.get("stale_assignments") or []:
        ride_id = str(item.get("ride_id") or "")
        if target_ride_ids and ride_id not in target_ride_ids:
            continue
        issue = str(item.get("issue") or "")
        if issue == "duplicate_active_assignments":
            ride = get_ride_by_id(db, ride_id)
            if not ride:
                continue
            keeper = _authoritative_assignment_for_ride(db, ride)
            closed = _close_active_assignments_for_ride(
                db,
                ride_id=ride_id,
                target_state=DispatchAssignmentState.EXPIRED.value,
                reason="assignment_state_reconcile_duplicate",
                keep_assignment_id=str(keeper.id) if keeper else None,
            )
            if closed:
                repairs.append({"ride_id": ride_id, "action": "closed_duplicate_assignments", "count": closed})
        elif issue == "expired_offer_still_active":
            assignment_id = str(item.get("assignment_id") or "")
            assignment = db.query(HealthISFDispatchAssignment).filter(HealthISFDispatchAssignment.id == assignment_id).first()
            ride = get_ride_by_id(db, ride_id)
            if assignment and ride and not ride.accepted_at:
                restored = reconcile_expired_bound_driver_assignment(db, ride, actor_user_id=actor_user_id)
                if restored:
                    repairs.append(
                        {
                            "ride_id": ride_id,
                            "action": "expired_bound_restored_to_offered",
                            "assignment_id": assignment_id,
                        }
                    )
                    continue
                _close_dispatch_assignment_record(
                    db,
                    assignment,
                    target_state=DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                    reason="assignment_state_reconcile_expired_offer",
                )
                if str(ride.driver_id or "") == str(assignment.driver_id or ""):
                    ride.driver_id = None
                    ride.updated_at = now_ts
                repairs.append({"ride_id": ride_id, "action": "expired_offer_released", "assignment_id": assignment_id})
        elif issue == "expired_bound_assignment":
            ride = get_ride_by_id(db, ride_id)
            if ride:
                restored = reconcile_expired_bound_driver_assignment(db, ride, actor_user_id=actor_user_id)
                if restored:
                    repairs.append(
                        {
                            "ride_id": ride_id,
                            "action": "expired_bound_restored_to_offered",
                            "assignment_id": str(restored.id),
                        }
                    )
        elif issue == "orphaned_active_assignment":
            assignment_id = str(item.get("assignment_id") or "")
            assignment = db.query(HealthISFDispatchAssignment).filter(HealthISFDispatchAssignment.id == assignment_id).first()
            ride = get_ride_by_id(db, ride_id)
            if assignment:
                _release_orphaned_dispatch_assignment(
                    db,
                    assignment,
                    ride,
                    reason="assignment_state_reconcile_orphaned",
                )
                repairs.append({"ride_id": ride_id, "action": "orphaned_assignment_released", "assignment_id": assignment_id})

    if not target_ride_ids:
        for item in audit_before.get("blocked_drivers") or []:
            driver_id = str(item.get("driver_id") or "")
            driver = get_driver_by_id(db, driver_id)
            if not driver:
                continue
            if str(item.get("issue") or "") == "multiple_active_rides":
                rows = (
                    db.query(HealthISFDispatchAssignment)
                    .filter(
                        HealthISFDispatchAssignment.driver_id == driver_id,
                        HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
                    )
                    .all()
                )
                candidates: list[tuple[tuple[int, str], HealthISFDispatchAssignment, HealthISFRide]] = []
                for row in rows:
                    ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
                    if not ride or _ride_is_terminal(ride):
                        _close_dispatch_assignment_record(
                            db,
                            row,
                            target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                            reason="assignment_state_reconcile_driver_terminal",
                        )
                        repairs.append({"driver_id": driver_id, "ride_id": str(row.ride_id or ""), "action": "closed_terminal_assignment"})
                        continue
                    candidates.append((_rank_driver_assignment_candidate(row, ride), row, ride))
                if len(candidates) > 1:
                    candidates.sort(key=lambda item: item[0], reverse=True)
                    keeper = candidates[0][1]
                    for _, row, ride in candidates[1:]:
                        _close_dispatch_assignment_record(
                            db,
                            row,
                            target_state=DispatchAssignmentState.EXPIRED.value,
                            reason="assignment_state_reconcile_driver_duplicate",
                        )
                        if str(ride.driver_id or "") == str(driver_id):
                            ride.driver_id = None
                            ride.updated_at = now_ts
                        repairs.append(
                            {
                                "driver_id": driver_id,
                                "ride_id": str(row.ride_id or ""),
                                "action": "released_non_authoritative_ride",
                                "kept_assignment_id": str(keeper.id),
                            }
                        )
            elif _driver_active_workload_count(db, driver_id) == 0:
                _release_driver_after_trip_completion(db, driver, increment_trip_count=False)
                repairs.append({"driver_id": driver_id, "action": "released_idle_driver"})

    if repairs:
        _commit_or_rollback(db)

    audit_after = audit_organization_assignment_state(db, organization_id=organization_id)
    return {
        **audit_after,
        "dry_run": False,
        "repairs_applied": len(repairs),
        "repairs": repairs,
        "actor_user_id": actor_user_id,
    }


def reconcile_ride_assignment_coherence(
    db: Session,
    ride: HealthISFRide,
    *,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    """Repair split-brain between ride.driver_id, assignment rows, driver availability, and customer request."""
    if not ride:
        return None
    depth = _reconcile_coherence_depth.get()
    if depth >= MAX_RECONCILE_COHERENCE_DEPTH:
        return _authoritative_assignment_for_ride(db, ride)
    token = _reconcile_coherence_depth.set(depth + 1)
    try:
        return _reconcile_ride_assignment_coherence_impl(db, ride, actor_user_id=actor_user_id)
    finally:
        _reconcile_coherence_depth.reset(token)


def _reconcile_ride_assignment_coherence_impl(
    db: Session,
    ride: HealthISFRide,
    *,
    actor_user_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    """Inner reconcile implementation guarded against recursion."""
    if not ride:
        return None
    if _ride_is_terminal(ride):
        closed = _close_active_assignments_for_ride(
            db,
            ride_id=str(ride.id),
            target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            reason="terminal_ride_reconcile",
        )
        driver = get_driver_by_id(db, str(ride.driver_id or "")) if ride.driver_id else None
        if driver and _driver_active_workload_count(db, driver.id) == 0:
            _release_driver_after_trip_completion(db, driver, increment_trip_count=False)
        if closed or driver:
            sync_customer_request_from_ride(db, ride)
            _commit_or_rollback(db)
        return None

    bound_driver_id = str(ride.driver_id or "")
    if bound_driver_id:
        bound_state = evaluate_driver_ride_operational_state(db, ride=ride, driver_id=bound_driver_id)
        if bound_state.reason == "expired_bound_needs_reconcile":
            restored = reconcile_expired_bound_driver_assignment(db, ride, actor_user_id=actor_user_id)
            if restored:
                sync_customer_request_from_ride(db, ride)
                _commit_or_rollback(db)
                db.refresh(ride)
                db.refresh(restored)
                return restored

    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    driver_id = str(ride.driver_id or "")
    if not driver_id:
        open_assignment = _authoritative_assignment_for_ride(db, ride)
        if open_assignment and open_assignment.driver_id:
            driver_id = str(open_assignment.driver_id)
            ride.driver_id = driver_id
            ride.updated_at = now()
        else:
            sync_customer_request_from_ride(db, ride)
            _commit_or_rollback(db)
            return open_assignment

    assignment = _latest_driver_assignment_for_ride(db, ride_id=str(ride.id), driver_id=driver_id)
    if not assignment:
        sync_customer_request_from_ride(db, ride)
        _commit_or_rollback(db)
        return None

    assignment_state = str(assignment.assignment_state or "")
    post_accept_lifecycle = {
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.ARRIVED_DESTINATION.value,
    }

    if assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
        if lifecycle in post_accept_lifecycle or ride.accepted_at:
            assignment.assignment_state = DispatchAssignmentState.ACCEPTED.value
            assignment.accepted_at = assignment.accepted_at or ride.accepted_at or now()
        else:
            assignment.assignment_state = DispatchAssignmentState.OFFERED.value
            assignment.offered_at = assignment.offered_at or now()
        assignment.reassignment_pending_at = None
        assignment.closed_reason = None
        assignment.updated_at = now()
    elif assignment_state == DispatchAssignmentState.OFFERED.value and lifecycle in post_accept_lifecycle:
        assignment.assignment_state = DispatchAssignmentState.ACCEPTED.value
        assignment.accepted_at = assignment.accepted_at or ride.accepted_at or now()
        assignment.updated_at = now()
    elif assignment_state == DispatchAssignmentState.ACCEPTED.value and lifecycle == RideStatus.DRIVER_EN_ROUTE.value:
        assignment.assignment_state = DispatchAssignmentState.EN_ROUTE_PICKUP.value
        assignment.en_route_pickup_at = assignment.en_route_pickup_at or now()
        assignment.updated_at = now()
    elif lifecycle in {RideStatus.RIDER_ONBOARD.value, RideStatus.IN_PROGRESS.value, RideStatus.IN_TRANSIT.value}:
        assignment.assignment_state = DispatchAssignmentState.PICKUP_COMPLETE.value
        assignment.pickup_complete_at = assignment.pickup_complete_at or now()
        assignment.updated_at = now()
    elif lifecycle == RideStatus.ARRIVED_DESTINATION.value:
        assignment.assignment_state = DispatchAssignmentState.ARRIVED_DESTINATION.value
        assignment.updated_at = now()

    driver = get_driver_by_id(db, driver_id)
    if driver:
        current_assignment_state = str(assignment.assignment_state or "")
        if lifecycle in post_accept_lifecycle or current_assignment_state in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
            if (
                str(driver.auth_state or "inactive").lower() == "active"
                and bool(driver.is_online)
                and _coerce_driver_status(driver.status) != DriverStatus.OFFLINE
            ):
                driver.availability_state = "on_trip"
                if lifecycle == RideStatus.DRIVER_EN_ROUTE.value:
                    _advance_driver_status_for_active_ride(db, driver, DriverStatus.EN_ROUTE_PICKUP, ride=ride)
                elif lifecycle in {
                    RideStatus.ARRIVED.value,
                    RideStatus.RIDER_ONBOARD.value,
                    RideStatus.IN_PROGRESS.value,
                    RideStatus.ARRIVED_DESTINATION.value,
                }:
                    _advance_driver_status_for_active_ride(db, driver, DriverStatus.IN_TRANSIT, ride=ride)
                elif current_assignment_state != DispatchAssignmentState.OFFERED.value:
                    _advance_driver_status_for_active_ride(db, driver, DriverStatus.ASSIGNED, ride=ride)
                else:
                    _advance_driver_status_for_active_ride(db, driver, DriverStatus.ASSIGNED, ride=ride)
                    driver.availability_state = "available"
                driver.is_online = True
                driver.auth_state = "active"
                driver.last_seen_at = now()

    sync_customer_request_from_ride(db, ride)
    _commit_or_rollback(db)
    db.refresh(ride)
    db.refresh(assignment)
    return assignment


def _mark_dispatch_assignment_state(
    db: Session,
    *,
    ride_id: str,
    assignment_state: str,
    note: Optional[str] = None,
    driver_id: Optional[str] = None,
) -> Optional[HealthISFDispatchAssignment]:
    ride = get_ride_by_id(db, ride_id)
    row = None
    target_driver = str(driver_id or (ride.driver_id if ride else "") or "")
    if target_driver:
        row = _latest_driver_assignment_for_ride(db, ride_id=ride_id, driver_id=target_driver)
    if not row and ride:
        row = _authoritative_assignment_for_ride(db, ride)
    if not row:
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
    if not bool(driver.is_online):
        return False
    if str(driver.availability_state or "offline").lower() != "available":
        return False
    if _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
        return False
    if str(driver.auth_state or "inactive").lower() != "active":
        return False
    return True


def evaluate_dispatch_candidates(
    db: Session,
    *,
    organization_id: str,
    ride: HealthISFRide,
    exclude_driver_ids: Optional[set[str]] = None,
) -> list[dict[str, Any]]:
    """Score active drivers for AI dispatch recommendation and auto-assignment."""
    reconcile_organization_driver_workloads(db, organization_id=organization_id)
    expire_stale_dispatch_offers(db, organization_id=organization_id)
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
        from app.modules.health_isf.scheduling import driver_has_schedule_conflict

        if driver_has_schedule_conflict(db, str(driver.id), ride):
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
    sync_customer_request_from_ride(db, assigned_ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)
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
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if not ride or _ride_is_terminal(ride):
            continue
        if ride.accepted_at or RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) not in {
            RideStatus.QUEUED.value,
            RideStatus.PENDING.value,
            RideStatus.REQUESTED.value,
            RideStatus.ASSIGNED.value,
        }:
            continue
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
            elif driver and ride and str(ride.driver_id or "") == str(row.driver_id):
                reconcile_ride_assignment_coherence(db, ride)
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

    from app.modules.health_isf.scheduling import is_dispatch_eligible

    if not is_dispatch_eligible(ride):
        _commit_or_rollback(db)
        return {
            "ride": ride,
            "offer": None,
            "candidates": [],
            "candidate_snapshot": [],
            "candidate_order_valid": True,
            "selection_parity_ok": True,
            "reason": "ride_not_dispatch_eligible",
        }

    reconcile_organization_driver_workloads(db, organization_id=ride.organization_id)
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
        existing_driver = get_driver_by_id(db, existing_offer.driver_id) if existing_offer.driver_id else None
        if not existing_driver or not _driver_is_dispatch_candidate(db, existing_driver):
            offer_ride = get_ride_by_id(db, ride.id)
            _release_orphaned_dispatch_assignment(
                db,
                existing_offer,
                offer_ride,
                reason="auto_assign_ineligible_existing_offer",
            )
            _commit_or_rollback(db)
            db.refresh(ride)
        else:
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
    selected_driver_id = str(selected["driver"].id)
    _record_dispatch(
        db,
        ride_id=ride.id,
        action="auto_dispatch_selected_driver",
        acted_by_user_id=actor_user_id,
        driver_id=selected_driver_id,
        note=json.dumps(
            {
                "eligible_driver_count": len(candidates),
                "selected_score": selected.get("score"),
            }
        )[:2000],
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason="auto_assign_request",
        transition_timestamp=now(),
        assignment_transition_source="auto_assign_request",
    )
    current_driver_id = str(ride.driver_id or "")
    assigned_ride = assign_driver_to_ride(
        db,
        ride_id=ride.id,
        driver_id=selected_driver_id,
        actor_user_id=actor_user_id,
        allow_existing_assignment=bool(current_driver_id) and current_driver_id == selected_driver_id,
        allow_reassignment=bool(current_driver_id) and current_driver_id != selected_driver_id,
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
    sync_customer_request_from_ride(db, assigned_ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)

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


def _driver_dispatch_exclusion_reason(
    db: Session,
    driver: HealthISFDriver,
    *,
    ride: Optional[HealthISFRide] = None,
    exclude_driver_ids: Optional[set[str]] = None,
) -> Optional[str]:
    exclude_ids = {str(item) for item in (exclude_driver_ids or set()) if str(item).strip()}
    if str(driver.id) in exclude_ids:
        return "excluded_driver_id"
    if not bool(driver.is_active):
        return "inactive_driver"
    if _driver_active_workload_count(db, driver.id) > 0:
        return "active_workload"
    if _is_driver_busy(driver.status):
        return "busy_status"
    if not bool(driver.is_online):
        return "offline"
    if str(driver.availability_state or "offline").lower() != "available":
        return f"availability_{str(driver.availability_state or 'offline').lower()}"
    if _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
        return f"status_{_coerce_driver_status(driver.status).value}"
    if str(driver.auth_state or "inactive").lower() != "active":
        return f"auth_{str(driver.auth_state or 'inactive').lower()}"
    if ride is not None:
        from app.modules.health_isf.scheduling import driver_has_schedule_conflict

        if driver_has_schedule_conflict(db, str(driver.id), ride):
            return "schedule_conflict"
    return None


def _audit_auto_dispatch_driver_pool(
    db: Session,
    *,
    ride: HealthISFRide,
    request_id: Optional[str],
    actor_user_id: Optional[str],
) -> dict[str, Any]:
    rows = (
        db.query(HealthISFDriver)
        .filter(
            HealthISFDriver.organization_id == ride.organization_id,
            HealthISFDriver.is_active == True,
        )
        .order_by(HealthISFDriver.updated_at.desc(), HealthISFDriver.id.asc())
        .all()
    )
    eligible = 0
    exclusions: list[dict[str, str]] = []
    for driver in rows:
        reason = _driver_dispatch_exclusion_reason(db, driver, ride=ride)
        if reason:
            exclusions.append(
                {
                    "driver_id": str(driver.id),
                    "phone": str(driver.phone or ""),
                    "reason": reason,
                }
            )
        else:
            eligible += 1
    summary = {
        "eligible_driver_count": eligible,
        "active_driver_count": len(rows),
        "exclusions": exclusions[:25],
    }
    _record_dispatch(
        db,
        ride_id=ride.id,
        action="auto_dispatch_eligible_driver_count",
        acted_by_user_id=actor_user_id,
        note=json.dumps(summary)[:4000],
        request_id=request_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason="auto_dispatch_driver_pool_audit",
        transition_timestamp=now(),
        assignment_transition_source="run_intake_dispatch_automation",
    )
    return summary


def _record_auto_dispatch_audit(
    db: Session,
    *,
    ride_id: str,
    action: str,
    request_id: Optional[str] = None,
    actor_user_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    note: Optional[str] = None,
    assignment_id: Optional[str] = None,
    lifecycle_state: Optional[str] = None,
) -> None:
    _record_dispatch(
        db,
        ride_id=ride_id,
        action=action,
        acted_by_user_id=actor_user_id,
        driver_id=driver_id,
        note=note,
        request_id=request_id,
        assignment_id=assignment_id,
        lifecycle_state=lifecycle_state,
        transition_reason=action,
        transition_timestamp=now(),
        assignment_transition_source="auto_dispatch_pipeline",
    )


def _prepare_pending_customer_request_for_intake_auto_dispatch(
    db: Session,
    *,
    ride: HealthISFRide,
    request_obj: HealthISFCustomerRideRequest,
    organization_id: str,
    actor_user_id: Optional[str] = None,
) -> tuple[bool, str]:
    """Auto-approve immediate dispatch-eligible rider requests when intake automation is enabled."""
    from app.modules.health_isf.scheduling import is_dispatch_eligible, is_immediate_ride

    request_id = str(request_obj.id)
    _record_auto_dispatch_audit(
        db,
        ride_id=str(ride.id),
        action="auto_dispatch_requested",
        request_id=request_id,
        actor_user_id=actor_user_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        note="customer_request_intake_background",
    )

    if not _is_intake_auto_dispatch_enabled(db, organization_id):
        _record_auto_dispatch_audit(
            db,
            ride_id=str(ride.id),
            action="auto_dispatch_skipped",
            request_id=request_id,
            actor_user_id=actor_user_id,
            note="intake_auto_dispatch_disabled",
        )
        return False, "awaiting_dispatcher_approval"

    if not is_immediate_ride(ride):
        _record_auto_dispatch_audit(
            db,
            ride_id=str(ride.id),
            action="auto_dispatch_skipped",
            request_id=request_id,
            actor_user_id=actor_user_id,
            note="routed_to_advance_scheduling",
        )
        return False, "advance_scheduling"

    if not is_dispatch_eligible(ride):
        _record_auto_dispatch_audit(
            db,
            ride_id=str(ride.id),
            action="auto_dispatch_skipped",
            request_id=request_id,
            actor_user_id=actor_user_id,
            note="not_dispatch_eligible_yet",
        )
        return False, "awaiting_dispatcher_approval"

    _record_auto_dispatch_audit(
        db,
        ride_id=str(ride.id),
        action="auto_dispatch_started",
        request_id=request_id,
        actor_user_id=actor_user_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
    )
    _set_customer_request_status(request_obj, CustomerRequestStatus.DISPATCHABLE.value)
    request_obj.updated_at = now()
    _commit_or_rollback(db)
    db.refresh(request_obj)
    _record_auto_dispatch_audit(
        db,
        ride_id=str(ride.id),
        action="auto_dispatch_auto_approved",
        request_id=request_id,
        actor_user_id=actor_user_id,
        note="immediate_ride_dispatchable",
    )
    return True, "dispatchable"


def promote_pending_immediate_customer_requests(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: Optional[str] = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Sweep pending immediate customer requests and run intake auto-dispatch."""
    from app.modules.health_isf.scheduling import is_immediate_ride

    if not _is_intake_auto_dispatch_enabled(db, organization_id):
        return []

    pending_rows = (
        db.query(HealthISFCustomerRideRequest)
        .filter(
            HealthISFCustomerRideRequest.organization_id == organization_id,
            HealthISFCustomerRideRequest.dispatch_status == CustomerRequestStatus.PENDING.value,
        )
        .order_by(HealthISFCustomerRideRequest.created_at.asc())
        .limit(max(1, int(limit)))
        .all()
    )
    outcomes: list[dict[str, Any]] = []
    for request_obj in pending_rows:
        ride = get_ride_by_id(db, str(request_obj.ride_id))
        if not ride or not is_immediate_ride(ride):
            continue
        assignment_before = _latest_assignment_for_ride(db, ride.id)
        if assignment_before and str(assignment_before.assignment_state or "").lower() in {
            DispatchAssignmentState.OFFERED.value,
            DispatchAssignmentState.ACCEPTED.value,
            DispatchAssignmentState.ASSIGNED.value,
        }:
            continue
        result = run_intake_dispatch_automation(
            db,
            ride_id=str(ride.id),
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        finalize_customer_request_intake_dispatch(db, request_obj=request_obj, actor_user_id=actor_user_id)
        outcomes.append(
            {
                "request_id": str(request_obj.id),
                "ride_id": str(ride.id),
                "mode": result.get("mode"),
                "offer_id": getattr(result.get("offer"), "id", None),
            }
        )
    return outcomes


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

    request_obj = get_customer_request_by_ride_id(db, ride_id)
    request_id = str(request_obj.id) if request_obj else None
    if request_obj and str(request_obj.dispatch_status or "").lower() == CustomerRequestStatus.CANCELLED.value:
        return {
            "ride": ride,
            "mode": "awaiting_dispatcher_approval",
            "recommendation": None,
            "offer": None,
            "selected_driver": None,
            "candidates": [],
        }

    if request_obj and str(request_obj.dispatch_status or "").lower() == CustomerRequestStatus.PENDING.value:
        proceed, _mode = _prepare_pending_customer_request_for_intake_auto_dispatch(
            db,
            ride=ride,
            request_obj=request_obj,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        if not proceed:
            from app.modules.health_isf.scheduling import is_immediate_ride

            if _mode == "advance_scheduling" or not is_immediate_ride(ride):
                from app.modules.health_isf.advance_scheduling import (
                    run_advance_scheduling_for_customer_request,
                    run_advance_scheduling_for_ride,
                )

                if request_obj:
                    outcomes = run_advance_scheduling_for_customer_request(
                        db,
                        request_id=str(request_obj.id),
                        organization_id=organization_id,
                        actor_user_id=actor_user_id,
                    )
                else:
                    outcomes = [
                        run_advance_scheduling_for_ride(
                            db,
                            ride_id=str(ride.id),
                            organization_id=organization_id,
                            actor_user_id=actor_user_id,
                        )
                    ]
                offer = None
                selected_driver = None
                for outcome in outcomes:
                    if outcome.get("offer"):
                        offer = outcome["offer"]
                        selected_driver = outcome.get("selected_driver")
                _commit_or_rollback(db)
                db.refresh(ride)
                if request_obj:
                    db.refresh(request_obj)
                return {
                    "ride": ride,
                    "mode": "scheduled_reserved" if offer else "awaiting_dispatcher_approval",
                    "recommendation": None,
                    "offer": offer,
                    "selected_driver": selected_driver,
                    "candidates": [],
                }
            _commit_or_rollback(db)
            return {
                "ride": ride,
                "mode": "awaiting_dispatcher_approval",
                "recommendation": None,
                "offer": None,
                "selected_driver": None,
                "candidates": [],
            }
        db.refresh(request_obj)

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

    driver_pool_summary = _audit_auto_dispatch_driver_pool(
        db,
        ride=ride,
        request_id=request_id,
        actor_user_id=actor_user_id,
    )
    _commit_or_rollback(db)

    if _is_intake_auto_dispatch_enabled(db, organization_id):
        from app.modules.health_isf.scheduling import is_immediate_ride

        if not is_immediate_ride(ride):
            _commit_or_rollback(db)
            return {
                "ride": ride,
                "mode": "scheduled_reserved" if ride.driver_id else "awaiting_dispatcher_approval",
                "recommendation": None,
                "offer": _latest_assignment_for_ride(db, ride.id),
                "selected_driver": get_driver_by_id(db, ride.driver_id) if ride.driver_id else None,
                "candidates": [],
            }
        auto_result = auto_assign_request(
            db,
            ride_id=ride_id,
            actor_user_id=actor_user_id,
            offer_timeout_seconds=offer_timeout_seconds,
        )
        offer = auto_result.get("offer")
        selected_driver = auto_result.get("selected_driver")
        if offer:
            db.refresh(ride)
            _record_auto_dispatch_audit(
                db,
                ride_id=str(ride.id),
                action="auto_dispatch_offer_created",
                request_id=request_id,
                actor_user_id=actor_user_id,
                driver_id=str(getattr(offer, "driver_id", "") or getattr(selected_driver, "id", "") or "") or None,
                assignment_id=str(getattr(offer, "id", "") or "") or None,
                lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
                note=f"eligible_driver_count={driver_pool_summary.get('eligible_driver_count', 0)}",
            )
            _record_auto_dispatch_audit(
                db,
                ride_id=str(ride.id),
                action="auto_dispatch_completed",
                request_id=request_id,
                actor_user_id=actor_user_id,
                driver_id=str(getattr(offer, "driver_id", "") or "") or None,
                assignment_id=str(getattr(offer, "id", "") or "") or None,
                lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
            )
            _commit_or_rollback(db)
            db.refresh(ride)
            return {
                **auto_result,
                "mode": "auto_assigned",
                "recommendation": None,
            }

        no_driver_reason = str(auto_result.get("reason") or "dispatch_search_no_candidates")
        _record_auto_dispatch_audit(
            db,
            ride_id=str(ride.id),
            action="auto_dispatch_failed",
            request_id=request_id,
            actor_user_id=actor_user_id,
            note=no_driver_reason,
            lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        )
        _commit_or_rollback(db)

        recommendation_result = recommend_driver_for_ride(
            db,
            ride_id=ride_id,
            actor_user_id=actor_user_id,
        )
        if recommendation_result.get("recommendation"):
            try:
                approved_result = approve_dispatch_recommendation(
                    db,
                    ride_id=ride_id,
                    actor_user_id=actor_user_id,
                    offer_timeout_seconds=offer_timeout_seconds,
                )
                if approved_result.get("offer"):
                    db.refresh(ride)
                    _record_auto_dispatch_audit(
                        db,
                        ride_id=str(ride.id),
                        action="auto_dispatch_completed",
                        request_id=request_id,
                        actor_user_id=actor_user_id,
                        driver_id=str(getattr(approved_result.get("offer"), "driver_id", "") or "") or None,
                        assignment_id=str(getattr(approved_result.get("offer"), "id", "") or "") or None,
                        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
                        note="recommendation_auto_approved",
                    )
                    _commit_or_rollback(db)
                    return {
                        **approved_result,
                        "mode": "auto_assigned",
                        "recommendation": recommendation_result.get("recommendation"),
                        "candidates": recommendation_result.get("candidates") or [],
                    }
            except Exception as exc:
                logger.warning(
                    "Intake auto-approval of dispatch recommendation failed for ride_id=%s: %s",
                    ride_id,
                    exc,
                )
        recommendation_result["mode"] = "recommendation"
        recommendation_result["offer"] = None
        return recommendation_result

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
    limit: int = 200,
) -> list[dict[str, Any]]:
    reconcile_organization_driver_workloads(db, organization_id=organization_id)
    from app.modules.health_isf.scheduling import promote_dispatch_eligible_rides

    promote_dispatch_eligible_rides(db, organization_id=organization_id)
    promote_pending_immediate_customer_requests(db, organization_id=organization_id)
    active_legacy_statuses = [RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]
    active_lifecycle_states = [
        RideStatus.REQUESTED.value,
        RideStatus.QUEUED.value,
        RideStatus.PENDING.value,
        RideStatus.ASSIGNED.value,
        RideStatus.ESCALATED.value,
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.IN_TRANSIT.value,
        "pending_review",
        "scheduled",
        "pending_assignment",
    ]
    rides = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            (
                HealthISFRide.status.in_(active_legacy_statuses)
                | HealthISFRide.lifecycle_state.in_(active_lifecycle_states)
            ),
        )
        .order_by(HealthISFRide.requested_at.desc(), HealthISFRide.created_at.desc())
        .limit(max(1, min(int(limit or 200), 500)))
        .all()
    )

    rows: list[dict[str, Any]] = []
    for ride in rides:
        if _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if lifecycle in {
            RideStatus.COMPLETED.value,
            RideStatus.CANCELLED.value,
            RideStatus.FAILED.value,
        }:
            continue
        active_assignment = _active_assignment_for_ride(db, ride.id)
        assignment = (
            active_assignment
            or _authoritative_assignment_for_ride(db, ride)
            or _latest_assignment_for_ride(db, ride.id)
        )
        # Completed rides must never remain in active/AI dispatch queues, even if a
        # stale reassignment_pending assignment row still exists.
        if assignment and str(assignment.assignment_state or "").lower() == DispatchAssignmentState.DROPOFF_COMPLETE.value:
            continue
        assignment_state = _resolve_dispatch_queue_assignment_state(db, ride)
        if assignment:
            raw_state = str(assignment.assignment_state or "")
            if raw_state not in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
                inferred = _infer_active_assignment_state(
                    ride,
                    driver_id=str(assignment.driver_id or ride.driver_id or ""),
                )
                if inferred:
                    assignment_state = inferred
        post_accept_queue_states = {
            DispatchAssignmentState.ACCEPTED.value,
            DispatchAssignmentState.EN_ROUTE_PICKUP.value,
            DispatchAssignmentState.PICKUP_COMPLETE.value,
            DispatchAssignmentState.ARRIVED_DESTINATION.value,
            DispatchAssignmentState.DROPOFF_COMPLETE.value,
        }
        if assignment_state in post_accept_queue_states:
            continue
        if ride.accepted_at and lifecycle in {
            RideStatus.ACCEPTED.value,
            RideStatus.ASSIGNED.value,
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ARRIVED.value,
            RideStatus.RIDER_ONBOARD.value,
            RideStatus.IN_PROGRESS.value,
            RideStatus.IN_TRANSIT.value,
            RideStatus.ARRIVED_DESTINATION.value,
        }:
            continue
        recommended_driver_id = (
            str(assignment.driver_id)
            if assignment and assignment.driver_id
            else (str(ride.driver_id) if ride.driver_id else None)
        )
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
        from app.modules.health_isf.scheduling import format_scheduling_summary

        scheduling_summary = format_scheduling_summary(ride)
        appointment_window = scheduling_summary if scheduling_summary != "Immediate ride" else None
        rows.append(
            {
                "ride_id": str(ride.id),
                "organization_id": str(ride.organization_id),
                "passenger_name": str(ride.passenger_name or "Unknown passenger"),
                "pickup_address": ride.pickup_address,
                "dropoff_address": ride.dropoff_address,
                "requested_at": ride.requested_at or ride.created_at or now(),
                "ride_status": _normalize_status_token(ride.lifecycle_state or ride.status),
                "assignment_state": assignment_state,
                "trip_leg": getattr(ride, "trip_leg", None),
                "round_trip_group_id": getattr(ride, "round_trip_group_id", None),
                "pickup_time": getattr(ride, "pickup_time", None),
                "appointment_time": getattr(ride, "appointment_time", None),
                "dispatch_eligible_at": getattr(ride, "dispatch_eligible_at", None),
                "call_when_ready": bool(getattr(ride, "call_when_ready", False)),
                "scheduling_summary": scheduling_summary,
                "appointment_window": appointment_window,
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


def get_newest_unassigned_queue_ride(
    db: Session,
    *,
    organization_id: str,
) -> Optional[tuple[HealthISFRide, dict[str, Any]]]:
    """Return the newest dispatch-queue ride that still needs a driver offer."""
    queue = get_dispatch_queue(db, organization_id=organization_id, limit=100)
    assignable_states = {
        "pending_assignment",
        DispatchAssignmentState.AWAITING_APPROVAL.value,
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        DispatchAssignmentState.QUEUED.value,
    }
    candidates: list[tuple[HealthISFRide, dict[str, Any]]] = []
    for row in queue:
        ride_id = str(row.get("ride_id") or "")
        if not ride_id:
            continue
        assignment_state = str(row.get("assignment_state") or "")
        if assignment_state not in assignable_states:
            continue
        ride = get_ride_by_id(db, ride_id)
        if not ride or _ride_is_terminal(ride) or ride.driver_id:
            continue
        if is_operational_excluded_ride(ride):
            continue
        from app.modules.health_isf.scheduling import is_dispatch_eligible

        if not is_dispatch_eligible(ride):
            continue
        candidates.append((ride, row))
    if not candidates:
        return None
    candidates.sort(
        key=lambda item: (
            _coerce_utc(getattr(item[0], "dispatch_eligible_at", None))
            or _coerce_utc(getattr(item[0], "appointment_time", None))
            or _coerce_utc(getattr(item[0], "requested_at", None))
            or datetime.max.replace(tzinfo=timezone.utc),
            _coerce_utc(getattr(item[0], "requested_at", None)) or datetime.min.replace(tzinfo=timezone.utc),
        )
    )
    return candidates[0]


def maybe_assign_next_pending_ride_to_available_driver(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    actor_user_id: Optional[str] = None,
    offer_timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Offer the newest pending queue ride to a driver who just completed a trip."""
    if _driver_active_workload_count(db, driver_id) > 0:
        return {"assigned": False, "reason": "driver_has_active_ride"}

    driver = get_driver_by_id(db, driver_id)
    if not driver:
        return {"assigned": False, "reason": "driver_not_found"}

    driver_status = _coerce_driver_status(driver.status)
    if driver_status not in {DriverStatus.AVAILABLE, DriverStatus.UNAVAILABLE}:
        return {"assigned": False, "reason": f"driver_status_{driver_status.value}"}

    resolved = get_newest_unassigned_queue_ride(db, organization_id=organization_id)
    if not resolved:
        return {"assigned": False, "reason": "no_pending_rides"}

    ride, _queue_row = resolved
    try:
        assigned_ride = assign_driver_to_ride(
            db,
            ride_id=ride.id,
            driver_id=driver_id,
            actor_user_id=actor_user_id,
        )
    except ValueError as exc:
        _commit_or_rollback(db)
        return {"assigned": False, "reason": str(exc)}

    if not assigned_ride:
        return {"assigned": False, "reason": "assign_failed"}

    offer = _latest_assignment_for_ride(db, ride.id)
    if offer:
        now_ts = now()
        offer.timeout_seconds = max(10, int(offer_timeout_seconds))
        offer.offered_at = offer.offered_at or now_ts
        offer.offer_expires_at = now_ts + timedelta(seconds=offer.timeout_seconds)
        offer.updated_at = now_ts
        _commit_or_rollback(db)
        db.refresh(offer)

    sync_customer_request_from_ride(db, assigned_ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)
    db.refresh(assigned_ride)

    _record_dispatch(
        db,
        ride_id=assigned_ride.id,
        action="post_completion_auto_assign",
        acted_by_user_id=actor_user_id,
        driver_id=driver_id,
        note="Auto-assigned pending ride after prior trip completion",
        assignment_id=offer.id if offer else None,
    )
    _commit_or_rollback(db)

    return {
        "assigned": True,
        "ride_id": str(assigned_ride.id),
        "driver_id": driver_id,
        "offer_id": str(offer.id) if offer else None,
    }


def assign_newest_queue_ride(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: Optional[str] = None,
    offer_timeout_seconds: int = 90,
) -> dict[str, Any]:
    """Assign the newest real queue ride to the best eligible driver."""
    resolved = get_newest_unassigned_queue_ride(db, organization_id=organization_id)
    if not resolved:
        raise ValueError("No assignable rides in dispatch queue")

    ride, queue_row = resolved
    assignment_state = str(queue_row.get("assignment_state") or "")
    if assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value:
        return approve_dispatch_recommendation(
            db,
            ride_id=ride.id,
            actor_user_id=actor_user_id,
            offer_timeout_seconds=offer_timeout_seconds,
        )

    result = auto_assign_request(
        db,
        ride_id=ride.id,
        actor_user_id=actor_user_id,
        offer_timeout_seconds=offer_timeout_seconds,
    )
    if result.get("offer"):
        result["ride"] = ride
        return result

    recommendation_result = recommend_driver_for_ride(
        db,
        ride_id=ride.id,
        actor_user_id=actor_user_id,
    )
    if recommendation_result.get("recommendation"):
        approved_result = approve_dispatch_recommendation(
            db,
            ride_id=ride.id,
            actor_user_id=actor_user_id,
            offer_timeout_seconds=offer_timeout_seconds,
        )
        if approved_result.get("offer"):
            approved_result["candidates"] = recommendation_result.get("candidates") or []
            return approved_result

    result["mode"] = "recommendation"
    result["recommendation"] = recommendation_result.get("recommendation")
    result["candidates"] = recommendation_result.get("candidates") or []
    return result


def _build_dispatch_active_assignment_payload(
    db: Session,
    *,
    assignment: HealthISFDispatchAssignment,
    ride: HealthISFRide,
    lock_map: dict[str, RideAssignmentLock],
) -> dict[str, Any]:
    driver = get_driver_by_id(db, assignment.driver_id) if assignment.driver_id else None
    lock = lock_map.get(str(ride.id))
    return {
        "offer_id": str(assignment.id),
        "ride_id": str(ride.id),
        "driver_id": assignment.driver_id,
        "driver_name": driver.name if driver else None,
        "assignment_state": assignment.assignment_state,
        "attempt_index": int(assignment.attempt_index or 0),
        "offered_at": assignment.offered_at,
        "offer_expires_at": assignment.offer_expires_at,
        "assigned_at": assignment.assigned_at,
        "accepted_at": assignment.accepted_at,
        "en_route_pickup_at": assignment.en_route_pickup_at,
        "pickup_complete_at": assignment.pickup_complete_at,
        "dropoff_complete_at": assignment.dropoff_complete_at,
        "reassignment_pending_at": assignment.reassignment_pending_at,
        "reassignment_started_at": assignment.reassignment_started_at,
        "reassignment_completed_at": assignment.reassignment_completed_at,
        "reassignment_attempt_count": int(assignment.reassignment_attempt_count or 0),
        "reassignment_reason": assignment.reassignment_reason,
        "reassignment_chain_id": assignment.reassignment_chain_id,
        "score": float(assignment.score) if assignment.score is not None else None,
        "passenger_name": str(ride.passenger_name or "Unknown passenger"),
        "ride_status": str(ride.lifecycle_state or ride.status),
        "ownership_locked": bool(lock),
        "ownership_locked_by_user_id": lock.locked_by_user_id if lock else None,
        "ownership_locked_at": lock.locked_at if lock else None,
        "ownership_lock_expires_at": lock.expires_at if lock else None,
    }


def _infer_active_assignment_state_for_ride(ride: HealthISFRide) -> Optional[str]:
    return _infer_active_assignment_state(ride)


def _infer_active_assignment_state(
    ride: HealthISFRide,
    *,
    driver_id: Optional[str] = None,
) -> Optional[str]:
    if not ride:
        return None
    bound_driver_id = str(driver_id or ride.driver_id or "")
    if not bound_driver_id:
        return None
    lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle in {
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
    }:
        return DispatchAssignmentState.EN_ROUTE_PICKUP.value
    if lifecycle in {
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.ARRIVED_DESTINATION.value,
        RideStatus.IN_TRANSIT.value,
    }:
        return DispatchAssignmentState.PICKUP_COMPLETE.value
    if lifecycle in {RideStatus.ACCEPTED.value, RideStatus.ASSIGNED.value}:
        return (
            DispatchAssignmentState.ACCEPTED.value
            if ride.accepted_at
            else DispatchAssignmentState.OFFERED.value
        )
    if lifecycle in {RideStatus.QUEUED.value, RideStatus.REQUESTED.value, RideStatus.PENDING.value}:
        return DispatchAssignmentState.OFFERED.value
    return DispatchAssignmentState.ASSIGNED.value


def get_dispatch_active_assignments(
    db: Session,
    *,
    organization_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _sweep_stale_assignment_rows_for_organization(db, organization_id=organization_id)
    safe_limit = max(1, min(int(limit or 100), 500))
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at))
        .limit(safe_limit * 2)
        .all()
    )
    active: list[dict[str, Any]] = []
    seen_ride_ids: set[str] = set()
    lock_map: dict[str, RideAssignmentLock] = {}

    def _ensure_lock_map(ride_ids: list[str]) -> None:
        missing = [ride_id for ride_id in ride_ids if ride_id and ride_id not in lock_map]
        if not missing:
            return
        now_ts = _as_utc_datetime(now())
        lock_rows = (
            db.query(RideAssignmentLock)
            .filter(
                RideAssignmentLock.ride_id.in_(missing),
                RideAssignmentLock.expires_at > now_ts,
            )
            .all()
        )
        for lock in lock_rows:
            lock_map[str(lock.ride_id)] = lock

    def _append_active_assignment(
        assignment: HealthISFDispatchAssignment,
        ride: HealthISFRide,
    ) -> None:
        ride_id = str(ride.id)
        if ride_id in seen_ride_ids:
            return
        assignment_state = str(assignment.assignment_state or "")
        if assignment_state in CLOSED_DISPATCH_ASSIGNMENT_STATES:
            return
        display_state = assignment_state
        if assignment_state not in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
            inferred = _infer_active_assignment_state_for_ride(ride)
            if not inferred:
                return
            display_state = inferred
        _ensure_lock_map([ride_id])
        payload = _build_dispatch_active_assignment_payload(db, assignment=assignment, ride=ride, lock_map=lock_map)
        payload["assignment_state"] = display_state
        active.append(payload)
        seen_ride_ids.add(ride_id)

    def _append_active_ride_without_assignment(ride: HealthISFRide) -> None:
        ride_id = str(ride.id)
        if ride_id in seen_ride_ids:
            return
        inferred_state = _infer_active_assignment_state_for_ride(ride)
        if not inferred_state:
            return
        driver = get_driver_by_id(db, str(ride.driver_id)) if ride.driver_id else None
        _ensure_lock_map([ride_id])
        lock = lock_map.get(ride_id)
        active.append(
            {
                "offer_id": str(ride_id),
                "ride_id": str(ride.id),
                "driver_id": ride.driver_id,
                "driver_name": driver.name if driver else None,
                "assignment_state": inferred_state,
                "attempt_index": 0,
                "offered_at": ride.assigned_at,
                "offer_expires_at": None,
                "assigned_at": ride.assigned_at,
                "accepted_at": ride.accepted_at,
                "en_route_pickup_at": None,
                "pickup_complete_at": None,
                "dropoff_complete_at": None,
                "reassignment_pending_at": None,
                "reassignment_started_at": None,
                "reassignment_completed_at": None,
                "reassignment_attempt_count": 0,
                "reassignment_reason": None,
                "reassignment_chain_id": None,
                "score": None,
                "passenger_name": str(ride.passenger_name or "Unknown passenger"),
                "ride_status": str(ride.lifecycle_state or ride.status),
                "ownership_locked": bool(lock),
                "ownership_locked_by_user_id": lock.locked_by_user_id if lock else None,
                "ownership_locked_at": lock.locked_at if lock else None,
                "ownership_lock_expires_at": lock.expires_at if lock else None,
            }
        )
        seen_ride_ids.add(ride_id)

    for row in rows:
        ride = get_ride_by_id(db, row.ride_id)
        if not ride:
            continue
        if _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        reconcile_ride_assignment_coherence(db, ride)
        db.refresh(ride)
        assignment = _authoritative_assignment_for_ride(
            db,
            ride,
            driver_id=str(row.driver_id or ride.driver_id or ""),
        )
        if not assignment:
            continue
        db.refresh(assignment)
        _append_active_assignment(assignment, ride)

    supplemental_rides = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id.isnot(None),
        )
        .order_by(desc(HealthISFRide.updated_at), desc(HealthISFRide.requested_at))
        .limit(safe_limit * 2)
        .all()
    )
    for ride in supplemental_rides:
        ride_id = str(ride.id)
        if ride_id in seen_ride_ids:
            continue
        if _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        reconcile_ride_assignment_coherence(db, ride)
        db.refresh(ride)
        assignment = _authoritative_assignment_for_ride(db, ride)
        if assignment:
            db.refresh(assignment)
            _append_active_assignment(assignment, ride)
            continue
        latest = _latest_driver_assignment_for_ride(
            db,
            ride_id=str(ride.id),
            driver_id=str(ride.driver_id or ""),
        )
        if latest:
            db.refresh(latest)
            _append_active_assignment(latest, ride)
            continue
        _append_active_ride_without_assignment(ride)

    active.sort(
        key=lambda item: _normalized_timestamp_token(item.get("accepted_at") or item.get("assigned_at") or item.get("offered_at")),
        reverse=True,
    )
    return active[:safe_limit]


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


def resolve_active_driver_session_from_token(
    db: Session,
    *,
    session_token: str,
) -> Optional[HealthISFDriverSession]:
    """Resolve an active driver session from token alone (ignores URL driver_id)."""
    token_hash = _hash_driver_session_token(session_token)
    now_ts = _as_utc_datetime(now())
    session = (
        db.query(HealthISFDriverSession)
        .filter(HealthISFDriverSession.session_token_hash == token_hash)
        .order_by(desc(HealthISFDriverSession.issued_at))
        .first()
    )
    if not session:
        return None
    session_expires_at = _as_utc_datetime(session.expires_at)
    if session.session_state != "active" or session.revoked_at is not None or session_expires_at < now_ts:
        return None
    return session


def _reactivate_driver_offers_on_login(db: Session, driver: HealthISFDriver) -> None:
    """Re-open expired/reassignment-pending offers so assigned rides appear in driver mobile after sign-in."""
    org_id = resolve_driver_organization_id(db, driver, persist_missing=True)
    _prepare_driver_mobile_workspace_read(
        db,
        organization_id=org_id,
        driver_id=str(driver.id),
    )
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver.id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.REASSIGNMENT_PENDING.value,
        )
        .all()
    )
    if not rows:
        return
    now_ts = now()
    for assignment in rows:
        ride = get_ride_by_id(db, assignment.ride_id) if assignment.ride_id else None
        if not ride or not _ride_is_driver_mobile_eligible(ride):
            if ride and _ride_is_terminal(ride):
                lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
                target_state = (
                    DispatchAssignmentState.DROPOFF_COMPLETE.value
                    if lifecycle == RideStatus.COMPLETED.value or ride.completed_at
                    else DispatchAssignmentState.EXPIRED.value
                )
                _close_dispatch_assignment_record(
                    db,
                    assignment,
                    target_state=target_state,
                    reason="terminal_reassignment_pending_login_sweep",
                )
            continue
        assignment.assignment_state = DispatchAssignmentState.OFFERED.value
        assignment.reassignment_pending_at = None
        assignment.offered_at = assignment.offered_at or now_ts
        assignment.offer_expires_at = now_ts + timedelta(seconds=90)
        assignment.updated_at = now_ts
        if str(ride.driver_id or "") != str(driver.id):
            ride.driver_id = driver.id
            ride.updated_at = now_ts
        reconcile_ride_assignment_coherence(db, ride)


def _normalize_driver_auth_state_on_login(db: Session, driver: HealthISFDriver) -> None:
    """Clear stale trip/assignment posture left by failed login or interrupted sessions."""
    _sanitize_driver_availability_state(driver)
    workload = _driver_active_workload_count(db, driver.id)
    active_rides = _current_active_rides_for_driver(db, driver.id)
    if workload > 0 or active_rides:
        return
    availability = str(driver.availability_state or "offline").lower()
    if availability in {"on_trip", "offer_pending", "assigned"}:
        driver.availability_state = "available"
    busy_statuses = {
        DriverStatus.ASSIGNED,
        DriverStatus.BUSY,
        DriverStatus.EN_ROUTE_PICKUP,
        DriverStatus.WAITING_AT_PICKUP,
        DriverStatus.IN_TRANSIT,
    }
    current = _coerce_driver_status(driver.status)
    if current in busy_statuses and current != DriverStatus.AVAILABLE:
        _set_driver_status(db, driver, DriverStatus.AVAILABLE, force=True)


def find_driver_by_login_phone(
    db: Session,
    *,
    phone: str,
    driver_id: str | None = None,
) -> Optional[HealthISFDriver]:
    normalized_id = str(driver_id or "").strip()

    def _match_rows(rows: list[Any]) -> Optional[HealthISFDriver]:
        matches: list[str] = []
        for row in rows:
            row_id = str(getattr(row, "id", None) or row[0])
            row_phone = str(getattr(row, "phone", None) or row[1])
            if not _phones_match_for_driver_login(row_phone, phone):
                continue
            if normalized_id and row_id != normalized_id:
                continue
            matches.append(row_id)
        if not matches:
            return None
        if len(matches) > 1 and not normalized_id:
            raise ValueError("Multiple drivers match this phone; select a driver profile")
        return get_driver_by_id(db, matches[0])

    try:
        candidates = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.is_active.is_(True))
            .all()
        )
        matches: list[HealthISFDriver] = []
        for driver in candidates:
            if not _phones_match_for_driver_login(driver.phone, phone):
                continue
            if normalized_id and str(driver.id) != normalized_id:
                continue
            matches.append(driver)
        if not matches:
            return None
        if len(matches) > 1 and not normalized_id:
            raise ValueError("Multiple drivers match this phone; select a driver profile")
        return matches[0]
    except SQLAlchemyError:
        from app.modules.health_isf.models import ensure_driver_mobile_login_schema

        db.rollback()
        ensure_driver_mobile_login_schema()
        rows = db.execute(
            text("SELECT id, phone FROM health_isf_drivers WHERE is_active = TRUE")
        ).all()
        driver = _match_rows(rows)
        if driver:
            return driver
        raise


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

    resolve_driver_organization_id(db, driver, persist_missing=True)
    db.refresh(driver)

    _sanitize_driver_availability_state(driver)
    _reactivate_driver_offers_on_login(db, driver)
    _normalize_driver_auth_state_on_login(db, driver)

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
    _sanitize_driver_availability_state(driver)
    if str(driver.availability_state or "offline").lower() == "offline":
        driver.availability_state = "available"
    workload = _driver_active_workload_count(db, driver.id)
    current_status = _coerce_driver_status(driver.status)
    if workload > 0:
        if current_status in {DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE, DriverStatus.AVAILABLE}:
            if current_status in {DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE}:
                _set_driver_status(db, driver, DriverStatus.AVAILABLE)
                current_status = DriverStatus.AVAILABLE
            if current_status == DriverStatus.AVAILABLE:
                _set_driver_status(db, driver, DriverStatus.ASSIGNED)
    elif (
        current_status != DriverStatus.AVAILABLE
        and _driver_status_from_availability(driver.availability_state) == DriverStatus.AVAILABLE
    ):
        _set_driver_status(db, driver, DriverStatus.AVAILABLE, force=True)
    else:
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


def get_round_trip_group(
    db: Session,
    *,
    organization_id: str,
    round_trip_group_id: str,
) -> list[HealthISFRide]:
    return (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.round_trip_group_id == round_trip_group_id,
        )
        .order_by(HealthISFRide.created_at.asc())
        .all()
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
    return request_obj


def finalize_customer_request_intake_dispatch(
    db: Session,
    *,
    request_obj: HealthISFCustomerRideRequest,
    actor_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Align customer-request dispatch status with intake automation output."""
    ride = get_ride_by_id(db, request_obj.ride_id)
    if not ride:
        return {"mode": "unknown", "request": request_obj, "ride": None, "assignment": None}

    assignment = _latest_assignment_for_ride(db, ride.id)
    assignment_state = str(getattr(assignment, "assignment_state", "") or "").lower()

    if assignment_state == DispatchAssignmentState.OFFERED.value:
        _set_customer_request_status(request_obj, CustomerRequestStatus.ASSIGNED.value)
    elif assignment_state in SCHEDULED_DISPATCH_ASSIGNMENT_STATES:
        _set_customer_request_status(request_obj, CustomerRequestStatus.ASSIGNED.value)
    elif assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value:
        _set_customer_request_status(request_obj, CustomerRequestStatus.APPROVED.value)
    elif assignment_state in {
        DispatchAssignmentState.ACCEPTED.value,
        DispatchAssignmentState.ASSIGNED.value,
        DispatchAssignmentState.EN_ROUTE_PICKUP.value,
        DispatchAssignmentState.PICKUP_COMPLETE.value,
        DispatchAssignmentState.DROPOFF_COMPLETE.value,
    }:
        _set_customer_request_status(request_obj, CustomerRequestStatus.ASSIGNED.value)
    else:
        sync_customer_request_from_ride(db, ride)

    request_obj.updated_at = now()
    _commit_or_rollback(db)
    db.refresh(request_obj)
    db.refresh(ride)

    mode = "pending"
    if assignment_state == DispatchAssignmentState.OFFERED.value:
        mode = "offered"
    elif assignment_state in SCHEDULED_DISPATCH_ASSIGNMENT_STATES:
        mode = "scheduled_reserved"
    elif assignment_state == DispatchAssignmentState.AWAITING_APPROVAL.value:
        mode = "awaiting_approval"
    elif ride.driver_id:
        mode = "assigned"

    if mode != "pending":
        _record_dispatch(
            db,
            ride_id=ride.id,
            action="customer_request_intake_synced",
            acted_by_user_id=actor_user_id,
            note=f"Customer request synced after intake dispatch ({mode})",
            request_id=request_obj.id,
            assignment_id=getattr(assignment, "id", None),
            lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
            transition_reason="intake_dispatch_sync",
            transition_timestamp=now(),
            assignment_transition_source="finalize_customer_request_intake_dispatch",
        )
        _commit_or_rollback(db)

    return {
        "mode": mode,
        "request": request_obj,
        "ride": ride,
        "assignment": assignment,
    }


def _ensure_completion_billing_records(
    db: Session,
    ride: HealthISFRide,
    *,
    actor_user_id: Optional[str] = None,
    materialize_payout_row: bool = False,
) -> dict[str, Any] | None:
    from app.modules.health_isf.financial_engine import TripFinancialEngine

    return TripFinancialEngine.process_trip_completion(
        db,
        ride,
        actor_user_id=actor_user_id,
        materialize_payout_row=materialize_payout_row,
    )


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
            reconcile_ride_assignment_coherence(db, ride)
            db.refresh(ride)
            return ride
    for ride in list_rides_for_passenger_phone(
        db,
        organization_id=organization_id,
        rider_phone=rider_phone,
        limit=40,
    ):
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(ride.status))
        if lifecycle_state not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}:
            reconcile_ride_assignment_coherence(db, ride)
            db.refresh(ride)
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


def _expire_superseded_preaccept_offers_for_driver(
    db: Session,
    *,
    driver_id: str,
    keep_ride_id: Optional[str] = None,
    min_requested_at_token: Optional[str] = None,
    reason: str = "superseded_by_newer_queue_ride",
) -> int:
    """Close older pre-accept offers so the newest queue ride can be offered."""
    closed = 0
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                ]
            ),
        )
        .all()
    )
    for row in rows:
        ride_id = str(row.ride_id or "")
        if keep_ride_id and ride_id == str(keep_ride_id):
            continue
        ride = get_ride_by_id(db, ride_id) if ride_id else None
        if ride and not _ride_is_terminal(ride) and not is_operational_excluded_ride(ride):
            from app.modules.health_isf.scheduling import is_protected_scheduled_reservation

            if is_protected_scheduled_reservation(ride, row):
                continue
        if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            _release_orphaned_dispatch_assignment(db, row, ride, reason=reason)
            closed += 1
            continue
        if ride.accepted_at:
            continue
        if keep_ride_id:
            _release_orphaned_dispatch_assignment(db, row, ride, reason=reason)
            closed += 1
            continue
        if min_requested_at_token and _normalized_timestamp_token(ride.requested_at) >= min_requested_at_token:
            continue
        _release_orphaned_dispatch_assignment(db, row, ride, reason=reason)
        closed += 1
    if closed:
        _commit_or_rollback(db)
    return closed


def _offer_newest_queue_ride_to_driver(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    offer_timeout_seconds: int = 90,
) -> Optional[HealthISFDispatchAssignment]:
    """Offer the newest operational dispatch-queue ride to an eligible driver."""
    now_ts = now()
    open_offers = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    for offer in open_offers:
        if offer.offer_expires_at and _as_utc_datetime(offer.offer_expires_at) < _as_utc_datetime(now_ts):
            continue
        offer_ride = get_ride_by_id(db, offer.ride_id) if offer.ride_id else None
        if not offer_ride or not _ride_is_driver_mobile_eligible(offer_ride):
            continue
        if is_operational_excluded_ride(offer_ride) or _is_orphaned_dispatch_assignment(offer, offer_ride):
            continue
        return offer

    resolved = get_newest_unassigned_queue_ride(db, organization_id=organization_id)
    if not resolved:
        return None
    queue_ride, _queue_row = resolved
    driver = get_driver_by_id(db, driver_id)
    if not driver or str(driver.organization_id) != str(organization_id):
        return None

    queue_token = _normalized_timestamp_token(queue_ride.requested_at)
    current_best_token = "1970-01-01T00:00:00+00:00"
    current_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                ]
            ),
        )
        .all()
    )
    for row in current_rows:
        ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if not ride or _ride_is_terminal(ride) or is_operational_excluded_ride(ride):
            continue
        token = _normalized_timestamp_token(ride.requested_at)
        if token > current_best_token:
            current_best_token = token

    latest_for_queue = _latest_assignment_for_ride(db, queue_ride.id)
    if latest_for_queue and str(latest_for_queue.driver_id or "") == str(driver_id):
        state = str(latest_for_queue.assignment_state or "")
        if state == DispatchAssignmentState.OFFERED.value:
            if not latest_for_queue.offer_expires_at or _as_utc_datetime(latest_for_queue.offer_expires_at) >= _as_utc_datetime(now()):
                return latest_for_queue
        preferred = _latest_driver_assignment_for_ride(
            db,
            ride_id=str(queue_ride.id),
            driver_id=str(driver_id),
        )
        if preferred and str(preferred.assignment_state or "") == DispatchAssignmentState.OFFERED.value:
            if not preferred.offer_expires_at or _as_utc_datetime(preferred.offer_expires_at) >= _as_utc_datetime(now()):
                return preferred

    if queue_token <= current_best_token and current_best_token != "1970-01-01T00:00:00+00:00":
        return None

    if not _driver_is_dispatch_candidate(db, driver):
        return None

    _expire_superseded_preaccept_offers_for_driver(
        db,
        driver_id=driver_id,
        keep_ride_id=str(queue_ride.id),
        min_requested_at_token=queue_token,
    )

    try:
        assign_driver_to_ride(
            db,
            ride_id=queue_ride.id,
            driver_id=driver_id,
            allow_reassignment=True,
        )
    except ValueError:
        _commit_or_rollback(db)
        return None

    offer = _latest_assignment_for_ride(db, queue_ride.id)
    if not offer or str(offer.driver_id or "") != str(driver_id):
        return None
    now_ts = now()
    offer.assignment_state = DispatchAssignmentState.OFFERED.value
    offer.timeout_seconds = max(10, int(offer_timeout_seconds))
    offer.offered_at = offer.offered_at or now_ts
    offer.offer_expires_at = now_ts + timedelta(seconds=offer.timeout_seconds)
    offer.updated_at = now_ts
    _commit_or_rollback(db)
    db.refresh(offer)
    return offer


def get_driver_active_offer(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> Optional[HealthISFDispatchAssignment]:
    _prepare_driver_mobile_workspace_read(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    expire_stale_dispatch_offers(db, organization_id=organization_id)
    _offer_newest_queue_ride_to_driver(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    offers = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                ]
            ),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    valid_offers: list[tuple[HealthISFDispatchAssignment, HealthISFRide]] = []
    for offer in offers:
        if offer.offer_expires_at and _as_utc_datetime(offer.offer_expires_at) < _as_utc_datetime(now()):
            continue
        ride = get_ride_by_id(db, offer.ride_id) if offer.ride_id else None
        if not ride or not _ride_is_driver_mobile_eligible(ride):
            continue
        if str(offer.assignment_state or "") == DispatchAssignmentState.REASSIGNMENT_PENDING.value:
            if str(ride.driver_id or "") != str(driver_id):
                continue
            reconcile_ride_assignment_coherence(db, ride)
            db.refresh(offer)
            if str(offer.assignment_state or "") not in {
                DispatchAssignmentState.OFFERED.value,
                DispatchAssignmentState.ASSIGNED.value,
            }:
                continue
        valid_offers.append((offer, ride))
    if not valid_offers:
        return None
    valid_offers.sort(
        key=lambda item: (
            _assignment_recency_token(item[0]),
            _normalized_timestamp_token(item[1].requested_at),
        ),
        reverse=True,
    )
    return valid_offers[0][0]


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
    driver, organization_id = _ensure_driver_organization_scope(
        db,
        driver_id=driver_id,
        organization_id=organization_id,
        persist_missing=True,
    )
    _prepare_driver_mobile_workspace_read(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    expire_stale_dispatch_offers(db, organization_id=organization_id)
    _offer_newest_queue_ride_to_driver(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )

    terminal_ride_states = {
        RideStatus.COMPLETED.value,
        RideStatus.CANCELLED.value,
        RideStatus.FAILED.value,
    }
    assignment_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    assignment: Optional[HealthISFDispatchAssignment] = None
    ride: Optional[HealthISFRide] = None
    ranked_candidates: list[tuple[tuple[int, str], HealthISFDispatchAssignment, HealthISFRide]] = []
    for row in assignment_rows:
        candidate_ride = get_ride_by_id(db, row.ride_id) if row.ride_id else None
        if not candidate_ride or not _ride_is_driver_mobile_eligible(candidate_ride):
            continue
        if not _driver_ride_is_active_for_driver_app(
            db,
            ride=candidate_ride,
            driver_id=driver_id,
            assignment=row,
        ):
            continue
        ranked_candidates.append((_rank_driver_assignment_candidate(row, candidate_ride), row, candidate_ride))
    if ranked_candidates:
        ranked_candidates.sort(key=lambda item: item[0], reverse=True)
        non_excluded = [item for item in ranked_candidates if not is_operational_excluded_ride(item[2])]
        if non_excluded:
            assignment, ride = non_excluded[0][1], non_excluded[0][2]
        else:
            assignment, ride = None, None
    if not ride:
        active_offer = get_driver_active_offer(
            db,
            organization_id=organization_id,
            driver_id=driver_id,
        )
        if active_offer and active_offer.ride_id:
            offer_ride = get_ride_by_id(db, str(active_offer.ride_id))
            if offer_ride and _ride_is_driver_mobile_eligible(offer_ride):
                op = evaluate_driver_ride_operational_state(
                    db,
                    ride=offer_ride,
                    driver_id=driver_id,
                    assignment=active_offer,
                )
                if op.is_active or op.has_active_offer:
                    ride = offer_ride
                    assignment = active_offer
    if not ride:
        fallback_ride = _active_ride_for_driver(db, driver_id)
        if fallback_ride and _ride_is_driver_mobile_eligible(fallback_ride):
            ride = fallback_ride
            assignment = _authoritative_assignment_for_ride(db, fallback_ride, driver_id=driver_id)
    if ride:
        assignment = assignment or _authoritative_assignment_for_ride(db, ride, driver_id=driver_id)
        op = evaluate_driver_ride_operational_state(db, ride=ride, driver_id=driver_id, assignment=assignment)
        ride_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if ride_state in terminal_ride_states or not (op.is_active or op.has_active_offer):
            ride = None
            assignment = None
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


def get_driver_active_ride_data(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
) -> dict[str, Any]:
    """Authoritative active assigned ride for the driver mobile app."""
    driver, organization_id = _ensure_driver_organization_scope(
        db,
        driver_id=driver_id,
        organization_id=organization_id,
        persist_missing=True,
    )

    _prepare_driver_mobile_workspace_read(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    expire_stale_dispatch_offers(db, organization_id=organization_id)

    active_offer = get_driver_active_offer(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    ride: Optional[HealthISFRide] = None
    assignment: Optional[HealthISFDispatchAssignment] = None
    eta_minutes = None

    if active_offer and active_offer.ride_id:
        db.refresh(active_offer)
        offer_ride = get_ride_by_id(db, str(active_offer.ride_id))
        if offer_ride and _ride_is_driver_mobile_eligible(offer_ride):
            op = evaluate_driver_ride_operational_state(
                db,
                ride=offer_ride,
                driver_id=driver_id,
                assignment=active_offer,
            )
            if op.is_active or op.has_active_offer:
                ride = offer_ride
                assignment = active_offer
                eta_minutes = _estimated_eta_minutes(offer_ride)

    if not ride:
        workspace = get_driver_live_workspace_data(
            db,
            organization_id=organization_id,
            driver_id=driver_id,
        )
        ride = workspace.get("ride")
        assignment = workspace.get("assignment")
        eta_minutes = workspace.get("eta_minutes")

    if not ride:
        assigned_rows = list_driver_assigned_rides(
            db,
            organization_id=organization_id,
            driver_id=driver_id,
            limit=1,
        )
        ride = assigned_rows[0] if assigned_rows else None
        if ride:
            assignment = _authoritative_assignment_for_ride(db, ride, driver_id=driver_id)

    provider_name = ""
    if ride and ride.provider_id:
        provider = get_provider_by_id(db, str(ride.provider_id))
        if provider:
            provider_name = str(getattr(provider, "name", None) or getattr(provider, "provider_name", None) or "")

    assignment_state = ""
    active_for_driver = False
    if ride:
        if assignment:
            db.refresh(assignment)
        op = evaluate_driver_ride_operational_state(
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

    return {
        "driver_id": driver_id,
        "organization_id": organization_id,
        "has_active_ride": bool(ride and active_for_driver),
        "ride": ride if active_for_driver else None,
        "assignment": assignment if active_for_driver else None,
        "assignment_state": assignment_state,
        "driver_name": str(getattr(driver, "name", None) or ""),
        "provider_name": provider_name,
        "eta_minutes": eta_minutes,
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
    trip_type: str = "one_way",
    service_date: Optional[Any] = None,
    pickup_time: Optional[datetime] = None,
    arrival_time: Optional[datetime] = None,
    return_pickup_type: Optional[str] = "scheduled_time",
    return_pickup_time: Optional[datetime] = None,
    recurrence: str = "none",
    recurrence_weekdays: Optional[list[str]] = None,
    recurrence_start_date: Optional[Any] = None,
    recurrence_end_date: Optional[Any] = None,
    return_pickup_address: Optional[str] = None,
    return_dropoff_address: Optional[str] = None,
    same_driver_preference: bool = False,
) -> tuple[HealthISFCustomerRideRequest, HealthISFRide]:
    from app.modules.health_isf.scheduling import (
        apply_scheduling_fields_to_ride,
        create_scheduled_ride_request,
        parse_scheduling_payload,
    )

    scheduling = parse_scheduling_payload(
        {
            "trip_type": trip_type,
            "service_date": service_date,
            "pickup_time": pickup_time,
            "arrival_time": arrival_time or scheduled_time,
            "scheduled_time": scheduled_time,
            "return_pickup_type": return_pickup_type,
            "return_pickup_time": return_pickup_time,
            "recurrence": recurrence if recurrence != "none" else ("weekly" if recurring else "none"),
            "recurrence_weekdays": recurrence_weekdays,
            "recurrence_start_date": recurrence_start_date,
            "recurrence_end_date": recurrence_end_date,
            "return_pickup_address": return_pickup_address,
            "return_dropoff_address": return_dropoff_address,
            "same_driver_preference": same_driver_preference,
            "recurring": recurring,
            "recurring_pattern": recurring_pattern,
        }
    )
    use_scheduling = (
        scheduling["trip_type"] == "round_trip"
        or scheduling["recurrence"] == "weekly"
        or scheduling["pickup_time"] is not None
        or scheduling["arrival_time"] is not None
    )

    normalized_ride_type = _normalize_customer_ride_type(ride_type)
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

    def _create_ride_wrapper(db_session: Session, **kwargs: Any) -> HealthISFRide:
        kwargs.setdefault("provider_id", provider.id)
        kwargs["service_type"] = serialize_service_category(normalized_ride_type)
        return create_ride(db_session, skip_intake_automation=True, **kwargs)

    def _create_request_wrapper(db_session: Session, **kwargs: Any) -> HealthISFCustomerRideRequest:
        ride = kwargs["ride"]
        linked = kwargs.get("linked_ride_ids") or [str(ride.id)]
        metadata = kwargs.get("scheduling_metadata") or {}
        request_obj = HealthISFCustomerRideRequest(
            id=uuid4(),
            organization_id=organization_id,
            ride_id=ride.id,
            submitted_by_user_id=submitted_by_user_id,
            rider_name=rider_name,
            rider_phone=rider_phone,
            pickup_address=pickup_address,
            dropoff_address=dropoff_address,
            scheduled_time=kwargs.get("scheduled_time"),
            ride_type=normalized_ride_type,
            is_recurring=bool(kwargs.get("is_recurring")),
            recurring_pattern_json=json.dumps(kwargs.get("recurring_pattern"))
            if kwargs.get("recurring_pattern")
            else None,
            notes=notes,
            trip_type=str(kwargs.get("trip_type") or "one_way"),
            scheduling_metadata_json=json.dumps(metadata) if metadata else None,
            linked_ride_ids_json=json.dumps(linked),
            dispatch_status=CustomerRequestStatus.PENDING.value,
            pending_at=now(),
            created_at=now(),
            updated_at=now(),
        )
        db_session.add(request_obj)
        _commit_or_rollback(db_session)
        db_session.refresh(request_obj)
        return request_obj

    if use_scheduling:
        request_row, primary, _all_rides = create_scheduled_ride_request(
            db,
            organization_id=organization_id,
            rider_name=rider_name,
            rider_phone=rider_phone,
            pickup_address=pickup_address,
            dropoff_address=dropoff_address,
            ride_type=normalized_ride_type,
            notes=notes,
            submitted_by_user_id=submitted_by_user_id,
            scheduling=scheduling,
            create_ride_fn=_create_ride_wrapper,
            create_request_fn=_create_request_wrapper,
        )
        _commit_or_rollback(db)
        return request_row, primary

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
        skip_intake_automation=True,
    )
    from app.modules.health_isf.scheduling import apply_scheduling_fields_to_ride

    apply_scheduling_fields_to_ride(
        ride,
        trip_leg="one_way",
        pickup_time=pickup_time,
        arrival_time=normalized_scheduled or arrival_time,
    )
    db.add(ride)

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
        trip_type=trip_type or "one_way",
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


def _latest_driver_assignment_for_ride(
    db: Session,
    *,
    ride_id: str,
    driver_id: str,
) -> Optional[HealthISFDispatchAssignment]:
    rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    if not rows:
        return None
    now_ts = _as_utc_datetime(now())
    preferred: Optional[HealthISFDispatchAssignment] = None
    preferred_rank = -1
    for row in rows:
        state = str(row.assignment_state or "")
        closed_reason = str(getattr(row, "closed_reason", "") or "").lower()
        if closed_reason and any(
            marker in closed_reason
            for marker in ("superseded", "duplicate", "terminal_ride", "orphaned", "executive_phase4")
        ):
            continue
        if state == DispatchAssignmentState.OFFERED.value:
            if row.offer_expires_at and _as_utc_datetime(row.offer_expires_at) < now_ts:
                continue
            rank = 3
        elif state in ACTIVE_DISPATCH_ASSIGNMENT_STATES:
            rank = 2
        elif state in {DispatchAssignmentState.EXPIRED.value, "expired", DispatchAssignmentState.REASSIGNMENT_PENDING.value}:
            rank = 0
        else:
            rank = 1
        if rank > preferred_rank:
            preferred = row
            preferred_rank = rank
    return preferred or rows[0]


def _driver_ride_is_active_for_driver_app(
    db: Session,
    *,
    ride: HealthISFRide,
    driver_id: str,
    assignment: Optional[HealthISFDispatchAssignment] = None,
) -> bool:
    if not _ride_is_driver_mobile_eligible(ride):
        return False
    op = evaluate_driver_ride_operational_state(
        db,
        ride=ride,
        driver_id=driver_id,
        assignment=assignment,
    )
    if op.reason == "scheduled_reservation":
        return False
    return op.is_active or op.has_active_offer


def list_driver_assigned_rides(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    limit: int = 100,
) -> list[HealthISFRide]:
    _, organization_id = _ensure_driver_organization_scope(
        db,
        driver_id=driver_id,
        organization_id=organization_id,
        persist_missing=True,
    )
    _prepare_driver_mobile_workspace_read(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    expire_stale_dispatch_offers(db, organization_id=organization_id)
    _offer_newest_queue_ride_to_driver(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
    )
    assignment_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.driver_id == driver_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(DRIVER_APP_ASSIGNMENT_STATES)),
        )
        .order_by(desc(HealthISFDispatchAssignment.updated_at), desc(HealthISFDispatchAssignment.created_at))
        .all()
    )
    merged: dict[str, HealthISFRide] = {}
    for assignment in assignment_rows:
        ride = get_ride_by_id(db, assignment.ride_id) if assignment.ride_id else None
        if not ride or not _ride_is_driver_mobile_eligible(ride):
            continue
        if not _driver_ride_is_active_for_driver_app(
            db,
            ride=ride,
            driver_id=driver_id,
            assignment=assignment,
        ):
            continue
        merged[str(ride.id)] = ride

    rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id == driver_id,
        )
        .order_by(desc(HealthISFRide.requested_at), desc(HealthISFRide.updated_at))
        .limit(limit)
        .all()
    )
    for ride in rows:
        if _is_ai_proof_ride(ride) or not _ride_is_driver_mobile_eligible(ride):
            continue
        assignment = _authoritative_assignment_for_ride(db, ride, driver_id=driver_id)
        if not _driver_ride_is_active_for_driver_app(
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
        .limit(limit)
        .all()
    )
    for ride in scheduled_rows:
        if _is_ai_proof_ride(ride) or is_operational_excluded_ride(ride) or _ride_is_terminal(ride):
            continue
        merged[str(ride.id)] = ride

    active_rows = list(merged.values())
    active_rows.sort(
        key=lambda row: _normalized_timestamp_token(row.requested_at),
        reverse=True,
    )
    live_offer = get_driver_active_offer(db, organization_id=organization_id, driver_id=driver_id)
    if live_offer and live_offer.ride_id:
        offer_ride_id = str(live_offer.ride_id)
        offer_idx = next((i for i, row in enumerate(active_rows) if str(row.id) == offer_ride_id), -1)
        if offer_idx > 0:
            active_rows.insert(0, active_rows.pop(offer_idx))
        elif offer_idx < 0:
            offer_ride = get_ride_by_id(db, offer_ride_id)
            if offer_ride and _ride_is_driver_mobile_eligible(offer_ride):
                op = evaluate_driver_ride_operational_state(
                    db,
                    ride=offer_ride,
                    driver_id=driver_id,
                    assignment=live_offer,
                )
                if op.is_active or op.has_active_offer:
                    active_rows.insert(0, offer_ride)
    non_proof = [row for row in active_rows if not _is_ai_proof_ride(row)]
    return (non_proof or active_rows)[:limit]


def list_driver_completed_rides(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    limit: int = 50,
) -> list[HealthISFRide]:
    scan_limit = max(limit * 4, 120)
    rows = (
        db.query(HealthISFRide)
        .filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id == driver_id,
        )
        .order_by(desc(HealthISFRide.completed_at), desc(HealthISFRide.updated_at))
        .limit(scan_limit)
        .all()
    )
    completed: list[HealthISFRide] = []
    seen_ids: set[str] = set()
    for ride in rows:
        if _is_ai_proof_ride(ride):
            continue
        lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if lifecycle != RideStatus.COMPLETED.value:
            continue
        completed.append(ride)
        seen_ids.add(str(ride.id))
        if len(completed) >= limit:
            break

    if len(completed) < limit:
        from app.modules.health_isf.financial_engine import TripFinancialEngine

        earnings = TripFinancialEngine.get_driver_earnings_summary(
            db,
            driver_id=driver_id,
            organization_id=organization_id,
        )
        for trip_row in earnings.get("recent_trips", []):
            ride_id = str(trip_row.get("ride_id") or "")
            if not ride_id or ride_id in seen_ids:
                continue
            ride = get_ride_by_id(db, ride_id)
            if not ride or _is_ai_proof_ride(ride):
                continue
            lifecycle = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            if lifecycle != RideStatus.COMPLETED.value:
                continue
            completed.append(ride)
            seen_ids.add(ride_id)
            if len(completed) >= limit:
                break
    return completed


def get_driver_completion_snapshot(
    db: Session,
    *,
    organization_id: str,
    driver_id: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Single authoritative driver completion view shared by earnings, history, and billing."""
    from app.modules.health_isf.financial_engine import TripFinancialEngine

    earnings = TripFinancialEngine.get_driver_earnings_summary(
        db,
        driver_id=driver_id,
        organization_id=organization_id,
    )
    completed_rides = list_driver_completed_rides(
        db,
        organization_id=organization_id,
        driver_id=driver_id,
        limit=limit,
    )
    completed_ids = {str(ride.id) for ride in completed_rides}
    billing_rows = list_billing_handoff_queue(db, organization_id=organization_id, limit=max(limit, 100))
    billing_for_driver = [
        row
        for row in billing_rows
        if str(row.get("ride_id") or "") in completed_ids
        or str(row.get("driver_id") or "") == str(driver_id)
    ]
    documents = TripFinancialEngine.list_trip_documents_for_driver(
        db,
        driver_id=driver_id,
        organization_id=organization_id,
        limit=max(limit * 3, 100),
    )
    return {
        "driver_id": driver_id,
        "organization_id": organization_id,
        "earnings": earnings,
        "completed_ride_count": len(completed_rides),
        "completed_rides": completed_rides,
        "billing_handoffs": billing_for_driver,
        "documents": documents,
    }


def list_billing_handoff_queue(
    db: Session,
    *,
    organization_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    handoffs = (
        db.query(HealthISFBillingHandoff)
        .filter(HealthISFBillingHandoff.organization_id == organization_id)
        .order_by(desc(HealthISFBillingHandoff.created_at))
        .limit(limit)
        .all()
    )
    if not handoffs:
        return []

    ride_ids = [str(row.ride_id) for row in handoffs if row.ride_id]
    rides_by_id: dict[str, HealthISFRide] = {}
    if ride_ids:
        ride_rows = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.id.in_(ride_ids))
            .all()
        )
        rides_by_id = {str(row.id): row for row in ride_rows}

    request_rows = (
        db.query(HealthISFCustomerRideRequest)
        .filter(
            HealthISFCustomerRideRequest.organization_id == organization_id,
            HealthISFCustomerRideRequest.ride_id.in_(ride_ids),
        )
        .all()
    )
    request_by_ride = {str(row.ride_id): row for row in request_rows if row.ride_id}

    queue: list[dict[str, Any]] = []
    seen_ride_ids: set[str] = set()
    for handoff in handoffs:
        ride_id = str(handoff.ride_id or "")
        if not ride_id or ride_id in seen_ride_ids:
            continue
        seen_ride_ids.add(ride_id)
        ride = rides_by_id.get(ride_id)
        request_row = request_by_ride.get(ride_id)
        queue.append(
            {
                "handoff_id": handoff.id,
                "ride_id": handoff.ride_id,
                "rider_id": getattr(request_row, "id", None),
                "passenger_name": (
                    getattr(ride, "passenger_name", None)
                    or getattr(request_row, "rider_name", None)
                ),
                "driver_id": getattr(ride, "driver_id", None),
                "provider_id": getattr(ride, "provider_id", None),
                "pickup_address": getattr(ride, "pickup_address", None),
                "dropoff_address": getattr(ride, "dropoff_address", None),
                "completed_at": (
                    ride.completed_at.isoformat()
                    if ride and ride.completed_at
                    else handoff.created_at.isoformat() if handoff.created_at else None
                ),
                "fare_amount": float(handoff.ride_price_usd or 0.0),
                "driver_pay": float(handoff.driver_pay_usd or 0.0),
                "platform_revenue": float(handoff.platform_revenue_usd or 0.0),
                "billing_status": str(handoff.handoff_status or "pending"),
                "payment_transaction_id": handoff.payment_transaction_id,
                "payout_id": handoff.payout_id,
                "claim_id": handoff.claim_id,
                "financial_record_id": handoff.financial_record_id,
                "created_at": handoff.created_at.isoformat() if handoff.created_at else None,
            }
        )
    return queue


DEFAULT_ORGANIZATION = {
    "name": "Amicor Health ISF",
    "code": "AMICOR-DEFAULT",
    "address": "100 Operations Ave, New York, NY 10001",
    "phone": "212-555-0000",
}

LEGACY_ORG_CODES = ("AMICOR-DEFAULT", "AMICOR-ISF")

SAMPLE_PROVIDERS = [
    {
        "name": "Fairview Hospital",
        "address": "2450 Riverside Ave, Minneapolis, MN 55454",
        "phone": "612-555-0100",
        "service_type": "hospital",
    },
    {
        "name": "HCMC",
        "address": "730 S 8th St, Minneapolis, MN 55415",
        "phone": "612-555-0200",
        "service_type": "hospital",
    },
    {
        "name": "North Memorial Health",
        "address": "3300 Oakdale Ave N, Robbinsdale, MN 55422",
        "phone": "612-555-0300",
        "service_type": "hospital",
    },
    {
        "name": "Amicor Test Clinic",
        "address": "100 Operations Ave, New York, NY 10001",
        "phone": "212-555-0400",
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
        "is_online": True,
        "rating": 4.8,
    },
    {
        "name": "Maria Garcia",
        "phone": "917-555-1002",
        "vehicle_type": "van",
        "vehicle_plate": "NYC-1002",
        "status": DriverStatus.AVAILABLE,
        "is_online": True,
        "rating": 4.9,
    },
    {
        "name": "David Chen",
        "phone": "917-555-1003",
        "vehicle_type": "sedan",
        "vehicle_plate": "NYC-1003",
        "status": DriverStatus.OFFLINE,
        "is_online": False,
        "rating": 4.7,
    },
    {
        "name": "Test Driver Four",
        "phone": "917-555-1004",
        "vehicle_type": "sedan",
        "vehicle_plate": "NYC-1004",
        "status": DriverStatus.AVAILABLE,
        "is_online": True,
        "rating": 4.6,
    },
    {
        "name": "Test Driver Five",
        "phone": "917-555-1005",
        "vehicle_type": "van",
        "vehicle_plate": "NYC-1005",
        "status": DriverStatus.OFFLINE,
        "is_online": False,
        "rating": 4.5,
    },
    {
        "name": "Test Driver Six",
        "phone": "917-555-1006",
        "vehicle_type": "medical_van",
        "vehicle_plate": "NYC-1006",
        "status": DriverStatus.AVAILABLE,
        "is_online": True,
        "rating": 4.8,
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


def resolve_driver_organization_id(
    db: Session,
    driver: HealthISFDriver,
    *,
    persist_missing: bool = False,
) -> str:
    """Resolve the effective organization for driver mobile reads and assignment sync."""
    existing = getattr(driver, "organization_id", None)
    if existing:
        return str(existing)
    default_org = _get_or_create_default_org(db)
    if persist_missing:
        driver.organization_id = default_org.id
        driver.updated_at = now()
        db.add(driver)
        _commit_or_rollback(db)
        db.refresh(driver)
    return str(default_org.id)


def _ensure_driver_organization_scope(
    db: Session,
    *,
    driver_id: str,
    organization_id: str | None,
    persist_missing: bool = False,
) -> tuple[HealthISFDriver, str]:
    driver = get_driver_by_id(db, driver_id)
    if not driver:
        raise ValueError("Driver not found")
    effective_org = resolve_driver_organization_id(db, driver, persist_missing=persist_missing)
    if organization_id and str(organization_id) not in {"", effective_org}:
        if driver.organization_id and str(driver.organization_id) != str(organization_id):
            raise ValueError("Driver not found")
    return driver, effective_org


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
        dialect = db.bind.dialect.name if db.bind is not None else ""
        if dialect == "postgresql":
            db.execute(
                text(
                    "UPDATE health_isf_drivers "
                    "SET status = substring(status from position('.' in status) + 1) "
                    "WHERE status LIKE 'driverstatus.%'"
                )
            )
        else:
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


def _driver_status_rank(status: DriverStatus) -> int:
    order = {
        DriverStatus.OFFLINE: 0,
        DriverStatus.UNAVAILABLE: 0,
        DriverStatus.AVAILABLE: 1,
        DriverStatus.ASSIGNED: 2,
        DriverStatus.BUSY: 2,
        DriverStatus.EN_ROUTE_PICKUP: 3,
        DriverStatus.WAITING_AT_PICKUP: 4,
        DriverStatus.IN_TRANSIT: 5,
        DriverStatus.COMPLETED: 6,
    }
    return order.get(status, 0)


def _advance_driver_status_for_active_ride(
    db: Session,
    driver: HealthISFDriver,
    target: DriverStatus,
    *,
    ride: Optional[HealthISFRide] = None,
) -> None:
    """Walk driver status through legal transitions when assignment did not pre-engage the driver."""
    desired = _coerce_driver_status(target)
    current = _coerce_driver_status(driver.status)
    if current == desired:
        return
    if _driver_status_rank(current) >= _driver_status_rank(desired):
        return

    if (
        current == DriverStatus.AVAILABLE
        and ride is not None
        and str(ride.driver_id or "") == str(driver.id)
    ):
        _set_driver_status(db, driver, DriverStatus.ASSIGNED)
        current = DriverStatus.ASSIGNED

    if current == desired:
        return

    progression: list[DriverStatus] = []
    if desired == DriverStatus.EN_ROUTE_PICKUP:
        if current in {DriverStatus.ASSIGNED, DriverStatus.BUSY}:
            progression = [DriverStatus.EN_ROUTE_PICKUP]
    elif desired == DriverStatus.WAITING_AT_PICKUP:
        if current in {DriverStatus.ASSIGNED, DriverStatus.BUSY}:
            progression = [DriverStatus.EN_ROUTE_PICKUP, DriverStatus.WAITING_AT_PICKUP]
        elif current == DriverStatus.EN_ROUTE_PICKUP:
            progression = [DriverStatus.WAITING_AT_PICKUP]
    elif desired == DriverStatus.IN_TRANSIT:
        if current in {DriverStatus.ASSIGNED, DriverStatus.BUSY}:
            progression = [
                DriverStatus.EN_ROUTE_PICKUP,
                DriverStatus.WAITING_AT_PICKUP,
                DriverStatus.IN_TRANSIT,
            ]
        elif current == DriverStatus.EN_ROUTE_PICKUP:
            progression = [DriverStatus.WAITING_AT_PICKUP, DriverStatus.IN_TRANSIT]
        elif current == DriverStatus.WAITING_AT_PICKUP:
            progression = [DriverStatus.IN_TRANSIT]
    else:
        progression = [desired]

    for step in progression:
        _set_driver_status(db, driver, step)


def _set_driver_status(
    db: Session,
    driver: HealthISFDriver,
    target_status: str | DriverStatus,
    *,
    force: bool = False,
) -> HealthISFDriver:
    next_status = _coerce_driver_status(target_status)
    current_status = _coerce_driver_status(driver.status)
    if current_status != next_status:
        if not force:
            _validate_driver_transition(current_status, next_status)
        driver.status = next_status
        driver.updated_at = now()
    return driver


def _current_active_rides_for_driver(db: Session, driver_id: str) -> list[HealthISFRide]:
    rows = db.query(HealthISFRide).filter(HealthISFRide.driver_id == driver_id).all()
    return [
        row
        for row in rows
        if not _ride_is_terminal(row) and not _is_ai_proof_ride(row)
    ]


def _release_driver_after_trip_completion(
    db: Session,
    driver: HealthISFDriver,
    *,
    increment_trip_count: bool = True,
) -> None:
    if increment_trip_count:
        driver.total_trips = int(driver.total_trips or 0) + 1
    _set_driver_status(db, driver, DriverStatus.AVAILABLE)
    driver.availability_state = "available"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()


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


def _ensure_driver_bound_ride_workflow_ready(
    db: Session,
    ride: HealthISFRide,
    driver: HealthISFDriver,
    actor_user_id: Optional[str] = None,
) -> HealthISFRide:
    """Align lifecycle when dispatch already bound the driver but state stayed queued."""
    if not ride or not driver or str(ride.driver_id) != str(driver.id):
        return ride
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state != RideStatus.QUEUED.value:
        return ride

    import time

    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.ASSIGNED.value,
        action_type="driver_workflow_ready",
        actor_user_id=actor_user_id,
        note="Driver workflow ready for bound ride",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_workflow_ready",
    )
    if not accepted and RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.ASSIGNED.value:
        raise RideLifecycleConflictError("Ride lifecycle is not ready for driver workflow progression")
    if not ride.accepted_at:
        ride.accepted_at = now()
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    _commit_or_rollback(db)
    db.refresh(ride)
    return ride


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
    if RideStatus(ride.status) in (RideStatus.COMPLETED, RideStatus.CANCELLED):
        raise ValueError("Cannot accept a terminal ride")

    reconcile_ride_assignment_coherence(db, ride)
    db.refresh(ride)

    assignment = _authoritative_assignment_for_ride(db, ride, driver_id=driver.id)
    from app.modules.health_isf.advance_scheduling import assert_driver_may_use_immediate_workflow

    assert_driver_may_use_immediate_workflow(db, ride=ride, driver_id=str(driver.id), assignment=assignment)

    if ride.driver_id != driver.id:
        if not assignment or str(getattr(assignment, "driver_id", "") or "") != str(driver.id):
            raise ValueError("Ride is not assigned to this driver")
        assignment_state_precheck = str(getattr(assignment, "assignment_state", "") or "").lower()
        if assignment_state_precheck in SCHEDULED_DISPATCH_ASSIGNMENT_STATES:
            raise RideLifecycleConflictError(
                f"Cannot accept ride from assignment state '{assignment_state_precheck}'"
            )
        ride.driver_id = driver.id
        ride.updated_at = now()
        _commit_or_rollback(db)
        db.refresh(ride)
        assignment = _authoritative_assignment_for_ride(db, ride, driver_id=driver.id)

    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    assignment = assignment or _authoritative_assignment_for_ride(db, ride, driver_id=driver.id)
    assignment_state = str(getattr(assignment, "assignment_state", "") or "").lower()
    post_accept_states = {
        RideStatus.DRIVER_EN_ROUTE.value,
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.ARRIVED_DESTINATION.value,
        RideStatus.COMPLETED.value,
    }
    post_accept_assignment_states = {
        DispatchAssignmentState.ACCEPTED.value,
        DispatchAssignmentState.EN_ROUTE_PICKUP.value,
        DispatchAssignmentState.PICKUP_COMPLETE.value,
        DispatchAssignmentState.ARRIVED_DESTINATION.value,
        DispatchAssignmentState.DROPOFF_COMPLETE.value,
    }
    if (
        lifecycle_state in post_accept_states
        or (ride.accepted_at and lifecycle_state == RideStatus.ASSIGNED.value)
        or assignment_state in post_accept_assignment_states
    ):
        # Idempotent accept: driver/mobile clients may retry after hydration lag.
        db.refresh(ride)
        return ride
    if assignment_state and assignment_state not in {
        DispatchAssignmentState.OFFERED.value,
        DispatchAssignmentState.ASSIGNED.value,
        DispatchAssignmentState.REASSIGNMENT_PENDING.value,
    }:
        raise RideLifecycleConflictError(f"Cannot accept ride from assignment state '{assignment_state}'")

    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    if lifecycle_state == RideStatus.QUEUED.value:
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
        if not accepted and RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.ASSIGNED.value:
            raise RideLifecycleConflictError("Ride is not in an offerable state for acceptance")

    ride.accepted_at = ride.accepted_at or now()
    _set_driver_status(db, driver, DriverStatus.ASSIGNED)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.ACCEPTED.value,
        note="Driver accepted assignment",
        driver_id=driver.id,
    )
    winning_assignment = _authoritative_assignment_for_ride(db, ride, driver_id=driver.id)
    _close_active_assignments_for_ride(
        db,
        ride_id=str(ride.id),
        target_state=DispatchAssignmentState.REJECTED.value,
        reason="superseded_by_acceptance",
        keep_assignment_id=str(winning_assignment.id) if winning_assignment else None,
    )
    competing_offers = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride.id,
            HealthISFDispatchAssignment.driver_id != driver.id,
            HealthISFDispatchAssignment.assignment_state.in_(
                [
                    DispatchAssignmentState.OFFERED.value,
                    DispatchAssignmentState.ASSIGNED.value,
                    DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                    DispatchAssignmentState.SCHEDULED_OFFERED.value,
                ]
            ),
        )
        .all()
    )
    for row in competing_offers:
        _close_dispatch_assignment_record(
            db,
            row,
            target_state=DispatchAssignmentState.REJECTED.value,
            reason="superseded_by_acceptance",
        )
    _record_dispatch(
        db,
        ride_id=ride.id,
        action="driver_accepted_ride",
        acted_by_user_id=actor_user_id,
        driver_id=driver.id,
        note="Driver accepted assignment",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ACCEPTED.value)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    reconcile_ride_assignment_coherence(db, ride)
    db.refresh(ride)
    _safe_runtime_update(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="driver_accept_ride",
        driver_id=driver.id,
    )
    return ride


def driver_en_route_pickup(
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

    ride = _ensure_driver_bound_ride_workflow_ready(db, ride, driver, actor_user_id=actor_user_id)
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state == RideStatus.DRIVER_EN_ROUTE.value:
        return ride
    if lifecycle_state in {
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.IN_TRANSIT.value,
        RideStatus.ARRIVED_DESTINATION.value,
        RideStatus.COMPLETED.value,
    }:
        return ride
    if lifecycle_state != RideStatus.ASSIGNED.value:
        raise RideLifecycleConflictError(
            f"Cannot mark en route to pickup from lifecycle state '{lifecycle_state}'"
        )

    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.DRIVER_EN_ROUTE.value,
        action_type="driver_en_route_pickup",
        actor_user_id=actor_user_id,
        note="Driver en route to pickup",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_en_route_pickup",
    )
    if not accepted and RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.DRIVER_EN_ROUTE.value:
        raise RideLifecycleConflictError("Unable to transition ride to en route pickup")

    _advance_driver_status_for_active_ride(db, driver, DriverStatus.EN_ROUTE_PICKUP, ride=ride)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.EN_ROUTE_PICKUP.value,
        note="Driver en route to pickup",
    )
    _commit_or_rollback(db)
    db.refresh(ride)
    _safe_runtime_update(
        ride=ride,
        state=RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status),
        source="driver_en_route_pickup",
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
    ride = _ensure_driver_bound_ride_workflow_ready(db, ride, driver, actor_user_id=actor_user_id)
    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state == RideStatus.ARRIVED.value:
        return ride
    if lifecycle_state in {
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.IN_TRANSIT.value,
        RideStatus.ARRIVED_DESTINATION.value,
        RideStatus.COMPLETED.value,
    }:
        return ride
    if lifecycle_state == RideStatus.ASSIGNED.value:
        ride = driver_en_route_pickup(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=actor_user_id)
        if not ride:
            raise ValueError("Unable to start route to pickup")
        db.refresh(ride)
        lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state != RideStatus.DRIVER_EN_ROUTE.value:
        raise RideLifecycleConflictError(
            f"Driver cannot arrive at pickup from lifecycle state '{lifecycle_state}'"
        )

    _advance_driver_status_for_active_ride(db, driver, DriverStatus.WAITING_AT_PICKUP, ride=ride)
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
    if lifecycle_state == RideStatus.RIDER_ONBOARD.value:
        return ride
    if lifecycle_state in {
        RideStatus.IN_PROGRESS.value,
        RideStatus.IN_TRANSIT.value,
        RideStatus.ARRIVED_DESTINATION.value,
        RideStatus.COMPLETED.value,
    }:
        return ride
    if lifecycle_state != RideStatus.ARRIVED.value:
        raise RideLifecycleConflictError(
            f"Pickup can only be completed after driver arrives from lifecycle state '{lifecycle_state}'"
        )

    _advance_driver_status_for_active_ride(db, driver, DriverStatus.IN_TRANSIT, ride=ride)
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
        db.refresh(ride)
        if RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.RIDER_ONBOARD.value:
            raise RideLifecycleConflictError("Unable to mark rider loaded for ride")

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


def driver_start_trip(
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
    if lifecycle_state == RideStatus.IN_PROGRESS.value:
        return ride
    if lifecycle_state in {
        RideStatus.IN_TRANSIT.value,
        RideStatus.ARRIVED_DESTINATION.value,
        RideStatus.COMPLETED.value,
    }:
        return ride
    if lifecycle_state != RideStatus.RIDER_ONBOARD.value:
        raise RideLifecycleConflictError(
            f"Cannot start trip from lifecycle state '{lifecycle_state}'"
        )

    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    progressed = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.IN_PROGRESS.value,
        action_type="transport_started",
        actor_user_id=actor_user_id,
        note="Transport started",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_start_trip",
    )
    if not progressed and RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.IN_PROGRESS.value:
        raise RideLifecycleConflictError("Unable to start trip for ride")

    _advance_driver_status_for_active_ride(db, driver, DriverStatus.IN_TRANSIT, ride=ride)
    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    _commit_or_rollback(db)
    db.refresh(ride)
    sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.IN_PROGRESS.value)
    _commit_or_rollback(db)
    db.refresh(ride)
    return ride


def driver_arrived_destination(
    db: Session,
    driver_id: str,
    ride_id: str,
    actor_user_id: Optional[str] = None,
    *,
    commit: bool = True,
) -> Optional[HealthISFRide]:
    driver = get_driver_by_id(db, driver_id)
    ride = get_ride_by_id(db, ride_id)
    if not driver or not ride:
        return None
    if ride.driver_id != driver.id:
        raise ValueError("Ride is not assigned to this driver")

    lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
    if lifecycle_state == RideStatus.ARRIVED_DESTINATION.value:
        return ride
    if lifecycle_state not in {
        RideStatus.IN_PROGRESS.value,
        RideStatus.IN_TRANSIT.value,
        RideStatus.RIDER_ONBOARD.value,
    }:
        raise RideLifecycleConflictError(
            f"Cannot mark arrived at destination from lifecycle state '{lifecycle_state}'"
        )

    import time
    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    accepted = RideLifecycleManager.transition_ride(
        db,
        ride,
        target_state=RideStatus.ARRIVED_DESTINATION.value,
        action_type="driver_arrived_destination",
        actor_user_id=actor_user_id,
        note="Driver arrived at destination",
        payload={"driver_id": driver.id},
        event_id=event_id,
        sequence_number=sequence_number,
        monotonic_ts=monotonic_ts,
        source="driver_arrived_destination",
    )
    if not accepted and RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.ARRIVED_DESTINATION.value:
        raise RideLifecycleConflictError("Unable to mark arrived at destination for ride")

    driver.availability_state = "on_trip"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now()
    _mark_dispatch_assignment_state(
        db,
        ride_id=ride.id,
        assignment_state=DispatchAssignmentState.ARRIVED_DESTINATION.value,
        note="Driver arrived at destination",
    )
    if commit:
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
    if lifecycle_state == RideStatus.COMPLETED.value:
        financial = _ensure_completion_billing_records(db, ride, actor_user_id=actor_user_id)
        if not financial:
            raise ValueError("Completed ride is missing financial settlement records")
        _mark_dispatch_assignment_state(
            db,
            ride_id=ride.id,
            assignment_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            note="Dropoff completed",
        )
        sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.COMPLETED.value)
        if _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
            _release_driver_after_trip_completion(db, driver, increment_trip_count=False)
        _commit_or_rollback(db)
        db.refresh(ride)
        db.refresh(driver)
        _safe_runtime_unregister(ride_id=ride.id, reason="driver_dropoff_complete")
        maybe_assign_next_pending_ride_to_available_driver(
            db,
            organization_id=ride.organization_id,
            driver_id=driver.id,
            actor_user_id=actor_user_id,
        )
        return ride

    if lifecycle_state != RideStatus.ARRIVED_DESTINATION.value:
        if lifecycle_state in {
            RideStatus.IN_PROGRESS.value,
            RideStatus.IN_TRANSIT.value,
            RideStatus.RIDER_ONBOARD.value,
        }:
            driver_arrived_destination(
                db,
                driver_id=driver_id,
                ride_id=ride_id,
                actor_user_id=actor_user_id,
                commit=False,
            )
            db.flush()
            lifecycle_state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
        if lifecycle_state != RideStatus.ARRIVED_DESTINATION.value:
            raise RideLifecycleConflictError(
                "Dropoff can only be completed after the driver arrives at destination"
            )

    import time
    from app.modules.health_isf.financial_engine import TripFinancialEngine

    monotonic_ts = time.monotonic()
    event_id = str(uuid4())
    sequence_number = int(monotonic_ts * 1000)
    try:
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
        if not accepted and RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status) != RideStatus.COMPLETED.value:
            raise RideLifecycleConflictError("Unable to complete dropoff for ride")

        financial = TripFinancialEngine.process_trip_completion(
            db,
            ride,
            actor_user_id=actor_user_id,
            materialize_payout_row=False,
        )
        if not financial or float(financial.get("ride_price_usd") or 0.0) <= 0.0:
            raise ValueError("Financial settlement did not produce a billable trip record")

        _close_active_assignments_for_ride(
            db,
            ride_id=str(ride.id),
            target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            reason="dropoff_completed",
        )
        _mark_dispatch_assignment_state(
            db,
            ride_id=ride.id,
            assignment_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            note="Dropoff completed",
            driver_id=driver.id,
        )
        sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.COMPLETED.value)
        _release_driver_after_trip_completion(db, driver)
        _commit_or_rollback(db)
    except Exception as exc:
        db.rollback()
        ride = get_ride_by_id(db, ride_id)
        driver = get_driver_by_id(db, driver_id)
        if ride:
            marker = "financial_exception"
            existing_notes = str(ride.notes or "")
            if marker not in existing_notes.lower():
                ride.notes = (existing_notes + f"\n{marker}: {exc}").strip()
                ride.updated_at = now()
            _record_dispatch(
                db,
                ride_id=ride.id,
                action="financial_exception",
                acted_by_user_id=actor_user_id,
                driver_id=driver.id if driver else None,
                note=str(exc),
            )
            reconcile_ride_assignment_coherence(db, ride, actor_user_id=actor_user_id)
            _commit_or_rollback(db)
        raise ValueError(f"Trip completion failed: {exc}") from exc

    db.refresh(ride)
    db.refresh(driver)
    _safe_runtime_unregister(ride_id=ride.id, reason="driver_dropoff_complete")
    maybe_assign_next_pending_ride_to_available_driver(
        db,
        organization_id=ride.organization_id,
        driver_id=driver.id,
        actor_user_id=actor_user_id,
    )
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


def _vehicle_plate_taken(db: Session, candidate: str) -> bool:
    if (
        db.query(HealthISFVehicle.id)
        .filter(HealthISFVehicle.vehicle_plate == candidate)
        .first()
    ):
        return True
    if (
        db.query(HealthISFDriver.id)
        .filter(HealthISFDriver.vehicle_plate == candidate)
        .first()
    ):
        return True
    return False


def _resolve_unique_vehicle_plate(db: Session, base_plate: str, organization_id: str) -> str:
    base = str(base_plate or "VEH").strip() or "VEH"
    candidates = [
        base,
        f"{base}-{organization_id.replace('-', '')[:6].upper()}",
        f"{base}-{uuid4()[:6].upper()}",
    ]
    for candidate in candidates:
        if not _vehicle_plate_taken(db, candidate):
            return candidate
    return f"{base}-{uuid4()[:8].upper()}"


def _release_canonical_phone(
    db: Session,
    canonical_phone: str,
    *,
    keep_driver_id: str | None = None,
) -> None:
    """Archive duplicate rows that hold a canonical sample-driver phone."""
    rows = (
        db.query(HealthISFDriver)
        .filter(HealthISFDriver.phone == canonical_phone)
        .order_by(HealthISFDriver.created_at.asc())
        .all()
    )
    for other in rows:
        if keep_driver_id and str(other.id) == str(keep_driver_id):
            continue
        other.phone = f"archived-{str(other.id)[:8]}"
        other.is_active = False
        other.updated_at = now()


def _operational_organization_ids(db: Session) -> set[str]:
    """Collect tenant ids that currently have providers, rides, or active users."""
    org_ids: set[str] = set()
    default_org = _get_or_create_default_org(db)
    org_ids.add(str(default_org.id))

    for model in (HealthISFProvider, HealthISFRide, HealthISFDriver):
        rows = db.query(model.organization_id).distinct().all()
        for row in rows:
            value = row[0] if isinstance(row, tuple) else row
            if value:
                org_ids.add(str(value))

    try:
        from app.db.models import User as PlatformUser

        user_rows = (
            db.query(PlatformUser.organization_id)
            .filter(PlatformUser.organization_id.isnot(None))
            .distinct()
            .all()
        )
        for row in user_rows:
            if row[0]:
                org_ids.add(str(row[0]))
    except Exception:
        pass

    return org_ids


def _apply_canonical_driver_runtime(row: HealthISFDriver, item: dict[str, Any]) -> None:
    """Apply canonical availability/online posture for seeded production drivers."""
    status = _coerce_driver_status(item["status"])
    is_online = bool(item.get("is_online", status == DriverStatus.AVAILABLE))
    row.status = status
    row.is_online = is_online
    if status == DriverStatus.AVAILABLE and is_online:
        row.availability_state = "available"
        row.auth_state = "active"
    else:
        row.availability_state = "offline"
        row.auth_state = "inactive"


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
        availability_state="offline",
        auth_state="inactive",
        is_online=False,
        is_active=True,
        total_trips=0,
        rating=item["rating"],
        created_at=now(),
        updated_at=now(),
    )
    _apply_canonical_driver_runtime(driver, item)
    db.add(driver)
    db.flush()
    return driver


def ensure_sample_drivers(db: Session, organization_id: str | None = None) -> dict[str, Any]:
    """Idempotently ensure baseline fleet drivers exist for dispatch and driver login."""
    org = _get_organization_by_id(db, organization_id) if organization_id else _get_or_create_default_org(db)
    if not org:
        return {"organization_id": None, "created": 0, "updated": 0, "total": 0, "driver_ids": [], "driver_names": []}

    created = 0
    updated = 0
    driver_ids: list[str] = []
    driver_names: list[str] = []
    changed = False

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
                    vehicle = db.query(HealthISFVehicle).filter(HealthISFVehicle.id == row.vehicle_id).first()
                    if vehicle:
                        vehicle.organization_id = org.id
                        vehicle.updated_at = now()
                updated += 1
                changed = True
        if not row:
            try:
                row = _create_canonical_sample_driver(db, org, item)
                created += 1
                changed = True
            except Exception as exc:
                db.rollback()
                logger.warning(
                    "Canonical driver create failed for org=%s name=%s: %s",
                    org.id,
                    canonical_name,
                    exc,
                )
                row = (
                    db.query(HealthISFDriver)
                    .filter(HealthISFDriver.phone == canonical_phone)
                    .order_by(HealthISFDriver.created_at.asc())
                    .first()
                )
                if not row:
                    raise
                if str(row.organization_id) != str(org.id):
                    row.organization_id = org.id
                row.name = canonical_name
                row.is_active = True
                row.updated_at = now()
                updated += 1
                changed = True
        else:
            row.name = canonical_name
            _release_canonical_phone(db, canonical_phone, keep_driver_id=str(row.id))
            row.phone = canonical_phone
            row.vehicle_type = item["vehicle_type"]
            row.status = item["status"]
            row.rating = item["rating"]
            row.is_active = True
            row.organization_id = org.id
            _apply_canonical_driver_runtime(row, item)
            row.updated_at = now()
            if row.vehicle_id:
                vehicle = db.query(HealthISFVehicle).filter(HealthISFVehicle.id == row.vehicle_id).first()
                if vehicle and str(vehicle.organization_id) != str(org.id):
                    vehicle.organization_id = org.id
                    vehicle.updated_at = now()
            updated += 1
            changed = True

        driver_ids.append(str(row.id))
        driver_names.append(str(row.name))

    if changed:
        _commit_or_rollback(db)

    total = (
        db.query(HealthISFDriver)
        .filter(
            HealthISFDriver.organization_id == org.id,
            HealthISFDriver.is_active == True,
        )
        .count()
    )
    return {
        "organization_id": str(org.id),
        "organization_name": org.name,
        "created": created,
        "updated": updated,
        "total": total,
        "driver_ids": driver_ids,
        "driver_names": driver_names,
    }


def sync_operational_driver_fleet(db: Session) -> dict[str, Any]:
    """Ensure baseline drivers exist for every tenant with operational activity."""
    summaries: list[dict[str, Any]] = []
    for org_id in sorted(_operational_organization_ids(db)):
        try:
            summaries.append(ensure_sample_drivers(db, organization_id=org_id))
        except Exception as exc:
            logger.warning("Operational driver fleet sync failed for org=%s: %s", org_id, exc)
    return {
        "organizations_synced": len(summaries),
        "summaries": summaries,
    }


def sync_operational_provider_fleet(db: Session) -> dict[str, Any]:
    """Ensure baseline providers exist for every tenant with operational activity."""
    summaries: list[dict[str, Any]] = []
    for org_id in sorted(_operational_organization_ids(db)):
        try:
            summaries.append(ensure_sample_providers(db, organization_id=org_id))
        except Exception as exc:
            logger.warning("Operational provider fleet sync failed for org=%s: %s", org_id, exc)
    return {
        "organizations_synced": len(summaries),
        "summaries": summaries,
    }


def ensure_operational_bootstrap(db: Session, organization_id: str | None = None) -> dict[str, Any]:
    """Idempotently ensure canonical providers and drivers exist for one tenant."""
    provider_summary = ensure_sample_providers(db, organization_id=organization_id)
    driver_summary = ensure_sample_drivers(db, organization_id=organization_id)
    return {
        "organization_id": provider_summary.get("organization_id") or driver_summary.get("organization_id"),
        "provider_total": int(provider_summary.get("total") or 0),
        "driver_total": int(driver_summary.get("total") or 0),
        "providers": provider_summary,
        "drivers": driver_summary,
    }


def sync_operational_bootstrap(db: Session) -> dict[str, Any]:
    """Ensure canonical providers and drivers for every active production tenant."""
    summaries: list[dict[str, Any]] = []
    for org_id in sorted(_operational_organization_ids(db)):
        try:
            summaries.append(ensure_operational_bootstrap(db, organization_id=org_id))
        except Exception as exc:
            logger.warning("Operational bootstrap failed for org=%s: %s", org_id, exc)
    return {
        "organizations_synced": len(summaries),
        "summaries": summaries,
    }


def ensure_sample_driver_credentials(db: Session, organization_id: str | None = None) -> dict[str, str]:
    """Backward-compatible wrapper returning driver_id -> phone map."""
    summary = ensure_sample_drivers(db, organization_id=organization_id)
    return {driver_id: "" for driver_id in summary.get("driver_ids", [])}


def ensure_sample_providers(db: Session, organization_id: str | None = None) -> dict[str, Any]:
    """Idempotently ensure baseline partner providers exist for ride creation and dispatch."""
    org = _get_organization_by_id(db, organization_id) if organization_id else _get_or_create_default_org(db)
    if not org:
        return {"organization_id": None, "created": 0, "updated": 0, "total": 0, "provider_ids": []}

    created = 0
    updated = 0
    provider_ids: list[str] = []
    for item in SAMPLE_PROVIDERS:
        name = str(item["name"]).strip()
        row = (
            db.query(HealthISFProvider)
            .filter(
                HealthISFProvider.organization_id == org.id,
                func.lower(HealthISFProvider.name) == name.lower(),
            )
            .order_by(HealthISFProvider.created_at.asc())
            .first()
        )
        if not row:
            row = HealthISFProvider(
                id=uuid4(),
                organization_id=org.id,
                name=name,
                address=item["address"],
                phone=item["phone"],
                service_type=item["service_type"],
                is_active=True,
                created_at=now(),
                updated_at=now(),
            )
            db.add(row)
            db.flush()
            created += 1
        else:
            row.address = item["address"]
            row.phone = item["phone"]
            row.service_type = item["service_type"]
            row.is_active = True
            row.updated_at = now()
            updated += 1
        provider_ids.append(str(row.id))

    if created or updated:
        _commit_or_rollback(db)

    total = (
        db.query(HealthISFProvider)
        .filter(
            HealthISFProvider.organization_id == org.id,
            HealthISFProvider.is_active == True,
        )
        .count()
    )
    return {
        "organization_id": str(org.id),
        "organization_name": org.name,
        "created": created,
        "updated": updated,
        "total": total,
        "provider_ids": provider_ids,
    }


def list_providers_for_organization(
    db: Session,
    organization_id: str,
    skip: int = 0,
    limit: int = 50,
) -> list[HealthISFProvider]:
    return (
        db.query(HealthISFProvider)
        .filter(
            HealthISFProvider.organization_id == organization_id,
            HealthISFProvider.is_active == True,
        )
        .order_by(HealthISFProvider.name.asc())
        .offset(skip)
        .limit(limit)
        .all()
    )


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
    provider_seed = ensure_sample_providers(db, organization_id=org.id)
    summary["providers"] = int(provider_seed.get("total") or 0)
    driver_seed = ensure_sample_drivers(db, organization_id=org.id)
    summary["drivers"] = int(driver_seed.get("total") or 0)

    existing_rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org.id).count()
    existing_drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).count()
    if existing_rides > 0 or existing_drivers > 0:
        summary["already_exists"] = True
        summary["organizations"] = 1
        return summary

    summary["organizations"] = 1

    providers_map = {}
    for item in SAMPLE_PROVIDERS:
        provider = (
            db.query(HealthISFProvider)
            .filter(
                HealthISFProvider.organization_id == org.id,
                func.lower(HealthISFProvider.name) == str(item["name"]).strip().lower(),
            )
            .first()
        )
        if not provider:
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
            summary["providers"] += 1
        providers_map[provider.name] = provider

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

_PLATFORM_RESET_EPOCH_BY_ORG: dict[str, str] = {}
_PLATFORM_RESET_EVENT_TYPE = "platform.operational_reset"


def _persist_platform_reset_epoch(db: Session, organization_id: str, reset_epoch: str) -> None:
    db.add(
        HealthISFWorkflowAuditLog(
            id=str(uuid4()),
            organization_id=str(organization_id),
            event_type=_PLATFORM_RESET_EVENT_TYPE,
            payload=json.dumps({"platform_reset_epoch": reset_epoch}),
            created_at=now(),
        )
    )


def _load_platform_reset_epoch(db: Session, organization_id: str) -> str:
    row = (
        db.query(HealthISFWorkflowAuditLog)
        .filter(
            HealthISFWorkflowAuditLog.organization_id == str(organization_id),
            HealthISFWorkflowAuditLog.event_type == _PLATFORM_RESET_EVENT_TYPE,
        )
        .order_by(desc(HealthISFWorkflowAuditLog.created_at))
        .first()
    )
    if not row or not row.payload:
        return ""
    try:
        payload = json.loads(row.payload)
    except Exception:
        return ""
    return str(payload.get("platform_reset_epoch") or "")


def _delete_rows_for_org(db: Session, model: Any, organization_id: str) -> int:
    return int(
        db.query(model)
        .filter(model.organization_id == organization_id)
        .delete(synchronize_session=False)
        or 0
    )


def _delete_rows_for_ride_ids(db: Session, model: Any, ride_ids: list[str]) -> int:
    if not ride_ids:
        return 0
    return int(
        db.query(model)
        .filter(model.ride_id.in_(ride_ids))
        .delete(synchronize_session=False)
        or 0
    )


TEST_RIDE_MARKERS = (
    "lifecycle test",
    "stability manual",
    "platform stability",
    "proof rider",
    "proof ",
    "two ride",
    "manual test",
    "browser verify",
    "ops verify",
    "prod verify",
    "verify api",
    "verify ave",
    "test rider",
    "manual rider",
    "driver dispatch lifecycle",
    "driver lifecycle",
    "backend recovery validation",
    "amicor gate rider",
    "timing test",
    "visible driver mobile rider",
    "clinic rider b op_",
    "nenway",
    "yeawon",
    "prod_sync_",
    "bill_sync_",
    "malik_final_proof",
    "mlik_final_proof",
    "e2e sync",
    "financial rider",
    "production sync consecutive",
    "billing module sync",
    "render_ready_",
    "final local production readiness",
    "ops_clean_",
    "final ops dashboard cleanup",
)


def _is_test_ride_row(ride: HealthISFRide) -> bool:
    haystack = " ".join(
        [
            str(ride.passenger_name or ""),
            str(ride.pickup_address or ""),
            str(ride.dropoff_address or ""),
            str(ride.notes or ""),
        ]
    ).lower()
    return any(marker in haystack for marker in TEST_RIDE_MARKERS) or _is_ai_proof_ride(ride)


def purge_test_operational_artifacts(db: Session, organization_id: str) -> dict[str, Any]:
    """Remove test/proof rides and related billing artifacts; keep seeded users/drivers/providers."""
    org_id = str(organization_id)
    now_ts = now()
    counts: dict[str, Any] = {"organization_id": org_id}

    rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org_id).all()
    test_ride_ids = [str(ride.id) for ride in rides if _is_test_ride_row(ride)]
    counts["test_rides_selected"] = len(test_ride_ids)

    driver_ids = [
        str(row[0])
        for row in db.query(HealthISFDriver.id).filter(HealthISFDriver.organization_id == org_id).all()
    ]

    if test_ride_ids:
        trip_ids = [
            str(row[0])
            for row in db.query(HealthISFTrip.id).filter(HealthISFTrip.ride_id.in_(test_ride_ids)).all()
        ]
        if trip_ids:
            counts["deleted_payouts"] = int(
                db.query(HealthISFPayout)
                .filter(HealthISFPayout.trip_id.in_(trip_ids))
                .delete(synchronize_session=False)
                or 0
            )

    if test_ride_ids:
        ride_scoped_models = (
            HealthISFTrip,
            HealthISFDispatchLog,
            HealthISFRideStatusHistory,
            HealthISFRideRoutePlan,
            HealthISFRideExecutionAction,
            HealthISFPaymentTransaction,
            HealthISFTripFinancialRecord,
            HealthISFBillingHandoff,
            HealthISFClaim,
            HealthISFSettlementLedger,
            HealthISFTripDocument,
            RideAssignmentLock,
            RealTimeEvent,
        )
        for model in ride_scoped_models:
            key = f"deleted_{model.__tablename__}"
            counts[key] = _delete_rows_for_ride_ids(db, model, test_ride_ids)

        counts["deleted_health_isf_dispatch_assignments"] = int(
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id.in_(test_ride_ids))
            .delete(synchronize_session=False)
            or 0
        )
        counts["deleted_health_isf_customer_ride_requests"] = int(
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.ride_id.in_(test_ride_ids))
            .delete(synchronize_session=False)
            or 0
        )
        counts["deleted_health_isf_rides"] = int(
            db.query(HealthISFRide)
            .filter(HealthISFRide.id.in_(test_ride_ids))
            .delete(synchronize_session=False)
            or 0
        )

    cancelled_active = int(
        db.execute(
            text(
                """
                UPDATE health_isf_rides
                SET status = 'cancelled',
                    lifecycle_state = 'cancelled',
                    driver_id = NULL,
                    updated_at = :now_ts
                WHERE organization_id = :org_id
                  AND COALESCE(lifecycle_state, status) NOT IN ('completed', 'cancelled', 'failed')
                  AND status NOT IN ('completed', 'cancelled', 'failed')
                """
            ),
            {"org_id": org_id, "now_ts": now_ts},
        ).rowcount
        or 0
    )
    db.execute(
        text(
            """
            UPDATE health_isf_dispatch_assignments
            SET assignment_state = 'dropoff_complete',
                updated_at = :now_ts
            WHERE organization_id = :org_id
              AND assignment_state IN ('offered', 'assigned', 'accepted', 'en_route_pickup', 'pickup_complete')
            """
        ),
        {"org_id": org_id, "now_ts": now_ts},
    )
    counts["cancelled_active_rides"] = cancelled_active

    drivers_reset = 0
    for driver in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all():
        driver.status = DriverStatus.AVAILABLE
        driver.availability_state = "available"
        driver.is_active = True
        driver.is_online = True
        driver.auth_state = "active"
        driver.last_seen_at = now_ts
        driver.updated_at = now_ts
        drivers_reset += 1
    counts["drivers_reset_available"] = drivers_reset

    db.commit()
    _clear_runtime_caches_for_org(org_id)
    counts["dispatch_queue_count"] = len(get_dispatch_queue(db, organization_id=org_id, limit=500))
    counts["active_assignments"] = int(
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == org_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .count()
    )
    return counts


def _purge_organization_operational_state(db: Session, organization_id: str) -> dict[str, int]:
    """Delete every org-scoped ride, queue, assignment, and operational artifact."""
    org_id = str(organization_id)
    counts: dict[str, int] = {}

    ride_ids = [
        str(row[0])
        for row in db.query(HealthISFRide.id).filter(HealthISFRide.organization_id == org_id).all()
    ]
    driver_ids = [
        str(row[0])
        for row in db.query(HealthISFDriver.id).filter(HealthISFDriver.organization_id == org_id).all()
    ]

    if driver_ids:
        counts["deleted_payouts"] = int(
            db.query(HealthISFPayout)
            .filter(HealthISFPayout.driver_id.in_(driver_ids))
            .delete(synchronize_session=False)
            or 0
        )
        counts["deleted_health_isf_trips_by_driver"] = int(
            db.query(HealthISFTrip)
            .filter(HealthISFTrip.driver_id.in_(driver_ids))
            .delete(synchronize_session=False)
            or 0
        )

    if ride_ids:
        ride_scoped_models = (
            HealthISFTrip,
            HealthISFDispatchLog,
            HealthISFRideStatusHistory,
            HealthISFRideRoutePlan,
            HealthISFRideExecutionAction,
            HealthISFPaymentTransaction,
            HealthISFTripFinancialRecord,
            HealthISFBillingHandoff,
            RideAssignmentLock,
            RealTimeEvent,
        )
        for model in ride_scoped_models:
            key = f"deleted_{model.__tablename__}"
            counts[key] = _delete_rows_for_ride_ids(db, model, ride_ids)

    org_scoped_models = (
        HealthISFDispatchAssignment,
        HealthISFCustomerRideRequest,
        HealthISFRecurringRideSchedule,
        HealthISFRide,
        OperationalAlertLog,
        HealthISFWorkflowEscalation,
        HealthISFWorkflowIncident,
        HealthISFWorkflowExecution,
        DispatcherActivityLog,
        DispatchEventRetry,
        DispatchDeadLetterEvent,
        HealthISFDriverLocationPing,
    )
    for model in org_scoped_models:
        key = f"deleted_{model.__tablename__}"
        counts[key] = _delete_rows_for_org(db, model, org_id)

    counts["deleted_health_isf_workflow_audit_logs"] = int(
        db.query(HealthISFWorkflowAuditLog)
        .filter(
            HealthISFWorkflowAuditLog.organization_id == org_id,
            HealthISFWorkflowAuditLog.event_type != _PLATFORM_RESET_EVENT_TYPE,
        )
        .delete(synchronize_session=False)
        or 0
    )

    for table_name in (
        "health_isf_dispatch_idempotency",
        "health_isf_operational_memory_snapshots",
        "health_isf_settlement_ledger",
        "health_isf_claims",
    ):
        try:
            result = db.execute(
                text(f"DELETE FROM {table_name} WHERE organization_id = :org_id"),
                {"org_id": org_id},
            )
            counts[f"deleted_{table_name}"] = int(result.rowcount or 0)
        except Exception:
            counts[f"deleted_{table_name}"] = 0

    counts["rides_before_delete"] = len(ride_ids)
    counts["drivers_in_org"] = len(driver_ids)
    return counts


def _clear_runtime_caches_for_org(organization_id: str) -> None:
    org_id = str(organization_id or "")
    if not org_id:
        return
    try:
        from app.modules.health_isf.realtime import get_broadcaster

        get_broadcaster().clear_organization_runtime_state(org_id)
    except Exception as exc:
        logger.info({"event": "operational_reset_runtime_cache_skipped", "error": str(exc)})

    try:
        assistant_redis_url = str(os.getenv("ASSISTANT_REDIS_URL", "") or "").strip()
        if assistant_redis_url:
            import redis

            client = redis.Redis.from_url(assistant_redis_url, decode_responses=True)
            for key in client.scan_iter(match=f"*{org_id}*"):
                client.delete(key)
    except Exception as exc:
        logger.info({"event": "operational_reset_assistant_redis_skipped", "error": str(exc)})


def get_platform_reset_status(db: Session, organization_id: str) -> dict[str, Any]:
    """Return live readiness flags used by clients to invalidate stale browser caches."""
    org = _get_organization_by_id(db, organization_id) or _get_or_create_default_org(db)
    org_id = str(org.id)
    open_assignments = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == org_id,
            HealthISFDispatchAssignment.assignment_state.in_(list(ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
        )
        .count()
    )
    ride_count = db.query(HealthISFRide).filter(HealthISFRide.organization_id == org_id).count()
    request_count = db.query(HealthISFCustomerRideRequest).filter(
        HealthISFCustomerRideRequest.organization_id == org_id
    ).count()
    dispatch_queue_count = len(get_dispatch_queue(db, organization_id=org_id, limit=500))
    available_drivers = (
        db.query(HealthISFDriver)
        .filter(
            HealthISFDriver.organization_id == org_id,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        )
        .count()
    )
    system_ready = (
        ride_count == 0
        and request_count == 0
        and open_assignments == 0
        and dispatch_queue_count == 0
    )
    epoch = _PLATFORM_RESET_EPOCH_BY_ORG.get(org_id) or _load_platform_reset_epoch(db, org_id)
    if epoch:
        _PLATFORM_RESET_EPOCH_BY_ORG[org_id] = epoch
    return {
        "organization_id": org_id,
        "platform_reset_epoch": epoch,
        "db_ride_count": ride_count,
        "db_customer_request_count": request_count,
        "db_open_assignments": open_assignments,
        "dispatch_queue_count": dispatch_queue_count,
        "available_driver_count": available_drivers,
        "system_ready_for_new_ride": system_ready,
    }


def complete_operational_reset(db: Session, organization_id: str) -> dict[str, Any]:
    """Hard-reset org ride/dispatch state so all surfaces show zero active work."""
    org = _get_organization_by_id(db, organization_id) or _get_or_create_default_org(db)
    if str(org.id) != str(organization_id):
        raise ValueError("Organization scope mismatch")

    now_ts = now()
    purge_counts = _purge_organization_operational_state(db, organization_id=str(org.id))

    revoked_sessions = 0
    bootstrap_summary = ensure_operational_bootstrap(db, organization_id=str(org.id))
    reset_drivers = int(bootstrap_summary.get("driver_total") or 0)

    drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org.id).all()
    sessions: list[HealthISFDriverSession] = []
    if drivers:
        sessions = (
            db.query(HealthISFDriverSession)
            .filter(
                HealthISFDriverSession.driver_id.in_([driver.id for driver in drivers]),
                HealthISFDriverSession.session_state == "active",
                HealthISFDriverSession.revoked_at.is_(None),
            )
            .all()
        )
    for session in sessions:
        session.session_state = "revoked"
        session.revoked_at = now_ts
        session.updated_at = now_ts
        revoked_sessions += 1

    reset_epoch = now_ts.isoformat()
    _PLATFORM_RESET_EPOCH_BY_ORG[str(org.id)] = reset_epoch
    _persist_platform_reset_epoch(db, str(org.id), reset_epoch)
    db.commit()
    _clear_runtime_caches_for_org(str(org.id))

    try:
        governor = get_runtime_governor()
        if governor and hasattr(governor, "run_cleanup_cycle"):
            governor.run_cleanup_cycle(db, organization_id=str(org.id))
    except Exception as exc:
        logger.info({"event": "operational_reset_governor_cleanup_skipped", "error": str(exc)})

    remaining_open = (
        db.query(HealthISFRide)
        .filter(HealthISFRide.organization_id == org.id)
        .count()
    )
    return {
        "organization_id": str(org.id),
        "platform_reset_epoch": reset_epoch,
        **purge_counts,
        "deleted_rides": purge_counts.get("deleted_health_isf_rides", 0),
        "rides_before_delete": purge_counts.get("rides_before_delete", 0),
        "deleted_assignments": purge_counts.get("deleted_health_isf_dispatch_assignments", 0),
        "deleted_customer_requests": purge_counts.get("deleted_health_isf_customer_ride_requests", 0),
        "drivers_reset": reset_drivers,
        "bootstrap": bootstrap_summary,
        "revoked_driver_sessions": revoked_sessions,
        "remaining_open_rides": remaining_open,
        "dispatch_queue_count": len(get_dispatch_queue(db, organization_id=org.id, limit=500)),
    }


def reset_pilot_environment(db: Session, organization_id: str) -> dict[str, Any]:
    """Clear all ride/dispatch state and restore drivers to an idle waiting posture."""
    return complete_operational_reset(db, organization_id=organization_id)


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
    org_ids = {
        str(row[0])
        for row in db.query(HealthISFDriver.organization_id)
        .filter(HealthISFDriver.is_active == True)
        .distinct()
        .all()
        if row[0]
    }
    for organization_id in org_ids:
        _sweep_stale_assignment_rows_for_organization(db, organization_id=organization_id)
    rows = (
        db.query(HealthISFDriver)
        .filter(
            and_(
                HealthISFDriver.is_active == True,
                HealthISFDriver.status == DriverStatus.AVAILABLE,
                HealthISFDriver.availability_state == "available",
                HealthISFDriver.is_online == True,
            )
        )
        .all()
    )
    return [driver for driver in rows if _driver_active_workload_count(db, driver.id) == 0]


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


def get_all_rides(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    *,
    organization_id: str | None = None,
    active_only: bool = False,
    exclude_test: bool = False,
    history_only: bool = False,
) -> list[HealthISFRide]:
    """List rides newest-first.

    active_only: operational dashboards (exclude completed/cancelled/failed).
    history_only: completed/cancelled/failed only (History/Reports).
    exclude_test: hide proof/demo/test marker rides from operational views.
    """
    query = db.query(HealthISFRide)
    if organization_id:
        query = query.filter(HealthISFRide.organization_id == organization_id)
    rows = (
        query.order_by(desc(HealthISFRide.requested_at), desc(HealthISFRide.created_at))
        .offset(max(0, int(skip or 0)))
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )
    out: list[HealthISFRide] = []
    for ride in rows:
        if exclude_test and (_is_ai_proof_ride(ride) or _is_test_ride_row(ride)):
            continue
        terminal = _ride_is_terminal(ride)
        if active_only and terminal:
            continue
        if history_only and not terminal:
            continue
        out.append(ride)
    return out


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
    skip_intake_automation: bool = False,
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
    if not ride.driver_id and not skip_intake_automation:
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
            _ensure_completion_billing_records(db, ride, actor_user_id=actor_user_id)
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

    _prepare_driver_mobile_workspace_read(
        db,
        organization_id=str(driver.organization_id),
        driver_id=str(driver.id),
        actor_user_id=actor_user_id,
    )
    _expire_superseded_preaccept_offers_for_driver(
        db,
        driver_id=str(driver.id),
        keep_ride_id=str(ride.id),
        reason="superseded_by_direct_assignment",
    )
    _reconcile_conflicting_driver_preaccept_assignments(
        db,
        organization_id=str(driver.organization_id),
        driver_id=str(driver.id),
        prefer_ride_id=str(ride.id),
        reason="superseded_by_direct_assignment",
    )

    if _driver_active_workload_count(db, driver.id) > 0:
        raise ValueError("Driver already has an active ride assignment")

    if str(driver.availability_state or "").lower() not in {"available"}:
        raise ValueError("Driver is not available for assignment")

    if _coerce_driver_status(driver.status) != DriverStatus.AVAILABLE:
        if not (allow_assigned_driver and _coerce_driver_status(driver.status) == DriverStatus.ASSIGNED):
            logger.warning({
                "event": "assignment_rejected",
                "ride_id": ride_id,
                "driver_id": driver_id,
                "driver_status": driver.status,
                "reason": "Driver unavailable"
            })
            raise ValueError("Cannot assign unavailable driver")

    if ride.organization_id != driver.organization_id:
        logger.warning({
            "event": "assignment_rejected",
            "ride_id": ride_id,
            "driver_id": driver_id,
            "reason": "Driver org mismatch"
        })
        raise ValueError("Driver must belong to the same organization as ride")

    _superseded_closed_markers = (
        "superseded",
        "duplicate",
        "terminal_ride",
        "terminal_reassignment",
        "orphaned",
        "executive_phase4",
        "sweep",
        "dropoff_complete",
        "dropoff_completed",
        "offer_timeout",
        "driver_rejected",
    )
    if (
        str(ride.driver_id or "") == str(driver.id)
        and not _ride_is_terminal(ride)
    ):
        existing_assignment = _latest_driver_assignment_for_ride(
            db,
            ride_id=str(ride.id),
            driver_id=str(driver.id),
        )
        existing_state = str(existing_assignment.assignment_state or "") if existing_assignment else ""
        existing_closed = str(getattr(existing_assignment, "closed_reason", "") or "").lower() if existing_assignment else ""
        if (
            existing_assignment
            and existing_state in {
                DispatchAssignmentState.OFFERED.value,
                DispatchAssignmentState.ASSIGNED.value,
                DispatchAssignmentState.ACCEPTED.value,
                DispatchAssignmentState.EN_ROUTE_PICKUP.value,
                DispatchAssignmentState.PICKUP_COMPLETE.value,
            }
            and not (existing_closed and any(marker in existing_closed for marker in _superseded_closed_markers))
        ):
            now_ts = now()
            existing_assignment.timeout_seconds = max(90, int(existing_assignment.timeout_seconds or 90))
            existing_assignment.offered_at = existing_assignment.offered_at or now_ts
            existing_assignment.offer_expires_at = now_ts + timedelta(seconds=existing_assignment.timeout_seconds)
            existing_assignment.assignment_state = DispatchAssignmentState.OFFERED.value
            existing_assignment.expired_at = None
            existing_assignment.closed_reason = None
            existing_assignment.updated_at = now_ts
            _expire_superseded_preaccept_offers_for_driver(
                db,
                driver_id=str(driver.id),
                keep_ride_id=str(ride.id),
                reason="superseded_by_direct_assignment",
            )
            sync_customer_request_from_ride(db, ride, explicit_status=CustomerRequestStatus.ASSIGNED.value)
            _commit_or_rollback(db)
            db.refresh(ride)
            logger.info({
                "event": "assignment_idempotent_refresh",
                "ride_id": ride_id,
                "driver_id": driver_id,
                "actor_user_id": actor_user_id,
            })
            return ride

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
    driver.availability_state = "available"
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
    _non_reusable_states = {
        DispatchAssignmentState.REJECTED.value,
        DispatchAssignmentState.DROPOFF_COMPLETE.value,
    }
    active_state = str(active_assignment.assignment_state or "") if active_assignment else ""
    closed_reason = str(getattr(active_assignment, "closed_reason", "") or "").lower() if active_assignment else ""
    must_create_new = (
        active_assignment is None
        or active_state in _non_reusable_states
        or (
            active_state in {
                DispatchAssignmentState.EXPIRED.value,
                DispatchAssignmentState.REASSIGNMENT_PENDING.value,
            }
            and closed_reason
            and any(marker in closed_reason for marker in _superseded_closed_markers)
        )
    )
    if must_create_new:
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
        db.flush()
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

    active_assignment.timeout_seconds = max(90, int(active_assignment.timeout_seconds or 90))
    active_assignment.offered_at = active_assignment.offered_at or now_ts
    active_assignment.offer_expires_at = now_ts + timedelta(seconds=active_assignment.timeout_seconds)
    active_assignment.expired_at = None
    active_assignment.closed_reason = None

    _expire_superseded_preaccept_offers_for_driver(
        db,
        driver_id=str(driver.id),
        keep_ride_id=str(ride.id),
        reason="superseded_by_direct_assignment",
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
    reconcile_ride_assignment_coherence(db, ride)
    db.refresh(ride)
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


def get_dashboard_metrics(db: Session, organization_id: str | None = None) -> DashboardMetrics:
    ride_query = db.query(HealthISFRide)
    driver_query = db.query(HealthISFDriver)
    payout_query = db.query(HealthISFPayout)
    trip_query = db.query(HealthISFTrip).filter(HealthISFTrip.status == TripStatus.COMPLETED)
    if organization_id:
        ride_query = ride_query.filter(HealthISFRide.organization_id == organization_id)
        driver_query = driver_query.filter(HealthISFDriver.organization_id == organization_id)
        org_driver_ids = [
            str(row[0])
            for row in db.query(HealthISFDriver.id).filter(HealthISFDriver.organization_id == organization_id).all()
        ]
        if org_driver_ids:
            payout_query = payout_query.filter(HealthISFPayout.driver_id.in_(org_driver_ids))
            trip_query = trip_query.filter(HealthISFTrip.driver_id.in_(org_driver_ids))
        else:
            payout_query = payout_query.filter(HealthISFPayout.driver_id.is_(None))
            trip_query = trip_query.filter(HealthISFTrip.driver_id.is_(None))

    rides = ride_query.all()
    drivers = driver_query.all()
    payouts = payout_query.all()
    completed_trips = trip_query.all()

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
        total_providers=db.query(HealthISFProvider).filter(
            HealthISFProvider.is_active == True,
            *(
                [HealthISFProvider.organization_id == organization_id]
                if organization_id
                else []
            ),
        ).count(),
        total_trips_completed=len(completed_trips),
        avg_driver_rating=round(avg_rating, 2),
        average_ride_duration_minutes=round(avg_duration, 2),
        cancellation_count=len(cancelled_rides),
        pending_payouts_usd=round(pending_payouts_usd, 2),
        total_payouts_usd=round(total_payouts_usd, 2),
        timestamp=now(),
    )
