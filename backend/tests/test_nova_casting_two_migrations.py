"""Run both inactive casting revisions on disposable database and roll back."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
POSTGRES = os.getenv("CASTING_TEST_POSTGRES_URL")

def load(name):
    path = VERSIONS / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

@pytest.mark.skipif(not POSTGRES, reason="Disposable PostgreSQL not configured")
def test_two_revisions_tenant_integrity_and_reverse_rollback():
    engine = sa.create_engine(POSTGRES)
    org_migration = load("20261010_casting_org_draft")
    content_migration = load("20261010_casting_content_draft")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS platform_users (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO platform_users (id) VALUES ('applicant'), ('reviewer') ON CONFLICT (id) DO NOTHING")
        operations = Operations(MigrationContext.configure(conn))
        originals = [m.op for m in (org_migration, content_migration)]
        try:
            org_migration.op = operations
            content_migration.op = operations
            org_migration.upgrade()
            content_migration.upgrade()
            meta = sa.MetaData()
            meta.reflect(bind=conn)
            org = meta.tables["nova_casting_organizations"]
            campaign = meta.tables["nova_casting_campaigns"]
            application = meta.tables["nova_casting_applications"]
            media = meta.tables["nova_casting_media"]
            review = meta.tables["nova_casting_reviews"]
            conn.execute(org.insert(), [
                dict(id="org1", nova_tenant_id="tenant1", name="One", created_at="now"),
                dict(id="org2", nova_tenant_id="tenant2", name="Two", created_at="now"),
            ])
            conn.execute(campaign.insert().values(id="camp1", owner_id="org1", title="Draft", category="film", created_at="now"))
            conn.execute(application.insert().values(id="app1", owner_id="org1", campaign_id="camp1", applicant_id="applicant", created_at="now"))
            assert conn.execute(sa.select(application.c.status).where(application.c.id == "app1")).scalar_one() == "DRAFT"
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(application.insert().values(id="bad", owner_id="org2", campaign_id="camp1", applicant_id="reviewer", created_at="now"))
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(media.insert().values(id="bad-media", owner_id="org2", application_id="app1", storage_key="private", mime_type="video/mp4", byte_size=100, created_at="now"))
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(review.insert().values(id="bad-review", owner_id="org2", application_id="app1", reviewer_id="reviewer", updated_at="now"))
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(media.insert().values(id="oversize", owner_id="org1", application_id="app1", storage_key="private", mime_type="video/mp4", byte_size=262144001, created_at="now"))
            content_migration.downgrade()
            org_migration.downgrade()
            names = set(sa.inspect(conn).get_table_names())
            assert "platform_users" in names
            assert not any(name.startswith("nova_casting_") for name in names)
        finally:
            org_migration.op, content_migration.op = originals
    engine.dispose()
