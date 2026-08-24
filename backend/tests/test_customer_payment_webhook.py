"""Focused tests for the Amicor Ride + Deliver customer-payment webhook.

Uses Stripe signature fixtures only. Does not call Stripe or banking APIs.
Does not touch Connect onboarding or live payouts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.session import SessionLocal
from app.main import app
from app.modules.payments.models import (
    PAYMENT_FAILED,
    PAYMENT_SUCCEEDED,
    PAYOUT_NOT_STARTED,
    AmicorCustomerPayment,
    AmicorCustomerPaymentEvent,
    ensure_payments_schema,
)
from app.modules.payments.stripe_payments import parse_payment_intent_metadata


PAYMENT_WEBHOOK_PATH = "/api/payments/stripe/webhook"
CONNECT_WEBHOOK_PATH = "/api/platform-ops/driver-onboarding/stripe/webhook"
PAYMENT_WEBHOOK_SECRET = "whsec_amicor_payment_test_only"
CONNECT_WEBHOOK_SECRET = "whsec_amicor_connect_test_only"


def _signed_webhook(payload: dict, secret: str = PAYMENT_WEBHOOK_SECRET) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def _payment_intent_event(
    *,
    event_type: str,
    event_id: str | None = None,
    payment_intent_id: str | None = None,
    metadata: dict | None = None,
    amount: int = 2550,
    currency: str = "usd",
    last_payment_error: dict | None = None,
) -> dict:
    return {
        "id": event_id or f"evt_{uuid4().hex}",
        "object": "event",
        "type": event_type,
        "data": {
            "object": {
                "id": payment_intent_id or f"pi_{uuid4().hex[:24]}",
                "object": "payment_intent",
                "amount": amount,
                "amount_received": amount if event_type == "payment_intent.succeeded" else 0,
                "currency": currency,
                "metadata": metadata or {},
                "last_payment_error": last_payment_error,
                "charges": {"data": [{"payment_method_details": {"card": {"last4": "4242"}}}]},
            }
        },
    }


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_payments_schema()
    return TestClient(app)


@pytest.fixture
def payment_secret(monkeypatch):
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", PAYMENT_WEBHOOK_SECRET)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", CONNECT_WEBHOOK_SECRET)


def _post_payment(client: TestClient, payload: dict, *, signature: str | None = None, secret: str = PAYMENT_WEBHOOK_SECRET):
    body, generated = _signed_webhook(payload, secret=secret)
    headers = {"Content-Type": "application/json"}
    if signature is not False:
        headers["Stripe-Signature"] = generated if signature is None else signature
    return client.post(PAYMENT_WEBHOOK_PATH, content=body, headers=headers)


def test_stripe_ids_with_long_digit_runs_are_not_redacted(client: TestClient, payment_secret) -> None:
    event_id = "evt_17fb4f578295449092203ba685469c63"
    pi_id = "pi_c2533684535543228a2707c8"
    ride_id = "ride-2533684535543"
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        event_id=event_id,
        payment_intent_id=pi_id,
        metadata={"service_type": "RIDE", "ride_id": ride_id},
    )
    response = _post_payment(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_id"] == event_id
    assert body["payment_intent_id"] == pi_id
    assert "[redacted]" not in body["event_id"]
    assert "[redacted]" not in body["payment_intent_id"]


def test_parse_ride_and_delivery_metadata():
    ride = parse_payment_intent_metadata(
        {
            "service_type": "ride",
            "ride_id": "ride-abc",
            "customer_id": "cust-1",
            "driver_id": "drv-1",
            "pricing_version": "v1",
        }
    )
    assert ride.service_type == "RIDE"
    assert ride.service_type_valid is True
    assert ride.internal_service_id == "ride-abc"
    assert ride.ride_id == "ride-abc"
    assert ride.delivery_id is None

    delivery = parse_payment_intent_metadata(
        {
            "service_type": "DELIVERY",
            "internal_service_id": "del-xyz",
            "customer_id": "cust-2",
        }
    )
    assert delivery.service_type == "DELIVERY"
    assert delivery.internal_service_id == "del-xyz"
    assert delivery.delivery_id == "del-xyz"


def test_payment_intent_succeeded_ride(client: TestClient, payment_secret) -> None:
    ride_id = f"ride-{uuid4().hex[:12]}"
    pi_id = f"pi_{uuid4().hex[:24]}"
    event_id = f"evt_{uuid4().hex}"
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        event_id=event_id,
        payment_intent_id=pi_id,
        metadata={
            "service_type": "RIDE",
            "ride_id": ride_id,
            "customer_id": "cust-ride",
            "driver_id": "drv-ride",
            "pricing_version": "sandbox-v0",
        },
        amount=2550,
    )
    response = _post_payment(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["received"] is True
    assert body["handled"] is True
    assert body["duplicate"] is False
    assert body["result"] == "paid"
    assert body["event_id"] == event_id
    assert body["payment_intent_id"] == pi_id
    assert body["service_type"] == "RIDE"
    assert body["internal_service_id"] == ride_id
    assert body["amount"] == 25.50
    assert body["currency"] == "usd"
    assert body["payment_status"] == PAYMENT_SUCCEEDED
    assert body["payout_status"] == PAYOUT_NOT_STARTED

    with SessionLocal() as db:
        payment = db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi_id).one()
        events = db.query(AmicorCustomerPaymentEvent).filter_by(stripe_event_id=event_id).all()
        assert len(events) == 1
        assert payment.service_type == "RIDE"
        assert payment.internal_service_id == ride_id
        assert payment.ride_id == ride_id
        assert payment.delivery_id is None
        assert payment.customer_id == "cust-ride"
        assert payment.driver_id == "drv-ride"
        assert payment.pricing_version == "sandbox-v0"
        assert payment.payment_status == PAYMENT_SUCCEEDED
        assert payment.payout_status == PAYOUT_NOT_STARTED
        assert payment.paid_at is not None
        assert payment.driver_earning_usd is None
        assert payment.amicor_share_usd is None
        assert payment.gross_customer_charge_usd == 25.50


def test_duplicate_event_is_idempotent(client: TestClient, payment_secret) -> None:
    ride_id = f"ride-{uuid4().hex[:12]}"
    pi_id = f"pi_{uuid4().hex[:24]}"
    event_id = f"evt_dup_{uuid4().hex}"
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        event_id=event_id,
        payment_intent_id=pi_id,
        metadata={"service_type": "RIDE", "internal_service_id": ride_id},
    )
    first = _post_payment(client, payload)
    second = _post_payment(client, payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    assert second.json()["result"] == "paid"
    assert second.json()["payment_id"] == first.json()["payment_id"]

    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi_id).count() == 1
        assert db.query(AmicorCustomerPaymentEvent).filter_by(stripe_event_id=event_id).count() == 1


def test_payment_intent_failed_does_not_mark_paid(client: TestClient, payment_secret) -> None:
    ride_id = f"ride-{uuid4().hex[:12]}"
    pi_id = f"pi_{uuid4().hex[:24]}"
    payload = _payment_intent_event(
        event_type="payment_intent.payment_failed",
        payment_intent_id=pi_id,
        metadata={"service_type": "RIDE", "ride_id": ride_id},
        last_payment_error={"code": "card_declined", "message": "Your card was declined."},
    )
    response = _post_payment(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["handled"] is True
    assert body["result"] == "payment_failed"
    assert body["payment_status"] == PAYMENT_FAILED
    assert body["payout_status"] == PAYOUT_NOT_STARTED

    with SessionLocal() as db:
        payment = db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi_id).one()
        assert payment.payment_status == PAYMENT_FAILED
        assert payment.paid_at is None
        assert payment.payout_status == PAYOUT_NOT_STARTED
        assert payment.failure_code == "card_declined"
        assert payment.failure_message is not None
        assert "declined" in payment.failure_message.lower()
        assert "4242" not in (payment.failure_message or "")


def test_invalid_stripe_signature_rejected(client: TestClient, payment_secret) -> None:
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        metadata={"service_type": "RIDE", "ride_id": "ride-x"},
    )
    response = _post_payment(client, payload, signature="t=1,v1=deadbeef")
    assert response.status_code == 400
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPaymentEvent).filter_by(stripe_event_id=payload["id"]).count() == 0


def test_unknown_service_type_acknowledged(client: TestClient, payment_secret) -> None:
    pi_id = f"pi_{uuid4().hex[:24]}"
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        payment_intent_id=pi_id,
        metadata={"service_type": "BOAT", "internal_service_id": "boat-1"},
    )
    response = _post_payment(client, payload)
    assert response.status_code == 200
    body = response.json()
    assert body["received"] is True
    assert body["handled"] is False
    assert body["result"] == "unknown_service_type"
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi_id).count() == 0
        event = db.query(AmicorCustomerPaymentEvent).filter_by(stripe_event_id=payload["id"]).one()
        assert event.processing_result == "unknown_service_type"


def test_missing_internal_service_id_acknowledged(client: TestClient, payment_secret) -> None:
    pi_id = f"pi_{uuid4().hex[:24]}"
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        payment_intent_id=pi_id,
        metadata={"service_type": "RIDE"},
    )
    response = _post_payment(client, payload)
    assert response.status_code == 200
    body = response.json()
    assert body["handled"] is False
    assert body["result"] == "missing_internal_service_id"
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi_id).count() == 0


def test_delivery_metadata_succeeded(client: TestClient, payment_secret) -> None:
    delivery_id = f"del-{uuid4().hex[:12]}"
    pi_id = f"pi_{uuid4().hex[:24]}"
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        payment_intent_id=pi_id,
        metadata={
            "service_type": "DELIVERY",
            "delivery_id": delivery_id,
            "customer_id": "cust-del",
            "pricing_version": "deliver-sandbox-v0",
        },
        amount=1999,
    )
    response = _post_payment(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["result"] == "paid"
    assert body["service_type"] == "DELIVERY"
    assert body["internal_service_id"] == delivery_id
    assert body["amount"] == 19.99
    assert body["payout_status"] == PAYOUT_NOT_STARTED

    with SessionLocal() as db:
        payment = db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=pi_id).one()
        assert payment.service_type == "DELIVERY"
        assert payment.delivery_id == delivery_id
        assert payment.ride_id is None
        assert payment.payment_status == PAYMENT_SUCCEEDED
        assert payment.payout_status == PAYOUT_NOT_STARTED


def test_unrelated_event_acknowledged_safely(client: TestClient, payment_secret) -> None:
    payload = {
        "id": f"evt_unrelated_{uuid4().hex}",
        "object": "event",
        "type": "charge.succeeded",
        "data": {"object": {"id": "ch_test", "metadata": {"service_type": "RIDE", "ride_id": "ride-1"}}},
    }
    response = _post_payment(client, payload)
    assert response.status_code == 200
    body = response.json()
    assert body["received"] is True
    assert body["handled"] is False
    assert body["result"] == "unrelated"
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).count() >= 0
        event = db.query(AmicorCustomerPaymentEvent).filter_by(stripe_event_id=payload["id"]).one()
        assert event.processing_result == "unrelated"
        assert db.query(AmicorCustomerPayment).filter_by(last_stripe_event_id=payload["id"]).count() == 0


def test_connect_webhook_still_ignores_payment_intent(client: TestClient, payment_secret) -> None:
    connect_registered = any(getattr(route, "path", None) == CONNECT_WEBHOOK_PATH for route in app.routes)
    if not connect_registered:
        pytest.skip("Connect webhook is not part of this payment-scoped candidate")
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        metadata={"service_type": "RIDE", "ride_id": f"ride-{uuid4().hex[:8]}"},
    )
    body, signature = _signed_webhook(payload, secret=CONNECT_WEBHOOK_SECRET)
    response = client.post(
        CONNECT_WEBHOOK_PATH,
        content=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json().get("handled") is False
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=payload["data"]["object"]["id"]).count() == 0


def test_missing_payment_webhook_secret_returns_503(client: TestClient, monkeypatch) -> None:
    monkeypatch.delenv("STRIPE_PAYMENT_WEBHOOK_SECRET", raising=False)
    payload = _payment_intent_event(
        event_type="payment_intent.succeeded",
        metadata={"service_type": "RIDE", "ride_id": "ride-x"},
    )
    response = _post_payment(client, payload)
    assert response.status_code == 503
