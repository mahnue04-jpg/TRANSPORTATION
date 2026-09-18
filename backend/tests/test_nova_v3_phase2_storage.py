"""Canonical V3 storage on the shared SQLAlchemy/Alembic path. Isolated sqlite is no longer the production model."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.persistence import V3Store
from app.core.nova.v3.schema import (
    REVISION,
    V3_TABLES,
    assert_store_url,
    ensure_v3_schema,
    lazy_v3_schema_allowed,
    rollback_plan,
)


def test_canonical_store_refuses_stripe_and_documents_alembic() -> None:
    assert_store_url("sqlite:///:memory:")
    assert_store_url("postgresql://localhost/amicor")
    with pytest.raises(V3Error):
        assert_store_url("postgresql://user:sk_" + "live_x@stripe.example/db")
    plan = rollback_plan()
    assert REVISION in plan["alembic"]
    assert "20260918_nova_work_revenue_v2_owner_scheduler" in plan["alembic"]
    assert "not applied" in plan["production_apply"]


def test_persist_owner_scoped_entities() -> None:
    kernel = NovaV3Kernel()
    created = kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")["created"][0]
    store = V3Store()
    written = kernel.persist(store)
    assert written >= 1
    rows = store.fetch("nova_v3_opportunities", organization_id="org-a", owner_user_id="owner-a")
    assert rows[0]["opportunity_id"] == created["opportunity_id"]
    assert store.fetch("nova_v3_opportunities", organization_id="org-a", owner_user_id="owner-b") == []
    assert store.count("nova_v3_opportunity_sources") >= 1
    assert store.count("nova_v3_classifications") >= 1
    assert set(V3_TABLES) >= {
        "nova_v3_opportunities",
        "nova_v3_scheduler_jobs",
        "nova_v3_webhooks",
        "nova_v3_connectors",
        "nova_v3_reconciliation",
        "nova_v3_monitoring",
        "nova_v3_leads",
        "nova_v3_shield_decisions",
        "nova_v3_growth_approvals",
    }


def test_injected_database_write_failure_does_not_corrupt_memory() -> None:
    kernel = NovaV3Kernel()
    kernel.ingest("synthetic_job_board", organization_id="org-a", owner_user_id="owner-a")
    kernel.fail_next_persist = True
    with pytest.raises(RuntimeError):
        kernel.persist()
    assert kernel.list_opportunities(organization_id="org-a", owner_user_id="owner-a")
    store = V3Store()
    store.fail_next_write = True
    with pytest.raises(RuntimeError):
        store.upsert(
            "nova_v3_clients",
            {"client_id": "c1", "organization_id": "org-a", "owner_user_id": "owner-a"},
            {"n": 1},
        )


def test_lazy_v3_schema_is_blocked_in_production(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("RUNTIME_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("NOVA_V3_LAZY_SCHEMA", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert lazy_v3_schema_allowed() is False
    engine = create_engine(f"sqlite:///{tmp_path / 'prod-v3.db'}")
    with pytest.raises(V3Error) as err:
        ensure_v3_schema(engine)
    assert err.value.code == "SCHEMA_MIGRATION_REQUIRED"
    assert "nova_v3_opportunities" not in set(inspect(engine).get_table_names())
