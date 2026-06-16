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
            name=f"Phase51 Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"P51-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.8,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict, rider_phone: str, suffix: str) -> dict:
    payload = {
        "pickup_address": "100 Phase51 Pickup, New York, NY 10001",
        "dropoff_address": "200 Phase51 Dropoff, New York, NY 10002",
        "rider_name": f"Phase51 Rider {suffix}",
        "rider_phone": rider_phone,
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "phase51 live dispatch simulation test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_phase51_driver_workspace_and_route_progression(client: TestClient) -> None:
    dispatcher = _login(client, "dispatcher@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")

    driver_id = _ensure_available_driver(org_id)
    rider_phone = "+1 212-555-5151"
    req = _create_customer_request(client, dispatcher_headers, rider_phone, "route")

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{req['id']}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{req['id']}/assign-driver",
        headers=dispatcher_headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    workspace = client.get(
        f"/api/health-isf/drivers/{driver_id}/live-workspace",
        headers=dispatcher_headers,
    )
    assert workspace.status_code == 200, workspace.text
    workspace_payload = workspace.json()
    assert workspace_payload["driver_id"] == driver_id

    for state in ["en_route_pickup", "arrived_pickup", "rider_loaded"]:
        progress = client.post(
            f"/api/health-isf/drivers/{driver_id}/route-progress",
            headers=dispatcher_headers,
            json={"target_state": state, "ride_id": req["ride_id"]},
        )
        assert progress.status_code == 200, progress.text

    tracking = client.get(
        "/api/health-isf/customers/workspace/live-tracking",
        headers=dispatcher_headers,
        params={"rider_phone": rider_phone, "limit": 80},
    )
    assert tracking.status_code == 200, tracking.text
    tracking_payload = tracking.json()
    assert tracking_payload.get("rider_phone") == rider_phone
    assert "timeline" in tracking_payload


def test_phase51_admin_live_operations_and_interventions(client: TestClient) -> None:
    dispatcher = _login(client, "dispatcher@amicor.local")
    admin = _login(client, "admin@amicor.local")
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher['access_token']}"}
    admin_headers = {"Authorization": f"Bearer {admin['access_token']}"}

    org_id = _org_id_for("dispatcher@amicor.local")
    primary_driver = _ensure_available_driver(org_id)
    backup_driver = _ensure_available_driver(org_id)

    req = _create_customer_request(client, dispatcher_headers, "+1 212-555-5152", "admin")

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{req['id']}/approve",
        headers=dispatcher_headers,
    )
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{req['id']}/assign-driver",
        headers=dispatcher_headers,
        json={"driver_id": primary_driver},
    )
    assert assign.status_code == 200, assign.text

    alerts_resp = client.get("/api/health-isf/admin/dispatch-alerts", headers=admin_headers)
    assert alerts_resp.status_code == 200, alerts_resp.text
    alerts_payload = alerts_resp.json()
    assert "alerts" in alerts_payload
    assert "counters" in alerts_payload

    live_ops_resp = client.get("/api/health-isf/admin/live-operations", headers=admin_headers)
    assert live_ops_resp.status_code == 200, live_ops_resp.text
    live_ops = live_ops_resp.json()
    assert "active_rides" in live_ops
    assert "driver_availability_board" in live_ops

    active_assignments = client.get("/api/health-isf/dispatch/active-assignments", headers=admin_headers)
    assert active_assignments.status_code == 200, active_assignments.text
    active_rows = active_assignments.json()
    offered_row = next((row for row in active_rows if row.get("assignment_state") == "offered" and row.get("ride_id") == req["ride_id"]), None)
    if offered_row is not None:
        force_expire = client.post(
            "/api/health-isf/admin/force-expire-assignment",
            headers=admin_headers,
            json={"offer_id": offered_row["offer_id"], "reason": "phase51_test_expire"},
        )
        assert force_expire.status_code == 200, force_expire.text

    reassign = client.post(
        "/api/health-isf/admin/reassign-driver",
        headers=admin_headers,
        json={"ride_id": req["ride_id"], "driver_id": backup_driver, "reason": "phase51_test_reassign"},
    )
    assert reassign.status_code == 200, reassign.text
    reassign_payload = reassign.json()
    assert reassign_payload.get("ride")
