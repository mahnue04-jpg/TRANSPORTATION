"""Driver + dispatch production lifecycle: every driver action through completion."""
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
    HealthISFDriverSession,
    HealthISFRide,
    HealthISFProvider,
    HealthISFTrip,
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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _reseed_james(organization_id: str) -> str:
    with SessionLocal() as db:
        hs.ensure_sample_driver_credentials(db, organization_id=organization_id)
        james = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == organization_id,
                HealthISFDriver.name.ilike("James Smith"),
            )
            .order_by(HealthISFDriver.updated_at.desc())
            .first()
        )
        assert james is not None
        now_ts = hs.now()
        james_rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.driver_id == james.id)
            .all()
        )
        for ride in james_rides:
            if str(ride.status) not in {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value}:
                ride.status = RideStatus.COMPLETED
                ride.lifecycle_state = RideStatus.COMPLETED.value
                ride.completed_at = now_ts
                ride.updated_at = now_ts
        open_assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(
                HealthISFDispatchAssignment.driver_id == james.id,
                HealthISFDispatchAssignment.assignment_state.in_(list(hs.ACTIVE_DISPATCH_ASSIGNMENT_STATES)),
            )
            .all()
        )
        for assignment in open_assignments:
            assignment.assignment_state = DispatchAssignmentState.REASSIGNMENT_PENDING.value
            assignment.updated_at = now_ts
        james.status = DriverStatus.AVAILABLE
        james.availability_state = "available"
        james.is_active = True
        james.is_online = True
        james.auth_state = "active"
        james.last_seen_at = now_ts
        james.updated_at = now_ts
        db.commit()
        db.refresh(james)
        return str(james.id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            if not provider.is_active:
                provider.is_active = True
                db.commit()
            return str(provider.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Driver Lifecycle Provider {uuid4()[:6]}",
            address="500 Driver Lifecycle Avenue",
            phone="212-555-0700",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def test_full_driver_dispatch_lifecycle_all_actions(client: TestClient) -> None:
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _reseed_james(org_id)

    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = _headers(rider_auth["access_token"])
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = _headers(dispatcher_auth["access_token"])
    admin_auth = _login(client, "admin@amicor.local")
    admin_headers = _headers(admin_auth["access_token"])

    suffix = uuid4()[:8]
    phone_digits = "".join(ch for ch in suffix if ch.isdigit()).ljust(4, "0")[:4]
    rider_phone = f"646-555-{phone_digits}"

    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Driver Lifecycle {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"100 Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "driver dispatch lifecycle test",
        },
    )
    assert create.status_code == 201, create.text
    request_row = create.json()
    request_id = request_row["id"]
    ride_id = request_row["ride_id"]

    queue = client.get("/api/health-isf/dispatch/queue", headers=dispatcher_headers, params={"limit": 200})
    assert queue.status_code == 200
    assert any(row.get("ride_id") == ride_id for row in queue.json())

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    ride_before_assign = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride_before_assign.status_code == 200, ride_before_assign.text
    if str(ride_before_assign.json().get("driver_id") or "") != driver_id:
        assign = client.post(
            f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
            headers=dispatcher_headers,
            json={"driver_id": driver_id},
        )
        assert assign.status_code == 200, assign.text

    offer = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=dispatcher_headers)
    assert offer.status_code == 200, offer.text
    assert (offer.json().get("offer") or {}).get("ride_id") == ride_id

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=dispatcher_headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

    contact = client.post(
        f"/api/health-isf/drivers/{driver_id}/contact-rider",
        headers=dispatcher_headers,
        json={"ride_id": ride_id, "channel": "sms"},
    )
    assert contact.status_code == 200, contact.text

    for target_state in (
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "completed",
    ):
        step = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert step.status_code == 200, f"{target_state}: {step.text}"

    ride = client.get(f"/api/health-isf/rides/{ride_id}", headers=dispatcher_headers)
    assert ride.status_code == 200, ride.text
    ride_payload = ride.json()
    assert str(ride_payload.get("lifecycle_state") or ride_payload.get("status")).lower() == "completed"

    rider_history = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=rider_headers,
        params={"rider_phone": rider_phone, "limit": 20},
    )
    assert rider_history.status_code == 200
    assert any(row.get("ride_id") == ride_id for row in rider_history.json().get("history", []))

    dashboard_before = client.get("/api/health-isf/dashboard", headers=dispatcher_headers)
    assert dashboard_before.status_code == 200

    audit = client.get("/api/health-isf/dispatcher/audit-log", headers=admin_headers, params={"limit": 50})
    assert audit.status_code == 200, audit.text

    with SessionLocal() as db:
        persisted = hs.get_ride_by_id(db, ride_id)
        assert persisted is not None
        assert str(persisted.lifecycle_state or persisted.status).lower() == "completed"
        trip = (
            db.query(HealthISFTrip)
            .filter(HealthISFTrip.ride_id == ride_id)
            .order_by(HealthISFTrip.created_at.desc())
            .first()
        )
        assert trip is not None
