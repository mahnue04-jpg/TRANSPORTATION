"""Authenticated sandbox pilot checks. SQLite is enough. No message is sent."""
import os
import smtplib
import sys
import types
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

_STUDIO = Path(__file__).resolve().parents[1] / "app/core/nova/creative_studio"
ORG = "org-a"
CAMPAIGN = "campaign-1"
EMAIL = "jordan.hale@example.invalid"
LINK = "https://example.invalid/tapes/jordan"


def _studio_package():
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


def _forbid_mail(monkeypatch):
    def opened(*_args, **_kwargs):
        raise AssertionError("outbound mail transport opened")

    monkeypatch.setattr(smtplib, "SMTP", opened)
    monkeypatch.setattr(smtplib, "SMTP_SSL", opened)


def _user_row(user_id, tenant):
    from app.db.models import User

    return User(
        id=user_id, email=f"{user_id}@example.invalid", hashed_password="not-a-login",
        role="staff", organization_id=tenant, is_active=True, is_verified=True,
    )


@pytest.fixture
def pilot_app(monkeypatch, tmp_path):
    _enable(monkeypatch)
    _forbid_mail(monkeypatch)
    _studio_package()
    from fastapi import Request

    from app.auth import UserContext, get_current_user_context
    from app.core.nova.creative_studio import casting_db_models
    from app.core.nova.creative_studio import casting_pilot_models
    from app.core.nova.creative_studio.casting_router_draft import router
    from app.db.models import User

    url = f"sqlite:///{tmp_path / 'pilot.db'}"
    engine = sa.create_engine(url, connect_args={"check_same_thread": False})

    @sa.event.listens_for(engine, "connect")
    def _foreign_keys(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

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
    ]
    for table in tables:
        table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    db = Session()
    db.add_all([
        _user_row("organizer", "tenant-a"),
        _user_row("reviewer", "tenant-a"),
        _user_row("applicant", "tenant-a"),
        _user_row("applicant-b", "tenant-a"),
        _user_row("invitee", "tenant-a"),
        _user_row("stranger", "tenant-a"),
        _user_row("other-tenant", "tenant-b"),
        casting_db_models.NovaCastingOrganization(
            id=ORG, nova_tenant_id="tenant-a", name="Harborlight samples",
            verification_status="VERIFIED", created_at="2026-10-01T00:00:00+00:00",
        ),
    ])
    db.flush()
    db.add_all([
        casting_db_models.NovaCastingMembership(
            id="member-organizer", nova_tenant_id="tenant-a", organization_id=ORG,
            user_id="organizer", casting_role="organizer", active=True,
            created_at="2026-10-01T00:00:00+00:00",
        ),
        casting_db_models.NovaCastingMembership(
            id="member-reviewer", nova_tenant_id="tenant-a", organization_id=ORG,
            user_id="reviewer", casting_role="reviewer", active=True,
            created_at="2026-10-01T00:00:00+00:00",
        ),
        casting_db_models.NovaCastingCampaign(
            id=CAMPAIGN, owner_id=ORG, title="Harborlight", category="film",
            status="DRAFT", minimum_age=18, created_at="2026-10-01T00:00:00+00:00",
        ),
    ])
    db.flush()
    db.add_all([
        casting_db_models.NovaCastingApplication(
            id="app-1", owner_id=ORG, campaign_id=CAMPAIGN, applicant_id="applicant",
            status="DRAFT", created_at="2026-10-01T00:00:00+00:00",
        ),
        casting_db_models.NovaCastingApplication(
            id="app-2", owner_id=ORG, campaign_id=CAMPAIGN, applicant_id="applicant-b",
            status="DRAFT", created_at="2026-10-01T00:00:00+00:00",
        ),
    ])
    db.commit()
    db.close()
    monkeypatch.setattr("app.db.session.SessionLocal", Session)
    app = FastAPI()
    app.include_router(router)

    def current_user(request: Request):
        user_id = request.headers.get("x-test-user") or ""
        tenant = request.headers.get("x-test-tenant") or ""
        if not user_id or not tenant:
            from fastapi import HTTPException
            raise HTTPException(status_code=401, detail="Authentication required")
        return UserContext(
            user_id=user_id, email=f"{user_id}@example.invalid", role="staff", organization_id=tenant,
        )

    app.dependency_overrides[get_current_user_context] = current_user

    class AuthedClient(TestClient):
        def __init__(self, user_id, tenant):
            super().__init__(app)
            self.user_id = user_id
            self.tenant = tenant

        def request(self, method, url, **kwargs):
            headers = dict(kwargs.pop("headers", None) or {})
            headers["x-test-user"] = self.user_id
            headers["x-test-tenant"] = self.tenant
            return super().request(method, url, headers=headers, **kwargs)

    def client_for(user_id, tenant="tenant-a"):
        return AuthedClient(user_id, tenant)

    yield {"client_for": client_for, "Session": Session, "url": url, "engine": engine}
    engine.dispose()


