"""Fictional subscriber FAQ stays in the sandbox and never stores billing."""
import os
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from sqlalchemy.orm import sessionmaker

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/versions/20261018_casting_faq.py"
_STUDIO = ROOT / "app/core/nova/creative_studio"


def _studio_package():
    """Import casting modules without loading the Creative Studio router."""
    name = "app.core.nova.creative_studio"
    package = sys.modules.get(name)
    if package is None or not hasattr(package, "__path__"):
        package = types.ModuleType(name)
        package.__path__ = [str(_STUDIO)]
        package.__package__ = name
        sys.modules[name] = package


_studio_package()
from app.core.nova.creative_studio.casting_access import CastingAccessDenied
from app.core.nova.creative_studio.casting_pilot import PilotDenied, PilotDirectory, PilotRejected
from app.core.nova.creative_studio.casting_subscriber_faq import classify_subscriber_question
PAN = "4111111111111111"


def _actor(role="applicant", user="applicant", org="org-a", tenant="tenant-a"):
    return {
        "user_id": user,
        "organization_id": org,
        "tenant_id": tenant,
        "role": role,
        "verified": True,
    }


def _directory():
    counter = {"n": 0}

    def factory():
        counter["n"] += 1
        return f"faq-{counter['n']}"

    return PilotDirectory(datetime(2026, 11, 2, tzinfo=timezone.utc), id_factory=factory)


def test_listed_harborlight_answer_is_not_a_send():
    result = _directory().ask_subscriber_faq(_actor(), "When is the fictional callback?")
    assert result["topic"] == "callback-window"
    assert result["status"] == "answered"
    assert result["human_required"] is False
    assert result["external_delivery"] is False
    assert result["billing_collected"] is False
    assert result["credentials_stored"] is False
    assert result["label"] == "Demo / Early Access"
    assert "asker_id" not in result


def test_card_number_is_redacted_and_waits_for_a_person():
    result = _directory().ask_subscriber_faq(_actor(), f"Please charge card {PAN}")
    assert PAN not in result["question"]
    assert "[redacted]" in result["question"]
    assert result["topic"] == "credentials"
    assert result["status"] == "waiting_for_person"
    assert result["human_required"] is True
    assert result["credentials_stored"] is False
    assert result["billing_collected"] is False
    assert "charged" in result["answer"].lower() or "Nothing was charged" in result["answer"]


def test_unlisted_and_ticket_questions_do_not_invent_a_checkout():
    directory = _directory()
    unknown = directory.ask_subscriber_faq(_actor(), "Can the fictional lead wear a green coat?")
    assert unknown["topic"] == "unlisted"
    assert unknown["status"] == "waiting_for_person"
    assert "does not guess" in unknown["answer"]
    tickets = directory.ask_subscriber_faq(_actor(user="applicant-2"), "Do you sell tickets or merchandise?")
    assert tickets["topic"] == "ticket-inquiry"
    assert tickets["human_required"] is True
    assert "no ticket cart" in tickets["answer"]
    assert tickets["billing_collected"] is False


def test_applicants_see_only_their_questions_and_cannot_acknowledge():
    directory = _directory()
    own = directory.ask_subscriber_faq(_actor(user="ada"), "Can the fictional lead wear a green coat?")
    directory.ask_subscriber_faq(_actor(user="bea"), "How long is the self-tape?")
    directory.ask_subscriber_faq(_actor(user="cy", org="org-b"), "What are your hours?")
    page = directory.list_subscriber_faq(_actor(user="ada"))
    assert [item["topic"] for item in page["items"]] == ["unlisted"]
    assert page["external_delivery"] is False
    with pytest.raises(PilotDenied):
        directory.acknowledge_subscriber_faq(_actor(user="ada"), own["id"])
    organizer = directory.list_subscriber_faq(_actor(role="organizer", user="organizer"))
    assert {item["topic"] for item in organizer["items"]} == {"unlisted", "self-tape"}
    assert all(item["asker_id"] for item in organizer["items"])
    acked = directory.acknowledge_subscriber_faq(_actor(role="reviewer", user="reviewer"), own["id"])
    assert acked["status"] == "acknowledged"
    assert acked["external_delivery"] is False
    assert acked["acknowledged_by"] == "reviewer"
    with pytest.raises(PilotRejected):
        directory.acknowledge_subscriber_faq(_actor(role="organizer", user="organizer"), own["id"])


def test_empty_question_is_rejected():
    with pytest.raises(PilotRejected):
        _directory().ask_subscriber_faq(_actor(), "   ")
    decision = classify_subscriber_question("password reset for the billing portal")
    assert decision["topic"] == "credentials"
    assert "password" not in decision["answer"].lower() or "passwords" in decision["answer"].lower()


