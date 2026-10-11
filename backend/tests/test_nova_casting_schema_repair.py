"""Forward-only repair after a production stamp that skipped casting DDL."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

REPAIR = Path(__file__).resolve().parents[1] / "migrations/versions/20261011_casting_schema_repair.py"
ORG = Path(__file__).resolve().parents[1] / "migrations/versions/20261010_casting_org_draft.py"
CONTENT = Path(__file__).resolve().parents[1] / "migrations/versions/20261010_casting_content_draft.py"
AUDIT = Path(__file__).resolve().parents[1] / "migrations/versions/20261010_casting_audit_consent_draft.py"
TABLES = (
    "nova_casting_organizations",
    "nova_casting_memberships",
    "nova_casting_campaigns",
    "nova_casting_applications",
    "nova_casting_reviews",
    "nova_casting_media",
    "nova_casting_consent_events",
    "nova_casting_audit_events",
)


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(connection, module):
    operations = Operations(MigrationContext.configure(connection))
    original = module.op
    module.op = operations
    try:
        module.upgrade()
    finally:
        module.op = original


def _downgrade(connection, module):
    operations = Operations(MigrationContext.configure(connection))
    original = module.op
    module.op = operations
    try:
        module.downgrade()
    finally:
        module.op = original


def test_repair_revision_is_forward_only_and_follows_audit():
    source = REPAIR.read_text(encoding="utf-8")
    assert 'revision = "20261011_casting_schema_repair"' in source
    assert 'down_revision = "20261010_casting_audit_consent"' in source
    assert "op.drop_table" not in source
    assert "_production_schema_locked" in source


def test_production_repair_creates_nothing(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("APP_ENV", "production")
    engine = sa.create_engine("sqlite:///:memory:")
    repair = _load(REPAIR, "_casting_repair_production")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)")
        _run(conn, repair)
        names = set(sa.inspect(conn).get_table_names())
        assert not any(name.startswith("nova_casting_") for name in names)
    engine.dispose()


@pytest.mark.parametrize("url", ["sqlite:///:memory:", pytest.param(
    os.getenv("CASTING_TEST_POSTGRES_URL", ""),
    marks=pytest.mark.skipif(
        not os.getenv("CASTING_TEST_POSTGRES_URL"),
        reason="PostgreSQL CI service not configured",
    ),
)])
def test_skipped_ddl_is_repaired_idempotently_and_downgrade_keeps_tables(url, monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    engine = sa.create_engine(url)
    schema = None
    if engine.dialect.name == "postgresql":
        schema = "casting_repair_ci"
        with engine.begin() as admin:
            admin.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            admin.exec_driver_sql(f"CREATE SCHEMA {schema}")
        engine.dispose()
        engine = sa.create_engine(url, connect_args={"options": f"-csearch_path={schema}"})
    org = _load(ORG, "_casting_repair_org")
    content = _load(CONTENT, "_casting_repair_content")
    audit = _load(AUDIT, "_casting_repair_audit")
    repair = _load(REPAIR, "_casting_repair_forward")
    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO platform_users (id) VALUES ('user1')")
        _run(conn, org)
        _run(conn, content)
        _run(conn, audit)
        assert not any(name.startswith("nova_casting_") for name in sa.inspect(conn).get_table_names())
        monkeypatch.setenv("AMICOR_ENVIRONMENT", "disposable")
        _run(conn, repair)
        _run(conn, repair)
        names = set(sa.inspect(conn).get_table_names())
        assert set(TABLES) <= names
        meta = sa.MetaData()
        meta.reflect(bind=conn)
        org_table = meta.tables["nova_casting_organizations"]
        campaign_table = meta.tables["nova_casting_campaigns"]
        conn.execute(org_table.insert().values(
            id="org1", nova_tenant_id="tenant1", name="Demo", created_at="today",
        ))
        with pytest.raises(sa.exc.IntegrityError):
            with conn.begin_nested():
                conn.execute(campaign_table.insert().values(
                    id="camp1", owner_id="org1", title="Nope", category="film",
                    status="OPEN", minimum_age=18, created_at="today",
                ))
        _downgrade(conn, repair)
        assert set(TABLES) <= set(sa.inspect(conn).get_table_names())
    engine.dispose()
    if schema and os.getenv("CASTING_TEST_POSTGRES_URL"):
        admin_engine = sa.create_engine(os.environ["CASTING_TEST_POSTGRES_URL"])
        with admin_engine.begin() as admin:
            admin.exec_driver_sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        admin_engine.dispose()