def _path(suffix):
    return f"/api/nova/casting/organizations/{ORG}{suffix}"


def _role_body():
    return {
        "title": "Harbor lead",
        "requirements": "Two-minute self-tape. Adults only.",
        "deadline": "2027-12-01T18:00:00+00:00",
        "minimum_age": 18,
        "questions": [{"id": "union", "prompt": "Can you attend a sandbox callback?"}],
    }


def _intake(role_id, **override):
    payload = {
        "role_id": role_id,
        "display_name": "Jordan Hale",
        "contact_email": EMAIL,
        "video_url": LINK,
        "age_years": 28,
        "consent_accepted": True,
        "consent_version": "sandbox-v1",
        "retention_days": 30,
        "answers": {"union": "Yes"},
    }
    payload.update(override)
    return payload


def _create_role(pilot_app):
    response = pilot_app["client_for"]("organizer").post(
        _path(f"/campaigns/{CAMPAIGN}/roles"), json=_role_body(),
    )
    assert response.status_code == 200, response.text
    assert response.json()["published"] is False
    return response.json()["id"]


def test_pilot_http_is_closed_in_production_and_when_unset(monkeypatch):
    _studio_package()
    from app.auth import UserContext, get_current_user_context
    from app.core.nova.creative_studio.casting_router_draft import router

    def fail(*_args, **_kwargs):
        raise AssertionError("casting session opened")

    monkeypatch.setattr("app.db.session.SessionLocal", fail)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: UserContext(
        user_id="organizer", email="organizer@example.invalid", role="staff", organization_id="tenant-a",
    )
    client = TestClient(app)
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, "disposable")
    assert client.get(_path("/pilot-snapshot")).status_code == 503
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    monkeypatch.setenv("APP_ENV", "production")
    denied = client.post(_path("/messages"), json={
        "kind": "update", "idempotency_key": "closed-key-1", "channel": "email",
    })
    assert denied.status_code == 503
    assert "sent" not in denied.text.lower() or "not enabled" in denied.text.lower()


def test_saved_harborlight_survives_a_new_session_and_is_not_sent(pilot_app):
    organizer = pilot_app["client_for"]("organizer")
    first = organizer.post(_path(f"/campaigns/{CAMPAIGN}/pilot-demo"))
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["published"] is False
    assert body["message"]["delivered"] is False
    assert body["message"]["external_delivery"] is False
    assert body["message"]["delivery_state"] == "not_sent"
    assert len(body["roles"]) == 3
    second = organizer.post(_path(f"/campaigns/{CAMPAIGN}/pilot-demo"))
    assert second.status_code == 200, second.text
    assert [role["id"] for role in second.json()["roles"]] == [role["id"] for role in body["roles"]]
    fresh_engine = sa.create_engine(pilot_app["url"], connect_args={"check_same_thread": False})
    Fresh = sessionmaker(bind=fresh_engine, expire_on_commit=False)
    db = Fresh()
    from app.core.nova.creative_studio.casting_pilot_models import (
        NovaCastingPilotMessage, NovaCastingRole,
    )
    roles = db.query(NovaCastingRole).all()
    messages = db.query(NovaCastingPilotMessage).all()
    assert len(roles) == 3
    assert len(messages) == 1
    assert messages[0].delivery_state == "not_sent"
    assert messages[0].channel == "email"
    db.close()
    fresh_engine.dispose()
    reloaded = organizer.get(_path(f"/pilot-snapshot?campaign_id={CAMPAIGN}"))
    assert reloaded.status_code == 200, reloaded.text
    saved = reloaded.json()
    assert saved["published"] is False
    assert saved["delivered"] is False
    assert saved["external_delivery"] is False
    assert len(saved["roles"]) == 3
    assert saved["messages"][0]["delivered"] is False
    assert saved["messages"][0]["delivery_state"] == "not_sent"


