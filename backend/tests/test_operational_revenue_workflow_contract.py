from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
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
            name=f"Revenue Contract Provider {uuid4()[:6]}",
            address="500 Runtime Ave",
            phone="212-555-6100",
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
            name=f"Revenue Contract Driver {uuid4()[:6]}",
            phone=f"646-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"RVC-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_online=True,
            auth_state="active",
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict) -> dict:
    payload = {
        "pickup_address": "11 Runtime Blvd, New York, NY 10001",
        "dropoff_address": "88 Revenue Pkwy, New York, NY 10010",
        "rider_name": f"Revenue Rider {uuid4()[:6]}",
        "rider_phone": "+1 212-555-9088",
        "ride_type": "healthcare",
        "recurring": False,
        "notes": "operational revenue workflow contract test",
    }
    response = client.post("/api/health-isf/customer-requests", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def _run_full_operational_flow(client: TestClient, headers: dict, request_id: str, ride_id: str, driver_id: str) -> None:
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

    onboard = client.post(
        f"/api/health-isf/drivers/{driver_id}/pickup-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert onboard.status_code == 200, onboard.text

    in_progress = client.patch(
        f"/api/health-isf/rides/{ride_id}/status",
        headers=headers,
        json={"status": "in_progress"},
    )
    assert in_progress.status_code == 200, in_progress.text

    complete = client.post(
        f"/api/health-isf/drivers/{driver_id}/dropoff-complete",
        headers=headers,
        json={"ride_id": ride_id},
    )
    assert complete.status_code == 200, complete.text


def test_revenue_workflow_timeline_contract_and_ordering(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "0")
    monkeypatch.setattr(
        "app.modules.health_isf.service._is_intake_auto_dispatch_enabled",
        lambda db, organization_id: False,
    )
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ = _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    created = _create_customer_request(client, headers)
    request_id = created["id"]
    ride_id = created["ride_id"]

    _run_full_operational_flow(client, headers, request_id, ride_id, driver_id)

    response = client.get(
        f"/api/health-isf/operations/revenue-workflow?ride_id={ride_id}&window_hours=24",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["ride_id"] == ride_id
    assert payload["lifecycle_contract"]["version"] == "v1"
    assert payload["lifecycle_contract"]["append_only_timeline"] is True

    timeline = payload["timeline"]
    assert isinstance(timeline, list)
    assert len(timeline) > 0

    sequences = [int(item["sequence"]) for item in timeline]
    assert sequences == sorted(sequences)

    event_types = {str(item.get("event_type")) for item in timeline}
    assert "request_created" in event_types
    assert "assigned" in event_types
    assert "accepted" in event_types
    assert "arrived" in event_types
    assert "onboarded" in event_types
    assert "completed" in event_types


def test_revenue_workflow_kpis_are_runtime_derived(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/health-isf/operations/revenue-workflow?window_hours=24", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    kpis = payload["kpis"]

    assert kpis["derived_from"] == "runtime_event_history_and_runtime_state"
    assert isinstance(kpis["completed_trips"], int)
    assert isinstance(kpis["cancellation_loss"], (int, float))
    assert isinstance(kpis["assignment_latency"]["seconds"], (int, float))
    assert isinstance(kpis["active_rides"], int)
    assert isinstance(kpis["driver_utilization"]["percent"], (int, float))
    assert isinstance(kpis["rides_per_hour"], (int, float))
    assert isinstance(kpis["dispatcher_load"]["index"], (int, float))
    assert isinstance(kpis["operational_sla_alerts"], list)


def test_revenue_workflow_role_streams_share_single_contract(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/health-isf/operations/revenue-workflow?window_hours=24", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    role_streams = payload["role_streams"]
    assert set(role_streams.keys()) == {"dispatcher", "driver", "rider", "operations"}

    for role, stream in role_streams.items():
        assert isinstance(stream, list)
        for event in stream:
            assert "event_id" in event
            assert "sequence" in event
            assert "event_type" in event
            assert "role_scope" in event
            assert role in list(event.get("role_scope") or [])

    dispatcher_types = {str(event.get("event_type")) for event in role_streams["dispatcher"]}
    rider_types = {str(event.get("event_type")) for event in role_streams["rider"]}
    assert len(dispatcher_types.intersection(rider_types)) >= 1
