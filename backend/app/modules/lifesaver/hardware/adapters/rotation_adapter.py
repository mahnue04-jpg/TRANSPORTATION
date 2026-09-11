"""Motorized-base simulation. STOP is always accepted. No real motor I/O."""
from __future__ import annotations

from typing import Any

from app.modules.lifesaver.hardware.motor_contract import HOME_ANGLE, MAX_ANGLE, MIN_ANGLE, SPEED_PROFILES, clamp_angle, motor_snapshot

HOME_DEG = HOME_ANGLE
STEP_DEG = 15


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
    state["requested_angle"] = current
    state["motor_state"] = "moving" if moving else ("stopped" if heading == "stopped" else "idle")
    state["home_calibrated"] = heading == "home" or current == HOME_DEG
    state["min_angle"] = MIN_ANGLE
    state["max_angle"] = MAX_ANGLE
    state.pop("rotation_blocked_reason", None)
    motor_snapshot(state)
    return state


def apply_angle(state: dict[str, Any], angle: float | int | None) -> dict[str, Any]:
    if state.get("privacy_mode"):
        return stop(state) | {"rotation_blocked_reason": "privacy_mode", "tracking_enabled": False}
    target = clamp_angle(angle)
    current = float(state.get("orientation_deg") or HOME_DEG)
    direction = "right" if target >= current else "left"
    if target == HOME_DEG:
        direction = "home"
    state["rotation"] = direction
    state["rotation_moving"] = target != current
    state["orientation_deg"] = target
    state["requested_angle"] = target
    state["motor_state"] = "moving" if target != current else "idle"
    state["motion_timeout_sec"] = 3 if target != current else 0
    state["tracking_enabled"] = False
    state["obstruction"] = False
    state["home_calibrated"] = target == HOME_DEG
    state["min_angle"] = MIN_ANGLE
    state["max_angle"] = MAX_ANGLE
    return state


def stop(state: dict[str, Any]) -> dict[str, Any]:
    state["rotation"] = "stopped"
    state["rotation_moving"] = False
    state["tracking_enabled"] = False
    state["motion_timeout_sec"] = 0
    state["motor_state"] = "stopped"
    state.pop("rotation_blocked_reason", None)
    return state
