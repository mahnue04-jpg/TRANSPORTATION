from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFProvider
from app.modules.health_isf.runtime_state_manager import get_live_transport_runtime_manager
from app.modules.health_isf.service_categories import (
    ServiceCategory,
    SERVICE_CATEGORY_CONFIG,
)


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
            name=f"Phase53 Provider {uuid4()[:6]}",
            address="300 Phase53 Provider Way",
            phone="212-555-5311",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ride_payload(provider_id: str, service_type: str) -> dict:
    return {
        "passenger_name": f"Phase53 Rider {uuid4()[:6]}",
        "passenger_phone": "+1 212-555-5312",
        "pickup_address": "10 Phase53 Pickup",
        "dropoff_address": "20 Phase53 Dropoff",
        "service_type": service_type,
        "provider_id": provider_id,
        "estimated_distance_miles": 4.0,
    }


def test_phase53_service_category_config_inactive_future_categories() -> None:
    assert SERVICE_CATEGORY_CONFIG[ServiceCategory.FUTURE_MEDICAL_LOGISTICS].active is False
    assert SERVICE_CATEGORY_CONFIG[ServiceCategory.FUTURE_MEDICAL_LOGISTICS].execution_enabled is False
    assert SERVICE_CATEGORY_CONFIG[ServiceCategory.FUTURE_PHARMACY_DELIVERY].active is False
    assert SERVICE_CATEGORY_CONFIG[ServiceCategory.FUTURE_PHARMACY_DELIVERY].execution_enabled is False


def test_phase53_create_ride_normalizes_transport_category(client: TestClient) -> None:
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")
    provider_id = _ensure_provider(org_id)

    response = client.post("/api/health-isf/rides", headers=headers, json=_ride_payload(provider_id, "healthcare"))
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload.get("service_type") == "medical_transport"


def test_phase53_future_categories_fail_closed(client: TestClient) -> None:
    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id_for("dispatcher@amicor.local")
    provider_id = _ensure_provider(org_id)

    response = client.post(
        "/api/health-isf/rides",
        headers=headers,
        json=_ride_payload(provider_id, "future_medical_logistics"),
    )
    assert response.status_code == 400, response.text
    assert "inactive" in str(response.text).lower()


def test_phase53_service_categories_endpoint(client: TestClient) -> None:
    auth = _login(client, "admin@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.get("/api/health-isf/operations/service-categories", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("transportation_first") is True
    categories = payload.get("categories", [])
    assert isinstance(categories, list)
    keys = {item.get("key") for item in categories}
    assert "medical_transport" in keys
    assert "future_medical_logistics" in keys


def test_phase53_runtime_replay_monotonic_and_deduplicated() -> None:
    manager = get_live_transport_runtime_manager()
    org_id = f"phase53-org-{uuid4()[:8]}"

    first = manager.record_lifecycle_event(
        organization_id=org_id,
        event_name="driver_assigned",
        role_scope=["admin", "dispatcher"],
        details={
            "ride_id": "ride-1",
            "driver_id": "driver-1",
            "request_id": "req-1",
            "assignment_id": "assign-1",
            "lifecycle_state": "assigned",
        },
    )
    second = manager.record_lifecycle_event(
        organization_id=org_id,
        event_name="driver_assigned",
        role_scope=["admin", "dispatcher"],
        details={
            "ride_id": "ride-1",
            "driver_id": "driver-1",
            "request_id": "req-1",
            "assignment_id": "assign-1",
            "lifecycle_state": "assigned",
        },
    )

    assert first.get("sequence") == second.get("sequence")

    replay = manager.replay(org_id, after_sequence=0, limit=10)
    assert replay.get("sequence_monotonic") is True
    events = replay.get("events", [])
    assert isinstance(events, list)
    assert len(events) == 1

    reconciliation = manager.reconcile(org_id, rides=[], drivers=[], providers=[])
    assert reconciliation.get("reconciliation_safe") is True
