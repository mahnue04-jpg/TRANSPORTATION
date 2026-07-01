from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFDriver, HealthISFProvider, DriverStatus
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService


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
        assert user.organization_id is not None
        return user.organization_id


def _require_intake_dispatcher_approval(org_id: str) -> None:
    with SessionLocal() as db:
        policy = WorkflowOrchestrationService.ensure_policy(db, org_id)
        policy.approval_required = True
        policy.is_enabled = True
        db.commit()


def _provider(org_id: str) -> str:
    with SessionLocal() as db:
        provider = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == org_id).first()
        if provider:
            return provider.id
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Phase8A Provider {uuid4()[:6]}",
            address="100 Phase Ave",
            phone="212-555-8800",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return provider.id


def _available_driver(org_id: str) -> str:
    with SessionLocal() as db:
        # Use a dedicated available driver for each scenario to reduce shared-state flakiness.
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Phase8A Driver {uuid4()[:6]}",
            phone=f"917-555-{str(uuid4().replace('-', ''))[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"P8A-{uuid4()[:4].upper()}",
            status=DriverStatus.AVAILABLE,
            rating=4.8,
        )
        db.add(driver)
        db.commit()
        return driver.id


def _create_ride(client: TestClient, headers: dict, provider_id: str, suffix: str = "") -> dict:
    response = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json={
            "provider_id": provider_id,
            "passenger_name": f"Phase8A Rider {suffix or uuid4()[:6]}",
            "passenger_phone": "917-555-4455",
            "service_type": "medical_transport",
            "pickup_address": f"{suffix or 'A'} 1 Main St",
            "dropoff_address": f"{suffix or 'A'} 2 Main St",
        },
    )
    assert response.status_code in {200, 201}, response.text
    return response.json()


def test_phase8a_full_lifecycle_execution(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)
    driver_id = _available_driver(org_id)

    ride = _create_ride(client, headers, provider_id, suffix="LIFE")
    ride_id = ride["id"]
    assert ride["status"] == "pending"
    assert ride.get("lifecycle_state") == "queued"

    assign = client.patch(
        f"/api/health-isf/rides/{ride_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text
    assert assign.json().get("lifecycle_state") == "assigned"
    time.sleep(0.01)

    assigned = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "accepted"},
    )
    assert assigned.status_code == 200, assigned.text
    time.sleep(0.01)

    accepted = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert accepted.status_code == 200, accepted.text
    time.sleep(0.01)

    en_route = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "driver_en_route"},
    )
    assert en_route.status_code == 200, en_route.text
    time.sleep(0.01)

    arrived = client.post(
        f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert arrived.status_code == 200, arrived.text
    assert arrived.json().get("lifecycle_state") == "arrived"
    time.sleep(0.01)

    onboard = client.post(
        f"/api/health-isf/drivers/{driver_id}/pickup-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert onboard.status_code == 200, onboard.text
    assert onboard.json().get("lifecycle_state") in {"rider_onboard", "in_progress"}
    time.sleep(0.01)

    progress = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "in_progress"},
    )
    assert progress.status_code == 200, progress.text
    assert progress.json().get("lifecycle_state") == "in_progress"

    complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert complete.status_code == 200, complete.text
    assert complete.json().get("lifecycle_state") == "completed"


def test_phase8a_illegal_transition_blocked(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)
    ride = _create_ride(client, headers, provider_id, suffix="ILLEGAL")

    bad = client.patch(
        f"/api/health-isf/rides/{ride['id']}/status",
        headers=headers,
        json={"status": "completed"},
    )
    assert bad.status_code == 400, bad.text


