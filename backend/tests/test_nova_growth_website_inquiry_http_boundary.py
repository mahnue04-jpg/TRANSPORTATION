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


def test_public_website_legacy_record_flows_to_owner_review_without_writes(monkeypatch):
    """Simulate Cloudflare's existing website writer format through HTTP owner read."""
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    ensure_auth_schema()
    seed_default_users()
    legacy_key = "lead:2026-11-15T06:00:00.000Z:12345678-1234-4234-8234-123456789abc"
    public_form_payload = {
        "receivedAt": "2026-11-15T06:00:00.000Z",
        "name": "Sample Customer",
        "company": "Example Business",
        "email": "buyer@example.invalid",
        "phone": "",
        "industry": "Professional Services",
        "companySize": "1-10",
        "product": "Nova Operations Agent",
        "message": "Please prepare a service quote",
        "consent": True,
        "source": "amicor-public-website-w8",
    }

    class CapturedPublicKV:
        def __init__(self):
            self.writes = 0
            self.list_calls = 0

        def list_keys(self, *, prefix, cursor):
            self.list_calls += 1
            assert (prefix, cursor) == ("lead:", None)
            return {"keys": [{"name": legacy_key}], "list_complete": True}

        def get_text(self, key):
            assert key == legacy_key
            return json.dumps(public_form_payload)

        def put(self, *args, **kwargs):
            self.writes += 1
            raise AssertionError("Read-only route must never write to KV")

    store = CapturedPublicKV()
    app.dependency_overrides[website_inquiry_source_factory] = lambda: lambda org: store
    try:
        client = TestClient(app)
        owner = _login(client, "admin@amicor.local")
        response = client.get(PATH, headers=owner)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["count"] == 1
        inquiry = payload["inquiries"][0]
        assert inquiry["source_key"] == legacy_key
        assert inquiry["company"] == "Example Business"
        assert inquiry["product"] == "Nova Operations Agent"
        assert inquiry["status"] == "needs_owner_review"
        assert inquiry["is_synthetic"] is False
        assert store.writes == 0
        assert store.list_calls == 1
        denied = client.get(PATH + "?organization_id=other-tenant", headers=owner)
        assert denied.status_code == 403
        assert store.list_calls == 1
    finally:
        app.dependency_overrides.pop(website_inquiry_source_factory, None)
