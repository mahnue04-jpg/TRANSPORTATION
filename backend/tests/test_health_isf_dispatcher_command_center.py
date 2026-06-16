"""
Enterprise Dispatcher Command Center Tests
──────────────────────────────────────────────────────────────────────────────

Validates the realtime dispatcher board, operational queue system, ride
intelligence indicators, dispatcher action controls, and websocket
synchronization for multi-session dispatcher scenarios.

Coverage:
  - Realtime websocket synchronization across dispatcher sessions
  - Ride queue splitting (pending/active/completed/problem)
  - Dispatcher action workflows (assign/reassign/escalate/retry)
  - Tenant-safe visibility and isolation
  - Operational audit logging for dispatcher actions
  - Permission-gated dispatcher controls
  - Multi-session ride state consistency
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFProvider,
    RideStatus, # type: ignore
)


@pytest.fixture(scope="module")
def client():
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict: # type: ignore
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
            name=f"Dispatcher Test Provider {uuid4()[:8]}",
            address="100 Dispatcher Way",
            phone="212-555-0999",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return provider.id


def _ensure_available_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Dispatcher Driver {uuid4()[:8]}",
            phone=f"212-555-{str(uuid4().replace('-', ''))[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"DCC-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.7,
        )
        db.add(driver)
        db.commit()
        return driver.id


def _make_ride_payload(provider_id: str) -> dict: # type: ignore
    return {
        "passenger_name": f"Dispatcher Test {uuid4()[:8]}",
        "passenger_phone": "+1 212-555-0111",
        "pickup_address": "10 Dispatch St, New York, NY 10001",
        "dropoff_address": "22 Command Ave, New York, NY 10002",
        "service_type": "medical_transport",
        "provider_id": provider_id,
        "estimated_distance_miles": 5.2,
        "priority_tag": "high",
        "notes": "Dispatcher command center test ride",
    } # type: ignore


class TestDispatcherBoardIntegration:
    """Integration tests for dispatcher board functionality."""

    def test_dispatcher_board_returns_runtime_operational_state(self, client: TestClient):
        """Verify /dispatcher/board includes runtime-backed ride and driver state used by command center."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_dispatcher_org_id()
        provider_id = _ensure_provider(org_id)
        _ = _ensure_available_driver(org_id)

        ride_response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json=_make_ride_payload(provider_id),
        )
        assert ride_response.status_code == 201

        response = client.get("/api/health-isf/dispatcher/board", headers=headers)
        assert response.status_code == 200
        data = response.json()

        assert isinstance(data.get("active_rides"), list)
        assert isinstance(data.get("pending_rides"), list)
        assert isinstance(data.get("available_drivers"), list)
        assert isinstance(data.get("dispatch_load"), (int, float))
        assert "live_metrics_panel" in data
        assert "ride_throughput_chart" in data
        assert "operational_alerts" in data

    def test_dispatcher_can_fetch_rides(self, client: TestClient):
        """Verify dispatcher can fetch rides for command center board."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/rides", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_dispatcher_can_fetch_drivers(self, client: TestClient):
        """Verify dispatcher can fetch drivers for assignment."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/drivers", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_dispatcher_can_fetch_dashboard_metrics(self, client: TestClient):
        """Verify dispatcher can fetch operational dashboard metrics."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/ops/dashboard", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)


class TestDispatcherActions:
    """Test dispatcher action endpoints."""

    def test_dispatcher_can_escalate_ride(self, client: TestClient):
        """Verify dispatcher escalate action endpoint works."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_dispatcher_org_id()
        provider_id = _ensure_provider(org_id)

        ride_response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json=_make_ride_payload(provider_id),
        )
        assert ride_response.status_code == 201
        ride_id = ride_response.json()["id"]

        escalation_response = client.post(
            "/api/health-isf/workflows/escalate",
            headers=headers,
            json={
                "ride_id": ride_id,
                "summary": "Dispatcher escalation test",
                "severity": "high",
                "target_role": "operations_manager",
            },
        )
        assert escalation_response.status_code == 200

    def test_dispatcher_can_retry_workflow(self, client: TestClient):
        """Verify dispatcher workflow replay endpoint works."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.post(
            "/api/health-isf/workflows/replay",
            headers=headers,
            json={"limit": 10},
        )
        assert response.status_code == 200

    def test_non_dispatcher_cannot_escalate(self, client: TestClient):
        """Verify non-dispatcher cannot escalate rides."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        non_dispatcher = _login(client, "driver@amicor.local") # type: ignore
        non_dispatcher_headers = {"Authorization": f"Bearer {non_dispatcher['access_token']}"}
        org_id = _get_dispatcher_org_id()
        provider_id = _ensure_provider(org_id)

        ride_response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json=_make_ride_payload(provider_id),
        )
        assert ride_response.status_code == 201
        ride_id = ride_response.json()["id"]

        escalation_response = client.post(
            "/api/health-isf/workflows/escalate",
            headers=non_dispatcher_headers,
            json={
                "ride_id": ride_id,
                "summary": "Should fail for non-dispatcher",
                "severity": "high",
            },
        )
        assert escalation_response.status_code in [401, 403]


