from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import (
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFWorkflowAuditLog,
)
from app.modules.health_isf.realtime import EventBroadcaster, EventEmitter, WebSocketConnection


@pytest.fixture(scope="module")
def client():
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _get_dispatcher_org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        assert user.organization_id is not None
        return user.organization_id


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            return provider.id

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Enterprise Intake Provider {uuid4()[:8]}",
            address="100 Enterprise Way",
            phone="212-555-0456",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return provider.id


def _make_payload(provider_id: str) -> dict:
    return {
        "passenger_name": f"Intake Passenger {uuid4()[:8]}",
        "passenger_phone": "+1 212-555-0111",
        "pickup_address": "10 Main St, New York, NY 10001",
        "dropoff_address": "22 Park Ave, New York, NY 10002",
        "service_type": "medical_transport",
        "provider_id": provider_id,
        "estimated_distance_miles": 8.4,
        "priority_tag": "high",
        "notes": "Needs wheelchair support",
    }


def test_create_ride_validation_rejects_invalid_payload(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_dispatcher_org_id()
    provider_id = _ensure_provider(org_id)

    response = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json={
            "passenger_name": "A",
            "passenger_phone": "bad-phone",
            "pickup_address": "123 Same Place",
            "dropoff_address": "123 Same Place",
            "service_type": "medical_transport",
            "provider_id": provider_id,
            "estimated_distance_miles": 0,
        },
    )

    assert response.status_code == 422, response.text


def test_create_ride_auto_duration_priority_context(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_dispatcher_org_id()
    provider_id = _ensure_provider(org_id)

    payload = _make_payload(provider_id)
    payload["estimated_duration_minutes"] = None
    payload["appointment_time"] = "2026-05-19T14:30:00Z"
    payload["recurring_trip_pattern"] = {"frequency": "weekly", "days": ["mon", "wed"]}
    payload["ai_dispatch_context"] = {"routing_bias": "wheelchair_priority"}

    response = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["organization_id"] == org_id
    assert body["estimated_duration_minutes"] and body["estimated_duration_minutes"] > 0
    assert body["priority_score"] and body["priority_score"] > 0
    assert body["priority_tag"] in {"high", "urgent", "emergency", "normal", "low"}


def test_create_ride_duplicate_submission_prevention(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_dispatcher_org_id()
    provider_id = _ensure_provider(org_id)

    payload = _make_payload(provider_id)
    first = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert second.status_code == 409, second.text


def test_create_ride_idempotent_submission(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    org_id = _get_dispatcher_org_id()
    provider_id = _ensure_provider(org_id)

    idem_key = f"ride-intake:{uuid4()}"
    headers = {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Idempotency-Key": idem_key,
    }

    payload = _make_payload(provider_id)
    first = client.post("/api/health-isf/rides", headers=headers, json=payload)
    second = client.post("/api/health-isf/rides", headers=headers, json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code in {200, 201}, second.text
    assert first.json()["id"] == second.json()["id"]


def test_create_ride_tenant_isolation(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    with SessionLocal() as db:
        org = HealthISFOrganization(
            id=uuid4(),
            name="Other Tenant",
            code=f"OT-{uuid4()[:8]}",
            is_active=True,
        )
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org.id,
            name="Other Tenant Provider",
            address="999 Other Ave",
            phone="212-555-0144",
            service_type="clinic",
            is_active=True,
        )
        db.add_all([org, provider])
        db.commit()
        provider_id = provider.id

    payload = _make_payload(provider_id)
    response = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert response.status_code == 403, response.text


def test_create_ride_websocket_and_workflow_hook(client: TestClient):
    from unittest.mock import patch

    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_dispatcher_org_id()
    provider_id = _ensure_provider(org_id)

    broadcaster = EventBroadcaster()
    emitter = EventEmitter(broadcaster)
    conn = WebSocketConnection("ride-create-test", "dispatcher-1", "dispatcher")
    conn.subscribe("dispatcher_board")
    asyncio.run(broadcaster.register_connection(conn, org_id))

    with patch("app.modules.health_isf.routes.get_emitter", return_value=emitter):
        response = client.post("/api/health-isf/rides", headers=headers, json=_make_payload(provider_id))
        assert response.status_code == 201, response.text
        ride_id = response.json()["id"]

    message = asyncio.run(asyncio.wait_for(conn.send_queue.get(), timeout=1.0))
    event = json.loads(message)
    assert event["event_type"] == "ride_created"
    assert event["payload"]["ride_id"] == ride_id

    with SessionLocal() as db:
        hooks = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == org_id,
                HealthISFWorkflowAuditLog.event_type == "workflow.intake.submitted",
            )
            .all()
        )
        assert any(ride_id in (row.payload or "") for row in hooks)
