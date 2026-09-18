"""Offline fallback. No network I/O."""
from __future__ import annotations

from typing import Any


def apply_command(state: dict[str, Any], command: str, extra: dict[str, Any] | None = None) -> tuple[dict[str, Any], str, str]:
    extra = extra or {}
    if command == "ROTATE_STOP":
        state["rotation"] = "stopped"
        state["rotation_moving"] = False
        return state, "OFFLINE", "COMPLETED"
    if command in {"GET_STATUS", "GET_DEVICE_HEALTH", "DEVICE_PING"}:
        return state, "OFFLINE", "TIMED_OUT"
    extra
    return state, "OFFLINE", "TIMED_OUT"
