from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, hash_password, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFProvider
from app.modules.health_isf.operational_event_models import OperationalEvent, OperationalEventType
from app.modules.health_isf.operational_event_bus import OperationalEventBus
from app.modules.health_isf.realtime import EventBroadcaster, WebSocketConnection


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login_user(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login_dispatcher(client: TestClient) -> dict:
    return _login_user(client, "dispatcher@amicor.local")


def _dispatcher_org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _ensure_secondary_dispatcher(organization_id: str) -> str:
    email = "dispatcher.sync2@amicor.local"
    with SessionLocal() as db:
        existing = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        if existing is not None:
            return email

        user = PlatformUser(
            id=uuid4(),
            email=email,
            hashed_password=hash_password(SEED_PASSWORD),
            display_name="Amicor Dispatcher Sync 2",
            role="dispatcher",
            organization_name="Amicor Health",
            organization_id=organization_id,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        return email


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
            name=f"Realtime Coordination Provider {uuid4()[:6]}",
            address="901 Coordination Ave",
            phone="212-555-6122",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Realtime Coordination Driver {uuid4()[:6]}",
            phone=f"646-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"RTC-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.7,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict) -> dict:
    payload = {
        "pickup_address": "11 Coordination Blvd, New York, NY 10001",
        "dropoff_address": "88 Replay Pkwy, New York, NY 10010",
        "rider_name": f"Realtime Rider {uuid4()[:6]}",
        "rider_phone": "+1 212-555-9288",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "distributed realtime coordination test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_role_scoped_broadcast_filters_connections() -> None:
    async def _run() -> None:
        broadcaster = EventBroadcaster()

        dispatcher = WebSocketConnection("disp-1", "disp-user", "dispatcher")
        driver = WebSocketConnection("drv-1", "drv-user", "driver")
        dispatcher.subscribe("dispatcher_board")
        driver.subscribe("dispatcher_board")

        await broadcaster.register_connection(dispatcher, "org-role-scope")
        await broadcaster.register_connection(driver, "org-role-scope")

        await broadcaster.broadcast_event(
            event_type="workflow_transition",
            payload={
                "ride_id": "ride-role",
                "role_scope": ["driver"],
                "actor_user_id": "drv-user",
                "correlation_id": "corr-role-scope",
            },
            organization_id="org-role-scope",
            subscription_types=["dispatcher_board"],
        )

        assert dispatcher.send_queue.empty()
        driver_msg = json.loads(await driver.send_queue.get())
        assert driver_msg["event_type"] == "workflow_transition"
        assert driver_msg["correlation_id"] == "corr-role-scope"

    asyncio.run(_run())


def test_ride_scoped_broadcast_filters_connections() -> None:
    async def _run() -> None:
        broadcaster = EventBroadcaster()

        subscribed = WebSocketConnection("disp-sub", "disp-sub-user", "dispatcher")
        subscribed.subscribe("dispatcher_board")
        subscribed.subscribe_ride("ride-target")

        all_rides = WebSocketConnection("disp-all", "disp-all-user", "dispatcher")
        all_rides.subscribe("dispatcher_board")

        await broadcaster.register_connection(subscribed, "org-ride-scope")
        await broadcaster.register_connection(all_rides, "org-ride-scope")

        await broadcaster.broadcast_event(
            event_type="workflow_transition",
            payload={"ride_id": "ride-other", "role_scope": ["dispatcher"]},
            organization_id="org-ride-scope",
            subscription_types=["dispatcher_board"],
        )

        assert subscribed.send_queue.empty()
        assert not all_rides.send_queue.empty()

    asyncio.run(_run())


def test_operational_event_bus_rejects_stale_event() -> None:
    bus = OperationalEventBus()
    event = OperationalEvent(
        organization_id="org-stale",
        event_id=str(uuid4()),
        event_type=OperationalEventType.WORKFLOW_TRANSITION,
        role_scope=["dispatcher"],
        payload={"ride_id": "ride-stale"},
        emitted_at=datetime.utcnow() - timedelta(minutes=20),
        source_nonce="stale-nonce",
    )
    accepted, reason, _ = bus.publish(event, stale_after_seconds=120)
    assert accepted is False
    assert reason == "stale_event_rejected"


def test_websocket_sync_persistent_reconnect_recovery(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ = _ensure_provider(org_id)

    created = _create_customer_request(client, headers)
    ride_id = created["ride_id"]

    ingest = client.post(
        "/api/health-isf/operations/lifecycle-events",
        headers=headers,
        json={
            "event_type": "escalated",
            "ride_id": ride_id,
            "role_scope": ["dispatcher", "operations"],
            "reason": "reconnect replay check",
        },
    )
    assert ingest.status_code == 200, ingest.text

    ws_url = f"/api/health-isf/ws/live/{org_id}/{auth['user_id']}?role=dispatcher&token={auth['access_token']}"
    with client.websocket_connect(ws_url) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"

        websocket.send_json({"type": "sync_persistent", "last_sequence": 0})
        sync = websocket.receive_json()
        assert sync["type"] == "sync"
        assert sync["source"] == "persistent_lifecycle_stream"
        assert isinstance(sync.get("events"), list)
        assert any(str(item.get("ride_id") or "") == ride_id for item in sync["events"])


def test_websocket_assignment_lock_conflict_prevention(client: TestClient) -> None:
    auth_primary = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth_primary['access_token']}"}
    org_id = _dispatcher_org_id()
    _ = _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)
    secondary_email = _ensure_secondary_dispatcher(org_id)
    auth_secondary = _login_user(client, secondary_email)

    created = _create_customer_request(client, headers)
    request_id = created["id"]
    ride_id = created["ride_id"]

    approve = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers)
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    ws1_url = f"/api/health-isf/ws/live/{org_id}/{auth_primary['user_id']}?role=dispatcher&token={auth_primary['access_token']}"
    ws2_url = f"/api/health-isf/ws/live/{org_id}/{auth_secondary['user_id']}?role=dispatcher&token={auth_secondary['access_token']}"
    with client.websocket_connect(ws1_url) as ws1, client.websocket_connect(ws2_url) as ws2:
        _ = ws1.receive_json()
        _ = ws2.receive_json()

        ws1.send_json({"type": "claim_assignment_lock", "ride_id": ride_id})
        lock_ok = ws1.receive_json()
        assert lock_ok["type"] == "assignment_lock_claimed"

        ws2.send_json({"type": "claim_assignment_lock", "ride_id": ride_id})
        conflict = ws2.receive_json()
        assert conflict["type"] == "error"
        assert conflict["code"] == "assignment_lock_conflict"