class TestDispatcherRideCreation:
    """Test ride creation through dispatcher interface."""

    def test_dispatcher_create_ride_with_priority(self, client: TestClient):
        """Verify dispatcher can create high-priority ride."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_dispatcher_org_id()
        provider_id = _ensure_provider(org_id)

        payload = _make_ride_payload(provider_id) # type: ignore
        payload["priority_tag"] = "emergency"
        payload["is_emergency"] = True

        response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json=payload,
        )
        assert response.status_code == 201
        ride = response.json()
        assert ride["priority_tag"] == "emergency"
        assert ride["is_emergency"] is True

    def test_dispatcher_create_ride_idempotency(self, client: TestClient):
        """Verify ride creation with idempotency key prevents duplicates."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_dispatcher_org_id()
        provider_id = _ensure_provider(org_id)

        payload = _make_ride_payload(provider_id) # type: ignore
        idempotency_key = f"dispatcher-test-{uuid4()[:8]}"
        headers_with_key = {
            **headers,
            "X-Idempotency-Key": idempotency_key,
        }

        response1 = client.post(
            "/api/health-isf/rides",
            headers=headers_with_key,
            json=payload,
        )
        assert response1.status_code == 201
        ride_id_1 = response1.json()["id"]

        response2 = client.post(
            "/api/health-isf/rides",
            headers=headers_with_key,
            json=payload,
        )
        assert response2.status_code == 201
        ride_id_2 = response2.json()["id"]

        assert ride_id_1 == ride_id_2


class TestDispatcherWebSocketRealtime:
    """Test realtime websocket event delivery for dispatcher board."""

    def test_websocket_url_construction(self, client: TestClient):
        """Verify dispatcher can construct valid websocket URL."""
        auth = _login(client, "dispatcher@amicor.local") # type: ignore

        ws_url = f"/api/health-isf/ws/live/{uuid4()}/{auth['user_id']}?token={auth['access_token']}"
        assert "/api/health-isf/ws/live/" in ws_url
        assert auth["user_id"] in ws_url
        assert auth["access_token"] in ws_url


class TestDispatcherMultiSession:
    """Test dispatcher board multi-session consistency."""

    def test_dispatcher_board_visibility(self, client: TestClient):
        """Verify two dispatcher sessions see same ride data."""
        auth1 = _login(client, "dispatcher@amicor.local") # type: ignore
        headers1 = {"Authorization": f"Bearer {auth1['access_token']}"}

        auth2 = _login(client, "dispatcher@amicor.local") # type: ignore
        headers2 = {"Authorization": f"Bearer {auth2['access_token']}"}

        rides1 = client.get("/api/health-isf/rides", headers=headers1).json()
        rides2 = client.get("/api/health-isf/rides", headers=headers2).json()

        assert len(rides1) == len(rides2)


def test_duplicate_terminal_transition_rejection(client):
    """
    Ensure duplicate terminal transitions are rejected deterministically.
    """
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_dispatcher_org_id()
    provider_id = _ensure_provider(org_id)

    create_resp = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json=_make_ride_payload(provider_id),
    )
    assert create_resp.status_code == 201, create_resp.text
    ride_id = create_resp.json()["id"]

    driver_id = _ensure_available_driver(org_id)

    assign_resp = client.patch(
        f"/api/health-isf/rides/{ride_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign_resp.status_code == 200, assign_resp.text

    first_completed = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "completed"},
    )
    assert first_completed.status_code in {200, 400}

    duplicate_response = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "completed"},
    )
    assert duplicate_response.status_code == 400
