"""Authorization, tenant isolation, and unauthorized-access tests for Lifesaver."""
from __future__ import annotations

import os

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import (
    auth_headers,
    bootstrap_profile,
    create_other_org_user,
    grant_consents,
)


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def test_unauthenticated_api_is_rejected():
    client = _client()
    response = client.get("/api/lifesaver/me")
    assert response.status_code in {401, 403}


def test_public_health_does_not_require_auth():
    client = _client()
    response = client.get("/api/lifesaver/health")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["diagnostic_device"] is False
    assert data["emergency_response_guaranteed"] is False
    assert "not a diagnostic" in data["disclaimer"].lower()


def test_organization_isolation_blocks_cross_tenant_readings():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    rider_profile = bootstrap_profile(client, rider)["profile"]
    created = client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={
            "reading_type": "glucose",
            "value_primary": 102,
            "source": "user_entered",
        },
    )
    assert created.status_code == 200, created.text
    reading_id = created.json()["data"]["id"]

    create_other_org_user()
    other = auth_headers(client, "lifesaver.other@example.local")
    grant_consents(client, other)
    other_list = client.get("/api/lifesaver/readings", headers=other)
    assert other_list.status_code == 200
    other_ids = [row["id"] for row in other_list.json()["data"]]
    assert reading_id not in other_ids

    cross = client.get(
        "/api/lifesaver/readings",
        headers=other,
        params={"member_profile_id": rider_profile["id"]},
    )
    assert cross.status_code in {403, 404}


def test_same_org_without_circle_cannot_read_health_data():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    rider_profile = bootstrap_profile(client, rider)["profile"]
    client.post(
        "/api/lifesaver/readings",
        headers=rider,
        json={"reading_type": "weight", "value_primary": 180, "source": "simulated"},
    )

    staff = auth_headers(client, "staff@amicor.local")
    grant_consents(client, staff)
    blocked = client.get(
        "/api/lifesaver/readings",
        headers=staff,
        params={"member_profile_id": rider_profile["id"]},
    )
    assert blocked.status_code == 403


def test_reminder_acknowledge_is_owner_only():
    client = _client()
    rider = auth_headers(client, "rider@amicor.local")
    grant_consents(client, rider)
    med = client.post(
        "/api/lifesaver/medications",
        headers=rider,
        json={"name": "User-entered vitamin", "schedule_times": ["23:59"]},
    )
    assert med.status_code == 200, med.text
    reminders = client.get("/api/lifesaver/reminders", headers=rider)
    assert reminders.status_code == 200
    rows = reminders.json()["data"]
    assert rows
    reminder_id = rows[0]["id"]

    staff = auth_headers(client, "staff@amicor.local")
    grant_consents(client, staff)
    stolen = client.post(f"/api/lifesaver/reminders/{reminder_id}/acknowledge", headers=staff)
    assert stolen.status_code == 404

    owned = client.post(f"/api/lifesaver/reminders/{reminder_id}/acknowledge", headers=rider)
    assert owned.status_code == 200
    assert owned.json()["data"]["status"] == "acknowledged"
