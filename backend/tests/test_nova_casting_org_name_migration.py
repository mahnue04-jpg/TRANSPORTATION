"""Disposable checks for the sandbox organization name constraint.

No production database. Rows are never deleted to make the constraint fit.
"""
import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
ORG_DRAFT = VERSIONS / "20261010_casting_org_draft.py"
CONTENT_DRAFT = VERSIONS / "20261010_casting_content_draft.py"
AUDIT_DRAFT = VERSIONS / "20261010_casting_audit_consent_draft.py"
REPAIR = VERSIONS / "20261011_casting_schema_repair.py"
NAME_UNIQUE = VERSIONS / "20261012_casting_org_name_unique.py"


def _load(path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bind(connection, module):
    module.op = Operations(MigrationContext.configure(connection))


def _names(connection):
    found = sa.inspect(connection).get_unique_constraints("nova_casting_organizations")
    return {item.get("name") for item in found}


def _count(connection):
    return connection.execute(sa.text("SELECT COUNT(*) FROM nova_casting_organizations")).scalar_one()


def test_duplicate_names_abort_without_deleting_rows():
    engine = sa.create_engine("sqlite://")
    draft = _load(ORG_DRAFT, "_casting_org_draft_for_duplicates")
    revision = _load(NAME_UNIQUE, "_casting_org_name_for_duplicates")
    with engine.begin() as connection:
        _bind(connection, draft)
        draft.upgrade()
        connection.execute(sa.text(
            "INSERT INTO nova_casting_organizations "
            "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
            "('org-a', 'tenant-a', 'North Studio', 'VERIFIED', 't1'), "
            "('org-b', 'tenant-a', 'North Studio', 'VERIFIED', 't2')"
        ))
        _bind(connection, revision)
        with pytest.raises(RuntimeError, match="does not delete or merge rows"):
            revision.upgrade()
        assert "uq_nova_casting_org_tenant_name" not in _names(connection)
        assert _count(connection) == 2
    engine.dispose()


def test_clean_table_gains_a_constraint_and_downgrade_keeps_rows():
    engine = sa.create_engine("sqlite://")
    draft = _load(ORG_DRAFT, "_casting_org_draft_for_clean")
    revision = _load(NAME_UNIQUE, "_casting_org_name_for_clean")
    with engine.begin() as connection:
        _bind(connection, draft)
        draft.upgrade()
        connection.execute(sa.text(
            "INSERT INTO nova_casting_organizations "
            "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
            "('org-a', 'tenant-a', 'North Studio', 'VERIFIED', 't1')"
        ))
        _bind(connection, revision)
        revision.upgrade()
        assert "uq_nova_casting_org_tenant_name" in _names(connection)
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                connection.execute(sa.text(
                    "INSERT INTO nova_casting_organizations "
                    "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
                    "('org-b', 'tenant-a', 'North Studio', 'VERIFIED', 't2')"
                ))
        connection.execute(sa.text(
            "INSERT INTO nova_casting_organizations "
            "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
            "('org-c', 'tenant-b', 'North Studio', 'VERIFIED', 't3')"
        ))
        assert _count(connection) == 2
        revision.downgrade()
        assert "uq_nova_casting_org_tenant_name" not in _names(connection)
        assert _count(connection) == 2
        connection.execute(sa.text(
            "INSERT INTO nova_casting_organizations "
            "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
            "('org-d', 'tenant-a', 'North Studio', 'VERIFIED', 't4')"
        ))
        assert _count(connection) == 3
    engine.dispose()


def test_missing_table_and_production_do_not_change_rows(monkeypatch):
    engine = sa.create_engine("sqlite://")
    revision = _load(NAME_UNIQUE, "_casting_org_name_for_absent")
    with engine.begin() as connection:
        _bind(connection, revision)
        revision.upgrade()
        revision.downgrade()
        assert "nova_casting_organizations" not in sa.inspect(connection).get_table_names()
    engine.dispose()

    draft = _load(ORG_DRAFT, "_casting_org_draft_before_lock")
    locked = _load(NAME_UNIQUE, "_casting_org_name_locked")
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        _bind(connection, draft)
        draft.upgrade()
        connection.execute(sa.text(
            "INSERT INTO nova_casting_organizations "
            "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
            "('org-a', 'tenant-a', 'North Studio', 'VERIFIED', 't1'), "
            "('org-b', 'tenant-a', 'North Studio', 'VERIFIED', 't2')"
        ))
        assert _count(connection) == 2
        monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
        monkeypatch.setenv("APP_ENV", "production")
        _bind(connection, locked)
        locked.upgrade()
        locked.downgrade()
        assert "uq_nova_casting_org_tenant_name" not in _names(connection)
        assert _count(connection) == 2
    engine.dispose()


def _disposable(monkeypatch):
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, "disposable")


