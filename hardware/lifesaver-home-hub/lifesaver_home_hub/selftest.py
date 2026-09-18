"""Startup self-test. Adapters are simulated; GPIO is never opened."""
from __future__ import annotations

from typing import Any

from lifesaver_home_hub.emulator import HomeHubEmulator


def run_self_test(hub: HomeHubEmulator) -> dict[str, Any]:
    components = {
        "agent": "PASS" if hub.device_state in {"ready", "degraded", "restarting"} else "FAIL",
        "identity": "PASS" if hub.identity.device_id else "FAIL",
        "config": "PASS" if hub.config.host else "FAIL",
        "token": "PASS" if hub.identity.device_token or hub.identity.pairing_state == "UNPAIRED" else "DEGRADED",
        "network": "FAIL" if hub.network["state"] == "disconnected" else ("DEGRADED" if hub.network["state"] == "degraded" else "PASS"),
        "camera": "DEGRADED" if hub.camera["failed"] else "PASS",
        "microphone": "DEGRADED" if hub.mic["failed"] else "PASS",
        "speaker": "PASS" if hub.speaker["available"] else "DEGRADED",
        "motor": "FAIL" if hub.motor.state == "FAULT" else ("DEGRADED" if hub.motor.obstruction else "PASS"),
        "rotation_calibration": "PASS" if hub.motor.home_calibrated else "DEGRADED",
        "sensors": "PASS",
        "storage": "PASS",
        "temperature": "FAIL" if hub.thermal["state"] == "critical" else ("DEGRADED" if hub.thermal["state"] == "high" else "PASS"),
        "privacy_switch": "PASS",
        "stop_button": "PASS",
        "power": "DEGRADED" if hub.power["low_battery"] or not hub.power["ac"] else "PASS",
    }
    if "FAIL" in components.values():
        overall = "FAIL"
    elif "DEGRADED" in components.values():
        overall = "DEGRADED"
    else:
        overall = "PASS"
    result = {
        "overall": overall,
        "components": components,
        "real_hardware": False,
        "agent_version": hub.digital_twin()["agent_version"],
    }
    hub.self_test = result
    return result
