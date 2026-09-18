"""V2 hardware-bridge contract. Local adapters only. No real devices, 911, or Stripe."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.auth import ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal, engine
from app.main import app
from app.modules.health_isf.models import HealthISFRide
from app.modules.lifesaver.hardware.command_contract import normalize_command
from app.modules.lifesaver.hardware.models import LifesaverDeviceCommand, LifesaverSafetyEvent
from app.modules.lifesaver.hardware.network_safety import reject_public_device_host
from app.modules.lifesaver.models import LifesaverAuditEvent, ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents
from tests.test_lifesaver_v2_hardware import _create_hub

LIFESAVER_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "lifesaver"


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


def test_pairing_requires_human_confirmation():
    client = _client()
    headers = _ready(client)
    discovered = client.post(
        "/api/lifesaver/devices/discover",
        headers=headers,
        json={"device_type": "HOME_HUB", "local_ip": "127.0.0.1"},
    )
    assert discovered.status_code == 200, discovered.text
    pairing = discovered.json()["data"]
    assert pairing["pairing_state"] == "DISCOVERED"
    assert pairing["auto_trusted"] is False
    assert pairing["confirmed"] is False
    discovery = pairing["discovery"]
    assert discovery["device_type"] == "HOME_HUB"
    assert discovery["local_ip"] == "127.0.0.1"
    assert discovery["camera_present"] is True
    assert discovery["rotation_supported"] is True
    denied = client.post(
        f"/api/lifesaver/devices/pairings/{pairing['id']}/confirm",
        headers=headers,
        json={"confirm": False},
    )
    assert denied.status_code == 422
    pending = client.post(
        f"/api/lifesaver/devices/pairings/{pairing['id']}/request",
        headers=headers,
    )
    assert pending.status_code == 200
    assert pending.json()["data"]["pairing_state"] == "PENDING_PAIR"
    confirmed = client.post(
        f"/api/lifesaver/devices/pairings/{pairing['id']}/confirm",
        headers=headers,
        json={"confirm": True, "adapter_type": "simulated"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["data"]["pairing_state"] == "PAIRED"
    assert confirmed.json()["data"]["confirmed"] is True


def test_unknown_device_is_rejected():
    client = _client()
    headers = _ready(client)
    missing = client.post(
        "/api/lifesaver/devices/pairings/not-a-real-pairing/confirm",
        headers=headers,
        json={"confirm": True},
    )
    assert missing.status_code == 404


def test_lan_address_safety_rejects_public_hosts():
    client = _client()
    headers = _ready(client)
    public = client.post(
        "/api/lifesaver/devices/discover",
        headers=headers,
        json={"device_type": "HOME_HUB", "local_ip": "8.8.8.8"},
    )
    assert public.status_code == 403
    try:
        reject_public_device_host("1.1.1.1")
        raise AssertionError("public host should be rejected")
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403


def test_adapter_selection_and_command_lifecycle():
    client = _client()
    headers = _ready(client)
    discovered = client.post(
        "/api/lifesaver/devices/discover",
        headers=headers,
        json={"device_type": "HOME_HUB", "local_ip": "127.0.0.1"},
    )
    pairing_id = discovered.json()["data"]["id"]
    client.post(f"/api/lifesaver/devices/pairings/{pairing_id}/request", headers=headers)
    confirmed = client.post(
        f"/api/lifesaver/devices/pairings/{pairing_id}/confirm",
        headers=headers,
        json={"confirm": True, "adapter_type": "local_lan"},
    )
    device_id = confirmed.json()["data"]["device_id"]
    ping = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "ping", "client_command_id": "cmd-ping-1", "adapter_type": "local_lan"},
    )
    assert ping.status_code == 200, ping.text
    body = ping.json()["data"]
    assert body["command"] == "DEVICE_PING"
    assert body["status"] == "COMPLETED"
    assert body["adapter_type"] == "local_lan"
    assert body["simulated"] is True
    assert body["external_device_contacted"] is False
    again = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "ping", "client_command_id": "cmd-ping-1"},
    )
    assert again.status_code == 200
    assert again.json()["data"]["idempotent"] is True
    assert again.json()["data"]["command_id"] == body["command_id"]


def test_privacy_enforcement_and_privacy_off_does_not_enable_camera():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    privacy = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "privacy_on"},
    )
    assert privacy.status_code == 200
    device = privacy.json()["data"]["device"]
    assert device["privacy_mode"] is True
    assert device["camera_enabled"] is False
    assert device["tracking_enabled"] is False
    camera = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "camera_on"},
    )
    assert camera.json()["data"]["device"]["camera_enabled"] is False
    off = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "privacy_off"},
    )
    restored = off.json()["data"]["device"]
    assert restored["privacy_mode"] is False
    assert restored["camera_enabled"] is False
    assert restored["microphone_enabled"] is False


def test_rotation_stop_and_simulated_orientation():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    left = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "rotate_left"},
    )
    assert left.status_code == 200
    oriented = left.json()["data"]["device"]
    assert oriented["orientation_deg"] != 0
    assert oriented["rotation_moving"] is True
    stop = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "rotation_stop"},
    )
    stopped = stop.json()["data"]["device"]
    assert stopped["rotation_state"] == "stopped"
    assert stopped["rotation_moving"] is False


def test_simulated_fall_pipeline_and_review():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    result = client.post(f"/api/lifesaver/devices/{home['id']}/simulate-fall", headers=headers)
    assert result.status_code == 200
    data = result.json()["data"]
    assert data["emergency_services_contacted"] is False
    assert data["review_status"] == "NEEDS_REVIEW"
    assert "Possible fall or safety event detected" in data["summary"]
    event_id = data["event"]["id"]
    reviewed = client.post(
        f"/api/lifesaver/devices/events/{event_id}/review",
        headers=headers,
        json={"review_status": "FALSE_ALARM"},
    )
    assert reviewed.status_code == 200
    body = reviewed.json()["data"]
    assert body["review_status"] == "FALSE_ALARM"
    assert body["emergency_services_contacted"] is False
    with SessionLocal() as db:
        rows = db.query(LifesaverSafetyEvent).all()
        assert rows
        assert all(row.emergency_services_contacted is False for row in rows)


def test_video_session_consent_and_privacy_gate():
    client = _client()
    headers = auth_headers(client, "rider@amicor.local")
    bootstrap_profile(client, headers)
    client.post(
        "/api/lifesaver/consents",
        headers=headers,
        json={"consent_type": "video_session_simulation", "granted": False},
    )
    grant_consents(client, headers, types=("hardware_simulation",))
    home = _create_hub(client, headers, "HOME_HUB")
    denied = client.post(
        f"/api/lifesaver/devices/{home['id']}/video-sessions",
        headers=headers,
        json={"participant_role": "caregiver"},
    )
    assert denied.status_code == 403
    grant_consents(client, headers)
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "PRIVACY_ENABLE"},
    )
    blocked = client.post(
        f"/api/lifesaver/devices/{home['id']}/video-sessions",
        headers=headers,
        json={},
    )
    assert blocked.status_code == 409
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "PRIVACY_DISABLE"},
    )
    requested = client.post(
        f"/api/lifesaver/devices/{home['id']}/video-sessions",
        headers=headers,
        json={"participant_role": "family"},
    )
    assert requested.status_code == 200
    session = requested.json()["data"]
    assert session["status"] == "requested"
    assert session["session_phase"] == "RINGING_SIMULATED"
    assert session["media_stored"] is False
    assert session["live_call"] is False


def test_offline_timeout_and_vehicle_commands_rejected():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    car = _create_hub(client, headers, "CAR_HUB")
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "SET_OFFLINE"},
    )
    timed = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "DEVICE_PING"},
    )
    assert timed.status_code == 200
    assert timed.json()["data"]["status"] == "TIMED_OUT"
    steer = client.post(
        f"/api/lifesaver/devices/{car['id']}/commands",
        headers=headers,
        json={"command": "STEER"},
    )
    assert steer.status_code == 422
    assert normalize_command("camera_on") == "CAMERA_ENABLE"


def test_audit_hygiene_and_no_phi_in_command_logs():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "GET_DEVICE_HEALTH"},
    )
    audit = client.get("/api/lifesaver/audit", headers=headers)
    for row in audit.json()["data"]:
        metadata = row.get("metadata") or {}
        blob = str(metadata).lower()
        assert "password" not in blob
        assert "token" not in blob
        assert "secret" not in blob
    with SessionLocal() as db:
        logs = db.query(LifesaverDeviceCommand).all()
        assert logs
        for row in logs:
            payload = (row.metadata_json or "").lower()
            assert "password" not in payload
            assert "journal" not in payload
            assert "email" not in payload
            assert row.simulated is True
        events = db.query(LifesaverAuditEvent).all()
        for row in events:
            meta = (row.metadata_json or "").lower()
            assert "sk_live_" not in meta
            assert "pairing_token" not in meta


def test_mock_pi_local_contract_and_prototype_config():
    client = _client()
    headers = _ready(client)
    health = client.get("/api/lifesaver/mock-pi/health")
    assert health.status_code == 200
    assert health.json()["data"]["simulated"] is True
    status = client.get("/api/lifesaver/mock-pi/status")
    assert status.status_code == 200
    assert status.json()["data"]["local_ip"] == "127.0.0.1"
    command = client.post("/api/lifesaver/mock-pi/commands", json={"command": "ping", "host": "127.0.0.1"})
    assert command.status_code == 200
    events = client.get("/api/lifesaver/mock-pi/events")
    assert events.status_code == 200
    public = client.post("/api/lifesaver/mock-pi/commands", json={"command": "ping", "host": "8.8.8.8"})
    assert public.status_code == 403
    proto = client.get("/api/lifesaver/devices/prototype-config", headers=headers)
    assert proto.status_code == 200
    body = proto.json()["data"]
    assert body["manufacturer_locked"] is False
    assert "camera_module" in body["home_hub"]["modules"]
    assert "optional_gps_later" in body["car_hub"]["modules"]


def test_no_live_external_calls_or_frozen_product_writes():
    client = _client()
    headers = _ready(client)
    names = set(inspect(engine).get_table_names())

    def _count(table: str) -> int:
        if table not in names:
            return 0
        with engine.connect() as conn:
            return int(conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0)

    def _driver_snapshot() -> list[tuple]:
        if "approval_engine_cases" not in names:
            return []
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT id, updated_at FROM approval_engine_cases WHERE display_badge = 'DRV-001'")
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    with SessionLocal() as db:
        rides_before = db.query(HealthISFRide).count()
    freight_before = _count("nova_freight_shipments")
    nova_before = _count("nova_today_tasks")
    driver_before = _driver_snapshot()
    delivery_tables = [name for name in names if name.startswith("delivery") or "delivery_" in name]
    delivery_before = {name: _count(name) for name in delivery_tables}
    home = _create_hub(client, headers, "HOME_HUB")
    client.post(f"/api/lifesaver/devices/{home['id']}/simulate-fall", headers=headers)
    client.post("/api/lifesaver/devices/discover", headers=headers, json={"device_type": "CAR_HUB", "local_ip": "127.0.0.1"})
    with SessionLocal() as db:
        assert db.query(HealthISFRide).count() == rides_before
    assert _count("nova_freight_shipments") == freight_before
    assert _count("nova_today_tasks") == nova_before
    assert _driver_snapshot() == driver_before
    assert {name: _count(name) for name in delivery_tables} == delivery_before
    banned = (
        "from app.modules.health_isf",
        "from app.core.nova",
        "from app.modules.delivery",
        "import stripe",
        "import twilio",
        "socket.socket",
        "sk_live_",
    )
    hardware = LIFESAVER_ROOT / "hardware"
    for path in hardware.rglob("*.py"):
        text_blob = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text_blob, f"{path} contains {token}"
    js = Path(__file__).resolve().parents[1] / "static" / "lifesaver" / "lifesaver.js"
    source = js.read_text(encoding="utf-8")
    assert "PRIVACY MODE" in source
    assert "Safety Event review" in source
    assert "Confirm pair" in source
    assert "zoom.us" not in source.lower()
