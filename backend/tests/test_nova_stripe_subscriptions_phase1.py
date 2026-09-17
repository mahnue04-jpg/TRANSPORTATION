"""Nova SaaS subscription billing Phase 1. Stripe TEST doubles only. No live charges."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DEFAULT_AUTHORIZED,
    SEED_PASSWORD,
    _serialize_authorized_roles,
    ensure_auth_schema,
    hash_password,
    seed_default_users,
)
from app.core.nova.billing.models import NovaBillingWebhookEvent, NovaTenantSubscription
from app.core.nova.billing.plans import nova_subscription_enforcement_enabled
from app.core.nova.billing.schema_ensure import ensure_nova_billing_schema
from app.core.nova.billing.service import nova_subscription_has_access
from app.core.nova.billing.stripe_client import FakeNovaBillingStripeClient, set_nova_billing_stripe_override
from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
from app.core.nova.today.schema_ensure import ensure_nova_today_schema
from app.db.models import User as UserModel
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFOrganization, ensure_health_isf_schema

WEBHOOK_SECRET = "whsec_nova_billing_test_only"
PRICE_STARTER = "price_nova_starter_test"
PRICE_PRO = "price_nova_professional_test"
PRICE_BIZ = "price_nova_business_test"


def _signed_webhook(payload: dict, secret: str = WEBHOOK_SECRET) -> tuple[bytes, str]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{body.decode('utf-8')}"
    digest = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def _reset_billing() -> None:
    ensure_nova_billing_schema(engine)
    with SessionLocal() as db:
        db.query(NovaBillingWebhookEvent).delete()
        db.query(NovaTenantSubscription).delete()
        db.commit()


def _env(monkeypatch) -> FakeNovaBillingStripeClient:
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_nova_billing_fake")
    monkeypatch.setenv("STRIPE_NOVA_BILLING_WEBHOOK_SECRET", WEBHOOK_SECRET)
    monkeypatch.setenv("NOVA_STRIPE_PRICE_STARTER", PRICE_STARTER)
    monkeypatch.setenv("NOVA_STRIPE_PRICE_PROFESSIONAL", PRICE_PRO)
    monkeypatch.setenv("NOVA_STRIPE_PRICE_BUSINESS", PRICE_BIZ)
    monkeypatch.setenv("NOVA_FREE_TRIAL_DAYS", "7")
    monkeypatch.setenv("NOVA_SUBSCRIPTION_ENFORCEMENT", "false")
    fake = FakeNovaBillingStripeClient()
    set_nova_billing_stripe_override(fake)
    _reset_billing()
    return fake


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_health_isf_schema()
    ensure_nova_today_schema(engine)
    ensure_nova_signup_schema(engine)
    ensure_nova_billing_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "admin@amicor.local", password: str = SEED_PASSWORD) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _admin_org() -> str:
    with SessionLocal() as db:
        user = db.query(UserModel).filter(UserModel.email == "admin@amicor.local").first()
        assert user is not None
        return str(user.organization_id)


def _create_other_admin() -> tuple[str, str]:
    email = f"billing.owner.{uuid4()[:8]}@example.com"
    password = "NovaBill-001-Qx7!"
    org_id = uuid4()
    with SessionLocal() as db:
        db.add(
            HealthISFOrganization(
                id=org_id,
                name=f"Nova Billing Org {org_id[:8]}",
                code=f"NVB-{org_id[:8]}",
                is_active=True,
            )
        )
        db.add(
            UserModel(
                email=email,
                hashed_password=hash_password(password),
                display_name="Billing Owner",
                role=ROLE_ADMIN,
                session_role=ROLE_ADMIN,
                authorized_roles=_serialize_authorized_roles(ROLE_DEFAULT_AUTHORIZED[ROLE_ADMIN]),
                organization_id=org_id,
                organization_name="Nova Billing Org",
                is_active=True,
                is_verified=True,
            )
        )
        db.commit()
    return email, password


def test_owner_and_admin_can_create_own_tenant_checkout(monkeypatch) -> None:
    fake = _env(monkeypatch)
    try:
        client = _client()
        headers = _login(client)
        created = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        assert created.status_code == 200, created.text
        body = created.json()
        assert body["plan"] == "starter"
        assert body["checkout_url"].startswith("https://checkout.stripe.com/")
        assert body["trial_applied"] is True
        assert fake.created_customers == 1
        assert fake.created_sessions == 1
        session = next(iter(fake.sessions.values()))
        assert session["mode"] == "subscription"
        assert session["subscription_data"]["trial_period_days"] == 7
        assert session["metadata"]["nova_tenant_id"] == _admin_org()
        assert "sk_" not in json.dumps(body)
        assert "whsec_" not in json.dumps(body)

        email, password = _create_other_admin()
        owner_headers = _login(client, email=email, password=password)
        owner = client.post("/api/nova/billing/checkout", headers=owner_headers, json={"plan_key": "professional"})
        assert owner.status_code == 200, owner.text
        assert owner.json()["plan"] == "professional"
        assert fake.created_customers == 2
    finally:
        set_nova_billing_stripe_override(None)


def test_unauthorized_and_unauthenticated_rejected(monkeypatch) -> None:
    _env(monkeypatch)
    try:
        client = _client()
        anon = client.post("/api/nova/billing/checkout", json={"plan_key": "starter"})
        assert anon.status_code == 401
        assert client.post("/api/nova/billing/portal", json={}).status_code == 401
        assert client.get("/api/nova/billing/subscription").status_code == 401
        driver = _login(client, email="driver@amicor.local")
        denied = client.post("/api/nova/billing/checkout", headers=driver, json={"plan_key": "starter"})
        assert denied.status_code == 403
        assert client.post("/api/nova/billing/portal", headers=driver, json={}).status_code == 403
        assert client.get("/api/nova/billing/subscription", headers=driver).status_code == 403
        dispatcher = _login(client, email="dispatcher@amicor.local")
        denied_disp = client.post("/api/nova/billing/checkout", headers=dispatcher, json={"plan_key": "starter"})
        assert denied_disp.status_code == 403
        assert client.get("/api/nova/billing/subscription", headers=dispatcher).status_code == 403
    finally:
        set_nova_billing_stripe_override(None)


def test_cross_tenant_invalid_plan_and_missing_price(monkeypatch) -> None:
    _env(monkeypatch)
    try:
        client = _client()
        headers = _login(client)
        foreign = client.post(
            "/api/nova/billing/checkout",
            headers=headers,
            json={"plan_key": "starter", "tenant_id": uuid4()},
        )
        assert foreign.status_code == 403
        unknown = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "enterprise"})
        assert unknown.status_code == 422
        monkeypatch.delenv("NOVA_STRIPE_PRICE_BUSINESS", raising=False)
        missing = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "business"})
        assert missing.status_code == 503
    finally:
        set_nova_billing_stripe_override(None)


def test_customer_reused_and_checkout_idempotent(monkeypatch) -> None:
    fake = _env(monkeypatch)
    try:
        client = _client()
        headers = _login(client)
        first = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        second = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["checkout_session_id"] == second.json()["checkout_session_id"]
        assert fake.created_customers == 1
        assert fake.created_sessions == 1
        with SessionLocal() as db:
            rows = db.query(NovaTenantSubscription).all()
            assert len(rows) == 1
            assert rows[0].stripe_customer_id
    finally:
        set_nova_billing_stripe_override(None)


def test_repeat_trial_not_applied(monkeypatch) -> None:
    fake = _env(monkeypatch)
    try:
        client = _client()
        headers = _login(client)
        first = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        assert first.json()["trial_applied"] is True
        with SessionLocal() as db:
            row = db.query(NovaTenantSubscription).one()
            row.stripe_checkout_session_id = None
            row.checkout_url = None
            row.subscription_status = "cancelled"
            row.stripe_subscription_id = None
            db.commit()
        again = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        assert again.status_code == 200, again.text
        assert again.json()["trial_applied"] is False
        session = fake.sessions[again.json()["checkout_session_id"]]
        assert "trial_period_days" not in session["subscription_data"]
    finally:
        set_nova_billing_stripe_override(None)


def test_portal_tenant_isolation(monkeypatch) -> None:
    _env(monkeypatch)
    try:
        client = _client()
        headers = _login(client)
        checkout = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        assert checkout.status_code == 200
        portal = client.post("/api/nova/billing/portal", headers=headers, json={})
        assert portal.status_code == 200, portal.text
        assert portal.json()["portal_url"].startswith("https://billing.stripe.com/")
        email, password = _create_other_admin()
        other = _login(client, email=email, password=password)
        isolated = client.post(
            "/api/nova/billing/portal",
            headers=other,
            json={"tenant_id": _admin_org()},
        )
        assert isolated.status_code in {403, 404}
        missing = client.post("/api/nova/billing/portal", headers=other, json={})
        assert missing.status_code == 404
    finally:
        set_nova_billing_stripe_override(None)


def _post_event(client: TestClient, payload: dict, *, signature: str | None = None, secret: str = WEBHOOK_SECRET):
    body, signed = _signed_webhook(payload, secret=secret)
    headers = {}
    if signature is not False:
        headers["Stripe-Signature"] = signed if signature is None else signature
    return client.post("/api/nova/billing/webhook", content=body, headers=headers)


def test_webhook_signature_required_and_events(monkeypatch) -> None:
    fake = _env(monkeypatch)
    try:
        client = _client()
        headers = _login(client)
        checkout = client.post("/api/nova/billing/checkout", headers=headers, json={"plan_key": "starter"})
        tenant_id = _admin_org()
        customer_id = next(iter(fake.customers))
        session_id = checkout.json()["checkout_session_id"]

        unsigned = client.post(
            "/api/nova/billing/webhook",
            json={"id": "evt_unsigned", "type": "checkout.session.completed", "data": {"object": {}}},
        )
        assert unsigned.status_code == 400

        bad = _post_event(
            client,
            {"id": "evt_bad", "type": "checkout.session.completed", "data": {"object": {}}},
            signature="t=1,v1=deadbeef",
        )
        assert bad.status_code == 400

        completed = {
            "id": "evt_checkout_1",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": session_id,
                    "customer": customer_id,
                    "subscription": "sub_nova_1",
                    "payment_status": "no_payment_required",
                    "client_reference_id": tenant_id,
                    "metadata": {"nova_tenant_id": tenant_id, "nova_plan_key": "starter"},
                }
            },
        }
        assert _post_event(client, completed).status_code == 200
        dup = _post_event(client, completed)
        assert dup.status_code == 200
        assert dup.json()["duplicate"] is True

        created = {
            "id": "evt_sub_created",
            "type": "customer.subscription.created",
            "data": {
                "object": {
                    "id": "sub_nova_1",
                    "object": "subscription",
                    "status": "trialing",
                    "customer": customer_id,
                    "cancel_at_period_end": False,
                    "trial_start": int(time.time()),
                    "trial_end": int(time.time()) + 7 * 86400,
                    "current_period_start": int(time.time()),
                    "current_period_end": int(time.time()) + 30 * 86400,
                    "metadata": {"nova_tenant_id": tenant_id, "nova_plan_key": "starter"},
                }
            },
        }
        assert _post_event(client, created).status_code == 200
        updated = dict(created)
        updated["id"] = "evt_sub_updated"
        updated["type"] = "customer.subscription.updated"
        updated["data"]["object"] = dict(created["data"]["object"], status="active")
        assert _post_event(client, updated).status_code == 200
        paid = {
            "id": "evt_invoice_paid",
            "type": "invoice.paid",
            "data": {"object": {"id": "in_paid", "customer": customer_id, "subscription": "sub_nova_1", "paid": True}},
        }
        assert _post_event(client, paid).status_code == 200
        failed = {
            "id": "evt_invoice_failed",
            "type": "invoice.payment_failed",
            "data": {"object": {"id": "in_fail", "customer": customer_id, "subscription": "sub_nova_1", "paid": False}},
        }
        assert _post_event(client, failed).status_code == 200
        deleted = {
            "id": "evt_sub_deleted",
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": "sub_nova_1",
                    "object": "subscription",
                    "status": "canceled",
                    "customer": customer_id,
                    "current_period_end": int((datetime.now(timezone.utc) - timedelta(days=1)).timestamp()),
                    "metadata": {"nova_tenant_id": tenant_id},
                }
            },
        }
        assert _post_event(client, deleted).status_code == 200

        with SessionLocal() as db:
            row = db.query(NovaTenantSubscription).filter(NovaTenantSubscription.tenant_id == tenant_id).one()
            assert row.subscription_status == "expired"
            assert db.query(NovaBillingWebhookEvent).count() == 6
        status = client.get("/api/nova/billing/subscription", headers=headers)
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "expired"
        assert payload["plan"] == "starter"
        assert payload["enforcement"] is False
        assert "stripe_secret" not in json.dumps(payload).lower()
        assert "sk_test" not in json.dumps(payload)
        assert "whsec_" not in json.dumps(payload)
    finally:
        set_nova_billing_stripe_override(None)


def test_enforcement_defaults_off_and_existing_nova_access(monkeypatch) -> None:
    _env(monkeypatch)
    try:
        assert nova_subscription_enforcement_enabled() is False
        assert nova_subscription_has_access(None) is True
        assert nova_subscription_has_access("expired") is True
        assert nova_subscription_has_access("trialing", enforcement=True) is True
        assert nova_subscription_has_access("active", enforcement=True) is True
        assert nova_subscription_has_access("past_due", enforcement=True, past_due_access=False) is False
        client = _client()
        dispatcher = _login(client, email="dispatcher@amicor.local")
        today = client.get("/api/nova/today/dashboard", headers=dispatcher)
        assert today.status_code == 200, today.text
        admin = _login(client)
        status = client.get("/api/nova/billing/subscription", headers=admin)
        assert status.status_code == 200
        assert status.json()["has_access"] is True
        assert status.json()["enforcement"] is False
    finally:
        set_nova_billing_stripe_override(None)
