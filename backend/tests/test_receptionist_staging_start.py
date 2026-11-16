"""Guards for free-plan receptionist staging startCommand."""

from __future__ import annotations

import os

import pytest


def test_assert_safe_database_rejects_sqlite(monkeypatch: pytest.MonkeyPatch):
    from scripts import receptionist_staging_start as start

    monkeypatch.setenv("DATABASE_URL", "sqlite:///./tmp.db")
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        start._assert_safe_database(start._database_url())


def test_assert_safe_database_rejects_490(monkeypatch: pytest.MonkeyPatch):
    from scripts import receptionist_staging_start as start

    url = "postgresql+psycopg2://u:p@127.0.0.1:5432/nova_ga_490_dispos"
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    with pytest.raises(SystemExit):
        start._assert_safe_database(url)


def test_assert_safe_database_accepts_expected_name(monkeypatch: pytest.MonkeyPatch):
    from scripts import receptionist_staging_start as start

    url = "postgresql+psycopg2://u:p@127.0.0.1:5432/nova_ga_receptionist_dispos"
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    assert start._assert_safe_database(url) == "nova_ga_receptionist_dispos"


def test_commit_guard_mismatch(monkeypatch: pytest.MonkeyPatch):
    from scripts import receptionist_staging_start as start

    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    with pytest.raises(SystemExit):
        start._assert_commit_guard()


def test_commit_guard_match_prefix(monkeypatch: pytest.MonkeyPatch):
    from scripts import receptionist_staging_start as start

    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", "d588fc5d")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "d588fc5d5bb28a8c9f9d3e509722b6d796622da5")
    start._assert_commit_guard()


def test_staging_readiness_http_200_without_google_twilio(monkeypatch: pytest.MonkeyPatch, client):
    """Missing optional OAuth/Twilio must not 503 staging traffic readiness."""
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "staging")
    monkeypatch.setenv("SECRET_KEY", "staging-secret-key-not-default-xxxxxxxx")
    monkeypatch.setenv("JWT_SECRET", "staging-jwt-secret-not-default-yyyyyyyy")
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "https://nova-receptionist-staging.onrender.com")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://nova-receptionist-staging.onrender.com")
    monkeypatch.setenv("APP_VERSION", "2026.11.16-nova-receptionist.staging")
    monkeypatch.delenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)

    # Force DB probe success without depending on live Postgres in unit path.
    monkeypatch.setattr(
        "app.db.session.check_db_connection_detail",
        lambda: {"connected": True, "detail": "ok"},
        raising=False,
    )

    from app.deployment import readiness as readiness_mod

    monkeypatch.setattr(
        readiness_mod.DeploymentReadinessChecker,
        "build_readiness_report",
        classmethod(
            lambda cls, *, db_ok=None: {
                "overall_status": "staging_only",
                "score": 80,
                "environment": {
                    "required_present": True,
                    "issues": [],
                    "warnings": [],
                    "passed": ["DATABASE_URL", "SECRET_KEY", "JWT_SECRET"],
                },
                "production_environment": {
                    "required_present": True,
                    "issues": [],
                    "passed": [],
                    "required_vars": [],
                },
                "config_checks": {
                    "production_database": {
                        "passed": True,
                        "detail": "postgresql",
                    }
                },
                "database": {"connected": True, "detail": "ok"},
                "blocked_reasons": [
                    "Set APP_VERSION before promoting to production (see STAGING_PRODUCTION_ENV_CHECKLIST.md)."
                ],
                "summary": "staging_only",
                "recommendations": [],
            }
        ),
    )

    response = client.get("/api/health/readiness")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["traffic_ready"] is True
    assert payload["http_probe"] == "staging_traffic"
    assert payload["optional_integrations_do_not_block_traffic"] is True


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.auth import ensure_auth_schema, seed_default_users
    from app.main import app

    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)
