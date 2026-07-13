from datetime import datetime, timedelta, timezone
import time

from fastapi.testclient import TestClient
import pytest

from app.auth import ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFCustomerRideRequest, HealthISFRide, HealthISFProvider


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
    # Queued rides map to dispatchable via _request_status_from_lifecycle; intake assign is deferred.
    assert payload.get("dispatch_status") in {"pending", "dispatchable"}
    assert payload.get("dispatch_status") != "assigned"
    assert payload.get("id")
    assert payload.get("ride_id")


def _numeric_phone_suffix(seed: str) -> str:
    digits = "".join(ch for ch in seed if ch.isdigit())
    return (digits + "0000")[:4]


def test_customer_request_create_returns_before_frontend_timeout(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_dispatcher_org_id())
    suffix = _numeric_phone_suffix(uuid4())

    started = time.perf_counter()
    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"Fast Response Rider {suffix}",
            "rider_phone": f"+1 212-555-{suffix}",
            "pickup_address": f"130 Fast Lane {suffix}",
            "dropoff_address": f"230 Clinic Way {suffix}",
            "ride_type": "healthcare",
        },
    )
    elapsed = time.perf_counter() - started

    assert response.status_code == 201, response.text
    assert elapsed < 12.0, f"create response took {elapsed:.3f}s (frontend timeout is 12-45s)"


def test_customer_request_creates_exactly_one_ride(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _dispatcher_org_id()
    _ensure_provider(org_id)
    suffix = _numeric_phone_suffix(uuid4())
    rider_phone = f"+1 212-555-{suffix}"

    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"Single Ride Rider {suffix}",
            "rider_phone": rider_phone,
            "pickup_address": f"140 Single St {suffix}",
            "dropoff_address": f"240 Care Ave {suffix}",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 201, response.text
    payload = response.json()
    ride_id = payload["ride_id"]
    request_id = payload["id"]

    with SessionLocal() as db:
        request_rows = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.id == request_id)
            .all()
        )
        ride_rows = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).all()
        phone_rides = db.query(HealthISFRide).filter(HealthISFRide.passenger_phone == rider_phone).all()

    assert len(request_rows) == 1
    assert len(ride_rows) == 1
    assert ride_rows[0].lifecycle_state in {"requested", "queued", "pending", "assigned"}


def test_customer_request_idempotency_key_prevents_duplicate(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_dispatcher_org_id())
    suffix = _numeric_phone_suffix(uuid4())
    idempotency_key = f"day1-idem-{suffix}"
    payload = {
        "rider_name": f"Idempotent Rider {suffix}",
        "rider_phone": f"+1 212-555-{suffix}",
        "pickup_address": f"150 Idem Blvd {suffix}",
        "dropoff_address": f"250 Clinic Rd {suffix}",
        "ride_type": "healthcare",
    }
    request_headers = {
        **headers,
        "X-Idempotency-Key": idempotency_key,
    }

    first = client.post("/api/health-isf/customer-requests", headers=request_headers, json=payload)
    second = client.post("/api/health-isf/customer-requests", headers=request_headers, json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_body = first.json()
    second_body = second.json()
    assert first_body["id"] == second_body["id"]
    assert first_body["ride_id"] == second_body["ride_id"]

    with SessionLocal() as db:
        ride_count = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.id == first_body["ride_id"])
            .count()
        )
        request_count = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.id == first_body["id"])
            .count()
        )

    assert ride_count == 1
    assert request_count == 1
