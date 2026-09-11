"""Microphone/speaker simulation. No audio buffers are stored."""
from __future__ import annotations

from typing import Any

from app.helpers import now


def apply_mic(state: dict[str, Any], enable: bool) -> dict[str, Any]:
    if state.get("privacy_mode"):
        state["microphone_enabled"] = False
        return state
    state["microphone_enabled"] = bool(enable)
    return state


def speaker_test(state: dict[str, Any]) -> dict[str, Any]:
    state["last_audio_test_at"] = now().isoformat()
    state["last_audio_test"] = "tone_simulated"
    return state
