"""
Authenticated Live Flow Tests
────────────────────────────────────────────────────────────────────────────────

End-to-end authenticated workflow coverage:
  - Ride creation with RBAC validation
  - Ride assignment by dispatcher
  - Status progression (pending → accepted → in_transit → completed)
  - Provider actions
  - AI dispatch recommendations
  - Nova context awareness of live operational state
  - Cross-tenant denial
  - Driver-cannot-mutate guardrails
"""
from __future__ import annotations

import json
import time
import threading
import queue
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import (
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFVehicle,
    DriverStatus,
    RideStatus,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

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


def _get_org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return user.organization_id


def _ensure_provider(org_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == org_id)
            .first()
        )
        if provider:
            return provider.id
        new_provider = HealthISFProvider(
            id=uuid4(),
            organization_id=org_id,
            name=f"Live Flow Clinic {uuid4()[:6]}",
            address="100 Live Flow St",
            phone="212-555-1234",
            service_type="clinic",
            is_active=True,
        )
        db.add(new_provider)
        db.commit()
        return new_provider.id


def _ensure_available_driver(org_id: str) -> str:
    with SessionLocal() as db:
        # Always create a dedicated available driver per test flow to avoid status contention.
        phone_suffix = ''.join(ch for ch in str(uuid4()) if ch.isdigit())[:4].ljust(4, '7')
        new_driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Live Driver {uuid4()[:6]}",
            phone=f"917-555-{phone_suffix}",
            vehicle_type="sedan",
            vehicle_plate=f"LF-{uuid4()[:4].upper()}",
            status=DriverStatus.AVAILABLE,
            rating=4.7,
        )
        db.add(new_driver)
        db.commit()
        return new_driver.id


def _ensure_vehicle(org_id: str, *, is_active: bool = True) -> str:
    with SessionLocal() as db:
        vehicle = HealthISFVehicle(
            id=uuid4(),
            organization_id=org_id,
            vehicle_type="van",
            vehicle_plate=f"LV-{uuid4()[:6].upper()}",
            capacity=6,
            is_active=is_active,
        )
        db.add(vehicle)
        db.commit()
        return vehicle.id


def _ensure_external_org_vehicle() -> str:
    with SessionLocal() as db:
        external_org = HealthISFOrganization(
            id=uuid4(),
            name=f"External Org {uuid4()[:6]}",
            code=f"EXT-{uuid4()[:8]}",
            is_active=True,
        )
        db.add(external_org)
        db.flush()

        vehicle = HealthISFVehicle(
            id=uuid4(),
            organization_id=external_org.id,
            vehicle_type="sedan",
            vehicle_plate=f"EX-{uuid4()[:6].upper()}",
            capacity=4,
            is_active=True,
        )
        db.add(vehicle)
        db.commit()
        return vehicle.id


def _ws_receive_json_with_timeout(websocket, timeout_seconds: float = 8.0):
    result_queue: queue.Queue[object] = queue.Queue(maxsize=1)

    def _target() -> None:
        try:
            result_queue.put(("ok", websocket.receive_json()))
        except Exception as exc:  # pragma: no cover - defensive capture for flaky socket behavior
            result_queue.put(("err", exc))

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    try:
        status, payload = result_queue.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise AssertionError(f"websocket receive timed out after {timeout_seconds}s") from exc

    if status == "err":
        raise AssertionError(f"websocket receive failed: {payload}")
    return payload


# ─── 1. Ride Creation ─────────────────────────────────────────────────────────

