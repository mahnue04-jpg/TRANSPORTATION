"""End-to-end local prototype scenarios and chaos cases."""
from __future__ import annotations

import os

os.environ.setdefault("AMICOR_SKIP_WMI_PLATFORM_QUERY", "1")
os.environ.setdefault("AMICOR_ENVIRONMENT", "local")

from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.main import app
from app.modules.lifesaver.hardware.home_hub_host import ensure_agent_path
from app.modules.lifesaver.models import ensure_lifesaver_schema

ensure_agent_path()
from lifesaver_home_hub.emulator import reset_emulator


def _client() -> TestClient:
    reset_emulator()
    ensure_auth_schema()
    seed_default_users()
    ensure_lifesaver_schema()
    return TestClient(app)


def _pair(client: TestClient) -> str:
    return client.post("/api/lifesaver/home-hub-agent/pair").json()["data"]["device_token"]


def test_scenario_a_boot_pair_self_test():
    client = _client()
    assert client.get("/api/lifesaver/home-hub-agent/health").status_code == 200
    token = _pair(client)
    assert token
    result = client.post("/api/lifesaver/home-hub-agent/self-test")
    assert result.json()["data"]["overall"] in {"PASS", "DEGRADED"}


def test_scenario_b_camera_toggle():
    client = _client()
    token = _pair(client)
    on = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "CAMERA_ENABLE", "device_token": token})
    assert on.json()["data"]["twin"]["camera"]["state"] == "on"
    off = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "CAMERA_DISABLE", "device_token": token})
    assert off.json()["data"]["twin"]["camera"]["state"] == "off"


def test_scenario_c_rotate_then_stop():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_RIGHT", "device_token": token})
    stop = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_STOP", "device_token": token})
    assert stop.json()["data"]["twin"]["motor"]["motor_state"] == "STOPPED"


def test_scenario_d_privacy_while_enabled():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "CAMERA_ENABLE", "device_token": token})
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "MIC_ENABLE", "device_token": token})
    privacy = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "PRIVACY_ENABLE", "device_token": token})
    twin = privacy.json()["data"]["twin"]
    assert twin["camera"]["privacy_blocked"] is True
    assert twin["tracking"]["state"] == "PRIVACY_BLOCKED"


def test_scenario_e_and_f_fall_review():
    client = _client()
    event = client.post("/api/lifesaver/home-hub-agent/events", json={"event_type": "POSSIBLE_FALL"}).json()["data"]
    ack = client.post(
        f"/api/lifesaver/home-hub-agent/events/{event['event_id']}/review",
        json={"review_status": "ACKNOWLEDGED"},
    )
    assert ack.json()["data"]["review_status"] == "ACKNOWLEDGED"
    second = client.post("/api/lifesaver/home-hub-agent/events", json={"event_type": "POSSIBLE_FALL"}).json()["data"]
    false = client.post(
        f"/api/lifesaver/home-hub-agent/events/{second['event_id']}/review",
        json={"review_status": "FALSE_ALARM"},
    )
    assert false.json()["data"]["review_status"] == "FALSE_ALARM"
    assert false.json()["data"]["emergency_services_contacted"] is False


def test_scenario_g_video_session():
    client = _client()
    _pair(client)
    client.post("/api/lifesaver/home-hub-agent/video", json={"action": "REQUEST"})
    client.post("/api/lifesaver/home-hub-agent/video", json={"action": "ACCEPT"})
    ended = client.post("/api/lifesaver/home-hub-agent/video", json={"action": "END"})
    assert ended.json()["data"]["state"] == "ENDED"


def test_scenario_h_and_i_offline_and_restart():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/faults", json={"kind": "network_disconnect"})
    twin = client.get("/api/lifesaver/home-hub-agent/twin").json()["data"]
    assert "OFFLINE" in (twin.get("offline_banner") or "")
    client.post("/api/lifesaver/home-hub-agent/faults", json={"kind": "network_reconnect"})
    client.post("/api/lifesaver/home-hub-agent/faults", json={"kind": "agent_restart"})
    health = client.get("/api/lifesaver/home-hub-agent/status").json()["data"]
    assert health["privacy_mode"] is False
    ping = client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "DEVICE_PING", "device_token": token})
    assert ping.status_code == 200


def test_scenario_j_wrong_token():
    client = _client()
    _pair(client)
    denied = client.post(
        "/api/lifesaver/home-hub-agent/commands",
        json={"command": "CAMERA_ENABLE", "device_token": "nope"},
    )
    assert denied.status_code == 403


def test_chaos_obstruction_high_temp_and_conflicting_rotation():
    client = _client()
    token = _pair(client)
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_LEFT", "device_token": token})
    client.post("/api/lifesaver/home-hub-agent/faults", json={"kind": "motor_obstruction"})
    motor = client.get("/api/lifesaver/home-hub-agent/twin").json()["data"]["motor"]
    assert motor["motor_state"] in {"STOPPED", "OBSTRUCTED"}
    client.post("/api/lifesaver/home-hub-agent/faults", json={"kind": "high_temperature"})
    temp = client.get("/api/lifesaver/home-hub-agent/twin").json()["data"]
    assert temp["thermal"]["state"] == "high"
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_LEFT", "device_token": token})
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "ROTATE_RIGHT", "device_token": token})
    client.post("/api/lifesaver/home-hub-agent/commands", json={"command": "STOP_MOTOR", "device_token": token})
    assert client.get("/api/lifesaver/home-hub-agent/twin").json()["data"]["motor"]["motor_state"] == "STOPPED"
