"""Device-health snapshot from simulated adapter state."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.camera_contract import camera_status
from app.modules.lifesaver.hardware.hardware_mode import local_pi_enabled
from app.modules.lifesaver.hardware.models import LifesaverDevice
from app.modules.lifesaver.hardware.motor_contract import motor_snapshot
from app.modules.lifesaver.hardware.registry import DEVICE_CAR_HUB, DEVICE_HOME_HUB, capabilities_for


def build_health(device: LifesaverDevice, state: dict[str, Any]) -> dict[str, Any]:
    privacy = bool(state.get("privacy_mode"))
    online = device.status not in {"OFFLINE", "MAINTENANCE"}
    warnings: list[str] = []
    if privacy:
        warnings.append("Privacy mode is on. Camera and rotation tracking are disabled.")
    if not online:
        warnings.append("Device is offline. Commands that require a live adapter are simulated locally only.")
    if device.device_type == DEVICE_CAR_HUB and state.get("safe_drive_mode"):
        warnings.append("Safe vehicle-use mode is on. No vehicle control is available.")
    return {
        "device_id": device.id,
        "online": online,
        "status": device.status,
        "last_seen": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "software_version": device.software_version,
        "firmware_version": device.firmware_version,
        "adapter_status": "simulated_ready" if online else "simulated_offline",
        "adapter_name": device.adapter_name,
        "camera_available": device.device_type == DEVICE_HOME_HUB and not privacy,
        "microphone_available": not privacy,
        "speaker_available": True,
        "motor_available": device.device_type == DEVICE_HOME_HUB and not privacy,
        "sensor_available": device.device_type == DEVICE_HOME_HUB,
        "privacy_mode": privacy,
        "camera_enabled": bool(state.get("camera_enabled")) and not privacy,
        "microphone_enabled": bool(state.get("microphone_enabled")) and not privacy,
        "battery_percent": state.get("battery_percent"),
        "temperature_c": state.get("temperature_c"),
        "orientation_deg": state.get("orientation_deg", 0) if device.device_type == DEVICE_HOME_HUB else None,
        "pairing_state": getattr(device, "pairing_state", None) or "PAIRED",
        "adapter_type": getattr(device, "adapter_type", None) or "simulated",
        "simulation_badge": "LOCAL PROTOTYPE" if local_pi_enabled() and getattr(device, "adapter_type", "") in {"local_pi", "raspberry_pi"} else "SIMULATION",
        "connected": online and getattr(device, "pairing_state", "PAIRED") != "UNPAIRED",
        "paired": getattr(device, "pairing_state", "PAIRED") not in {"UNPAIRED", "DISCOVERED", "PENDING_PAIR"},
        "local_host_label": getattr(device, "local_ip", None) or "local",
        "motor_state": motor_snapshot(state)["moving_state"],
        "power_status": state.get("power") or "mains",
        "last_command": state.get("last_command"),
        "last_acknowledgement": state.get("last_acknowledgement"),
        "safety_event_status": state.get("safety_event_status") or "none",
        "camera_contract": camera_status(state, privacy=privacy),
        "capabilities": list(capabilities_for(device.device_type)),
        "warnings": warnings,
        "external_device_contacted": False,
        "medical_certified": False,
    }