def test_cross_tenant_role_and_reviewer_privacy(pilot_app):
    role_id = _create_role(pilot_app)
    applicant = pilot_app["client_for"]("applicant")
    saved = applicant.post(_path("/applications/app-1/intake"), json=_intake(role_id))
    assert saved.status_code == 200, saved.text
    submitted = applicant.post(_path("/applications/app-1/intake/submit"))
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["contact_email"] == EMAIL
    other = pilot_app["client_for"]("other-tenant", "tenant-b")
    hidden = other.get(_path("/pilot-snapshot"))
    assert hidden.status_code == 404
    assert EMAIL not in hidden.text
    assert "example.invalid/tapes" not in hidden.text
    assert other.post(_path(f"/campaigns/{CAMPAIGN}/roles"), json=_role_body()).status_code == 404
    stranger = pilot_app["client_for"]("stranger")
    denied = stranger.get(_path("/review-queue"))
    assert denied.status_code == 404
    assert EMAIL not in denied.text
    reviewer = pilot_app["client_for"]("reviewer")
    queue = reviewer.get(_path("/review-queue?limit=20&offset=0"))
    assert queue.status_code == 200, queue.text
    item = queue.json()["items"][0]
    assert item["contact_email"] == ""
    assert item["video_url"] == ""
    assert item["display_name"] == ""
    assert EMAIL not in queue.text
    assert LINK not in queue.text
    assert reviewer.get(_path("/pilot-export?include_contact=true")).status_code == 404
    assert reviewer.post(_path("/messages"), json={
        "kind": "invite", "application_id": "app-1", "idempotency_key": "reviewer-no-mail", "channel": "email",
    }).status_code == 404
    assert applicant.post(_path(f"/campaigns/{CAMPAIGN}/roles"), json=_role_body()).status_code == 404
    other_applicant = pilot_app["client_for"]("applicant-b")
    own = other_applicant.get(_path("/pilot-snapshot"))
    assert own.status_code == 200, own.text
    assert EMAIL not in own.text
    assert own.json()["messages"] == []
    duplicate = other_applicant.post(_path("/applications/app-2/intake"), json=_intake(
        role_id, display_name="Other Person",
    ))
    assert duplicate.status_code == 422
    assert duplicate.json()["detail"] == "Duplicate application"


def test_revoke_persists_minimized_contact_for_the_next_session(pilot_app):
    role_id = _create_role(pilot_app)
    applicant = pilot_app["client_for"]("applicant")
    assert applicant.post(_path("/applications/app-1/intake"), json=_intake(role_id)).status_code == 200
    revoked = applicant.post(_path("/applications/app-1/intake/revoke"))
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["contact_email"] == ""
    assert revoked.json()["video_url"] == ""
    assert revoked.json()["consent_revoked"] is True
    fresh = sessionmaker(bind=sa.create_engine(
        pilot_app["url"], connect_args={"check_same_thread": False},
    ))()
    from app.core.nova.creative_studio.casting_pilot_models import NovaCastingIntake
    row = fresh.get(NovaCastingIntake, "app-1")
    assert row.contact_email == ""
    assert row.video_url == ""
    assert row.display_name == ""
    assert row.consent_revoked_at
    assert row.status == "WITHDRAWN"
    fresh.close()
    organizer = pilot_app["client_for"]("organizer").get(_path("/pilot-snapshot"))
    assert organizer.status_code == 200
    saved = organizer.json()["intakes"][0]
    assert saved["contact_email"] == ""
    assert saved["video_url"] == ""
    assert EMAIL not in organizer.text
    reviewer = pilot_app["client_for"]("reviewer").get(_path("/review-queue"))
    assert EMAIL not in reviewer.text
    assert LINK not in reviewer.text
    blocked = applicant.post(_path("/applications/app-1/intake/submit"))
    assert blocked.status_code == 422, blocked.text
    assert blocked.json()["detail"] == "Consent revoked"


