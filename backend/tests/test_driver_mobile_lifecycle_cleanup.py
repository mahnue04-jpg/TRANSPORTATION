"""Regression tests: completed/cancelled rides must not reappear on Driver Mobile."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import DispatchAssignmentState, HealthISFDispatchAssignment, HealthISFDriver, RideStatus


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user and user.organization_id
        return str(user.organization_id)


def _driver_by_name(org_id: str, name: str) -> HealthISFDriver:
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike(name))
            .first()
        )
        assert driver is not None
        return driver


def _create_ride(client: TestClient, rider_headers: dict[str, str], dispatcher_headers: dict[str, str], driver_id: str) -> str:
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Lifecycle Cleanup {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Cleanup Ave, New York, NY",
            "dropoff_address": "20 Cleanup Rd, New York, NY",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create.status_code == 201, create.text
    request_id = create.json()["id"]
    ride_id = create.json()["ride_id"]
    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text
    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=dispatcher_headers,
        json={"driver_id": driver_id},
    )
    if assign.status_code not in {200, 400}:
        assert assign.status_code == 200, assign.text
    return ride_id


def test_completed_reassignment_pending_closed_on_driver_read(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_ride(client, rider_headers, dispatcher_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        driver_id = str(ride.driver_id or driver_id)
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        ride.lifecycle_state = RideStatus.COMPLETED.value
        ride.status = RideStatus.COMPLETED.value
        ride.completed_at = hs.now()
        assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
        db.commit()

    with SessionLocal() as db:
        hs.get_driver_live_workspace_data(db, organization_id=org_id, driver_id=driver_id)
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assert str(assignment.assignment_state) == DispatchAssignmentState.DROPOFF_COMPLETE.value

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=dispatcher_headers)
    assert offer.status_code == 200
    assert active.status_code == 200
    assert assigned.status_code == 200
    assert str((offer.json().get("offer") or {}).get("ride_id") or "") != ride_id
    assert str((active.json().get("ride") or {}).get("id") or "") != ride_id
    assert ride_id not in [str(row.get("id") or row.get("ride_id") or "") for row in assigned.json()]


def test_completed_ride_history_preserved_after_cleanup(client: TestClient) -> None:
    org_id = _org_id()
    driver = _driver_by_name(org_id, "Test Driver Four")
    driver_id = str(driver.id)
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    rider_headers = _headers(_login(client, "rider@amicor.local")["access_token"])
    ride_id = _create_ride(client, rider_headers, dispatcher_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        ride.lifecycle_state = RideStatus.COMPLETED.value
        ride.status = RideStatus.COMPLETED.value
        ride.completed_at = hs.now()
        ride.driver_id = driver_id
        db.commit()

    snapshot = client.get(
        f"/api/health-isf/drivers/{driver_id}/completion-snapshot",
        headers=dispatcher_headers,
    )
    assert snapshot.status_code == 200
    completed_ids = [
        str(row.get("id") or row.get("ride_id") or "")
        for row in (snapshot.json().get("completed_rides") or [])
    ]
    assert ride_id in completed_ids
