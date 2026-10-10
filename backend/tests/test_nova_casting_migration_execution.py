"""Exercise draft casting migration and tenant isolation on disposable databases."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

MIGRATION = Path(__file__).resolve().parents[1] / "migrations/versions/20261010_casting_org_draft.py"


@pytest.mark.parametrize("url", ["sqlite:///:memory:", pytest.param(
    os.getenv("CASTING_TEST_POSTGRES_URL", ""),
    marks=pytest.mark.skipif(not os.getenv("CASTING_TEST_POSTGRES_URL"), reason="PostgreSQL CI service not configured"),
)])
def test_draft_migration_upgrade_rejects_cross_tenant_and_downgrades(url):
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO platform_users (id) VALUES ('user1'), ('user2')")
        spec = importlib.util.spec_from_file_location("_casting_migration_under_test", MIGRATION)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        operations = Operations(MigrationContext.configure(conn))
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
            meta = sa.MetaData()
            meta.reflect(bind=conn)
            org = meta.tables["nova_casting_organizations"]
            membership = meta.tables["nova_casting_memberships"]
            conn.execute(org.insert().values(id="org1", nova_tenant_id="tenant1", name="Demo", created_at="today"))
            conn.execute(membership.insert().values(id="member1", nova_tenant_id="tenant1",
                organization_id="org1", user_id="user1", casting_role="reviewer", created_at="today"))
            row = conn.execute(sa.select(membership.c.active)).scalar_one()
            assert row is False or row == 0
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(membership.insert().values(id="member2", nova_tenant_id="tenant2",
                        organization_id="org1", user_id="user2", casting_role="reviewer", created_at="today"))
            migration.downgrade()
            tables = sa.inspect(conn).get_table_names()
            assert "nova_casting_memberships" not in tables
            assert "nova_casting_organizations" not in tables
            assert "platform_users" in tables
        finally:
            migration.op = original_op
    engine.dispose()
