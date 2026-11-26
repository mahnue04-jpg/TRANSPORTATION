"""Staging bridge tests: no real Stripe, no hosted database, no fulfillment."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from app.core.nova.work_revenue.operations_package_usage_ledger import AllowanceBlocked
from app.core.nova.work_revenue.operations_subscription_task_bridge import (
    reserve_verified_subscription_task,
)

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def subscription(plan="launch_99", status="active"):
    start, end = NOW-timedelta(days=1), NOW+timedelta(days=29)
    return {
        "id": "sub_synthetic", "livemode": False, "customer": "cus_synthetic",
        "status": status,
        "metadata": {"nova_product": "nova_anonymous_operations_agent",
                     "nova_agent_lead_id": "lead_synthetic", "nova_agent_plan": plan},
        "items": {"data": [{"quantity": 1, "price": "price_synthetic",
                            "current_period_start": int(start.timestamp()),
                            "current_period_end": int(end.timestamp())}]},
        "latest_invoice": {
            "status": "paid", "paid": True, "currency": "usd",
            "amount_paid": {"launch_99": 9900, "business_299": 29900}[plan],
            "customer": "cus_synthetic", "subscription": "sub_synthetic",
            "lines": {"data": [{"subscription": "sub_synthetic",
                               "period": {"start": int(start.timestamp()), "end": int(end.timestamp())}}]},
        },
    }


def reserve(db, *, plan="launch_99", owner_scope_approved=True, data=None, **kw):
    p = dict(
        owner_scope_approved=owner_scope_approved, plan=plan,
        lead_id="lead_synthetic", saved_customer_id="cus_synthetic",
        saved_subscription_id="sub_synthetic", saved_payment_status="paid",
        test_price_id="price_synthetic",
        retrieved_test_subscription=data if data is not None else subscription(plan),
        request_key="synthetic-request", task_fingerprint="a"*64, now=NOW,
    )
    p.update(kw)
    return reserve_verified_subscription_task(db, **p)


@pytest.fixture
def staging(monkeypatch):
    for key, value in (
        ("APP_ENV", "staging"), ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
        ("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED", "true"),
    ):
        monkeypatch.setenv(key, value)


def test_bridge_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED", raising=False)
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        with pytest.raises(AllowanceBlocked, match="subscription_bridge_disabled"):
            reserve(Mock())
        write.assert_not_called()


def test_owner_must_approve(staging):
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        with pytest.raises(AllowanceBlocked, match="owner_scope_approval_required"):
            reserve(Mock(), owner_scope_approved=False)
        write.assert_not_called()


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_paid_verified_subscription_forwarded_to_ledger(staging, plan):
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        write.return_value = {"reservation_id": "synthetic", "consumed": True, "replayed": False}
        result = reserve(Mock(), plan=plan)
        assert result["consumed"]
        e = write.call_args.kwargs["entitlement"]
        assert e.plan == plan and e.paid and e.customer_id == "cus_synthetic"


@pytest.mark.parametrize("change", [
    {"saved_payment_status": "failed"},
    {"saved_customer_id": "cus_other"},
    {"saved_subscription_id": "sub_other"},
])
def test_mismatched_saved_state_cannot_reserve(staging, change):
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        with pytest.raises(ValueError):
            reserve(Mock(), **change)
        write.assert_not_called()


def test_canceled_subscription_cannot_reserve(staging):
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        with pytest.raises(ValueError):
            reserve(Mock(), data=subscription(status="canceled"))
        write.assert_not_called()


def test_live_sales_setting_blocks_bridge(staging, monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        with pytest.raises(AllowanceBlocked):
            reserve(Mock())
        write.assert_not_called()


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_strict_hosted_bridge_denies_legacy_invoice(staging, monkeypatch, plan):
    monkeypatch.setenv("NOVA_OPERATIONS_STRICT_INVOICE_STAGING", "true")
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        with pytest.raises(ValueError, match="current_invoice_required"):
            reserve(Mock(), plan=plan)
        write.assert_not_called()


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_strict_hosted_bridge_accepts_bound_current_invoice(staging, monkeypatch, plan):
    monkeypatch.setenv("NOVA_OPERATIONS_STRICT_INVOICE_STAGING", "true")
    data = subscription(plan)
    data["items"]["data"][0]["id"] = "si_synthetic"
    invoice = data["latest_invoice"]
    invoice["livemode"] = False
    invoice["parent"] = {"type": "subscription_details", "subscription_details": {"subscription": invoice.pop("subscription")}}
    invoice["lines"]["has_more"] = False
    line = invoice["lines"]["data"][0]
    line["parent"] = {"type": "subscription_item_details", "subscription_item_details": {"subscription": line.pop("subscription"), "subscription_item": "si_synthetic", "proration": False}}
    line["pricing"] = {"type": "price_details", "price_details": {"price": "price_synthetic"}}
    line["quantity"] = 1
    with patch("app.core.nova.work_revenue.operations_subscription_task_bridge.reserve_staging_task") as write:
        write.return_value = {"consumed": True}
        assert reserve(Mock(), plan=plan, data=data)["consumed"]
        write.assert_called_once()
