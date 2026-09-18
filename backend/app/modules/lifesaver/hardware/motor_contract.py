"""Future rotating-base motor-controller abstraction. No real GPIO."""
from __future__ import annotations

from typing import Any

MIN_ANGLE = 0
MAX_ANGLE = 350
HOME_ANGLE = 0
SPEED_PROFILES = {"slow": 8, "normal": 15, "fast": 30}


def motor_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    moving = bool(state.get("rotation_moving"))
    heading = state.get("rotation") or "home"
    if heading == "stopped" or not moving:
        motor_state = "stopped" if heading == "stopped" else "idle"
    else:
        motor_state = "moving"
    return {
        "current_angle": float(state.get("orientation_deg") or HOME_ANGLE),
        "requested_angle": state.get("requested_angle"),
        "direction": heading,
        "speed_profile": state.get("rotation_speed") or "normal",
        "moving_state": motor_state,
        "obstruction": bool(state.get("obstruction")),
        "timeout_sec": int(state.get("motion_timeout_sec") or 0),
        "home_calibrated": bool(state.get("home_calibrated", True)),
        "min_angle": MIN_ANGLE,
        "max_angle": MAX_ANGLE,
        "infinite_rotation": False,
        "real_motor": False,
    }


def clamp_angle(angle: float | int | None) -> float:
    try:
        value = float(angle)
    except (TypeError, ValueError):
        return float(HOME_ANGLE)
    return max(MIN_ANGLE, min(MAX_ANGLE, value))
