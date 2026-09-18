"""V2 physical Home Hub adapter foundation. Local only. No real Pi, 911, or Stripe."""
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
from app.modules.lifesaver.hardware.adapters import physical_pi_adapter
from app.modules.lifesaver.hardware.hardware_mode import hardware_mode, snapshot
from app.modules.lifesaver.hardware.models import LifesaverDevice, LifesaverDeviceCommand, LifesaverSafetyEvent
from app.modules.lifesaver.hardware.network_safety import reject_public_device_host
from app.modules.lifesaver.models import LifesaverAuditEvent, ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents

LIFESAVER_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules" / "lifesaver"
STATIC = Path(__file__).resolve().parents[1] / "static" / "lifesaver"


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


def _enable_local_pi(monkeypatch) -> None:
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "local")
    monkeypatch.setenv("AMICOR_LIFESAVER_HARDWARE_MODE", "local_pi")
    monkeypatch.setenv("AMICOR_LIFESAVER_PI_HOST", "127.0.0.1")
    monkeypatch.setenv("LIFESAVER_LOCAL_DEVICE_ALLOWLIST", "127.0.0.1,localhost,::1,10.0.0.12")
    physical_pi_adapter.set_transport(None)
    physical_pi_adapter.reset_attempts()


def _pair_local_pi(client: TestClient, headers: dict[str, str], local_ip: str = "127.0.0.1") -> tuple[str, str, str]:
    discovered = client.post(
        "/api/lifesaver/devices/discover",
        headers=headers,
        json={"device_type": "HOME_HUB", "local_ip": local_ip},
    )
    assert discovered.status_code == 200, discovered.text
    pairing_id = discovered.json()["data"]["id"]
    client.post(f"/api/lifesaver/devices/pairings/{pairing_id}/request", headers=headers)
    confirmed = client.post(
        f"/api/lifesaver/devices/pairings/{pairing_id}/confirm",
        headers=headers,
        json={"confirm": True, "adapter_type": "local_pi"},
    )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()["data"]
    device_id = body["device_id"]
    token = body.get("device_token")
    if not token:
        with SessionLocal() as db:
            row = db.query(LifesaverDevice).filter(LifesaverDevice.id == device_id).one()
            token = row.pairing_token
    assert token
    return device_id, token, pairing_id


def test_hardware_mode_defaults_to_mock(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "local")
    monkeypatch.delenv("AMICOR_LIFESAVER_HARDWARE_MODE", raising=False)
    assert hardware_mode() == "mock"
    client = _client()
    headers = _ready(client)
    mode = client.get("/api/lifesaver/devices/hardware-mode", headers=headers)
    assert mode.status_code == 200
    body = mode.json()["data"]
    assert body["mode"] == "mock"
    assert body["default_mode"] == "mock"
    assert body["local_pi_enabled"] is False
    assert body["prototype_panel_available"] is True
    assert body["real_camera_streaming"] is False
    assert body["emergency_services_enabled"] is False


def test_production_forces_mock_and_hides_prototype_panel(monkeypatch):
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    monkeypatch.setenv("AMICOR_LIFESAVER_HARDWARE_MODE", "local_pi")
    snap = snapshot()
    assert snap["mode"] == "mock"
    assert snap["prototype_panel_available"] is False


def test_public_ip_rejected(monkeypatch):
    _enable_local_pi(monkeypatch)
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
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    with SessionLocal() as db:
        row = db.query(LifesaverDevice).filter(LifesaverDevice.id == device_id).one()
        row.local_ip = "8.8.8.8"
        db.commit()
    denied = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "DEVICE_PING", "device_token": token, "adapter_type": "local_pi"},
    )
    assert denied.status_code == 403


def test_unpaired_pi_rejected(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, token, pairing_id = _pair_local_pi(client, headers)
    unpaired = client.post(f"/api/lifesaver/devices/pairings/{pairing_id}/unpair", headers=headers)
    assert unpaired.status_code == 200
    ping = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "DEVICE_PING", "device_token": token, "adapter_type": "local_pi"},
    )
    assert ping.status_code == 409


def test_invalid_token_rejected(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, _token, _pairing_id = _pair_local_pi(client, headers)
    denied = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "DEVICE_PING", "device_token": "not-the-paired-token", "adapter_type": "local_pi"},
    )
    assert denied.status_code == 403