class TestRideCreation:
    def test_dispatcher_can_create_ride(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)

        payload = {
            "provider_id": provider_id,
            "passenger_name": "Alice Johnson",
            "passenger_phone": "917-555-0001",
               "service_type": "medical_transport",
            "pickup_address": "100 Broadway, New York, NY",
            "dropoff_address": "500 Park Ave, New York, NY",
            "scheduled_time": "2026-06-01T10:00:00",
            "notes": "Wheelchair accessible required",
        }
        response = client.post("/api/health-isf/rides", headers=headers, json=payload)
        assert response.status_code in {200, 201}, response.text
        data = response.json()
        assert data["passenger_name"] == "Alice Johnson"
        assert data["status"] == "pending"
        return data["id"]

    def test_driver_cannot_create_ride(self, client: TestClient):
        auth = _login(client, "driver@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_org_id("driver@amicor.local")
        provider_id = _ensure_provider(org_id)

        payload = {
            "provider_id": provider_id,
            "passenger_name": "Unauthorized User",
            "passenger_phone": "917-555-0002",
               "service_type": "medical_transport",
            "pickup_address": "1 Blocked Ln",
            "dropoff_address": "2 Blocked Ave",
        }
        response = client.post("/api/health-isf/rides", headers=headers, json=payload)
        assert response.status_code == 403, response.text

    def test_unauthenticated_cannot_create_ride(self, client: TestClient):
        response = client.post("/api/health-isf/rides", json={})
        assert response.status_code in {401, 403}


# ─── 2. Ride Assignment ───────────────────────────────────────────────────────

class TestRideAssignment:
    def _create_ride(self, client: TestClient, org_id: str, provider_id: str) -> str:
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-1111",
                   "service_type": "medical_transport",
                "pickup_address": "123 Main St",
                "dropoff_address": "456 Oak Ave",
            },
        )
        assert response.status_code in {200, 201}, response.text
        return response.json()["id"]

    def test_dispatcher_can_assign_driver_to_ride(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        driver_id = _ensure_available_driver(org_id)
        ride_id = self._create_ride(client, org_id, provider_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["driver_id"] == driver_id

    def test_cannot_assign_nonexistent_driver(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        ride_id = self._create_ride(client, org_id, provider_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": "nonexistent-driver-id"},
        )
        assert response.status_code in {400, 404, 422}, response.text


class TestRideVehicleAssignment:
    def _create_ride(self, client: TestClient, org_id: str, provider_id: str) -> str:
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        response = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Vehicle Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-3333",
                "service_type": "medical_transport",
                "pickup_address": "123 Vehicle St",
                "dropoff_address": "456 Vehicle Ave",
            },
        )
        assert response.status_code in {200, 201}, response.text
        return response.json()["id"]

    def test_dispatcher_can_assign_vehicle_to_ride_and_reload(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        vehicle_id = _ensure_vehicle(org_id, is_active=True)
        ride_id = self._create_ride(client, org_id, provider_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        assign_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-vehicle",
            headers=headers,
            json={"vehicle_id": vehicle_id},
        )
        assert assign_resp.status_code == 200, assign_resp.text
        assert assign_resp.json().get("vehicle_id") == vehicle_id

        reload_resp = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers)
        assert reload_resp.status_code == 200, reload_resp.text
        assert reload_resp.json().get("vehicle_id") == vehicle_id

    def test_dispatcher_lists_only_active_tenant_vehicles(self, client: TestClient):
        org_id = _get_org_id()
        active_vehicle_id = _ensure_vehicle(org_id, is_active=True)
        _ensure_vehicle(org_id, is_active=False)
        _ensure_external_org_vehicle()

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/vehicles/active", headers=headers)
        assert response.status_code == 200, response.text
        vehicles = response.json()
        ids = {row.get("id") for row in vehicles}

        assert active_vehicle_id in ids
        assert all(row.get("is_active") is True for row in vehicles)
        assert all(str(row.get("organization_id")) == str(org_id) for row in vehicles)

    def test_cannot_assign_inactive_vehicle(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        inactive_vehicle_id = _ensure_vehicle(org_id, is_active=False)
        ride_id = self._create_ride(client, org_id, provider_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-vehicle",
            headers=headers,
            json={"vehicle_id": inactive_vehicle_id},
        )
        assert response.status_code == 400, response.text

    def test_cannot_assign_vehicle_from_other_tenant(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        external_vehicle_id = _ensure_external_org_vehicle()
        ride_id = self._create_ride(client, org_id, provider_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-vehicle",
            headers=headers,
            json={"vehicle_id": external_vehicle_id},
        )
        assert response.status_code in {400, 403}, response.text


class TestRealtimeWebSocketFlow:
    def test_authenticated_websocket_receives_live_ride_created_event(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)

        with client.websocket_connect(
            f"/api/health-isf/ws/live/{org_id}/{auth['user_id']}?role=dispatcher&token={auth['access_token']}"
        ) as websocket:
            connected = _ws_receive_json_with_timeout(websocket)
            assert connected["type"] == "connected"

            websocket.send_json({"type": "subscribe", "subscription_type": "dispatcher_board"})
            subscribed = _ws_receive_json_with_timeout(websocket)
            assert subscribed["type"] == "subscribed"
            assert subscribed["subscription_type"] == "dispatcher_board"

            create_response = client.post(
                "/api/health-isf/rides",
                headers=headers,
                json={
                    "provider_id": provider_id,
                    "passenger_name": f"Realtime Patient {uuid4()[:6]}",
                    "passenger_phone": "917-555-3131",
                    "service_type": "medical_transport",
                    "pickup_address": "50 Realtime Way",
                    "dropoff_address": "60 Sync Ave",
                },
            )
            assert create_response.status_code in {200, 201}, create_response.text
            ride_id = create_response.json()["id"]

            event = _ws_receive_json_with_timeout(websocket, timeout_seconds=12.0)
            assert event["type"] == "event"
            assert event["event_type"] == "ride_created"
            assert event["payload"]["ride_id"] == ride_id


# ─── 3. Dispatch Status Progression ──────────────────────────────────────────

class TestDispatchStatusProgression:
    def _create_assigned_ride(self, client: TestClient) -> tuple[str, dict[str, str], str]:
        """Returns (ride_id, headers)."""
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        driver_id = _ensure_available_driver(org_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        create_resp = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Status Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-2222",
                   "service_type": "medical_transport",
                "pickup_address": "1 Status St",
                "dropoff_address": "2 Status Ave",
            },
        )
        assert create_resp.status_code in {200, 201}
        ride_id = create_resp.json()["id"]

        assign_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        assert assign_resp.status_code == 200, assign_resp.text

        assigned_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "accepted"},
        )
        assert assigned_resp.status_code == 200, assigned_resp.text
        return ride_id, headers, driver_id

    def test_status_progression_pending_to_accepted(self, client: TestClient):
        ride_id, headers, _ = self._create_assigned_ride(client)

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "accepted"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "accepted"

    def test_status_progression_to_in_transit(self, client: TestClient):
        ride_id, headers, driver_id = self._create_assigned_ride(client)

        accept = client.post(
            f"/api/health-isf/drivers/{driver_id}/accept-ride",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert accept.status_code == 200, accept.text
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
        time.sleep(0.01)

        onboard = client.post(
            f"/api/health-isf/drivers/{driver_id}/pickup-complete",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert onboard.status_code == 200, onboard.text
        time.sleep(0.01)

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "in_progress"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] in {"in_progress", "in_transit"}

    def test_driver_cannot_update_status(self, client: TestClient):
        """Drivers must not be able to set arbitrary ride status."""
        ride_id, _, _ = self._create_assigned_ride(client)

        driver_auth = _login(client, "driver@amicor.local")
        driver_headers = {"Authorization": f"Bearer {driver_auth['access_token']}"}

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=driver_headers,
            json={"status": "cancelled"},
        )
        assert response.status_code == 403, response.text

    def test_driver_assigned_queue_and_decline_persists_reassignment(self, client: TestClient):
        ride_id, headers, driver_id = self._create_assigned_ride(client)

        queue_response = client.get(
            f"/api/health-isf/drivers/{driver_id}/assigned-rides",
            headers=headers,
        )
        assert queue_response.status_code == 200, queue_response.text
        queue_rows = queue_response.json()
        matching = [row for row in queue_rows if row.get("id") == ride_id]
        assert matching, queue_rows
        assert matching[0].get("driver_id") == driver_id

        decline_response = client.post(
            f"/api/health-isf/drivers/{driver_id}/decline-ride",
            headers=headers,
            json={"ride_id": ride_id, "note": "driver_declined_test"},
        )
        assert decline_response.status_code == 200, decline_response.text
        declined = decline_response.json()
        assert declined.get("status") == "pending"

        with SessionLocal() as db:
            ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
            assert ride is not None
            assert ride.driver_id is None
            assert str(ride.lifecycle_state) == RideStatus.QUEUED.value

            assignment = (
                db.query(HealthISFDispatchAssignment)
                .filter(HealthISFDispatchAssignment.ride_id == ride_id)
                .order_by(HealthISFDispatchAssignment.updated_at.desc())
                .first()
            )
            assert assignment is not None
            assert str(assignment.assignment_state) == "reassignment_pending"
            assert assignment.rejected_at is not None

        refreshed_queue = client.get(
            f"/api/health-isf/drivers/{driver_id}/assigned-rides",
            headers=headers,
        )
        assert refreshed_queue.status_code == 200, refreshed_queue.text
        assert all(row.get("id") != ride_id for row in refreshed_queue.json())

    def test_auto_assign_persists_driver_assignment_for_driver_queue(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        driver_id = _ensure_available_driver(org_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        with SessionLocal() as db:
            driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id).first()
            assert driver is not None
            driver_phone = str(driver.phone)

        login_response = client.post(
            "/api/health-isf/drivers/login",
            headers=headers,
            json={"driver_id": driver_id, "phone": driver_phone},
        )
        assert login_response.status_code == 200, login_response.text
        session_token = login_response.json()["session_token"]

        availability_response = client.post(
            "/api/health-isf/drivers/availability",
            headers=headers,
            json={"driver_id": driver_id, "availability_state": "available", "session_token": session_token},
        )
        assert availability_response.status_code == 200, availability_response.text

        create_resp = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Auto Assign Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-2727",
                "service_type": "medical_transport",
                "pickup_address": "10 Auto Assign St",
                "dropoff_address": "20 Queue View Ave",
            },
        )
        assert create_resp.status_code in {200, 201}, create_resp.text
        ride_id = create_resp.json()["id"]

        auto_assign_response = client.post(
            "/api/health-isf/dispatch/auto-assign",
            headers=headers,
            json={"ride_id": ride_id, "offer_timeout_seconds": 90},
        )
        assert auto_assign_response.status_code == 200, auto_assign_response.text
        auto_assigned = auto_assign_response.json()
        selected_driver_id = auto_assigned.get("selected_driver_id")
        assert selected_driver_id
        assert auto_assigned.get("assignment_state") == "offered"

        queue_response = client.get(
            f"/api/health-isf/drivers/{selected_driver_id}/assigned-rides",
            headers=headers,
        )
        assert queue_response.status_code == 200, queue_response.text
        assert any(row.get("id") == ride_id for row in queue_response.json())

        with SessionLocal() as db:
            ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
            assert ride is not None
            assert str(ride.driver_id) == str(selected_driver_id)
            assert ride.assigned_at is not None

            assignment = (
                db.query(HealthISFDispatchAssignment)
                .filter(HealthISFDispatchAssignment.ride_id == ride_id)
                .order_by(HealthISFDispatchAssignment.updated_at.desc())
                .first()
            )
            assert assignment is not None
            assert str(assignment.driver_id) == str(selected_driver_id)
            assert str(assignment.assignment_state) == "offered"
            assert assignment.assigned_at is not None
            assert assignment.offer_expires_at is not None

    def test_auto_assign_without_available_driver_keeps_pending_assignment_visible(self, client: TestClient):
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        with SessionLocal() as db:
            drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == org_id).all()
            original_states = []
            for driver in drivers:
                original_states.append((driver.id, str(driver.status), str(driver.auth_state), str(driver.availability_state), bool(driver.is_online)))
                driver.status = DriverStatus.OFFLINE
                driver.auth_state = "inactive"
                driver.availability_state = "offline"
                driver.is_online = False
            db.commit()

        try:
            create_resp = client.post(
                "/api/health-isf/rides",
                headers=headers,
                json={
                    "provider_id": provider_id,
                    "passenger_name": f"No Driver Patient {uuid4()[:6]}",
                    "passenger_phone": "917-555-3838",
                    "service_type": "medical_transport",
                    "pickup_address": "30 Pending Assignment St",
                    "dropoff_address": "40 Dispatcher Watch Ave",
                },
            )
            assert create_resp.status_code in {200, 201}, create_resp.text
            ride_id = create_resp.json()["id"]

            auto_assign_response = client.post(
                "/api/health-isf/dispatch/auto-assign",
                headers=headers,
                json={"ride_id": ride_id, "offer_timeout_seconds": 90},
            )
            assert auto_assign_response.status_code == 200, auto_assign_response.text
            auto_assigned = auto_assign_response.json()
            assert auto_assigned.get("selected_driver_id") is None
            assert auto_assigned.get("assignment_state") == "pending_assignment"

            queue_response = client.get("/api/health-isf/dispatch/queue", headers=headers)
            assert queue_response.status_code == 200, queue_response.text
            queue_rows = queue_response.json()
            queue_row = next((row for row in queue_rows if row.get("ride_id") == ride_id), None)
            assert queue_row is not None
            assert queue_row.get("assignment_state") == "pending_assignment"
            assert queue_row.get("dispatcher_message") == "No available driver"

            with SessionLocal() as db:
                ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
                assert ride is not None
                assert ride.driver_id is None
                assert str(ride.lifecycle_state) == RideStatus.QUEUED.value
        finally:
            with SessionLocal() as db:
                for driver_id_value, status_value, auth_state_value, availability_state_value, is_online_value in original_states:
                    driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == driver_id_value).first()
                    if not driver:
                        continue
                    driver.status = status_value
                    driver.auth_state = auth_state_value
                    driver.availability_state = availability_state_value
                    driver.is_online = is_online_value
                db.commit()


