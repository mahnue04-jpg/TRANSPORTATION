"""Shared driver/dispatch test isolation for health-isf acceptance tests."""
from __future__ import annotations

import time

from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFDriverLocationPing,
    HealthISFRide,
    HealthISFRideRoutePlan,
    RideStatus,
)

_DRIVER_TEST_RESET_MODULES = {
    "test_driver_accept_immediate_offer.py",
    "test_driver_app_authoritative_assignment.py",
    "test_driver_dispatch_lifecycle.py",
    "test_driver_mobile_assignment_sync.py",
    "test_immediate_offer_auto_reassign.py",
    "test_scheduled_route_activation.py",
    "test_multi_ride_driver_scheduling.py",
    "test_advance_scheduling.py",
    "test_driver_mobile_routing_lifecycle_guard.py",
    "test_sprint_a_day2_dispatch_contract.py",
    "test_sprint_a_day4_completion_contract.py",
    "test_operational_revenue_workflow_contract.py",
}


def driver_test_module_names() -> frozenset[str]:
    return frozenset(_DRIVER_TEST_RESET_MODULES)


def organization_id_for_dispatcher() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def drain_org_dispatch_queue(org_id: str) -> None:
    """Cancel unassigned queue rides so post-completion auto-assign does not pollute tests."""
    with SessionLocal() as db:
        queue = hs.get_dispatch_queue(db, organization_id=org_id, limit=200)
        now_ts = hs.now()
        for row in queue:
            ride_id = str(row.get("ride_id") or "")
            if not ride_id:
                continue
            ride = hs.get_ride_by_id(db, ride_id)
            if not ride or hs._ride_is_terminal(ride):
                continue
            if ride.driver_id:
                continue
            ride.status = RideStatus.CANCELLED.value
            ride.lifecycle_state = RideStatus.CANCELLED.value
            ride.updated_at = now_ts
            hs._close_active_assignments_for_ride(
                db,
                ride_id=ride_id,
                target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
                reason="test_queue_drain",
            )
        db.commit()


def _finalize_open_org_rides(db, org_id: str, now_ts) -> None:
    for ride in db.query(HealthISFRide).filter(HealthISFRide.organization_id == org_id).all():
        if hs._ride_is_terminal(ride):
            continue
        ride.status = RideStatus.COMPLETED.value
        ride.lifecycle_state = RideStatus.COMPLETED.value
        ride.completed_at = now_ts
        ride.updated_at = now_ts
        hs._close_active_assignments_for_ride(
            db,
            ride_id=str(ride.id),
            target_state=DispatchAssignmentState.DROPOFF_COMPLETE.value,
            reason="test_reset",
        )


def reset_organization_driver_test_state(
    org_id: str,
    *,
    driver_names: tuple[str, ...] = ("James Smith", "Maria Garcia"),
) -> None:
    """Reset seeded drivers and open rides so dispatch tests do not cross-pollute."""
    for _ in range(10):
        _reset_organization_driver_test_state_once(org_id, driver_names=driver_names)
        with SessionLocal() as db:
            open_rides = [
                ride
                for ride in db.query(HealthISFRide).filter(HealthISFRide.organization_id == org_id).all()
                if not hs._ride_is_terminal(ride)
            ]
            active_assignments = (
                db.query(HealthISFDispatchAssignment)
                .filter(
                    HealthISFDispatchAssignment.organization_id == org_id,
                    HealthISFDispatchAssignment.assignment_state.in_(
                        list(hs.ACTIVE_DISPATCH_ASSIGNMENT_STATES)
                    ),
                )
                .count()
            )
        if not open_rides and active_assignments == 0:
            return
        time.sleep(0.2)


def _reset_organization_driver_test_state_once(
    org_id: str,
    *,
    driver_names: tuple[str, ...],
) -> None:
    drain_org_dispatch_queue(org_id)
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        now_ts = hs.now()
        _finalize_open_org_rides(db, org_id, now_ts)
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.organization_id == org_id
        ).all():
            state = str(assignment.assignment_state or "")
            if state not in {
                DispatchAssignmentState.DROPOFF_COMPLETE.value,
                DispatchAssignmentState.REJECTED.value,
            }:
                assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
                assignment.closed_reason = "test_reset"
                assignment.updated_at = now_ts
        for name in driver_names:
            drivers = (
                db.query(HealthISFDriver)
                .filter(
                    HealthISFDriver.organization_id == org_id,
                    HealthISFDriver.name.ilike(name),
                )
                .all()
            )
            for driver in drivers:
                driver.status = DriverStatus.AVAILABLE
                driver.availability_state = "available"
                driver.is_active = True
                driver.is_online = True
                driver.auth_state = "active"
                driver.last_seen_at = now_ts
                driver.updated_at = now_ts
        db.commit()


