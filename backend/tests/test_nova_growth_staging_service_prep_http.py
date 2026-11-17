"""Fail-closed HTTP coverage for owner-only staging service preparation."""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ.setdefault("TESTING", "true")

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app
from app.core.nova.growth_agent.service import GrowthAgentService


@pytest.fixture()
def client():
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _auth(client):
    res = client.post(
        "/api/auth/login",
        json={"email": "admin@amicor.local", "password": SEED_PASSWORD},
    )
    assert res.status_code == 200, res.text
    token = res.json().get("access_token") or res.json().get("token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def _enable(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_DEMO_MODE", "true")
    monkeypatch.setenv("NOVA_GA_STAGING_SERVICE_PREP_ENABLED", "true")
    monkeypatch.setenv("NOVA_GA_EXPECTED_DATABASE_NAME", "nova_ga_receptionist_dispos")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-dbtka2ei0phs73dk80dg")


def test_disabled_by_default(client, monkeypatch):
    _enable(monkeypatch)
    monkeypatch.delenv("NOVA_GA_STAGING_SERVICE_PREP_ENABLED")
    response = client.post(
        "/api/nova/growth-agent/staging/prepare-service",
        headers=_auth(client), json={"service_code": "consult"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("key,value", [
    ("NOVA_GA_EXPECTED_DATABASE_NAME", "production"),
    ("RENDER_SERVICE_ID", "srv-unrelated"),
    ("NOVA_GROWTH_AGENT_DEMO_MODE", "false"),
])
def test_refuses_other_environment(client, monkeypatch, key, value):
    _enable(monkeypatch)
    monkeypatch.setenv(key, value)
    response = client.post(
        "/api/nova/growth-agent/staging/prepare-service",
        headers=_auth(client), json={"service_code": "consult"},
    )
    assert response.status_code == 404


def test_anonymous_denied(client, monkeypatch):
    _enable(monkeypatch)
    response = client.post(
        "/api/nova/growth-agent/staging/prepare-service",
        json={"service_code": "consult"},
    )
    assert response.status_code in (401, 403)


def test_owner_uses_org_scoped_service_without_external_calls(client, monkeypatch):
    _enable(monkeypatch)
    calls = []
    def fake_prepare(self, org_id, *, service_code, actor_user_id):
        calls.append((org_id, service_code, actor_user_id))
        return {"staging_only": True, "service_code": service_code}
    monkeypatch.setattr(GrowthAgentService, "prepare_staging_appointment_service", fake_prepare)
    response = client.post(
        "/api/nova/growth-agent/staging/prepare-service",
        headers=_auth(client), json={"service_code": "consult"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["staging_only"] is True
    assert len(calls) == 1
    assert calls[0][1] == "consult"
    assert all(calls[0][i] for i in (0, 2))
