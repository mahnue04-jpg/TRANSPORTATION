"""Scheduled ride ownership isolation across drivers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.advance_scheduling import (
    accept_scheduled_ride,
    assign_driver_to_scheduled_ride,
    list_upcoming_schedule_for_driver,
)
from app.modules.health_isf.models import DispatchAssignmentState, DriverStatus, HealthISFDispatchAssignment, HealthISFDriver


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


def _ensure_driver(organization_id: str, *, phone: str | None = None) -> str:
    digits = "".join(ch for ch in str(phone or uuid4()) if ch.isdigit())[:10]
    if len(digits) < 10:
        digits = f"917555{digits[:4].ljust(4, '0')}"
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Owner Driver {digits[-4:]}",
            phone=digits,
            vehicle_type="sedan",
            vehicle_plate=f"OW-{uuid4()[:5].upper()}",
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


def _create_future_request(client: TestClient, headers: dict[str, str], suffix: str) -> str:
    pickup = datetime.now(timezone.utc) + timedelta(days=3)
    pickup = pickup.replace(hour=10, minute=0, second=0, microsecond=0)
    arrival = pickup + timedelta(hours=1)
    created = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"owner_sched_{suffix}",
            "rider_phone": f"646555{''.join(ch for ch in suffix if ch.isdigit()).ljust(4, '0')[:4]}",
            "pickup_address": f"10 Owner Pickup {suffix}, NY",
            "dropoff_address": f"20 Owner Dropoff {suffix}, NY",
            "ride_type": "healthcare",
            "trip_type": "one_way",
            "service_date": pickup.date().isoformat(),
            "pickup_time": pickup.isoformat(),
            "arrival_time": arrival.isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json().get("ride_id") or "")


def _driver_session(client: TestClient, phone: str) -> tuple[str, dict[str, str]]:
    login = client.post("/api/health-isf/drivers/mobile-login", json={"phone": phone})
    assert login.status_code == 200, login.text
    body = login.json()
    return str(body["driver_id"]), {"X-Driver-Session-Token": str(body["session_token"])}


def test_accept_expires_competing_driver_scheduled_offer(client: TestClient) -> None:
    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    suffix = uuid4()[:8]
    digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(8, "0")[:8]
    phone_a = f"917555{digits[:4]}"
    phone_b = f"917556{digits[4:8]}"
    driver_a = _ensure_driver(org_id, phone=phone_a)
    driver_b = _ensure_driver(org_id, phone=phone_b)
    ride_id = _create_future_request(client, headers, suffix)

    with SessionLocal() as db:
        assign_driver_to_scheduled_ride(db, ride_id=ride_id, driver_id=driver_a)
        assign_driver_to_scheduled_ride(db, ride_id=ride_id, driver_id=driver_b)
        accept_scheduled_ride(db, driver_id=driver_a, ride_id=ride_id)
        b_rows = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.driver_id == driver_b,
            )
            .all()
        )
        assert b_rows
        assert all(str(row.assignment_state) == "expired" for row in b_rows)
        upcoming_b = list_upcoming_schedule_for_driver(db, organization_id=org_id, driver_id=driver_b)
        assert not any(str(row["ride_id"]) == ride_id for row in upcoming_b)
        upcoming_a = list_upcoming_schedule_for_driver(db, organization_id=org_id, driver_id=driver_a)
        assert any(str(row["ride_id"]) == ride_id for row in upcoming_a)
        assert any(
            str(row.get("assignment_state")) == DispatchAssignmentState.SCHEDULED_ACCEPTED.value
            for row in upcoming_a
        )


def test_cross_driver_cannot_accept_reserved_scheduled_ride(client: TestClient) -> None:
    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    suffix = uuid4()[:8]
    digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(8, "0")[:8]
    phone_a = f"917557{digits[:4]}"
    phone_b = f"917558{digits[4:8]}"
    driver_a = _ensure_driver(org_id, phone=phone_a)
    driver_b = _ensure_driver(org_id, phone=phone_b)
    ride_id = _create_future_request(client, headers, suffix)

    with SessionLocal() as db:
        assign_driver_to_scheduled_ride(db, ride_id=ride_id, driver_id=driver_a)
        accept_scheduled_ride(db, driver_id=driver_a, ride_id=ride_id)

    _, headers_b = _driver_session(client, phone_b)
    denied = client.post(
        f"/api/health-isf/drivers/{driver_b}/accept-scheduled-ride",
        headers=headers_b,
        json={"ride_id": ride_id},
    )
    assert denied.status_code in {400, 403}, denied.text


def test_active_ride_upcoming_schedule_is_driver_scoped(client: TestClient) -> None:
    rider_auth = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    headers = {"Authorization": f"Bearer {rider_auth.json()['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    suffix = uuid4()[:8]
    digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(8, "0")[:8]
    phone_a = f"917559{digits[:4]}"
    phone_b = f"917560{digits[4:8]}"
    driver_a = _ensure_driver(org_id, phone=phone_a)
    driver_b = _ensure_driver(org_id, phone=phone_b)
    ride_id = _create_future_request(client, headers, suffix)

    with SessionLocal() as db:
        assign_driver_to_scheduled_ride(db, ride_id=ride_id, driver_id=driver_a)
        accept_scheduled_ride(db, driver_id=driver_a, ride_id=ride_id)

    _, headers_a = _driver_session(client, phone_a)
    _, headers_b = _driver_session(client, phone_b)
    active_a = client.get(f"/api/health-isf/drivers/{driver_a}/active-ride", headers=headers_a)
    active_b = client.get(f"/api/health-isf/drivers/{driver_b}/active-ride", headers=headers_b)
    assert active_a.status_code == 200
    assert active_b.status_code == 200
    ids_a = {str(row.get("ride_id")) for row in (active_a.json().get("upcoming_schedule") or [])}
    ids_b = {str(row.get("ride_id")) for row in (active_b.json().get("upcoming_schedule") or [])}
    assert ride_id in ids_a
    assert ride_id not in ids_b
