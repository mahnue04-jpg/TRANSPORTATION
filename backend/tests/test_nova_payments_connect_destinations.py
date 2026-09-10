"""Nova V2 Payments Phase 4: separate Connect TEST event destinations.

Uses mocked Stripe signatures and in-process fakes only. Does not create
Stripe objects, account links, charges, payments, refunds, transfers, or payouts.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.payments.models import AmicorCustomerPayment, ensure_payments_test_schema
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingStripeEvent,
    ensure_platform_ops_schema,
)
from app.modules.platform_ops.onboarding.stripe_connect import set_stripe_connect_client_override
from tests.test_nova_payments_stripe_test_verify import FakeStripeTestReader, _check, _headers

from app.core.nova.payments.stripe_test_verify import (
    CONNECT_V2_WEBHOOK_URL,
    CONNECT_WEBHOOK_URL,
    CUSTOMER_PAYMENT_WEBHOOK_URL,
    reset_test_verification_state,
    set_test_reader_override,
)


CONNECT_V1_PATH = "/api/platform-ops/driver-onboarding/stripe/webhook"
CONNECT_V2_PATH = "/api/platform-ops/driver-onboarding/stripe/v2/webhook"
PAYMENT_PATH = "/api/payments/stripe/webhook"
VERIFY_PATH = "/api/nova/payments/readiness/verify"
V1_SECRET = "whsec_amicor_connect_v1_phase4_only"
V2_SECRET = "whsec_amicor_connect_v2_phase4_only"
PAYMENT_SECRET = "whsec_amicor_payment_phase4_only"


def _signed(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def _account_snapshot(account_id: str, *, complete: bool = True, metadata: dict | None = None) -> dict:
    status = "active" if complete else "pending"
    return {
        "id": account_id,
        "object": "account",
        "details_submitted": complete,
        "payouts_enabled": complete,
        "metadata": metadata or {},
        "configuration": {
            "recipient": {
                "capabilities": {
                    "stripe_balance": {
                        "stripe_transfers": {"status": status},
                    }
                }
            }
        },
    }


def _v1_event(*, account_id: str, event_id: str | None = None, livemode: bool | None = False, **kwargs) -> dict:
    payload = {
        "id": event_id or f"evt_{uuid4().hex}",
        "object": "event",
        "type": "account.updated",
        "data": {"object": _account_snapshot(account_id, **kwargs)},
    }
    if livemode is not None:
        payload["livemode"] = livemode
    return payload


def _v2_event(
    *,
    account_id: str,
    event_id: str | None = None,
    livemode: bool | None = False,
    snapshot: dict | None = None,
    event_type: str = "v2.core.account.updated",
) -> dict:
    payload = {
        "id": event_id or f"evt_{uuid4().hex}",
        "object": "v2.core.event",
        "type": event_type,
        "related_object": {"id": account_id, "type": "v2.core.account"},
        "data": {"object": snapshot} if snapshot is not None else {},
    }
    if livemode is not None:
        payload["livemode"] = livemode
    return payload


@pytest.fixture
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_payments_test_schema()
    return TestClient(app)


def _clear_signed_delivery_ledger() -> None:
    ensure_platform_ops_schema()
    with SessionLocal() as db:
        db.query(PlatformDriverOnboardingStripeEvent).delete()
        db.commit()


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch):
    set_stripe_connect_client_override(None)
    reset_test_verification_state()
    set_test_reader_override(None)
    _clear_signed_delivery_ledger()
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", V1_SECRET)
    monkeypatch.setenv("STRIPE_CONNECT_V2_WEBHOOK_SECRET", V2_SECRET)
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", PAYMENT_SECRET)
    yield
    set_stripe_connect_client_override(None)
    reset_test_verification_state()
    set_test_reader_override(None)
    _clear_signed_delivery_ledger()


def _org_id() -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "admin@amicor.local").first()
        assert user and user.organization_id
        return str(user.organization_id)


def _seed_application(
    *,
    organization_id: str | None = None,
    account_id: str | None = None,
    status: str = "draft",
) -> PlatformDriverOnboardingApplication:
    with SessionLocal() as db:
        row = PlatformDriverOnboardingApplication(
            organization_id=organization_id or _org_id(),
            status=status,
            legal_first_name="Casey",
            legal_last_name="Driver",
            email=f"phase4-{uuid4().hex[:8]}@example.com",
            stripe_account_id=account_id,
            stripe_onboarding_status="pending_verification" if account_id else None,
            stripe_payouts_enabled=False,
            stripe_details_submitted=False,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        db.expunge(row)
        return row


def _post(client: TestClient, path: str, payload: dict, *, secret: str, signature: str | None = None):
    body, generated = _signed(payload, secret)
    headers = {"Content-Type": "application/json"}
    if signature is not False:
        headers["Stripe-Signature"] = generated if signature is None else signature
    return client.post(path, content=body, headers=headers)


def _matched_destinations() -> tuple[list[dict], list[dict]]:
    endpoints = [
        {
            "url": CUSTOMER_PAYMENT_WEBHOOK_URL,
            "status": "enabled",
            "livemode": False,
            "enabled_events": ["payment_intent.succeeded", "payment_intent.payment_failed"],
        },
        {
            "url": CONNECT_WEBHOOK_URL,
            "status": "enabled",
            "livemode": False,
            "connect": True,
            "enabled_events": ["account.updated"],
        },
        {
            "url": "https://unrelated.example/hooks",
            "status": "enabled",
            "livemode": False,
            "enabled_events": ["*"],
            "id": "we_should_never_appear",
        },
    ]
    destinations = [
        {
            "url": CONNECT_V2_WEBHOOK_URL,
            "status": "enabled",
            "livemode": False,
            "event_payload": "thin",
            "events_from": ["@accounts"],
            "enabled_events": ["v2.core.account.updated"],
            "type": "webhook_endpoint",
            "id": "ed_should_never_appear",
        },
        {
            "url": "https://unrelated.example/v2",
            "status": "enabled",
            "livemode": False,
            "event_payload": "thin",
            "events_from": ["@self"],
            "enabled_events": ["*"],
        },
    ]
    return endpoints, destinations


def test_v2_route_fail_closed_without_secret(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STRIPE_CONNECT_V2_WEBHOOK_SECRET", raising=False)
    response = _post(client, CONNECT_V2_PATH, _v2_event(account_id="acct_unused"), secret=V2_SECRET)
    assert response.status_code == 503
    assert response.json()["detail"] == "Webhook is unavailable."


def test_v1_and_v2_missing_and_invalid_signatures(client: TestClient) -> None:
    v1_invalid = _post(client, CONNECT_V1_PATH, _v1_event(account_id="acct_unused"), secret=V1_SECRET, signature="t=1,v1=deadbeef")
    v2_invalid = _post(client, CONNECT_V2_PATH, _v2_event(account_id="acct_unused"), secret=V2_SECRET, signature="t=1,v1=deadbeef")
    v1_missing = _post(client, CONNECT_V1_PATH, _v1_event(account_id="acct_unused"), secret=V1_SECRET, signature=False)
    v2_missing = _post(client, CONNECT_V2_PATH, _v2_event(account_id="acct_unused"), secret=V2_SECRET, signature=False)
    for response in (v1_invalid, v2_invalid, v1_missing, v2_missing):
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid webhook."


def test_cross_secret_rejection(client: TestClient) -> None:
    v1_with_v2 = _post(client, CONNECT_V1_PATH, _v1_event(account_id="acct_unused"), secret=V2_SECRET)
    v2_with_v1 = _post(client, CONNECT_V2_PATH, _v2_event(account_id="acct_unused"), secret=V1_SECRET)
    v1_with_payment = _post(client, CONNECT_V1_PATH, _v1_event(account_id="acct_unused"), secret=PAYMENT_SECRET)
    v2_with_payment = _post(client, CONNECT_V2_PATH, _v2_event(account_id="acct_unused"), secret=PAYMENT_SECRET)
    for response in (v1_with_v2, v2_with_v1, v1_with_payment, v2_with_payment):
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid webhook."


def test_raw_body_signature_verification(client: TestClient) -> None:
    payload = _v2_event(account_id="acct_unused")
    body, signature = _signed(payload, V2_SECRET)
    tampered = body + b" "
    response = client.post(
        CONNECT_V2_PATH,
        content=tampered,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid webhook."


def test_live_signed_event_is_ignored(client: TestClient) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app_row = _seed_application(account_id=account_id)
    response = _post(client, CONNECT_V1_PATH, _v1_event(account_id=account_id, livemode=True), secret=V1_SECRET)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["result"] == "ignored"
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_row.id).one()
        assert row.stripe_payouts_enabled is False
        assert row.status == "draft"
        assert row.approved_at is None
        event = db.query(PlatformDriverOnboardingStripeEvent).one()
        assert event.livemode is True
        assert event.destination == "connect_v1"


def test_v2_thin_event_acknowledged_without_side_effects(client: TestClient) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app_row = _seed_application(account_id=account_id)
    payload = _v2_event(account_id=account_id, livemode=False)
    response = _post(client, CONNECT_V2_PATH, payload, secret=V2_SECRET)
    assert response.status_code == 200
    assert response.json()["received"] is True
    assert response.json()["handled"] is False
    assert response.json()["result"] == "ignored"
    assert payload["id"] not in response.text
    assert account_id not in response.text
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_row.id).one()
        assert row.status == "draft"
        assert row.approved_at is None
        assert row.activated_at is None
        assert row.submitted_at is None
        assert row.stripe_payouts_enabled is False
        event = db.query(PlatformDriverOnboardingStripeEvent).one()
        assert event.destination == "connect_v2"
        assert event.livemode is False
        assert event.event_type == "v2.core.account.updated"


def test_v2_unknown_signed_event_ignored(client: TestClient) -> None:
    payload = _v2_event(account_id="acct_unused", event_type="v2.core.account.created")
    response = _post(client, CONNECT_V2_PATH, payload, secret=V2_SECRET)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["result"] == "ignored"


def test_v1_route_fail_closes_on_thin_v2_payload(client: TestClient) -> None:
    payload = _v2_event(account_id="acct_unused")
    response = _post(client, CONNECT_V1_PATH, payload, secret=V1_SECRET)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid webhook."


def test_v2_replay_is_idempotent(client: TestClient) -> None:
    event_id = f"evt_{uuid4().hex}"
    payload = _v2_event(account_id="acct_unused", event_id=event_id)
    first = _post(client, CONNECT_V2_PATH, payload, secret=V2_SECRET)
    second = _post(client, CONNECT_V2_PATH, payload, secret=V2_SECRET)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    with SessionLocal() as db:
        assert db.query(PlatformDriverOnboardingStripeEvent).filter_by(stripe_event_id=event_id).count() == 1


def test_v2_cross_organization_denied(client: TestClient) -> None:
    org_a = _org_id()
    org_b = str(uuid4())
    account_a = f"acct_test_{uuid4().hex[:10]}"
    app_a = _seed_application(organization_id=org_a, account_id=account_a)
    app_b = _seed_application(organization_id=org_b, account_id=f"acct_test_{uuid4().hex[:10]}")
    snapshot = _account_snapshot(account_a, metadata={"organization_id": org_b, "application_id": app_b.id})
    response = _post(
        client,
        CONNECT_V2_PATH,
        _v2_event(account_id=account_a, snapshot=snapshot),
        secret=V2_SECRET,
    )
    assert response.status_code == 200
    assert response.json()["handled"] is False
    with SessionLocal() as db:
        left = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_a.id).one()
        right = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_b.id).one()
        assert left.stripe_payouts_enabled is False
        assert right.stripe_payouts_enabled is False
        assert left.status == "draft"
        assert right.status == "draft"


def test_no_financial_or_onboarding_side_effects(client: TestClient) -> None:
    before = 0
    with SessionLocal() as db:
        before = db.query(AmicorCustomerPayment).count()
    _post(client, CONNECT_V2_PATH, _v2_event(account_id=f"acct_test_{uuid4().hex[:10]}"), secret=V2_SECRET)
    payment = client.post(
        PAYMENT_PATH,
        content=_signed(
            {
                "id": f"evt_{uuid4().hex}",
                "object": "event",
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_not_from_connect", "object": "payment_intent"}},
            },
            V2_SECRET,
        )[0],
        headers={"Stripe-Signature": "t=1,v1=nope", "Content-Type": "application/json"},
    )
    assert payment.status_code == 400
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).count() == before


def test_secret_signature_and_identifier_exclusion(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app_row = _seed_application(account_id=account_id)
    payload = _v2_event(account_id=account_id)
    with caplog.at_level(logging.INFO):
        response = _post(client, CONNECT_V2_PATH, payload, secret=V2_SECRET)
    dumped = response.text + "".join(record.getMessage() for record in caplog.records)
    assert response.status_code == 200
    assert V1_SECRET not in dumped
    assert V2_SECRET not in dumped
    assert PAYMENT_SECRET not in dumped
    assert account_id not in dumped
    assert payload["id"] not in dumped
    assert app_row.id not in dumped
    assert app_row.email not in dumped
    assert "Stripe-Signature" not in dumped


def test_destination_scope_and_coverage_reporting(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints, fake.destinations = _matched_destinations()
    fake.destinations[0]["enabled_events"] = ["*"]
    fake.destinations[0]["events_from"] = ["@self"]
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "connect_v1_webhook_registration")["status"] == "Verified"
    assert _check(body, "connect_v1_webhook_scope")["status"] == "Verified"
    assert _check(body, "connect_v1_webhook_events")["status"] == "Verified"
    assert _check(body, "connect_v2_webhook_registration")["status"] == "Verified"
    assert _check(body, "connect_v2_webhook_scope")["status"] == "Missing"
    assert _check(body, "connect_v2_webhook_events")["status"] == "Not verified"
    assert "Coverage: not verified" in _check(body, "connect_v2_webhook_events")["explanation"]
    dumped = json.dumps(body)
    assert "we_should_never_appear" not in dumped
    assert "ed_should_never_appear" not in dumped
    assert "unrelated.example" not in dumped


def test_exact_v2_url_and_payload_must_match(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints, _ = _matched_destinations()
    fake.destinations = [
        {
            "url": CONNECT_V2_WEBHOOK_URL + "/extra",
            "status": "enabled",
            "livemode": False,
            "event_payload": "thin",
            "events_from": ["@accounts"],
            "enabled_events": ["v2.core.account.updated"],
            "type": "webhook_endpoint",
        },
        {
            "url": CONNECT_V2_WEBHOOK_URL,
            "status": "enabled",
            "livemode": False,
            "event_payload": "snapshot",
            "events_from": ["@accounts"],
            "enabled_events": ["v2.core.account.updated"],
            "type": "webhook_endpoint",
        },
    ]
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "connect_v2_webhook_registration")["status"] == "Missing"


def test_signed_delivery_verified_only_after_test_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints, fake.destinations = _matched_destinations()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    before = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(before, "connect_v1_signed_delivery")["status"] == "Not verified"
    assert _check(before, "connect_v2_signed_delivery")["status"] == "Not verified"
    assert _check(before, "connect_v1_webhook_secret")["status"] == "Configured"
    reset_test_verification_state()
    set_test_reader_override(fake)
    account_id = f"acct_test_{uuid4().hex[:10]}"
    _seed_application(account_id=account_id)
    _post(client, CONNECT_V1_PATH, _v1_event(account_id=account_id, livemode=False), secret=V1_SECRET)
    _post(client, CONNECT_V2_PATH, _v2_event(account_id=account_id, livemode=False), secret=V2_SECRET)
    after = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(after, "test_platform_auth")["status"] == "Verified"
    assert _check(after, "customer_webhook_registration")["status"] == "Verified"
    assert _check(after, "connect_v1_webhook_registration")["status"] == "Verified"
    assert _check(after, "connect_v2_webhook_registration")["status"] == "Verified"
    assert _check(after, "connect_v1_webhook_events")["status"] == "Verified"
    assert _check(after, "connect_v2_webhook_events")["status"] == "Verified"
    assert _check(after, "connect_v1_signed_delivery")["status"] == "Verified"
    assert _check(after, "connect_v2_signed_delivery")["status"] == "Verified"
    assert _check(after, "connect_v1_webhook_secret")["status"] == "Configured"
    assert _check(after, "connect_v2_webhook_secret")["status"] == "Configured"
    assert after["go_live_displayed"] is False
    dumped = json.dumps(after)
    assert V1_SECRET not in dumped
    assert V2_SECRET not in dumped
    assert account_id not in dumped
    assert "whsec_" not in dumped


def test_live_event_does_not_verify_signed_delivery(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints, fake.destinations = _matched_destinations()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    account_id = f"acct_test_{uuid4().hex[:10]}"
    _seed_application(account_id=account_id)
    _post(client, CONNECT_V1_PATH, _v1_event(account_id=account_id, livemode=True), secret=V1_SECRET)
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "connect_v1_signed_delivery")["status"] == "Not verified"
