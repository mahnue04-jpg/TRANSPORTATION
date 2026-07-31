"""Driver accept for immediate offers (including rides with scheduling_summary metadata)."""
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
from app.modules.health_isf.models import DispatchAssignmentState, HealthISFDispatchAssignment


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _prepare_driver(org_id: str) -> str:
    from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFRide, RideStatus

    with SessionLocal() as db:
        queue = hs.get_dispatch_queue(db, organization_id=org_id, limit=200)
        now_ts = hs.now()
        for row in queue:
            ride_id = str(row.get("ride_id") or "")
            ride = hs.get_ride_by_id(db, ride_id) if ride_id else None
            if not ride or hs._ride_is_terminal(ride) or ride.driver_id:
                continue
            ride.status = RideStatus.CANCELLED.value
            ride.lifecycle_state = RideStatus.CANCELLED.value
            ride.updated_at = now_ts
        db.commit()
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=org_id)
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike("James Smith"))
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
        driver.status = DriverStatus.AVAILABLE
        driver.availability_state = "available"
        driver.is_online = True
        driver.auth_state = "active"
        driver.last_seen_at = now_ts
        db.commit()
        return str(driver.id)


def _create_and_assign(
    client: TestClient,
    dispatcher_headers: dict[str, str],
    rider_headers: dict[str, str],
    driver_id: str,
) -> str:
    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Accept Immediate {suffix}",
            "rider_phone": f"646-555-{phone_digits}",
            "pickup_address": "10 Accept Ave, New York, NY 10001",
            "dropoff_address": "20 Accept Rd, New York, NY 10002",
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
    from tests.health_isf_driver_test_helpers import ensure_ride_assigned_to_driver

    admin_headers = _headers(
        client.post("/api/auth/login", json={"email": "admin@amicor.local", "password": SEED_PASSWORD}).json()[
            "access_token"
        ]
    )
    ensure_ride_assigned_to_driver(
        client,
        dispatcher_headers=dispatcher_headers,
        admin_headers=admin_headers,
        request_id=request_id,
        ride_id=ride_id,
        driver_id=driver_id,
    )
    return ride_id


def test_immediate_offer_accept_with_scheduling_summary(client: TestClient) -> None:
    org_id = _org_id()
    driver_id = _prepare_driver(org_id)
    dispatcher_headers = _headers(
        client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD}).json()[
            "access_token"
        ]
    )
    rider_headers = _headers(
        client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD}).json()[
            "access_token"
        ]
    )
    ride_id = _create_and_assign(client, dispatcher_headers, rider_headers, driver_id)

    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        ride.scheduling_summary = "Immediate ride"
        db.commit()

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["id"] == ride_id
    assert str(body.get("assignment_state") or "").lower() == DispatchAssignmentState.ACCEPTED.value

    active = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-ride",
        headers=dispatcher_headers,
    )
    assert active.status_code == 200, active.text
    assert active.json()["has_active_ride"] is True
    assert str(active.json().get("assignment_state") or "").lower() == DispatchAssignmentState.ACCEPTED.value

    with SessionLocal() as db:
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.driver_id == driver_id,
                HealthISFDispatchAssignment.assignment_state == DispatchAssignmentState.ACCEPTED.value,
            )
            .first()
        )
        assert assignment is not None
        assert str(assignment.assignment_state) == DispatchAssignmentState.ACCEPTED.value

    scheduled = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-scheduled-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert scheduled.status_code in {200, 400}
    if scheduled.status_code == 400:
        assert "scheduled offer" in scheduled.json().get("detail", "").lower()
