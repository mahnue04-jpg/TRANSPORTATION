"""Nova V2 Payments Phase 2: Connect return/refresh lock and webhook security.

Uses mocked Stripe signatures and in-process fakes only. Does not create
Stripe objects, account links, charges, payments, or payouts.
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
from app.modules.platform_ops.onboarding.connect_redirects import (
    APPROVED_PRODUCTION_ORIGIN,
    ConnectRedirectError,
    build_connect_redirect_urls,
    validate_connect_redirect_url,
)
from app.modules.platform_ops.onboarding.stripe_connect import (
    FakeStripeConnectClient,
    set_stripe_connect_client_override,
)


CONNECT_WEBHOOK_PATH = "/api/platform-ops/driver-onboarding/stripe/webhook"
PAYMENT_WEBHOOK_PATH = "/api/payments/stripe/webhook"
CONNECT_SECRET = "whsec_amicor_connect_phase2_only"
PAYMENT_SECRET = "whsec_amicor_payment_phase2_only"
APPROVED_RETURN = f"{APPROVED_PRODUCTION_ORIGIN}/platform-ops/driver-apply?work_setup=stripe_return"
APPROVED_REFRESH = f"{APPROVED_PRODUCTION_ORIGIN}/platform-ops/driver-apply?work_setup=stripe_refresh"


def _signed(payload: dict, secret: str) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.{body.decode('utf-8')}".encode("utf-8"), hashlib.sha256).hexdigest()
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


def _account_updated_event(
    *,
    account_id: str,
    event_id: str | None = None,
    complete: bool = True,
    metadata: dict | None = None,
) -> dict:
    return {
        "id": event_id or f"evt_{uuid4().hex}",
        "object": "event",
        "type": "account.updated",
        "data": {"object": _account_snapshot(account_id, complete=complete, metadata=metadata)},
    }


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_platform_ops_schema()
    ensure_payments_test_schema()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_stripe(monkeypatch: pytest.MonkeyPatch):
    set_stripe_connect_client_override(None)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", CONNECT_SECRET)
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", PAYMENT_SECRET)
    yield
    set_stripe_connect_client_override(None)


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
            email=f"phase2-{uuid4().hex[:8]}@example.com",
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


def _post_connect(client: TestClient, payload: dict, *, secret: str = CONNECT_SECRET, signature: str | None = None):
    body, generated = _signed(payload, secret)
    headers = {"Content-Type": "application/json"}
    if signature is not False:
        headers["Stripe-Signature"] = generated if signature is None else signature
    return client.post(CONNECT_WEBHOOK_PATH, content=body, headers=headers)


def test_approved_production_https_origin_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    return_url, refresh_url = build_connect_redirect_urls()
    assert return_url == APPROVED_RETURN
    assert refresh_url == APPROVED_REFRESH
    validate_connect_redirect_url(return_url, production=True)
    validate_connect_redirect_url(refresh_url, production=True)


@pytest.mark.parametrize(
    "url",
    [
        "http://amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://evil.amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://amicor-health-isf-py.onrender.com.evil.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://prefix-amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://amicor-health-isf-py.onrender.com.example/platform-ops/driver-apply?work_setup=stripe_return",
        "https://amicor-health-isf-py.onrender.com:8443/platform-ops/driver-apply?work_setup=stripe_return",
        "//amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://user@amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://user:pass@amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return&redirect=https://evil.example",
        "https://amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return%26redirect%3Dhttps%3A%2F%2Fevil.example",
        "https://amicor-health-isf-py.onrender.com%2Eevil.com/platform-ops/driver-apply?work_setup=stripe_return",
        "https://amicor-health-isf-py.onrender.com/platform-ops/driver-apply?work_setup=stripe_return&token=abc",
        "http://127.0.0.1/platform-ops/driver-apply?work_setup=stripe_return",
        "http://localhost/platform-ops/driver-apply?work_setup=stripe_return",
    ],
)
def test_production_redirect_attacks_rejected(url: str) -> None:
    with pytest.raises(ConnectRedirectError):
        validate_connect_redirect_url(url, production=True)


def test_localhost_accepted_only_in_test_or_development(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "test")
    return_url, refresh_url = build_connect_redirect_urls()
    assert return_url.startswith("http://127.0.0.1/")
    assert refresh_url.startswith("http://127.0.0.1/")
    validate_connect_redirect_url(return_url, production=False)
    with pytest.raises(ConnectRedirectError):
        validate_connect_redirect_url(return_url, production=True)


def test_production_cannot_fall_back_to_localhost(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    return_url, refresh_url = build_connect_redirect_urls()
    assert "127.0.0.1" not in return_url
    assert "localhost" not in return_url
    assert "127.0.0.1" not in refresh_url
    assert return_url.startswith("https://amicor-health-isf-py.onrender.com/")


def test_applicant_token_absent_from_generated_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    return_url, refresh_url = build_connect_redirect_urls()
    assert "token=" not in return_url
    assert "token=" not in refresh_url
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "test")
    return_url, refresh_url = build_connect_redirect_urls()
    assert "token=" not in return_url
    assert "token=" not in refresh_url


def test_host_header_poisoning_ignored(client: TestClient) -> None:
    created = client.post(
        "/api/platform-ops/driver-onboarding/applications",
        json={"organization_id": _org_id(), "legal_first_name": "Casey", "legal_last_name": "Driver"},
    )
    assert created.status_code == 200, created.text
    app_id = created.json()["application"]["id"]
    token = created.json()["applicant_access_token"]
    fake = FakeStripeConnectClient()
    set_stripe_connect_client_override(fake)
    start = client.post(
        f"/api/platform-ops/driver-onboarding/applications/{app_id}/work-setup/payout/start",
        headers={
            "X-Applicant-Token": token,
            "Host": "evil-lookalike.example",
            "X-Forwarded-Host": "evil-lookalike.example",
        },
        json={
            "return_url": "https://evil-lookalike.example/steal?token=abc",
            "refresh_url": "http://127.0.0.1/platform-ops/driver-apply?work_setup=stripe_refresh",
        },
    )
    assert start.status_code == 200, start.text
    assert fake.last_return_url == "http://127.0.0.1/platform-ops/driver-apply?work_setup=stripe_return"
    assert fake.last_refresh_url == "http://127.0.0.1/platform-ops/driver-apply?work_setup=stripe_refresh"
    assert "evil" not in (fake.last_return_url or "")
    assert "token=" not in (fake.last_return_url or "")


def test_no_live_stripe_account_link_in_url_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.platform_ops.onboarding.stripe_connect import LiveStripeConnectClient

    def boom(*_args, **_kwargs):
        raise AssertionError("Live account-link creation is not allowed in Phase 2 tests.")

    monkeypatch.setattr(LiveStripeConnectClient, "create_account_onboarding_link", boom)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    build_connect_redirect_urls()


def test_valid_mocked_signature_accepted(client: TestClient) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app = _seed_application(account_id=account_id)
    payload = _account_updated_event(account_id=account_id)
    response = _post_connect(client, payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["received"] is True
    assert body["handled"] is True
    assert body["result"] == "applied"
    assert "evt_" not in response.text
    assert account_id not in response.text
    assert app.id not in response.text
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app.id).one()
        assert row.stripe_onboarding_status == "complete"
        assert row.stripe_payouts_enabled is True
        assert row.stripe_details_submitted is True
        assert row.status == "draft"
        assert row.approved_at is None
        assert row.activated_at is None


def test_invalid_and_missing_signatures_rejected(client: TestClient) -> None:
    payload = _account_updated_event(account_id="acct_unused")
    invalid = _post_connect(client, payload, signature="t=1,v1=deadbeef")
    assert invalid.status_code == 400
    assert invalid.json()["detail"] == "Invalid webhook."
    missing = _post_connect(client, payload, signature=False)
    assert missing.status_code == 400
    assert missing.json()["detail"] == "Invalid webhook."


def test_missing_connect_secret_is_unavailable(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    payload = _account_updated_event(account_id="acct_unused")
    with caplog.at_level(logging.INFO):
        response = _post_connect(client, payload)
    assert response.status_code == 503
    assert response.json()["detail"] == "Webhook is unavailable."
    dumped = response.text + "".join(record.getMessage() for record in caplog.records)
    assert CONNECT_SECRET not in dumped
    assert PAYMENT_SECRET not in dumped


def test_customer_payment_secret_cannot_validate_connect(client: TestClient) -> None:
    payload = _account_updated_event(account_id="acct_unused")
    response = _post_connect(client, payload, secret=PAYMENT_SECRET)
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid webhook."


def test_unknown_signed_event_acknowledged_and_ignored(client: TestClient) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app = _seed_application(account_id=account_id)
    payload = {
        "id": f"evt_{uuid4().hex}",
        "object": "event",
        "type": "charge.succeeded",
        "data": {"object": {"id": "ch_test", "object": "charge"}},
    }
    response = _post_connect(client, payload)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["result"] == "ignored"
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app.id).one()
        assert row.stripe_onboarding_status == "pending_verification"
        assert row.stripe_payouts_enabled is False


def test_malformed_event_handled_safely(client: TestClient) -> None:
    payload = {"id": f"evt_{uuid4().hex}", "object": "event", "type": "account.updated", "data": {"object": "not-an-object"}}
    response = _post_connect(client, payload)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["result"] in {"ignored", "unrelated"}


def test_exact_stored_account_matching(client: TestClient) -> None:
    stored = f"acct_test_{uuid4().hex[:10]}"
    other = f"acct_test_{uuid4().hex[:10]}"
    app = _seed_application(account_id=stored)
    _seed_application(account_id=other)
    response = _post_connect(client, _account_updated_event(account_id=stored))
    assert response.status_code == 200
    assert response.json()["handled"] is True
    with SessionLocal() as db:
        matched = db.query(PlatformDriverOnboardingApplication).filter_by(id=app.id).one()
        outsider = db.query(PlatformDriverOnboardingApplication).filter_by(stripe_account_id=other).one()
        assert matched.stripe_payouts_enabled is True
        assert outsider.stripe_payouts_enabled is False


def test_metadata_only_matching_refused(client: TestClient) -> None:
    app = _seed_application(account_id=f"acct_test_{uuid4().hex[:10]}")
    payload = {
        "id": f"evt_{uuid4().hex}",
        "object": "event",
        "type": "account.updated",
        "data": {
            "object": {
                "object": "account",
                "metadata": {
                    "application_id": app.id,
                    "organization_id": app.organization_id,
                    "email": app.email,
                },
                "details_submitted": True,
                "payouts_enabled": True,
            }
        },
    }
    response = _post_connect(client, payload)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app.id).one()
        assert row.stripe_payouts_enabled is False
        assert row.status == "draft"


def test_cross_organization_update_refused(client: TestClient) -> None:
    org_a = _org_id()
    org_b = str(uuid4())
    account_a = f"acct_test_{uuid4().hex[:10]}"
    app_a = _seed_application(organization_id=org_a, account_id=account_a)
    app_b = _seed_application(organization_id=org_b, account_id=f"acct_test_{uuid4().hex[:10]}")
    payload = _account_updated_event(
        account_id=account_a,
        metadata={"organization_id": org_b, "application_id": app_b.id},
    )
    response = _post_connect(client, payload)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    with SessionLocal() as db:
        left = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_a.id).one()
        right = db.query(PlatformDriverOnboardingApplication).filter_by(id=app_b.id).one()
        assert left.stripe_payouts_enabled is False
        assert right.stripe_payouts_enabled is False
        assert left.status == "draft"
        assert right.status == "draft"


def test_duplicate_event_is_idempotent(client: TestClient) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app = _seed_application(account_id=account_id)
    event_id = f"evt_{uuid4().hex}"
    payload = _account_updated_event(account_id=account_id, event_id=event_id)
    first = _post_connect(client, payload)
    second = _post_connect(client, payload)
    assert first.status_code == 200
    assert first.json()["handled"] is True
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["handled"] is False
    with SessionLocal() as db:
        assert db.query(PlatformDriverOnboardingStripeEvent).filter_by(stripe_event_id=event_id).count() == 1
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app.id).one()
        assert row.stripe_payouts_enabled is True
        assert row.status == "draft"


def test_event_cannot_approve_or_activate_and_updates_only_readiness_fields(client: TestClient) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app = _seed_application(account_id=account_id)
    response = _post_connect(client, _account_updated_event(account_id=account_id))
    assert response.status_code == 200
    with SessionLocal() as db:
        row = db.query(PlatformDriverOnboardingApplication).filter_by(id=app.id).one()
        assert row.status == "draft"
        assert row.approved_at is None
        assert row.activated_at is None
        assert row.submitted_at is None
        assert row.stripe_onboarding_status == "complete"
        assert row.stripe_payouts_enabled is True
        assert row.stripe_details_submitted is True
        assert row.stripe_account_id == account_id


def test_no_financial_movement_or_customer_payment_write(client: TestClient) -> None:
    before = 0
    with SessionLocal() as db:
        before = db.query(AmicorCustomerPayment).count()
    payload = _account_updated_event(account_id=f"acct_test_{uuid4().hex[:10]}")
    response = _post_connect(client, payload)
    assert response.status_code == 200
    payment = client.post(
        PAYMENT_WEBHOOK_PATH,
        content=_signed(
            {
                "id": f"evt_{uuid4().hex}",
                "object": "event",
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_not_from_connect", "object": "payment_intent"}},
            },
            CONNECT_SECRET,
        )[0],
        headers={"Stripe-Signature": "t=1,v1=nope", "Content-Type": "application/json"},
    )
    assert payment.status_code == 400
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).count() == before


def test_no_secret_signature_token_or_payload_leakage(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    account_id = f"acct_test_{uuid4().hex[:10]}"
    app = _seed_application(account_id=account_id)
    token_value = "applicant-token-value-not-a-session"
    payload = _account_updated_event(account_id=account_id)
    with caplog.at_level(logging.INFO):
        response = _post_connect(client, payload)
    dumped = response.text + "".join(record.getMessage() for record in caplog.records)
    assert response.status_code == 200
    assert CONNECT_SECRET not in dumped
    assert PAYMENT_SECRET not in dumped
    assert account_id not in dumped
    assert payload["id"] not in dumped
    assert token_value not in dumped
    assert app.id not in dumped
    assert "Stripe-Signature" not in dumped


def test_independent_fail_soft_behavior(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.platform_ops.onboarding import connect_webhook as webhook

    def boom(*_args, **_kwargs):
        raise RuntimeError("processing exploded")

    monkeypatch.setattr(webhook, "process_connect_webhook_event", boom)
    payload = _account_updated_event(account_id="acct_unused")
    response = _post_connect(client, payload)
    assert response.status_code == 200
    assert response.json()["handled"] is False
    assert response.json()["result"] == "ignored"
    assert "processing exploded" not in response.text


def test_customer_payment_webhook_remains_separate(client: TestClient) -> None:
    payload = {
        "id": f"evt_{uuid4().hex}",
        "object": "event",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": f"pi_{uuid4().hex[:24]}",
                "object": "payment_intent",
                "amount": 1000,
                "amount_received": 1000,
                "currency": "usd",
                "metadata": {"service_type": "RIDE", "ride_id": f"ride-{uuid4().hex[:8]}"},
            }
        },
    }
    body, signature = _signed(payload, CONNECT_SECRET)
    connect = client.post(
        CONNECT_WEBHOOK_PATH,
        content=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )
    assert connect.status_code == 200
    assert connect.json()["handled"] is False
    with SessionLocal() as db:
        assert db.query(AmicorCustomerPayment).filter_by(stripe_payment_intent_id=payload["data"]["object"]["id"]).count() == 0


def test_unsigned_payments_readiness_remains_401(client: TestClient) -> None:
    response = client.get("/api/nova/payments/readiness")
    assert response.status_code == 401
