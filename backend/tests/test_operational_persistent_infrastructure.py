from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFProvider
from app.modules.health_isf.operational_event_bus import get_operational_event_bus
from app.modules.health_isf.operational_replay_service import OperationalReplayService


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login_dispatcher(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _login_supervisor(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": "supervisor@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _dispatcher_org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
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
            name=f"Persistent Infra Provider {uuid4()[:6]}",
            address="940 Persistence Way",
            phone="212-555-6110",
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
            name=f"Persistent Infra Driver {uuid4()[:6]}",
            phone=f"646-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"PIF-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.8,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict) -> dict:
    payload = {
        "pickup_address": "11 Persistent Blvd, New York, NY 10001",
        "dropoff_address": "88 Recovery Pkwy, New York, NY 10010",
        "rider_name": f"Persistent Rider {uuid4()[:6]}",
        "rider_phone": "+1 212-555-9188",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "persistent operational infrastructure test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _run_driver_flow(client: TestClient, headers: dict, request_id: str, ride_id: str, driver_id: str) -> None:
    approve = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers)
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    accept = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert accept.status_code == 200, accept.text

    arrived = client.post(
        f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert arrived.status_code == 200, arrived.text


def test_lifecycle_event_contract_rejects_invalid_transition(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ = _ensure_provider(org_id)

    created = _create_customer_request(client, headers)
    ride_id = created["ride_id"]

    # Completed as first explicit lifecycle ingestion must be rejected by ordered transition contract.
    invalid_payload = {
        "event_type": "completed",
        "ride_id": ride_id,
        "driver_id": str(uuid4()),
        "role_scope": ["dispatcher", "driver", "rider"],
        "reason": "forced completion should fail",
    }
    response = client.post("/api/health-isf/operations/lifecycle-events", headers=headers, json=invalid_payload)
    assert response.status_code == 400, response.text
    assert "Invalid transition" in response.json().get("detail", "")


def test_persistent_recovery_rebuilds_dispatcher_rider_driver_and_timeline(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ = _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    created = _create_customer_request(client, headers)
    request_id = created["id"]
    ride_id = created["ride_id"]

    # Emit strict typed lifecycle event that is persisted + published to event bus replay chain.
    ingest_payload = {
        "event_type": "escalated",
        "ride_id": ride_id,
        "role_scope": ["dispatcher", "operations"],
        "reason": "manual supervision escalation",
    }
    ingest_response = client.post("/api/health-isf/operations/lifecycle-events", headers=headers, json=ingest_payload)
    assert ingest_response.status_code == 200, ingest_response.text

    _run_driver_flow(client, headers, request_id, ride_id, driver_id)

    recovery = client.get(
        f"/api/health-isf/operations/persistent-recovery?ride_id={ride_id}&driver_id={driver_id}&after_sequence=0&limit=200",
        headers=headers,
    )
    assert recovery.status_code == 200, recovery.text
    payload = recovery.json()

    assert payload["recovery_source"] == "persistent_operational_storage"
    assert payload["synchronization"]["append_only_audit_chain"] is True

    board = payload["dispatcher_board"]
    assert "active_rides" in board
    assert "available_drivers" in board

    assert payload["rider_active_trip_state"] is not None
    assert str(payload["rider_active_trip_state"]["id"]) == ride_id

    assert payload["driver_active_workflow_state"] is not None
    assert str(payload["driver_active_workflow_state"]["driver_id"]) == driver_id

    timeline = payload["lifecycle_timeline"]
    assert isinstance(timeline, list)
    assert len(timeline) > 0
    assert all("sequence" in item for item in timeline)

    replay = payload["event_stream_replay"]
    assert replay["reconnect_safe"] is True
    assert replay["backend_authoritative"] is True


def test_supervisor_can_read_persistent_recovery_and_runtime_replay(client: TestClient) -> None:
    supervisor = _login_supervisor(client)
    headers = {"Authorization": f"Bearer {supervisor['access_token']}"}

    recovery = client.get("/api/health-isf/operations/persistent-recovery?limit=50", headers=headers)
    assert recovery.status_code == 200, recovery.text
    recovery_payload = recovery.json()
    assert recovery_payload["recovery_source"] == "persistent_operational_storage"
    visibility = recovery_payload.get("supervisor_operational_visibility") or {}
    assert visibility.get("read_only") is True
    assert isinstance(visibility.get("active_assignments"), list)
    assert isinstance(visibility.get("reassignment_chains"), list)
    assert isinstance(visibility.get("escalation_history"), list)
    assert isinstance(visibility.get("orphaned_ride_states"), list)
    assert isinstance(visibility.get("stale_dispatch_queues"), list)
    mobile = recovery_payload.get("mobile_operational_hydration") or {}
    assert mobile.get("hydration_safe") is True
    assert mobile.get("utc_normalized") is True
    assert mobile.get("partial_payload_tolerant") is True

    replay = client.get("/api/health-isf/operations/runtime-replay?after_sequence=0&limit=50", headers=headers)
    assert replay.status_code == 200, replay.text
    replay_payload = replay.json()
    assert replay_payload.get("replay_safe") is True
    assert replay_payload.get("hydration_safe") is True
    assert replay_payload.get("backend_authoritative") is True
    assert replay_payload.get("sequence_monotonic") is True
    assert isinstance(replay_payload.get("events"), list)


def test_persistent_event_replay_survives_memory_reset(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ = _ensure_provider(org_id)

    created = _create_customer_request(client, headers)
    ride_id = created["ride_id"]

    event_response = client.post(
        "/api/health-isf/operations/lifecycle-events",
        headers=headers,
        json={
            "event_type": "escalated",
            "ride_id": ride_id,
            "role_scope": ["dispatcher", "operations"],
            "reason": "persistence replay validation",
        },
    )
    assert event_response.status_code == 200, event_response.text

    # Simulate process memory reset; replay must still work from persisted audit storage.
    bus = get_operational_event_bus()
    bus._events.clear()  # pyright: ignore[reportPrivateUsage]
    bus._sequences.clear()  # pyright: ignore[reportPrivateUsage]

    replay = OperationalReplayService.replay(
        organization_id=org_id,
        after_sequence=0,
        role="dispatcher",
        limit=200,
    )
    assert replay["reconnect_safe"] is True
    assert replay["tenant_scoped"] is True
    assert len(replay["events"]) > 0
    assert any(str(item.get("event_type")) == "workflow_transition" for item in replay["events"])
