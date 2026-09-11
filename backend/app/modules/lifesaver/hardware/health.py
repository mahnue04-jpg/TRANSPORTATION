"""Device-health snapshot from simulated adapter state."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.models import LifesaverDevice
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
        "simulation_badge": "SIMULATION",
        "capabilities": list(capabilities_for(device.device_type)),
        "warnings": warnings,
        "external_device_contacted": False,
        "medical_certified": False,
    }
