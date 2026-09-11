"""Consent boundaries and Care Circle permission tests for Lifesaver."""
from __future__ import annotations

import os

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def test_feature_requires_explicit_consent():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    bootstrap_profile(client, rider)
    client.post(
        "/api/lifesaver/consents",
        headers=rider,
        json={"consent_type": "journal", "granted": False},
    )
    denied = client.post(
        "/api/lifesaver/journal",
        headers=rider,
        json={"body": "private note"},
    )
    assert denied.status_code == 403

    grant_consents(client, rider, ("journal",))
    allowed = client.post(
        "/api/lifesaver/journal",
        headers=rider,
        json={"body": "private note"},
    )
    assert allowed.status_code == 200, allowed.text


def test_revoked_consent_blocks_later_access():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider, ("health_readings",))
    created = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "temperature", "value_primary": 98.6, "source": "user_entered"},
    )
    assert created.status_code == 200
    revoke = client.post(
        "/api/lifesaver/consents",
        headers=rider,
        json={"consent_type": "health_readings", "granted": False},
    )
    assert revoke.status_code == 200
    blocked = client.get("/api/lifesaver/readings", headers=rider)
    assert blocked.status_code == 403


def test_caregiver_permissions_and_acknowledgment():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    member = bootstrap_profile(client, rider)["profile"]

    invite = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={
            "caregiver_email": "staff@amicor.local",
            "permissions": [
                "view_today",
                "view_readings",
                "receive_alerts",
                "acknowledge_alerts",
                "manage_tasks",
                "handoff",
            ],
        },
    )
    assert invite.status_code == 200, invite.text
    link = invite.json()["data"]
    assert link["status"] == "active"
    assert "view_readings" in link["permissions"]

    reading = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "oxygen_saturation", "value_primary": 97, "source": "simulated"},
    )
    assert reading.status_code == 200
    reading_id = reading.json()["data"]["id"]

    staff = auth_headers(client, "staff@amicor.local")
    visible = client.get(
        "/api/lifesaver/readings",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert visible.status_code == 200, visible.text
    assert reading_id in [row["id"] for row in visible.json()["data"]]
    assert all(row["device_sourced"] is False for row in visible.json()["data"])

    journal_denied = client.get(
        "/api/lifesaver/journal",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert journal_denied.status_code == 403

    alerts = client.get("/api/lifesaver/alerts", headers=staff)
    assert alerts.status_code == 200
    open_alerts = [row for row in alerts.json()["data"] if row["status"] == "open"]
    assert open_alerts
    ack = client.post(f"/api/lifesaver/alerts/{open_alerts[0]['id']}/acknowledge", headers=staff)
    assert ack.status_code == 200
    assert ack.json()["data"]["status"] == "acknowledged"


def test_handoff_requires_circle_membership_and_target_ack():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    member = bootstrap_profile(client, rider)["profile"]
    perms = ["view_today", "receive_alerts", "acknowledge_alerts", "handoff"]
    first = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={"caregiver_email": "staff@amicor.local", "permissions": perms},
    )
    second = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={"caregiver_email": "medical@amicor.local", "permissions": perms},
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    from_id = first.json()["data"]["caregiver_profile_id"]
    to_id = second.json()["data"]["caregiver_profile_id"]

    handoff = client.post(
        "/api/lifesaver/handoffs",
        headers=rider,
        json={
            "member_profile_id": member["id"],
            "from_caregiver_id": from_id,
            "to_caregiver_id": to_id,
            "note": "weekend coverage",
        },
    )
    assert handoff.status_code == 200, handoff.text
    handoff_id = handoff.json()["data"]["id"]

    staff = auth_headers(client, "staff@amicor.local")
    stolen = client.post(f"/api/lifesaver/handoffs/{handoff_id}/accept", headers=staff)
    assert stolen.status_code == 403

    medical = auth_headers(client, "medical@amicor.local")
    accepted = client.post(f"/api/lifesaver/handoffs/{handoff_id}/accept", headers=medical)
    assert accepted.status_code == 200
    assert accepted.json()["data"]["status"] == "accepted"


def test_permission_editor_requires_explicit_grant_for_readings():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    member = bootstrap_profile(client, rider)["profile"]
    invite = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={"caregiver_email": "staff@amicor.local"},
    )
    assert invite.status_code == 200, invite.text
    link = invite.json()["data"]
    assert "view_readings" not in link["permissions"]
    assert set(link["permissions"]) == {"acknowledge_alerts", "receive_alerts", "view_today"}

    client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "glucose", "value_primary": 99, "source": "user_entered"},
    )
    staff = auth_headers(client, "staff@amicor.local")
    denied = client.get(
        "/api/lifesaver/readings",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert denied.status_code == 403

    granted = client.patch(
        f"/api/lifesaver/circle/{link['id']}/permissions",
        headers=rider,
        json={"permissions": ["view_today", "receive_alerts", "acknowledge_alerts", "view_readings"]},
    )
    assert granted.status_code == 200, granted.text
    assert "view_readings" in granted.json()["data"]["permissions"]

    allowed = client.get(
        "/api/lifesaver/readings",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert allowed.status_code == 200
    audit = client.get("/api/lifesaver/audit", headers=rider)
    events = audit.json()["data"]
    assert any(row["action"] == "circle.permissions" and row["outcome"] == "allowed" for row in events)
    for row in events:
        metadata = row.get("metadata") or {}
        assert "value_primary" not in metadata
        assert "body" not in metadata
        assert 99 not in (metadata.values() if isinstance(metadata, dict) else [])


def test_revoked_caregiver_loses_access():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    member = bootstrap_profile(client, rider)["profile"]
    invite = client.post(
        "/api/lifesaver/circle/invite",
        headers=rider,
        json={"caregiver_email": "staff@amicor.local", "permissions": ["view_today", "view_readings"]},
    )
    link_id = invite.json()["data"]["id"]
    revoke = client.post(f"/api/lifesaver/circle/{link_id}/revoke", headers=rider)
    assert revoke.status_code == 200
    assert revoke.json()["data"]["status"] == "revoked"

    staff = auth_headers(client, "staff@amicor.local")
    blocked = client.get(
        "/api/lifesaver/today",
        headers=staff,
        params={"member_profile_id": member["id"]},
    )
    assert blocked.status_code == 403
