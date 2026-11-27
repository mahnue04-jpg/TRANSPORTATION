"""Authenticated Operations checkout stays closed unless both sales flags are true."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.db.session import get_db
from app.main import app


class Account:
    def __init__(self, **changes):
        self.id = "user-1"
        self.email = "buyer@example.invalid"
        self.is_active = True
        self.is_verified = True
        self.organization_id = "org-1"
        for key, value in changes.items():
            setattr(self, key, value)


class FakeDb:
    def __init__(self, account=None):
        self.account = Account() if account is None else account
        self.added = []
        self.rolled_back = False

    def get(self, model, ident):
        if self.account is not None and ident == self.account.id:
            return self.account
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if not getattr(obj, "id", None):
                obj.id = "lead-1"

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        raise AssertionError("checkout test must not commit before the payment connector")


CUSTOMER = UserContext(
    user_id="user-1",
    email="buyer@example.invalid",
    role="staff",
    organization_id="org-1",
)


@pytest.fixture
def client():
    application = TestClient(app)
    database = FakeDb()
    application.app.dependency_overrides[get_current_user_context] = lambda: CUSTOMER
    application.app.dependency_overrides[get_db] = lambda: database
    try:
        yield application, database
    finally:
        application.app.dependency_overrides.clear()


def test_checkout_intent_requires_a_verified_customer_and_creates_no_session(client):
    application, database = client
    response = application.get("/api/nova/operations/checkout", params={"package": "launch_99"})
    body = response.json()
    assert response.status_code == 200
    assert body["authenticated"] is True
    assert body["sales_enabled"] is False
    assert body["stripe_session_created"] is False
    assert body["executes_work"] is False
    assert body["amount_cents"] == 9900
    assert body["fulfillment"]["kind"] == "subscription_quota_with_owner_approval"
    assert body["fulfillment"]["managed_task_allowance"] == 3
    assert body["fulfillment"]["executes_work"] is False
    assert "checkout_url" not in body
    assert database.added == []

    fulfillment = application.get("/api/nova/operations/fulfillment", params={"package": "starter_49"})
    lane = fulfillment.json()
    assert fulfillment.status_code == 200
    assert lane["kind"] == "paid_binding_private_delivery"
    assert lane["managed_task_allowance"] == 1
    assert lane["binding_gate"] == "disabled"
    assert lane["delivery_gate"] == "disabled"
    assert lane["executes_work"] is False

    starter = application.get("/api/nova/operations/fulfillment", params={"package": "starter"})
    assert starter.json()["managed_task_allowance"] == 0
    assert starter.json()["kind"] == "self_service"
    business = application.get("/api/nova/operations/fulfillment", params={"package": "business_299"})
    assert business.json()["managed_task_allowance"] == 10


def test_unverified_or_unknown_customers_cannot_purchase(client):
    application, database = client
    database.account = Account(is_verified=False)
    assert application.post("/api/nova/operations/checkout", json={"package": "starter"}).status_code == 403
    database.account = Account(is_active=False)
    assert application.get("/api/nova/operations/checkout", params={"package": "starter"}).status_code == 403
    database.account = Account(email="other@example.invalid")
    assert application.post(
        "/api/nova/operations/checkout",
        json={"package": "starter_49", "email": "buyer@example.invalid", "amount_cents": 1},
    ).status_code == 403
    database.account = None
    assert application.get("/api/nova/operations/fulfillment", params={"package": "starter"}).status_code == 403
    assert application.get("/api/nova/operations/checkout", params={"package": "not-a-plan"}).status_code == 403


def test_anonymous_checkout_is_rejected(monkeypatch):
    monkeypatch.delenv("NOVA_STRIPE_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", raising=False)
    application = TestClient(app)
    try:
        assert application.get("/api/nova/operations/checkout", params={"package": "starter"}).status_code == 401
        assert application.post("/api/nova/operations/checkout", json={"package": "starter"}).status_code == 401
    finally:
        application.app.dependency_overrides.clear()


def test_disabled_sales_never_open_stripe(client, monkeypatch):
    application, database = client
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")

    def forbidden(*args, **kwargs):
        raise AssertionError("Stripe checkout must stay closed")

    monkeypatch.setattr("app.core.nova.billing.service.start_checkout", forbidden)
    monkeypatch.setattr("app.modules.marketing.routes.create_nova_agent_checkout", forbidden)
    response = application.post(
        "/api/nova/operations/checkout",
        json={"package": "business_299", "email": "attacker@evil.invalid", "amount_cents": 100},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Public Operations sales are disabled"
    assert database.added == []


def test_enabled_marketing_checkout_uses_the_signed_in_account_only(client, monkeypatch):
    application, database = client
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    monkeypatch.setattr("app.modules.marketing.models.ensure_marketing_schema", lambda: None)
    seen = {}

    def fake_checkout(lead_id, request, db):
        seen["lead_id"] = lead_id
        return {"checkout_url": "https://checkout.stripe.com/c/pay/cs_test_synthetic", "plan": "starter_49"}

    monkeypatch.setattr("app.modules.marketing.routes.create_nova_agent_checkout", fake_checkout)
    response = application.post(
        "/api/nova/operations/checkout",
        json={"package": "starter_49", "email": "attacker@evil.invalid", "amount_cents": 1},
    )
    body = response.json()
    assert response.status_code == 200
    assert seen["lead_id"] == "lead-1"
    lead = database.added[0]
    assert lead.work_email == "buyer@example.invalid"
    assert lead.service_plan == "starter_49"
    assert lead.source_path == "nova-user:user-1"
    assert lead.lead_source == "authenticated-checkout"
    assert body["stripe_session_created"] is True
    assert body["executes_work"] is False
    assert body["fulfillment"]["executes_work"] is False


def test_enabled_saas_checkout_uses_the_starter_catalog_plan(client, monkeypatch):
    application, _database = client
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    seen = {}

    def fake_start(db, *, user, plan_key, tenant_id=None):
        seen["plan_key"] = plan_key
        seen["email"] = user.email
        return {"checkout_url": "https://checkout.stripe.com/c/pay/cs_test_saas", "plan": plan_key}

    monkeypatch.setattr("app.core.nova.billing.service.start_checkout", fake_start)
    response = application.post("/api/nova/operations/checkout", json={"package": "starter"})
    assert response.status_code == 200
    assert seen == {"plan_key": "starter", "email": "buyer@example.invalid"}
    assert response.json()["stripe_session_created"] is True
    assert response.json()["fulfillment"]["managed_task_allowance"] == 0


def test_checkout_connector_failure_rolls_back_the_lead(client, monkeypatch):
    application, database = client
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    monkeypatch.setattr("app.modules.marketing.models.ensure_marketing_schema", lambda: None)

    def unavailable(*args, **kwargs):
        raise HTTPException(status_code=503, detail="Secure checkout is not available yet.")

    monkeypatch.setattr("app.modules.marketing.routes.create_nova_agent_checkout", unavailable)
    response = application.post("/api/nova/operations/checkout", json={"package": "launch_99"})
    assert response.status_code == 503
    assert database.rolled_back is True


def test_unknown_package_is_rejected_for_a_verified_customer(client):
    application, _database = client
    assert application.get("/api/nova/operations/checkout", params={"package": "free_scope"}).status_code == 422
    assert application.post("/api/nova/operations/checkout", json={"package": "free_scope"}).status_code == 422
    assert application.get("/api/nova/operations/fulfillment", params={"package": "free_scope"}).status_code == 422
