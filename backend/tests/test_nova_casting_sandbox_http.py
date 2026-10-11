"""Disposable PostgreSQL and TestClient journey for sandbox casting workflows."""
import os

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.casting_access import CastingAccessDenied
from app.core.nova.creative_studio.casting_router_draft import router

URL = os.getenv("CASTING_TEST_POSTGRES_URL")
ORG = "sandbox-org"
NOTE = "DO-NOT-AUDIT-this-note"


def _enable(monkeypatch, name="disposable"):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, name)


def _user(user_id, tenant="tenant-a"):
    return UserContext(user_id=user_id, email=f"{user_id}@example.invalid", role="staff", organization_id=tenant)


def test_disabled_and_production_sandbox_posts_do_not_open_a_session(monkeypatch):
    def fail_session(*_args, **_kwargs):
        raise AssertionError("casting session opened")

    monkeypatch.setattr("app.db.session.SessionLocal", fail_session)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: _user("organizer")
    client = TestClient(app)
    body = {"title": "Draft", "category": "film", "minimum_age": 18, "status": "DRAFT"}
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, "disposable")
    assert client.post(f"/api/nova/casting/organizations/{ORG}/campaigns", json=body).status_code == 503
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    monkeypatch.setenv("APP_ENV", "production")
    assert client.post(f"/api/nova/casting/organizations/{ORG}/campaigns", json=body).status_code == 503


def test_sql_lookup_failures_do_not_leak_database_text(monkeypatch):
    _enable(monkeypatch)
    from app.core.nova.creative_studio.casting_db_writes import create_draft_campaign

    class Boom:
        def query(self, *_args, **_kwargs):
            raise OperationalError("select", {}, Exception("secret-sql"))

    with pytest.raises(CastingAccessDenied) as caught:
        create_draft_campaign(
            db=Boom(), user_id="organizer", tenant_id="tenant-a", organization_id=ORG,
            payload={"title": "Draft", "category": "film", "minimum_age": 18, "status": "DRAFT"},
        )
    assert "secret-sql" not in str(caught.value)


