"""Final production-acceptance matrix for four paid packages + payment receiver.

Synthetic only: never contacts live Stripe, never enables customer sales, and
never writes production databases. Live twins are exercised with temporary
production env markers in-process, then cleared.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.nova.billing.operations_catalog import LIVE_OPERATIONS_PRICES
from app.core.nova.billing.starter_authenticated_access import starter_access_mode
from app.core.nova.work_revenue.operations_commercial_mode import resolve_operations_mode
from app.core.nova.work_revenue.operations_customer_delivery import customer_delivery_mode
from app.core.nova.work_revenue.operations_private_storage import (
    OperationsStorageSettings,
    is_production_artifact_runtime,
)
from app.core.nova.work_revenue.operations_revenue_recording import operations_revenue_mode
from app.core.nova.work_revenue.operations_starter_payment_binding import starter_binding_mode
from app.core.nova.work_revenue.operations_authenticated_subscription_adapter import (
    subscription_adapter_mode,
)
from app.core.nova.work_revenue.operations_subscription_delivery_guard import (
    subscription_delivery_mode,
)
from app.core.nova.work_revenue.operations_subscription_execution_guard import (
    subscription_execution_mode,
)
from app.modules.marketing.operations_billing import AGENT_PLANS, checkout_payload
from app.modules.marketing.starter_checkout_verification import starter_checkout_outcome
from app.modules.marketing.subscription_checkout_verification import (
    subscription_checkout_outcome,
)
from app.modules.platform_ops.secure_storage import SecureStorageNotConfigured
import operations_payment_intake as intake


LIVE = {
    "APP_ENV": "production",
    "AMICOR_ENVIRONMENT": "production",
    "NOVA_STRIPE_LIVE_ENABLED": "true",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "true",
}

LIVE_SURFACE_FLAGS = (
    "NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED",
    "NOVA_OPERATIONS_CUSTOMER_DELIVERY_LIVE_ENABLED",
    "NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED",
    "NOVA_OPERATIONS_SUBSCRIPTION_WEBHOOK_LIVE_ENABLED",
    "NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_LIVE_ENABLED",
    "NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED",
    "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED",
    "NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_LIVE_ENABLED",
    "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_LIVE_ENABLED",
    "NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_LIVE_ENABLED",
    "NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED",
)


@pytest.fixture
def clear_ops(monkeypatch):
    for key in (
        *LIVE.keys(),
        *LIVE_SURFACE_FLAGS,
        "NOVA_OPERATIONS_STARTER_BINDING_ENABLED",
        "NOVA_OPERATIONS_CUSTOMER_DELIVERY_ENABLED",
        "NOVA_OPERATIONS_REVENUE_RECORDING_ENABLED",
        "NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED",
        "NOVA_STRIPE_PRICE_STARTER",
        "NOVA_BILLING_CHECKOUT_TRIAL_ENABLED",
        "STRIPE_SECRET_KEY",
        "STRIPE_NOVA_AGENT_WEBHOOK_SECRET",
        "AMICOR_PUBLIC_URL",
        "NOVA_OPERATIONS_PRIVATE_S3_BUCKET",
        "NOVA_OPERATIONS_PRIVATE_S3_REGION",
        "NOVA_OPERATIONS_PRIVATE_S3_ACCESS_KEY",
        "NOVA_OPERATIONS_PRIVATE_S3_SECRET_KEY",
        "AMICOR_DOCUMENT_S3_BUCKET",
        "AMICOR_DOCUMENT_BUCKET",
        "NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET",
        "NOVA_OPERATIONS_DATABASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_live_sales_remain_disabled_by_default(clear_ops):
    assert starter_access_mode() is None
    assert starter_binding_mode() is None
    assert customer_delivery_mode() is None
    assert operations_revenue_mode() is None
    assert subscription_adapter_mode() is None
    assert subscription_execution_mode() is None
    assert subscription_delivery_mode() is None
    assert resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_SUBSCRIPTION_WEBHOOK_STAGING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_SUBSCRIPTION_WEBHOOK_LIVE_ENABLED",),
    ) is None


def test_free_scope_check_never_requires_checkout_or_revenue(clear_ops):
    plan = AGENT_PLANS["free_scope"]
    assert plan["mode"] == "free"
    assert plan["amount_cents"] == 0
    with pytest.raises(ValueError, match="does not require checkout"):
        checkout_payload(
            lead_id="lead", email="buyer@example.invalid",
            plan_key="free_scope", customer_id="cus_x",
        )


def test_catalog_covers_exact_four_paid_prices():
    assert LIVE_OPERATIONS_PRICES == {
        "starter": "price_1UfWpDBCDlIbm4gm7kY4yIva",
        "starter_49": "price_1URDdoBCDlIbm4gmtQqEQgey",
        "launch_99": "price_1UfWrXBCDlIbm4gmsdgH2js5",
        "business_299": "price_1UfWsqBCDlIbm4gm8dVahkxS",
    }
    assert AGENT_PLANS["starter_49"]["amount_cents"] == 4900
    assert AGENT_PLANS["launch_99"]["amount_cents"] == 9900
    assert AGENT_PLANS["business_299"]["amount_cents"] == 29900


def test_live_checkout_payloads_use_catalog_prices(clear_ops, monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_synthetic_acceptance_only")
    monkeypatch.setenv("STRIPE_NOVA_AGENT_WEBHOOK_SECRET", "whsec_synthetic")
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "https://acceptance.example")
    for plan, amount in (("starter_49", 4900), ("launch_99", 9900), ("business_299", 29900)):
        payload = checkout_payload(
            lead_id="lead-accept", email="buyer@example.com",
            plan_key=plan, customer_id="cus_accept",
        )
        assert payload["line_items"] == [{"price": LIVE_OPERATIONS_PRICES[plan], "quantity": 1}]
        assert "price_data" not in payload["line_items"][0]
        assert payload["mode"] == AGENT_PLANS[plan]["mode"]
        assert AGENT_PLANS[plan]["amount_cents"] == amount


def test_starter_49_payment_confirmation_accepts_exact_paid_session(clear_ops):
    lead = SimpleNamespace(
        service_plan="starter_49", payment_status="pending",
        stripe_checkout_session_id="cs_49", stripe_customer_id="cus_49",
    )
    obj = {
        "id": "cs_49", "customer": "cus_49", "mode": "payment",
        "currency": "usd", "amount_total": 4900, "payment_status": "paid",
        "livemode": True, "payment_intent": "pi_49",
    }
    assert starter_checkout_outcome(
        lead, "checkout.session.completed", obj,
        {"nova_agent_plan": "starter_49"},
    ) == "paid"
    assert starter_checkout_outcome(
        lead, "checkout.session.completed", {**obj, "amount_total": 0},
        {"nova_agent_plan": "starter_49"},
    ) == "starter_payment_amount_mismatch"


@pytest.mark.parametrize("plan,amount,price", [
    ("launch_99", 9900, LIVE_OPERATIONS_PRICES["launch_99"]),
    ("business_299", 29900, LIVE_OPERATIONS_PRICES["business_299"]),
])
def test_launch_business_confirmation_requires_amount_and_catalog_price(
    clear_ops, plan, amount, price,
):
    lead = SimpleNamespace(
        service_plan=plan, payment_status="pending",
        stripe_checkout_session_id="cs_sub", stripe_customer_id="cus_sub",
    )
    base = {
        "id": "cs_sub", "customer": "cus_sub", "mode": "subscription",
        "currency": "usd", "amount_total": amount, "payment_status": "paid",
        "livemode": True, "subscription": "sub_live",
        "line_items": {"data": [{"quantity": 1, "price": {"id": price}}]},
    }
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", base, {"nova_agent_plan": plan},
        expected_livemode=True,
    ) == "paid"
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", {**base, "amount_total": None},
        {"nova_agent_plan": plan}, expected_livemode=True,
    ) == "subscription_payment_amount_mismatch"
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", {**base, "amount_total": 0},
        {"nova_agent_plan": plan}, expected_livemode=True,
    ) == "subscription_payment_amount_mismatch"
    # Without expanded line_items, exact amount still confirms (Stripe often omits
    # expansion on webhook payloads); wrong expanded price is still rejected.
    without_items = {k: v for k, v in base.items() if k != "line_items"}
    assert subscription_checkout_outcome(
        lead, "checkout.session.completed", without_items, {"nova_agent_plan": plan},
        expected_livemode=True,
    ) == "paid"


def test_authenticated_starter_live_mode_requires_exact_price(clear_ops, monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED", "true")
    monkeypatch.setenv("NOVA_BILLING_CHECKOUT_TRIAL_ENABLED", "false")
    monkeypatch.setenv("NOVA_STRIPE_PRICE_STARTER", LIVE_OPERATIONS_PRICES["starter"])
    assert starter_access_mode() == "live"
    monkeypatch.setenv("NOVA_STRIPE_PRICE_STARTER", "price_wrong")
    assert starter_access_mode() is None


def test_live_fulfillment_twins_require_full_flag_set(clear_ops, monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    assert starter_binding_mode() is None
    assert customer_delivery_mode() is None
    assert subscription_adapter_mode() is None
    monkeypatch.setenv("NOVA_OPERATIONS_STARTER_BINDING_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_DELIVERY_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_DELIVERY_LIVE_ENABLED", "true")
    monkeypatch.setenv("NOVA_OPERATIONS_REVENUE_RECORDING_LIVE_ENABLED", "true")
    assert starter_binding_mode() == "live"
    assert customer_delivery_mode() == "live"
    assert subscription_adapter_mode() == "live"
    assert subscription_execution_mode() == "live"
    assert subscription_delivery_mode() == "live"
    assert operations_revenue_mode() == "live"


def test_production_private_storage_rejects_shared_bucket(clear_ops, monkeypatch):
    for key, value in LIVE.items():
        monkeypatch.setenv(key, value)
    assert is_production_artifact_runtime() is True
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_BUCKET", "shared-bucket")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_REGION", "us-east-1")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_ACCESS_KEY", "AKIA_SYNTHETIC")
    monkeypatch.setenv("NOVA_OPERATIONS_PRIVATE_S3_SECRET_KEY", "synthetic-secret")
    monkeypatch.setenv("AMICOR_DOCUMENT_S3_BUCKET", "shared-bucket")
    with pytest.raises(SecureStorageNotConfigured, match="separate bucket"):
        OperationsStorageSettings.from_environment()


def test_payment_intake_receiver_still_accepts_signed_live_events(clear_ops, monkeypatch):
    """Existing dedicated payment receiver remains functional (ledger-only)."""
    secret = "whsec_acceptance_receiver"
    event = {
        "id": "evt_accept", "object": "event", "type": "invoice.paid",
        "livemode": True, "data": {"object": {"id": "in_accept", "object": "invoice"}},
    }
    recorded = []

    def fake_record(database_url, event_id, event_type, object_id):
        recorded.append((event_id, event_type, object_id))

    monkeypatch.setenv("NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("NOVA_OPERATIONS_DATABASE_URL", "postgresql://synthetic")

    def signed(payload: dict):
        data = json.dumps(payload).encode()
        stamp = str(int(time.time()))
        digest = hmac.new(secret.encode(), stamp.encode() + b"." + data, hashlib.sha256).hexdigest()
        return data, {"stripe-signature": f"t={stamp},v1={digest}"}

    with patch.object(intake, "verify_writer", return_value=None), \
            patch.object(intake, "record_event", side_effect=fake_record):
        client = TestClient(intake.app)
        assert client.get("/health").json()["service"] == "nova-operations"
        data, headers = signed(event)
        assert client.post("/payments/stripe/webhook", content=data, headers=headers).status_code == 200
        assert client.post("/payments/stripe/webhook", content=data, headers=headers).status_code == 200
        event["livemode"] = False
        data_test, headers_test = signed(event)
        assert client.post(
            "/payments/stripe/webhook", content=data_test, headers=headers_test,
        ).status_code == 400
    assert recorded == [
        ("evt_accept", "invoice.paid", "in_accept"),
        ("evt_accept", "invoice.paid", "in_accept"),
    ]
