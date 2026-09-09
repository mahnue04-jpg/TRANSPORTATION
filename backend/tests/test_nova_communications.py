"""Nova Core Phase 3: Communications Hub. Does not send mail or touch Health /workspace."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
COMMS_HTML = (STATIC / "nova-communications" / "index.html").read_text(encoding="utf-8")
COMMS_JS = (STATIC / "nova-communications" / "communications.js").read_text(encoding="utf-8")
COMMS_CSS = (STATIC / "nova-communications" / "communications.css").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
WS_HTML = (STATIC / "nova-workspace" / "index.html").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
HEALTH_HTML = (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


def _counts() -> dict[str, int]:
    from app.core.nova.freight.models import NovaFreightShipment
    from app.modules.health_isf.models import HealthISFRide
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    with SessionLocal() as db:
        return {
            "freight": db.query(NovaFreightShipment).count(),
            "health_rides": db.query(HealthISFRide).count(),
            "driver_apps": db.query(PlatformDriverOnboardingApplication).count(),
            "driver_001": db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .count(),
        }


def test_nova_communications_route_loads(client: TestClient) -> None:
    response = client.get("/nova/communications")
    assert response.status_code == 200
    assert "Communications" in response.text
    assert "Mrs. Nova Brain" in response.text
    assert "ops-shell.js" not in response.text
    assert 'src="/static/nova-communications/communications.js"' in response.text
    assert "Health ISF Workspace" not in response.text


def test_nova_communications_signed_out_blocks_apis(client: TestClient) -> None:
    assert client.get("/api/nova/communications/dashboard").status_code == 401
    assert client.post(
        "/api/nova/communications/drafts",
        json={"subject": "Nope", "body": "blocked"},
    ).status_code == 401


def test_nova_communications_dashboard_and_brain(client: TestClient) -> None:
    headers = _headers(client)
    dash = client.get("/api/nova/communications/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["send_enabled"] is False
    assert "inbox" in body and "drafts" in body and "notifications" in body
    asked = client.post(
        "/api/nova/communications/ask",
        headers=headers,
        json={"action": "summarize_recent", "question": "Summarize my communications."},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"]
    assert "Mrs. Nova Brain" in COMMS_HTML


def test_nova_communications_email_list_read_and_draft_no_send(client: TestClient) -> None:
    headers = _headers(client)
    created = client.post(
        "/api/nova/communications/messages",
        headers=headers,
        json={
            "sender": "alex@example.com",
            "subject": "Need a decision",
            "body": "Please review the Nova brief.",
            "important": True,
        },
    )
    assert created.status_code == 200, created.text
    message_id = created.json()["message_id"]
    listed = client.get("/api/nova/communications/messages", headers=headers)
    assert any(row["message_id"] == message_id for row in listed.json())
    detail = client.get(f"/api/nova/communications/messages/{message_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["read"] is True
    assert detail.json()["body"]

    draft = client.post(
        "/api/nova/communications/drafts",
        headers=headers,
        json={"to": ["alex@example.com"], "subject": "Re: Need a decision", "body": "Draft only"},
    )
    assert draft.status_code == 200
    assert draft.json()["status"] == "draft"
    drafts = client.get("/api/nova/communications/drafts", headers=headers)
    assert any(row["subject"] == "Re: Need a decision" for row in drafts.json())

    blocked = client.post(
        "/api/nova/communications/send",
        headers=headers,
        json={"confirm_send": True, "to": ["alex@example.com"], "subject": "Must not send", "body": "nope"},
    )
    assert blocked.status_code == 403
    unconfirmed = client.post(
        "/api/nova/communications/send",
        headers=headers,
        json={"confirm_send": False, "to": ["alex@example.com"], "subject": "Must not send", "body": "nope"},
    )
    assert unconfirmed.status_code == 400
    assert "smtp" not in COMMS_JS.lower()
    assert "/api/email/send" not in COMMS_JS


def test_nova_communications_calendar_and_contacts(client: TestClient) -> None:
    headers = _headers(client)
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    end = start + timedelta(hours=1)
    created = client.post(
        "/api/nova/communications/events",
        headers=headers,
        json={
            "title": "Nova stand-up",
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "location": "https://meet.example.com/nova",
            "attendees": ["jordan@example.com"],
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["provider"] == "local"
    assert created.json()["location"] == "https://meet.example.com/nova"
    events = client.get("/api/nova/communications/events", headers=headers)
    assert any(row["title"] == "Nova stand-up" for row in events.json())
    contacts = client.get("/api/nova/communications/contacts", headers=headers, params={"q": "jordan"})
    assert contacts.status_code == 200
    assert any("jordan@example.com" in (row.get("email") or "") for row in contacts.json())


def test_nova_communications_notifications_and_isolation(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = client.post(
        "/api/nova/communications/messages",
        headers=owner,
        json={"sender": "private@example.com", "subject": "Dispatcher only note", "body": "secret"},
    )
    assert created.status_code == 200
    message_id = created.json()["message_id"]
    hidden = client.get(f"/api/nova/communications/messages/{message_id}", headers=other)
    assert hidden.status_code == 404
    notices = client.get("/api/nova/communications/notifications", headers=owner)
    assert notices.status_code == 200
    assert any("Dispatcher only note" in row["title"] for row in notices.json())
    cross = client.get(
        "/api/nova/communications/dashboard",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403


def test_nova_communications_navigation_and_responsive() -> None:
    assert 'href="/nova/communications" data-destination="communications"' in HOME_HTML
    assert 'href="/nova/communications">Communications' in WS_HTML
    assert 'href="/nova">Nova Home' in COMMS_HTML
    assert 'href="/nova/workspace">Nova Workspace' in COMMS_HTML
    assert 'href="/nova/government">Government' in COMMS_HTML
    assert 'href="/workspace">Health' in COMMS_HTML
    assert 'href="/app">Delivery' in COMMS_HTML
    assert 'href="/nova/freight">Freight' in COMMS_HTML
    assert 'name="viewport"' in COMMS_HTML
    assert "@media (max-width: 720px)" in COMMS_CSS
    assert "@media (min-width: 1280px)" in COMMS_CSS
    assert "@media (min-width: 1600px)" in COMMS_CSS
    assert "humanVoiceEngine.js" in COMMS_HTML
    assert "/api/voice/speak" in (STATIC / "ux" / "humanVoiceEngine.js").read_text(encoding="utf-8")


def test_nova_communications_safety_and_frozen_products(client: TestClient) -> None:
    before = _counts()
    headers = _headers(client)
    client.get("/nova/communications")
    client.get("/nova")
    client.get("/nova/workspace")
    client.get("/workspace")
    client.post(
        "/api/nova/communications/drafts",
        headers=headers,
        json={"to": ["safety@example.com"], "subject": "Isolation draft", "body": "local"},
    )
    after = _counts()
    assert before == after
    bundle = COMMS_HTML + COMMS_JS + COMMS_CSS
    assert "Driver 001" not in bundle
    assert "DRV-001" not in bundle
    assert "sk_live" not in bundle
    assert "pk_live" not in bundle
    assert "smtp_password" not in COMMS_JS
    assert "client_secret" not in COMMS_JS
    assert "nova-communications" not in OPS_JS
    assert "Health ISF Workspace" in HEALTH_HTML
    assert "/nova/communications" not in HEALTH_HTML
    health = client.get("/workspace")
    assert health.status_code == 200
    assert "Health ISF Workspace" in health.text
    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    assert "New Freight Request" in freight.text or "Freight / Logistics" in freight.text
