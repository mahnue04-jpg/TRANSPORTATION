"""Synthetic gates for four-package commercial release. No Stripe network or live DB."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue.operations_commercial_mode import (
    operations_live_mode,
    operations_test_mode,
    resolve_operations_mode,
)
from app.core.nova.work_revenue import operations_starter_payment_binding as binding
from app.core.nova.work_revenue.operations_revenue_recording import (
    operations_revenue_mode,
    record_operations_revenue_event,
)
from app.modules.marketing.subscription_checkout_verification import (
    subscription_checkout_outcome,
    subscription_id_from_object,
)


LIVE_ENV = {
    "APP_ENV": "production",
    "AMICOR_ENVIRONMENT": "production",
    "NOVA_STRIPE_LIVE_ENABLED": "true",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "true",
}
STAGING_ENV = {
    "APP_ENV": "staging",
    "AMICOR_ENVIRONMENT": "staging",
    "NOVA_STRIPE_LIVE_ENABLED": "false",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "false",
}


@pytest.fixture
def clear_mode(monkeypatch):
    for key in (
        "APP_ENV", "AMICOR_ENVIRONMENT", "NOVA_STRIPE_LIVE_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_REVENUE_RECORDING_ENABLED",
        "NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_WEBHOOK_STAGING_ENABLED",
        "NOVA_OPERATIONS_SUBSCRIPTION_WEBHOOK_LIVE_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)


def test_modes_disabled_by_default(clear_mode):
    assert operations_test_mode() is False
    assert operations_live_mode() is False
    assert resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_STARTER_BINDING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",),
    ) is None
    assert operations_revenue_mode() is None


def test_staging_mode_requires_explicit_feature_flag(clear_mode, monkeypatch):
    for key, value in STAGING_ENV.items():
        monkeypatch.setenv(key, value)
    assert resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_STARTER_BINDING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",),
    ) is None
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_ENABLED", "true")
    assert resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_STARTER_BINDING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",),
    ) == "test"


def test_live_mode_never_infers_from_key_alone(clear_mode, monkeypatch):
    for key, value in LIVE_ENV.items():
        monkeypatch.setenv(key, value)
    assert resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_STARTER_BINDING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",),
    ) is None
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED", "true")
    assert resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_STARTER_BINDING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",),
    ) == "live"


def test_starter_binding_live_twin(clear_mode, monkeypatch):
    for key, value in LIVE_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED", "true")
    assert binding.starter_binding_mode() == "live"
    lead = SimpleNamespace(
        id="lead-1", lead_type="anonymous_operations", service_plan="starter_49",
        payment_status="paid", consent=True, stripe_checkout_session_id="cs_live_1",
        starter_paid_session_id="cs_live_1", stripe_customer_id="cus_live_1",
        starter_payment_intent_id="pi_live_1", starter_entitlement_state="active",
        organization_name="Acme Ops", contact_name="Buyer",
    )

    class FakeSession:
        def __init__(self):
            self.inserted = []
            self.commits = 0
            self.existing = None

        def get(self, model, key):
            return lead if key == lead.id else None

        def execute(self, stmt):
            if stmt.is_select:
                return SimpleNamespace(first=lambda: self.existing)
            self.inserted.append(stmt)
            return SimpleNamespace()

        def commit(self):
            self.commits += 1

        def rollback(self):
            pass

    db = FakeSession()
    binding.bind_paid_starter(
        db, lead_id="lead-1", organization_id="org", owner_user_id="owner",
        engagement_id="eng", task_id="task", client_name="Acme Ops",
    )
    assert db.commits == 1
    assert len(db.inserted) == 1


def test_free_scope_never_records_operations_revenue(clear_mode, monkeypatch):
    for key, value in STAGING_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NOVA_OPERATIONS_REVENUE_RECORDING_ENABLED", "true")
    db = Mock()
    assert record_operations_revenue_event(
        db, event_id="evt_1", event_type="checkout.session.completed",
        lead_id="lead", plan="free_scope", obj={"amount_total": 0},
    ) is False
    db.add.assert_not_called()


@pytest.mark.parametrize("plan,amount", [("launch_99", 9900), ("business_299", 29900)])
def test_subscription_checkout_outcome_accepts_exact_paid_session(clear_mode, monkeypatch, plan, amount):
    monkeypatch.setenv("NOVA_OPERATIONS_LAUNCH_TEST_PRICE_ID", "price_test_launch")
    monkeypatch.setenv("NOVA_OPERATIONS_BUSINESS_TEST_PRICE_ID", "price_test_business")
    lead = SimpleNamespace(
        service_plan=plan, payment_status="pending",
        stripe_checkout_session_id="cs_sub", stripe_customer_id="cus_sub",
    )
    obj = {
        "id": "cs_sub", "customer": "cus_sub", "mode": "subscription",
        "currency": "usd", "amount_total": amount, "payment_status": "paid",
        "livemode": False, "subscription": "sub_exact",
        "line_items": {"data": [{"quantity": 1, "price": {
            "id": "price_test_launch" if plan == "launch_99" else "price_test_business",
        }}]},
    }
    metadata = {"nova_agent_plan": plan}
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", obj, metadata, expected_livemode=False,
    ) == "paid"
    assert subscription_id_from_object(obj) == "sub_exact"


@pytest.mark.parametrize("plan,amount", [("launch_99", 9900), ("business_299", 29900)])
def test_subscription_checkout_rejects_amount_or_price_mismatch(clear_mode, monkeypatch, plan, amount):
    monkeypatch.setenv("NOVA_OPERATIONS_LAUNCH_TEST_PRICE_ID", "price_test_launch")
    monkeypatch.setenv("NOVA_OPERATIONS_BUSINESS_TEST_PRICE_ID", "price_test_business")
    lead = SimpleNamespace(
        service_plan=plan, payment_status="pending",
        stripe_checkout_session_id="cs_sub", stripe_customer_id="cus_sub",
    )
    bad_amount = {
        "id": "cs_sub", "customer": "cus_sub", "mode": "subscription",
        "currency": "usd", "amount_total": amount - 1, "payment_status": "paid",
        "livemode": False,
    }
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", bad_amount, {"nova_agent_plan": plan},
        expected_livemode=False,
    ) == "subscription_payment_amount_mismatch"
    bad_price = {
        "id": "cs_sub", "customer": "cus_sub", "mode": "subscription",
        "currency": "usd", "amount_total": amount, "payment_status": "paid",
        "livemode": False,
        "line_items": {"data": [{"quantity": 1, "price": {"id": "price_wrong"}}]},
    }
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", bad_price, {"nova_agent_plan": plan},
        expected_livemode=False,
    ) == "subscription_price_mismatch"


def test_live_subscription_requires_catalog_price(clear_mode, monkeypatch):
    from app.core.nova.billing.operations_catalog import LIVE_OPERATIONS_PRICES
    lead = SimpleNamespace(
        service_plan="launch_99", payment_status="pending",
        stripe_checkout_session_id="cs_live", stripe_customer_id="cus_live",
    )
    obj = {
        "id": "cs_live", "customer": "cus_live", "mode": "subscription",
        "currency": "usd", "amount_total": 9900, "payment_status": "paid",
        "livemode": True, "subscription": "sub_live",
        "line_items": {"data": [{"quantity": 1, "price": {
            "id": LIVE_OPERATIONS_PRICES["launch_99"],
        }}]},
    }
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", obj, {"nova_agent_plan": "launch_99"},
        expected_livemode=True,
    ) == "paid"


def test_adapter_live_mode_gate(clear_mode, monkeypatch):
    from app.core.nova.work_revenue.operations_authenticated_subscription_adapter import (
        reserve_owner_approved_test_subscription_task,
        subscription_adapter_mode,
    )
    from app.core.nova.work_revenue.operations_package_usage_ledger import AllowanceBlocked

    for key, value in LIVE_ENV.items():
        monkeypatch.setenv(key, value)
    assert subscription_adapter_mode() is None
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED", "true")
    assert subscription_adapter_mode() == "live"
    with pytest.raises(AllowanceBlocked, match="authenticated_owner_required"):
        reserve_owner_approved_test_subscription_task(
            Mock(), authenticated_user=SimpleNamespace(user_id="", organization_id="o", role="admin"),
            organization_id="o", engagement_id="e", task_id="t", lead_id="l",
            request_key="r", task_fingerprint="a" * 64, now=datetime.now(timezone.utc),
        )


def test_execution_and_delivery_live_flags_default_off(clear_mode):
    from app.core.nova.work_revenue.operations_subscription_execution_guard import (
        subscription_execution_mode,
    )
    from app.core.nova.work_revenue.operations_subscription_delivery_guard import (
        subscription_delivery_mode,
    )
    assert subscription_execution_mode() is None
    assert subscription_delivery_mode() is None


def test_delivery_proof_merge_tolerates_shared_mode_key():
    """Regression: proof already includes mode; dict(**proof, mode=...) TypeErrored."""
    proof = {
        "reservation_id": "res",
        "lead_id": "lead",
        "plan": "launch_99",
        "authorized": True,
        "mode": "test",
    }
    merged = {
        **proof,
        "recipient_user_id": "recipient",
        "recipient_organization_id": "recipient-org",
        "output_sha256": "a" * 64,
        "mode": "test",
    }
    assert merged["mode"] == "test"
    assert merged["authorized"] is True
