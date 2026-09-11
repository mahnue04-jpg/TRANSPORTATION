"""V2 simulated Home Hub / Car Hub foundation. No real devices, 911, or Stripe."""
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
from app.modules.lifesaver.hardware.models import LifesaverDeviceCommand, LifesaverDeviceEvent
from app.modules.lifesaver.models import LifesaverNotificationOutbox, ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, create_other_org_user, grant_consents

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


def _create_hub(client: TestClient, headers: dict[str, str], device_type: str) -> dict:
    created = client.post(
        "/api/lifesaver/devices/simulated",
        headers=headers,
        json={"device_type": device_type},
    )
    assert created.status_code == 200, created.text
    device = created.json()["data"]
    restarted = client.post(
        f"/api/lifesaver/devices/{device['id']}/commands",
        headers=headers,
        json={"command": "DEVICE_RESTART_SIMULATED", "adapter_type": "simulated"},
    )
    assert restarted.status_code == 200, restarted.text
    return restarted.json()["data"]["device"]


def test_home_hub_and_car_hub_creation():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    car = _create_hub(client, headers, "CAR_HUB")
    assert home["device_type"] == "HOME_HUB"
    assert home["camera_enabled"] is False
    assert home["camera_state"] == "off"
    assert home["privacy_mode"] is False
    assert home["external_device_connected"] is False
    assert car["device_type"] == "CAR_HUB"
    assert car["vehicle_control"] is False
    listed = client.get("/api/lifesaver/devices", headers=headers)
    assert listed.status_code == 200
    types = {row["device_type"] for row in listed.json()["data"]}
    assert types == {"HOME_HUB", "CAR_HUB"}


def test_tenant_isolation_and_idor():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    create_other_org_user()
    other = auth_headers(client, "lifesaver.other@example.local")
    grant_consents(client, other)
    denied = client.get(f"/api/lifesaver/devices/{home['id']}", headers=other)
    assert denied.status_code == 404
    cmd = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=other,
        json={"command": "DEVICE_PING"},
    )
    assert cmd.status_code == 404
    fall = client.post(f"/api/lifesaver/devices/{home['id']}/simulate-fall", headers=other)
    assert fall.status_code == 404


def test_invalid_device_is_rejected():
    client = _client()
    headers = _ready(client)
    missing = client.get("/api/lifesaver/devices/not-a-real-device", headers=headers)
    assert missing.status_code == 404
    unknown = client.post(
        "/api/lifesaver/devices/simulated",
        headers=headers,
        json={"device_type": "PACEMAKER"},
    )
    assert unknown.status_code == 422


def test_privacy_mode_blocks_camera_and_rotation_tracking():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    device_id = home["id"]
    privacy = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "PRIVACY_ENABLE"},
    )
    assert privacy.status_code == 200, privacy.text
    data = privacy.json()["data"]["device"]
    assert data["privacy_mode"] is True
    assert data["camera_enabled"] is False
    camera = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "CAMERA_ENABLE"},
    )
    assert camera.status_code == 200
    assert camera.json()["data"]["device"]["camera_enabled"] is False
    rotate = client.post(
        f"/api/lifesaver/devices/{device_id}/commands",
        headers=headers,
        json={"command": "ROTATE_LEFT"},
    )
    assert rotate.status_code == 200
    assert rotate.json()["data"]["device"]["rotation_moving"] is False


def test_camera_authorization_defaults_off():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    assert home["camera_enabled"] is False
    enabled = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "CAMERA_ENABLE"},
    )
    assert enabled.status_code == 200
    assert enabled.json()["data"]["device"]["camera_enabled"] is True
    disabled = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "CAMERA_DISABLE"},
    )
    assert disabled.json()["data"]["device"]["camera_enabled"] is False


