from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    payload = _login(client, email)
    return {"Authorization": f"Bearer {payload['access_token']}"}


def _get_org_id(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return user.organization_id


def _create_driver(org_id: str) -> HealthISFDriver:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=org_id,
            name=f"Revenue Driver {uuid4()[:6]}",
            phone=f"917555{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"REV-{str(uuid4())[:6].upper()}",
            status=DriverStatus.AVAILABLE,
            auth_state="active",
            availability_state="available",
            is_online=True,
        )
        db.add(driver)
        db.commit()
        db.refresh(driver)
        return driver


def test_revenue_pilot_manual_workflow_persists_end_to_end(client: TestClient) -> None:
    rider_headers = _auth_headers(client, "rider@amicor.local")
    dispatcher_headers = _auth_headers(client, "dispatcher@amicor.local")
    driver_headers = _auth_headers(client, "driver@amicor.local")
    admin_headers = _auth_headers(client, "admin@amicor.local")
    rider_phone = "+1555" + "".join(ch for ch in str(uuid4()) if ch.isdigit())[:7]

    org_id = _get_org_id("dispatcher@amicor.local")
    driver = _create_driver(org_id)

    create_response = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": "Revenue Pilot Rider",
            "rider_phone": rider_phone,
            "pickup_address": "101 Revenue Way",
            "dropoff_address": "202 Care Ave",
            "ride_type": "healthcare",
            "notes": "Wheelchair support requested",
        },
    )
    assert create_response.status_code == 201, create_response.text
    request_payload = create_response.json()
    request_id = request_payload["id"]
    ride_id = request_payload["ride_id"]
    assert request_payload["dispatch_status"] == "pending"

    approve_response = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve",
        headers=dispatcher_headers,
    )
    assert approve_response.status_code == 200, approve_response.text
    assert approve_response.json()["request"]["dispatch_status"] == "approved"

    requests_response = client.get(
        "/api/health-isf/customer-requests?limit=50",
        headers=dispatcher_headers,
    )
    assert requests_response.status_code == 200, requests_response.text
    request_rows = requests_response.json()
    assert any(item["id"] == request_id and item["ride_id"] == ride_id for item in request_rows)

    assign_response = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=dispatcher_headers,
        json={"driver_id": driver.id},
    )
    assert assign_response.status_code == 200, assign_response.text
    assigned_payload = assign_response.json()
    assert assigned_payload["request"]["dispatch_status"] == "assigned"
    assert assigned_payload["ride"]["driver_id"] == driver.id

    active_assignments_response = client.get(
        "/api/health-isf/dispatch/active-assignments?limit=50",
        headers=dispatcher_headers,
    )
    assert active_assignments_response.status_code == 200, active_assignments_response.text
    active_assignments = active_assignments_response.json()
    assert any(item["ride_id"] == ride_id and item["driver_id"] == driver.id for item in active_assignments)

    driver_workspace_response = client.get(
        f"/api/health-isf/drivers/{driver.id}/live-workspace",
        headers=dispatcher_headers,
    )
    assert driver_workspace_response.status_code == 200, driver_workspace_response.text
    driver_workspace = driver_workspace_response.json()
    assert driver_workspace["driver_id"] == driver.id
    assert driver_workspace["active_ride"]["id"] == ride_id

    for target_state in ["en_route_pickup", "arrived_pickup", "rider_loaded"]:
        progress_response = client.post(
            f"/api/health-isf/drivers/{driver.id}/route-progress",
            headers=dispatcher_headers,
            json={"ride_id": ride_id, "target_state": target_state},
        )
        assert progress_response.status_code == 200, progress_response.text

    progress_action_response = client.post(
        "/api/ops/workspace/action?role_view=driver",
        headers=driver_headers,
        json={
            "action_type": "driver.update_route_progress",
            "payload": {"trip_id": ride_id, "driver_id": driver.id, "route_progress_percent": 90},
        },
    )
    assert progress_action_response.status_code == 200, progress_action_response.text

    complete_action_response = client.post(
        "/api/ops/workspace/action?role_view=driver",
        headers=driver_headers,
        json={
            "action_type": "driver.complete_trip",
            "payload": {"trip_id": ride_id, "driver_id": driver.id},
        },
    )
    assert complete_action_response.status_code == 200, complete_action_response.text

    history_response = client.get(
        "/api/health-isf/customers/workspace/history?rider_phone=" + rider_phone.replace("+", "%2B") + "&limit=20",
        headers=rider_headers,
    )
    assert history_response.status_code == 200, history_response.text
    history_payload = history_response.json()
    history_rows = history_payload.get("history") or []
    matching_history = [row for row in history_rows if row["ride_id"] == ride_id]
    assert matching_history
    assert matching_history[0]["dispatch_status"] == "completed"

    active_rider_response = client.get(
        "/api/health-isf/customers/workspace/active?rider_phone=" + rider_phone.replace("+", "%2B"),
        headers=rider_headers,
    )
    assert active_rider_response.status_code == 200, active_rider_response.text
    assert active_rider_response.json().get("active_ride") is None

    activity_feed_response = client.get(
        "/api/health-isf/activity-feed?limit=100",
        headers=admin_headers,
    )
    assert activity_feed_response.status_code == 200, activity_feed_response.text
    activities = activity_feed_response.json()["activities"]
    ride_activities = [item for item in activities if item.get("ride_id") == ride_id]
    assert ride_activities
    actions = {item["action"] for item in ride_activities}
    assert any(action in actions for action in {"customer_ride_requested", "customer-request-approved", "assignment-issued"})
    assert any(action in actions for action in {"trip-completed", "ride_completed", "completed"})