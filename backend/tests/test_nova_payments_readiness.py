"""Nova V2 Payments Phase 1: read-only Stripe readiness. No Stripe writes."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import (
    DEFAULT_ORGANIZATION_NAME,
    ROLE_SUPER_ADMIN_SUPPORT,
    SEED_PASSWORD,
    _serialize_authorized_roles,
    ensure_auth_schema,
    hash_password,
    seed_default_users,
)
from app.core.nova.payments.classify import classify_key_mode, modes_match
from app.db.models import User as UserModel
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
PAGE_HTML = (STATIC / "nova-payments" / "index.html").read_text(encoding="utf-8")
PAGE_JS = (STATIC / "nova-payments" / "readiness.js").read_text(encoding="utf-8")
PAGE_CSS = (STATIC / "nova-payments" / "readiness.css").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
HOME_JS = (STATIC / "nova-home" / "home.js").read_text(encoding="utf-8")
TODAY_HTML = (STATIC / "nova-today" / "index.html").read_text(encoding="utf-8")
ACCT_HTML = (STATIC / "nova-accounting" / "index.html").read_text(encoding="utf-8")
AGING_HTML = (STATIC / "nova-accounting" / "aging.html").read_text(encoding="utf-8")
TREND_HTML = (STATIC / "nova-accounting" / "trends.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
FROZEN_V1 = [
    STATIC / "nova-home" / "home.js",
    STATIC / "nova-workspace" / "workspace.js",
    STATIC / "nova-communications" / "communications.js",
    STATIC / "nova-government" / "government.js",
    STATIC / "nova-business" / "business.js",
    ROOT / "app" / "core" / "nova" / "router.py",
    ROOT / "app" / "core" / "nova" / "service.py",
]
SECRET_SHAPED = ("sk_test_51SECRETVALUEONLY", "pk_live_51SECRETVALUEONLY", "whsec_SECRETVALUEONLY")
FORBIDDEN_CONTROLS = (
    "Create account",
    "Activate LIVE",
    "Register webhook",
    "Rotate key",
    "Start payout",
    "Onboard driver",
    "Retry payment",
    "Repair webhook",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.modules.payments.models import ensure_payments_test_schema

    ensure_auth_schema()
    seed_default_users()
    ensure_payments_test_schema()
    _ensure_super_admin()
    return TestClient(app)


def _ensure_super_admin() -> None:
    with SessionLocal() as db:
        existing = db.query(UserModel).filter(UserModel.email == "superadmin@amicor.local").first()
        admin = db.query(UserModel).filter(UserModel.email == "admin@amicor.local").first()
        org_id = admin.organization_id if admin is not None else None
        if existing is None:
            db.add(
                UserModel(
                    email="superadmin@amicor.local",
                    hashed_password=hash_password(SEED_PASSWORD),
                    display_name="Amicor Super Admin",
                    role=ROLE_SUPER_ADMIN_SUPPORT,
                    authorized_roles=_serialize_authorized_roles((ROLE_SUPER_ADMIN_SUPPORT,)),
                    session_role=ROLE_SUPER_ADMIN_SUPPORT,
                    organization_name=DEFAULT_ORGANIZATION_NAME,
                    organization_id=org_id,
                    is_active=True,
                    is_verified=True,
                )
            )
        else:
            existing.role = ROLE_SUPER_ADMIN_SUPPORT
            existing.session_role = ROLE_SUPER_ADMIN_SUPPORT
            existing.is_active = True
        db.commit()


def _headers(client: TestClient, email: str = "admin@amicor.local") -> tuple[dict[str, str], str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, str(body["organization_id"])


def _counts() -> dict[str, int]:
    from app.core.nova.freight.models import NovaFreightInvoice
    from app.modules.health_isf.models import HealthISFRide
    from app.modules.payments.models import AmicorCustomerPayment
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication
    from sqlalchemy import text

    with SessionLocal() as db:
        return {
            "freight_shipments": int(db.execute(text("SELECT COUNT(*) FROM nova_freight_shipments")).scalar() or 0),
            "freight_invoices": db.query(NovaFreightInvoice).count(),
            "health_rides": db.query(HealthISFRide).count(),
            "customer_payments": db.query(AmicorCustomerPayment).count(),
            "driver_001": db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .count(),
        }


def _check(body: dict, key: str) -> dict:
    for section in body.get("sections") or []:
        for row in section.get("checks") or []:
            if row.get("key") == key:
                return row
    raise AssertionError(f"missing check {key}")


def _dumped(body: dict) -> str:
    return json.dumps(body)


def test_classify_test_live_and_unverified() -> None:
    test_key = classify_key_mode("sk_test_example")
    live_key = classify_key_mode("pk_live_example")
    missing = classify_key_mode("")
    unknown = classify_key_mode("not-a-stripe-key")
    assert test_key.mode == "TEST" and test_key.status == "Configured"
    assert live_key.mode == "LIVE" and live_key.status == "Configured"
    assert missing.status == "Missing"
    assert unknown.status == "Not verified" and unknown.present is True
    assert modes_match(test_key, live_key) == "Blocked"
    assert modes_match(test_key, classify_key_mode("pk_test_example")) == "Configured"
    assert modes_match(missing, test_key) == "Missing"
    assert modes_match(unknown, test_key) == "Not verified"


def test_payments_readiness_page_and_nav() -> None:
    assert "Payments Readiness" in PAGE_HTML
    assert "Configured is not verified" in PAGE_HTML
    assert "TEST is not LIVE" in PAGE_HTML
    assert "Customer payment configuration" in PAGE_HTML
    assert "Stripe Connect and driver payout configuration" in PAGE_HTML
    assert "Driver onboarding business gates" in PAGE_HTML
    assert "Operational safety controls" in PAGE_HTML
    assert "Blockers and next actions" in PAGE_HTML
    assert "DRAFT FOR ATTORNEY REVIEW" in PAGE_HTML
    assert 'name="viewport"' in PAGE_HTML
    assert "@media (max-width: 390px)" in PAGE_CSS
    assert "min-height: 44px" in PAGE_CSS
    assert "/api/nova/payments/readiness" in PAGE_JS
    assert 'href="/nova/payments/readiness"' in HOME_HTML
    assert 'href="/nova/payments/readiness">Payments Readiness</a>' in TODAY_HTML
    assert 'href="/nova/payments/readiness">Payments Readiness</a>' in ACCT_HTML
    assert 'href="/nova/payments/readiness">Payments Readiness</a>' in AGING_HTML
    assert 'href="/nova/payments/readiness">Payments Readiness</a>' in TREND_HTML
    for label in FORBIDDEN_CONTROLS:
        assert label not in PAGE_HTML
        assert label not in PAGE_JS
    assert "method=\"POST\"" not in PAGE_HTML or "login-form" in PAGE_HTML
    assert "/api/nova/payments/pay" not in PAGE_JS
    assert "sk_live" not in PAGE_JS
    assert "pk_live" not in PAGE_JS
    assert "whsec_" not in PAGE_HTML + PAGE_JS
    assert "DRV-001" not in PAGE_HTML + PAGE_JS
    assert "Driver 001" not in PAGE_HTML + PAGE_JS


def test_payments_readiness_auth_matrix(client: TestClient) -> None:
    page = client.get("/nova/payments/readiness")
    assert page.status_code == 200
    assert "Payments Readiness" in page.text
    assert "sk_test_" not in page.text
    assert "whsec_" not in page.text
    assert client.get("/api/nova/payments/readiness").status_code == 401

    admin, _ = _headers(client, "admin@amicor.local")
    super_admin, _ = _headers(client, "superadmin@amicor.local")
    dispatcher, _ = _headers(client, "dispatcher@amicor.local")
    staff, _ = _headers(client, "staff@amicor.local")
    driver, _ = _headers(client, "driver@amicor.local")

    assert client.get("/api/nova/payments/readiness", headers=admin).status_code == 200
    assert client.get("/api/nova/payments/readiness", headers=super_admin).status_code == 200
    assert client.get("/api/nova/payments/readiness", headers=dispatcher).status_code == 403
    assert client.get("/api/nova/payments/readiness", headers=staff).status_code == 403
    assert client.get("/api/nova/payments/readiness", headers=driver).status_code == 403
    applicant = client.get(
        "/api/nova/payments/readiness",
        headers={"X-Applicant-Token": "applicant-token-value-not-a-session"},
    )
    assert applicant.status_code == 403
    assert "sections" not in (applicant.json() or {})
    cross = client.get(
        "/api/nova/payments/readiness",
        headers=admin,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403


def test_payments_readiness_write_routes_refused(client: TestClient) -> None:
    headers, _ = _headers(client)
    for path in (
        "/api/nova/payments/pay",
        "/api/nova/payments/payout",
        "/api/nova/payments/activate",
        "/api/nova/payments/onboard",
        "/api/nova/payments/webhook",
        "/api/nova/payments/connect",
        "/api/nova/payments/refund",
        "/api/nova/payments/live",
        "/api/nova/payments/key",
    ):
        assert client.post(path, headers=headers).status_code == 403
    assert client.patch("/api/nova/payments/readiness", headers=headers).status_code in {403, 405}
    assert client.put("/api/nova/payments/readiness", headers=headers).status_code in {403, 405}
    assert client.delete("/api/nova/payments/readiness", headers=headers).status_code in {403, 405}


def test_configured_versus_verified_and_missing_versus_unverified(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_exampleonly")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_exampleonly")
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", "whsec_exampleonly")
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    headers, _ = _headers(client)
    body = client.get("/api/nova/payments/readiness", headers=headers).json()
    assert body["go_live_displayed"] is False
    assert body["live_customer_payments_verified"] is False
    assert body["live_driver_payouts_verified"] is False
    assert body["stripe_mode"] == "TEST"
    assert _check(body, "secret_key_mode")["status"] == "Configured"
    assert _check(body, "secret_key_mode")["classification"] == "TEST"
    assert _check(body, "connect_webhook_route")["status"] == "Missing"
    assert _check(body, "connect_webhook_configured")["status"] == "Missing"
    assert _check(body, "connect_webhook_verified")["status"] == "Not verified"
    assert _check(body, "connect_webhook_route")["status"] != _check(body, "connect_webhook_verified")["status"]
    assert _check(body, "customer_webhook_signing")["status"] == "Configured"
    assert _check(body, "ica_attorney_draft")["status"] == "Configured"
    assert "DRAFT FOR ATTORNEY REVIEW" in _check(body, "ica_attorney_draft")["explanation"]
    assert _check(body, "staff_approval_required")["status"] == "Configured"
    assert _check(body, "submit_cannot_activate")["status"] == "Configured"
    dumped = _dumped(body)
    assert "sk_test_exampleonly" not in dumped
    assert "pk_test_exampleonly" not in dumped
    assert "whsec_exampleonly" not in dumped
    assert "applicant-token" not in dumped
    assert all(row.get("action_authorized_now") is False for row in body["blockers"])


def test_mismatched_key_modes_are_blocked(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_exampleonly")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get("/api/nova/payments/readiness", headers=headers).json()
    assert _check(body, "key_modes_match")["status"] == "Blocked"
    assert body["stripe_mode"] == "Not verified"
    assert "sk_live_exampleonly" not in _dumped(body)
    assert "pk_test_exampleonly" not in _dumped(body)


def test_unclassifiable_secret_is_not_verified(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "unusual-secret-format")
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", "pk_test_exampleonly")
    headers, _ = _headers(client)
    body = client.get("/api/nova/payments/readiness", headers=headers).json()
    assert _check(body, "secret_key_mode")["status"] == "Not verified"
    assert "unusual-secret-format" not in _dumped(body)


def test_section_fail_soft(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.nova.payments import service as readiness_service

    def boom() -> list:
        raise RuntimeError("inspect failed")

    monkeypatch.setattr(readiness_service, "_connect_section", boom)
    headers, _ = _headers(client)
    body = client.get("/api/nova/payments/readiness", headers=headers).json()
    connect = next(section for section in body["sections"] if section["key"] == "connect_payouts")
    customer = next(section for section in body["sections"] if section["key"] == "customer_payments")
    assert connect["status"] == "unavailable"
    assert connect["checks"][0]["status"] == "Not verified"
    assert customer["status"] == "ok"
    assert customer["checks"]


def test_secret_and_token_exclusion_and_log_safety(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("STRIPE_SECRET_KEY", SECRET_SHAPED[0])
    monkeypatch.setenv("STRIPE_PUBLISHABLE_KEY", SECRET_SHAPED[1])
    monkeypatch.setenv("STRIPE_PAYMENT_WEBHOOK_SECRET", SECRET_SHAPED[2])
    headers, _ = _headers(client)
    with caplog.at_level(logging.INFO):
        response = client.get("/api/nova/payments/readiness", headers=headers)
    assert response.status_code == 200
    dumped = response.text + "".join(record.getMessage() for record in caplog.records)
    for secret in SECRET_SHAPED:
        assert secret not in dumped
    assert "applicant-token-value" not in dumped
    assert "X-Applicant-Token" not in response.text


def test_policy_draft_and_human_approval_reporting(client: TestClient) -> None:
    headers, _ = _headers(client)
    body = client.get("/api/nova/payments/readiness", headers=headers).json()
    required = _check(body, "required_policy_count")
    draft = _check(body, "draft_policy_count")
    published = _check(body, "published_policy_count")
    assert required["status"] == "Configured"
    assert "10" in required["explanation"]
    assert draft["status"] == "Configured"
    assert published["status"] == "Configured"
    assert "0 catalog policies are published" in published["explanation"] or "0" in published["explanation"]
    assert _check(body, "staff_approval_required")["status"] == "Configured"
    names = _dumped(body).lower()
    assert "ssn" not in names
    assert "routing number" not in names
    assert "@amicor.local" not in names


def test_driver_001_and_frozen_boundaries(client: TestClient) -> None:
    before = _counts()
    headers, _ = _headers(client)
    client.get("/nova/payments/readiness")
    client.get("/nova")
    client.get("/nova/today")
    client.get("/nova/accounting")
    client.get("/api/nova/payments/readiness", headers=headers)
    after = _counts()
    assert after == before
    bundle = PAGE_HTML + PAGE_JS + PAGE_CSS
    assert "DRV-001" not in bundle
    assert "Driver 001" not in bundle
    assert "nova-payments" not in OPS_JS
    assert "/api/nova/payments" not in HOME_JS
    for path in FROZEN_V1:
        text = path.read_text(encoding="utf-8")
        assert "nova_payments_readiness" not in text
        assert "/api/nova/payments/readiness" not in text


def test_accounting_phases_unchanged(client: TestClient) -> None:
    headers, _ = _headers(client, "dispatcher@amicor.local")
    summary = client.get("/api/nova/accounting/summary", headers=headers)
    aging = client.get("/api/nova/accounting/aging", headers=headers)
    trends = client.get("/api/nova/accounting/trends", headers=headers)
    assert summary.status_code == 200
    assert aging.status_code == 200
    assert trends.status_code == 200
    assert len(summary.json()["metrics"]) == 6
    assert aging.json().get("customer_payment_pipeline")
    assert aging.json().get("freight_invoice_pipeline")
    assert trends.json().get("streams")
    assert trends.json().get("months") == 12
