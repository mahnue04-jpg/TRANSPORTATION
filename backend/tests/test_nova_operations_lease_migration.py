"""Gated lease Alembic migration tests using disposable PostgreSQL only."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import os
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.nova.work_revenue import operations_postgres_leases as leases


@pytest.fixture
def migration():
    path = (Path(__file__).resolve().parents[1] / "migrations" / "versions"
            / "20261117_nova_operations_leases.py")
    spec = spec_from_file_location("nova_ops_lease_migration_ci", path)
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_rejects_unapproved_staging(monkeypatch, migration):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.delenv("AMICOR_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", raising=False)
    with pytest.raises(RuntimeError, match="approval"):
        migration.upgrade()


def test_migration_rejects_conflicting_environments(monkeypatch, migration):
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "staging-only")
    with pytest.raises(RuntimeError, match="approval"):
        migration.upgrade()


def test_production_migration_refuses_to_mark_revision_applied(monkeypatch, migration):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("AMICOR_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "staging-only")

    class FailIfAccessed:
        def get_bind(self):
            raise AssertionError("Production upgrade must not access database DDL")

    monkeypatch.setattr(migration, "op", FailIfAccessed())
    with pytest.raises(RuntimeError, match="staging-only"):
        migration.upgrade()


def test_migration_creates_matching_schema_only_in_isolated_staging(monkeypatch, migration):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("CI requires disposable loopback PostgreSQL")
        pytest.skip("Disposable loopback PostgreSQL required")
    engine = sa.create_engine(url)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "staging-only")
    with engine.connect() as lookup:
        actual_db = lookup.execute(sa.text("SELECT current_database()")).scalar_one()
    monkeypatch.setenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE", actual_db)
    try:
        with engine.begin() as conn:
            context = MigrationContext.configure(conn)
            monkeypatch.setattr(migration, "op", Operations(context))
            migration.upgrade()
        inspector = sa.inspect(engine)
        assert leases.lease_jobs.name in inspector.get_table_names()
        cols = {c["name"] for c in inspector.get_columns(leases.lease_jobs.name)}
        assert set(leases.lease_jobs.columns.keys()) == cols
        constraints = {
            c["name"] for c in inspector.get_check_constraints(leases.lease_jobs.name)
        }
        assert "ck_nova_operations_lease_input_binding" in constraints
        assert "ck_nova_operations_lease_state" in constraints
        assert "ix_nova_operations_lease_ready" in {
            i["name"] for i in inspector.get_indexes(leases.lease_jobs.name)
        }
        # Disposable metadata and the reviewed migration must enforce the
        # same private-input binding constraint.
        expected_checks = {
            c.name for c in leases.lease_jobs.constraints
            if isinstance(c, sa.CheckConstraint)
        }
        assert expected_checks.issubset(constraints)
    finally:
        leases.lease_metadata.drop_all(engine)
        engine.dispose()


def test_staging_migration_rejects_missing_or_wrong_database_identity(
    monkeypatch, migration,
):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("CI requires disposable loopback PostgreSQL")
        pytest.skip("Disposable loopback PostgreSQL required")
    engine = sa.create_engine(url)
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "staging-only")
    try:
        with engine.begin() as conn:
            context = MigrationContext.configure(conn)
            monkeypatch.setattr(migration, "op", Operations(context))
            monkeypatch.delenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE", raising=False)
            with pytest.raises(RuntimeError, match="database name required"):
                migration.upgrade()
            monkeypatch.setenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE", "wrong_staging_database")
            with pytest.raises(RuntimeError, match="does not match staging approval"):
                migration.upgrade()
        assert leases.lease_jobs.name not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_no_environment_migration_must_fail_instead_of_no_op(monkeypatch, migration):
    for key in ("APP_ENV", "AMICOR_ENVIRONMENT", "ENVIRONMENT"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "staging-only")
    with pytest.raises(RuntimeError, match="staging-only"):
        migration.upgrade()


def test_downgrade_refuses_silent_alembic_version_change(monkeypatch, migration):
    with pytest.raises(RuntimeError, match="separate owner approval"):
        migration.downgrade()
