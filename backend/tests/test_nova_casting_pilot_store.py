"""SQLite round trip for the sandbox pilot store. No message is marked sent."""
import os
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

_STUDIO = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"


def _studio_package():
    """Import casting modules without loading the Creative Studio router."""
    name = "app.core.nova.creative_studio"
    package = sys.modules.get(name)
    if package is None or not hasattr(package, "__path__"):
        package = types.ModuleType(name)
        package.__path__ = [str(_STUDIO)]
        package.__package__ = name
        sys.modules[name] = package
    return package

os.environ.setdefault("JWT_SECRET", "test-only")
os.environ.setdefault("SECRET_KEY", "test-only")


def _enable(monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, "disposable")
    monkeypatch.delenv("NOVA_CASTING_SMS_PROVIDER", raising=False)
    monkeypatch.delenv("NOVA_CASTING_WHATSAPP_PROVIDER", raising=False)


def test_sqlite_pilot_persists_intake_and_refuses_delivery(monkeypatch):
    _enable(monkeypatch)
    _studio_package()
    from app.db.models import User
    from app.core.nova.creative_studio import casting_db_models
    from app.core.nova.creative_studio import casting_pilot_models
    from app.core.nova.creative_studio.casting_access import CastingAccessDenied
    from app.core.nova.creative_studio.casting_pilot import PilotRejected
    from app.core.nova.creative_studio import casting_pilot_store

    engine = sa.create_engine("sqlite://")
    tables = [
        User.__table__,
        casting_db_models.NovaCastingOrganization.__table__,
        casting_db_models.NovaCastingMembership.__table__,
        casting_db_models.NovaCastingCampaign.__table__,
        casting_db_models.NovaCastingApplication.__table__,
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
    db.add(casting_db_models.NovaCastingCampaign(
        id="campaign-1", owner_id="org-a", title="Harborlight", category="film",
        status="DRAFT", minimum_age=18, created_at="2026-11-01T00:00:00+00:00",
    ))
    db.add(casting_db_models.NovaCastingApplication(
        id="app-1", owner_id="org-a", campaign_id="campaign-1", applicant_id="applicant",
        status="DRAFT", created_at="2026-11-01T00:00:00+00:00",
    ))
    db.commit()
    role = casting_pilot_store.create_role(
        db=db, user_id="organizer", tenant_id="tenant-a", organization_id="org-a",
        campaign_id="campaign-1",
        payload={
            "title": "Harbor lead",
            "requirements": "Self-tape.",
            "deadline": "2026-12-01T18:00:00+00:00",
            "minimum_age": 18,
            "questions": [{"id": "union", "prompt": "Can you attend?"}],
        },
    )
    db.commit()
    saved = casting_pilot_store.save_intake(
        db=db, user_id="applicant", tenant_id="tenant-a", organization_id="org-a",
        application_id="app-1",
        payload={
            "role_id": role["id"],
            "display_name": "Jordan Hale",
            "contact_email": "jordan.hale@example.invalid",
            "video_url": "https://example.invalid/tapes/jordan",
            "age_years": 28,
            "consent_accepted": True,
            "consent_version": "sandbox-v1",
            "retention_days": 30,
            "answers": {"union": "Yes"},
        },
    )
    db.commit()
    assert saved["receipt"].startswith("CA-")
    assert saved["video_url"].startswith("https://")
    again = casting_pilot_store.list_roles(
        db=db, user_id="organizer", tenant_id="tenant-a", organization_id="org-a",
        campaign_id="campaign-1", limit=20, offset=0,
    )
    assert again["items"][0]["title"] == "Harbor lead"
    assert again["items"][0]["published"] is False
    message = casting_pilot_store.draft_message(
        db=db, user_id="organizer", tenant_id="tenant-a", organization_id="org-a",
        payload={"kind": "confirmation", "application_id": "app-1", "idempotency_key": "store-key-01", "channel": "email"},
    )
    db.commit()
    assert message["delivered"] is False
    assert message["external_delivery"] is False
    assert message["delivery_state"] == "not_sent"
    row = db.get(casting_pilot_models.NovaCastingPilotMessage, message["id"])
    assert row.delivery_state == "not_sent"
    with pytest.raises(PilotRejected):
        casting_pilot_store.draft_message(
            db=db, user_id="organizer", tenant_id="tenant-a", organization_id="org-a",
            payload={"kind": "reminder", "idempotency_key": "store-sms-01", "channel": "sms"},
        )
    with pytest.raises(CastingAccessDenied):
        casting_pilot_store.create_role(
            db=db, user_id="organizer", tenant_id="tenant-b", organization_id="org-a",
            campaign_id="campaign-1", payload={"title": "Other", "deadline": "2026-12-01T18:00:00+00:00"},
        )
    db.close()
    engine.dispose()