class TestDispatcherRideCompletion:
    def _create_ready_for_completion_ride(self, client: TestClient) -> tuple[str, dict[str, str]]:
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        driver_id = _ensure_available_driver(org_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        create_resp = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Completion Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-4444",
                "service_type": "medical_transport",
                "pickup_address": "100 Completion St",
                "dropoff_address": "200 Completion Ave",
            },
        )
        assert create_resp.status_code in {200, 201}, create_resp.text
        ride_id = create_resp.json()["id"]

        assign_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        assert assign_resp.status_code == 200, assign_resp.text

        accepted_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "accepted"},
        )
        assert accepted_resp.status_code == 200, accepted_resp.text

        accept_driver_resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/accept-ride",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert accept_driver_resp.status_code == 200, accept_driver_resp.text

        en_route_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "driver_en_route"},
        )
        assert en_route_resp.status_code == 200, en_route_resp.text

        arrived_resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert arrived_resp.status_code == 200, arrived_resp.text

        onboard_resp = client.post(
            f"/api/health-isf/drivers/{driver_id}/pickup-complete",
            headers=headers,
            json={"ride_id": ride_id},
        )
        assert onboard_resp.status_code == 200, onboard_resp.text

        in_progress_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "in_progress"},
        )
        assert in_progress_resp.status_code == 200, in_progress_resp.text

        return ride_id, headers

    def test_dispatcher_can_complete_ride_and_reload_persists(self, client: TestClient):
        ride_id, headers = self._create_ready_for_completion_ride(client)

        complete_resp = client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/complete",
            headers=headers,
        )
        assert complete_resp.status_code == 200, complete_resp.text
        completed = complete_resp.json()
        assert completed.get("status") == "completed"
        assert completed.get("completed_at") is not None

        reload_resp = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers)
        assert reload_resp.status_code == 200, reload_resp.text
        reloaded = reload_resp.json()
        assert reloaded.get("status") == "completed"
        assert reloaded.get("completed_at") is not None

    def test_dispatcher_cannot_complete_other_tenant_ride(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        with SessionLocal() as db:
            external_org = HealthISFOrganization(
                id=uuid4(),
                name=f"External Completion Org {uuid4()[:6]}",
                code=f"EXT-COMP-{uuid4()[:8]}",
                is_active=True,
            )
            db.add(external_org)
            db.flush()

            external_provider = HealthISFProvider(
                id=uuid4(),
                organization_id=external_org.id,
                name=f"External Provider {uuid4()[:6]}",
                address="1 External Way",
                phone="212-555-7777",
                service_type="clinic",
                is_active=True,
            )
            db.add(external_provider)
            db.flush()

            external_ride = HealthISFRide(
                id=uuid4(),
                organization_id=external_org.id,
                provider_id=external_provider.id,
                passenger_name=f"External Rider {uuid4()[:6]}",
                passenger_phone="917-555-9999",
                pickup_address="10 External St",
                dropoff_address="20 External Ave",
                service_type="medical_transport",
                status=RideStatus.IN_PROGRESS,
                lifecycle_state=RideStatus.IN_PROGRESS.value,
            )
            db.add(external_ride)
            db.commit()
            ride_id = external_ride.id

        response = client.patch(
            f"/api/health-isf/dispatcher/rides/{ride_id}/complete",
            headers=headers,
        )
        assert response.status_code in {400, 403}, response.text


class TestDispatchLifecycleWorkflow:
    def _create_assigned_ride(self, client: TestClient) -> tuple[str, dict[str, str]]:
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        driver_id = _ensure_available_driver(org_id)

        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        create_resp = client.post(
            "/api/health-isf/rides",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Lifecycle Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-9090",
                "service_type": "medical_transport",
                "pickup_address": "10 Lifecycle St",
                "dropoff_address": "20 Lifecycle Ave",
            },
        )
        assert create_resp.status_code in {200, 201}, create_resp.text
        ride_id = create_resp.json()["id"]

        assign_resp = client.patch(
            f"/api/health-isf/rides/{ride_id}/assign-driver",
            headers=headers,
            json={"driver_id": driver_id},
        )
        assert assign_resp.status_code == 200, assign_resp.text

        return ride_id, headers

    def test_valid_lifecycle_chain_requested_to_completed(self, client: TestClient):
        ride_id, headers = self._create_assigned_ride(client)

        # Compatibility mapping accepted -> assigned (idempotent when already assigned).
        accepted = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "accepted"},
        )
        assert accepted.status_code == 200, accepted.text

        en_route = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "driver_en_route"},
        )
        assert en_route.status_code == 200, en_route.text

        arrived = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "arrived"},
        )
        assert arrived.status_code == 200, arrived.text

        onboard = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "rider_onboard"},
        )
        assert onboard.status_code == 200, onboard.text

        transporting = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "in_progress"},
        )
        assert transporting.status_code == 200, transporting.text

        completed = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "completed"},
        )
        assert completed.status_code == 200, completed.text
        payload = completed.json()
        assert payload.get("status") == "completed"
        assert payload.get("completed_at") is not None

    def test_invalid_lifecycle_transition_rejected(self, client: TestClient):
        ride_id, headers = self._create_assigned_ride(client)

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "in_progress"},
        )
        assert response.status_code in {400, 409}, response.text

    def test_stage_timestamps_persist_and_reload(self, client: TestClient):
        ride_id, headers = self._create_assigned_ride(client)

        assign_payload = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "accepted"},
        )
        assert assign_payload.status_code == 200, assign_payload.text
        assert assign_payload.json().get("assigned_at") is not None

        enroute_payload = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "driver_en_route"},
        )
        assert enroute_payload.status_code == 200, enroute_payload.text
        assert enroute_payload.json().get("enroute_at") is not None

        arrived_payload = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "arrived"},
        )
        assert arrived_payload.status_code == 200, arrived_payload.text
        assert arrived_payload.json().get("arrived_at") is not None

        pickup_payload = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "rider_onboard"},
        )
        assert pickup_payload.status_code == 200, pickup_payload.text
        assert pickup_payload.json().get("picked_up_at") is not None

        transport_payload = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "in_progress"},
        )
        assert transport_payload.status_code == 200, transport_payload.text
        assert transport_payload.json().get("transporting_at") is not None

        complete_payload = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "completed"},
        )
        assert complete_payload.status_code == 200, complete_payload.text
        assert complete_payload.json().get("completed_at") is not None

        reload_resp = client.get(f"/api/health-isf/rides/{ride_id}", headers=headers)
        assert reload_resp.status_code == 200, reload_resp.text
        reloaded = reload_resp.json()
        assert reloaded.get("assigned_at") is not None
        assert reloaded.get("enroute_at") is not None
        assert reloaded.get("arrived_at") is not None
        assert reloaded.get("picked_up_at") is not None
        assert reloaded.get("transporting_at") is not None
        assert reloaded.get("completed_at") is not None

    def test_dispatcher_cannot_update_other_tenant_ride_status(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        with SessionLocal() as db:
            external_org = HealthISFOrganization(
                id=uuid4(),
                name=f"External Lifecycle Org {uuid4()[:6]}",
                code=f"EXT-LIFE-{uuid4()[:8]}",
                is_active=True,
            )
            db.add(external_org)
            db.flush()

            external_provider = HealthISFProvider(
                id=uuid4(),
                organization_id=external_org.id,
                name=f"External Lifecycle Provider {uuid4()[:6]}",
                address="1 External Lifecycle Way",
                phone="212-555-8181",
                service_type="clinic",
                is_active=True,
            )
            db.add(external_provider)
            db.flush()

            external_ride = HealthISFRide(
                id=uuid4(),
                organization_id=external_org.id,
                provider_id=external_provider.id,
                passenger_name=f"External Lifecycle Rider {uuid4()[:6]}",
                passenger_phone="917-555-1212",
                pickup_address="30 External St",
                dropoff_address="40 External Ave",
                service_type="medical_transport",
                status=RideStatus.ACCEPTED,
                lifecycle_state=RideStatus.ASSIGNED.value,
            )
            db.add(external_ride)
            db.commit()
            ride_id = external_ride.id

        response = client.patch(
            f"/api/health-isf/rides/{ride_id}/status",
            headers=headers,
            json={"status": "driver_en_route"},
        )
        assert response.status_code in {400, 403}, response.text


class TestRecurringTransportationScheduling:
    def _dispatcher_headers(self, client: TestClient) -> dict[str, str]:
        auth = _login(client, "dispatcher@amicor.local")
        return {"Authorization": f"Bearer {auth['access_token']}"}

    def _create_schedule(
        self,
        client: TestClient,
        *,
        frequency: str,
        weekdays: list[str] | None = None,
        interval_count: int = 1,
    ) -> tuple[str, dict[str, str]]:
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)
        headers = self._dispatcher_headers(client)
        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=14)

        response = client.post(
            "/api/health-isf/recurring/schedules",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": f"Recurring Patient {uuid4()[:6]}",
                "passenger_phone": "917-555-6767",
                "pickup_address": "11 Recurring Way",
                "dropoff_address": "22 Recurring Ave",
                "service_type": "medical_transport",
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "frequency": frequency,
                "interval_count": interval_count,
                "weekdays": weekdays or [],
                "pickup_time_local": "08:30",
                "horizon_days": 14,
            },
        )
        assert response.status_code in {200, 201}, response.text
        data = response.json()
        assert data.get("id")
        return data["id"], headers

    def test_daily_generation(self, client: TestClient):
        schedule_id, headers = self._create_schedule(client, frequency="daily")
        rides_resp = client.get(f"/api/health-isf/recurring/schedules/{schedule_id}/rides", headers=headers)
        assert rides_resp.status_code == 200, rides_resp.text
        rides = rides_resp.json()
        assert len(rides) >= 5
        assert all(ride.get("recurring_schedule_id") == schedule_id for ride in rides)

    def test_weekly_generation(self, client: TestClient):
        schedule_id, headers = self._create_schedule(client, frequency="weekly")
        rides_resp = client.get(f"/api/health-isf/recurring/schedules/{schedule_id}/rides", headers=headers)
        assert rides_resp.status_code == 200, rides_resp.text
        rides = rides_resp.json()
        assert len(rides) >= 2
        assert all(ride.get("recurring_schedule_id") == schedule_id for ride in rides)

    def test_multi_day_generation_custom_weekdays(self, client: TestClient):
        schedule_id, headers = self._create_schedule(client, frequency="custom", weekdays=["mon", "wed", "fri"])
        rides_resp = client.get(f"/api/health-isf/recurring/schedules/{schedule_id}/rides", headers=headers)
        assert rides_resp.status_code == 200, rides_resp.text
        rides = rides_resp.json()
        assert len(rides) >= 4
        assert all(ride.get("recurring_schedule_id") == schedule_id for ride in rides)

    def test_pause_schedule(self, client: TestClient):
        schedule_id, headers = self._create_schedule(client, frequency="daily")
        pause_resp = client.patch(f"/api/health-isf/recurring/schedules/{schedule_id}/pause", headers=headers)
        assert pause_resp.status_code == 200, pause_resp.text
        paused = pause_resp.json()
        assert paused.get("is_active") is False

    def test_resume_schedule(self, client: TestClient):
        schedule_id, headers = self._create_schedule(client, frequency="daily")
        pause_resp = client.patch(f"/api/health-isf/recurring/schedules/{schedule_id}/pause", headers=headers)
        assert pause_resp.status_code == 200, pause_resp.text

        resume_resp = client.patch(f"/api/health-isf/recurring/schedules/{schedule_id}/resume?horizon_days=14", headers=headers)
        assert resume_resp.status_code == 200, resume_resp.text
        resumed = resume_resp.json()
        assert resumed.get("is_active") is True
        assert resumed.get("generated_ride_count", 0) > 0

    def test_tenant_protection(self, client: TestClient):
        headers = self._dispatcher_headers(client)
        with SessionLocal() as db:
            external_org = HealthISFOrganization(
                id=uuid4(),
                name=f"External Recurring Org {uuid4()[:6]}",
                code=f"EXT-RECUR-{uuid4()[:8]}",
                is_active=True,
            )
            db.add(external_org)
            db.flush()

            external_provider = HealthISFProvider(
                id=uuid4(),
                organization_id=external_org.id,
                name=f"External Recurring Provider {uuid4()[:6]}",
                address="99 External Rd",
                phone="212-555-6161",
                service_type="clinic",
                is_active=True,
            )
            db.add(external_provider)
            db.commit()
            provider_id = external_provider.id

        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        response = client.post(
            "/api/health-isf/recurring/schedules",
            headers=headers,
            json={
                "provider_id": provider_id,
                "passenger_name": "Cross Tenant Rider",
                "passenger_phone": "917-555-7878",
                "pickup_address": "10 Blocked St",
                "dropoff_address": "20 Blocked Ave",
                "service_type": "medical_transport",
                "start_date": start.isoformat(),
                "frequency": "daily",
                "interval_count": 1,
                "weekdays": [],
                "pickup_time_local": "09:00",
                "horizon_days": 7,
            },
        )
        assert response.status_code in {400, 403}, response.text

    def test_persistence_after_reload(self, client: TestClient):
        schedule_id, headers = self._create_schedule(client, frequency="daily")
        first_list = client.get("/api/health-isf/recurring/schedules", headers=headers)
        assert first_list.status_code == 200, first_list.text
        assert any(item.get("id") == schedule_id for item in first_list.json())

        rides_resp = client.get(f"/api/health-isf/recurring/schedules/{schedule_id}/rides", headers=headers)
        assert rides_resp.status_code == 200, rides_resp.text
        rides = rides_resp.json()
        assert len(rides) > 0
        assert all(row.get("recurring_schedule_id") == schedule_id for row in rides)

        second_list = client.get("/api/health-isf/recurring/schedules", headers=headers)
        assert second_list.status_code == 200, second_list.text
        assert any(item.get("id") == schedule_id for item in second_list.json())


