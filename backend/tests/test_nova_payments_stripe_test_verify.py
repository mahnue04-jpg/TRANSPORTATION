"""Nova V2 Payments Phase 3: read-only Stripe TEST verification.

Uses mocked Stripe retrieve/list only. Does not create, update, delete,
register, or send Stripe objects or events.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.payments.stripe_test_verify import (
    CONNECT_WEBHOOK_URL,
    CUSTOMER_PAYMENT_WEBHOOK_URL,
    reset_test_verification_state,
    set_test_reader_override,
    webhook_urls_exactly_equal,
)
from app.main import app
from app.modules.payments.models import ensure_payments_test_schema


VERIFY_PATH = "/api/nova/payments/readiness/verify"
READINESS_PATH = "/api/nova/payments/readiness"
PAGE_HTML = (Path(__file__).resolve().parents[1] / "static" / "nova-payments" / "index.html").read_text(encoding="utf-8")
PAGE_CSS = (Path(__file__).resolve().parents[1] / "static" / "nova-payments" / "readiness.css").read_text(encoding="utf-8")
SECRET_SHAPED = ("sk_test_51SECRETVALUEONLY", "pk_test_51SECRETVALUEONLY", "whsec_SECRETVALUEONLY")


class FakeStripeTestReader:
    def __init__(self) -> None:
        self.balance_calls = 0
        self.list_calls = 0
        self.balance = {"object": "balance", "livemode": False}
        self.endpoints: list[dict] = []
        self.balance_error: Exception | None = None
        self.list_error: Exception | None = None
        self.delay = 0.0

    @property
    def calls(self) -> int:
        return self.balance_calls + self.list_calls

    def retrieve_platform_balance(self) -> dict:
        self.balance_calls += 1
        if self.delay:
            time.sleep(self.delay)
        if self.balance_error:
            raise self.balance_error
        return dict(self.balance)

    def list_webhook_summaries(self) -> list[dict]:
        self.list_calls += 1
        if self.list_error:
            raise self.list_error
        return [dict(row) for row in self.endpoints]


@pytest.fixture
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_payments_test_schema()
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_verify():
    reset_test_verification_state()
    set_test_reader_override(None)
    yield
    reset_test_verification_state()
    set_test_reader_override(None)


def _headers(client: TestClient, email: str = "admin@amicor.local") -> tuple[dict[str, str], str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, str(body["organization_id"])


def _check(body: dict, key: str) -> dict:
    for section in body.get("sections") or []:
        for row in section.get("checks") or []:
            if row.get("key") == key:
                return row
    raise AssertionError(f"missing check {key}")


def _matched_endpoints() -> list[dict]:
    return [
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
            "enabled_events": ["account.updated", "v2.core.account.updated"],
        },
        {
            "url": "https://unrelated.example/hooks",
            "status": "enabled",
            "livemode": False,
            "enabled_events": ["*"],
            "id": "we_should_never_appear",
        },
    ]


def test_signed_out_verify_causes_zero_stripe_calls(client: TestClient) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    assert client.get(VERIFY_PATH).status_code == 401
    assert client.get(READINESS_PATH).status_code == 401
    assert fake.calls == 0


def test_unauthorized_role_causes_zero_stripe_calls(client: TestClient) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    headers, _ = _headers(client, "dispatcher@amicor.local")
    assert client.get(VERIFY_PATH, headers=headers).status_code == 403
    assert fake.calls == 0


def test_cross_organization_causes_zero_stripe_calls(client: TestClient) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    headers, _ = _headers(client)
    response = client.get(VERIFY_PATH, headers=headers, params={"organization_id": "org-not-the-caller"})
    assert response.status_code == 403
    assert fake.calls == 0


def test_live_credential_blocks_without_stripe_calls(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_exampleonly")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert body["go_live_displayed"] is False
    assert _check(body, "test_platform_auth")["status"] == "Blocked"
    assert fake.calls == 0
    assert "sk_live_exampleonly" not in json.dumps(body)


def test_missing_credential_returns_missing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "test_platform_auth")["status"] == "Missing"
    assert fake.calls == 0


def test_ambiguous_credential_not_verified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "unusual-secret-format")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "test_platform_auth")["status"] == "Not verified"
    assert fake.calls == 0
    assert "unusual-secret-format" not in json.dumps(body)


def test_successful_test_authentication_and_exact_webhooks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints = _matched_endpoints()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", "whsec_exampleonly")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_connect_exampleonly")
    headers, _ = _headers(client)
    assert client.get(READINESS_PATH, headers=headers).status_code == 200
    assert fake.calls == 0
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert fake.balance_calls == 1
    assert fake.list_calls == 1
    assert body["go_live_displayed"] is False
    assert _check(body, "test_platform_auth")["status"] == "Verified"
    assert _check(body, "customer_webhook_registration")["status"] == "Verified"
    assert _check(body, "customer_webhook_events")["status"] == "Verified"
    assert _check(body, "connect_webhook_registration")["status"] == "Verified"
    assert _check(body, "connect_webhook_events")["status"] == "Verified"
    assert _check(body, "customer_webhook_signing_match")["status"] == "Configured"
    assert _check(body, "connect_webhook_signing_match")["status"] == "Configured"
    dumped = json.dumps(body)
    assert "we_should_never_appear" not in dumped
    assert "unrelated.example" not in dumped
    assert "sk_test_exampleonly" not in dumped
    assert "whsec_exampleonly" not in dumped
    assert CUSTOMER_PAYMENT_WEBHOOK_URL in _check(body, "customer_webhook_registration")["explanation"]
    assert CONNECT_WEBHOOK_URL in _check(body, "connect_webhook_registration")["explanation"]


def test_executor_timeout_becomes_not_verified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.nova.payments import stripe_test_verify as verify

    fake = FakeStripeTestReader()
    fake.delay = 0.2
    set_test_reader_override(fake)
    monkeypatch.setattr(verify, "VERIFY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "test_platform_auth")["status"] == "Not verified"


def test_timeout_and_sdk_failures_are_not_verified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    fake.balance_error = TimeoutError("timed out")
    timeout_body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(timeout_body, "test_platform_auth")["status"] == "Not verified"
    reset_test_verification_state()
    fake.balance_error = RuntimeError("stripe sdk exploded sk_test_leak we_123")
    error_body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(error_body, "test_platform_auth")["status"] == "Not verified"
    dumped = json.dumps(error_body)
    assert "stripe sdk exploded" not in dumped
    assert "sk_test_leak" not in dumped
    assert "we_123" not in dumped


def test_network_failure_not_verified(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeStripeTestReader()
    fake.balance_error = ConnectionError("network down")
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "test_platform_auth")["status"] == "Not verified"
    assert "network down" not in json.dumps(body)


def test_http_port_lookalike_and_path_mismatches_rejected() -> None:
    expected = CUSTOMER_PAYMENT_WEBHOOK_URL
    assert webhook_urls_exactly_equal(expected, expected) is True
    assert webhook_urls_exactly_equal(expected.replace("https://", "http://"), expected) is False
    assert webhook_urls_exactly_equal(expected.replace(".com/", ".com:8443/"), expected) is False
    assert webhook_urls_exactly_equal(
        "https://evil.amicor-health-isf-py.onrender.com/api/payments/stripe/webhook",
        expected,
    ) is False
    assert webhook_urls_exactly_equal(expected + "/extra", expected) is False
    assert webhook_urls_exactly_equal(CONNECT_WEBHOOK_URL, expected) is False


def test_incomplete_events_and_separate_endpoints(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints = [
        {
            "url": CUSTOMER_PAYMENT_WEBHOOK_URL,
            "status": "enabled",
            "livemode": False,
            "enabled_events": ["payment_intent.succeeded"],
        },
        {
            "url": CONNECT_WEBHOOK_URL,
            "status": "enabled",
            "livemode": False,
            "enabled_events": ["account.updated"],
        },
    ]
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(body, "customer_webhook_registration")["status"] == "Verified"
    assert _check(body, "customer_webhook_events")["status"] == "Not verified"
    assert "Coverage: no" in _check(body, "customer_webhook_events")["explanation"]
    assert _check(body, "connect_webhook_events")["status"] == "Not verified"
    assert "Coverage: not verified" in _check(body, "connect_webhook_events")["explanation"]
    assert _check(body, "customer_webhook_signing_match")["status"] != "Verified"
    assert _check(body, "connect_webhook_signing_match")["status"] != "Verified"


def test_cache_keeps_successful_verified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints = _matched_endpoints()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    first = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(first, "test_platform_auth")["status"] == "Verified"
    fake.balance_error = RuntimeError("later failure")
    second = client.get(VERIFY_PATH, headers=headers).json()
    assert _check(second, "test_platform_auth")["status"] == "Verified"
    cached = client.get(READINESS_PATH, headers=headers).json()
    assert _check(cached, "test_platform_auth")["status"] == "Verified"


def test_rate_limiting(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.nova.payments import stripe_test_verify as verify

    monkeypatch.setattr(verify, "RATE_LIMIT", 2)
    fake = FakeStripeTestReader()
    fake.endpoints = _matched_endpoints()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    headers, _ = _headers(client)
    assert client.get(VERIFY_PATH, headers=headers).status_code == 200
    assert client.get(VERIFY_PATH, headers=headers).status_code == 200
    limited = client.get(VERIFY_PATH, headers=headers)
    assert limited.status_code == 429
    assert "Verification is temporarily limited." in limited.text
    assert "sk_test_" not in limited.text


def test_public_pages_and_probes_cause_zero_stripe_calls(client: TestClient) -> None:
    fake = FakeStripeTestReader()
    set_test_reader_override(fake)
    assert client.get("/nova/payments/readiness").status_code == 200
    assert client.get("/nova").status_code == 200
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/api/health/readiness").status_code in {200, 503}
    assert fake.calls == 0
    assert "section-stripe_test_verification" in PAGE_HTML
    assert "@media (max-width: 390px)" in PAGE_CSS
    assert "min-height: 44px" in PAGE_CSS


def test_no_mutating_sdk_methods_in_adapter() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "core"
        / "nova"
        / "payments"
        / "stripe_test_verify.py"
    ).read_text(encoding="utf-8")
    assert "v1.balance.retrieve" in source
    assert "v1.webhook_endpoints.list" in source
    assert "webhook_endpoints.create" not in source
    assert "accounts.create" not in source
    assert "account_links.create" not in source
    assert ".delete(" not in source
    assert "test_helpers" not in source


def test_secret_and_id_exclusion(client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeStripeTestReader()
    fake.endpoints = _matched_endpoints()
    set_test_reader_override(fake)
    monkeypatch.setenv("STRIPE_SECRET_KEY", SECRET_SHAPED[0])
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", SECRET_SHAPED[1])
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", SECRET_SHAPED[2])
    headers, _ = _headers(client)
    with caplog.at_level(logging.INFO):
        body = client.get(VERIFY_PATH, headers=headers).json()
        page = client.get("/nova/payments/readiness")
    dumped = json.dumps(body) + page.text + "".join(record.getMessage() for record in caplog.records)
    for secret in SECRET_SHAPED:
        assert secret not in dumped
    assert "we_should_never_appear" not in dumped
    assert body["go_live_displayed"] is False