def test_rotation_stop_is_always_accepted():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "ROTATE_RIGHT"},
    )
    stop = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "ROTATE_STOP"},
    )
    assert stop.status_code == 200
    device = stop.json()["data"]["device"]
    assert device["rotation_state"] == "stopped"
    assert device["rotation_moving"] is False
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "PRIVACY_ENABLE"},
    )
    stop_again = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "ROTATE_STOP"},
    )
    assert stop_again.status_code == 200
    assert stop_again.json()["data"]["device"]["rotation_moving"] is False


def test_fall_simulation_is_local_only():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    result = client.post(
        f"/api/lifesaver/devices/{home['id']}/simulate-fall",
        headers=headers,
    )
    assert result.status_code == 200, result.text
    data = result.json()["data"]
    assert data["emergency_services_contacted"] is False
    assert data["external_message_sent"] is False
    assert data["needs_human_review"] is True
    assert data["label"] == "SIMULATION"
    assert "Possible fall or safety event detected" in data["summary"]
    assert data["event"]["emergency_services_contacted"] is False
    coord = client.get("/api/lifesaver/coordination", headers=headers)
    assert coord.status_code == 200
    cards = coord.json()["data"]["cards"]
    safety = [card for card in cards if card["kind"] == "safety"]
    assert safety
    assert safety[0]["priority"] == "HIGH"
    assert safety[0]["needs_human_review"] is True
    assert safety[0]["emergency_services_contacted"] is False
    notices = client.get("/api/lifesaver/notifications", headers=headers)
    assert notices.status_code == 200
    queued = [row for row in notices.json()["data"] if row["notification_type"] == "safety_event_review"]
    assert queued
    assert queued[0]["status"] == "queued_local"
    assert queued[0]["external_message_sent"] is False
    with SessionLocal() as db:
        events = db.query(LifesaverDeviceEvent).all()
        assert events
        assert all(row.emergency_services_contacted is False for row in events)
        outbox = db.query(LifesaverNotificationOutbox).filter(
            LifesaverNotificationOutbox.notification_type == "safety_event_review"
        ).all()
        assert outbox
        assert all(row.status == "queued_local" for row in outbox)


def test_device_health_and_local_audit():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    health = client.get(f"/api/lifesaver/devices/{home['id']}/health", headers=headers)
    assert health.status_code == 200
    snapshot = health.json()["data"]
    assert snapshot["online"] is True
    assert snapshot["privacy_mode"] is False
    assert snapshot["camera_enabled"] is False
    assert snapshot["external_device_contacted"] is False
    assert snapshot["medical_certified"] is False
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "DEVICE_PING"},
    )
    audit = client.get("/api/lifesaver/audit", headers=headers)
    rows = audit.json()["data"]
    actions = {row["action"] for row in rows}
    assert "device.command" in actions
    assert "device.health" in actions
    for row in rows:
        metadata = row.get("metadata") or {}
        assert "password" not in metadata
        assert "token" not in metadata
        assert "secret" not in metadata
        assert "body" not in metadata
    with SessionLocal() as db:
        commands = db.query(LifesaverDeviceCommand).all()
        assert commands
        assert all(row.simulated is True for row in commands)


def test_video_session_requires_privacy_and_camera_gate():
    client = _client()
    headers = _ready(client)
    home = _create_hub(client, headers, "HOME_HUB")
    requested = client.post(
        f"/api/lifesaver/devices/{home['id']}/video-sessions",
        headers=headers,
        json={},
    )
    assert requested.status_code == 200, requested.text
    session_id = requested.json()["data"]["id"]
    assert requested.json()["data"]["media_stored"] is False
    blocked = client.post(
        f"/api/lifesaver/devices/video-sessions/{session_id}/accept",
        headers=headers,
    )
    assert blocked.status_code == 409
    declined = client.post(
        f"/api/lifesaver/devices/video-sessions/{session_id}/decline",
        headers=headers,
    )
    assert declined.status_code == 200
    assert declined.json()["data"]["status"] == "declined"


