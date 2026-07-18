"""Platform JWT and driver operational session consistency."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
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


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_platform_login_me_and_dispatch_share_org_scope() -> None:
    client = _client()
    headers = _login(client, "dispatcher@amicor.local")
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    org_id = me.json()["organization_id"]
    queue = client.get("/api/health-isf/dispatch/queue", headers=headers, params={"limit": 20})
    assert queue.status_code == 200, queue.text
    assert isinstance(queue.json(), list)
    assert me.json()["organization_id"] == org_id


def test_driver_login_clears_stale_on_trip_without_active_assignment() -> None:
    client = _client()
    headers = _login(client, "dispatcher@amicor.local")
    with SessionLocal() as db:
        maria = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.name.ilike("Maria Garcia"))
            .first()
        )
        assert maria is not None
        maria.availability_state = "on_trip"
        maria.status = DriverStatus.EN_ROUTE_PICKUP
        maria.auth_state = "active"
        maria.is_online = True
        db.commit()
        driver_id = str(maria.id)
        phone = str(maria.phone)

    login = client.post(
        "/api/health-isf/drivers/login",
        headers=headers,
        json={"driver_id": driver_id, "phone": phone},
    )
    assert login.status_code == 200, login.text

    with SessionLocal() as db:
        refreshed = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        assert refreshed is not None
        assert str(refreshed.availability_state) == "available"
        assert hs._coerce_driver_status(refreshed.status) == DriverStatus.AVAILABLE
        assert hs._driver_active_workload_count(db, driver_id) == 0


def test_driver_login_succeeds_with_offer_pending_availability_and_active_assignment() -> None:
    client = _client()
    headers = _login(client, "dispatcher@amicor.local")
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.name.ilike("Test Driver Four"))
            .first()
        )
        assert driver is not None
        ride = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.driver_id == driver.id)
            .order_by(HealthISFRide.updated_at.desc())
            .first()
        )
        if ride is None:
            ride = HealthISFRide(
                id=hs.uuid4(),
                organization_id=driver.organization_id,
                passenger_name="Driver Four Login Proof",
                passenger_phone="646-555-9004",
                pickup_address="100 Proof Ave, New York, NY",
                dropoff_address="200 Clinic Rd, New York, NY",
                service_type="medical_transport",
                status=RideStatus.ASSIGNED.value,
                lifecycle_state=RideStatus.ASSIGNED.value,
                driver_id=driver.id,
            )
            db.add(ride)
            db.flush()
            assignment = HealthISFDispatchAssignment(
                id=hs.uuid4(),
                organization_id=driver.organization_id,
                ride_id=ride.id,
                driver_id=driver.id,
                assignment_state=DispatchAssignmentState.REASSIGNMENT_PENDING.value,
            )
            db.add(assignment)
        driver.availability_state = "offer_pending"
        driver.status = DriverStatus.ASSIGNED
        driver.auth_state = "active"
        driver.is_online = True
        db.commit()
        driver_id = str(driver.id)
        phone = str(driver.phone)
        ride_id = str(ride.id)

    login = client.post(
        "/api/health-isf/drivers/login",
        headers=headers,
        json={"driver_id": driver_id, "phone": phone},
    )
    assert login.status_code == 200, login.text
    assert login.json()["session_token"]

    active = client.get(f"/api/health-isf/drivers/{driver_id}/active-ride", headers=headers)
    assert active.status_code == 200, active.text
    payload = active.json()
    assert payload["has_active_ride"] is True
    assert (payload.get("ride") or {}).get("id") == ride_id

    with SessionLocal() as db:
        refreshed = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
        assert refreshed is not None
        assert str(refreshed.availability_state) == "available"
        assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.ride_id == ride_id,
                HealthISFDispatchAssignment.driver_id == driver_id,
            )
            .order_by(HealthISFDispatchAssignment.updated_at.desc())
            .first()
        )
        assert assignment is not None
        assert str(assignment.assignment_state) == DispatchAssignmentState.OFFERED.value
