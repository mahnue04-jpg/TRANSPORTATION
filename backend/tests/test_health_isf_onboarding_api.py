from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFWorkflowAuditLog


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _get_org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return user.organization_id


def test_post_provider_is_tenant_scoped_and_idempotent(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Idempotency-Key": f"provider-onboard:{uuid4()}",
    }
    org_id = _get_org_id()

    payload = {
        "name": f"Onboarding Provider {uuid4()[:8]}",
        "address": "11 Onboarding Way",
        "phone": f"212-555-{str(uuid4().replace('-', ''))[:4]}",
        "service_type": "clinic",
    }

    first = client.post("/api/health-isf/providers", headers=headers, json=payload)
    second = client.post("/api/health-isf/providers", headers=headers, json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code in {200, 201}, second.text
    assert first.json()["id"] == second.json()["id"]

    provider_id = first.json()["id"]
    with SessionLocal() as db:
        onboarding_audit = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == org_id,
                HealthISFWorkflowAuditLog.event_type == "workflow.onboarding.provider.created",
            )
            .all()
        )
        assert any(provider_id in str(row.payload or "") for row in onboarding_audit)



def test_post_driver_duplicate_guard_and_audit_event(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_org_id()

    phone = f"917-555-{str(uuid4().replace('-', ''))[:4]}"
    first_payload = {
        "name": f"Driver {uuid4()[:6]}",
        "phone": phone,
        "vehicle_type": "sedan",
        "vehicle_plate": f"DR-{uuid4()[:6].upper()}",
    }
    second_payload = {
        "name": f"Driver Dup {uuid4()[:6]}",
        "phone": phone,
        "vehicle_type": "sedan",
        "vehicle_plate": f"DR-{uuid4()[:6].upper()}",
    }

    first = client.post("/api/health-isf/drivers", headers=headers, json=first_payload)
    duplicate = client.post("/api/health-isf/drivers", headers=headers, json=second_payload)

    assert first.status_code == 201, first.text
    assert duplicate.status_code == 409, duplicate.text

    driver_id = first.json()["id"]
    with SessionLocal() as db:
        onboarding_audit = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == org_id,
                HealthISFWorkflowAuditLog.event_type == "workflow.onboarding.driver.created",
            )
            .all()
        )
        assert any(driver_id in str(row.payload or "") for row in onboarding_audit)



def test_post_vehicle_idempotent_and_duplicate_guard(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    org_id = _get_org_id()
    plate = f"VH-{uuid4()[:6].upper()}"

    first_headers = {
        "Authorization": f"Bearer {auth['access_token']}",
        "X-Idempotency-Key": f"vehicle-onboard:{uuid4()}",
    }
    first_payload = {
        "vehicle_type": "van",
        "vehicle_plate": plate,
        "capacity": 6,
    }

    first = client.post("/api/health-isf/vehicles", headers=first_headers, json=first_payload)
    same = client.post("/api/health-isf/vehicles", headers=first_headers, json=first_payload)

    assert first.status_code == 201, first.text
    assert same.status_code in {200, 201}, same.text
    assert first.json()["id"] == same.json()["id"]
    assert first.json()["organization_id"] == org_id

    duplicate = client.post(
        "/api/health-isf/vehicles",
        headers={"Authorization": f"Bearer {auth['access_token']}"},
        json={
            "vehicle_type": "van",
            "vehicle_plate": plate,
            "capacity": 4,
        },
    )
    assert duplicate.status_code == 409, duplicate.text



def test_bootstrap_workflow_uses_public_onboarding_apis(client: TestClient):
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _get_org_id()

    provider_resp = client.post(
        "/api/health-isf/providers",
        headers=headers,
        json={
            "name": f"Bootstrap Provider {uuid4()[:6]}",
            "address": "200 Bootstrap Ave",
            "phone": f"212-555-{str(uuid4().replace('-', ''))[:4]}",
            "service_type": "clinic",
        },
    )
    assert provider_resp.status_code == 201, provider_resp.text
    provider_id = provider_resp.json()["id"]

    driver_resp = client.post(
        "/api/health-isf/drivers",
        headers=headers,
        json={
            "name": f"Bootstrap Driver {uuid4()[:6]}",
            "phone": f"917-555-{str(uuid4().replace('-', ''))[:4]}",
            "vehicle_type": "sedan",
            "vehicle_plate": f"BT-{uuid4()[:6].upper()}",
        },
    )
    assert driver_resp.status_code == 201, driver_resp.text

    vehicle_resp = client.post(
        "/api/health-isf/vehicles",
        headers=headers,
        json={
            "vehicle_type": "van",
            "vehicle_plate": f"BV-{uuid4()[:6].upper()}",
            "capacity": 5,
        },
    )
    assert vehicle_resp.status_code == 201, vehicle_resp.text

    ride_resp = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json={
            "provider_id": provider_id,
            "passenger_name": f"Rider {uuid4()[:6]}",
            "passenger_phone": "917-555-0111",
            "pickup_address": "100 Main St, New York, NY 10001",
            "dropoff_address": "200 Park Ave, New York, NY 10002",
            "service_type": "medical_transport",
            "estimated_distance_miles": 5.1,
        },
    )
    assert ride_resp.status_code == 201, ride_resp.text
    assert ride_resp.json()["organization_id"] == org_id

    with SessionLocal() as db:
        operational_rows = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == org_id,
                HealthISFWorkflowAuditLog.event_type.like("operational.event_bus.%"),
            )
            .count()
        )
        assert operational_rows > 0
