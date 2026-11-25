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


from types import SimpleNamespace
from app.core.nova.billing.starter_subscription_evidence import verify_starter_feature


def evidence():
    start = int((NOW-timedelta(days=1)).timestamp())
    end = int((NOW+timedelta(days=29)).timestamp())
    row = SimpleNamespace(tenant_id="synthetic-tenant", plan_key="starter",
        subscription_status="active", stripe_customer_id="cus_synthetic",
        stripe_subscription_id="sub_synthetic", stripe_price_id="price_synthetic_starter")
    sub = dict(id="sub_synthetic", customer="cus_synthetic", livemode=False,
        status="active", metadata=dict(nova_product="nova_saas",
            nova_tenant_id=row.tenant_id, nova_plan_key="starter"),
        items=dict(has_more=False, data=[dict(quantity=1,
            current_period_start=start, current_period_end=end,
            price=dict(id=row.stripe_price_id, livemode=False, unit_amount=999,
                currency="usd", recurring=dict(interval="month", interval_count=1)))]),
        latest_invoice=dict(livemode=False, status="paid", currency="usd",
            amount_paid=999, customer=row.stripe_customer_id,
            parent=dict(type="subscription_details", subscription_details=dict(
                subscription=row.stripe_subscription_id)),
            lines=dict(has_more=False, data=[dict(
                parent=dict(type="subscription_item_details",
                    subscription_item_details=dict(proration=False, subscription=row.stripe_subscription_id)),
                period=dict(start=start, end=end))])))
    return row, sub


def check(row, sub, feature="basic_workspace"):
    return verify_starter_feature(feature=feature, tenant_id="synthetic-tenant",
        row=row, subscription=sub, now=NOW)


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_exact_subscription_evidence(feature):
    row, sub = evidence()
    assert check(row, sub, feature)


@pytest.mark.parametrize("path,value", [
    (("id",), "sub_wrong"), (("customer",), "cus_wrong"),
    (("livemode",), True), (("status",), "canceled"),
    (("metadata", "nova_tenant_id"), "other-tenant"),
    (("metadata", "nova_product"), "other-product"),
    (("metadata", "nova_plan_key"), "business"),
    (("items", "has_more"), True),
    (("items", "data", 0, "quantity"), 2),
    (("items", "data", 0, "price", "id"), "price_wrong"),
    (("items", "data", 0, "price", "unit_amount"), 9900),
    (("items", "data", 0, "price", "currency"), "eur"),
    (("items", "data", 0, "price", "livemode"), True),
    (("items", "data", 0, "price", "recurring", "interval"), "year"),
    (("items", "data", 0, "current_period_end"), int(NOW.timestamp())),
    (("latest_invoice", "status"), "open"),
    (("latest_invoice", "amount_paid"), 0),
    (("latest_invoice", "livemode"), True),
    (("latest_invoice", "customer"), "cus_wrong"),
    (("latest_invoice", "parent", "subscription_details", "subscription"), "sub_wrong"),
    (("latest_invoice", "lines", "has_more"), True),
    (("latest_invoice", "lines", "data", 0, "period", "end"), 0),
    (("latest_invoice", "lines", "data", 0, "parent", "subscription_item_details", "proration"), True),
])
def test_subscription_evidence_mismatch(path, value):
    row, sub = evidence()
    target = sub
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not check(row, sub)


@pytest.mark.parametrize("field,value", [
    ("tenant_id", "other-tenant"), ("subscription_status", "past_due"),
    ("plan_key", "business"), ("stripe_customer_id", None),
    ("stripe_subscription_id", None), ("stripe_price_id", "price_wrong"),
])
def test_record_binding_mismatch(field, value):
    row, sub = evidence()
    setattr(row, field, value)
    assert not check(row, sub)


def test_missing_invoice_fails_closed():
    row, sub = evidence()
    del sub["latest_invoice"]
    assert not check(row, sub)
    row, sub = evidence()
    assert not check(row, sub, "managed_task")


