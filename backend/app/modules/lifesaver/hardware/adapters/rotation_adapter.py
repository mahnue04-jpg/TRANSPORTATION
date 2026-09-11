"""Motorized-base simulation. STOP is always accepted. No real motor I/O."""
from __future__ import annotations

from typing import Any

HOME_DEG = 0
STEP_DEG = 15
SPEED_PROFILES = {"slow": 8, "normal": 15, "fast": 30}


def _clamp(angle: float) -> float:
    value = float(angle) % 360
    return value if value >= 0 else value + 360


def apply(state: dict[str, Any], heading: str, *, moving: bool) -> dict[str, Any]:
    if state.get("privacy_mode") and heading != "stopped":
        state["rotation"] = "stopped"
        state["rotation_moving"] = False
        state["tracking_enabled"] = False
        state["rotation_blocked_reason"] = "privacy_mode"
        return state
    current = float(state.get("orientation_deg") or HOME_DEG)
    speed = SPEED_PROFILES.get(str(state.get("rotation_speed") or "normal"), STEP_DEG)
    if heading == "left":
        current = _clamp(current - speed)
    elif heading == "right":
        current = _clamp(current + speed)
    elif heading == "home":
        current = HOME_DEG
        moving = False
    state["rotation"] = heading
    state["rotation_moving"] = bool(moving)
    state["orientation_deg"] = current
    state["tracking_enabled"] = bool(moving) and not state.get("privacy_mode")
    state["motion_timeout_sec"] = 3 if moving else 0
    state["obstruction"] = False
    state.pop("rotation_blocked_reason", None)
    return state


def stop(state: dict[str, Any]) -> dict[str, Any]:
    state["rotation"] = "stopped"
    state["rotation_moving"] = False
    state["tracking_enabled"] = False
    state["motion_timeout_sec"] = 0
    state.pop("rotation_blocked_reason", None)
    return state