# ─── 4. Nova Context Awareness of Live State ─────────────────────────────────

class TestNovaLiveContextAwareness:
    def test_nova_context_reflects_ride_counts(self, client: TestClient):
        """Nova /context must return live ride counts from the DB."""
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/context", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()

        summary = payload["health_isf_summary"]
        assert isinstance(summary["rides_total"], int)
        assert isinstance(summary["drivers_total"], int)
        assert isinstance(summary["drivers_available"], int)
        assert summary["dispatch_health"] in {"healthy", "stable", "degraded", "watch", "critical", "needs_attention"}

    def test_nova_intelligence_reflects_live_org(self, client: TestClient):
        """Nova /intelligence must return organization_id scoped to the logged-in user."""
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_org_id()

        response = client.get("/api/nova/intelligence", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()

        assert payload["organization_id"] == org_id


# ─── 5. Provider Actions ──────────────────────────────────────────────────────

class TestProviderActions:
    def test_dispatcher_can_update_provider(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}
        org_id = _get_org_id()
        provider_id = _ensure_provider(org_id)

        response = client.patch(
            f"/api/health-isf/providers/{provider_id}",
            headers=headers,
            json={"phone": "212-555-9999"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["phone"] == "212-555-9999"

    def test_dispatcher_can_list_providers(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/health-isf/providers", headers=headers)
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), list)


# ─── 6. AI Dispatch Recommendations ──────────────────────────────────────────

class TestAIDispatchRecommendations:
    def test_nova_status_includes_ai_recommendations(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get("/api/nova/status", headers=headers)
        assert response.status_code == 200, response.text
        payload = response.json()

        assert "next_recommended_action" in payload
        assert isinstance(payload["next_recommended_action"], str)
        assert len(payload["next_recommended_action"]) > 0

    def test_nova_next_step_returns_dispatch_actions(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.post(
            "/api/nova/next-step",
            headers=headers,
            json={"mode": "dispatch_supervisor"},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert isinstance(payload["checklist"], list)
        assert len(payload["checklist"]) > 0


# ─── 7. Cross-tenant denial ───────────────────────────────────────────────────

class TestCrossTenantDenial:
    def test_nova_cross_tenant_raises_403(self, client: TestClient):
        """Requesting another org's Nova context must be denied."""
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get(
            "/api/nova/context",
            headers=headers,
            params={"organization_id": "attacker-org-00000000"},
        )
        assert response.status_code in {400, 403}, response.text

    def test_nova_intelligence_cross_tenant_raises_403(self, client: TestClient):
        auth = _login(client, "dispatcher@amicor.local")
        headers = {"Authorization": f"Bearer {auth['access_token']}"}

        response = client.get(
            "/api/nova/intelligence",
            headers=headers,
            params={"organization_id": "attacker-org-00000000"},
        )
        assert response.status_code in {400, 403}, response.text
