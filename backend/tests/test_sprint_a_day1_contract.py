from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.auth import ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFProvider


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login_dispatcher(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": "Amicor123!"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("access_token")
    return payload


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
            name=f"Day1 Provider {uuid4()[:6]}",
            address="500 Day1 Ave",
            phone="212-555-6109",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def test_customer_request_rejects_same_pickup_and_dropoff(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}

    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": "Contract Validation Rider",
            "rider_phone": "+1 212-555-6100",
            "pickup_address": "100 Same Street",
            "dropoff_address": "100 Same Street",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 422, response.text


def test_customer_request_rejects_past_scheduled_time(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    stale_time = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()

    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": "Past Schedule Rider",
            "rider_phone": "+1 212-555-6101",
            "pickup_address": "101 Intake Lane",
            "dropoff_address": "201 Authorization Ave",
            "scheduled_time": stale_time,
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 422, response.text


def test_customer_request_adapter_stub_is_non_blocking(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_dispatcher_org_id())

    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": "Adapter Stub Rider",
            "rider_phone": "+1 212-555-6102",
            "pickup_address": "120 Startup Blvd",
            "dropoff_address": "220 Care Clinic",
            "ride_type": "healthcare",
            "recurring": True,
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload.get("dispatch_status") == "pending"
    assert payload.get("id")
    assert payload.get("ride_id")
