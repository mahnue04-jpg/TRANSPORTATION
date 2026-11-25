"""Isolated adapter checks: no live network, database, or customer processing."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.core.nova.work_revenue.operations_package_usage_ledger import AllowanceBlocked
from app.core.nova.work_revenue.operations_authenticated_subscription_adapter import (
    reserve_owner_approved_test_subscription_task,
)

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def call(db=None, user=None):
    return reserve_owner_approved_test_subscription_task(
        db or Mock(), authenticated_user=user, organization_id="org_synthetic",
        engagement_id="eng_synthetic", task_id="task_synthetic", lead_id="lead_synthetic",
        request_key="req-synthetic", task_fingerprint="a"*64, now=NOW,
    )


@pytest.fixture
def staging(monkeypatch):
    for name, value in (
        ("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED", "true"),
        ("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED", "true"),
        ("APP_ENV", "staging"),
        ("AMICOR_ENVIRONMENT", "staging"),
        ("NOVA_STRIPE_LIVE_ENABLED", "false"),
        ("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "false"),
    ):
        monkeypatch.setenv(name, value)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED", raising=False)
    db = Mock()
    with pytest.raises(AllowanceBlocked, match="owner_subscription_adapter_disabled"):
        call(db, SimpleNamespace(user_id="owner", organization_id="org_synthetic", role="admin"))
    db.execute.assert_not_called()


@pytest.mark.parametrize("role,organization,user_id", [
    ("staff", "org_synthetic", "owner"),
    ("admin", "wrong_org", "owner"),
    ("admin", "org_synthetic", ""),
    ("", "org_synthetic", "owner"),
])
def test_requires_authenticated_owner_scope(staging, role, organization, user_id):
    db = Mock()
    with pytest.raises(AllowanceBlocked, match="authenticated_owner_required"):
        call(db, SimpleNamespace(user_id=user_id, organization_id=organization, role=role))
    db.execute.assert_not_called()


def test_sales_flag_blocks_even_admin(staging, monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    db = Mock()
    with pytest.raises(AllowanceBlocked, match="owner_subscription_adapter_disabled"):
        call(db, SimpleNamespace(user_id="owner", organization_id="org_synthetic", role="admin"))
    db.execute.assert_not_called()


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
@pytest.mark.parametrize("verified", [False, None])
def test_reversed_or_missing_payment_never_reserves(staging, monkeypatch, plan, verified):
    import sys
    from types import ModuleType
    from sqlalchemy import Table, Column, String, MetaData
    from sqlalchemy.orm import registry
    from app.core.nova.work_revenue import operations_authenticated_subscription_adapter as adapter
    from app.core.nova.work_revenue import operations_subscription_approvals as approval_module

    mapper = registry()
    models = ModuleType("app.core.nova.work_revenue.models")
    for name, fields in (
        ("NovaWorkEngagement", ["engagement_id", "organization_id", "owner_user_id"]),
        ("NovaWorkTask", ["task_id", "engagement_id", "organization_id", "owner_user_id"]),
    ):
        cls = type(name, (), {})
        table = Table(name.lower(), mapper.metadata,
            *(Column(field, String, primary_key=(i == 0)) for i, field in enumerate(fields)))
        mapper.map_imperatively(cls, table)
        setattr(models, name, cls)
    lead_models = ModuleType("app.modules.marketing.models")
    lead_models.MarketingWebsiteLead = type("SyntheticLead", (), {})
    billing = ModuleType("app.modules.marketing.operations_billing")
    stripe = Mock()
    subscription = {"id": "sub_synthetic", "livemode": False}
    stripe.retrieve_subscription.return_value = subscription
    stripe.verify_subscription_payment.return_value = verified
    billing.agent_checkout_mode = lambda: "test"
    billing.get_agent_stripe_client = lambda: stripe
    billing.subscription_test_price = lambda plan: "price_synthetic"
    for module in (models, lead_models, billing):
        monkeypatch.setitem(sys.modules, module.__name__, module)
    monkeypatch.setattr(approval_module, "require_saved_owner_scope_approval", Mock())
    reserve = Mock()
    monkeypatch.setattr(adapter, "reserve_verified_subscription_task", reserve)
    db = Mock()
    db.execute.return_value.scalar_one_or_none.side_effect = [
        SimpleNamespace(), SimpleNamespace(review_required=True)]
    db.get.return_value = SimpleNamespace(id="lead_synthetic",
        lead_type="anonymous_operations", service_plan=plan, payment_status="paid",
        stripe_customer_id="cus_synthetic", stripe_subscription_id="sub_synthetic",
        work_email="buyer@example.invalid")
    user = SimpleNamespace(user_id="owner", organization_id="org_synthetic", role="admin")
    with pytest.raises(AllowanceBlocked, match="subscription_payment_reversed_or_unverified"):
        call(db, user)
    stripe.verify_subscription_payment.assert_called_once_with(
        plan=plan, customer_id="cus_synthetic", subscription=subscription)
    reserve.assert_not_called()
    db.commit.assert_not_called()
