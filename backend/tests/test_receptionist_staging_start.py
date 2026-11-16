"""Guards for free-plan receptionist staging startCommand."""

from __future__ import annotations

import pytest

FULL_A = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
FULL_B = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
APPROVED_URL = "postgresql+psycopg2://u:p@127.0.0.1:5432/nova_ga_receptionist_dispos"
APPROVED_URL_ALT_SCHEME = "postgresql://u:p@127.0.0.1:5432/nova_ga_receptionist_dispos"
STAGING_490 = "postgresql+psycopg2://u:p@127.0.0.1:5432/nova_ga_490_dispos"


def _import_start():
    from scripts import receptionist_staging_start as start

    return start


def test_commit_guard_requires_expected(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.delenv("NOVA_GA_EXPECTED_GIT_COMMIT", raising=False)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_A)
    with pytest.raises(SystemExit):
        start._assert_commit_guard()


def test_commit_guard_rejects_abbreviated_expected(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", "b48ec239")
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_A)
    with pytest.raises(SystemExit):
        start._assert_commit_guard()


def test_commit_guard_rejects_abbreviated_actual_prefix_trick(monkeypatch: pytest.MonkeyPatch):
    """RENDER_GIT_COMMIT='b' must not match expected starting with 'b'."""
    start = _import_start()
    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", FULL_B)
    monkeypatch.setenv("RENDER_GIT_COMMIT", "b")
    with pytest.raises(SystemExit):
        start._assert_commit_guard()


def test_commit_guard_rejects_malformed_non_hex(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", "z" * 40)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_A)
    with pytest.raises(SystemExit):
        start._assert_commit_guard()


def test_commit_guard_rejects_mismatch(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", FULL_A)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_B)
    with pytest.raises(SystemExit):
        start._assert_commit_guard()


def test_commit_guard_accepts_exact_full_match(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", FULL_A)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_A)
    start._assert_commit_guard()


def test_commit_guard_accepts_git_commit_alias(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", FULL_A)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    monkeypatch.setenv("GIT_COMMIT", FULL_A)
    start._assert_commit_guard()


def test_conflicting_database_urls_rejected(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("DATABASE_URL", STAGING_490)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    with pytest.raises(SystemExit) as exc:
        start.resolve_approved_database_url()
    assert exc.value.code == 1


def test_equivalent_schemes_accepted_and_unified(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("DATABASE_URL", APPROVED_URL_ALT_SCHEME)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_HOST", "127.0.0.1")
    url, dest = start.resolve_approved_database_url()
    assert dest["database"] == "nova_ga_receptionist_dispos"
    assert dest["host"] == "127.0.0.1"
    assert dest["identity"] == "postgresql://127.0.0.1:5432/nova_ga_receptionist_dispos"
    # App + Alembic both receive the approved DATABASE_URL preference.
    assert start._env("DATABASE_URL") == APPROVED_URL_ALT_SCHEME
    assert start._env("ALEMBIC_DATABASE_URL") == APPROVED_URL_ALT_SCHEME
    assert url == APPROVED_URL_ALT_SCHEME


def test_rejects_sqlite(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./tmp.db")
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        start.resolve_approved_database_url()


def test_rejects_protected_490(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("DATABASE_URL", STAGING_490)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    with pytest.raises(SystemExit):
        start.resolve_approved_database_url()


def test_rejects_production_host(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://u:p@amicor-health-isf-db.oregon-postgres.render.com:5432/nova_ga_receptionist_dispos",
    )
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    with pytest.raises(SystemExit):
        start.resolve_approved_database_url()


def test_expected_host_mismatch_rejected(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    monkeypatch.setenv("DATABASE_URL", APPROVED_URL)
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_HOST", "db.example.internal")
    with pytest.raises(SystemExit):
        start.resolve_approved_database_url()


def test_migrate_only_fails_before_db_on_bad_commit(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    calls: list[str] = []

    def boom(*_a, **_k):
        calls.append("connect")
        raise AssertionError("psycopg2.connect must not run")

    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", "b")  # abbreviated
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_B)
    monkeypatch.setenv("DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    monkeypatch.setattr(start, "_with_advisory_lock", lambda *_a, **_k: calls.append("lock"))
    monkeypatch.setitem(__import__("sys").modules, "psycopg2", type("M", (), {"connect": staticmethod(boom)})())

    with pytest.raises(SystemExit):
        start.migrate_only()
    assert calls == []


def test_migrate_only_fails_before_db_on_url_conflict(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    calls: list[str] = []

    def fake_lock(*_a, **_k):
        calls.append("lock")
        raise AssertionError("lock must not run")

    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", FULL_A)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_A)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("DATABASE_URL", STAGING_490)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    monkeypatch.setattr(start, "_with_advisory_lock", fake_lock)

    with pytest.raises(SystemExit):
        start.migrate_only()
    assert calls == []


def test_migrate_only_propagates_unified_url_before_lock(monkeypatch: pytest.MonkeyPatch):
    start = _import_start()
    seen: dict[str, str] = {}

    def fake_lock(url, fn):
        seen["lock_url"] = url
        seen["DATABASE_URL"] = start._env("DATABASE_URL")
        seen["ALEMBIC_DATABASE_URL"] = start._env("ALEMBIC_DATABASE_URL")
        # Do not invoke fn (would run alembic).

    monkeypatch.setenv("NOVA_GA_EXPECTED_GIT_COMMIT", FULL_A)
    monkeypatch.setenv("RENDER_GIT_COMMIT", FULL_A)
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", APPROVED_URL)
    monkeypatch.setenv("DATABASE_URL", APPROVED_URL_ALT_SCHEME)
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_HOST", "127.0.0.1")
    monkeypatch.setattr(start, "_with_advisory_lock", fake_lock)

    start.migrate_only()
    assert seen["lock_url"] == APPROVED_URL_ALT_SCHEME
    assert seen["DATABASE_URL"] == APPROVED_URL_ALT_SCHEME
    assert seen["ALEMBIC_DATABASE_URL"] == APPROVED_URL_ALT_SCHEME


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
                "blocked_reasons": [],
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


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.auth import ensure_auth_schema, seed_default_users
    from app.main import app

    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)