def test_duplicate_client_command_id_is_idempotent(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    first = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={
            "command": "DEVICE_PING",
            "client_command_id": "pi-ping-1",
            "device_token": token,
            "adapter_type": "local_pi",
        },
    )
    assert first.status_code == 200, first.text
    assert first.json()["data"]["status"] == "COMPLETED"
    again = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={
            "command": "DEVICE_PING",
            "client_command_id": "pi-ping-1",
            "device_token": token,
            "adapter_type": "local_pi",
        },
    )
    assert again.status_code == 200
    assert again.json()["data"]["idempotent"] is True
    assert again.json()["data"]["command_id"] == first.json()["data"]["command_id"]


def test_timeout_handled_and_retry_ceiling_honored(monkeypatch):
    _enable_local_pi(monkeypatch)
    monkeypatch.setenv("LIFESAVER_DEVICE_RETRY_CEILING", "2")

    def _timeout(_payload, _host):
        return {"status": "TIMED_OUT"}

    physical_pi_adapter.set_transport(_timeout)
    physical_pi_adapter.reset_attempts()
    try:
        client = _client()
        headers = _ready(client)
        device_id, token, _pairing_id = _pair_local_pi(client, headers)
        timed = client.post(
            f"/api/lifesaver/devices/{device_id}/commands",
            headers=headers,
            json={"command": "DEVICE_PING", "device_token": token, "adapter_type": "local_pi"},
        )
        assert timed.status_code == 200, timed.text
        assert timed.json()["data"]["status"] == "TIMED_OUT"
        assert physical_pi_adapter.attempts() == 3
    finally:
        physical_pi_adapter.set_transport(None)
        physical_pi_adapter.reset_attempts()


def test_privacy_blocks_camera_mic_and_tracking(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    privacy = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "PRIVACY_ENABLE", "device_token": token, "adapter_type": "local_pi"},
    )
    assert privacy.status_code == 200, privacy.text
    device = privacy.json()["data"]["device"]
    assert device["privacy_mode"] is True
    assert device["camera_enabled"] is False
    assert device["microphone_enabled"] is False
    assert device["tracking_enabled"] is False
    assert device["camera_contract"]["privacy_block"] is True
    assert device["camera_contract"]["stream_ready"] is False
    camera = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "CAMERA_ENABLE", "device_token": token, "adapter_type": "local_pi"},
    )
    assert camera.json()["data"]["device"]["camera_enabled"] is False
    mic = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "MIC_ENABLE", "device_token": token, "adapter_type": "local_pi"},
    )
    assert mic.json()["data"]["device"]["microphone_enabled"] is False
    rotate = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "ROTATE_LEFT", "device_token": token, "adapter_type": "local_pi"},
    )
    assert rotate.json()["data"]["device"]["tracking_enabled"] is False


def test_stop_motor_always_accepted_locally(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, token, pairing_id = _pair_local_pi(client, headers)
    stop = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "STOP_MOTOR", "device_token": token, "adapter_type": "local_pi"},
    )
    assert stop.status_code == 200, stop.text
    assert stop.json()["data"]["status"] == "COMPLETED"
    assert stop.json()["data"]["device"]["rotation_state"] == "stopped"
    client.post(f"/api/lifesaver/devices/pairings/{pairing_id}/unpair", headers=headers)
    unpaired_stop = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "ROTATE_STOP", "adapter_type": "local_pi"},
    )
    assert unpaired_stop.status_code == 200
    assert unpaired_stop.json()["data"]["status"] == "COMPLETED"


