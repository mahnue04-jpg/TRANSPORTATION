"""Motion / IMU simulation. Passive observation is off in privacy mode."""
from __future__ import annotations

from typing import Any

from app.helpers import now


def sample(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("privacy_mode"):
        state["motion_detected"] = False
        state["passive_observation"] = False
        state["last_sensor_sample_at"] = now().isoformat()
        return state
    state["last_sensor_sample_at"] = now().isoformat()
    state["orientation"] = state.get("orientation") or "level"
    return state


def set_motion(state: dict[str, Any], detected: bool) -> dict[str, Any]:
    if state.get("privacy_mode"):
        state["motion_detected"] = False
        state["passive_observation"] = False
        return state
    state["motion_detected"] = bool(detected)
    return state
