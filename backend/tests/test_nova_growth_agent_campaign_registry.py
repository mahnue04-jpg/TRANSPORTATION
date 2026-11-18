"""Full batch acceptance for Growth Agent's owner-reviewed campaign registry.

All data is synthetic, scoped to disposable SQLite; no real Studio assets,
marketing delivery, payments, publishing or production connections.
"""
from __future__ import annotations

from types import SimpleNamespace
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.nova.growth_agent import router as ga_router
from app.core.nova.growth_agent.tenant import require_growth_owner
from app.core.nova.growth_agent.campaign_registry import (
    CampaignReviewRegistry, CampaignRegistryDenied,
)
from app.db.session import get_db


SCHEMA = """
CREATE TABLE nova_ga_campaign_asset_reviews (
    id VARCHAR(36) PRIMARY KEY,
    organization_id VARCHAR(36) NOT NULL,
    owner_user_id VARCHAR(36) NOT NULL,
    campaign_id VARCHAR(128) NOT NULL,
    studio_project_id VARCHAR(128) NOT NULL,
    asset_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at VARCHAR(48) NOT NULL,
    updated_at VARCHAR(48) NOT NULL,
    UNIQUE (organization_id, campaign_id)
)
"""


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as con:
        con.execute(text(SCHEMA))
    with Session(engine) as db:
        yield db
    engine.dispose()


def register(repo, *, org="org-A", owner_id="owner-A",
             campaign_id="campaign-1", project_id="project-1",
             asset_id="asset-1"):
    return repo.register(
        org=org, owner_id=owner_id, campaign_id=campaign_id,
        project_id=project_id, asset_id=asset_id,
    )


def test_full_review_queue_idempotency_and_withdraw(session):
    repo = CampaignReviewRegistry(session)
    first, outcome = register(repo)
    assert outcome == "recorded"
    assert first["status"] == "verification_pending"
    assert first["studio_verified"] is False
    assert first["published"] is False
    assert first["lead_created"] is False
    second, outcome = register(repo)
    assert outcome == "duplicate" and second == first
    assert len(repo.list_for_owner(org="org-A", owner_id="owner-A")) == 1
    assert repo.list_for_owner(org="org-A", owner_id="another-owner") == []
    result, outcome = repo.withdraw(
        org="org-A", owner_id="owner-A", campaign_id="campaign-1",
    )
    assert outcome == "withdrawn" and result["status"] == "withdrawn"
    assert repo.withdraw(
        org="org-A", owner_id="owner-A", campaign_id="campaign-1",
    )[1] == "duplicate"
    with pytest.raises(CampaignRegistryDenied, match="withdrawn"):
        register(repo)


def test_campaign_tenant_isolation_and_conflict(session):
    repo = CampaignReviewRegistry(session)
    register(repo)
    register(repo, org="org-B", owner_id="owner-B")
    assert len(repo.list_for_owner(org="org-B", owner_id="owner-B")) == 1
    with pytest.raises(CampaignRegistryDenied, match="collision"):
        register(repo, asset_id="another-asset")
    with pytest.raises(CampaignRegistryDenied, match="collision"):
        register(repo, owner_id="other-owner")
    with pytest.raises(CampaignRegistryDenied):
        repo.withdraw(org="org-A", owner_id="other-owner", campaign_id="campaign-1")
    assert repo.list_for_owner(org="org-A", owner_id="owner-A")[0]["status"] == "verification_pending"


def test_persisted_review_survives_repository_restart(session):
    first = CampaignReviewRegistry(session)
    register(first)
    second = CampaignReviewRegistry(session)
    assert second.list_for_owner(org="org-A", owner_id="owner-A")[0]["campaign_id"] == "campaign-1"


def test_missing_schema_never_auto_created():
    engine = create_engine("sqlite://")
    with Session(engine) as db:
        with pytest.raises(Exception):
            register(CampaignReviewRegistry(db))
    with engine.connect() as connection:
        tables = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
        assert tables == []
    engine.dispose()


@pytest.mark.parametrize("changes", [
    dict(org="bad org"), dict(owner_id=""), dict(campaign_id="../outside"),
    dict(project_id="bad project"), dict(asset_id="bad asset"),
])
def test_bad_identifiers_denied(session, changes):
    with pytest.raises(CampaignRegistryDenied):
        register(CampaignReviewRegistry(session), **changes)


def test_review_result_never_exposes_customer_media_or_credentials(session):
    repo = CampaignReviewRegistry(session)
    register(repo)
    result = repo.list_for_owner(org="org-A", owner_id="owner-A")
    assert all(not any(key in item for key in (
        "email", "phone", "media_url", "script", "secret", "token",
    )) for item in result)


@pytest.fixture()
def http(session, monkeypatch):
    monkeypatch.setenv("NOVA_GA_CAMPAIGN_REVIEW_ENABLED", "true")
    monkeypatch.delenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED", raising=False)
    principal = SimpleNamespace(user_id="owner-A", organization_id="org-A", role="admin")

    class Profile:
        def __init__(self, db):
            self.db = db

        def get_profile(self, org):
            return dict(
                configured=True, organization_id=org,
                is_synthetic_demo=True, activated=False, agent_disabled=True,
                contact_email="private@example.invalid",
            )

    def scoped_db():
        yield session

    monkeypatch.setattr(ga_router, "GrowthAgentService", Profile)
    app.dependency_overrides[require_growth_owner] = lambda: principal
    app.dependency_overrides[get_db] = scoped_db
    try:
        yield TestClient(app), principal
    finally:
        app.dependency_overrides.clear()


def payload(**changes):
    item = dict(
        organization_id="org-A", campaign_id="campaign-1",
        studio_project_id="project-1", asset_id="asset-1",
    )
    item.update(changes)
    return item