@contextmanager
def _postgres_schema(schema):
    """Isolated schema with the platform_users parent the older drafts reference."""
    engine = sa.create_engine(os.environ["CASTING_TEST_POSTGRES_URL"])
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
            connection.exec_driver_sql(f"SET search_path TO {schema}")
            connection.exec_driver_sql(
                "CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)"
            )
            yield connection
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        engine.dispose()


def _insert_org(connection, org_id, tenant_id, name):
    connection.execute(sa.text(
        "INSERT INTO nova_casting_organizations "
        "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
        "(:org_id, :tenant_id, :name, 'VERIFIED', 't1')"
    ), {"org_id": org_id, "tenant_id": tenant_id, "name": name})


@pytest.mark.skipif(
    not os.getenv("CASTING_TEST_POSTGRES_URL"),
    reason="Disposable PostgreSQL not configured",
)
def test_postgres_duplicate_names_abort_without_deleting_rows(monkeypatch):
    _disposable(monkeypatch)
    draft = _load(ORG_DRAFT, "_casting_org_draft_pg_duplicates")
    revision = _load(NAME_UNIQUE, "_casting_org_name_pg_duplicates")
    with _postgres_schema("casting_org_name_ci") as connection:
        assert "platform_users" in sa.inspect(connection).get_table_names()
        _bind(connection, draft)
        draft.upgrade()
        connection.execute(sa.text(
            "INSERT INTO nova_casting_organizations "
            "(id, nova_tenant_id, name, verification_status, created_at) VALUES "
            "('org-a', 'tenant-a', 'North Studio', 'VERIFIED', 't1'), "
            "('org-b', 'tenant-a', 'North Studio', 'VERIFIED', 't2')"
        ))
        _bind(connection, revision)
        with pytest.raises(RuntimeError, match="does not delete or merge rows"):
            revision.upgrade()
        assert "uq_nova_casting_org_tenant_name" not in _names(connection)
        assert _count(connection) == 2


@pytest.mark.skipif(
    not os.getenv("CASTING_TEST_POSTGRES_URL"),
    reason="Disposable PostgreSQL not configured",
)
def test_postgres_clean_upgrade_from_older_org_draft_keeps_rows(monkeypatch):
    _disposable(monkeypatch)
    draft = _load(ORG_DRAFT, "_casting_org_draft_pg_clean")
    revision = _load(NAME_UNIQUE, "_casting_org_name_pg_clean")
    with _postgres_schema("casting_org_name_clean_ci") as connection:
        _bind(connection, draft)
        draft.upgrade()
        _insert_org(connection, "org-a", "tenant-a", "North Studio")
        assert _count(connection) == 1
        _bind(connection, revision)
        revision.upgrade()
        assert "uq_nova_casting_org_tenant_name" in _names(connection)
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                _insert_org(connection, "org-b", "tenant-a", "North Studio")
        _insert_org(connection, "org-c", "tenant-b", "North Studio")
        assert _count(connection) == 2
        revision.downgrade()
        assert "uq_nova_casting_org_tenant_name" not in _names(connection)
        assert _count(connection) == 2
        _insert_org(connection, "org-d", "tenant-a", "North Studio")
        assert _count(connection) == 3


@pytest.mark.skipif(
    not os.getenv("CASTING_TEST_POSTGRES_URL"),
    reason="Disposable PostgreSQL not configured",
)
def test_postgres_older_casting_migrations_then_name_constraint_keeps_rows(monkeypatch):
    """A disposable database that already ran the older casting revisions keeps its rows."""
    _disposable(monkeypatch)
    older = [
        _load(ORG_DRAFT, "_casting_org_history_org"),
        _load(CONTENT_DRAFT, "_casting_org_history_content"),
        _load(AUDIT_DRAFT, "_casting_org_history_audit"),
        _load(REPAIR, "_casting_org_history_repair"),
    ]
    revision = _load(NAME_UNIQUE, "_casting_org_history_name")
    with _postgres_schema("casting_org_name_history_ci") as connection:
        for module in older:
            _bind(connection, module)
            module.upgrade()
        names = set(sa.inspect(connection).get_table_names())
        assert "platform_users" in names
        assert "nova_casting_organizations" in names
        assert "nova_casting_campaigns" in names
        assert "nova_casting_audit_events" in names
        _insert_org(connection, "org-a", "tenant-a", "North Studio")
        assert _count(connection) == 1
        _bind(connection, revision)
        revision.upgrade()
        assert "uq_nova_casting_org_tenant_name" in _names(connection)
        assert _count(connection) == 1
        with pytest.raises(sa.exc.IntegrityError):
            with connection.begin_nested():
                _insert_org(connection, "org-b", "tenant-a", "North Studio")
        assert _count(connection) == 1
        revision.downgrade()
        assert "uq_nova_casting_org_tenant_name" not in _names(connection)
        assert _count(connection) == 1
