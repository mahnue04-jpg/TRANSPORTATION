"""Readings, reminders, audit, SOS/AI safety, UI, and frozen-surface regression."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, grant_consents


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def test_health_reading_source_is_never_device_claimed():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    response = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={
            "reading_type": "blood_pressure",
            "value_primary": 120,
            "value_secondary": 80,
            "source": "user_entered",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["device_sourced"] is False
    assert data["source"] == "user_entered"
    assert data["unit"] == "mmHg"
    rejected = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={
            "reading_type": "glucose",
            "value_primary": 90,
            "source": "medical_device",
        },
    )
    assert rejected.status_code == 422


def test_reminder_engine_and_appointment_ownership():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    starts = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    created = client.post(
        "/api/lifesaver/appointments",
        headers=rider,
        json={"title": "Wellness visit", "location": "Clinic", "starts_at": starts},
    )
    assert created.status_code == 200, created.text
    appointment_id = created.json()["data"]["id"]
    reminders = client.get("/api/lifesaver/reminders", headers=rider)
    assert reminders.status_code == 200
    mine = reminders.json()["data"]
    assert any(row["source_id"] == appointment_id for row in mine)

    listed = client.get("/api/lifesaver/appointments", headers=rider)
    assert listed.status_code == 200
    assert appointment_id in [row["id"] for row in listed.json()["data"]]
    today = client.get("/api/lifesaver/today", headers=rider)
    assert today.status_code == 200
    assert appointment_id in [row["id"] for row in today.json()["data"]["appointments"]]

    staff = auth_headers(client, "staff@amicor.local")
    grant_consents(client, staff)
    other = client.get("/api/lifesaver/appointments", headers=staff)
    assert other.status_code == 200
    assert appointment_id not in [row["id"] for row in other.json()["data"]]


def test_ui_includes_phase1_gap_fixes():
    client = _client()
    page = client.get("/lifesaver")
    assert page.status_code == 200
    script = client.get("/static/lifesaver/lifesaver.js")
    assert script.status_code == 200
    js = script.text
    assert "perm-form" in js
    assert "handoff-form" in js
    assert "care-appointments" in js
    assert "Save permissions" in js
    assert "Create handoff" in js
    assert "view_readings" in js


def test_audit_records_actions_without_phi_fields():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    client.post("/api/lifesaver/journal", headers=rider, json={"body": "sensitive journal text"})
    audit = client.get("/api/lifesaver/audit", headers=rider)
    assert audit.status_code == 200
    rows = audit.json()["data"]
    assert any(row["action"] == "journal.create" and row["outcome"] == "allowed" for row in rows)
    blob = str(rows).lower()
    assert "sensitive journal text" not in blob
    for row in rows:
        metadata = row.get("metadata") or {}
        assert "body" not in metadata
        assert "value_primary" not in metadata


def test_sos_demonstration_requires_human_confirmation_and_is_not_emergency():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    started = client.post("/api/lifesaver/sos/start", headers=rider, json={"note": "demo"})
    assert started.status_code == 200
    sos_id = started.json()["data"]["id"]
    assert started.json()["data"]["emergency_services_contacted"] is False
    assert started.json()["data"]["status"] == "draft"

    missing = client.post(
        f"/api/lifesaver/sos/{sos_id}/confirm",
        headers=rider,
        json={"confirm": True, "understood_not_emergency": False},
    )
    assert missing.status_code == 422

    confirmed = client.post(
        f"/api/lifesaver/sos/{sos_id}/confirm",
        headers=rider,
        json={"confirm": True, "understood_not_emergency": True},
    )
    assert confirmed.status_code == 200, confirmed.text
    data = confirmed.json()["data"]
    assert data["status"] == "confirmed"
    assert data["emergency_services_contacted"] is False


def test_ai_interface_refuses_diagnosis_and_does_not_use_nova():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    response = client.post(
        "/api/lifesaver/ai/converse",
        headers=rider,
        json={"message": "Can you diagnose this and tell me the treatment?"},
    )
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["uses_nova_engine"] is False
    assert data["mode"] == "safety_refusal"
    assert "cannot diagnose" in data["reply"].lower()


def test_lifesaver_ui_is_isolated_and_frozen_surfaces_still_serve():
    client = _client()
    page = client.get("/lifesaver")
    assert page.status_code == 200
    assert "Lifesaver AI Care Cloud" in page.text
    assert "ops-shell" not in page.text

    marketing = client.get("/contact")
    assert marketing.status_code == 200
    assert "AMICOR" in marketing.text

    live = client.get("/api/health/live")
    assert live.status_code == 200

    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    apply_page = client.get("/platform-ops/driver-apply")
    assert apply_page.status_code == 200
