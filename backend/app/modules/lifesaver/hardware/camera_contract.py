"""Future camera integration contract. No live stream or stored media."""
from __future__ import annotations

from typing import Any


def camera_status(state: dict[str, Any], *, privacy: bool) -> dict[str, Any]:
    enabled = bool(state.get("camera_enabled")) and not privacy
    return {
        "camera_available": not privacy,
        "stream_ready": False,
        "session_request_status": "idle",
        "local_preview_status": "disabled",
        "remote_session_status": "not_connected",
        "camera_permission": "explicit_enable_required",
        "privacy_block": privacy,
        "camera_enabled": enabled,
        "session_ended": True,
        "recording": False,
        "media_stored": False,
        "provider": None,
        "disclaimer": "Camera contract only. No live preview, recording, or upload is active.",
    }
