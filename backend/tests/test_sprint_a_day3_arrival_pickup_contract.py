from fastapi.testclient import TestClient
import pytest

from app.auth import ensure_auth_schema, seed_default_users
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
        json={"email": "dispatcher@amicor.local", "password": "Amicor123!"},
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
            name=f"Day3 Provider {uuid4()[:6]}",
            address="700 Day3 Ave",
            phone="212-555-6377",
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
            name=f"Day3 Driver {uuid4()[:6]}",
            phone=f"212-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"D3-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            is_active=True,
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def _create_customer_request(client: TestClient, headers: dict) -> dict:
    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"Day3 Rider {uuid4()[:6]}",
            "rider_phone": "+1 212-555-6388",
            "pickup_address": "100 Arrival St",
            "dropoff_address": "200 Pickup Ave",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_arrival_status_endpoint_tracks_evidence_and_state(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    request_row = _create_customer_request(client, headers)

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/approve",
        headers=headers,
    )
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    pre = client.get(f"/api/health-isf/rides/{request_row['ride_id']}/arrival-status", headers=headers)
    assert pre.status_code == 200, pre.text
    pre_payload = pre.json()
    assert pre_payload["arrived"] is False

    arrived = client.post(
        f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
        headers=headers,
        json={"ride_id": request_row["ride_id"]},
    )
    assert arrived.status_code == 200, arrived.text

    post = client.get(f"/api/health-isf/rides/{request_row['ride_id']}/arrival-status", headers=headers)
    assert post.status_code == 200, post.text
    payload = post.json()
    assert payload["arrived"] is True
    assert payload["evidence_event_id"]
    assert payload["evidence_source"] == "driver_arrived_pickup"


def test_pickup_status_endpoint_tracks_evidence_and_progression(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    driver_id = _ensure_driver(org_id)

    request_row = _create_customer_request(client, headers)

    approve = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/approve",
        headers=headers,
    )
    assert approve.status_code == 200, approve.text

    assign = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_row['id']}/assign-driver",
        headers=headers,
        json={"driver_id": driver_id},
    )
    assert assign.status_code == 200, assign.text

    pre = client.get(f"/api/health-isf/rides/{request_row['ride_id']}/pickup-status", headers=headers)
    assert pre.status_code == 200, pre.text
    pre_payload = pre.json()
    assert pre_payload["picked_up"] is False

    arrived = client.post(
        f"/api/health-isf/drivers/{driver_id}/arrived-pickup",
        headers=headers,
        json={"ride_id": request_row["ride_id"]},
    )
    assert arrived.status_code == 200, arrived.text

    picked = client.post(
        f"/api/health-isf/drivers/{driver_id}/pickup-complete",
        headers=headers,
        json={"ride_id": request_row["ride_id"]},
    )
    assert picked.status_code == 200, picked.text

    post = client.get(f"/api/health-isf/rides/{request_row['ride_id']}/pickup-status", headers=headers)
    assert post.status_code == 200, post.text
    payload = post.json()
    assert payload["picked_up"] is True
    assert payload["in_progress"] is True
    assert payload["evidence_event_id"]
    assert payload["evidence_source"] in {"driver_pickup_complete"}