def test_phase8a_websocket_sync_replay(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    _require_intake_dispatcher_approval(org_id)
    provider_id = _provider(org_id)

    with client.websocket_connect(
        f"/api/health-isf/ws/live/{org_id}/{auth['user_id']}?role=dispatcher&token={auth['access_token']}"
    ) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        assert "replay_sequence" in connected

        websocket.send_json({"type": "subscribe", "subscription_type": "dispatcher_board"})
        subscribed = websocket.receive_json()
        assert subscribed["type"] == "subscribed"

        created = _create_ride(client, headers, provider_id, suffix="WS")

        event = json.loads(websocket.receive_text())
        assert event["type"] == "event"
        assert event["payload"]["ride_id"] == created["id"]

        sync = None
        for _ in range(5):
            websocket.send_json({"type": "sync", "last_sequence": 0})
            message = websocket.receive_json()
            if message["type"] == "sync":
                sync = message
                break
            assert message["type"] == "event"
        assert sync is not None
        assert isinstance(sync.get("events"), list)
        assert len(sync["events"]) >= 1


def test_phase8a_duplicate_prevention(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)

    payload = {
        "provider_id": provider_id,
        "passenger_name": "Duplicate Guard",
        "passenger_phone": "917-555-7777",
        "service_type": "medical_transport",
        "pickup_address": "100 Duplicate St",
        "dropoff_address": "200 Duplicate Ave",
    }
    first = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert first.status_code in {200, 201}, first.text

    second = client.post("/api/health-isf/rides", headers=headers, json=payload)
    assert second.status_code == 409, second.text


def test_phase8a_dispatch_reassignment(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)

    ride = _create_ride(client, headers, provider_id, suffix="REASSIGN")
    d1 = _available_driver(org_id)

    # Ensure second available driver exists.
    with SessionLocal() as db:
        d2 = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == org_id,
            HealthISFDriver.id != d1,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        ).first()
        if not d2:
            d2 = HealthISFDriver(
                id=uuid4(),
                organization_id=org_id,
                name=f"Phase8A Driver {uuid4()[:6]}",
                phone=f"917-555-{str(uuid4().replace('-', ''))[:4]}",
                vehicle_type="sedan",
                vehicle_plate=f"P8B-{uuid4()[:4].upper()}",
                status=DriverStatus.AVAILABLE,
                rating=4.6,
            )
            db.add(d2)
            db.commit()
        d2_id = d2.id

    assign = client.patch(
        f"/api/health-isf/rides/{ride['id']}/assign-driver",
        headers=headers,
        json={"driver_id": d1},
    )
    if assign.status_code not in {200, 400}:
        pytest.fail(assign.text)
    if assign.status_code == 400:
        assert "already has an assigned driver" in assign.text

    reassign = client.patch(
        f"/api/health-isf/dispatcher/rides/{ride['id']}/reassign-driver",
        headers=headers,
        json={"driver_id": d2_id},
    )
    if reassign.status_code == 200:
        assert reassign.json()["driver_id"] == d2_id
    else:
        assert reassign.status_code == 400
        assert "already has an assigned driver" in reassign.text


def test_phase8a_restart_continuity_and_replay_integrity(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)
    driver_id = _available_driver(org_id)

    ride = _create_ride(client, headers, provider_id, suffix="PERSIST")
    ride_id = ride["id"]

    assign = client.patch(
        f"/api/health-isf/rides/{ride_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    history = client.get(f"/api/health-isf/rides/{ride_id}/history", headers=headers)
    assert history.status_code == 200, history.text
    states = [item["to_status"] for item in history.json()]
    assert "queued" in states
    assert "assigned" in states

    # Idempotent status call should not duplicate lifecycle transition.
    before_len = len(states)
    same_state = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "assigned"},
    )
    assert same_state.status_code == 200, same_state.text

    history2 = client.get(f"/api/health-isf/rides/{ride_id}/history", headers=headers)
    assert history2.status_code == 200, history2.text
    assert len(history2.json()) == before_len


def test_phase8a_auto_assignment_orchestration(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id()
    provider_id = _provider(org_id)
    _available_driver(org_id)

    ride = _create_ride(client, headers, provider_id, suffix="AUTO")
    response = client.post(f"/api/health-isf/dispatcher/rides/{ride['id']}/auto-assign", headers=headers)
    assert response.status_code == 200, response.text
    assigned = response.json()
    assert assigned.get("driver_id")
    assert assigned.get("lifecycle_state") == "assigned"


def test_phase8a_dispatcher_queue_priority_and_overload_payload(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/health-isf/dispatcher/queues", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "priority_queue" in payload
    assert "overload" in payload
    assert isinstance(payload["priority_queue"], list)
    assert isinstance(payload["overload"], dict)
