"""Application-level authorization for the fal pricing diagnostic.

Uses the real Creative Studio router, Nova access dependency, and login
tokens. Provider calls are intercepted in-process. No live fal request, no
credential material, and no operator allowlist addresses are printed.
"""
from __future__ import annotations

import io
import json
import os

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.creative_studio import fal_diagnostic as diagnostic
from app.core.nova.creative_studio.router import _fal_diagnostic_owner_emails
from app.main import app

DIAGNOSTIC = "/api/nova/creative/fal-first-shot-diagnostic"
GUARDRAILS = "/api/nova/creative/guardrails"
SENTINEL_KEY = "synthetic-diagnostic-key"
STUDIO_SEED_EMAILS = frozenset({
    "admin@amicor.local",
    "dispatcher@amicor.local",
    "staff@amicor.local",
    "driver@amicor.local",
    "rider@amicor.local",
    "provider@amicor.local",
})

if not os.environ.get("DATABASE_URL", "").startswith("sqlite:////tmp/"):
    raise RuntimeError("Refusing to run diagnostic auth tests without a disposable SQLite DATABASE_URL")


def _price_body() -> bytes:
    payload = {
        "prices": [{
            "endpoint_id": diagnostic.MODEL,
            "unit": "second",
            "unit_price": "0.07",
            "currency": "USD",
        }]
    }
    return json.dumps(payload).encode()


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def fal_calls(monkeypatch):
    monkeypatch.setenv("FAL_KEY", SENTINEL_KEY)
    calls: list[str] = []

    class Opener:
        def open(self, request, timeout=None):
            calls.append(request.get_method() + " " + request.full_url.split("?", 1)[0])
            if request.get_method() != "GET":
                raise AssertionError("diagnostic used a non-GET provider method")
            return io.BytesIO(_price_body())

    monkeypatch.setattr(diagnostic.urllib.request, "build_opener", lambda *args, **kwargs: Opener())
    return calls


def test_explicit_allowlist_is_exact_and_normalized(monkeypatch):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", " Owner@Example.invalid, , second@example.invalid ")
    assert _fal_diagnostic_owner_emails() == {"owner@example.invalid", "second@example.invalid"}


def test_blank_configured_allowlist_denies_everyone(monkeypatch):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", " , ")
    assert _fal_diagnostic_owner_emails() == set()


def test_unset_allowlist_does_not_add_studio_seed_accounts(monkeypatch):
    monkeypatch.delenv("NOVA_V3_OWNER_EMAILS", raising=False)
    overlap = STUDIO_SEED_EMAILS.intersection(_fal_diagnostic_owner_emails())
    assert overlap == set()


def test_whitespace_env_uses_grants_without_studio_seeds(monkeypatch):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "   ")
    owners = _fal_diagnostic_owner_emails()
    overlap = STUDIO_SEED_EMAILS.intersection(owners)
    assert overlap == set()
    assert len(owners) > 0


@pytest.mark.parametrize("email", ["dispatcher@amicor.local", "driver@amicor.local", "rider@amicor.local"])
def test_non_owner_accounts_cannot_invoke_diagnostic(client, fal_calls, monkeypatch, email):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "owner@example.invalid")
    response = client.get(DIAGNOSTIC, headers=_login(client, email))
    assert response.status_code == 403
    assert fal_calls == []
    assert SENTINEL_KEY not in response.text
    assert "owner@example.invalid" not in response.text
    assert "api.fal.ai" not in response.text


def test_anonymous_and_bad_token_never_contact_fal(client, fal_calls):
    anonymous = client.get(DIAGNOSTIC)
    bad_token = client.get(DIAGNOSTIC, headers={"Authorization": "Bearer not-a-token"})
    assert anonymous.status_code == 401
    assert bad_token.status_code == 401
    assert fal_calls == []
    assert SENTINEL_KEY not in anonymous.text + bad_token.text


def test_missing_key_still_denies_non_owner_before_provider(client, fal_calls, monkeypatch):
    monkeypatch.delenv("FAL_KEY", raising=False)
    monkeypatch.delenv("NOVA_V3_OWNER_EMAILS", raising=False)
    response = client.get(DIAGNOSTIC, headers=_login(client, "dispatcher@amicor.local"))
    assert response.status_code == 403
    assert fal_calls == []


def test_allowlisted_owner_gets_read_only_pricing_result(client, fal_calls, monkeypatch):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "Dispatcher@Amicor.local")
    response = client.get(DIAGNOSTIC, headers=_login(client, "dispatcher@amicor.local"))
    assert response.status_code == 200
    report = response.json()
    assert report["key_authenticated"] == "PRICING_API_ACCEPTED"
    assert report["price_status"] == "VERIFIED_FOR_PRICING_API"
    assert report["provider_request_submitted"] is False
    assert report["generation_enabled_by_this_check"] is False
    assert fal_calls == ["GET https://api.fal.ai/v1/models/pricing"]
    rendered = response.text
    assert SENTINEL_KEY not in rendered
    assert "dispatcher@amicor.local" not in rendered.lower()


def test_same_non_owner_keeps_general_studio_access(client, fal_calls, monkeypatch):
    monkeypatch.setenv("NOVA_V3_OWNER_EMAILS", "owner@example.invalid")
    headers = _login(client, "dispatcher@amicor.local")
    diagnostic_response = client.get(DIAGNOSTIC, headers=headers)
    guardrails_response = client.get(GUARDRAILS, headers=headers)
    assert diagnostic_response.status_code == 403
    assert guardrails_response.status_code == 200
    assert fal_calls == []
