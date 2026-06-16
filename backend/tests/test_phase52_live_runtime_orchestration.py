from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import DriverStatus, HealthISFDriver


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


def _ensure_available_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Phase52 Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"P52-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict, rider_phone: str, suffix: str) -> dict:
    payload = {
        "pickup_address": "100 Phase52 Pickup, New York, NY 10001",
        "dropoff_address": "200 Phase52 Dropoff, New York, NY 10002",
        "rider_name": f"Phase52 Rider {suffix}",
        "rider_phone": rider_phone,
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "phase52 live runtime orchestration test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_phase52_lifecycle_runtime_replay_and_state(client: TestClient) -> None:
    dispatcher = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")

    driver_id = _ensure_available_driver(org_id)
    request_row = _create_customer_request(client, dispatcher_headers, "+1 212-555-5251", "lifecycle")
    ride_id = request_row["ride_id"]

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    assign = client.post(
        "/api/health-isf/operations/lifecycle-action",
        headers=dispatcher_headers,
        params={"action": "assign_driver", "ride_id": ride_id, "driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    for action in ["accept_assignment", "driver_arrived", "rider_picked_up", "ride_completed"]:
        result = client.post(
            "/api/health-isf/operations/lifecycle-action",
            headers=dispatcher_headers,
            params={"action": action, "ride_id": ride_id, "driver_id": driver_id},
        )
        assert result.status_code == 200, result.text

    runtime_state_resp = client.get(
        "/api/health-isf/operations/runtime-state",
        headers=dispatcher_headers,
        params={"include_timeline": True, "limit": 80},
    )
    assert runtime_state_resp.status_code == 200, runtime_state_resp.text
    runtime_state = runtime_state_resp.json()
    assert runtime_state.get("organization_id") == org_id
    assert "sequence" in runtime_state
    assert isinstance(runtime_state.get("timeline", []), list)
    assert runtime_state.get("safety", {}).get("deterministic_event_ordering") is True

    replay_resp = client.get(
        "/api/health-isf/operations/runtime-replay",
        headers=dispatcher_headers,
        params={"after_sequence": 0, "limit": 200},
    )
    assert replay_resp.status_code == 200, replay_resp.text
    replay_payload = replay_resp.json()
    events = replay_payload.get("events", [])
    assert isinstance(events, list)

    ride_events = [row for row in events if (row.get("details") or {}).get("ride_id") == ride_id]
    assert ride_events, "Expected runtime replay events for lifecycle ride"
    aliases = {str(row.get("event_alias") or row.get("event_name") or "") for row in ride_events}
    assert "ride_completed" in aliases


def test_phase52_dispatch_recovery_and_reconcile(client: TestClient) -> None:
    dispatcher = _login(client, "dispatcher@amicor.local")
    admin = _login(client, "admin@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    org_id = _org_id_for("dispatcher@amicor.local")
    primary_driver = _ensure_available_driver(org_id)
    _ensure_available_driver(org_id)
    request_row = _create_customer_request(client, dispatcher_headers, "+1 212-555-5252", "recovery")

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/assign-driver",
        headers=dispatcher_headers,
        json={"driver_id": primary_driver},
    )
    assert assign.status_code == 200, assign.text

    recovery = client.post(
        "/api/health-isf/operations/dispatch-recovery",
        headers=admin_headers,
        params={"ride_id": request_row["ride_id"], "strategy": "reassign"},
    )
    assert recovery.status_code in {200, 400}, recovery.text
    recovery_payload = recovery.json()
    if recovery.status_code == 200:
        assert recovery_payload.get("strategy") == "reassign"
        assert recovery_payload.get("ride", {}).get("id") == request_row["ride_id"]
    else:
        assert "assigned driver" in str(recovery_payload.get("detail", "")).lower()

    reconcile = client.post(
        "/api/health-isf/operations/runtime-reconcile",
        headers=admin_headers,
    )
    assert reconcile.status_code == 200, reconcile.text
    reconcile_payload = reconcile.json()
    assert reconcile_payload.get("organization_id") == org_id
    assert "last_reconciliation_at" in reconcile_payload
    assert "deterministic_event_ordering" in reconcile_payload

    runtime_state_resp = client.get(
        "/api/health-isf/operations/runtime-state",
        headers=admin_headers,
        params={"include_timeline": True, "limit": 120},
    )
    assert runtime_state_resp.status_code == 200, runtime_state_resp.text
    runtime_state = runtime_state_resp.json()
    assert isinstance(runtime_state.get("websocket_subscriber_registry", []), list)
    assert isinstance(runtime_state.get("active_rides", []), list)
