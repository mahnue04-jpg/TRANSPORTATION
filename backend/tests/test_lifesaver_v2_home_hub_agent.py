"""Home Hub agent, emulator, recovery, and privacy contracts. Local only."""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")
os.environ.setdefault("AMICOR_ENVIRONMENT", "local")

from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from app.auth import ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal, engine
from app.main import app
from app.modules.health_isf.models import HealthISFRide
from app.modules.lifesaver.hardware.home_hub_host import ensure_agent_path
from app.modules.lifesaver.models import ensure_lifesaver_schema
from tests.lifesaver_test_helpers import auth_headers, bootstrap_profile, grant_consents

ensure_agent_path()
from lifesaver_home_hub.emulator import reset_emulator
from lifesaver_home_hub.motor import MotorController

REPO = Path(__file__).resolve().parents[2]


def _client() -> TestClient:
    reset_emulator()
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _ready(client: TestClient) -> dict[str, str]:
    headers = auth_headers(client, "rider@amicor.local")
    grant_consents(client, headers)
    bootstrap_profile(client, headers)
    return headers


def _pair(client: TestClient) -> str:
    paired = client.post("/api/lifesaver/home-hub-agent/pair")
    assert paired.status_code == 200, paired.text
    return paired.json()["data"]["device_token"]


def test_health_status_and_version():
    client = _client()
    health = client.get("/api/lifesaver/home-hub-agent/health")
    assert health.status_code == 200
    body = health.json()["data"]
    assert body["agent"] == "lifesaver-home-hub-agent"
    assert body["version"] == "0.1.0-dev"
    assert body["real_camera_streaming"] is False
    status = client.get("/api/lifesaver/home-hub-agent/status")
    assert status.json()["data"]["hardware_note"] == "NOT CONNECTED TO REAL HARDWARE"


def test_pair_token_and_wrong_token_rejected():
    client = _client()
    token = _pair(client)
    ok = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "CAMERA_ENABLE", "device_token": token},
    )
    assert ok.status_code == 200
    denied = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "CAMERA_ENABLE", "device_token": "wrong-token"},
    )
    assert denied.status_code == 403


def test_unpaired_command_rejected_except_stop():
    client = _client()
    stop = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "STOP_MOTOR"})
    assert stop.status_code == 200
    cam = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "CAMERA_ENABLE"})
    assert cam.status_code == 403


def test_privacy_blocks_and_off_does_not_reenable():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "CAMERA_ENABLE", "device_token": token})
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "MIC_ENABLE", "device_token": token})
    privacy = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "PRIVACY_ENABLE", "device_token": token})
    twin = privacy.json()["data"]["twin"]
    assert twin["privacy_mode"] is True
    assert twin["camera"]["state"] in {"off", "privacy-blocked"}
    assert twin["microphone"]["state"] in {"off", "privacy-blocked"}
    assert twin["tracking"]["state"] == "PRIVACY_BLOCKED"
    off = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "PRIVACY_DISABLE", "device_token": token})
    restored = off.json()["data"]["twin"]
    assert restored["privacy_mode"] is False
    assert restored["camera"]["state"] == "off"
    assert restored["microphone"]["state"] == "off"


def test_physical_privacy_switch_overrides_software():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/privacy-switch", json={"pressed": True})
    off = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "PRIVACY_DISABLE", "device_token": token})
    assert off.json()["data"]["twin"]["privacy_mode"] is True
    cam = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "CAMERA_ENABLE", "device_token": token})
    assert cam.json()["data"]["twin"]["camera"]["privacy_blocked"] is True


def test_motor_stop_priority_and_invalid_angle():
    client = _client()
    token = _pair(client)
    left = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_LEFT", "device_token": token})
    assert left.json()["data"]["twin"]["motor"]["motor_state"] == "MOVING_LEFT"
    stop = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "STOP_MOTOR", "device_token": token})
    assert stop.json()["data"]["twin"]["motor"]["motor_state"] == "STOPPED"
    bad = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "ROTATE_TO_ANGLE", "angle": 400, "device_token": token},
    )
    assert bad.status_code == 422
    motor = MotorController()
    motor.apply("ROTATE_RIGHT")
    motor.apply("NETWORK_LOSS")
    assert motor.state == "STOPPED"


def test_physical_stop_cancels_movement():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_RIGHT", "device_token": token})
    stopped = client.post("/api/lifesaver/home-hub-agent/physical-stop")
    assert stopped.json()["data"]["motor"]["motor_state"] == "STOPPED"
    assert stopped.json()["data"]["motor"]["physical_stop"] is True


