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
