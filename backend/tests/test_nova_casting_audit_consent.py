"""Disposable checks for the draft consent and audit revision."""
import importlib.util
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

VERSIONS = Path(__file__).resolve().parents[1] / "migrations/versions"
POSTGRES = os.getenv("CASTING_TEST_POSTGRES_URL")
AUDIT = VERSIONS / "20261010_casting_audit_consent_draft.py"


def load(name):
    path = VERSIONS / (name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_audit_consent_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_audit_actions_match_the_formatter_and_omit_private_columns():
    source = AUDIT.read_text(encoding="utf-8")
    audit = VERSIONS.parents[1] / "app/core/nova/creative_studio/casting_audit.py"
    formatter = audit.read_text(encoding="utf-8")
    for action in (
        "campaign.created", "application.submitted", "application.withdrawn",
        "review.updated", "callback.proposed", "media.quarantined", "media.approved",
    ):
        assert action in source
        assert action in formatter
    for forbidden in ("storage_key", "email", "date_of_birth", "facial", "signed_url", "note"):
        assert forbidden not in source
    assert 'down_revision = "20261010_casting_content_draft"' in source
    assert "def upgrade():" in source and "def downgrade():" in source
    assert "ck_nova_casting_consent_minimum_age" in source
    assert "fk_nova_casting_consent_application_owner" in source


@pytest.mark.parametrize("url", ["sqlite:///:memory:", pytest.param(
    POSTGRES,
    marks=pytest.mark.skipif(not POSTGRES, reason="PostgreSQL CI service not configured"),
)])
def test_consent_and_audit_constraints_round_trip(url):
    engine = sa.create_engine(url)
    modules = [load(name) for name in (
        "20261010_casting_org_draft",
        "20261010_casting_content_draft",
        "20261010_casting_audit_consent_draft",
    )]
    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")
        conn.exec_driver_sql("CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO platform_users (id) VALUES ('applicant'), ('reviewer')")
        originals = [module.op for module in modules]
        operations = Operations(MigrationContext.configure(conn))
        try:
            for module in modules:
                module.op = operations
                module.upgrade()
            meta = sa.MetaData()
            meta.reflect(bind=conn)
            org = meta.tables["nova_casting_organizations"]
            campaign = meta.tables["nova_casting_campaigns"]
            application = meta.tables["nova_casting_applications"]
            consent = meta.tables["nova_casting_consent_events"]
            audit = meta.tables["nova_casting_audit_events"]
            conn.execute(org.insert(), [
                dict(id="org1", nova_tenant_id="tenant1", name="One", created_at="now"),
                dict(id="org2", nova_tenant_id="tenant2", name="Two", created_at="now"),
            ])
            conn.execute(campaign.insert().values(
                id="camp1", owner_id="org1", title="Draft", category="film", created_at="now",
            ))
            conn.execute(application.insert().values(
                id="app1", owner_id="org1", campaign_id="camp1", applicant_id="applicant", created_at="now",
            ))
            conn.execute(consent.insert().values(
                id="consent1", owner_id="org1", application_id="app1", applicant_id="applicant",
                consent_version="v1", minimum_age_attested=18, accepted=True, created_at="now",
            ))
            conn.execute(audit.insert().values(
                id="audit1", actor_id="reviewer", organization_id="org1",
                action="application.submitted", object_id="app1", occurred_at="now",
            ))
            for values in (
                dict(id="young", owner_id="org1", application_id="app1", applicant_id="applicant",
                     consent_version="v1", minimum_age_attested=17, accepted=True, created_at="now"),
                dict(id="refused", owner_id="org1", application_id="app1", applicant_id="applicant",
                     consent_version="v1", minimum_age_attested=18, accepted=False, created_at="now"),
                dict(id="blank", owner_id="org1", application_id="app1", applicant_id="applicant",
                     consent_version="", minimum_age_attested=18, accepted=True, created_at="now"),
                dict(id="cross", owner_id="org2", application_id="app1", applicant_id="applicant",
                     consent_version="v1", minimum_age_attested=21, accepted=True, created_at="now"),
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    with conn.begin_nested():
                        conn.execute(consent.insert().values(**values))
            with pytest.raises(sa.exc.IntegrityError):
                with conn.begin_nested():
                    conn.execute(audit.insert().values(
                        id="bad-action", actor_id="reviewer", organization_id="org1",
                        action="applicant.scored", object_id="app1", occurred_at="now",
                    ))
            for module in reversed(modules):
                module.downgrade()
            names = set(sa.inspect(conn).get_table_names())
            assert "platform_users" in names
            assert not any(name.startswith("nova_casting_") for name in names)
            conn.exec_driver_sql("DROP TABLE platform_users")
        finally:
            for module, original in zip(modules, originals):
                module.op = original
    engine.dispose()