def test_car_hub_safe_mode_and_no_vehicle_control():
    client = _client()
    headers = _ready(client)
    car = _create_hub(client, headers, "CAR_HUB")
    fall = client.post(f"/api/lifesaver/devices/{car['id']}/simulate-fall", headers=headers)
    assert fall.status_code == 409
    ping = client.post(
        f"/api/lifesaver/devices/{car['id']}/commands",
        headers=headers,
        json={"command": "CONNECTION_TEST"},
    )
    assert ping.status_code == 200
    device = ping.json()["data"]["device"]
    assert device["vehicle_control"] is False
    assert "does not control the vehicle" in (device["vehicle_disclaimer"] or "").lower()
    camera = client.post(
        f"/api/lifesaver/devices/{car['id']}/commands",
        headers=headers,
        json={"command": "CAMERA_ENABLE"},
    )
    assert camera.status_code == 409


def test_hardware_consent_and_unknown_command():
    client = _client()
    headers = auth_headers(client, "rider@amicor.local")
    bootstrap_profile(client, headers)
    client.post(
        "/api/lifesaver/consents",
        headers=headers,
        json={"consent_type": "hardware_simulation", "granted": False},
    )
    denied = client.post(
        "/api/lifesaver/devices/simulated",
        headers=headers,
        json={"device_type": "HOME_HUB"},
    )
    assert denied.status_code == 403
    grant_consents(client, headers)
    home = _create_hub(client, headers, "HOME_HUB")
    unknown = client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "LAUNCH_MISSILES"},
    )
    assert unknown.status_code == 422


def test_no_frozen_product_writes_or_external_calls():
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
    driver_before = _driver_snapshot()
    delivery_tables = [name for name in names if name.startswith("delivery") or "delivery_" in name]
    delivery_before = {name: _count(name) for name in delivery_tables}
    home = _create_hub(client, headers, "HOME_HUB")
    _create_hub(client, headers, "CAR_HUB")
    client.post(
        f"/api/lifesaver/devices/{home['id']}/commands",
        headers=headers,
        json={"command": "CAMERA_ENABLE"},
    )
    client.post(f"/api/lifesaver/devices/{home['id']}/simulate-fall", headers=headers)
    with SessionLocal() as db:
        assert db.query(HealthISFRide).count() == rides_before
    assert _count("nova_freight_shipments") == freight_before
    assert _driver_snapshot() == driver_before
    assert {name: _count(name) for name in delivery_tables} == delivery_before


def test_hardware_source_stays_isolated():
    banned = (
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
        "socket.socket",
    )
    hardware = LIFESAVER_ROOT / "hardware"
    for path in hardware.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path} contains {token}"
        assert "911" not in text or "does not contact" in text or "emergency_services_contacted" in text


def test_devices_ui_and_mobile_contract():
    client = _client()
    page = client.get("/lifesaver")
    assert page.status_code == 200
    html = page.text
    assert 'id="view-devices"' in html
    assert 'data-view="devices"' in html
    js = client.get("/static/lifesaver/lifesaver.js").text
    css = client.get("/static/lifesaver/lifesaver.css").text
    assert "Camera On" in js
    assert "Camera Off" in js
    assert "Privacy Mode" in js
    assert "Rotate Left" in js
    assert "Rotate Right" in js
    assert "ROTATE_STOP" in js
    assert "Simulate Fall Event · SIMULATION" in js
    assert "Connection Test" in js
    assert "Audio Test" in js
    assert "Safe Mode" in js
    assert "Device Health" in js
    assert "Camera:" in js
    assert "Privacy:" in js
    assert "hub-stop" in js
    assert "SIMULATION" in js
    assert "--ls-tap: 48px" in css
    assert "hub-stop" in css
    assert "bottom-nav" in css
    assert "repeat(6, 1fr)" in css
    assert "overflow-x: scroll" not in css
    source = STATIC.joinpath("lifesaver.js").read_text(encoding="utf-8")
    assert "zoom.us" not in source.lower()
    assert "twilio" not in source.lower()
    assert "No third-party video provider is connected" in js
