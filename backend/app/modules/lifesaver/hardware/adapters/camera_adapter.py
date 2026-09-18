"""Camera capability helper. Camera defaults off. No frames are captured."""
from __future__ import annotations

from typing import Any


def apply(state: dict[str, Any], enable: bool) -> dict[str, Any]:
    if state.get("privacy_mode"):
        state["camera_enabled"] = False
        state["camera_blocked_reason"] = "privacy_mode"
        return state
    state["camera_enabled"] = bool(enable)
    state.pop("camera_blocked_reason", None)
    return state
