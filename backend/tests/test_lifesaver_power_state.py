"""Home Hub virtual power-state contract. No physical battery is implied."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app
from app.modules.lifesaver.hardware.power_state import (
    EVENT_BACKUP_ACTIVE,
    EVENT_LOW_BATTERY,
    EVENT_POWER_LOSS,
    EVENT_POWER_RESTORED,
    EVENT_SHUTDOWN_WARNING,
    EVENT_SYSTEM_RECOVERED,
    POWER_BACKUP,
    POWER_LOW,
    POWER_MAINS,
    POWER_NORMAL,
    POWER_RESTORING,
    POWER_SHUTDOWN,
    evaluate_transition,
)
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents
from tests.test_lifesaver_v2_hardware import _create_hub


def _client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _ready(client: TestClient) -> dict[str, str]:
    headers = auth_headers(client, "rider@amicor.local")
    grant_consents(client, headers)
    bootstrap_profile(client, headers)
    return headers


def test_unit_normal_to_backup():
    result = evaluate_transition(POWER_MAINS, POWER_BACKUP)
    assert result.applied is True
    assert result.to_state == POWER_BACKUP
    assert EVENT_POWER_LOSS in result.events
    assert EVENT_BACKUP_ACTIVE in result.events
    assert result.physical_battery_connected is False


def test_unit_backup_to_low_battery():
    result = evaluate_transition(POWER_BACKUP, POWER_LOW)
    assert result.applied is True
    assert result.events == (EVENT_LOW_BATTERY,)


def test_unit_low_battery_to_shutdown_warning():
    result = evaluate_transition(POWER_LOW, POWER_SHUTDOWN)
    assert result.applied is True
    assert result.events == (EVENT_SHUTDOWN_WARNING,)


def test_unit_backup_to_restored():
    result = evaluate_transition(POWER_BACKUP, POWER_RESTORING)
    assert result.applied is True
    assert result.events == (EVENT_POWER_RESTORED,)


def test_unit_restored_to_normal():
    result = evaluate_transition(POWER_RESTORING, POWER_NORMAL)
    assert result.applied is True
    assert result.events == (EVENT_SYSTEM_RECOVERED,)


def test_unit_duplicate_power_event():
    result = evaluate_transition(POWER_BACKUP, POWER_BACKUP)
    assert result.applied is False
    assert result.duplicate is True
    assert result.events == ()


def test_unit_stale_power_event():
    last = datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc)
    older = last - timedelta(minutes=5)
    result = evaluate_transition(POWER_MAINS, POWER_BACKUP, event_at=older, last_transition_at=last)
    assert result.applied is False
    assert result.stale is True


def test_unit_invalid_transition():
    result = evaluate_transition(POWER_MAINS, POWER_LOW)
    assert result.applied is False
    assert result.invalid is True
    result = evaluate_transition(POWER_BACKUP, POWER_NORMAL)
    assert result.invalid is True


def test_home_hub_power_contract_http():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    device_id = home["id"]
    assert home["power_state"] == POWER_MAINS
    assert home["physical_battery_connected"] is False
    assert "SIMULATED" in (home.get("power_label") or "")

    backup = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SIMULATE_POWER_LOSS"},
    )
    assert backup.status_code == 200, backup.text
    data = backup.json()["data"]
    assert data["device"]["power_state"] == POWER_BACKUP
    assert data["device"]["physical_battery_connected"] is False
    assert EVENT_POWER_LOSS in data["power_events"]
    assert EVENT_BACKUP_ACTIVE in data["power_events"]

    low = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SIMULATE_LOW_BATTERY"},
    )
    assert low.json()["data"]["device"]["power_state"] == POWER_LOW

    shutdown = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SIMULATE_SHUTDOWN_WARNING"},
    )
    assert shutdown.json()["data"]["device"]["power_state"] == POWER_SHUTDOWN

    restore = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SIMULATE_POWER_RESTORE"},
    )
    assert restore.json()["data"]["device"]["power_state"] == POWER_RESTORING
    assert EVENT_POWER_RESTORED in restore.json()["data"]["power_events"]

    recovered = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SIMULATE_SYSTEM_RECOVER"},
    )
    assert recovered.json()["data"]["device"]["power_state"] == POWER_NORMAL
    assert recovered.json()["data"]["device"]["last_power_transition"]["to_state"] == POWER_NORMAL

    duplicate = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SET_POWER_STATE", "power_state": POWER_NORMAL},
    )
    assert duplicate.status_code == 200, duplicate.text
    assert duplicate.json()["data"]["power_transition"]["duplicate"] is True
    assert duplicate.json()["data"]["power_events"] == []

    stale = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={
            "command": "SET_POWER_STATE",
            "power_state": POWER_BACKUP,
            "event_at": "2020-01-01T00:00:00+00:00",
        },
    )
    assert stale.status_code == 200, stale.text
    assert stale.json()["data"]["power_transition"]["stale"] is True
    assert stale.json()["data"]["device"]["power_state"] == POWER_NORMAL

    invalid = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "SET_POWER_STATE", "power_state": POWER_LOW},
    )
    assert invalid.status_code == 422

    events = client.get(f"/api/lifesaver/devices/{device_id}/events", headers=headers)
    assert events.status_code == 200
    kinds = {row["event_type"] for row in events.json()["data"]}
    assert EVENT_BACKUP_ACTIVE in kinds
    assert EVENT_SYSTEM_RECOVERED in kinds
    assert all(row.get("emergency_services_contacted") is False for row in events.json()["data"])
