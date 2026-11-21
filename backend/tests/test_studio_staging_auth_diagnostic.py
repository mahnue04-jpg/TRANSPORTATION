"""Staging-only Studio login diagnostic.

The HTTP rejection stays generic. The reason is a server log only when
APP_ENV is staging. These cases use fixture accounts, never an owner password.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app

FIXTURE_PASSWORD = "fixture-password-not-a-secret"
SEEDED_EMAIL = "dispatcher@amicor.local"
MISSING_EMAIL = "missing-studio-user@example.test"


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _reject(client: TestClient, email: str, forwarded_for: str):
    return client.post(
        "/api/auth/login",
        json={"email": email, "password": FIXTURE_PASSWORD},
        headers={"X-Forwarded-For": forwarded_for},
    )


def _assert_generic_401(response) -> None:
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"
    body = response.text
    assert "account_not_found" not in body
    assert "password_verification_failed" not in body
    assert FIXTURE_PASSWORD not in body
    assert MISSING_EMAIL not in body


def test_staging_logs_missing_account_without_changing_401(client, monkeypatch, caplog) -> None:
    monkeypatch.setenv("APP_ENV", "staging")
    with caplog.at_level(logging.WARNING, logger="amicor.auth"):
        response = _reject(client, MISSING_EMAIL, "203.0.113.10")
    _assert_generic_401(response)
    assert FIXTURE_PASSWORD not in caplog.text
    assert MISSING_EMAIL not in caplog.text
    assert "studio_staging_auth_rejected reason=account_not_found" in caplog.text
    assert "password_verification_failed" not in caplog.text


def test_staging_logs_bad_password_for_seeded_user(client, monkeypatch, caplog) -> None:
    monkeypatch.setenv("APP_ENV", "Staging")
    with caplog.at_level(logging.WARNING, logger="amicor.auth"):
        response = _reject(client, SEEDED_EMAIL, "203.0.113.11")
    _assert_generic_401(response)
    assert FIXTURE_PASSWORD not in caplog.text
    assert SEEDED_EMAIL not in caplog.text
    assert "studio_staging_auth_rejected reason=password_verification_failed" in caplog.text


@pytest.mark.parametrize("app_env", ["production", "development", ""])
def test_non_staging_omits_auth_diagnostic(client, monkeypatch, caplog, app_env: str) -> None:
    if app_env:
        monkeypatch.setenv("APP_ENV", app_env)
    else:
        monkeypatch.delenv("APP_ENV", raising=False)
    with caplog.at_level(logging.WARNING, logger="amicor.auth"):
        response = _reject(client, MISSING_EMAIL, f"203.0.113.{20 + len(app_env)}")
    _assert_generic_401(response)
    assert "studio_staging_auth_rejected" not in caplog.text
