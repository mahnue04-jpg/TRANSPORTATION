"""In-process Car Hub simulator. No vehicle control, CAN, or OEM APIs."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.adapters import audio_adapter
from app.modules.lifesaver.hardware.registry import (
    CMD_AUDIO_TEST,
    CMD_CONNECTION_TEST,
    CMD_DEVICE_PING,
    CMD_DEVICE_RESTART_SIMULATED,
    CMD_DISPLAY_DISABLE,
    CMD_DISPLAY_ENABLE,
    CMD_PRIVACY_DISABLE,
    CMD_PRIVACY_ENABLE,
    CMD_SAFE_MODE_DISABLE,
    CMD_SAFE_MODE_ENABLE,
    CMD_SET_OFFLINE,
    CMD_SET_ONLINE,
    NO_VEHICLE_CONTROL,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_PRIVACY_MODE,
)


def default_state() -> dict[str, Any]:
    return {
        "display_active": True,
        "microphone_enabled": False,
        "speaker_available": True,
        "privacy_mode": False,
        "network_status": "connected_simulated",
        "safe_drive_mode": True,
        "nova_lifesaver_link": "simulated_ready",
        "vehicle_control": False,
        "note": NO_VEHICLE_CONTROL,
    }


def apply_command(state: dict[str, Any], command: str, extra: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    extra = extra or {}
    if command in {CMD_DEVICE_PING, "GET_STATUS", "GET_DEVICE_HEALTH", "LIFESAVER_LINK_STATUS", "NOVA_LINK_STATUS"}:
        state["lifesaver_link"] = state.get("nova_lifesaver_link") or "simulated_ready"
        return state, STATUS_ONLINE
    if command == CMD_SET_ONLINE:
        return state, STATUS_ONLINE
    if command == CMD_SET_OFFLINE:
        state["network_status"] = "offline_simulated"
        state["nova_lifesaver_link"] = "simulated_offline"
        return state, STATUS_OFFLINE
    if command == CMD_CONNECTION_TEST:
        state["network_status"] = "connected_simulated"
        state["nova_lifesaver_link"] = "simulated_ready"
        state["last_connection_test"] = "ok_simulated"
        return state, STATUS_ONLINE
    if command == CMD_AUDIO_TEST:
        audio_adapter.speaker_test(state)
        return state, STATUS_ONLINE
    if command == CMD_SAFE_MODE_ENABLE:
        state["safe_drive_mode"] = True
        return state, STATUS_ONLINE
    if command == CMD_SAFE_MODE_DISABLE:
        state["safe_drive_mode"] = False
        return state, STATUS_ONLINE
    if command == CMD_DISPLAY_ENABLE:
        state["display_active"] = True
        return state, STATUS_ONLINE
    if command == CMD_DISPLAY_DISABLE:
        state["display_active"] = False
        return state, STATUS_ONLINE
    if command == CMD_PRIVACY_ENABLE:
        state["privacy_mode"] = True
        state["microphone_enabled"] = False
        return state, STATUS_PRIVACY_MODE
    if command == CMD_PRIVACY_DISABLE:
        state["privacy_mode"] = False
        return state, STATUS_ONLINE
    if command == CMD_DEVICE_RESTART_SIMULATED:
        return default_state(), STATUS_ONLINE
    extra  # unused on purpose
    return state, STATUS_ONLINE
