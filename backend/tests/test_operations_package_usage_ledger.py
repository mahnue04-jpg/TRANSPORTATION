"""No external Stripe or PostgreSQL connection. Fail-closed tests only."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.core.nova.work_revenue.operations_package_allowances import VerifiedEntitlement
from app.core.nova.work_revenue.operations_package_usage_ledger import (
    AllowanceBlocked, _identity, require_staging, reserve_staging_task,
)

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def entitlement(plan="launch_99", **overrides):
    fields = dict(
        plan=plan, customer_id="cus_synthetic", paid=True, status="active",
        subscription_id="sub_synthetic", period_start=NOW-timedelta(days=1),
        period_end=NOW+timedelta(days=29), payment_id="pi_synthetic",
    )
    fields.update(overrides)
    return VerifiedEntitlement(**fields)


def test_period_scoped_to_verified_start():
    assert _identity(entitlement()) == (
        "sub_synthetic", (NOW-timedelta(days=1)).isoformat()
    )


def test_starter_payment_scoped_to_one_time_key():
    assert _identity(entitlement("starter_49")) == ("pi_synthetic", "one_time")


@pytest.mark.parametrize("e", [
    entitlement("launch_99", subscription_id=None),
    entitlement("launch_99", period_start=None),
    entitlement("launch_99", period_start=datetime(2026, 11, 23)),
    entitlement("starter_49", payment_id=None),
])
def test_missing_identity_blocks(e):
    with pytest.raises(AllowanceBlocked):
        _identity(e)


def test_feature_disabled_fails_closed(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED", raising=False)
    db = Mock()
    with pytest.raises(AllowanceBlocked, match="staging_postgres_only"):
        require_staging(db)


def test_live_sales_setting_blocks_even_if_feature_requested(monkeypatch):
    monkeypatch.setenv("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED", "true")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "true")
    monkeypatch.setenv("NOVA_STRIPE_LIVE_ENABLED", "false")
    db = Mock()
    db.get_bind.return_value.dialect.name = "postgresql"
    with pytest.raises(AllowanceBlocked, match="staging_postgres_only"):
        require_staging(db)


def test_reservation_without_enabled_staging_never_writes(monkeypatch):
    monkeypatch.delenv("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED", raising=False)
    db = Mock()
    with pytest.raises(AllowanceBlocked):
        reserve_staging_task(
            db, entitlement=entitlement(), customer_id="cus_synthetic",
            request_key="task-one", task_fingerprint="a"*64, now=NOW,
        )
    db.execute.assert_not_called()
