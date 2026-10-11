"""Sandbox HTTP checks for the default-off casting read API."""
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.casting_router_draft import casting_read_session, router
from app.db.session import get_db

APPLICATION = "/api/nova/casting/organizations/org-1/applications/app-1"
CAMPAIGN = "/api/nova/casting/organizations/org-1/campaigns/camp-1"


def _app():
    app = FastAPI()
    app.include_router(router)
    return app


def _user():
    return UserContext(
        user_id="reviewer-1",
        email="reviewer@example.invalid",
        role="staff",
        organization_id="tenant-a",
    )


def _fake_db():
    yield object()


def test_importing_the_router_does_not_import_casting_models():
    models_name = "app.core.nova.creative_studio.casting_db_models"
    existing = sys.modules.get(models_name)
    sys.modules.pop(models_name, None)
    sys.modules.pop("app.core.nova.creative_studio.casting_router_draft", None)
    import app.core.nova.creative_studio.casting_router_draft as loaded
    assert loaded.router is not None
    assert models_name not in sys.modules
    if existing is not None:
        sys.modules[models_name] = existing


def test_anonymous_callers_are_rejected(monkeypatch):
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    app = _app()
    app.dependency_overrides[get_db] = _fake_db
    client = TestClient(app)
    response = client.get(APPLICATION)
    assert response.status_code == 401


def test_disabled_flag_returns_503_without_opening_a_casting_session(monkeypatch):
    monkeypatch.delenv("NOVA_CASTING_STAGING_READS", raising=False)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")

    def fail_session(*_args, **_kwargs):
        raise AssertionError("casting session opened")

    monkeypatch.setattr("app.db.session.SessionLocal", fail_session)
    app = _app()
    app.dependency_overrides[get_current_user_context] = _user
    client = TestClient(app)
    response = client.get(APPLICATION)
    assert response.status_code == 503
    assert response.json()["detail"] == "Casting application access is not enabled"
    readiness = client.get("/api/nova/casting/readiness")
    assert readiness.status_code == 200
    body = readiness.json()
    assert body["enabled"] is False
    assert body["applications_enabled"] is False
    assert body["media_uploads_enabled"] is False
    assert body["staging_reads_enabled"] is False
    assert body["sandbox_writes_enabled"] is False
    assert client.post(APPLICATION).status_code == 405
    blocked = client.post(
        "/api/nova/casting/organizations/org-1/campaigns",
        json={"title": "Draft", "category": "film", "minimum_age": 18, "status": "DRAFT"},
    )
    assert blocked.status_code == 503


def test_production_lock_ignores_the_staging_flag(monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")

    def fail_session(*_args, **_kwargs):
        raise AssertionError("casting session opened")

    monkeypatch.setattr("app.db.session.SessionLocal", fail_session)
    app = _app()
    app.dependency_overrides[get_current_user_context] = _user
    client = TestClient(app)
    assert client.get(APPLICATION).status_code == 503
    assert client.get(CAMPAIGN).status_code == 503
    assert client.get("/api/nova/casting/readiness").json()["staging_reads_enabled"] is False


def test_enabled_reads_use_the_session_identity_and_hide_storage_keys(monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENVIRONMENT", "development")
    captured = {}

    def application_read(**kwargs):
        captured.update(kwargs)
        return {
            "id": "app-1",
            "campaign_id": "camp-1",
            "status": "DRAFT",
            "created_at": "now",
            "storage_key": "private/object",
            "applicant_id": "person",
        }

    def campaign_read(**kwargs):
        return {
            "id": "camp-1",
            "title": "Draft",
            "category": "film",
            "status": "DRAFT",
            "created_at": "now",
            "minimum_age": 18,
            "owner_id": "org-1",
        }

    monkeypatch.setattr(
        "app.core.nova.creative_studio.casting_db_reads.read_casting_application_for_nova_user",
        application_read,
    )
    monkeypatch.setattr(
        "app.core.nova.creative_studio.casting_db_reads.read_casting_campaign_for_nova_user",
        campaign_read,
    )
    app = _app()
    app.dependency_overrides[get_current_user_context] = _user
    app.dependency_overrides[casting_read_session] = _fake_db
    client = TestClient(app)
    response = client.get(APPLICATION + "?user_id=attacker&tenant_id=other-tenant")
    assert response.status_code == 200
    assert response.json() == {
        "id": "app-1",
        "campaign_id": "camp-1",
        "status": "DRAFT",
        "created_at": "now",
    }
    assert captured["user_id"] == "reviewer-1"
    assert captured["tenant_id"] == "tenant-a"
    assert "attacker" not in captured.values()
    campaign = client.get(CAMPAIGN)
    assert campaign.status_code == 200
    assert "owner_id" not in campaign.json()
    readiness = client.get("/api/nova/casting/readiness").json()
    assert readiness["staging_reads_enabled"] is True
    assert readiness["sandbox_writes_enabled"] is True
    assert readiness["enabled"] is False
    assert readiness["applications_enabled"] is False
    assert readiness["media_uploads_enabled"] is False


def test_access_denial_is_not_found(monkeypatch):
    monkeypatch.setenv("NOVA_CASTING_STAGING_READS", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    from app.core.nova.creative_studio.casting_access import CastingAccessDenied

    def deny(**_kwargs):
        raise CastingAccessDenied("hidden reason")

    monkeypatch.setattr(
        "app.core.nova.creative_studio.casting_db_reads.read_casting_application_for_nova_user",
        deny,
    )
    app = _app()
    app.dependency_overrides[get_current_user_context] = _user
    app.dependency_overrides[casting_read_session] = _fake_db
    client = TestClient(app)
    response = client.get(APPLICATION)
    assert response.status_code == 404
    assert response.json()["detail"] == "Application unavailable"
    assert "hidden reason" not in response.text
