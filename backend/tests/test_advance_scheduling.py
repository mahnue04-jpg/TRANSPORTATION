"""Advance scheduling: reservations do not block immediate dispatch workload."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

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
from app.modules.health_isf.models import DispatchAssignmentState, DriverStatus, HealthISFDriver


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
            name=f"Advance Driver {uuid4()[:6]}",
            phone=f"917-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"AD-{uuid4()[:5].upper()}",
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


def _driver_session(client: TestClient, phone: str) -> tuple[str, dict[str, str]]:
    login = client.post("/api/health-isf/drivers/mobile-login", json={"phone": phone})
    assert login.status_code == 200, login.text
    body = login.json()
    return str(body["driver_id"]), {"X-Driver-Session-Token": str(body["session_token"])}


def _create_future_request(client: TestClient, headers: dict[str, str], suffix: str) -> str:
    pickup = datetime.now(timezone.utc) + timedelta(days=2)
    pickup = pickup.replace(hour=14, minute=30, second=0, microsecond=0)
    arrival = pickup + timedelta(hours=1)
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"advance_sched_{suffix}",
            "rider_phone": f"646555{''.join(ch for ch in suffix if ch.isdigit()).ljust(4, '0')[:4]}",
            "pickup_address": f"10 Advance Pickup {suffix}, NY",
            "dropoff_address": f"20 Advance Dropoff {suffix}, NY",
            "ride_type": "healthcare",
            "trip_type": "one_way",
            "service_date": pickup.date().isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json().get("ride_id") or "")


def test_future_reservation_does_not_increment_active_workload(client: TestClient) -> None:
    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    assert rider_auth.status_code == 200
    headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    driver_id = _ensure_driver(org_id)
    ride_id = _create_future_request(client, headers, uuid4()[:8])

    with SessionLocal() as db:
        _, offer = assign_driver_to_scheduled_ride(
            db,
            ride_id=ride_id,
            driver_id=driver_id,
            actor_user_id=None,
        )
        assert str(offer.assignment_state) == DispatchAssignmentState.SCHEDULED_OFFERED.value
        assert service._driver_active_workload_count(db, driver_id) == 0

        accept_scheduled_ride(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=None)
        assert service._driver_active_workload_count(db, driver_id) == 0
        ride = service.get_ride_by_id(db, ride_id)
        op = service.evaluate_driver_ride_operational_state(db, ride=ride, driver_id=driver_id)
        assert op.is_active is False
        assert op.reason == "scheduled_reservation"


def test_driver_upcoming_schedule_endpoint(client: TestClient) -> None:
    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    suffix = uuid4()[:8]
    driver_id = _ensure_driver(org_id)
    ride_id = _create_future_request(client, headers, suffix)

    with SessionLocal() as db:
        driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        assert driver is not None
        driver_phone = str(driver.phone)
        assign_driver_to_scheduled_ride(db, ride_id=ride_id, driver_id=driver_id)
        accept_scheduled_ride(db, driver_id=driver_id, ride_id=ride_id)
        upcoming = list_upcoming_schedule_for_driver(db, organization_id=org_id, driver_id=driver_id)
        assert any(str(row["ride_id"]) == ride_id for row in upcoming)

    _, driver_headers = _driver_session(client, driver_phone)
    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=driver_headers)
    assert active.status_code == 200, active.text
    body = active.json()
    assert body.get("has_active_ride") is False
    assert any(str(row.get("ride_id")) == ride_id for row in (body.get("upcoming_schedule") or []))
