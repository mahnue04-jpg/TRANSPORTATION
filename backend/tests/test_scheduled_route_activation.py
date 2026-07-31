"""Scheduled route activation: immediate Start Route after acceptance."""
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
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager
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
            phone=f"917{random.randint(1000000, 9999999)}",
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
    trip_leg: str = "return",
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
        trip_leg=trip_leg,
        pickup_time=pickup_time,
        arrival_time=pickup_time + timedelta(minutes=30),
    )
    db.add(ride)
    db.commit()
    db.refresh(ride)
    return ride


def test_scheduled_accepted_allows_immediate_start_route(client: TestClient):
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
        db.refresh(ride)
        assert is_route_start_eligible(ride)
        upcoming = list_upcoming_schedule_for_driver(
            db, organization_id=org_id, driver_id=driver_id
        )
        entry = next(item for item in upcoming if str(item["ride_id"]) == str(ride.id))
        assert entry["can_start_route"] is True
        assert "Start Route is available now" in str(entry.get("activation_message") or "")


def test_start_route_records_en_route_without_changing_pickup(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = service.now() + timedelta(hours=2)
    with SessionLocal() as db:
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        original_pickup = ride.pickup_time
        service.driver_en_route_pickup(db, driver_id=driver_id, ride_id=str(ride.id))
        db.refresh(ride)
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
        assert assignment.assignment_state == DispatchAssignmentState.EN_ROUTE_PICKUP.value
        assert assignment.en_route_pickup_at is not None
        assert ride.pickup_time == original_pickup
        assert ride.enroute_at is not None
        assert RideStatus.DRIVER_EN_ROUTE.value == RideLifecycleManager.normalize_state(
            ride.lifecycle_state or ride.status
        )


def test_early_arrival_allowed_without_auto_onboard(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = service.now() + timedelta(hours=4)
    with SessionLocal() as db:
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        service.driver_en_route_pickup(db, driver_id=driver_id, ride_id=str(ride.id))
        arrived = service.driver_arrived_pickup(db, driver_id=driver_id, ride_id=str(ride.id))
        assert arrived is not None
        db.refresh(arrived)
        lifecycle = RideLifecycleManager.normalize_state(
            arrived.lifecycle_state or arrived.status
        )
        assert lifecycle == RideStatus.ARRIVED.value
        assert lifecycle != RideStatus.RIDER_ONBOARD.value


def test_driver_mobile_does_not_auto_promote_future_reservation(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = datetime(2026, 7, 30, 23, 47, tzinfo=timezone.utc)
    now = datetime(2026, 7, 30, 22, 0, tzinfo=timezone.utc)
    with SessionLocal() as db, patch.object(service, "now", return_value=now):
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        snapshot = build_driver_mobile_read_snapshot(
            db,
            organization_id=org_id,
            driver_id=driver_id,
        )
        assert snapshot["has_active_ride"] is False
        assert any(
            str(item.get("ride_id")) == str(ride.id)
            for item in (snapshot.get("upcoming_schedule") or [])
        )


def test_repeated_start_route_is_idempotent(client: TestClient):
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    pickup = service.now() + timedelta(minutes=90)
    with SessionLocal() as db:
        ride = _create_scheduled_ride(db, organization_id=org_id, pickup_time=pickup)
        assign_driver_to_scheduled_ride(db, ride_id=str(ride.id), driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=str(ride.id))
        service.driver_en_route_pickup(db, driver_id=driver_id, ride_id=str(ride.id))
        before_events = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride.id)
            .count()
        )
        service.driver_en_route_pickup(db, driver_id=driver_id, ride_id=str(ride.id))
        after_events = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride.id)
            .count()
        )
        assert before_events == after_events
        db.refresh(ride)
        assert RideStatus.DRIVER_EN_ROUTE.value == RideLifecycleManager.normalize_state(
            ride.lifecycle_state or ride.status
        )


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
    with SessionLocal() as db:
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
