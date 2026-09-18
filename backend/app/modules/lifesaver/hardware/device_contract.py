"""JSON request/response contract for a future Raspberry Pi Home Hub."""
from __future__ import annotations

from typing import Any

from app.helpers import now
from app.modules.lifesaver.hardware.hardware_mode import hardware_mode


def command_request(
    *,
    device_id: str,
    command: str,
    command_id: str | None = None,
    angle: float | None = None,
    acknowledgement_required: bool = True,
) -> dict[str, Any]:
    payload = {
        "device_id": device_id,
        "device_type": "HOME_HUB",
        "command": command,
        "command_id": command_id,
        "command_timestamp": now().isoformat(),
        "acknowledgement_required": acknowledgement_required,
        "media_requested": False,
        "emergency_services": False,
    }
    if angle is not None:
        payload["requested_angle"] = angle
    return payload


def command_response(*, request: dict[str, Any], status: str, state: dict[str, Any], failure_reason: str | None = None) -> dict[str, Any]:
    return {
        "device_id": request.get("device_id"),
        "device_type": "HOME_HUB",
        "serial": state.get("serial_placeholder") or "UNASSIGNED",
        "model": state.get("hardware_model") or "raspberry-pi-class-home-hub",
        "firmware_version": state.get("firmware_version") or "proto-pending",
        "ip_address": state.get("local_ip") or "127.0.0.1",
        "pairing_state": state.get("pairing_state") or "PAIRED",
        "online": state.get("status") not in {"OFFLINE", "MAINTENANCE"},
        "camera_state": "off" if state.get("privacy_mode") else ("on" if state.get("camera_enabled") else "off"),
        "microphone_state": "off" if state.get("privacy_mode") else ("on" if state.get("microphone_enabled") else "off"),
        "privacy_state": "on" if state.get("privacy_mode") else "off",
        "rotation_angle": state.get("orientation_deg", 0),
        "motor_state": state.get("motor_state") or ("moving" if state.get("rotation_moving") else "stopped"),
        "temperature": state.get("temperature_c"),
        "battery_power_state": state.get("power_state") or state.get("power") or "MAINS_POWER",
        "physical_battery_connected": False,
        "last_seen": now().isoformat(),
        "command_id": request.get("command_id"),
        "command_status": status,
        "command_timestamp": request.get("command_timestamp"),
        "acknowledgement": status in {"ACKNOWLEDGED", "COMPLETED"},
        "failure_reason": failure_reason,
        "safety_event_status": state.get("safety_event_status") or "none",
        "hardware_mode": hardware_mode(),
        "media_stored": False,
        "emergency_services_contacted": False,
    }


def contract_example() -> dict[str, Any]:
    request = command_request(device_id="example-home-hub", command="DEVICE_PING", command_id="cmd-example")
    return {
        "request": request,
        "response": command_response(
            request=request,
            status="COMPLETED",
            state={"privacy_mode": False, "camera_enabled": False, "orientation_deg": 0, "power": "mains", "temperature_c": 31.2},
        ),
        "notes": [
            "Local LAN only. Public IPs are rejected.",
            "No video, audio, credentials, or journal contents are logged.",
            "emergency_services_contacted remains false.",
        ],
    }