def test_expired_consent_cannot_be_submitted(pilot_app):
    role_id = _create_role(pilot_app)
    applicant = pilot_app["client_for"]("applicant")
    saved = applicant.post(_path("/applications/app-1/intake"), json=_intake(role_id, retention_days=1))
    assert saved.status_code == 200, saved.text
    db = pilot_app["Session"]()
    from app.core.nova.creative_studio.casting_pilot_models import NovaCastingIntake
    row = db.get(NovaCastingIntake, "app-1")
    row.consent_expires_at = "2020-01-01T00:00:00+00:00"
    db.commit()
    db.close()
    expired = applicant.post(_path("/applications/app-1/intake/submit"))
    assert expired.status_code == 422
    assert expired.json()["detail"] == "Consent expired"
    check = pilot_app["Session"]()
    kept = check.get(NovaCastingIntake, "app-1")
    assert kept.status == "DRAFT"
    check.close()


def test_minor_and_protected_fields_are_not_stored(pilot_app):
    role_id = _create_role(pilot_app)
    applicant = pilot_app["client_for"]("applicant")
    minor = applicant.post(_path("/applications/app-1/intake"), json=_intake(role_id, age_years=17))
    assert minor.status_code == 422
    assert minor.json()["detail"] == "Applicant does not meet the minimum age"
    protected = applicant.post(_path("/applications/app-1/intake"), json=_intake(
        role_id, guardian_attestation=True,
    ))
    assert protected.status_code == 422
    assert protected.json()["detail"] == "Request rejected"
    assert "guardian_attestation" not in protected.text
    db = pilot_app["Session"]()
    from app.core.nova.creative_studio.casting_pilot_models import NovaCastingIntake
    assert db.query(NovaCastingIntake).count() == 0
    db.close()


