"""Customer and owner Operations interfaces, with sales left closed.

Synthetic only. No Stripe network, no production database, and no live charges.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.work_revenue.operations_revenue_recording import (
    record_operations_revenue_event,
)
from app.core.nova.work_revenue.operations_subscription_entitlement import (
    SubscriptionNotEntitled,
    from_reconciled_test_subscription,
)
from app.db.session import get_db
from app.main import app
import operations_payment_intake as intake


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://amicor-health-isf-py.onrender.com"
PACKAGES = {
    "starter": 999,
    "starter_49": 4900,
    "launch_99": 9900,
    "business_299": 29900,
}


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

    def get(self, model, ident):
        if self.account is not None and ident == self.account.id:
            return self.account
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        return None

    def rollback(self):
        return None


class RevenueDb:
    def __init__(self):
        self.rows = []

    def query(self, model):
        return self

    def filter(self, *args):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def add(self, row):
        self.rows.append(row)


@pytest.fixture
def customer_client():
    application = TestClient(app)
    database = FakeDb()
    user = UserContext(
        user_id="user-1", email="buyer@example.invalid", role="staff", organization_id="org-1",
    )
    application.app.dependency_overrides[get_current_user_context] = lambda: user
    application.app.dependency_overrides[get_db] = lambda: database
    try:
        yield application, database
    finally:
        application.app.dependency_overrides.clear()


def test_dedicated_interfaces_and_purchase_route():
    client = TestClient(app)
    customer = client.get("/nova/operations/customer")
    owner = client.get("/nova/operations/owner")
    assert customer.status_code == 200
    assert owner.status_code == 200
    for amount in ("$9.99", "$49", "$99", "$299"):
        assert amount in customer.text
    assert "Operations Agent" in customer.text
    assert 'id="continue-payment"' in customer.text
    assert "Run private storage round-trip test" in owner.text
    assert 'id="storage-probe"' in owner.text
    assert client.get("/api/nova/starter/interface").status_code == 401
    assert client.get("/api/nova/work/operations/customer/deliveries").status_code == 401
    assert client.post("/api/nova/work/operations/owner/storage-probe").status_code == 401

    script = (ROOT / "website" / "assets" / "js" / "operations-checkout.js").read_text(encoding="utf-8")
    pricing = (ROOT / "website" / "pricing" / "index.html").read_text(encoding="utf-8")
    assert 'APP_ORIGIN + "/nova/operations/customer?signin=1&operations_package="' in script
    assert 'next.pathname === "/nova/operations/customer"' in script
    for package in PACKAGES:
        assert package + ": true" in script
        assert f"/nova/operations/customer?signin=1&amp;operations_package={package}" in pricing
    assert script.count(ORIGIN) == 1
    assert "checkout.stripe.com" not in pricing


def test_authenticated_packages_stay_closed_and_isolated(customer_client):
    application, database = customer_client
    for package, amount in PACKAGES.items():
        intent = application.get("/api/nova/operations/checkout", params={"package": package})
        body = intent.json()
        assert intent.status_code == 200
        assert body["amount_cents"] == amount
        assert body["authenticated"] is True
        assert body["sales_enabled"] is False
        assert body["stripe_session_created"] is False
        assert body["executes_work"] is False
        fulfillment = application.get("/api/nova/operations/fulfillment", params={"package": package})
        lane = fulfillment.json()
        assert fulfillment.status_code == 200
        assert lane["executes_work"] is False
        assert "buyer-two@example.invalid" not in fulfillment.text
        denied = application.post(
            "/api/nova/operations/checkout",
            json={"package": package, "email": "buyer-two@example.invalid", "amount_cents": 1},
        )
        assert denied.status_code == 403
    assert database.added == []


def test_authentication_gates_are_closed_until_explicitly_live(monkeypatch):
    for key in (
        "APP_ENV", "AMICOR_ENVIRONMENT", "NOVA_STRIPE_LIVE_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED",
        "NOVA_STRIPE_PRICE_STARTER", "NOVA_BILLING_CHECKOUT_TRIAL_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_LIVE_ENABLED",
        "NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_LIVE_ENABLED",
        "NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_LIVE_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    closed = intake.operations_production_readiness(probe_database=False)
    assert closed["live_sales_enabled"] is False
    assert set(closed["authentication_gates"]) >= {
        "starter_access_mode", "starter_binding_mode", "customer_delivery_mode",
        "revenue_recording_mode", "subscription_adapter_mode",
        "subscription_execution_mode", "subscription_delivery_mode",
    }
    assert all(value == "closed" for value in closed["authentication_gates"].values())
    assert closed["interfaces"]["customer"] == "/nova/operations/customer"
    assert closed["interfaces"]["owner"] == "/nova/operations/owner"

    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    monkeypatch.setenv("NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED", "true")
    monkeypatch.setenv("NOVA_STRIPE_PRICE_STARTER", "price_1UfWpDBCDlIbm4gm7kY4yIva")
    monkeypatch.setenv("NOVA_BILLING_CHECKOUT_TRIAL_ENABLED", "false")
    for flag in (
        "NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_LIVE_ENABLED",
        "NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_LIVE_ENABLED",
        "NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_LIVE_ENABLED",
    ):
        monkeypatch.setenv(flag, "true")
    opened = intake.operations_production_readiness(probe_database=False)
    assert all(value == "live" for value in opened["authentication_gates"].values())
    assert None not in opened["authentication_gates"].values()


def test_duplicate_payment_and_cancellation_do_not_grant_access(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED", "true")
    database = RevenueDb()
    payload = {"amount_total": 9900, "currency": "usd", "customer": "cus_a"}
    assert record_operations_revenue_event(
        database, event_id="evt_once", event_type="checkout.session.completed",
        lead_id="lead-a", plan="launch_99", obj=payload,
    ) is True
    assert record_operations_revenue_event(
        database, event_id="evt_once", event_type="checkout.session.completed",
        lead_id="lead-a", plan="launch_99", obj=payload,
    ) is False
    assert len(database.rows) == 1
    with pytest.raises(SubscriptionNotEntitled):
        from_reconciled_test_subscription(
            plan="launch_99", lead_id="lead-a", saved_customer_id="cus_a",
            saved_subscription_id="sub_a", saved_payment_status="paid",
            test_price_id="price_launch",
            subscription={
                "id": "sub_a", "customer": "cus_a", "livemode": False, "status": "canceled",
            },
            now=datetime.now(timezone.utc),
        )
