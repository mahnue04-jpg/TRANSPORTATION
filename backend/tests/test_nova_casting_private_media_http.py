"""Disposable upload, scan, and private playback. Public hosting stays closed."""
import os
import stat
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.casting_router_draft import router

URL = os.getenv("CASTING_TEST_POSTGRES_URL")
ORG = "media-org"
BACKEND_STATIC = Path(__file__).resolve().parents[1] / "static"
MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isomavc1"
EICAR = MP4 + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"
JPEG = b"\xff\xd8\xff\x00fake"


def _enable(monkeypatch, name="disposable"):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    for key in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(key, name)


def _user(user_id, tenant="tenant-a"):
    return UserContext(user_id=user_id, email=f"{user_id}@example.invalid", role="staff", organization_id=tenant)


def test_private_upload_does_not_open_when_the_sandbox_is_locked(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVA_CASTING_PRIVATE_MEDIA_DIR", str(tmp_path))

    def fail_session(*_args, **_kwargs):
        raise AssertionError("casting session opened")

    monkeypatch.setattr("app.db.session.SessionLocal", fail_session)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: _user("applicant")
    client = TestClient(app)
    target = f"/api/nova/casting/organizations/{ORG}/applications/app-1/media/file"
    files = {"file": ("audition.mp4", MP4, "video/mp4")}
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    _enable(monkeypatch)
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    assert client.post(target, files=files, data={"mime_type": "video/mp4"}).status_code == 503
    _enable(monkeypatch, "production")
    assert client.post(target, files=files, data={"mime_type": "video/mp4"}).status_code == 503
    assert list(tmp_path.iterdir()) == []


@pytest.mark.skipif(not URL, reason="Disposable PostgreSQL unavailable")
def test_scanned_video_plays_only_for_an_authorized_caller(monkeypatch, tmp_path):
    _enable(monkeypatch)
    monkeypatch.setenv("NOVA_CASTING_PRIVATE_MEDIA_DIR", str(tmp_path))
    from app.db.session import Base
    from app.db.models import User
    from app.core.nova.creative_studio import casting_db_models

    admin = sa.create_engine(URL)
    with admin.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS casting_media_ci CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA casting_media_ci")
    admin.dispose()
    engine = sa.create_engine(URL, connect_args={"options": "-csearch_path=casting_media_ci"})
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
        User(id="applicant", email="applicant@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-a", is_active=True, is_verified=True),
        User(id="stranger", email="stranger@example.invalid", hashed_password="not-a-login",
             role="staff", organization_id="tenant-a", is_active=True, is_verified=True),
        casting_db_models.NovaCastingOrganization(
            id=ORG, nova_tenant_id="tenant-a", name="Media company",
            verification_status="VERIFIED", created_at="seed",
        ),
    ])
    seed.flush()
    seed.add(casting_db_models.NovaCastingMembership(
        id="member-organizer", nova_tenant_id="tenant-a", organization_id=ORG,
        user_id="organizer", casting_role="organizer", active=True, created_at="seed",
    ))
    seed.commit()
    seed.close()

    holder = {"user": _user("organizer")}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_context] = lambda: holder["user"]
    client = TestClient(app)
    base = f"/api/nova/casting/organizations/{ORG}"

    def call(path, user="applicant", **kwargs):
        holder["user"] = _user(user)
        return client.request(kwargs.pop("method", "POST"), path, **kwargs)

    created = call(
        f"{base}/campaigns",
        user="organizer",
        json={"title": "Private playback", "category": "film", "minimum_age": 18, "status": "DRAFT"},
    )
    assert created.status_code == 200, created.text
    campaign_id = created.json()["id"]
    saved = call(
        f"{base}/campaigns/{campaign_id}/applications",
        json={"consent_accepted": True, "consent_version": "sandbox-v1", "age_years": 24},
    )
    assert saved.status_code == 200, saved.text
    application_id = saved.json()["id"]
    assert call(f"{base}/applications/{application_id}/submit").status_code == 200

    metadata = call(
        f"{base}/applications/{application_id}/media",
        json={"mime_type": "video/mp4", "byte_size": 2048},
    )
    assert metadata.status_code == 200
    assert metadata.json()["playback"] == "unavailable"
    metadata_id = metadata.json()["id"]
    holder["user"] = _user("applicant")
    assert client.get(f"{base}/applications/{application_id}/media/{metadata_id}/content").status_code == 404
    direct = Session()
    direct.get(casting_db_models.NovaCastingMedia, metadata_id).status = "CLEAN"
    direct.commit()
    direct.close()
    holder["user"] = _user("applicant")
    status = client.get(f"{base}/applications/{application_id}/media/{metadata_id}")
    assert status.status_code == 200
    assert status.json()["playback"] == "unavailable"
    assert "storage_key" not in status.json()
    assert client.get(f"{base}/applications/{application_id}/media/{metadata_id}/content").status_code == 404

    rejected_type = call(
        f"{base}/applications/{application_id}/media/file",
        files={"file": ("photo.jpg", JPEG, "video/mp4")},
        data={"mime_type": "video/mp4"},
    )
    assert rejected_type.status_code == 422
    assert list(tmp_path.iterdir()) == []

    hostile = call(
        f"{base}/applications/{application_id}/media/file",
        files={"file": ("bad.mp4", EICAR, "video/mp4")},
        data={"mime_type": "video/mp4"},
    )
    assert hostile.status_code == 200, hostile.text
    assert hostile.json()["status"] == "REJECTED"
    assert hostile.json()["playback"] == "unavailable"
    assert "storage_key" not in hostile.json()
    assert "signed_url" not in hostile.json()
    assert list(tmp_path.iterdir()) == []

    uploaded = call(
        f"{base}/applications/{application_id}/media/file",
        files={"file": ("audition.mp4", MP4, "video/mp4")},
        data={"mime_type": "video/mp4"},
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["status"] == "CLEAN"
    assert body["playback"] == "private"
    assert body["scan_engine"] in {"structural", "clamscan"}
    assert "storage_key" not in body
    assert "signed_url" not in body
    media_id = body["id"]
    stored = list(tmp_path.iterdir())
    assert len(stored) == 1
    assert stored[0].name == media_id
    assert stat.S_IMODE(stored[0].stat().st_mode) == 0o600
    assert BACKEND_STATIC.resolve() not in stored[0].resolve().parents
    holder["user"] = _user("applicant")
    played = client.get(f"{base}/applications/{application_id}/media/{media_id}/content")
    assert played.status_code == 200
    assert played.content == MP4
    assert played.headers["cache-control"] == "private, no-store"
    assert played.headers["x-content-type-options"] == "nosniff"
    assert "storage_key" not in played.headers
    assert media_id not in played.headers.get("content-disposition", "")
    holder["user"] = _user("organizer")
    organizer_play = client.get(f"{base}/applications/{application_id}/media/{media_id}/content")
    assert organizer_play.status_code == 200
    assert organizer_play.content == MP4
    holder["user"] = _user("stranger")
    assert client.get(f"{base}/applications/{application_id}/media/{media_id}/content").status_code == 404
    blocked = call(
        f"{base}/applications/{application_id}/media/file",
        user="organizer",
        files={"file": ("other.mp4", MP4, "video/mp4")},
        data={"mime_type": "video/mp4"},
    )
    assert blocked.status_code == 404
    assert len(list(tmp_path.iterdir())) == 1

    holder["user"] = _user("organizer")
    audit = client.get(f"{base}/audit?limit=50")
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["items"]]
    assert "media.approved" in actions
    assert "private-quarantine" not in audit.text
    assert "EICAR-STANDARD-ANTIVIRUS-TEST-FILE" not in audit.text
    assert str(tmp_path) not in audit.text
    assert "storage_key" not in audit.text

    assert call(f"{base}/applications/{application_id}/withdraw").status_code == 200
    after = call(
        f"{base}/applications/{application_id}/media/file",
        files={"file": ("later.mp4", MP4, "video/mp4")},
        data={"mime_type": "video/mp4"},
    )
    assert after.status_code == 404
    assert len(list(tmp_path.iterdir())) == 1
