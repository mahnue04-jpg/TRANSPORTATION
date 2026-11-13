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


def test_synthetic_demo_requires_demo_mode(monkeypatch: pytest.MonkeyPatch, client: TestClient) -> None:
    from app.core.nova.growth_agent import flags as ga_flags

    monkeypatch.setattr(ga_flags, "demo_mode_enabled", lambda: False)
    headers = _headers(client)
    res = client.post("/api/nova/growth-agent/demo/synthetic", headers=headers, json={})
    assert res.status_code == 404
    assert "demo" in str(res.json().get("detail", "")).lower()


def test_http_journey_smoke_authenticated(client: TestClient) -> None:
    headers = _headers(client)
    profile = client.post(
        "/api/nova/growth-agent/profile",
        headers=headers,
        json={
            "business_name": "HTTP Journey Biz",
            "website": "https://journey.example",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [{"code": "consult", "name": "Consult", "duration_minutes": 30}],
            "faqs": [
                {
                    "id": "faq_hours",
                    "question": "Hours?",
                    "keywords": ["hours"],
                    "answer": "Mon–Fri 9–5.",
                }
            ],
            "contact_email": "owner@journey.example",
            "handoff_phone": "+15555550111",
            "escalation_settings": {"handoff_on_unknown": True},
            "activate": True,
        },
    )
    assert profile.status_code == 200, profile.text
    widget = client.post(
        "/api/nova/growth-agent/widget/installations",
        headers=headers,
        json={"domain": "journey.example"},
    )
    assert widget.status_code == 200, widget.text
    token = widget.json()["token"]
    chat = client.post(
        "/api/nova/growth-agent/widget/chat",
        headers={**headers, "Origin": "https://journey.example"},
        json={
            "token": token,
            "message": "What are your hours?",
            "visitor_name": "Pat Journey",
            "visitor_email": "pat.journey@example.com",
            "consent_transactional": True,
            "consent_marketing": True,
        },
    )
    assert chat.status_code == 200, chat.text
    body = chat.json()
    assert body["grounded"] is True
    contact_id = body["contact_id"]
    assert contact_id
    lead = client.patch(
        f"/api/nova/growth-agent/leads/{contact_id}",
        headers=headers,
        json={"lead_state": "contacted", "notes": "HTTP journey"},
    )
    assert lead.status_code == 200, lead.text
    analytics = client.get("/api/nova/growth-agent/analytics?days=30", headers=headers)
    assert analytics.status_code == 200
    assert analytics.json()["inquiries"] >= 1
    health = client.get("/api/nova/growth-agent/health", headers=headers)
    assert health.status_code == 200
    assert health.json()["live_flags"]["sms"] is False


def test_workflow_review_queue_requires_authentication(client: TestClient) -> None:
    """Workflow previews must never become a public endpoint."""
    response = client.get("/api/nova/growth-agent/workflows/review-queue")
    assert response.status_code in {401, 403}


def test_workflow_review_queue_owner_reads_only_own_tenant(client: TestClient) -> None:
    """A regular tenant user cannot request another organization's review queue."""
    headers = _headers(client)
    own = client.get("/api/nova/growth-agent/workflows/review-queue?limit=2", headers=headers)
    assert own.status_code == 200, own.text
    assert isinstance(own.json().get("items"), list)

    other = client.get(
        "/api/nova/growth-agent/workflows/review-queue?organization_id=other-tenant-unknown",
        headers=headers,
    )
    assert other.status_code == 403, other.text


def test_workflow_review_queue_limit_is_validated(client: TestClient) -> None:
    headers = _headers(client)
    response = client.get("/api/nova/growth-agent/workflows/review-queue?limit=101", headers=headers)
    assert response.status_code == 422