def test_heartbeat_misses_and_recovery():
    client = _client()
    beat = client.post("/api/lifesaver/home-hub-agent/heartbeat")
    assert beat.json()["data"]["heartbeat_state"] == "ONLINE"
    client.post("/api/lifesaver/home-hub-agent/heartbeat/miss")
    second = client.post("/api/lifesaver/home-hub-agent/heartbeat/miss")
    assert second.json()["data"]["heartbeat_state"] == "DEGRADED"
    client.post("/api/lifesaver/home-hub-agent/heartbeat/miss")
    offline = client.post("/api/lifesaver/home-hub-agent/heartbeat/miss")
    assert offline.json()["data"]["heartbeat_state"] == "OFFLINE"
    recover = client.post("/api/lifesaver/home-hub-agent/faults", json={"kind": "network_reconnect"})
    assert recover.json()["data"]["heartbeat"]["heartbeat_state"] in {"ONLINE", "DEGRADED"}


def test_safety_pipeline_never_calls_emergency_services():
    client = _client()
    event = client.post("/api/lifesaver/home-hub-agent/events", json={"event_type": "POSSIBLE_FALL"})
    body = event.json()["data"]
    assert body["emergency_services_contacted"] is False
    assert body["human_review_required"] is True
    reviewed = client.post(
        f"/api/lifesaver/home-hub-agent/events/{body['event_id']}/review",
        json={"review_status": "FALSE_ALARM"},
    )
    assert reviewed.json()["data"]["emergency_services_contacted"] is False
    assert reviewed.json()["data"]["review_status"] == "FALSE_ALARM"


def test_video_privacy_and_no_vendor():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "PRIVACY_ENABLE", "device_token": token})
    blocked = client.post("/api/lifesaver/home-hub-agent/video", json={"action": "REQUEST"})
    assert blocked.status_code == 409
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "PRIVACY_DISABLE", "device_token": token})
    ringing = client.post("/api/lifesaver/home-hub-agent/video", json={"action": "REQUEST"})
    assert ringing.json()["data"]["state"] == "RINGING"
    accepted = client.post("/api/lifesaver/home-hub-agent/video", json={"action": "ACCEPT"})
    assert accepted.json()["data"]["state"] == "ACTIVE_SIMULATED"
    ended = client.post("/api/lifesaver/home-hub-agent/video", json={"action": "END"})
    assert ended.json()["data"]["state"] == "ENDED"
    js = Path(__file__).resolve().parents[1] / "static" / "lifesaver" / "lifesaver.js"
    source = js.read_text(encoding="utf-8")
    assert "Home Hub digital twin" in source
    assert "HOME HUB DIAGNOSTICS" in source
    assert "zoom.us" not in source.lower()


def test_self_test_wizard_and_car_contract():
    client = _client()
    _pair(client)
    test = client.post("/api/lifesaver/home-hub-agent/self-test")
    assert test.json()["data"]["overall"] in {"PASS", "DEGRADED"}
    wizard = client.get("/api/lifesaver/home-hub-agent/wizard")
    assert "pair" in wizard.json()["data"]["steps"]
    step = client.post("/api/lifesaver/home-hub-agent/wizard/step", json={"step": 10})
    assert step.status_code == 200
    car = client.get("/api/lifesaver/home-hub-agent/car-hub-contract")
    assert car.json()["data"]["vehicle_control"] is False
    assert "steering" in car.json()["data"]["rejected"]


def test_idempotent_command_and_audit_hygiene():
    client = _client()
    token = _pair(client)
    first = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "DEVICE_PING", "client_command_id": "hub-ping-1", "device_token": token},
    )
    again = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "DEVICE_PING", "client_command_id": "hub-ping-1", "device_token": token},
    )
    assert again.json()["data"]["idempotent"] is True
    assert again.json()["data"]["command"]["command_id"] == first.json()["data"]["command"]["command_id"]
    from lifesaver_home_hub.emulator import get_emulator
    for row in get_emulator().audit.recent():
        blob = str(row).lower()
        assert token.lower() not in blob
        assert "password" not in blob
        assert "sk_live_" not in blob


def test_vehicle_rejected_and_frozen_surfaces():
    client = _client()
    token = _pair(client)
    steer = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "STEER", "device_token": token},
    )
    assert steer.status_code == 422
    names = set(inspect(engine).get_table_names())
    with SessionLocal() as db:
        rides = db.query(HealthISFRide).count()
    freight = 0
    if "nova_freight_shipments" in names:
        with engine.connect() as conn:
            freight = int(conn.execute(text("SELECT COUNT(*) FROM nova_freight_shipments")).scalar() or 0)
    client.post("/api/lifesaver/home-hub-agent/events", json={"event_type": "POSSIBLE_FALL"})
    with SessionLocal() as db:
        assert db.query(HealthISFRide).count() == rides
    if "nova_freight_shipments" in names:
        with engine.connect() as conn:
            assert int(conn.execute(text("SELECT COUNT(*) FROM nova_freight_shipments")).scalar() or 0) == freight
    banned = ("from app.modules.health_isf", "from app.core.nova", "import stripe", "socket.socket", "sk_live_")
    agent = REPO / "hardware" / "lifesaver-home-hub"
    for path in agent.rglob("*.py"):
        text_blob = path.read_text(encoding="utf-8")
        for token_name in banned:
            assert token_name not in text_blob, f"{path} contains {token_name}"
