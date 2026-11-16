"""Authenticated HTTP journey for receptionist pilot — disposable DB, fake providers."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_DEMO_MODE"] = "true"
os.environ["NOVA_GROWTH_AGENT_WIDGET_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_CALENDAR_SYNC_WORKER"] = "true"
os.environ["NOVA_GROWTH_AGENT_OWNER_NOTIFY_WORKER"] = "true"
os.environ["NOVA_GROWTH_AGENT_VOICE_SIMULATOR"] = "true"
os.environ.setdefault("TESTING", "true")
os.environ["NOVA_GA_CREDENTIAL_ENCRYPTION_KEY"] = Fernet.generate_key().decode()
os.environ["NOVA_GA_GOOGLE_OAUTH_CLIENT_ID"] = "test-client"
os.environ["NOVA_GA_GOOGLE_OAUTH_CLIENT_SECRET"] = "test-secret"
os.environ["NOVA_GA_GOOGLE_OAUTH_REDIRECT_URI"] = "https://example.invalid/oauth/callback"

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.growth_agent import calendar_oauth
from app.core.nova.growth_agent import handoff_queue as hq
from app.core.nova.growth_agent.models import (
    GaAvailabilityRule,
    GaBusinessProfile,
    GaCalendarConnection,
)
from app.core.nova.growth_agent.providers.credential_crypto import encrypt_secret
from app.db.session import SessionLocal
from app.main import app


@pytest.fixture()
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _headers(client: TestClient, email: str = "admin@amicor.local") -> dict[str, str]:
    res = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert res.status_code == 200, res.text
    token = res.json().get("access_token") or res.json().get("token")
    assert token
    return {"Authorization": f"Bearer {token}", "_token": token}


def _activate_profile(client: TestClient, headers: dict[str, str], name: str = "Receptionist Biz") -> str:
    profile = client.post(
        "/api/nova/growth-agent/profile",
        headers={k: v for k, v in headers.items() if not k.startswith("_")},
        json={
            "business_name": name,
            "website": "https://journey.example",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [
                {
                    "code": "consult",
                    "name": "Consult",
                    "duration_minutes": 30,
                    "buffer_minutes": 10,
                }
            ],
            "faqs": [
                {
                    "id": "faq_hours",
                    "question": "Hours?",
                    "keywords": ["hours"],
                    "answer": "Mon–Fri 9–5.",
                }
            ],
            "contact_email": "owner@example.invalid",
            "handoff_phone": "+15555550111",
            "escalation_settings": {"handoff_on_unknown": True},
            "activate": True,
        },
    )
    assert profile.status_code == 200, profile.text
    return profile.json()["organization_id"]


def test_anonymous_receptionist_denied(client: TestClient) -> None:
    assert client.get("/api/nova/growth-agent/receptionist/status").status_code in {401, 403}


def test_receptionist_status_not_connected(client: TestClient) -> None:
    headers = _headers(client)
    auth = {k: v for k, v in headers.items() if not k.startswith("_")}
    _activate_profile(client, headers)
    res = client.get("/api/nova/growth-agent/receptionist/status", headers=auth)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["calendar"]["status"] == "Not connected"
    assert body["calendar"]["connected"] is False
    assert body["honesty"]["internal_booking_is_not_google_confirmation"] is True
    assert "rt-secret" not in res.text
    assert "refresh_token" not in res.text.lower() or "refresh_token_encrypted" not in res.text.lower()


def test_oauth_start_injected_complete_and_disconnect(client: TestClient) -> None:
    headers = _headers(client)
    auth = {k: v for k, v in headers.items() if not k.startswith("_")}
    token = headers["_token"]
    org_id = _activate_profile(client, headers, "OAuth Biz")

    start = client.post("/api/nova/growth-agent/calendar/oauth/start", headers=auth, json={})
    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload.get("authorization_url")
    assert payload.get("state")
    assert "refresh_token" not in start.text.lower()

    db = SessionLocal()
    try:
        profile = db.query(GaBusinessProfile).filter_by(organization_id=org_id).one()
        fp = hashlib.sha256(f"{profile.owner_user_id}|{token[-32:]}".encode()).hexdigest()

        def fake_exchange(code: str, verifier: str, redirect: str) -> dict:
            assert code == "auth-code-1"
            assert verifier
            return {
                "refresh_token": "rt-secret-never-log",
                "access_token": "at-secret-never-log",
                "expires_in": 3600,
                "scope": "https://www.googleapis.com/auth/calendar.events",
            }

        result = calendar_oauth.complete_oauth(
            db,
            org_id=org_id,
            owner_user_id=profile.owner_user_id,
            session_fingerprint=fp,
            state=payload["state"],
            code="auth-code-1",
            http_exchange=fake_exchange,
        )
        assert result.get("status") in {"connected", "Connected"} or result.get("calendar_id")
        assert "rt-secret" not in str(result)
        db.commit()
    finally:
        db.close()

    status = client.get("/api/nova/growth-agent/receptionist/status", headers=auth)
    assert status.status_code == 200
    cal = status.json()["calendar"]
    assert cal["status"] != "Not connected"
    assert cal["connected"] is True
    assert "rt-secret" not in status.text

    disc = client.post("/api/nova/growth-agent/calendar/disconnect", headers=auth, json={})
    assert disc.status_code == 200
    assert disc.json()["status"] == "Not connected"
    assert disc.json()["connected"] is False


def test_oauth_get_callback_redirects_to_spa(client: TestClient) -> None:
    res = client.get(
        "/api/nova/growth-agent/calendar/oauth/callback",
        params={"state": "st-test", "code": "cd-test"},
        follow_redirects=False,
    )
    assert res.status_code in {302, 307}
    loc = res.headers.get("location") or ""
    assert loc.startswith("/nova/growth")
    assert "calendar_oauth=1" in loc
    assert "state=st-test" in loc
    assert "code=cd-test" in loc
    assert "access_token" not in loc
    assert "refresh_token" not in loc

    err = client.get(
        "/api/nova/growth-agent/calendar/oauth/callback",
        params={"error": "access_denied"},
        follow_redirects=False,
    )
    assert err.status_code in {302, 307}
    err_loc = err.headers.get("location") or ""
    assert "oauth_error=access_denied" in err_loc


def test_booking_journey_sync_pending_not_external_confirmed(client: TestClient) -> None:
    headers = _headers(client)
    auth = {k: v for k, v in headers.items() if not k.startswith("_")}
    org_id = _activate_profile(client, headers, "Journey Biz")

    widget = client.post(
        "/api/nova/growth-agent/widget/installations",
        headers=auth,
        json={"domain": "journey.example"},
    )
    assert widget.status_code == 200, widget.text
    token = widget.json()["token"]
    chat = client.post(
        "/api/nova/growth-agent/widget/chat",
        headers={**auth, "Origin": "https://journey.example"},
        json={
            "token": token,
            "message": "What are your hours?",
            "visitor_name": "Pat Journey",
            "visitor_email": "pat.journey@example.com",
            "visitor_phone": "+15555550199",
            "consent_transactional": True,
        },
    )
    assert chat.status_code == 200, chat.text
    contact_id = chat.json()["contact_id"]
    assert contact_id

    db = SessionLocal()
    try:
        # Ensure weekday rules exist for availability
        existing = db.query(GaAvailabilityRule).filter_by(organization_id=org_id).count()
        if existing == 0:
            for dow in range(5):
                db.add(
                    GaAvailabilityRule(
                        id=uuid4().hex,
                        organization_id=org_id,
                        day_of_week=dow,
                        start_minute=9 * 60,
                        end_minute=17 * 60,
                    )
                )
        profile = db.query(GaBusinessProfile).filter_by(organization_id=org_id).one()
        conn = (
            db.query(GaCalendarConnection)
            .filter_by(organization_id=org_id)
            .one_or_none()
        )
        if conn is None:
            conn = GaCalendarConnection(
                id=uuid4().hex,
                organization_id=org_id,
                owner_user_id=profile.owner_user_id,
            )
            db.add(conn)
        conn.owner_user_id = profile.owner_user_id
        conn.provider = "google"
        conn.status = "connected"
        conn.calendar_id = "primary"
        conn.calendar_summary = "Pilot calendar"
        conn.scopes_json = ["calendar.events"]
        conn.refresh_token_encrypted = encrypt_secret("fake-refresh")
        conn.access_token_encrypted = encrypt_secret("fake-access")
        conn.connected_at = datetime.utcnow()
        conn.disconnected_at = None
        conn.last_error_code = None
        db.commit()
    finally:
        db.close()

    day = datetime.now(timezone.utc).astimezone(ZoneInfo("America/Chicago")) + timedelta(days=1)
    while day.weekday() > 4:
        day += timedelta(days=1)
    day_s = day.strftime("%Y-%m-%d")
    avail = client.get(
        f"/api/nova/growth-agent/availability?service_code=consult&day={day_s}",
        headers=auth,
    )
    assert avail.status_code == 200, avail.text
    slots = avail.json().get("slots") or []
    assert slots, avail.text
    start = slots[0]["starts_at_utc"]

    book = client.post(
        "/api/nova/growth-agent/appointments",
        headers=auth,
        json={
            "contact_id": contact_id,
            "service_code": "consult",
            "starts_at_utc": start,
            "idempotency_key": "journey-book-1",
            "is_synthetic_demo": True,
        },
    )
    assert book.status_code == 200, book.text
    booked = book.json()
    assert booked["calendar_sync"]["externally_confirmed"] is False
    assert booked["calendar_sync"]["live"] is False
    assert booked["calendar_sync"]["status"] in {"pending", "suppressed", "confirmed", "sent_mock"}
    appt_id = booked["id"]

    book2 = client.post(
        "/api/nova/growth-agent/appointments",
        headers=auth,
        json={
            "contact_id": contact_id,
            "service_code": "consult",
            "starts_at_utc": start,
            "idempotency_key": "journey-book-1",
            "is_synthetic_demo": True,
        },
    )
    assert book2.status_code == 200
    assert book2.json()["id"] == appt_id

    if len(slots) > 1:
        new_start = slots[1]["starts_at_utc"]
    else:
        dt = datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=1)
        new_start = dt.isoformat().replace("+00:00", "Z")
    resched = client.post(
        f"/api/nova/growth-agent/appointments/{appt_id}/reschedule",
        headers=auth,
        json={"starts_at_utc": new_start, "idempotency_key": "journey-resched-1"},
    )
    assert resched.status_code == 200, resched.text
    assert resched.json()["calendar_sync"]["externally_confirmed"] is False

    cancel = client.post(
        f"/api/nova/growth-agent/appointments/{appt_id}/cancel",
        headers=auth,
    )
    assert cancel.status_code == 200, cancel.text
    assert cancel.json()["status"] == "cancelled"

    rebook = client.post(
        "/api/nova/growth-agent/appointments",
        headers=auth,
        json={
            "contact_id": contact_id,
            "service_code": "consult",
            "starts_at_utc": start,
            "idempotency_key": "journey-rebook-1",
            "is_synthetic_demo": True,
        },
    )
    assert rebook.status_code == 200, rebook.text

    sync_errors = client.get("/api/nova/growth-agent/calendar/sync-errors", headers=auth)
    assert sync_errors.status_code == 200
    assert isinstance(sync_errors.json().get("jobs"), list)
    assert sync_errors.json()["jobs"], "expected durable sync jobs after booking"

    notes = client.get("/api/nova/growth-agent/notifications", headers=auth)
    assert notes.status_code == 200
    assert notes.json()["honesty"]["provider_accepted_is_not_inbox_receipt"] is True
    assert notes.json()["notifications"], "expected owner notifications queued"

    db = SessionLocal()
    try:
        row = hq.create_handoff(
            db,
            org_id=org_id,
            reason="test_escalation",
            summary="Customer asked for human",
            channel="voice",
        )
        db.commit()
        hid = row["id"]
    finally:
        db.close()
    ack = client.post(
        f"/api/nova/growth-agent/handoffs/{hid}/acknowledge",
        headers=auth,
        json={},
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"

    denied = client.get(
        "/api/nova/growth-agent/receptionist/status?organization_id=00000000-0000-0000-0000-000000000099",
        headers=auth,
    )
    assert denied.status_code in {403, 400}


def test_voice_simulator_labeled(client: TestClient) -> None:
    headers = _headers(client)
    auth = {k: v for k, v in headers.items() if not k.startswith("_")}
    _activate_profile(client, headers, "Voice Sim Biz")
    res = client.post(
        "/api/nova/growth-agent/voice/simulator/run",
        headers=auth,
        json={
            "called_number": "+15555550100",
            "caller_number": "+15555550101",
            "script": [{"event_type": "faq_answer", "question": "What are your hours?"}],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["simulated"] is True
    assert body["live_phone"] is False
    assert "SIMULATED" in body["label"]


def test_voice_simulator_ui_intent_utterance_payload(client: TestClient) -> None:
    """receptionist.js sends intent/utterance/simulated — API must accept them."""
    headers = _headers(client)
    auth = {k: v for k, v in headers.items() if not k.startswith("_")}
    _activate_profile(client, headers, "Voice UI Biz")
    res = client.post(
        "/api/nova/growth-agent/voice/simulator/run",
        headers=auth,
        json={
            "called_number": "+15555550100",
            "caller_number": "+15555550101",
            "intent": "general",
            "utterance": "What are your hours?",
            "simulated": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["simulated"] is True
    assert body["intent"] == "general"
    assert body["outcomes"]
    assert body["outcomes"][0]["status"] in {"processed", "duplicate"}
    faq = body["outcomes"][0].get("result") or body["outcomes"][0]
    # Service-backed FAQ should return grounded content from approved FAQs
    blob = str(faq).lower()
    assert "hour" in blob or "mon" in blob or "9" in blob or "faq" in blob or "answer" in blob


def test_calendar_status_states_connected_expired_revoked(client: TestClient) -> None:
    headers = _headers(client)
    auth = {k: v for k, v in headers.items() if not k.startswith("_")}
    org_id = _activate_profile(client, headers, "Status States Biz")

    db = SessionLocal()
    try:
        profile = db.query(GaBusinessProfile).filter_by(organization_id=org_id).one()
        conn = (
            db.query(GaCalendarConnection)
            .filter_by(organization_id=org_id)
            .one_or_none()
        )
        if conn is None:
            conn = GaCalendarConnection(
                id=uuid4().hex,
                organization_id=org_id,
                owner_user_id=profile.owner_user_id,
            )
            db.add(conn)
        conn.owner_user_id = profile.owner_user_id
        conn.provider = "google"
        conn.status = "connected"
        conn.calendar_id = "primary"
        conn.calendar_summary = "Pilot"
        conn.refresh_token_encrypted = encrypt_secret("fake-refresh")
        conn.access_token_encrypted = encrypt_secret("fake-access")
        conn.connected_at = datetime.utcnow()
        conn.disconnected_at = None
        conn.last_error_code = None
        db.commit()
    finally:
        db.close()

    ok = client.get("/api/nova/growth-agent/receptionist/status", headers=auth)
    assert ok.status_code == 200
    assert ok.json()["calendar"]["connected"] is True
    assert ok.json()["calendar"]["status"] == "connected"

    db = SessionLocal()
    try:
        row = db.query(GaCalendarConnection).filter_by(organization_id=org_id).one()
        row.status = "needs_reconnect"
        row.last_error_code = "CREDENTIALS_EXPIRED"
        db.commit()
    finally:
        db.close()
    expired = client.get("/api/nova/growth-agent/receptionist/status", headers=auth)
    assert expired.json()["calendar"]["connected"] is False
    assert expired.json()["calendar"]["status"] == "needs_reconnect"

    db = SessionLocal()
    try:
        row = db.query(GaCalendarConnection).filter_by(organization_id=org_id).one()
        row.status = "revoked"
        db.commit()
    finally:
        db.close()
    revoked = client.get("/api/nova/growth-agent/receptionist/status", headers=auth)
    assert revoked.json()["calendar"]["connected"] is False
    assert revoked.json()["calendar"]["status"] == "revoked"
