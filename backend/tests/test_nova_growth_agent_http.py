"""HTTP smoke: page route, flag gate, authenticated synthetic demo path."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_DEMO_MODE"] = "true"
os.environ["NOVA_GROWTH_AGENT_WIDGET_ENABLED"] = "true"
os.environ.setdefault("TESTING", "true")

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    token = res.json().get("access_token") or res.json().get("token")
    assert token
    return {"Authorization": f"Bearer {token}"}


def test_growth_page_served(client: TestClient) -> None:
    res = client.get("/nova/growth")
    assert res.status_code == 200
    assert "Growth Agent" in res.text
    assert "Synthetic" in res.text or "synthetic" in res.text.lower()


def test_flags_and_plans_authenticated(client: TestClient) -> None:
    headers = _headers(client)
    flags = client.get("/api/nova/growth-agent/flags", headers=headers)
    assert flags.status_code == 200
    body = flags.json()["flags"]
    assert body["REAL_SMS_SEND"] is False
    assert body["GROWTH_AGENT_ENABLED"] is True
    plans = client.get("/api/nova/growth-agent/plans", headers=headers)
    assert plans.status_code == 200
    assert plans.json()["subscriptions_enabled"] is False


def test_unauthenticated_api_rejected(client: TestClient) -> None:
    res = client.get("/api/nova/growth-agent/leads")
    assert res.status_code in {401, 403}


def test_disabled_flag_returns_404(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("NOVA_GROWTH_AGENT_ENABLED", "false")
    # flags module reads env at call time for growth_agent_enabled
    from app.core.nova.growth_agent import flags as ga_flags

    monkeypatch.setattr(ga_flags, "growth_agent_enabled", lambda: False)
    headers = _headers(client)
    res = client.get("/api/nova/growth-agent/health", headers=headers)
    assert res.status_code == 404


def test_widget_chat_requires_widget_flag(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    monkeypatch.setenv("NOVA_GROWTH_AGENT_WIDGET_ENABLED", "false")
    res = client.post(
        "/api/nova/growth-agent/widget/chat",
        json={"token": "not-a-real-token", "message": "hi"},
    )
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert "widget" in (detail if isinstance(detail, str) else str(detail)).lower()
