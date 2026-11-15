"""Security smoke for website-inquiry synthetic preview (no production KV)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = response.json().get("access_token") or response.json().get("token")
    return {"Authorization": "Bearer " + token}


def test_website_inquiry_preview_requires_owner(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    monkeypatch.setenv("NOVA_GROWTH_AGENT_DEMO_MODE", "true")
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)
    path = "/api/nova/growth-agent/website-inquiries/preview"
    assert client.get(path).status_code in (401, 403)
    assert client.get(path, headers=_login(client, "dispatcher@amicor.local")).status_code == 403
    owner_headers = _login(client, "admin@amicor.local")
    denied = client.get(path + "?organization_id=foreign-tenant", headers=owner_headers)
    assert denied.status_code == 403
    allowed = client.get(path, headers=owner_headers)
    assert allowed.status_code == 200, allowed.text
    body = allowed.json()
    assert body["status"] == "synthetic_preview"
    assert body["production_kv_connected"] is False
    assert body["external_actions_performed"] is False
    assert body["count"] == 1
    assert all(record["is_synthetic"] for record in body["inquiries"])


def test_website_inquiry_preview_disabled_by_default(monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "true")
    monkeypatch.setenv("NOVA_GROWTH_AGENT_DEMO_MODE", "false")
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)
    path = "/api/nova/growth-agent/website-inquiries/preview"
    result = client.get(path, headers=_login(client, "admin@amicor.local"))
    assert result.status_code == 200
    assert result.json()["status"] == "unavailable"
    assert result.json()["inquiries"] is None
    assert result.json()["production_kv_connected"] is False
