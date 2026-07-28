"""End-to-end rider app workflow: request → dispatcher queue → assign → driver offer."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFProvider


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
            name=f"Rider Flow Provider {uuid4()[:6]}",
            address="500 Rider Flow Avenue",
            phone="212-555-0600",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_available_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Rider Flow Driver {uuid4()[:6]}",
            phone=f"917-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"RF-{uuid4()[:5].upper()}",
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


def test_rider_role_creates_customer_request_and_dispatcher_sees_it(client: TestClient) -> None:
    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    rider_org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(rider_org_id)
    rider_phone = "+1 646-555-7788"
    suffix = uuid4()[:8]

    create_resp = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Saye Rider {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"100 Rider Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"200 Rider Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "Rider app workflow verification",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    ride_id = created["ride_id"]
    request_id = created["id"]
    assert created["dispatch_status"] in {"pending", "approved", "dispatchable", "assigned"}
    assert ride_id
    assert request_id

    history_resp = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=rider_headers,
        params={"rider_phone": rider_phone, "limit": 20},
    )
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()["history"]
    assert any(row.get("ride_id") == ride_id for row in history)

    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth['access_token']}"}

    queue_resp = client.get(
        "/api/health-isf/customer-requests",
        headers=dispatcher_headers,
        params={"limit": 100},
    )
    assert queue_resp.status_code == 200, queue_resp.text
    queue_rows = queue_resp.json()
    assert any(row.get("id") == request_id for row in queue_rows)

    dispatch_queue_resp = client.get(
        "/api/health-isf/dispatch/queue",
        headers=dispatcher_headers,
        params={"limit": 200},
    )
    assert dispatch_queue_resp.status_code == 200, dispatch_queue_resp.text
    dispatch_rows = dispatch_queue_resp.json()
    assert any(row.get("ride_id") == ride_id or row.get("id") == ride_id for row in dispatch_rows)


def test_rider_request_full_dispatch_to_driver_offer(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    dispatcher_auth = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_auth['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")
    _ensure_provider(org_id)
    driver_id = _ensure_available_driver(org_id)
    suffix = uuid4()[:8]
    rider_phone = "+1 646-555-7799"

    create_resp = client.post(
        "/api/health-isf/customer-requests",
        headers=dispatcher_headers,
        json={
            "rider_name": f"Full Flow Rider {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"10 Flow Pickup {suffix}, New York, NY 10001",
            "dropoff_address": f"20 Flow Dropoff {suffix}, New York, NY 10002",
            "ride_type": "healthcare",
            "recurring": False,
            "notes": "full rider workflow",
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    request_row = create_resp.json()
    request_id = request_row["id"]
    ride_id = request_row["ride_id"]

    approve_resp = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve_resp.status_code == 200, approve_resp.text

    auto_dispatch_resp = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/auto-dispatch",
        headers=dispatcher_headers,
        json={"driver_id": driver_id, "offer_timeout_seconds": 120},
    )
    assert auto_dispatch_resp.status_code == 200, auto_dispatch_resp.text

    offer_resp = client.get(
        f"/api/health-isf/drivers/{driver_id}/active-offer",
        headers=dispatcher_headers,
    )
    assert offer_resp.status_code == 200, offer_resp.text
    offer_payload = offer_resp.json()
    assert offer_payload.get("driver_id") == driver_id
    assert offer_payload.get("offer") is not None
    assert str((offer_payload.get("offer") or {}).get("ride_id") or "") == ride_id

    tracking_resp = client.get(
        "/api/health-isf/customers/workspace/live-tracking",
        headers=dispatcher_headers,
        params={"rider_phone": rider_phone, "limit": 20},
    )
    assert tracking_resp.status_code == 200, tracking_resp.text
    tracking = tracking_resp.json()
    assert tracking.get("rider_phone") == rider_phone
