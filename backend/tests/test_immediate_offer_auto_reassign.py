"""Auto-reassignment after immediate dispatch offer expiry."""
from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
    RideStatus,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _clear_driver(db, driver: HealthISFDriver) -> None:
    now_ts = hs.now()
    for ride in db.query(HealthISFRide).filter(HealthISFRide.driver_id == driver.id).all():
        if str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
            ride.status = RideStatus.CANCELLED.value
            ride.lifecycle_state = RideStatus.CANCELLED.value
            ride.updated_at = now_ts
    for assignment in db.query(HealthISFDispatchAssignment).filter(
        HealthISFDispatchAssignment.driver_id == driver.id
    ).all():
        assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
    driver.status = DriverStatus.AVAILABLE
    driver.availability_state = "available"
    driver.is_online = True
    driver.auth_state = "active"
    driver.last_seen_at = now_ts


def _prepare_two_drivers(org_id: str) -> tuple[str, str]:
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        drivers = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.is_active == True)
            .order_by(HealthISFDriver.name.asc())
            .limit(10)
            .all()
        )
        assert len(drivers) >= 2
        for driver in drivers[:2]:
            _clear_driver(db, driver)
        db.commit()
        return str(drivers[0].id), str(drivers[1].id)


def _create_immediate_ride(client: TestClient, org_id: str) -> str:
    rider = client.post(
        "/api/auth/login",
        json={"email": "rider@amicor.local", "password": SEED_PASSWORD},
    ).json()["access_token"]
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers={"Authorization": f"Bearer {rider}"},
        json={
            "rider_name": f"Auto Reassign {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Reassign Ave, New York, NY 10001",
            "dropoff_address": "20 Reassign Rd, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create.status_code == 201, create.text
    ride_id = create.json()["ride_id"]
    dispatcher = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    ).json()["access_token"]
    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{create.json()['id']}/approve",
        headers={"Authorization": f"Bearer {dispatcher}"},
    )
    assert approve.status_code == 200, approve.text
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        assert ride.organization_id == org_id
    return ride_id


def _active_offered_assignment(db, ride_id: str) -> HealthISFDispatchAssignment | None:
    return (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.ride_id == ride_id,
            HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
        )
        .order_by(HealthISFDispatchAssignment.created_at.desc())
        .first()
    )


def test_first_offer_expiry_creates_second_driver_offer(client: TestClient) -> None:
    org_id = _org_id()
    driver_a, driver_b = _prepare_two_drivers(org_id)
    ride_id = _create_immediate_ride(client, org_id)

    with SessionLocal() as db:
        first = _active_offered_assignment(db, ride_id)
        assert first is not None
        first_driver = str(first.driver_id)
        first_id = str(first.id)
        first.offer_expires_at = hs.now() - timedelta(seconds=30)
        db.commit()

        expired = hs.expire_stale_dispatch_offers(
            db,
            organization_id=org_id,
            ride_id=ride_id,
            auto_reassign_immediate=True,
        )
        assert len(expired) == 1
        db.refresh(first)
        assert str(first.assignment_state) == DispatchAssignmentState.REASSIGNMENT_PENDING.value

        offered = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
            )
            .all()
        )
        assert len(offered) == 1
        second = offered[0]
        assert str(second.id) != first_id
        assert str(second.driver_id) != first_driver
        assert str(second.driver_id) in {driver_a, driver_b}


def test_duplicate_reassign_is_idempotent(client: TestClient) -> None:
    org_id = _org_id()
    _prepare_two_drivers(org_id)
    ride_id = _create_immediate_ride(client, org_id)

    with SessionLocal() as db:
        first = _active_offered_assignment(db, ride_id)
        assert first is not None
        first.offer_expires_at = hs.now() - timedelta(minutes=1)
        db.commit()

        hs.expire_stale_dispatch_offers(
            db,
            organization_id=org_id,
            ride_id=ride_id,
            auto_reassign_immediate=True,
        )
        offered_after_first = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
            )
            .count()
        )
        assert offered_after_first == 1

        hs.expire_stale_dispatch_offers(
            db,
            organization_id=org_id,
            ride_id=ride_id,
            auto_reassign_immediate=True,
        )
        offered_after_second = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.OFFERED.value,
            )
            .count()
        )
        assert offered_after_second == 1


def test_second_driver_can_accept_after_auto_reassign(client: TestClient) -> None:
    org_id = _org_id()
    driver_a, driver_b = _prepare_two_drivers(org_id)
    ride_id = _create_immediate_ride(client, org_id)
    dispatcher = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {dispatcher}"}

    with SessionLocal() as db:
        first = _active_offered_assignment(db, ride_id)
        assert first is not None
        first.offer_expires_at = hs.now() - timedelta(seconds=5)
        db.commit()
        hs.expire_stale_dispatch_offers(
            db,
            organization_id=org_id,
            ride_id=ride_id,
            auto_reassign_immediate=True,
        )
        second = _active_offered_assignment(db, ride_id)
        assert second is not None
        second_driver = str(second.driver_id)

    accept = client.post(
        f"/api/health-isf/drivers/{second_driver}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

    with SessionLocal() as db:
        active = _active_offered_assignment(db, ride_id)
        assert active is None
        accepted = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.ACCEPTED.value,
            )
            .first()
        )
        assert accepted is not None
        assert str(accepted.driver_id) == second_driver
        assert str(accepted.driver_id) in {driver_a, driver_b}