def test_rate_limit_and_fake_providers_do_not_send(pilot_app, monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_SMS_PROVIDER", "fake-mail")
    monkeypatch.setenv("NOVA_CASTING_WHATSAPP_PROVIDER", "fake-mail")
    organizer = pilot_app["client_for"]("organizer")
    for index in range(20):
        drafted = organizer.post(_path("/messages"), json={
            "kind": "update",
            "idempotency_key": f"rate-key-{index:02d}",
            "channel": "email",
        })
        assert drafted.status_code == 200, drafted.text
        assert drafted.json()["delivered"] is False
        assert drafted.json()["external_delivery"] is False
        assert drafted.json()["delivery_state"] == "not_sent"
    blocked = organizer.post(_path("/messages"), json={
        "kind": "update", "idempotency_key": "rate-key-overflow", "channel": "email",
    })
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "Rate limited"
    sms = organizer.post(_path("/messages"), json={
        "kind": "reminder", "idempotency_key": "rate-key-00", "channel": "sms",
    })
    assert sms.status_code == 200, sms.text
    assert sms.json()["delivered"] is False
    assert sms.json()["channel"] == "email"
    whatsapp = organizer.post(_path("/messages"), json={
        "kind": "reminder", "idempotency_key": "whatsapp-closed-01", "channel": "whatsapp",
    })
    assert whatsapp.status_code == 422
    assert whatsapp.json()["detail"] == "Rate limited"
    approved = organizer.post(_path(f"/messages/{sms.json()['id']}/approve"))
    assert approved.status_code == 200, approved.text
    assert approved.json()["delivered"] is False
    assert approved.json()["external_delivery"] is False
    retried = organizer.post(_path(f"/messages/{sms.json()['id']}/retry"))
    assert retried.status_code == 200, retried.text
    assert retried.json()["delivered"] is False
    assert retried.json()["attempt_count"] == 1
    db = pilot_app["Session"]()
    from app.core.nova.creative_studio.casting_pilot_models import NovaCastingPilotMessage
    rows = db.query(NovaCastingPilotMessage).all()
    assert len(rows) == 20
    assert {row.delivery_state for row in rows} == {"not_sent"}
    assert all(row.status != "sent" for row in rows)
    db.close()


def test_configured_fake_sms_is_stored_unsent_before_the_daily_cap(pilot_app, monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_SMS_PROVIDER", "fake-mail")
    monkeypatch.setenv("NOVA_CASTING_WHATSAPP_PROVIDER", "fake-mail")
    organizer = pilot_app["client_for"]("organizer")
    sms = organizer.post(_path("/messages"), json={
        "kind": "reminder", "idempotency_key": "sms-closed-01", "channel": "sms",
    })
    assert sms.status_code == 200, sms.text
    assert sms.json()["status"] == "failed_closed"
    assert sms.json()["delivered"] is False
    assert sms.json()["external_delivery"] is False
    assert sms.json()["delivery_state"] == "not_sent"
    whatsapp = organizer.post(_path("/messages"), json={
        "kind": "reminder", "idempotency_key": "wa-closed-01", "channel": "whatsapp",
    })
    assert whatsapp.status_code == 200, whatsapp.text
    assert whatsapp.json()["status"] == "failed_closed"
    assert whatsapp.json()["delivered"] is False
    db = pilot_app["Session"]()
    from app.core.nova.creative_studio.casting_pilot_models import NovaCastingPilotMessage
    rows = db.query(NovaCastingPilotMessage).all()
    assert len(rows) == 2
    assert {row.delivery_state for row in rows} == {"not_sent"}
    db.close()


def _mini_mp4() -> bytes:
    body = b"ftyp" + b"isom" + b"\x00\x00\x00\x00"
    return (len(body) + 4).to_bytes(4, "big") + body


def test_authenticated_journey_invite_mock_transport_and_upload(pilot_app):
    organizer = pilot_app["client_for"]("organizer")
    invitee = pilot_app["client_for"]("invitee")
    other = pilot_app["client_for"]("other-tenant", "tenant-b")
    reviewer = pilot_app["client_for"]("reviewer")
    role_id = _create_role(pilot_app)
    issued = organizer.post(_path(f"/campaigns/{CAMPAIGN}/invites"), json={
        "role_id": role_id,
        "expires_at": "2027-12-01T18:00:00+00:00",
    })
    assert issued.status_code == 200, issued.text
    invite = issued.json()
    assert invite["published"] is False
    assert invite["status"] == "open"
    assert invite["public_url"] == ""
    assert invite["token"]
    assert other.post(_path("/invites/redeem"), json={"token": invite["token"]}).status_code == 404
    redeemed = invitee.post(_path("/invites/redeem"), json={"token": invite["token"]})
    assert redeemed.status_code == 200, redeemed.text
    application_id = redeemed.json()["application_id"]
    assert redeemed.json()["token"] == ""
    assert redeemed.json()["public_url"] == ""
    saved = invitee.post(_path(f"/applications/{application_id}/intake"), json=_intake(role_id, contact_email="invitee@example.invalid"))
    assert saved.status_code == 200, saved.text
    receipt = saved.json()["receipt"]
    assert receipt.startswith("CA-")
    submitted = invitee.post(_path(f"/applications/{application_id}/intake/submit"))
    assert submitted.status_code == 200, submitted.text
    files = {"file": ("tape.mp4", _mini_mp4(), "video/mp4")}
    clean = invitee.post(
        _path(f"/applications/{application_id}/mock-upload"),
        data={"mime_type": "video/mp4", "consent_accepted": "true"},
        files=files,
    )
    assert clean.status_code == 200, clean.text
    assert clean.json()["scan_status"] == "CLEAN"
    assert clean.json()["public_url"] == ""
    assert clean.json()["bytes_released"] is False
    assert clean.json()["playback"] == "unavailable"
    assert clean.json()["media_uploads_enabled"] is False
    hostile = invitee.post(
        _path(f"/applications/{application_id}/mock-upload"),
        data={"mime_type": "video/mp4", "consent_accepted": "true"},
        files={"file": ("bad.mp4", _mini_mp4() + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE", "video/mp4")},
    )
    assert hostile.status_code == 200, hostile.text
    assert hostile.json()["scan_status"] == "REJECTED"
    assert hostile.json()["bytes_released"] is False
    hidden = reviewer.get(_path(f"/applications/{application_id}/mock-uploads"))
    assert hidden.status_code == 200, hidden.text
    assert hidden.json()["public_url"] == ""
    assert all(item["public_url"] == "" and item["playback"] == "unavailable" for item in hidden.json()["items"])
    assert "example.invalid" not in hidden.text
    short = reviewer.post(_path(f"/applications/{application_id}/pilot-review"), json={"stage": "Callback", "shortlisted": True})
    assert short.status_code == 200, short.text
    drafted = organizer.post(_path("/messages"), json={
        "kind": "confirmation", "idempotency_key": "journey-key-01", "channel": "email",
        "application_id": application_id,
    })
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["delivery_state"] == "not_sent"
    blocked_send = organizer.post(_path(f"/messages/{drafted.json()['id']}/mock-dispatch"), json={"fail": False})
    assert blocked_send.status_code == 422
    approved = organizer.post(_path(f"/messages/{drafted.json()['id']}/approve"))
    assert approved.status_code == 200, approved.text
    failed = organizer.post(_path(f"/messages/{drafted.json()['id']}/mock-dispatch"), json={"fail": True})
    assert failed.status_code == 200, failed.text
    assert failed.json()["mock_outcome"] == "mock_failed"
    assert failed.json()["mock_receipt"] == ""
    assert failed.json()["real_delivery"] is False
    assert failed.json()["delivery_state"] == "not_sent"
    accepted = organizer.post(_path(f"/messages/{drafted.json()['id']}/mock-dispatch"), json={"fail": False})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["mock_outcome"] == "mock_accepted"
    assert accepted.json()["mock_receipt"].startswith("MOCK-")
    assert accepted.json()["external_delivery"] is False
    again = organizer.post(_path(f"/messages/{drafted.json()['id']}/mock-dispatch"), json={"fail": True})
    assert again.status_code == 200, again.text
    assert again.json()["mock_receipt"] == accepted.json()["mock_receipt"]
    invitee.post(_path("/suppressions"), json={"contact_email": "invitee@example.invalid", "reason": "unsubscribe"})
    opted = organizer.post(_path("/messages"), json={
        "kind": "reminder", "idempotency_key": "journey-opt-01", "channel": "email",
        "application_id": application_id,
    })
    assert opted.status_code == 200, opted.text
    assert opted.json()["status"] == "suppressed"
    opted_send = organizer.post(_path(f"/messages/{opted.json()['id']}/mock-dispatch"), json={"fail": False})
    assert opted_send.status_code == 200, opted_send.text
    assert opted_send.json()["mock_outcome"] == "opted_out"
    assert opted_send.json()["mock_receipt"] == ""
    assert opted_send.json()["real_delivery"] is False
    scheduled = organizer.post(_path(f"/campaigns/{CAMPAIGN}/schedule"), json={
        "role_id": role_id,
        "timezone": "America/New_York",
        "starts_at": "2026-11-18T15:00:00+00:00",
        "ends_at": "2026-11-18T18:00:00+00:00",
        "location_label": "Fictional reading room",
        "document_url": "https://example.invalid/side.pdf",
    })
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["published"] is False
    sheet = organizer.get(_path(f"/roles/{role_id}/call-sheet"))
    assert sheet.status_code == 200, sheet.text
    assert sheet.json()["external_delivery"] is False
    exported = organizer.get(_path("/pilot-export?include_contact=false"))
    assert exported.status_code == 200, exported.text
    assert receipt in exported.text
    assert "https://" not in exported.text
    reloaded = organizer.get(_path(f"/pilot-snapshot?campaign_id={CAMPAIGN}"))
    assert reloaded.status_code == 200, reloaded.text
    assert invite["token"] in {item["token"] for item in reloaded.json()["invites"]}
    assert reloaded.json()["delivered"] is False
    assert reloaded.json()["media_uploads_enabled"] is False
    expired = organizer.post(_path(f"/campaigns/{CAMPAIGN}/invites"), json={
        "role_id": role_id, "expires_at": "2020-01-01T00:00:00+00:00",
    })
    assert expired.status_code == 200, expired.text
    denied = invitee.post(_path("/invites/redeem"), json={"token": expired.json()["token"]})
    assert denied.status_code == 422
    assert denied.json()["detail"] == "Expired invite"
    closed = organizer.patch(_path(f"/campaigns/{CAMPAIGN}"), json={
        "title": "Harborlight", "category": "film", "minimum_age": 18, "status": "CLOSED",
    })
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "CLOSED"
    blocked = organizer.post(_path(f"/campaigns/{CAMPAIGN}/invites"), json={
        "role_id": role_id, "expires_at": "2027-12-02T18:00:00+00:00",
    })
    assert blocked.status_code == 422
    assert blocked.json()["detail"] == "Campaign cannot be published"
    from app.core.nova.creative_studio.casting_pilot_models import (
        NovaCastingInvite, NovaCastingJourneyAudit, NovaCastingMockAttempt,
        NovaCastingMockMedia, NovaCastingPilotMessage,
    )
    before_restart = sessionmaker(bind=sa.create_engine(
        pilot_app["url"], connect_args={"check_same_thread": False},
    ))()
    assert before_restart.query(NovaCastingMockMedia).count() >= 1
    assert "byte" not in {column.name for column in NovaCastingMockMedia.__table__.columns if "url" in column.name or column.name == "payload"}
    assert not any(column.name in {"file_bytes", "content", "payload"} for column in NovaCastingMockMedia.__table__.columns)
    assert {row.action for row in before_restart.query(NovaCastingJourneyAudit).all()} >= {"invite.issued", "invite.redeemed", "mock.dispatched"}
    assert any(row.mock_receipt.startswith("MOCK-") for row in before_restart.query(NovaCastingMockAttempt).all())
    assert {row.delivery_state for row in before_restart.query(NovaCastingPilotMessage).all()} == {"not_sent"}
    saved_token = before_restart.query(NovaCastingInvite).filter(NovaCastingInvite.status == "redeemed").one().token
    before_restart.close()
    audit = organizer.get(_path("/pilot-audit?limit=50&offset=0"))
    assert audit.status_code == 200, audit.text
    audit_actions = {item["action"] for item in audit.json()["items"]}
    assert {"invite.issued", "invite.redeemed", "mock.dispatched", "upload.mock_recorded"} <= audit_actions
    assert saved_token not in audit.text
    assert "example.invalid" not in audit.text
    assert other.get(_path("/pilot-audit?limit=50&offset=0")).status_code == 404
    assert saved_token not in other.get(_path("/pilot-audit?limit=50&offset=0")).text
    stranger = pilot_app["client_for"]("stranger")
    assert stranger.get(_path("/pilot-audit?limit=50&offset=0")).status_code == 404
    assert saved_token not in stranger.get(_path("/pilot-snapshot")).text
    assert other.get(_path("/pilot-snapshot")).status_code == 404
    assert saved_token not in other.get(_path("/pilot-snapshot")).text
    wiped = organizer.post(_path("/mock-uploads/wipe"))
    assert wiped.status_code == 200, wiped.text
    assert wiped.json()["bytes_released"] is False
    assert wiped.json()["wiped"] >= 1
    after_restart = sessionmaker(bind=sa.create_engine(
        pilot_app["url"], connect_args={"check_same_thread": False},
    ))()
    assert after_restart.query(NovaCastingMockMedia).count() == 0
    assert after_restart.query(NovaCastingInvite).filter(NovaCastingInvite.status == "redeemed").count() == 1
    assert {row.delivery_state for row in after_restart.query(NovaCastingPilotMessage).all()} == {"not_sent"}
    after_restart.close()
    listed = organizer.get(_path(f"/applications/{application_id}/mock-uploads"))
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"] == []
    assert listed.json()["bytes_released"] is False
    assert listed.json()["media_uploads_enabled"] is False
    assert other.post(_path("/mock-uploads/wipe")).status_code == 404
