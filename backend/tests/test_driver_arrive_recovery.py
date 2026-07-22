"""Driver mobile arrive action: en_route fallback, idempotent recovery, stale ride rejection."""
from __future__ import annotations

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
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            return str(provider.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Arrive Provider {uuid4()[:6]}",
            address="500 Arrive Avenue",
            phone="212-555-0800",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _prepare_driver(org_id: str, phone: str = "917-555-1001") -> str:
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.phone == phone)
            .first()
        )
        assert driver is not None
        now_ts = hs.now()
        for ride in db.query(HealthISFRide).filter(HealthISFRide.driver_id == driver.id).all():
            if str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                ride.status = RideStatus.COMPLETED.value
                ride.lifecycle_state = RideStatus.COMPLETED.value
                ride.completed_at = now_ts
        for assignment in db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.driver_id == driver.id
        ).all():
            assignment.assignment_state = DispatchAssignmentState.DROPOFF_COMPLETE.value
            assignment.closed_reason = "arrive_recovery_test_cleanup"
        driver.status = DriverStatus.AVAILABLE
        db.commit()
        return str(driver.id)


def _driver_session(client: TestClient, phone: str = "917-555-1001") -> tuple[str, dict]:
    response = client.post("/api/health-isf/drivers/mobile-login", json={"phone": phone})
    assert response.status_code == 200, response.text
    body = response.json()
    driver_id = str(body["driver_id"])
    headers = {"X-Driver-Session-Token": body["session_token"]}
    return driver_id, headers


def _create_assign_accept(
    client: TestClient,
    dispatcher_headers: dict,
    rider_headers: dict,
    driver_id: str,
    driver_headers: dict,
    label: str,
) -> str:
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Arrive Rider {label} {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": f"100 Pickup {suffix}, New York, NY",
            "dropoff_address": f"200 Dropoff {suffix}, New York, NY",
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
    assert assign.status_code == 200, assign.text

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=driver_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text
    return ride_id


def test_arrive_after_accept_without_explicit_en_route(client: TestClient) -> None:
    dispatcher_headers = {"Authorization": f"Bearer {_login(client, 'dispatcher@amicor.local')['access_token']}"}
    rider_headers = {"Authorization": f"Bearer {_login(client, 'rider@amicor.local')['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _prepare_driver(org_id)
    _, driver_headers = _driver_session(client)
    ride_id = _create_assign_accept(
        client,
        dispatcher_headers,
        rider_headers,
        driver_id,
        driver_headers,
        "accept-only",
    )

    arrive = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=driver_headers,
        json={"ride_id": ride_id, "target_state": "arrived_pickup"},
    )
    assert arrive.status_code == 200, arrive.text
    active_ride = arrive.json().get("active_ride") or {}
    assert str(active_ride.get("id") or active_ride.get("ride_id") or "") == ride_id
    assert str(active_ride.get("lifecycle_state") or active_ride.get("status") or "").lower() in {
        "arrived",
        "accepted",
    }


def test_arrive_is_idempotent_when_already_arrived(client: TestClient) -> None:
    dispatcher_headers = {"Authorization": f"Bearer {_login(client, 'dispatcher@amicor.local')['access_token']}"}
    rider_headers = {"Authorization": f"Bearer {_login(client, 'rider@amicor.local')['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _prepare_driver(org_id)
    _, driver_headers = _driver_session(client)
    ride_id = _create_assign_accept(
        client,
        dispatcher_headers,
        rider_headers,
        driver_id,
        driver_headers,
        "idempotent",
    )

    first = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=driver_headers,
        json={"ride_id": ride_id, "target_state": "arrived_pickup"},
    )
    assert first.status_code == 200, first.text

    second = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=driver_headers,
        json={"ride_id": ride_id, "target_state": "arrived_pickup"},
    )
    assert second.status_code == 200, second.text


def test_arrive_rejects_stale_ride_after_driver_unassigned(client: TestClient) -> None:
    dispatcher_headers = {"Authorization": f"Bearer {_login(client, 'dispatcher@amicor.local')['access_token']}"}
    rider_headers = {"Authorization": f"Bearer {_login(client, 'rider@amicor.local')['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _prepare_driver(org_id)
    _, driver_headers = _driver_session(client)
    ride_id = _create_assign_accept(
        client,
        dispatcher_headers,
        rider_headers,
        driver_id,
        driver_headers,
        "stale",
    )

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert ride is not None
        ride.driver_id = None
        ride.lifecycle_state = RideStatus.CANCELLED.value
        ride.status = RideStatus.CANCELLED.value
        db.commit()

    arrive = client.post(
        f"/api/health-isf/drivers/{driver_id}/route-progress",
        headers=driver_headers,
        json={"ride_id": ride_id, "target_state": "arrived_pickup"},
    )
    assert arrive.status_code in {400, 409}, arrive.text
    assert "driver" in arrive.text.lower() or "lifecycle" in arrive.text.lower() or "cancel" in arrive.text.lower()
