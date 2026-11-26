"""No external service access. Scope approval failures must be closed by default."""
from unittest.mock import Mock

import pytest

from app.core.nova.work_revenue.operations_package_usage_ledger import AllowanceBlocked
from app.core.nova.work_revenue.operations_subscription_approvals import (
    require_saved_owner_scope_approval,
)


def evidence(db=None, **kw):
    values = dict(
        organization_id="org_synthetic", owner_user_id="owner_synthetic",
        engagement_id="eng_synthetic", task_id="task_synthetic",
        lead_id="lead_synthetic", task_fingerprint="a"*64,
    )
    values.update(kw)
    return require_saved_owner_scope_approval(db or Mock(), **values)


def test_approval_disabled_without_flag(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_STAGING_ENABLED", raising=False)
    db = Mock()
    with pytest.raises(AllowanceBlocked, match="subscription_approval_ledger_disabled"):
        evidence(db)
    db.execute.assert_not_called()


def test_live_customer_sales_block_even_with_flag(monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_STAGING_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    with pytest.raises(AllowanceBlocked, match="subscription_approval_ledger_disabled"):
        evidence(db)
    db.execute.assert_not_called()
