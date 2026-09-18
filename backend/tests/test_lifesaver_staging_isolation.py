"""Staging isolation, bootstrap safety, and public-boundary tests for Lifesaver."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app
from app.modules.lifesaver.hardware.hardware_mode import hardware_mode, prototype_panel_available
from app.modules.lifesaver.models import ensure_lifesaver_schema
from app.modules.lifesaver.staging import (
    initialize_lifesaver_schema,
    looks_like_production_database,
    refuse_alembic_heads,
)
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents

REPO = Path(__file__).resolve().parents[2]
BOOTSTRAP = REPO / "scripts" / "lifesaver_staging_bootstrap.py"
HOME_HUB_START = REPO / "hardware" / "lifesaver-home-hub" / "scripts" / "start_local.py"
FORBIDDEN_PREFIXES = ("STRIPE_", "TWILIO_", "SES_", "SENDGRID_", "SMTP_")


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _isolate(monkeypatch, **extra: str) -> None:
    monkeypatch.setenv("AMICOR_LIFESAVER_STAGING_ISOLATED", "1")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "lifesaver_staging")
    monkeypatch.setenv("JWT_SECRET", "lifesaver-staging-test-jwt")
    monkeypatch.setenv("SECRET_KEY", "lifesaver-staging-test-secret")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://amicor-lifesaver-staging.onrender.com")
    monkeypatch.setenv("AMICOR_PUBLIC_URL", "https://amicor-lifesaver-staging.onrender.com")
    monkeypatch.setenv("APP_VERSION", "lifesaver-v2-staging-test")
    monkeypatch.setenv("AMICOR_RESTRICT_SEED_ACCOUNTS", "1")
    monkeypatch.delenv("TESTING", raising=False)
    monkeypatch.delenv("LIFESAVER_SMOKE_ALLOW_PRODUCTION", raising=False)
    for key in list(os.environ):
        if key.upper().startswith(FORBIDDEN_PREFIXES):
            monkeypatch.delenv(key, raising=False)
    for key, value in extra.items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)


def test_lifesaver_ui_and_health_load_without_isolation():
    client = _client()
    page = client.get("/lifesaver")
    assert page.status_code == 200
    assert "Lifesaver AI Care Cloud" in page.text
    health = client.get("/api/lifesaver/health")
    assert health.status_code == 200
    data = health.json()["data"]
    assert data["product"] == "Healthcare Technology Lifesaver AI Care Cloud"
    assert data["version"] == "v2"
    assert data["simulated_device_mode"] is True
    assert data["home_hub_public"] is False
    assert data["stripe_enabled"] is False
    assert data["twilio_enabled"] is False
    assert data["email_sending_enabled"] is False
    assert data["emergency_services_enabled"] is False
    assert data["staging_isolated"] is False


def test_isolated_hostname_exposes_only_lifesaver_surfaces(monkeypatch):
    _isolate(monkeypatch)
    client = _client()
    page = client.get("/lifesaver")
    assert page.status_code == 200
    assert "Lifesaver AI Care Cloud" in page.text
    css = client.get("/static/lifesaver/lifesaver.css")
    assert css.status_code == 200
    health = client.get("/api/lifesaver/health")
    assert health.status_code == 200
    assert health.headers.get("x-amicor-lifesaver-staging") == "isolated"
    data = health.json()["data"]
    assert data["staging_isolated"] is True
    assert data["environment"] == "lifesaver_staging"
    assert data["hardware_mode"] == "mock"
    assert data["simulated_device_mode"] is True
    assert client.get("/", follow_redirects=False).status_code == 307
    for path in (
        "/nova",
        "/app",
        "/workspace",
        "/admin",
        "/platform-ops/driver-apply",
        "/api/payments/config",
        "/api/nova/health",
    ):
        blocked = client.get(path)
        assert blocked.status_code == 404, path
        assert "Lifesaver staging only" in blocked.text


def test_isolated_auth_and_lifesaver_routes_still_work(monkeypatch):
    _isolate(monkeypatch)
    client = _client()
    headers = auth_headers(client, "rider@amicor.local")
    grant_consents(client, headers)
    me = bootstrap_profile(client, headers)
    assert me["profile"]["id"]
    today = client.get("/api/lifesaver/today", headers=headers)
    assert today.status_code == 200
    connected = client.get("/api/lifesaver/connected-health/meta")
    assert connected.status_code == 200


def test_isolated_home_hub_agent_requires_session(monkeypatch):
    _isolate(monkeypatch)
    client = _client()
    health = client.get("/api/lifesaver/home-hub-agent/health")
    assert health.status_code == 200
    assert health.json()["data"]["simulated"] is True
    assert health.json()["data"]["emergency_services_contacted"] is False
    pair = client.post("/api/lifesaver/home-hub-agent/pair")
    assert pair.status_code == 401
    status = client.get("/api/lifesaver/home-hub-agent/status")
    assert status.status_code == 401
    headers = auth_headers(client, "rider@amicor.local")
    authed = client.get("/api/lifesaver/home-hub-agent/status", headers=headers)
    assert authed.status_code == 200


def test_mock_pi_is_hidden_on_isolated_staging(monkeypatch):
    _isolate(monkeypatch)
    client = _client()
    assert client.get("/api/lifesaver/mock-pi/health").status_code == 404
    assert client.post("/api/lifesaver/mock-pi/commands", json={"command": "GET_STATUS"}).status_code == 404


def test_isolated_staging_forces_mock_hardware(monkeypatch):
    _isolate(monkeypatch, AMICOR_LIFESAVER_HARDWARE_MODE="local_pi")
    assert hardware_mode() == "mock"
    assert prototype_panel_available() is False


def test_production_database_url_is_rejected(monkeypatch):
    production_url = "postgresql://user:pass@amicor-health-isf-db/amicor"
    assert looks_like_production_database(production_url) is True
    monkeypatch.setenv("DATABASE_URL", production_url)
    try:
        initialize_lifesaver_schema()
        raise AssertionError("production DATABASE_URL must be refused")
    except RuntimeError as exc:
        assert "production-looking" in str(exc)


def test_isolated_runtime_refuses_missing_secrets_and_production_host(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    client = _client()
    missing = client.get("/api/lifesaver/health")
    assert missing.status_code == 503
    _isolate(monkeypatch, AMICOR_PUBLIC_URL="https://amicor-health-isf-py.onrender.com")
    host = client.get("/api/lifesaver/health")
    assert host.status_code == 503
    _isolate(monkeypatch, ALLOWED_ORIGINS="*")
    cors = client.get("/api/lifesaver/health")
    assert cors.status_code == 503
    _isolate(monkeypatch, STRIPE_SECRET_KEY="sk_test_not_used")
    stripe = client.get("/api/lifesaver/health")
    assert stripe.status_code == 503


def test_bootstrap_refuses_alembic_heads_and_inits_dedicated_sqlite(tmp_path, monkeypatch):
    try:
        refuse_alembic_heads(["alembic", "upgrade", "heads"])
        raise AssertionError("alembic upgrade heads must raise")
    except RuntimeError as exc:
        assert "forbidden" in str(exc)

    db_path = tmp_path / "lifesaver_staging.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    env["AMICOR_SKIP_WMI_PLATFORM_QUERY"] = "1"
    env.pop("AMICOR_LIFESAVER_STAGING_ISOLATED", None)
    env["AMICOR_ENVIRONMENT"] = "local"
    for key in list(env):
        if key.upper().startswith(FORBIDDEN_PREFIXES):
            env.pop(key, None)
    result = subprocess.run(
        [sys.executable, str(BOOTSTRAP)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "alembic_heads=not_run" in result.stdout
    assert "health_isf_schema=not_run" in result.stdout
    assert "nova_schema=not_run" in result.stdout
    assert "lifesaver_profiles" in result.stdout
    assert "lifesaver_connected_devices" in result.stdout
    assert "platform_users" in result.stdout
    import sqlite3

    names = {
        row[0]
        for row in sqlite3.connect(db_path).execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "lifesaver_profiles" in names
    assert "platform_users" in names
    assert not any(name.startswith("health_isf") or name.startswith("nova_") for name in names)

    env["DATABASE_URL"] = "postgresql://user:pass@amicor-health-isf-db/amicor"
    refused = subprocess.run(
        [sys.executable, str(BOOTSTRAP)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refused.returncode == 2
    assert "production" in refused.stderr.lower()


def test_smoke_script_allows_lifesaver_staging_and_refuses_health_isf():
    import importlib.util

    spec = importlib.util.spec_from_file_location("lifesaver_staging_smoke", REPO / "scripts" / "lifesaver_staging_smoke.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    assert module.host_is_refused("https://amicor-lifesaver-staging.onrender.com") is False
    assert module.host_is_refused("https://amicor-health-isf-py.onrender.com") is True
    assert module.host_is_refused("https://other-app.onrender.com") is True
    assert module.host_is_refused("https://amicor-health-isf-py.onrender.com", allow_prod=True) is False


def test_home_hub_start_script_stays_private():
    source = HOME_HUB_START.read_text(encoding="utf-8")
    assert "127.0.0.1" in source
    assert "8041" in source
    assert "Refusing to start on a public host." in source
    sys.path.insert(0, str(REPO / "hardware" / "lifesaver-home-hub"))
    from lifesaver_home_hub.config import is_private_host

    assert is_private_host("127.0.0.1") is True
    assert is_private_host("8.8.8.8") is False
    assert is_private_host("amicor-lifesaver-staging.onrender.com") is False