def reset_scheduling_test_organization(org_id: str) -> None:
    """Clear open rides and normalize all drivers after scheduling tests."""
    with SessionLocal() as db:
        now_ts = hs.now()
        _finalize_open_org_rides(db, org_id, now_ts)
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.organization_id == org_id
        ).all():
            # Close leftover EXPIRED/open assignments in TEST isolation only so a
            # later accept is not blocked by shared-org assignment state.
            state = str(assignment.assignment_state or "")
            if state not in {
                DispatchAssignmentState.DROPOFF_COMPLETE.value,
                DispatchAssignmentState.REJECTED.value,
            }:
                assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
                assignment.closed_reason = "test_reset"
                assignment.updated_at = now_ts
        for driver in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all():
            driver.status = DriverStatus.AVAILABLE
            driver.availability_state = "available"
            driver.is_active = True
            driver.is_online = True
            driver.auth_state = "active"
            driver.last_seen_at = now_ts
            driver.updated_at = now_ts
        db.commit()


def close_competing_assignments_for_ride(ride_id: str, driver_id: str) -> None:
    """TEST-ONLY: close leftover auto-dispatch rows for other drivers on this ride.

    Immediate intake can leave a second awaiting_approval/offered assignment on the
    same ride. That leftover does not change production assignment rules; it only
    pollutes later Driver Mobile reads/progress in a shared test org.
    """
    with SessionLocal() as db:
        now_ts = hs.now()
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.ride_id == ride_id
        ).all():
            if str(assignment.driver_id or "") == str(driver_id):
                continue
            state = str(assignment.assignment_state or "")
            if state in {
                DispatchAssignmentState.DROPOFF_COMPLETE.value,
                DispatchAssignmentState.REJECTED.value,
            }:
                continue
            assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
            assignment.closed_reason = "test_competing_assignment_close"
            assignment.updated_at = now_ts
        db.commit()


def clear_routing_sidecar_test_artifacts(org_id: str) -> None:
    """TEST-ONLY: drop GPS pings, route plans, and geocode cache for one org."""
    with SessionLocal() as db:
        driver_ids = [
            str(row.id)
            for row in db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all()
        ]
        db.query(HealthISFRideRoutePlan).filter(HealthISFRideRoutePlan.organization_id == org_id).delete(
            synchronize_session=False
        )
        if driver_ids:
            db.query(HealthISFDriverLocationPing).filter(
                HealthISFDriverLocationPing.driver_id.in_(driver_ids)
            ).delete(synchronize_session=False)
        db.commit()


def prepare_driver(org_id: str, name: str = "James Smith") -> str:
    """Reset org driver state and return the requested driver id."""
    reset_organization_driver_test_state(org_id, driver_names=(name,))
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike(name))
            .first()
        )
        assert driver is not None
        return str(driver.id)


def ensure_ride_assigned_to_driver(
    client,
    *,
    dispatcher_headers: dict[str, str],
    admin_headers: dict[str, str] | None,
    request_id: str,
    ride_id: str,
    driver_id: str,
) -> None:
    """Assign or reassign a ride to the requested driver for deterministic tests."""
    ride_before = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before.status_code == 200, ride_before.text
    assigned_driver = str(ride_before.json().get("driver_id") or "")
    if assigned_driver != driver_id:
        assert admin_headers is not None, "admin headers required to assign auto-dispatched rides"
        reassign = client.post(
            "/api/health-isf/admin/reassign-driver",
            headers=admin_headers,
            json={"ride_id": ride_id, "driver_id": driver_id, "reason": "test_setup"},
        )
        assert reassign.status_code == 200, reassign.text
    close_competing_assignments_for_ride(ride_id, driver_id)
