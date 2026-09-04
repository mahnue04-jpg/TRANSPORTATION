"""Rider fare quote and sandbox pay-before-dispatch tests.

Uses synthetic rides only. Does not touch Driver 001 or production records.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4 as amicor_uuid4
from app.main import app
from app.modules.health_isf.models import (
    CustomerRequestStatus,
    HealthISFCustomerRideRequest,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.service import get_dispatch_queue
from app.modules.payments.models import PAYMENT_FAILED, PAYMENT_SUCCEEDED, ensure_payments_test_schema
from app.modules.payments.rider_checkout import (
    FakeStripePaymentIntentClient,
    quote_rider_fare,
    set_stripe_payment_client_override,
)


QUOTE_PATH = "/api/payments/rider/fare-quote"
CHECKOUT_PATH = "/api/payments/rider/checkout"
STATUS_PATH = "/api/payments/rider/payment-status"
WEBHOOK_PATH = "/api/payments/stripe/webhook"
WEBHOOK_SECRET = "whsec_amicor_payment_test_only"

# Minneapolis downtown -> MSP airport area
PICKUP_LAT = 44.9778
PICKUP_LNG = -93.2650
DROPOFF_LAT = 44.8848
DROPOFF_LNG = -93.2223


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_payments_test_schema()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _stripe_override():
    fake = FakeStripePaymentIntentClient()
    set_stripe_payment_client_override(fake)
    yield fake
    set_stripe_payment_client_override(None)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json().get("access_token") or response.json().get("token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None and user.organization_id
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> None:
    with SessionLocal() as db:
        existing = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .first()
        )
        if existing:
            return
        db.add(
            HealthISFProvider(
                id=amicor_uuid4(),
                organization_id=organization_id,
                name=f"Quote Provider {amicor_uuid4()[:6]}",
                address="100 Test Ave",
                phone="612-555-0100",
                service_type="clinic",
                is_active=True,
            )
        )
        db.commit()


def _signed_webhook(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    digest = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def test_fare_quote_uses_canonical_engine(client: TestClient):
    headers = _login(client)
    payload = {
        "pickup_address": "100 Nicollet Mall, Minneapolis, MN",
        "dropoff_address": "4300 Glumack Dr, St Paul, MN",
        "ride_type": "healthcare",
        "pickup_latitude": PICKUP_LAT,
        "pickup_longitude": PICKUP_LNG,
        "dropoff_latitude": DROPOFF_LAT,
        "dropoff_longitude": DROPOFF_LNG,
    }
    response = client.post(QUOTE_PATH, headers=headers, json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    with SessionLocal() as db:
        expected = quote_rider_fare(db, **payload)
    assert body["estimated_distance_miles"] == expected["estimated_distance_miles"]
    assert body["estimated_duration_minutes"] == expected["estimated_duration_minutes"]
    assert body["estimated_ride_fare_usd"] == expected["estimated_ride_fare_usd"]
    assert body["sandbox_notice"]
    assert "sandbox test" in body["sandbox_notice"].lower()
    assert body["pricing_version"] == expected["pricing_version"]


def test_checkout_holds_ride_out_of_dispatch(client: TestClient, _stripe_override):
    org_id = _org_id()
    _ensure_provider(org_id)
    headers = _login(client)
    response = client.post(
        CHECKOUT_PATH,
        headers=headers,
        json={
            "rider_name": "Quote Rider",
            "rider_phone": "6125550199",
            "pickup_address": "100 Nicollet Mall, Minneapolis, MN",
            "dropoff_address": "4300 Glumack Dr, St Paul, MN",
            "ride_type": "healthcare",
            "pickup_latitude": PICKUP_LAT,
            "pickup_longitude": PICKUP_LNG,
            "dropoff_latitude": DROPOFF_LAT,
            "dropoff_longitude": DROPOFF_LNG,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["client_secret"]
    assert body["stripe_payment_intent_id"]
    assert "sk_" not in json.dumps(body)
    assert body["dispatch_status"] == CustomerRequestStatus.AWAITING_PAYMENT.value
    assert _stripe_override.last_metadata["service_type"] == "RIDE"
    assert _stripe_override.last_metadata["ride_id"] == body["ride_id"]

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == body["ride_id"]).one()
        request_row = db.query(HealthISFCustomerRideRequest).filter(
            HealthISFCustomerRideRequest.id == body["request_id"]
        ).one()
        assert ride.lifecycle_state == RideStatus.AWAITING_PAYMENT.value
        assert request_row.dispatch_status == CustomerRequestStatus.AWAITING_PAYMENT.value
        queue = get_dispatch_queue(db, organization_id=org_id, limit=200, read_only=True)
        assert all(row.get("ride_id") != body["ride_id"] for row in queue)


def test_webhook_success_releases_ride_and_failure_keeps_hold(client: TestClient, monkeypatch):
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", WEBHOOK_SECRET)
    org_id = _org_id()
    _ensure_provider(org_id)
    headers = _login(client)
    checkout = client.post(
        CHECKOUT_PATH,
        headers=headers,
        json={
            "rider_name": "Webhook Rider",
            "rider_phone": "6125550188",
            "pickup_address": "100 Nicollet Mall, Minneapolis, MN",
            "dropoff_address": "4300 Glumack Dr, St Paul, MN",
            "ride_type": "healthcare",
            "pickup_latitude": PICKUP_LAT,
            "pickup_longitude": PICKUP_LNG,
            "dropoff_latitude": DROPOFF_LAT,
            "dropoff_longitude": DROPOFF_LNG,
        },
    )
    assert checkout.status_code == 200, checkout.text
    checkout_body = checkout.json()
    intent_id = checkout_body["stripe_payment_intent_id"]
    ride_id = checkout_body["ride_id"]
    request_id = checkout_body["request_id"]

    failed_event = {
        "id": f"evt_{uuid4().hex}",
        "object": "event",
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": intent_id,
                "object": "payment_intent",
                "amount": checkout_body["amount_minor"],
                "amount_received": 0,
                "currency": "usd",
                "metadata": {
                    "service_type": "RIDE",
                    "ride_id": ride_id,
                    "internal_service_id": ride_id,
                },
                "last_payment_error": {"message": "Your card was declined."},
            }
        },
    }
    body, signature = _signed_webhook(failed_event)
    failed = client.post(WEBHOOK_PATH, content=body, headers={"Stripe-Signature": signature})
    assert failed.status_code == 200, failed.text
    status_failed = client.get(f"{STATUS_PATH}/{request_id}", headers=headers)
    assert status_failed.status_code == 200
    assert status_failed.json()["payment_status"] == PAYMENT_FAILED
    assert status_failed.json()["held_for_payment"] is True

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).one()
        assert ride.lifecycle_state == RideStatus.AWAITING_PAYMENT.value

    success_event = {
        "id": f"evt_{uuid4().hex}",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": intent_id,
                "object": "payment_intent",
                "amount": checkout_body["amount_minor"],
                "amount_received": checkout_body["amount_minor"],
                "currency": "usd",
                "metadata": {
                    "service_type": "RIDE",
                    "ride_id": ride_id,
                    "internal_service_id": ride_id,
                },
            }
        },
    }
    body, signature = _signed_webhook(success_event)
    succeeded = client.post(WEBHOOK_PATH, content=body, headers={"Stripe-Signature": signature})
    assert succeeded.status_code == 200, succeeded.text
    status_paid = client.get(f"{STATUS_PATH}/{request_id}", headers=headers)
    assert status_paid.status_code == 200
    assert status_paid.json()["payment_status"] == PAYMENT_SUCCEEDED
    assert status_paid.json()["held_for_payment"] is False

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).one()
        request_row = db.query(HealthISFCustomerRideRequest).filter(
            HealthISFCustomerRideRequest.id == request_id
        ).one()
        assert ride.lifecycle_state != RideStatus.AWAITING_PAYMENT.value
        assert request_row.dispatch_status != CustomerRequestStatus.AWAITING_PAYMENT.value


def test_live_stripe_key_is_rejected():
    from app.modules.payments.rider_checkout import is_live_stripe_key, sanitize_checkout_error

    assert is_live_stripe_key("sk_live_example") is True
    assert is_live_stripe_key("rk_live_example") is True
    assert is_live_stripe_key("sk_test_example") is False
    redacted = sanitize_checkout_error("boom sk_test_51SECRET pi_abc_secret_xyz")
    assert "sk_test_51SECRET" not in redacted
    assert "pi_abc_secret_xyz" not in redacted
    assert "[REDACTED]" in redacted


def test_checkout_unexpected_error_returns_503_without_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    def _boom(**_kwargs):
        raise RuntimeError("stripe failed sk_test_51SECRET pi_1_secret_abc")

    monkeypatch.setattr("app.modules.payments.routes.create_rider_checkout", _boom)
    headers = _login(client)
    response = client.post(
        CHECKOUT_PATH,
        headers=headers,
        json={
            "rider_name": "Quote Rider",
            "rider_phone": "6125550199",
            "pickup_address": "100 Nicollet Mall, Minneapolis, MN",
            "dropoff_address": "4300 Glumack Dr, St Paul, MN",
            "ride_type": "healthcare",
            "pickup_latitude": PICKUP_LAT,
            "pickup_longitude": PICKUP_LNG,
            "dropoff_latitude": DROPOFF_LAT,
            "dropoff_longitude": DROPOFF_LNG,
        },
    )
    assert response.status_code == 503, response.text
    assert "sk_test" not in response.text
    assert "pi_1_secret" not in response.text
    assert response.json()["detail"] == "Rider checkout is temporarily unavailable."


def test_fare_quote_accepts_minneapolis_street_addresses(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    from app.modules.health_isf.driver_mobile_routing import normalize_address_key

    coords = {
        normalize_address_key("2823 Aldrich Ave N, Minneapolis, MN 55411"): {
            "latitude": 45.0088009,
            "longitude": -93.2893813,
            "provider": "nominatim",
        },
        normalize_address_key("2400 E 28th St, Minneapolis, MN"): {
            "latitude": 44.9519645,
            "longitude": -93.2601688,
            "provider": "nominatim",
        },
    }

    def _fake_geocode(_db, address: str):
        return coords.get(normalize_address_key(address))

    monkeypatch.setattr("app.modules.health_isf.driver_mobile_routing.geocode_address", _fake_geocode)
    headers = _login(client)
    response = client.post(
        QUOTE_PATH,
        headers=headers,
        json={
            "pickup_address": "2823 Aldrich Ave N, Minneapolis, MN 55411",
            "dropoff_address": "2400 E 28th St, Minneapolis, MN",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pickup_latitude"] == 45.0088009
    assert body["dropoff_latitude"] == 44.9519645
    assert body["estimated_distance_miles"] > 0
    assert body["estimated_duration_minutes"] >= 2
    assert body["estimated_ride_fare_usd"] >= 18.0
