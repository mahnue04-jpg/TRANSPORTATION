from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

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


def _login_dispatcher(client: TestClient) -> dict:
    response = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
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
        existing = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if existing:
            return str(existing.id)

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Phase49 Provider {uuid4()[:6]}",
            address="400 Phase49 Way",
            phone="212-555-0199",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_available_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Phase49 Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"P49-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.8,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict, rider_tag: str) -> dict:
    payload = {
        "pickup_address": "100 Clinic Way, New York, NY 10001",
        "dropoff_address": "200 Wellness Ave, New York, NY 10002",
        "rider_name": f"Phase49 Rider {rider_tag}",
        "rider_phone": "+1 212-555-0101",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "phase49 end-to-end workflow test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_phase49_customer_request_status_support_and_metrics(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    created = _create_customer_request(client, headers, "metrics")
    request_id = created["id"]

    approved = client.patch(
        f"/api/health-isf/customer-requests/{request_id}/status",
        headers=headers,
        json={"dispatch_status": "approved"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["dispatch_status"] == "approved"

    dispatchable = client.patch(
        f"/api/health-isf/customer-requests/{request_id}/status",
        headers=headers,
        json={"dispatch_status": "dispatchable"},
    )
    assert dispatchable.status_code == 200, dispatchable.text
    assert dispatchable.json()["dispatch_status"] == "dispatchable"

    metrics_resp = client.get("/api/health-isf/customer-requests/metrics", headers=headers)
    assert metrics_resp.status_code == 200, metrics_resp.text
    metrics = metrics_resp.json()
    assert "approved" in metrics
    assert "dispatchable" in metrics


def test_phase49_dispatcher_customer_request_controls_and_workflow_proof(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    driver_id = _ensure_available_driver(org_id)

    created = _create_customer_request(client, headers, "controls")
    request_id = created["id"]
    ride_id = created["ride_id"]

    approve_resp = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers)
    assert approve_resp.status_code == 200, approve_resp.text
    assert approve_resp.json()["request"]["dispatch_status"] == "approved"

    assign_resp = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign_resp.status_code == 200, assign_resp.text
    assert assign_resp.json()["request"]["dispatch_status"] == "assigned"

    accept_resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/accept-ride",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert accept_resp.status_code in {200, 409}, accept_resp.text

    arrived_resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert arrived_resp.status_code in {200, 409}, arrived_resp.text

    pickup_resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/pickup-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert pickup_resp.status_code in {200, 409}, pickup_resp.text

    dropoff_resp = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert dropoff_resp.status_code in {200, 400, 409}, dropoff_resp.text

    workflow_resp = client.get(f"/api/health-isf/rides/{ride_id}/workflow-path", headers=headers)
    assert workflow_resp.status_code == 200, workflow_resp.text
    workflow = workflow_resp.json()
    assert workflow["ride_id"] == ride_id
    assert "proof" in workflow
    assert bool(workflow["proof"].get("customer_request_submitted")) is True
    assert bool(workflow["proof"].get("audit_timeline_available")) is True

    completed = client.patch(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/complete",
        headers=headers,
        json={"reason": "phase49 test completion"},
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["request"]["dispatch_status"] == "completed"


def test_phase49_dispatcher_customer_request_cancel_wrapper(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    driver_id = _ensure_available_driver(org_id)

    created = _create_customer_request(client, headers, "cancel")
    request_id = created["id"]

    approve_resp = client.post(f"/api/health-isf/dispatcher/customer-requests/{request_id}/approve", headers=headers)
    assert approve_resp.status_code == 200, approve_resp.text

    assign_resp = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign_resp.status_code == 200, assign_resp.text

    cancel_resp = client.patch(
        f"/api/health-isf/dispatcher/customer-requests/{request_id}/cancel",
        headers=headers,
        json={"reason": "phase49 cancel wrapper validation"},
    )
    assert cancel_resp.status_code in {200, 400}, cancel_resp.text
    if cancel_resp.status_code == 200:
        assert cancel_resp.json()["request"]["dispatch_status"] == "cancelled"
    else:
        assert "invalid target state" in str(cancel_resp.json().get("detail", "")).lower()
