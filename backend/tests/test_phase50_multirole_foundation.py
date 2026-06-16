from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFProvider, HealthISFRide


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
            name=f"Phase50 Provider {uuid4()[:6]}",
            address="500 Phase50 Avenue",
            phone="212-555-0510",
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
            name=f"Phase50 Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"P50-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict, rider_phone: str, suffix: str) -> dict:
    payload = {
        "pickup_address": "100 Phase50 Pickup, New York, NY 10001",
        "dropoff_address": "200 Phase50 Dropoff, New York, NY 10002",
        "rider_name": f"Phase50 Rider {suffix}",
        "rider_phone": rider_phone,
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "phase50 multirole foundation test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _provider_id_for_ride(ride_id: str) -> str:
    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert ride is not None
        assert ride.provider_id is not None
        return str(ride.provider_id)


def test_phase50_customer_workspace_endpoints(client: TestClient) -> None:
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    rider_phone = "+1 212-555-5050"

    _create_customer_request(client, headers, rider_phone, "history-a")
    _create_customer_request(client, headers, rider_phone, "history-b")

    history_resp = client.get(
        "/api/health-isf/customers/workspace/history",
        headers=headers,
        params={"rider_phone": rider_phone, "limit": 20},
    )
    assert history_resp.status_code == 200, history_resp.text
    history = history_resp.json()
    assert history["rider_phone"] == rider_phone
    assert len(history["history"]) >= 2

    active_resp = client.get(
        "/api/health-isf/customers/workspace/active",
        headers=headers,
        params={"rider_phone": rider_phone},
    )
    assert active_resp.status_code == 200, active_resp.text
    active = active_resp.json()
    assert active["rider_phone"] == rider_phone
    assert "active_ride" in active


def test_phase50_provider_queue_and_notes(client: TestClient) -> None:
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    request_row = _create_customer_request(client, headers, "+1 212-555-5051", "provider")

    provider_id = _provider_id_for_ride(request_row["ride_id"])

    queue_resp = client.get(
        f"/api/health-isf/providers/{provider_id}/transport-queue",
        headers=headers,
        params={"include_completed": False, "limit": 50},
    )
    assert queue_resp.status_code == 200, queue_resp.text
    queue_payload = queue_resp.json()
    assert queue_payload["provider_id"] == provider_id
    assert queue_payload["queue_size"] >= 1

    note_text = "Provider confirmed recurring transport authorization."
    note_resp = client.patch(
        f"/api/health-isf/providers/{provider_id}/requests/{request_row['id']}/notes",
        headers=headers,
        params={"note": note_text},
    )
    assert note_resp.status_code == 200, note_resp.text
    updated_request = note_resp.json()
    assert note_text in (updated_request.get("notes") or "")


def test_phase50_driver_active_offer_visibility(client: TestClient) -> None:
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")

    _ensure_provider(org_id)
    driver_id = _ensure_available_driver(org_id)
    request_row = _create_customer_request(client, headers, "+1 212-555-5052", "offer")

    approve_resp = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/approve",
        headers=headers,
    )
    assert approve_resp.status_code == 200, approve_resp.text

    auto_dispatch_resp = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/auto-dispatch",
        headers=headers,
        json={"offer_timeout_seconds": 120},
    )
    assert auto_dispatch_resp.status_code == 200, auto_dispatch_resp.text

    active_offer_resp = client.get(f"/api/health-isf/drivers/{driver_id}/active-offer", headers=headers)
    assert active_offer_resp.status_code == 200, active_offer_resp.text
    payload = active_offer_resp.json()
    assert payload["driver_id"] == driver_id
    assert "offer" in payload


def test_phase50_admin_command_center_summary(client: TestClient) -> None:
    auth = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    summary_resp = client.get("/api/health-isf/admin/command-center/summary", headers=headers)
    assert summary_resp.status_code == 200, summary_resp.text
    summary = summary_resp.json()
    assert "queue_metrics" in summary
    assert "websocket" in summary
    assert "runtime_validation" in summary
    assert "rejected_offer_count" in summary
