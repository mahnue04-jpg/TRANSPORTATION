"""Scheduled route activation at pickup minus lead minutes."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service
from app.modules.health_isf.advance_scheduling import (
    accept_scheduled_ride,
    assign_driver_to_scheduled_ride,
    list_upcoming_schedule_for_driver,
    promote_scheduled_reservations_for_driver,
)
from app.modules.health_isf.driver_mobile_read_path import build_driver_mobile_read_snapshot
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.scheduling import (
    apply_scheduling_fields_to_ride,
    is_route_start_eligible,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _ensure_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Route Driver {uuid4()[:6]}",
            phone=f"917555{random.randint(1000, 9999)}",
            vehicle_type="sedan",
            vehicle_plate=f"RT-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_scheduled_ride(
    db,
    *,
    organization_id: str,
    pickup_time: datetime,
    passenger_name: str = "Route Activation Rider",
) -> HealthISFRide:
    ride = HealthISFRide(
        id=uuid4(),
        organization_id=organization_id,
        passenger_name=passenger_name,
        passenger_phone="6465550101",
        pickup_address="100 Route Pickup",
        dropoff_address="200 Route Dropoff",
        service_type="healthcare",
        status=RideStatus.PENDING,
        lifecycle_state="scheduled",
        requested_at=service.now(),
    )
    apply_scheduling_fields_to_ride(
        ride,
        trip_leg="return",
        pickup_time=pickup_time,
        arrival_time=pickup_time + timedelta(minutes=30),
    )
    db.add(ride)
    db.commit()
    db.refresh(ride)
    return ride


def test_scheduled_ride_visible_more_than_60_minutes_before_pickup(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = service.now() + timedelta(hours=3)
    with SessionLocal() as db:
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(
            db,
            ride_id=str(ride.id),
            driver_id=driver_id,
            actor_user_id=None,
        )
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        upcoming = list_upcoming_schedule_for_driver(
            db, organization_id=org_id, driver_id=driver_id
        )
        assert any(str(item["ride_id"]) == str(ride.id) for item in upcoming)
        assert not is_route_start_eligible(ride)


def test_activation_exactly_60_minutes_before_pickup(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    now = datetime(2026, 7, 30, 22, 47, tzinfo=timezone.utc)  # 5:47 PM Chicago CDT
    pickup = datetime(2026, 7, 30, 23, 47, tzinfo=timezone.utc)  # 6:47 PM Chicago CDT
    with SessionLocal() as db, patch.object(service, "now", return_value=now):
        ride = _create_scheduled_ride(
            db,
            organization_id=org_id,
            pickup_time=pickup,
            passenger_name="jack doe",
        )
        assign_driver_to_scheduled_ride(
            db,
            ride_id=str(ride.id),
            driver_id=driver_id,
            actor_user_id=None,
        )
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        db.refresh(ride)
        assert is_route_start_eligible(ride, at=now)
        activated = promote_scheduled_reservations_for_driver(
            db,
            organization_id=org_id,
            driver_id=driver_id,
        )
        assert len(activated) == 1
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride.id,
                HealthISFDispatchAssignment.driver_id == driver_id,
            )
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assert assignment.assignment_state == DispatchAssignmentState.ACCEPTED.value
        upcoming = list_upcoming_schedule_for_driver(
            db, organization_id=org_id, driver_id=driver_id
        )
        assert not any(str(item["ride_id"]) == str(ride.id) for item in upcoming)


def test_driver_mobile_poll_promotes_missed_window(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    now = datetime(2026, 7, 30, 23, 10, tzinfo=timezone.utc)
    pickup = datetime(2026, 7, 30, 23, 47, tzinfo=timezone.utc)
    with SessionLocal() as db, patch.object(service, "now", return_value=now):
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(
            db, ride_id=str(ride.id), driver_id=driver_id
        )
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        promote_scheduled_reservations_for_driver(
            db, organization_id=org_id, driver_id=driver_id
        )
        snapshot = build_driver_mobile_read_snapshot(
            db,
            organization_id=org_id,
            driver_id=driver_id,
        )
        assert snapshot["has_active_ride"] is True
        assert snapshot["ride"] is not None
        assert str(snapshot["ride"].id) == str(ride.id)


def test_repeated_polling_is_idempotent(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    now = datetime(2026, 7, 30, 23, 0, tzinfo=timezone.utc)
    pickup = datetime(2026, 7, 30, 23, 47, tzinfo=timezone.utc)
    with SessionLocal() as db, patch.object(service, "now", return_value=now):
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        first = promote_scheduled_reservations_for_driver(
            db, organization_id=org_id, driver_id=driver_id
        )
        second = promote_scheduled_reservations_for_driver(
            db, organization_id=org_id, driver_id=driver_id
        )
        assert len(first) == 1
        assert len(second) == 0
        active_count = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride.id,
                HealthISFDispatchAssignment.assignment_state
                == DispatchAssignmentState.ACCEPTED.value,
            )
            .count()
        )
        assert active_count == 1


def test_accept_scheduled_reservation_is_idempotent(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = service.now() + timedelta(hours=2)
    with SessionLocal() as db:
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        ride_result, already = service.accept_driver_ride(
            db, driver_id=driver_id, ride_id=str(ride.id)
        )
        assert ride_result is not None
        assert already is True


def test_accept_resolves_assignment_id(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = service.now() + timedelta(minutes=20)
    with SessionLocal() as db, patch.object(service, "now", return_value=service.now()):
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accepted_assignment = accept_scheduled_ride(
            db, driver_id=driver_id, ride_id=str(ride.id)
        )
        ride_result, already = service.accept_driver_ride(
            db, driver_id=driver_id, ride_id=str(accepted_assignment.id)
        )
        assert ride_result is not None
        assert str(ride_result.id) == str(ride.id)
        assert already is True
