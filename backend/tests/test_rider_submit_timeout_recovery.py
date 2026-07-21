"""Rider submit timeout/recovery contract: idempotency, lookup, and duplicate protection."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi.testclient import TestClient
import pytest

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFCustomerRideRequest, HealthISFRide, HealthISFProvider
from app.modules.health_isf.realtime_service import IdempotencyService


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
            name=f"Rider Timeout Provider {uuid4()[:6]}",
            address="500 Recovery Avenue",
            phone="212-555-0700",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _numeric_phone_suffix(seed: str | None = None) -> str:
    raw = seed or uuid4()
    digits = "".join(ch for ch in raw if ch.isdigit())
    return digits.ljust(4, "0")[:4]


def _build_payload(suffix: str | None = None) -> dict:
    token = suffix or uuid4()[:8]
    phone_suffix = _numeric_phone_suffix(token)
    return {
        "rider_name": f"Timeout Rider {phone_suffix}",
        "rider_phone": f"+1 646-555-{phone_suffix}",
        "pickup_address": f"100 Recovery Pickup {phone_suffix}, New York, NY",
        "dropoff_address": f"200 Recovery Dropoff {phone_suffix}, New York, NY",
        "ride_type": "healthcare",
        "recurring": False,
    }


def test_rider_submit_success_normal_response(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_org_id_for("rider@amicor.local"))
    suffix = uuid4()[:8]
    idempotency_key = f"rider-timeout-success-{suffix}"

    response = client.post(
        "/api/health-isf/customer-requests",
        headers={**headers, "X-Idempotency-Key": idempotency_key},
        json=_build_payload(suffix),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body.get("id")
    assert body.get("ride_id")
    assert body.get("dispatch_status")


def test_rider_submit_duplicate_idempotency_creates_one_ride(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_org_id_for("rider@amicor.local"))
    suffix = uuid4()[:8]
    idempotency_key = f"rider-timeout-dup-{suffix}"
    request_headers = {**headers, "X-Idempotency-Key": idempotency_key}
    payload = _build_payload(suffix)

    first = client.post("/api/health-isf/customer-requests", headers=request_headers, json=payload)
    second = client.post("/api/health-isf/customer-requests", headers=request_headers, json=payload)

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    first_body = first.json()
    second_body = second.json()
    assert first_body["id"] == second_body["id"]
    assert first_body["ride_id"] == second_body["ride_id"]

    with SessionLocal() as db:
        ride_count = db.query(HealthISFRide).filter(HealthISFRide.id == first_body["ride_id"]).count()
        request_count = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.id == first_body["id"])
            .count()
        )
    assert ride_count == 1
    assert request_count == 1


def test_rider_submit_concurrent_duplicate_tap_one_ride(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_org_id_for("rider@amicor.local"))
    suffix = uuid4()[:8]
    idempotency_key = f"rider-timeout-concurrent-{suffix}"
    request_headers = {**headers, "X-Idempotency-Key": idempotency_key}
    payload = _build_payload(suffix)

    def submit_once() -> tuple[int, dict]:
        response = client.post(
            "/api/health-isf/customer-requests",
            headers=request_headers,
            json=payload,
        )
        body = response.json() if response.content else {}
        return response.status_code, body

    statuses: list[int] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit_once) for _ in range(2)]
        for future in as_completed(futures):
            status, _body = future.result()
            statuses.append(status)

    assert all(status in {201, 409, 500} for status in statuses), statuses

    lookup = client.get(
        f"/api/health-isf/customer-requests/idempotency/{idempotency_key}",
        headers=headers,
    )
    assert lookup.status_code == 200, lookup.text
    recovered = lookup.json()

    retry = client.post(
        "/api/health-isf/customer-requests",
        headers=request_headers,
        json=payload,
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == recovered["id"]
    assert retry.json()["ride_id"] == recovered["ride_id"]

    with SessionLocal() as db:
        ride_count = db.query(HealthISFRide).filter(HealthISFRide.id == recovered["ride_id"]).count()
        request_count = (
            db.query(HealthISFCustomerRideRequest)
            .filter(HealthISFCustomerRideRequest.id == recovered["id"])
            .count()
        )
    assert ride_count == 1
    assert request_count == 1


def test_rider_submit_idempotency_recovery_while_processing(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    suffix = uuid4()[:8]
    idempotency_key = f"rider-timeout-processing-{suffix}"
    lookup_url = f"/api/health-isf/customer-requests/idempotency/{idempotency_key}"

    with SessionLocal() as db:
        reserved = IdempotencyService.reserve_key(
            db,
            idempotency_key=idempotency_key,
            scope="customer_ride_request",
        )
        assert reserved is True

    processing = client.get(lookup_url, headers=headers)
    assert processing.status_code == 202, processing.text

    create_resp = client.post(
        "/api/health-isf/customer-requests",
        headers={**headers, "X-Idempotency-Key": idempotency_key},
        json=_build_payload(suffix),
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()

    recovered = client.get(lookup_url, headers=headers)
    assert recovered.status_code == 200, recovered.text
    recovered_body = recovered.json()
    assert recovered_body["id"] == created["id"]
    assert recovered_body["ride_id"] == created["ride_id"]


def test_rider_submit_timeout_recovery_lookup_after_create(client: TestClient) -> None:
    auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_org_id_for("rider@amicor.local"))
    suffix = uuid4()[:8]
    idempotency_key = f"rider-timeout-recover-{suffix}"
    payload = _build_payload(suffix)
    payload["client_request_key"] = idempotency_key

    create_resp = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json=payload,
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()

    lookup = client.get(
        f"/api/health-isf/customer-requests/idempotency/{idempotency_key}",
        headers=headers,
    )
    assert lookup.status_code == 200, lookup.text
    recovered = lookup.json()
    assert recovered["id"] == created["id"]
    assert recovered["ride_id"] == created["ride_id"]


def test_rider_submit_slow_create_still_idempotent(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulates server work exceeding legacy 15s client timeout; recovery uses idempotency key."""
    from app.modules.health_isf import routes as health_routes

    auth = _login(client, "rider@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _ensure_provider(_org_id_for("rider@amicor.local"))
    suffix = uuid4()[:8]
    idempotency_key = f"rider-timeout-slow-{suffix}"
    request_headers = {**headers, "X-Idempotency-Key": idempotency_key}
    payload = _build_payload(suffix)

    original_create = health_routes.service.create_customer_ride_request

    def slow_create(*args, **kwargs):
        time.sleep(0.25)
        return original_create(*args, **kwargs)

    monkeypatch.setattr(health_routes.service, "create_customer_ride_request", slow_create)

    started = time.perf_counter()
    response = client.post(
        "/api/health-isf/customer-requests",
        headers=request_headers,
        json=payload,
    )
    elapsed = time.perf_counter() - started
    assert response.status_code == 201, response.text
    assert elapsed >= 0.2
    body = response.json()

    recovery = client.get(
        f"/api/health-isf/customer-requests/idempotency/{idempotency_key}",
        headers=headers,
    )
    assert recovery.status_code == 200, recovery.text
    recovered = recovery.json()
    assert recovered["id"] == body["id"]

    retry = client.post(
        "/api/health-isf/customer-requests",
        headers=request_headers,
        json=payload,
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == body["id"]
