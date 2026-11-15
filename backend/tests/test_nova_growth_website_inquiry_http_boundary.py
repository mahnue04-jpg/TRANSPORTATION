"""Authenticated HTTP boundary tests; injected synthetic KV fixture only."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app
from app.core.nova.growth_agent.router import website_inquiry_source_factory

PATH = "/api/nova/growth-agent/website-inquiries/read-only"
KEY = "lead:AMQ-AB12CD34"
RECORD = {
    "receivedAt": "2026-11-14T21:00:00Z",
    "name": "Synthetic Fixture",
    "company": "Fictional Company",
    "email": "qa@example.invalid",
    "message": "INTERNAL TEST ONLY",
    "consent": True,
}


class Fixture:
    def __init__(self):
        self.reads = 0

    def list_keys(self, *, prefix, cursor):
        self.reads += 1
        assert prefix == "lead:" and cursor is None
        return {"list_complete": True, "keys": [{"name": KEY}]}

    def get_text(self, key):
        assert key == KEY
        return json.dumps(RECORD)


def _login(client, email):
    res = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": "Bearer " + res.json()["access_token"]}


def test_default_no_source_fails_closed_without_claiming_empty(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)
    result = client.get(PATH, headers=_login(client, "admin@amicor.local"))
    assert result.status_code == 503
    assert result.json() == {"detail": "website_inquiry_source_unavailable"}


def test_authenticated_owner_can_read_only_tenant_fixture(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    ensure_auth_schema()
    seed_default_users()
    fixture = Fixture()
    selected = []
    def source_for_tenant(org):
        selected.append(org)
        return fixture
    app.dependency_overrides[website_inquiry_source_factory] = lambda: source_for_tenant
    try:
        client = TestClient(app)
        headers = _login(client, "admin@amicor.local")
        response = client.get(PATH, headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["count"] == 1
        assert body["read_only"] is True
        assert body["inquiries"][0]["is_synthetic"] is False
        assert selected == [body["organization_id"]]
        assert fixture.reads == 1
    finally:
        app.dependency_overrides.pop(website_inquiry_source_factory, None)


def test_unauthenticated_dispatcher_and_cross_tenant_denied_without_source_read(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    ensure_auth_schema()
    seed_default_users()
    attempted = []
    def forbidden_source(org):
        attempted.append(org)
        raise AssertionError("Never open source for denied request")
    app.dependency_overrides[website_inquiry_source_factory] = lambda: forbidden_source
    try:
        client = TestClient(app)
        assert client.get(PATH).status_code in (401, 403)
        dispatcher = _login(client, "dispatcher@amicor.local")
        assert client.get(PATH, headers=dispatcher).status_code == 403
        owner = _login(client, "admin@amicor.local")
        foreign = client.get(PATH + "?organization_id=foreign-tenant", headers=owner)
        assert foreign.status_code == 403
        assert attempted == []
    finally:
        app.dependency_overrides.pop(website_inquiry_source_factory, None)


def test_disabled_growth_flag_denies_inquiry_http(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "false")
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)
    result = client.get(PATH, headers=_login(client, "admin@amicor.local"))
    assert result.status_code == 404
