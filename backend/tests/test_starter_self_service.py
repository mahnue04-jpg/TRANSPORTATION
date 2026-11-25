"""Synthetic-only tests of the approved $9.99 access policy."""
from datetime import datetime, timedelta, timezone

import pytest

from app.core.nova.billing.starter_self_service import (
    FEATURES, MANAGED_TASKS_INCLUDED, allows_starter_feature,
)
from app.core.nova.work_revenue.operations_package_allowances import (
    VerifiedEntitlement, can_accept_task,
)

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
FLAGS = {
    "APP_ENV": "staging",
    "AMICOR_ENVIRONMENT": "staging",
    "NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED": "true",
    "NOVA_STRIPE_LIVE_ENABLED": "false",
    "NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED": "false",
    "NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID": "price_synthetic_starter",
}
BASE = dict(feature="basic_workspace", tenant_id="synthetic-tenant",
    verified_tenant_id="synthetic-tenant", recorded_plan="starter",
    status="active", recorded_price="price_synthetic_starter",
    verified_subscription=True, verified_paid_invoice=True,
    stripe_livemode=False, current_period_end=NOW+timedelta(days=30), now=NOW)


@pytest.fixture(autouse=True)
def staging(monkeypatch):
    for name, value in FLAGS.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_approved_self_service_features(feature):
    assert allows_starter_feature(**{**BASE, "feature": feature})


@pytest.mark.parametrize("field,value", [
    ("feature", "managed_task"), ("feature", "private_delivery"),
    ("feature", "premium_tools"), ("feature", "unknown"),
    ("tenant_id", ""), ("verified_tenant_id", "other-tenant"),
    ("recorded_plan", "professional"), ("recorded_plan", "starter_49"),
    ("status", "trialing"), ("status", "past_due"), ("status", "canceled"),
    ("status", "unpaid"), ("recorded_price", "price_wrong"),
    ("verified_subscription", False), ("verified_paid_invoice", False),
    ("stripe_livemode", True), ("stripe_livemode", None),
    ("current_period_end", NOW), ("current_period_end", NOW-timedelta(seconds=1)),
    ("current_period_end", NOW.replace(tzinfo=None)),
])
def test_invalid_evidence_denied(field, value):
    assert not allows_starter_feature(**{**BASE, field: value})


@pytest.mark.parametrize("flag,value", [
    ("APP_ENV", "production"), ("AMICOR_ENVIRONMENT", "production"),
    ("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED", "false"),
    ("NOVA_STRIPE_LIVE_ENABLED", "true"),
    ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true"),
    ("NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID", ""),
])
def test_fail_closed_configuration(monkeypatch, flag, value):
    monkeypatch.setenv(flag, value)
    assert not allows_starter_feature(**BASE)
    monkeypatch.delenv(flag)
    assert not allows_starter_feature(**BASE)


@pytest.mark.parametrize("plan", ["starter", "starter_999"])
def test_starter_has_no_managed_task_allowance(plan):
    assert MANAGED_TASKS_INCLUDED == 0
    entitlement = VerifiedEntitlement(plan=plan, customer_id="cus_synthetic",
        paid=True, status="active", subscription_id="sub_synthetic",
        period_start=NOW-timedelta(days=1), period_end=NOW+timedelta(days=29))
    allowed, _ = can_accept_task(entitlement, customer_id="cus_synthetic",
        now=NOW, accepted_unique_tasks=frozenset(), request_key="synthetic")
    assert not allowed