@pytest.mark.skipif(not URL, reason="Disposable PostgreSQL unavailable")
def test_postgres_sandbox_journey_is_human_controlled_and_tenant_scoped(monkeypatch):
    _enable(monkeypatch)
    from app.db.session import Base
    from app.db.models import User
    from app.core.nova.creative_studio import casting_db_models, casting_db_writes

    admin = sa.create_engine(URL)
    with admin.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS casting_sandbox_ci CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA casting_sandbox_ci")
    admin.dispose()
    engine = sa.create_engine(URL, connect_args={"options": "-csearch_path=casting_sandbox_ci"})
    wanted = {
        User.__table__.name,
        casting_db_models.NovaCastingOrganization.__table__.name,
        casting_db_models.NovaCastingMembership.__table__.name,
        casting_db_models.NovaCastingCampaign.__table__.name,
        casting_db_models.NovaCastingApplication.__table__.name,
        casting_db_models.NovaCastingReview.__table__.name,
        casting_db_models.NovaCastingMedia.__table__.name,
        casting_db_models.NovaCastingConsentEvent.__table__.name,
        casting_db_models.NovaCastingAuditEvent.__table__.name,
    }
    for table in Base.metadata.sorted_tables:
        if table.name in wanted:
            table.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.session.SessionLocal", Session)
    seed = Session()
    seed.add_all([
        User(id="organizer", email="organizer@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-a", is_active=True, is_verified=True),
        User(id="reviewer", email="reviewer@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-a", is_active=True, is_verified=True),
        User(id="applicant", email="applicant@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-a", is_active=True, is_verified=True),
        User(id="stranger", email="stranger@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-a", is_active=True, is_verified=True),
        User(id="other-tenant", email="other-tenant@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-b", is_active=True, is_verified=True),
        casting_db_models.NovaCastingOrganization(
            id=ORG, nova_tenant_id="tenant-a", name="Sandbox company",
            verification_status="VERIFIED", created_at="seed",
        ),
    ])
    seed.flush()
    seed.add_all([
        casting_db_models.NovaCastingMembership(
            id="member-organizer", nova_tenant_id="tenant-a", organization_id=ORG,
            user_id="organizer", casting_role="organizer", active=True, created_at="seed",
        ),
        casting_db_models.NovaCastingMembership(
            id="member-reviewer", nova_tenant_id="tenant-a", organization_id=ORG,
            user_id="reviewer", casting_role="reviewer", active=True, created_at="seed",
        ),
    ])
    seed.commit()
    seed.close()

    holder = {"user": _user("organizer")}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: holder["user"]
    client = TestClient(app)
    base = f"/api/nova/casting/organizations/{ORG}"

    def post(path, payload=None, user="organizer", tenant="tenant-a", method="POST"):
        holder["user"] = _user(user, tenant)
        if payload is None:
            return client.request(method, path)
        return client.request(method, path, json=payload)

    campaign_body = {"title": "Disposable film test", "category": "film", "minimum_age": 18, "status": "DRAFT"}
    created = post(f"{base}/campaigns", campaign_body)
    assert created.status_code == 200, created.text
    campaign = created.json()
    assert campaign["status"] == "DRAFT"
    assert "owner_id" not in campaign
    campaign_id = campaign["id"]
    assert post(f"{base}/campaigns", campaign_body, user="reviewer").status_code == 404
    assert post(f"{base}/campaigns", {**campaign_body, "status": "OPEN"}).status_code == 422
    listed = client.get(f"{base}/campaigns?limit=1&offset=0")
    assert listed.status_code == 200
    assert len(listed.json()["items"]) == 1
    assert client.get(f"{base}/campaigns?limit=0").status_code == 422

    holder["user"] = _user("applicant")
    assert client.get(f"{base}/campaigns").status_code == 404
    rejected = post(
        f"{base}/campaigns/{campaign_id}/applications",
        {"consent_accepted": True, "consent_version": "sandbox-v1", "age_years": 17},
        user="applicant",
    )
    assert rejected.status_code == 422
    saved = post(
        f"{base}/campaigns/{campaign_id}/applications",
        {"consent_accepted": True, "consent_version": "sandbox-v1", "age_years": 24},
        user="applicant",
    )
    assert saved.status_code == 200, saved.text
    application_id = saved.json()["id"]
    again = post(
        f"{base}/campaigns/{campaign_id}/applications",
        {"consent_accepted": True, "consent_version": "sandbox-v1", "age_years": 24, "email": "hidden@example.invalid"},
        user="applicant",
    )
    assert again.status_code == 422
    repeat = post(
        f"{base}/campaigns/{campaign_id}/applications",
        {"consent_accepted": True, "consent_version": "sandbox-v1", "age_years": 24},
        user="applicant",
    )
    assert repeat.json()["id"] == application_id
    submit = post(f"{base}/applications/{application_id}/submit", user="applicant")
    assert submit.status_code == 200, submit.text
    assert submit.json()["status"] == "SUBMITTED"
    holder["user"] = _user("applicant")
    detail = client.get(f"{base}/applications/{application_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "SUBMITTED"
    assert "applicant_id" not in detail.json()
    own = client.get(f"{base}/applications")
    assert own.status_code == 200
    assert own.json()["items"][0]["id"] == application_id
    assert "applicant_id" not in own.json()["items"][0]

    assert post(f"{base}/applications/{application_id}/review", {"stage": "New", "score": 4, "note": NOTE}, user="stranger", method="PUT").status_code == 404
    assert post(f"{base}/applications/{application_id}/review", {"stage": "New", "score": 4, "note": NOTE}, user="other-tenant", tenant="tenant-b", method="PUT").status_code == 404
    reviewed = post(
        f"{base}/applications/{application_id}/review",
        {"stage": "New", "score": 4, "note": NOTE},
        user="organizer",
        method="PUT",
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["note"] == NOTE
    shortlisted = post(f"{base}/applications/{application_id}/shortlist", {"shortlisted": True}, user="organizer")
    assert shortlisted.status_code == 200
    assert shortlisted.json()["shortlisted"] is True
    assert shortlisted.json()["stage"] == "In review"
    callback = post(f"{base}/applications/{application_id}/callback", {"proposed": True}, user="organizer")
    assert callback.status_code == 200, callback.text
    assert callback.json()["callback_proposed"] is True
    assert callback.json()["external_delivery"] is False
    assert "note" not in callback.json()
    assert "signed_url" not in callback.json()
    again_callback = post(f"{base}/applications/{application_id}/callback", {"proposed": True}, user="organizer")
    assert again_callback.status_code == 200

    media = post(
        f"{base}/applications/{application_id}/media",
        {"mime_type": "video/mp4", "byte_size": 2048},
        user="applicant",
    )
    assert media.status_code == 200, media.text
    assert media.json()["status"] == "QUARANTINED"
    assert media.json()["playback"] == "unavailable"
    assert "storage_key" not in media.json()
    assert "private-quarantine" not in media.text
    assert post(
        f"{base}/applications/{application_id}/media",
        {"mime_type": "text/plain", "byte_size": 2048},
        user="applicant",
    ).status_code == 422
    assert post(
        f"{base}/applications/{application_id}/media",
        {"mime_type": "video/mp4", "byte_size": 2048, "storage_key": "s3://secret"},
        user="applicant",
    ).status_code == 422
    media_id = media.json()["id"]
    hidden = client.get(f"{base}/applications/{application_id}/media/{media_id}")
    holder["user"] = _user("applicant")
    hidden = client.get(f"{base}/applications/{application_id}/media/{media_id}")
    assert hidden.status_code == 404
    direct = Session()
    direct.get(casting_db_models.NovaCastingMedia, media_id).status = "CLEAN"
    direct.commit()
    direct.close()
    holder["user"] = _user("organizer")
    playback = client.get(f"{base}/applications/{application_id}/media/{media_id}")
    assert playback.status_code == 200
    assert playback.json()["status"] == "CLEAN"
    assert playback.json()["playback"] == "unavailable"
    assert "storage_key" not in playback.json()
    assert "signed_url" not in playback.json()

    holder["user"] = _user("applicant")
    withdrawn = post(f"{base}/applications/{application_id}/withdraw", user="applicant")
    assert withdrawn.status_code == 200
    assert withdrawn.json()["status"] == "WITHDRAWN"
    assert post(
        f"{base}/applications/{application_id}/review",
        {"stage": "Closed", "note": "later"},
        user="organizer",
        method="PUT",
    ).status_code == 404

    holder["user"] = _user("organizer")
    audit = client.get(f"{base}/audit?limit=50")
    assert audit.status_code == 200, audit.text
    actions = [item["action"] for item in audit.json()["items"]]
    for required in (
        "campaign.created", "application.submitted", "review.updated",
        "callback.proposed", "media.quarantined", "application.withdrawn",
    ):
        assert required in actions
    assert actions.count("callback.proposed") == 1
    blob = audit.text
    assert NOTE not in blob
    assert "applicant@example.invalid" not in blob
    assert "private-quarantine" not in blob
    assert "storage_key" not in blob

    direct = Session()
    direct.get(User, "organizer").is_active = False
    direct.commit()
    holder["user"] = _user("organizer")
    assert client.get(f"{base}/audit").status_code == 404
    direct.get(User, "organizer").is_active = True
    direct.get(casting_db_models.NovaCastingMembership, "member-organizer").active = False
    direct.commit()
    assert client.get(f"{base}/campaigns").status_code == 404
    direct.get(User, "organizer").is_active = True
    direct.get(casting_db_models.NovaCastingMembership, "member-organizer").active = True
    direct.commit()
    before = direct.query(casting_db_models.NovaCastingCampaign).count()
    direct.close()

    def boom(*_args, **_kwargs):
        raise OperationalError("insert", {}, Exception("secret-sql"))

    monkeypatch.setattr(casting_db_writes, "_audit", boom)
    failed = post(
        f"{base}/campaigns",
        {"title": "Should not stick", "category": "beauty", "minimum_age": 18, "status": "DRAFT"},
        user="organizer",
    )
    assert failed.status_code == 404
    assert "secret-sql" not in failed.text
    direct = Session()
    after = direct.query(casting_db_models.NovaCastingCampaign).count()
    direct.close()
    assert after == before

    engine.dispose()
    admin = sa.create_engine(URL)
    with admin.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS casting_sandbox_ci CASCADE")
    admin.dispose()
