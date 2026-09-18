"""V2 migration safety: production does not lazy-create V2 tables. Alembic is canonical."""
from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from app.core.nova.work_revenue.schema_ensure import (
    V2_TABLE_NAMES,
    _EXTRA_COLUMNS,
    ensure_work_revenue_schema,
    lazy_v2_schema_allowed,
)
from app.core.nova.work_revenue.service import NovaWorkError, _ensure_v2


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations" / "versions"


def test_production_does_not_allow_lazy_v2_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("NOVA_WR_LAZY_V2_SCHEMA", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert lazy_v2_schema_allowed() is False


def test_pytest_and_explicit_override_allow_lazy_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_nova_work_revenue_v2_migration.py")
    monkeypatch.delenv("NOVA_WR_LAZY_V2_SCHEMA", raising=False)
    assert lazy_v2_schema_allowed() is True
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("NOVA_WR_LAZY_V2_SCHEMA", "1")
    assert lazy_v2_schema_allowed() is True


def test_audit_extra_columns_are_merged() -> None:
    audit = _EXTRA_COLUMNS["nova_work_audit_events"]
    assert "actor_category" in audit
    assert "idempotency_key" in audit
    assert "approval_ref" in audit


def test_ensure_without_v2_skips_v2_tables(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'wr.db'}")
    ensure_work_revenue_schema(engine, include_v2=False)
    names = set(inspect(engine).get_table_names())
    assert "nova_work_opportunities" in names
    assert "nova_work_revenue_entries" in names
    assert V2_TABLE_NAMES.isdisjoint(names)


def test_ensure_v2_fails_closed_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.core.nova.work_revenue.service.ensure_work_revenue_schema", lambda: None)
    monkeypatch.setattr("app.core.nova.work_revenue.service.v2_schema_ready", lambda: False)
    with pytest.raises(NovaWorkError) as err:
        _ensure_v2()
    assert err.value.status_code == 503
    assert "SCHEMA_MIGRATION_REQUIRED" in str(err.value)


def test_alembic_revisions_are_additive_v2_only() -> None:
    files = [
        MIGRATIONS / "20260918_nova_work_revenue_v2.py",
        MIGRATIONS / "20260918_nova_work_revenue_v2_hardening.py",
        MIGRATIONS / "20260918_nova_work_revenue_v2_owner_scheduler.py",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "def upgrade" in text
        assert "def downgrade" in text
        lowered = text.lower()
        assert 'drop_table("nova_work_opportunities")' not in lowered
        assert "isf_trips" not in lowered
        assert "lifesaver" not in lowered
        assert "stripe_customers" not in lowered
        assert "payment_intents" not in lowered
    combined = "\n".join(path.read_text(encoding="utf-8") for path in files)
    assert "nova_work_historical_corrections" in combined
    assert "owner_user_id" in combined
    docs = (ROOT / "docs" / "NOVA_WORK_REVENUE_V2_MIGRATION.md").read_text(encoding="utf-8")
    assert "Alembic is the only production schema source" in docs
    assert "SCHEMA_MIGRATION_REQUIRED" in docs
    assert "not applied" in docs.lower()
