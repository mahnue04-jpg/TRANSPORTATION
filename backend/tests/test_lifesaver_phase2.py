"""Phase 2 Care Coordination, adapters, outbox, device foundation, and isolation."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf.models import HealthISFRide
from app.modules.lifesaver.coordination import assign_priority
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents

LIFESAVER_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "lifesaver"


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _grant_core(client: TestClient, headers: dict[str, str]) -> None:
    grant_consents(client, headers)


def test_coordination_requires_consent():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    bootstrap_profile(client, rider)
    client.post(
        "/api/lifesaver/consents",
        headers=rider,
        json={"consent_type": "care_cloud_use", "granted": False},
    )
    denied = client.get("/api/lifesaver/coordination", headers=rider)
    assert denied.status_code == 403
    _grant_core(client, rider)
    allowed = client.get("/api/lifesaver/coordination", headers=rider)
    assert allowed.status_code == 200, allowed.text
    data = allowed.json()["data"]
    assert data["values_included"] is False
    assert data["journal_body_included"] is False


def test_coordination_priority_rules_are_deterministic():
    clock = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    first = assign_priority(kind="task", status="open", due_at=clock - timedelta(hours=1), clock=clock)
    second = assign_priority(kind="task", status="open", due_at=clock - timedelta(hours=1), clock=clock)
    assert first == second
    assert first["priority"] == "HIGH"
    assert "overdue" in first["why"].lower()
    medium = assign_priority(kind="handoff", status="pending", clock=clock)
    assert medium["priority"] == "MEDIUM"
    assert medium["needs_human_review"] is True
    later = assign_priority(
        kind="reminder",
        status="scheduled",
        due_at=clock.replace(hour=20),
        clock=clock,
    )
    assert later["priority"] == "MEDIUM"
    done = assign_priority(kind="task", status="completed", clock=clock)
    assert done["priority"] == "LOW"
    appt = assign_priority(
        kind="appointment",
        status="scheduled",
        due_at=clock + timedelta(hours=12),
        extra={"unresolved_transport": True},
        clock=clock,
    )
    assert appt["priority"] == "HIGH"


def test_coordination_hides_unauthorized_readings_and_journal_body():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    member = bootstrap_profile(client, rider)["profile"]
    client.post("/api/lifesaver/journal", headers=rider, json={"body": "SECRET_JOURNAL_BODY_XYZ"})
    client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "glucose", "value_primary": 188.25, "source": "user_entered"},
    )
    invite = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={"caregiver_email": "staff@amicor.local", "permissions": ["view_today", "receive_alerts"]},
    )
    assert invite.status_code == 200, invite.text
    staff = auth_headers(client, "staff@amicor.local")
    grant_consents(client, staff, ("care_cloud_use",))
    coord = client.get(
        "/api/lifesaver/coordination",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert coord.status_code == 200, coord.text
    blob = str(coord.json()).lower()
    assert "188.25" not in blob
    assert "secret_journal_body_xyz" not in blob
    readings = client.get(
        "/api/lifesaver/readings",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert readings.status_code == 403


def test_care_circle_permission_revocation_blocks_future_reads():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    member = bootstrap_profile(client, rider)["profile"]
    invited = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={"caregiver_email": "staff@amicor.local", "permissions": ["view_today", "view_readings", "receive_alerts"]},
    )
    link_id = invited.json()["data"]["id"]
    client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "weight", "value_primary": 160, "source": "user_entered"},
    )
    staff = auth_headers(client, "staff@amicor.local")
    before = client.get("/api/lifesaver/readings", headers=staff, params={"member_profile_id": member["id"]})
    assert before.status_code == 200
    patched = client.patch(
        f"/api/lifesaver/circle/{link_id}/permissions",
        headers=rider,
        json={"permissions": ["view_today", "receive_alerts"]},
    )
    assert patched.status_code == 200, patched.text
    assert "view_readings" not in patched.json()["data"]["permissions"]
    after = client.get("/api/lifesaver/readings", headers=staff, params={"member_profile_id": member["id"]})
    assert after.status_code == 403


def test_nova_adapter_refuses_diagnosis_and_treatment():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    diagnosis = client.post(
        "/api/lifesaver/ai/orchestrate",
        headers=rider,
        json={"message": "Do I have a heart attack?"},
    )
    assert diagnosis.status_code == 200
    assert diagnosis.json()["data"]["mode"] == "safety_refusal"
    assert diagnosis.json()["data"]["uses_nova_engine"] is False
    assert diagnosis.json()["data"]["writes_nova_tables"] is False
    treatment = client.post(
        "/api/lifesaver/ai/orchestrate",
        headers=rider,
        json={"message": "Should I stop taking this medication?"},
    )
    assert treatment.status_code == 200
    assert treatment.json()["data"]["mode"] == "safety_refusal"
    dangerous = client.post(
        "/api/lifesaver/ai/converse",
        headers=rider,
        json={"message": "Is this blood pressure dangerous?"},
    )
    assert dangerous.status_code == 200
    assert dangerous.json()["data"]["mode"] == "safety_refusal"
    admin = client.post(
        "/api/lifesaver/ai/orchestrate",
        headers=rider,
        json={"message": "Summarize today for care coordination"},
    )
    assert admin.status_code == 200
    assert admin.json()["data"]["mode"] != "safety_refusal"


def test_ai_coordination_summary_matches_live_counts():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    starts = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    created = client.post(
        "/api/lifesaver/appointments",
        headers=rider,
        json={"title": "Therapy follow-up", "location": "Clinic", "starts_at": starts},
    )
    assert created.status_code == 200, created.text
    coord = client.get("/api/lifesaver/coordination", headers=rider)
    assert coord.status_code == 200, coord.text
    counts = coord.json()["data"]["counts"]
    reply = client.post(
        "/api/lifesaver/ai/converse",
        headers=rider,
        json={"message": "Summarize care coordination priorities"},
    )
    assert reply.status_code == 200, reply.text
    text = reply.json()["data"]["reply"]
    assert reply.json()["data"]["mode"] == "summarize_care_coordination"
    assert f"{counts['high']} high" in text
    assert f"{counts['medium']} medium" in text
    assert f"{counts['low']} low" in text
    assert f"{counts['needs_review']} item" in text


def test_nova_adapter_does_not_import_or_write_nova():
    text = ""
    for path in LIFESAVER_ROOT.rglob("*.py"):
        text += path.read_text(encoding="utf-8") + "\n"
    assert "from app.core.nova" not in text
    assert not any(line.strip().startswith("import app.core.nova") for line in text.splitlines())
    assert "NovaAction" not in text


def test_transport_request_stays_local_and_requires_confirmation():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    with SessionLocal() as db:
        before = db.query(HealthISFRide).count()
    created = client.post(
        "/api/lifesaver/transport/requests",
        headers=rider,
        json={
            "pickup_label": "Home lobby",
            "destination_label": "Clinic front door",
            "companion_needed": False,
        },
    )
    assert created.status_code == 200, created.text
    data = created.json()["data"]
    assert data["status"] == "requested"
    assert data["dispatches_ride"] is False
    assert data["creates_health_isf_ride"] is False
    request_id = data["id"]
    missing = client.post(
        f"/api/lifesaver/transport/requests/{request_id}/confirm",
        headers=rider,
        json={"confirm": False},
    )
    assert missing.status_code == 422
    early = client.post(f"/api/lifesaver/transport/requests/{request_id}/handoff-simulated", headers=rider)
    assert early.status_code == 409
    confirmed = client.post(
        f"/api/lifesaver/transport/requests/{request_id}/confirm",
        headers=rider,
        json={"confirm": True},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "ready_for_handoff"
    handed = client.post(f"/api/lifesaver/transport/requests/{request_id}/handoff-simulated", headers=rider)
    assert handed.status_code == 200
    assert handed.json()["data"]["status"] == "handed_off_simulated"
    assert handed.json()["data"]["simulated"] is True
    with SessionLocal() as db:
        after = db.query(HealthISFRide).count()
    assert after == before


def test_notification_outbox_is_local_and_redacts_sensitive_copy():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    queued = client.post(
        "/api/lifesaver/notifications",
        headers=rider,
        json={
            "notification_type": "appointment_reminder",
            "channel": "email",
            "title": "Visit reminder 188.25 SECRET_JOURNAL_BODY_XYZ",
            "reason": "glucose 188.25 journal SECRET_JOURNAL_BODY_XYZ",
            "journal_body": "SECRET_JOURNAL_BODY_XYZ",
            "reading_value": "188.25",
            "recipient_role": "caregiver",
        },
    )
    assert queued.status_code == 200, queued.text
    notice = queued.json()["data"]
    assert notice["external_message_sent"] is False
    assert notice["status"] == "queued_local"
    assert "188.25" not in notice["title"]
    assert "SECRET_JOURNAL_BODY_XYZ" not in (notice["reason"] or "")
    delivered = client.post(f"/api/lifesaver/notifications/{notice['id']}/simulate-deliver", headers=rider)
    assert delivered.status_code == 200
    assert delivered.json()["data"]["status"] == "delivered_simulated"
    failed = client.post(
        "/api/lifesaver/notifications",
        headers=rider,
        json={"notification_type": "task_assigned", "channel": "sms", "title": "Task assigned", "recipient_role": "caregiver"},
    )
    fail_id = failed.json()["data"]["id"]
    sim_fail = client.post(f"/api/lifesaver/notifications/{fail_id}/simulate-fail", headers=rider)
    assert sim_fail.json()["data"]["status"] == "failed_simulated"
    retried = client.post(f"/api/lifesaver/notifications/{fail_id}/retry", headers=rider)
    assert retried.json()["data"]["status"] == "queued_local"
    suppressed = client.post(f"/api/lifesaver/notifications/{fail_id}/suppress", headers=rider)
    assert suppressed.json()["data"]["status"] == "suppressed"
    listed = client.get("/api/lifesaver/notifications", headers=rider)
    assert listed.status_code == 200
    assert all(row["external_message_sent"] is False for row in listed.json()["data"])


def test_device_simulator_labels_and_reserved_source_is_blocked():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    user = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "temperature", "value_primary": 98.6, "source": "user_entered"},
    )
    assert user.status_code == 200
    assert user.json()["data"]["source"] == "user_entered"
    assert user.json()["data"]["device_sourced"] is False
    sim = client.post(
        "/api/lifesaver/readings/simulated-device",
        headers=rider,
        json={"reading_type": "spo2", "value_primary": 96, "source": "simulated_device", "device_alias": "demo-pulse"},
    )
    assert sim.status_code == 200, sim.text
    data = sim.json()["data"]
    assert data["source"] == "simulated_device"
    assert data["device_sourced"] is False
    assert "SIMULATED" in (data["label"] or data["disclaimer"])
    reserved_direct = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "glucose", "value_primary": 90, "source": "external_device_reserved"},
    )
    assert reserved_direct.status_code in {409, 422}
    reserved_device = client.post(
        "/api/lifesaver/readings/simulated-device",
        headers=rider,
        json={"reading_type": "glucose", "value_primary": 90, "source": "external_device_reserved"},
    )
    assert reserved_device.status_code == 409


def test_audit_excludes_reading_values_and_journal_bodies():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    _grant_core(client, rider)
    client.post("/api/lifesaver/journal", headers=rider, json={"body": "SECRET_JOURNAL_BODY_XYZ"})
    client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "glucose", "value_primary": 188.25, "source": "user_entered"},
    )
    client.get("/api/lifesaver/coordination", headers=rider)
    audit = client.get("/api/lifesaver/audit", headers=rider)
    assert audit.status_code == 200
    rows = audit.json()["data"]
    blob = str(rows)
    assert "SECRET_JOURNAL_BODY_XYZ" not in blob
    assert "188.25" not in blob
    assert any(row["action"] == "care_coordination.view" for row in rows)
    for row in rows:
        metadata = row.get("metadata") or {}
        assert "body" not in metadata
        assert "value_primary" not in metadata
        assert "value" not in metadata


def test_phase2_ui_and_frozen_surface_smoke():
    client = _client()
    page = client.get("/lifesaver")
    assert page.status_code == 200
    html = page.text
    assert "data-view=\"coord\"" in html
    assert "data-view=\"notify\"" in html
    js = client.get("/static/lifesaver/lifesaver.js").text
    css = client.get("/static/lifesaver/lifesaver.css").text
    assert "Care Coordination" in js
    assert "Notification Center" in js
    assert "SIMULATED — NOT FROM A MEDICAL DEVICE" in js
    assert "LOCAL SIMULATION — no external message sent." in js
    assert "Transportation coordination only. This does not dispatch a ride." in js
    assert "perm-form" in js
    assert "handoff-form" in js
    assert "--ls-tap: 48px" in css
    assert "ops-shell" not in html
    assert client.get("/contact").status_code == 200
    assert client.get("/api/health/live").status_code == 200
    assert client.get("/nova/freight").status_code == 200
    assert client.get("/platform-ops/driver-apply").status_code == 200


def test_lifesaver_module_does_not_touch_frozen_or_payment_surfaces():
    banned_imports = (
        "from app.modules.health_isf",
        "import app.modules.health_isf",
        "from app.core.nova",
        "import app.core.nova",
        "from app.modules.delivery",
        "import app.modules.delivery",
        "import stripe",
        "from stripe",
        "import twilio",
        "import sendgrid",
        "import smtplib",
    )
    for path in LIFESAVER_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned_imports:
            assert not any(line.strip().startswith(token) for line in text.splitlines()), (
                f"{path} contains banned import {token}"
            )
