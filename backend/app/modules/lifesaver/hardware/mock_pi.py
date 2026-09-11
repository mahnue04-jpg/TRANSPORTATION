"""In-process mock Raspberry Pi Home Hub. Localhost / explicit local test only."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import os

from app.helpers import now
from app.modules.lifesaver.hardware.adapters import simulated_home_hub
from app.modules.lifesaver.hardware.command_contract import normalize_command
from app.modules.lifesaver.hardware.network_safety import reject_public_device_host
from app.responses import normalize_success


def _reject_if_production() -> None:
    env = (os.getenv("AMICOR_ENVIRONMENT") or "").strip().lower()
    if env in {"production", "prod"}:
        raise HTTPException(status_code=404, detail="Mock Pi is local-only.")

router = APIRouter(prefix="/mock-pi", tags=["lifesaver-mock-pi"])

_STATE: dict[str, Any] = simulated_home_hub.default_state()
_EVENTS: list[dict[str, Any]] = []


class MockCommand(BaseModel):
    command: str
    motion_detected: bool | None = None
    host: str = Field(default="127.0.0.1", max_length=64)


def snapshot() -> dict[str, Any]:
    privacy = bool(_STATE.get("privacy_mode"))
    return {
        "device_type": "HOME_HUB",
        "hardware_model": "amicor-home-hub-prototype",
        "firmware_version": "mock-pi-0.1",
        "local_ip": "127.0.0.1",
        "connection_state": "ONLINE",
        "battery_level": _STATE.get("battery_percent"),
        "temperature": _STATE.get("temperature_c"),
        "camera_present": True,
        "microphone_present": True,
        "speaker_present": True,
        "rotation_supported": True,
        "fall_sensor_supported": True,
        "video_supported": True,
        "last_seen_at": now().isoformat(),
        "capabilities": list(simulated_home_hub.default_state().keys()),
        "privacy_mode": privacy,
        "camera_enabled": bool(_STATE.get("camera_enabled")) and not privacy,
        "orientation_deg": _STATE.get("orientation_deg", 0),
        "simulated": True,
        "external_device_connected": False,
    }


@router.get("/health")
def mock_health():
    _reject_if_production()
    return normalize_success(data={"ok": True, "adapter": "mock_raspberry_pi", "simulated": True})


@router.get("/status")
def mock_status():
    _reject_if_production()
    return normalize_success(data=snapshot())


@router.get("/events")
def mock_events():
    _reject_if_production()
    return normalize_success(data=list(_EVENTS))


@router.post("/commands")
def mock_commands(payload: MockCommand):
    _reject_if_production()
    reject_public_device_host(payload.host)
    command = normalize_command(payload.command)
    extra = {}
    if payload.motion_detected is not None:
        extra["motion_detected"] = payload.motion_detected
    if command == "SIMULATE_FALL_EVENT":
        event = {
            "event_type": "SIMULATED_FALL_EVENT",
            "summary": "Possible fall or safety event detected.",
            "emergency_services_contacted": False,
            "simulated": True,
            "detected_at": now().isoformat(),
        }
        _EVENTS.insert(0, event)
        return normalize_success(data={"status": "COMPLETED", "event": event, "device": snapshot()})
    global _STATE
    _STATE, device_status = simulated_home_hub.apply_command(_STATE, command, extra)
    return normalize_success(
        data={"status": "COMPLETED", "device_status": device_status, "device": snapshot(), "command": command}
    )


def handle_in_process(command: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Used by the LAN adapter. No sockets."""
    extra = extra or {}
    command = normalize_command(command)
    if command == "SIMULATE_FALL_EVENT":
        event = {
            "event_type": "SIMULATED_FALL_EVENT",
            "summary": "Possible fall or safety event detected.",
            "emergency_services_contacted": False,
            "simulated": True,
            "detected_at": now().isoformat(),
        }
        _EVENTS.insert(0, event)
        return {"status": "COMPLETED", "event": event, "device": snapshot()}
    global _STATE
    _STATE, device_status = simulated_home_hub.apply_command(_STATE, command, extra)
    return {"status": "COMPLETED", "device_status": device_status, "device": snapshot(), "command": command}


def reset_mock() -> None:
    global _STATE, _EVENTS
    _STATE = simulated_home_hub.default_state()
    _EVENTS = []
