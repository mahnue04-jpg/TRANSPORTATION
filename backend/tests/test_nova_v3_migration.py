"""Canonical V3 Alembic: additive, reversible, chained after V2 owner-scheduler head. Not applied to production."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from app.core.nova.v3.schema import DOWN_REVISION, REVISION, V3_TABLES, lazy_v3_schema_allowed


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "versions" / "20260918_nova_v3_live_infrastructure.py"


def test_v3_revision_chains_canonical_v2_head() -> None:
    text_body = MIGRATION.read_text(encoding="utf-8")
    assert f'revision = "{REVISION}"' in text_body
    assert f'down_revision = "{DOWN_REVISION}"' in text_body
    assert "def upgrade" in text_body
    assert "def downgrade" in text_body
    lowered = text_body.lower()
    assert 'drop_table("nova_work_opportunities")' not in lowered
    assert "isf_trips" not in lowered
    assert "lifesaver" not in lowered
    assert "stripe_customers" not in lowered
    assert "payment_intents" not in lowered
    for table in V3_TABLES:
        assert table in text_body
    assert "organization_id" in text_body
    assert "owner_user_id" in text_body
    assert "ix_nova_v3_job_period" in text_body
    assert "ix_nova_v3_lead_org_fp" in text_body


def test_production_does_not_allow_lazy_v3_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("NOVA_V3_LAZY_SCHEMA", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert lazy_v3_schema_allowed() is False


def _load_revision():
    spec = importlib.util.spec_from_file_location("nova_v3_live_infrastructure", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_upgrade_and_downgrade_only(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'v3-mig.db'}")
    module = _load_revision()
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        module.op = Operations(context)
        module.upgrade()
    names = set(inspect(engine).get_table_names())
    assert set(V3_TABLES).issubset(names)
    assert "nova_work_opportunities" not in names
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        module.op = Operations(context)
        module.downgrade()
    after = set(inspect(engine).get_table_names())
    assert set(V3_TABLES).isdisjoint(after)