def test_sqlite_faq_survives_a_new_session(monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, "disposable")
    _studio_package()
    from app.db.models import User
    from app.core.nova.creative_studio import casting_db_models, casting_pilot_models, casting_pilot_store

    engine = sa.create_engine("sqlite://")
    tables = [
        User.__table__,
        casting_db_models.NovaCastingOrganization.__table__,
        casting_db_models.NovaCastingMembership.__table__,
        casting_db_models.NovaCastingCampaign.__table__,
        casting_pilot_models.NovaCastingRole.__table__,
        casting_pilot_models.NovaCastingIntake.__table__,
        casting_pilot_models.NovaCastingRubric.__table__,
        casting_pilot_models.NovaCastingPilotMessage.__table__,
        casting_pilot_models.NovaCastingSuppression.__table__,
        casting_pilot_models.NovaCastingSchedule.__table__,
        casting_pilot_models.NovaCastingPilotAudit.__table__,
        casting_pilot_models.NovaCastingInvite.__table__,
        casting_pilot_models.NovaCastingMockAttempt.__table__,
        casting_pilot_models.NovaCastingMockMedia.__table__,
        casting_pilot_models.NovaCastingJourneyAudit.__table__,
        casting_pilot_models.NovaCastingFaqTicket.__table__,
    ]
    for table in tables:
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    db.add(User(
        id="organizer", email="organizer@example.invalid", hashed_password="not-a-login",
        role="staff", organization_id="tenant-a", is_active=True, is_verified=True,
    ))
    db.add(User(
        id="applicant", email="applicant@example.invalid", hashed_password="not-a-login",
        role="staff", organization_id="tenant-a", is_active=True, is_verified=True,
    ))
    db.add(casting_db_models.NovaCastingOrganization(
        id="org-a", nova_tenant_id="tenant-a", name="Harborlight samples",
        verification_status="VERIFIED", created_at="2026-11-01T00:00:00+00:00",
    ))
    db.add(casting_db_models.NovaCastingMembership(
        id="member-organizer", nova_tenant_id="tenant-a", organization_id="org-a",
        user_id="organizer", casting_role="organizer", active=True,
        created_at="2026-11-01T00:00:00+00:00",
    ))
    db.commit()
    saved = casting_pilot_store.ask_subscriber_faq(
        db=db, user_id="applicant", tenant_id="tenant-a", organization_id="org-a",
        question=f"My account number is {PAN}",
    )
    db.commit()
    assert saved["external_delivery"] is False
    db.close()
    again = Session()
    listed = casting_pilot_store.list_subscriber_faq(
        db=again, user_id="organizer", tenant_id="tenant-a", organization_id="org-a",
    )
    assert len(listed["items"]) == 1
    assert PAN not in listed["items"][0]["question"]
    row = again.get(casting_pilot_models.NovaCastingFaqTicket, saved["id"])
    assert row.external_delivery == "false"
    assert row.credentials_stored == "false"
    assert row.billing_collected == "false"
    acked = casting_pilot_store.acknowledge_subscriber_faq(
        db=again, user_id="organizer", tenant_id="tenant-a", organization_id="org-a",
        ticket_id=saved["id"],
    )
    again.commit()
    assert acked["status"] == "acknowledged"
    assert acked["external_delivery"] is False
    with pytest.raises(CastingAccessDenied):
        casting_pilot_store.list_subscriber_faq(
            db=again, user_id="organizer", tenant_id="tenant-b", organization_id="org-a",
        )
    again.close()
    engine.dispose()


def _migration(engine):
    spec_name = "casting_faq_migration_under_test"
    import importlib.util
    spec = importlib.util.spec_from_file_location(spec_name, MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def bind(connection):
        module.op = Operations(MigrationContext.configure(connection))

    return module, bind


def test_faq_migration_is_production_locked_and_reversible(monkeypatch):
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(name, "disposable")
    engine = sa.create_engine("sqlite://")
    module, bind = _migration(engine)
    with engine.begin() as connection:
        bind(connection)
        os.environ["APP_ENV"] = "production"
        module.upgrade()
        assert "nova_casting_faq_tickets" not in set(sa.inspect(connection).get_table_names())
        os.environ["APP_ENV"] = "disposable"
        module.upgrade()
        assert "nova_casting_faq_tickets" not in set(sa.inspect(connection).get_table_names())
        connection.execute(sa.text("CREATE TABLE platform_users (id VARCHAR(36) PRIMARY KEY)"))
        connection.execute(sa.text("CREATE TABLE nova_casting_organizations (id VARCHAR(36) PRIMARY KEY)"))
        module.upgrade()
        assert "nova_casting_faq_tickets" in set(sa.inspect(connection).get_table_names())
        failed = False
        try:
            with connection.begin_nested():
                connection.execute(sa.text(
                    "INSERT INTO nova_casting_faq_tickets "
                    "(id, organization_id, asker_id, question, topic, answer, status, human_required, "
                    "external_delivery, credentials_stored, billing_collected, acknowledged_by, "
                    "acknowledged_at, created_at) VALUES "
                    "('t', 'o', 'u', 'hours', 'support-hours', 'canned', 'answered', 0, "
                    "'true', 'false', 'false', '', '', 't')"
                ))
        except Exception:
            failed = True
        assert failed is True
        module.downgrade()
        names = set(sa.inspect(connection).get_table_names())
        assert "nova_casting_faq_tickets" not in names
        assert "platform_users" in names
