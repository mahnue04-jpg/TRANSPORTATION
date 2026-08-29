from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        return user.organization_id


def _provider(org_id: str) -> str:
    with SessionLocal() as db:
        provider = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org_id).first()
        if provider:
            return provider.id
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Phase8B Provider {uuid4()[:6]}",
            address="200 Phase Ave",
            phone="212-555-9900",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return provider.id


def _available_driver(org_id: str) -> str:
    with SessionLocal() as db:
        driver = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == org_id,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        ).first()
        if driver:
            return driver.id
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Phase8B Driver {uuid4()[:6]}",
            phone=f"917-555-{str(uuid4().replace('-', ''))[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"P8C-{uuid4()[:4].upper()}",
            status=DriverStatus.AVAILABLE,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return driver.id


def _create_ride(client: TestClient, headers: dict, provider_id: str, suffix: str) -> dict:
    response = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json={
            "provider_id": provider_id,
            "passenger_name": f"Phase8B Rider {suffix}",
            "passenger_phone": "917-555-0101",
            "service_type": "medical_transport",
            "pickup_address": f"{suffix} 10 Main St",
            "dropoff_address": f"{suffix} 20 Main St",
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()


def test_phase8b_route_gps_reconnect_flow(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        "app.modules.health_isf.service._is_intake_auto_dispatch_enabled",
        lambda db, organization_id: False,
    )
    monkeypatch.setattr(
        "app.modules.health_isf.routes._schedule_customer_request_side_effects",
        lambda **kwargs: None,
    )
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)
    driver_id = _available_driver(org_id)

    ride = _create_ride(client, headers, provider_id, suffix="GPS")

    assign = client.patch(
        f"/api/health-isf/rides/{ride['id']}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    route = client.post(
        "/api/health-isf/transport/routes/plan",
        headers=headers,
        json={
            "ride_id": ride["id"],
            "origin_latitude": 40.7484,
            "origin_longitude": -73.9857,
            "destination_latitude": 40.7306,
            "destination_longitude": -73.9352,
            "map_provider": "synthetic",
            "traffic_mode": "normal",
        },
    )
    assert route.status_code == 200, route.text
    route_payload = route.json()
    assert route_payload["ride_id"] == ride["id"]
    assert route_payload["estimated_duration_minutes"] >= 1

    ping = client.post(
        "/api/health-isf/transport/location/ingest",
        headers=headers,
        json={
            "driver_id": driver_id,
            "ride_id": ride["id"],
            "latitude": 40.7410,
            "longitude": -73.9700,
            "speed_kph": 34.0,
            "heading": 115.0,
            "device_id": "ios-driver-001",
            "source": "mobile",
        },
    )
    assert ping.status_code == 200, ping.text
    ping_payload = ping.json()
    assert ping_payload["driver_id"] == driver_id
    assert "location_ping_id" in ping_payload

    snapshot = client.get(f"/api/health-isf/transport/rides/{ride['id']}/route", headers=headers)
    assert snapshot.status_code == 200, snapshot.text
    body = snapshot.json()
    assert body["ride_id"] == ride["id"]
    assert len(body["recent_points"]) >= 1

    reconnect = client.post(
        "/api/health-isf/mobile/reconnect/snapshot",
        headers=headers,
        json={"driver_id": driver_id, "last_ping_id": None},
    )
    assert reconnect.status_code == 200, reconnect.text
    reconnect_payload = reconnect.json()
    assert reconnect_payload["driver_id"] == driver_id
    assert isinstance(reconnect_payload["queued_location_updates"], list)


def test_phase8b_payments_capture_and_settlement(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        "app.modules.health_isf.service._is_intake_auto_dispatch_enabled",
        lambda db, organization_id: False,
    )
    monkeypatch.setattr(
        "app.modules.health_isf.routes._schedule_customer_request_side_effects",
        lambda **kwargs: None,
    )
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)
    driver_id = _available_driver(org_id)

    ride = _create_ride(client, headers, provider_id, suffix="PAY")
    assign = client.patch(
        f"/api/health-isf/rides/{ride['id']}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    intent = client.post(
        "/api/health-isf/payments/intents",
        headers=headers,
        json={
            "ride_id": ride["id"],
            "amount_usd": 45.25,
            "tip_amount_usd": 3.0,
            "surcharge_usd": 1.25,
            "invoice_reference": "INV-PHASE8B-001",
            "capture_immediately": False,
        },
    )
    assert intent.status_code == 200, intent.text
    intent_payload = intent.json()
    assert intent_payload["status"] == "requires_capture"

    capture = client.post(
        "/api/health-isf/payments/capture",
        headers=headers,
        json={"payment_id": intent_payload["id"]},
    )
    assert capture.status_code == 200, capture.text
    assert capture.json()["status"] == "succeeded"

    settle = client.post(
        "/api/health-isf/payments/settle",
        headers=headers,
        json={
            "payment_id": intent_payload["id"],
            "driver_ratio": 0.70,
            "provider_ratio": 0.30,
        },
    )
    assert settle.status_code == 200, settle.text
    settlement = settle.json()
    assert settlement["settlement_status"] == "processed"
    assert len(settlement["entries"]) == 2

    listed = client.get(f"/api/health-isf/payments/rides/{ride['id']}", headers=headers)
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert len(rows) >= 1
    assert rows[0]["ride_id"] == ride["id"]