def test_http_create_list_withdraw_end_to_end(http):
    client, principal = http
    r = client.post("/api/nova/growth-agent/campaign-assets/reviews", json=payload())
    assert r.status_code == 200, r.text
    assert r.json()["review"]["status"] == "verification_pending"
    assert r.json()["review"]["studio_verified"] is False
    assert r.headers["cache-control"] == "private, no-store"
    again = client.post("/api/nova/growth-agent/campaign-assets/reviews", json=payload())
    assert again.status_code == 200 and again.json()["outcome"] == "duplicate"
    listing = client.get("/api/nova/growth-agent/campaign-assets/reviews?organization_id=org-A")
    assert listing.status_code == 200 and len(listing.json()["reviews"]) == 1
    withdrawn = client.post(
        "/api/nova/growth-agent/campaign-assets/reviews/campaign-1/withdraw",
        json={"organization_id": "org-A"},
    )
    assert withdrawn.status_code == 200 and withdrawn.json()["outcome"] == "withdrawn"
    refused = client.post("/api/nova/growth-agent/campaign-assets/reviews", json=payload())
    assert refused.status_code == 409


def test_http_cross_tenant_role_and_extra_fields_rejected(http):
    client, principal = http
    bad_tenant = client.post(
        "/api/nova/growth-agent/campaign-assets/reviews",
        json=payload(organization_id="org-B"),
    )
    assert bad_tenant.status_code == 403
    extra = client.post(
        "/api/nova/growth-agent/campaign-assets/reviews",
        json={**payload(), "customer_email": "private@example.invalid"},
    )
    assert extra.status_code == 422
    principal.role = "staff"
    denied = client.post("/api/nova/growth-agent/campaign-assets/reviews", json=payload())
    assert denied.status_code == 403


def test_http_queue_default_off(http, monkeypatch):
    client, _ = http
    monkeypatch.delenv("NOVA_GA_CAMPAIGN_REVIEW_ENABLED", raising=False)
    refused = client.post("/api/nova/growth-agent/campaign-assets/reviews", json=payload())
    assert refused.status_code == 404


def test_http_queue_refuses_live_flag(http, monkeypatch):
    client, _ = http
    monkeypatch.setenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED", "true")
    refused = client.post("/api/nova/growth-agent/campaign-assets/reviews", json=payload())
    assert refused.status_code == 404


def test_http_missing_review_schema_is_disabled_not_server_error(monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with Session(engine) as db:
        monkeypatch.setenv("NOVA_GA_CAMPAIGN_REVIEW_ENABLED", "true")
        monkeypatch.delenv("NOVA_GROWTH_CAMPAIGN_LIVE_ENABLED", raising=False)
        principal = SimpleNamespace(user_id="owner-A", organization_id="org-A", role="admin")

        class Profile:
            def __init__(self, _db):
                pass

            def get_profile(self, org):
                return dict(
                    configured=True, organization_id=org,
                    is_synthetic_demo=True, activated=False, agent_disabled=True,
                )

        def scoped_db():
            yield db

        monkeypatch.setattr(ga_router, "GrowthAgentService", Profile)
        app.dependency_overrides[require_growth_owner] = lambda: principal
        app.dependency_overrides[get_db] = scoped_db
        try:
            client = TestClient(app)
            created = client.post(
                "/api/nova/growth-agent/campaign-assets/reviews", json=payload(),
            )
            listed = client.get(
                "/api/nova/growth-agent/campaign-assets/reviews?organization_id=org-A",
            )
            withdrawn = client.post(
                "/api/nova/growth-agent/campaign-assets/reviews/campaign-1/withdraw",
                json={"organization_id": "org-A"},
            )
        finally:
            app.dependency_overrides.clear()
    assert created.status_code == 404, created.text
    assert created.json()["detail"] == "Campaign review queue disabled"
    assert listed.status_code == 404, listed.text
    assert withdrawn.status_code == 404, withdrawn.text
    with engine.connect() as connection:
        tables = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
        assert tables == []
    engine.dispose()


def _campaign_migration():
    import importlib.util
    from pathlib import Path

    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261118_nova_ga_campaign_review.py"
    )
    spec = importlib.util.spec_from_file_location("_nova_ga_campaign_review_mig", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_campaign_upgrade(module, connection):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    module.op = Operations(MigrationContext.configure(connection))
    module.upgrade()


def test_campaign_migration_provisions_table_without_approval_flags(monkeypatch):
    for name in (
        "NOVA_GA_CAMPAIGN_SCHEMA_APPROVED",
        "NOVA_GA_CAMPAIGN_SCHEMA_STAGING_ONLY",
    ):
        monkeypatch.delenv(name, raising=False)
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        monkeypatch.setenv(name, "test")
    module = _campaign_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _run_campaign_upgrade(module, connection)
        names = set(connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).scalars())
        assert "nova_ga_campaign_asset_reviews" in names
        _run_campaign_upgrade(module, connection)
        module.downgrade()
        names = set(connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).scalars())
        assert "nova_ga_campaign_asset_reviews" in names
    engine.dispose()


def test_campaign_migration_stays_inert_in_production_even_if_flags_set(monkeypatch):
    monkeypatch.setenv("NOVA_GA_CAMPAIGN_SCHEMA_APPROVED", "true")
    monkeypatch.setenv("NOVA_GA_CAMPAIGN_SCHEMA_STAGING_ONLY", "true")
    monkeypatch.setenv("APP_ENV", "production")
    module = _campaign_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        _run_campaign_upgrade(module, connection)
        names = set(connection.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).scalars())
        assert "nova_ga_campaign_asset_reviews" not in names
    engine.dispose()
