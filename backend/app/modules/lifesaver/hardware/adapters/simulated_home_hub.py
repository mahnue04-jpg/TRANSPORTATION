"""In-process Home Hub simulator. Camera defaults off. No sockets."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.adapters import audio_adapter, camera_adapter, rotation_adapter, sensor_adapter
from app.modules.lifesaver.hardware.registry import (
    CMD_AUDIO_TEST,
    CMD_CAMERA_DISABLE,
    CMD_CAMERA_ENABLE,
    CMD_DEVICE_PING,
    CMD_DEVICE_RESTART_SIMULATED,
    CMD_MIC_DISABLE,
    CMD_MIC_ENABLE,
    CMD_PRIVACY_DISABLE,
    CMD_PRIVACY_ENABLE,
    CMD_ROTATE_HOME,
    CMD_ROTATE_LEFT,
    CMD_ROTATE_RIGHT,
    CMD_ROTATE_STOP,
    CMD_SENSOR_SAMPLE,
    CMD_SET_MOTION,
    CMD_SET_OFFLINE,
    CMD_SET_ONLINE,
    STATUS_OFFLINE,
    STATUS_ONLINE,
    STATUS_PRIVACY_MODE,
)


def default_state() -> dict[str, Any]:
    return {
        "camera_enabled": False,
        "microphone_enabled": False,
        "speaker_available": True,
        "privacy_mode": False,
        "rotation": "home",
        "rotation_moving": False,
        "orientation_deg": 0,
        "rotation_speed": "normal",
        "tracking_enabled": False,
        "motion_timeout_sec": 0,
        "obstruction": False,
        "motion_detected": False,
        "passive_observation": False,
        "battery_percent": 98,
        "temperature_c": 31.2,
        "power": "mains",
        "touchscreen": True,
        "wifi": True,
        "bluetooth": True,
    }


def apply_privacy(state: dict[str, Any], enabled: bool) -> dict[str, Any]:
    state["privacy_mode"] = bool(enabled)
    if enabled:
        state["camera_enabled"] = False
        state["microphone_enabled"] = False
        state["rotation_moving"] = False
        state["rotation"] = "stopped"
        state["motion_detected"] = False
        state["passive_observation"] = False
        state["tracking_enabled"] = False
    return state


def apply_command(state: dict[str, Any], command: str, extra: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
    extra = extra or {}
    if command in {CMD_DEVICE_PING, "GET_STATUS", "GET_DEVICE_HEALTH", "START_VIDEO_SESSION", "END_VIDEO_SESSION"}:
        return state, STATUS_ONLINE if not state.get("privacy_mode") else STATUS_PRIVACY_MODE
    if command == CMD_SET_ONLINE:
        return state, STATUS_ONLINE
    if command == CMD_SET_OFFLINE:
        return state, STATUS_OFFLINE
    if command == CMD_PRIVACY_ENABLE:
        return apply_privacy(state, True), STATUS_PRIVACY_MODE
    if command == CMD_PRIVACY_DISABLE:
        apply_privacy(state, False)
        return state, STATUS_ONLINE
    if command == CMD_CAMERA_ENABLE:
        camera_adapter.apply(state, True)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_CAMERA_DISABLE:
        camera_adapter.apply(state, False)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_MIC_ENABLE:
        audio_adapter.apply_mic(state, True)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_MIC_DISABLE:
        audio_adapter.apply_mic(state, False)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_ROTATE_LEFT:
        rotation_adapter.apply(state, "left", moving=True)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_ROTATE_RIGHT:
        rotation_adapter.apply(state, "right", moving=True)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_ROTATE_HOME:
        rotation_adapter.apply(state, "home", moving=False)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_ROTATE_STOP:
        rotation_adapter.stop(state)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_AUDIO_TEST:
        audio_adapter.speaker_test(state)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_SENSOR_SAMPLE:
        sensor_adapter.sample(state)
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_SET_MOTION:
        sensor_adapter.set_motion(state, bool(extra.get("motion_detected")))
        return state, STATUS_PRIVACY_MODE if state.get("privacy_mode") else STATUS_ONLINE
    if command == CMD_DEVICE_RESTART_SIMULATED:
        next_state = default_state()
        next_state["battery_percent"] = state.get("battery_percent", 98)
        return next_state, STATUS_ONLINE
    return state, STATUS_ONLINE