import sys
from types import ModuleType
from app.core.nova.billing.starter_authenticated_access import authenticated_starter_access
from app.core.nova.billing import starter_authenticated_access as adapter


@pytest.fixture
def adapter_fixture(monkeypatch):
    row, sub = evidence()
    user = SimpleNamespace(organization_id=row.tenant_id,
        user_id="synthetic-user", email="starter@example.invalid")
    state = SimpleNamespace(row=row, subscription=sub, key="sk_test_fixture",
        queries=0, reads=0, fail=False)
    from sqlalchemy import Table, Column, String, MetaData
    table = Table("synthetic_subscription", MetaData(), Column("tenant_id", String))
    models = ModuleType("app.core.nova.billing.models")
    models.NovaTenantSubscription = table
    signup_client = ModuleType("app.core.nova.signup.stripe_client")
    signup_client.stripe_secret_key = lambda: state.key
    billing_client = ModuleType("app.core.nova.billing.stripe_client")

    def retrieve(sub_id, params):
        state.reads += 1
        assert sub_id == row.stripe_subscription_id
        assert params == {"expand": ["latest_invoice"]}
        if state.fail:
            raise RuntimeError("synthetic provider failure")
        return state.subscription

    billing_client.LiveNovaBillingStripeClient = lambda api_key: SimpleNamespace(
        _build_client=lambda: SimpleNamespace(v1=SimpleNamespace(
            subscriptions=SimpleNamespace(retrieve=retrieve))))
    for module in (models, signup_client, billing_client):
        monkeypatch.setitem(sys.modules, module.__name__, module)

    def execute(statement):
        state.queries += 1
        assert statement.compile().params == {"tenant_id_1": user.organization_id}
        return SimpleNamespace(scalar_one_or_none=lambda: state.row)

    db = SimpleNamespace(execute=execute)
    monkeypatch.setattr(adapter, "datetime", SimpleNamespace(now=lambda tz: NOW))
    return db, user, state


@pytest.mark.parametrize("feature", sorted(FEATURES))
def test_authenticated_adapter_valid(adapter_fixture, feature):
    db, user, state = adapter_fixture
    assert authenticated_starter_access(db, authenticated_user=user, feature=feature)
    assert state.queries == 1 and state.reads == 1


@pytest.mark.parametrize("field,value", [
    ("organization_id", ""), ("user_id", ""), ("email", "customer@example.com"),
])
def test_authenticated_adapter_invalid_identity(adapter_fixture, field, value):
    db, user, state = adapter_fixture
    setattr(user, field, value)
    assert not authenticated_starter_access(db, authenticated_user=user, feature="basic_workspace")
    assert state.queries == 0 and state.reads == 0


@pytest.mark.parametrize("failure", ["missing_row", "wrong_tenant", "wrong_plan",
    "live_key", "missing_key", "provider_failure", "canceled", "unpaid",
    "managed_task", "disabled"])
def test_authenticated_adapter_failures(adapter_fixture, monkeypatch, failure):
    db, user, state = adapter_fixture
    feature = "basic_workspace"
    if failure == "missing_row":
        state.row = None
    elif failure == "wrong_tenant":
        state.row.tenant_id = "other-tenant"
    elif failure == "wrong_plan":
        state.row.plan_key = "business"
    elif failure == "live_key":
        state.key = "sk_live_fixture"
    elif failure == "missing_key":
        state.key = ""
    elif failure == "provider_failure":
        state.fail = True
    elif failure == "canceled":
        state.subscription["status"] = "canceled"
    elif failure == "unpaid":
        state.subscription["latest_invoice"]["status"] = "open"
    elif failure == "managed_task":
        feature = "managed_task"
    elif failure == "disabled":
        monkeypatch.setenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED", "false")
    assert not authenticated_starter_access(db, authenticated_user=user, feature=feature)
    if failure in {"missing_row", "wrong_plan", "live_key", "missing_key",
                   "managed_task", "disabled"}:
        assert state.reads == 0