def test_vehicle_control_commands_rejected(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    for command in ("STEER", "BRAKE", "THROTTLE", "IGNITION_ON"):
        denied = client.post(
            f"/api/lifesaver/devices/{device_id}/commands",
            headers=headers,
            json={"command": command, "device_token": token, "adapter_type": "local_pi"},
        )
        assert denied.status_code == 422, command


def test_safety_event_never_contacts_emergency_services(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, _token, _pairing_id = _pair_local_pi(client, headers)
    event = client.post(
        f"/api/lifesaver/devices/{device_id}/hardware-events",
        headers=headers,
        json={"event_type": "POSSIBLE_FALL_EVENT", "confidence": "low"},
    )
    assert event.status_code == 200, event.text
    body = event.json()["data"]
    assert body["emergency_services_contacted"] is False
    assert body["needs_human_review"] is True
    assert "human review required" in body["summary"].lower()
    with SessionLocal() as db:
        rows = db.query(LifesaverSafetyEvent).all()
        assert rows
        assert all(row.emergency_services_contacted is False for row in rows)


def test_no_phi_in_command_logs(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    ping = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "GET_DEVICE_HEALTH", "device_token": token, "adapter_type": "local_pi"},
    )
    assert ping.status_code == 200, ping.text
    audit = client.get("/api/lifesaver/audit", headers=headers)
    for row in audit.json()["data"]:
        if not str(row.get("action") or "").startswith("device."):
            continue
        blob = str(row.get("metadata") or {}).lower()
        assert "password" not in blob
        assert "secret" not in blob
        assert "pairing_token" not in blob
        assert "device_token" not in blob
        assert "sk_live_" not in blob
    with SessionLocal() as db:
        logs = db.query(LifesaverDeviceCommand).all()
        assert logs
        for row in logs:
            payload = (row.metadata_json or "").lower()
            assert "password" not in payload
            assert "journal" not in payload
            assert token.lower() not in payload
            assert "sk_live_" not in payload
        events = db.query(LifesaverAuditEvent).all()
        for row in events:
            meta = (row.metadata_json or "").lower()
            assert token.lower() not in meta
            assert "sk_live_" not in meta


def test_supported_local_pi_commands_and_contract(monkeypatch):
    _enable_local_pi(monkeypatch)
    client = _client()
    headers = _ready(client)
    contract = client.get("/api/lifesaver/devices/contract", headers=headers)
    assert contract.status_code == 200, contract.text
    example = contract.json()["data"]
    response = example["response"]
    for key in (
        "device_id",
        "device_type",
        "serial",
        "model",
        "firmware_version",
        "ip_address",
        "pairing_state",
        "online",
        "camera_state",
        "microphone_state",
        "privacy_state",
        "rotation_angle",
        "motor_state",
        "temperature",
        "battery_power_state",
        "last_seen",
        "command_id",
        "command_status",
        "command_timestamp",
        "acknowledgement",
        "failure_reason",
        "safety_event_status",
    ):
        assert key in response
    assert response["emergency_services_contacted"] is False
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    for command, extra in (
        ("DEVICE_PING", {}),
        ("GET_DEVICE_HEALTH", {}),
        ("CAMERA_ENABLE", {}),
        ("CAMERA_DISABLE", {}),
        ("MIC_ENABLE", {}),
        ("MIC_DISABLE", {}),
        ("SPEAKER_TEST", {}),
        ("ROTATE_LEFT", {}),
        ("ROTATE_RIGHT", {}),
        ("ROTATE_HOME", {}),
        ("ROTATE_TO_ANGLE", {"angle": 90}),
        ("ROTATE_STOP", {}),
        ("PRIVACY_ENABLE", {}),
        ("PRIVACY_DISABLE", {}),
        ("DEVICE_RESTART", {}),
    ):
        body = {"command": command, "device_token": token, "adapter_type": "local_pi"}
        body.update(extra)
        result = client.post(f"/api/lifesaver/devices/{device_id}/commands", headers=headers, json=body)
        assert result.status_code == 200, f"{command}: {result.text}"
        assert result.json()["data"]["external_device_contacted"] is False


def test_frozen_surfaces_untouched(monkeypatch):
    _enable_local_pi(monkeypatch)
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
    device_id, token, _pairing_id = _pair_local_pi(client, headers)
    client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "DEVICE_PING", "device_token": token, "adapter_type": "local_pi"},
    )
    client.post(
        f"/api/lifesaver/devices/{device_id}/hardware-events",
        headers=headers,
        json={"event_type": "MOTION_EVENT"},
    )
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
    js = STATIC.joinpath("lifesaver.js").read_text(encoding="utf-8")
    assert "LOCAL PROTOTYPE TEST" in js
    assert "STOP MOTOR" in js
    assert "Camera On" in js
    assert "Simulate Fall Event · SIMULATION" in js
    assert "ROTATE_STOP" in js
    assert "zoom.us" not in js.lower()
    assert "twilio" not in js.lower()
    device = client.get(f"/api/lifesaver/devices/{device_id}", headers=headers)
    assert device.status_code == 200
    assert device.json()["data"]["simulation_badge"] == "LOCAL PROTOTYPE"
    assert device.json()["data"]["paired"] is True
