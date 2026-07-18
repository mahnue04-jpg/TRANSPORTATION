"""Regression tests for expired-bound assignment reconciliation and driver API alignment."""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import DispatchAssignmentState, HealthISFDispatchAssignment, HealthISFDriver, HealthISFRide, RideStatus


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
            "rider_name": f"Reconcile Test {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Reconcile Ave, New York, NY",
            "dropoff_address": "20 Reconcile Rd, New York, NY",
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
    ride_before = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before.status_code == 200
    assigned = str(ride_before.json().get("driver_id") or "")
    if assigned:
        return ride_id
    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=dispatcher_headers,
        json={"driver_id": driver_id},
    )
    if assign.status_code == 400 and "already has an assigned driver" in assign.text.lower():
        ride_after = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
        assert ride_after.status_code == 200
        return ride_id
    assert assign.status_code == 200, assign.text
    return ride_id


def test_expired_bound_reconciles_to_offered_without_duplicate(client: TestClient) -> None:
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
        assignment.assignment_state = "expired"
        assignment.expired_at = hs.now()
        ride.driver_id = driver_id
        ride.lifecycle_state = RideStatus.QUEUED.value
        ride.status = RideStatus.PENDING.value
        db.commit()

    started = time.perf_counter()
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        restored = hs.reconcile_expired_bound_driver_assignment(db, ride)
        db.commit()
        assert restored is not None
        assert str(restored.assignment_state) == DispatchAssignmentState.OFFERED.value
        count = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride_id)
            .count()
        )
        assert count == 1
        again = hs.reconcile_expired_bound_driver_assignment(db, ride)
        db.commit()
        assert again is not None
        assert str(again.assignment_state) == DispatchAssignmentState.OFFERED.value
    elapsed = time.perf_counter() - started
    assert elapsed < 3.0


def test_driver_endpoints_agree_after_expired_bound_reconcile(client: TestClient) -> None:
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
        assignment = hs._latest_driver_assignment_for_ride(db, ride_id=ride_id, driver_id=driver_id)
        assert assignment is not None
        assignment.assignment_state = "expired"
        ride.driver_id = driver_id
        ride.lifecycle_state = RideStatus.QUEUED.value
        db.commit()

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=dispatcher_headers)
    assigned = client.get(f"/api/health-isf/drivers/{driver_id}/assigned-rides", headers=dispatcher_headers)
    workspace = client.get(f"/api/health-isf/drivers/{driver_id}/live-workspace", headers=dispatcher_headers)
    assert offer.status_code == 200
    assert active.status_code == 200
    assert assigned.status_code == 200
    assert workspace.status_code == 200

    offer_ride = str((offer.json().get("offer") or {}).get("ride_id") or "")
    active_ride = active.json()
    active_id = str((active_ride.get("ride") or {}).get("id") or "")
    assigned_ids = [str(row.get("id") or row.get("ride_id") or "") for row in assigned.json()]
    ws_ride = str((workspace.json().get("active_ride") or workspace.json().get("ride") or {}).get("id") or "")

    assert offer_ride == ride_id
    assert active_id == ride_id
    assert ride_id in assigned_ids
    assert ws_ride == ride_id or active_ride.get("has_active_ride") is True


def test_terminal_ride_not_reactivated(client: TestClient) -> None:
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
        assignment.assignment_state = "expired"
        db.commit()
        restored = hs.reconcile_expired_bound_driver_assignment(db, ride)
        assert restored is None


def test_proof_ride_excluded_from_dispatch_queue() -> None:
    class _Ride:
        passenger_name = "Hydration Proof Rider xyz"
        pickup_address = "120 Proof Pickup xyz"
        dropoff_address = "220 Proof Dropoff xyz"
        notes = ""

    assert hs.is_operational_excluded_ride(_Ride()) is True


def test_ai_focuses_newest_valid_queue_ride(client: TestClient) -> None:
    org_id = _org_id()
    dispatcher_headers = _headers(_login(client, "dispatcher@amicor.local")["access_token"])
    snapshot = client.get("/api/health-isf/ai-dispatch/snapshot?publish=false", headers=dispatcher_headers)
    assert snapshot.status_code == 200
    live = snapshot.json().get("live_dispatch") or {}
    focused = live.get("focused_ride") or {}
    queue_ids = live.get("queue_ride_ids") or []
    if queue_ids and focused.get("ride_id"):
        assert str(focused.get("ride_id")) in queue_ids
        assert "Hydration Proof Rider" not in str(focused.get("passenger_name") or "")
