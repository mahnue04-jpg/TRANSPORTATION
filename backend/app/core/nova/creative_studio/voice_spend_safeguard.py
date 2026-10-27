"""Voice-only Coral narration spending safeguard.

Enforces a hard USD ceiling for exactly one paid Coral TTS request per project
and blocks duplicate paid submissions. Does not call providers, purchase
credits, or activate Kling / image / video generation.
"""

from __future__ import annotations

import hashlib
import math
import os
from typing import Any

from app.core.nova.creative_studio.flags import (
    image_provider_live_enabled,
    talking_presenter_provider_live_enabled,
    video_provider_live_enabled,
    voice_provider_live_enabled,
)

# Strict owner ceiling for the first professional Coral narration request.
CORAL_VOICE_MAX_USD = 0.10
CORAL_VOICE = "coral"
DEFAULT_VOICE_MODEL = "gpt-4o-mini-tts"

# Conservative OpenAI planning rates (not invoices). Padded so estimates fail closed.
_TTS_USD_PER_AUDIO_MINUTE = 0.015
_WHISPER_USD_PER_AUDIO_MINUTE = 0.006
_CHARS_PER_SPEAKING_MINUTE = 750.0
_ESTIMATE_PAD = 1.5
_MIN_AUDIO_MINUTES = 1.0 / 60.0  # never estimate below one second of audio

METADATA_KEY = "coral_voice_spend"


class VoiceSpendBlocked(Exception):
    """Raised when a paid Coral narration request must not proceed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def normalize_script(script: str) -> str:
    return " ".join(str(script or "").split()).strip()


def voice_model_name() -> str:
    return str(os.getenv("NOVA_CREATIVE_VOICE_MODEL") or DEFAULT_VOICE_MODEL).strip() or DEFAULT_VOICE_MODEL


def estimate_coral_narration_usd(script: str, *, include_whisper: bool = False) -> float:
    """Conservative USD estimate for one Coral TTS call (optional Whisper captions)."""
    clean = normalize_script(script)
    chars = max(1, len(clean))
    minutes = max(_MIN_AUDIO_MINUTES, chars / _CHARS_PER_SPEAKING_MINUTE)
    total = minutes * _TTS_USD_PER_AUDIO_MINUTE
    if include_whisper:
        total += minutes * _WHISPER_USD_PER_AUDIO_MINUTE
    return round(total * _ESTIMATE_PAD, 4)


def request_fingerprint(
    *,
    owner_id: str,
    project_id: str,
    script: str,
    voice: str,
    model: str,
    include_whisper: bool,
) -> str:
    payload = {
        "owner_id": str(owner_id),
        "project_id": str(project_id),
        "script": normalize_script(script),
        "voice": str(voice or "").strip().lower(),
        "model": str(model or "").strip(),
        "include_whisper": bool(include_whisper),
        "kind": "coral_voice_only",
    }
    import json

    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def other_paid_media_live() -> bool:
    """True when non-voice paid Creative Studio providers are activated."""
    return bool(
        image_provider_live_enabled()
        or video_provider_live_enabled()
        or talking_presenter_provider_live_enabled()
    )


def safeguard_status(existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Read-only status for readiness UIs. Never submits paid work."""
    record = dict(existing or {})
    voice_only = not other_paid_media_live()
    ready = voice_only and CORAL_VOICE_MAX_USD > 0
    return {
        "kind": "coral_voice_only",
        "max_usd": CORAL_VOICE_MAX_USD,
        "voice": CORAL_VOICE,
        "budget_enforcement_ready": ready,
        "voice_only": voice_only,
        "voice_live_enabled": voice_provider_live_enabled(),
        "other_paid_media_live": not voice_only,
        "paid_request_submitted": bool(record.get("paid_request_submitted")),
        "status": str(record.get("status") or "idle"),
        "fingerprint": record.get("fingerprint"),
        "estimated_usd": record.get("estimated_usd"),
        "asset_id": record.get("asset_id"),
        "message": (
            "Coral voice-only spend safeguard is ready: one narration request capped at "
            f"${CORAL_VOICE_MAX_USD:.2f}, duplicates blocked. Kling/image/video stay off."
            if ready
            else "Coral voice-only spend safeguard refuses while other paid media providers are live."
        ),
    }


def evaluate_coral_request(
    *,
    owner_id: str,
    project_id: str,
    script: str,
    voice: str | None,
    include_whisper: bool = False,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one Coral narration request against the hard spend ceiling.

    Does not mutate project state and does not call providers.
    """
    resolved_voice = str(voice or CORAL_VOICE).strip().lower()
    clean = normalize_script(script)
    model = voice_model_name()
    estimate = estimate_coral_narration_usd(clean, include_whisper=include_whisper)
    fingerprint = request_fingerprint(
        owner_id=owner_id,
        project_id=project_id,
        script=clean,
        voice=resolved_voice,
        model=model,
        include_whisper=include_whisper,
    )
    record = dict(existing or {})
    status = {
        "allowed": False,
        "fingerprint": fingerprint,
        "voice": resolved_voice,
        "model": model,
        "estimated_usd": estimate,
        "max_usd": CORAL_VOICE_MAX_USD,
        "include_whisper": bool(include_whisper),
        "reuse_existing": False,
        "existing_asset_id": record.get("asset_id"),
        "code": None,
        "message": "",
    }

    if not clean:
        status["code"] = "EMPTY_NARRATION_SCRIPT"
        status["message"] = "A Coral narration script is required before a paid voice request."
        return status

    if resolved_voice != CORAL_VOICE:
        status["code"] = "CORAL_VOICE_REQUIRED"
        status["message"] = (
            f"This spend safeguard only authorizes the Coral voice (got {resolved_voice!r}). "
            "Other voices stay blocked for paid narration."
        )
        return status

    if other_paid_media_live():
        status["code"] = "VOICE_ONLY_REQUIRED"
        status["message"] = (
            "Coral narration spending is voice-only. Disable paid image, Kling/video, and "
            "talking-presenter live flags before authorizing this request."
        )
        return status

    if not math.isfinite(estimate) or estimate <= 0:
        status["code"] = "INVALID_VOICE_ESTIMATE"
        status["message"] = "Could not compute a finite Coral narration cost estimate."
        return status

    if estimate > CORAL_VOICE_MAX_USD:
        status["code"] = "CORAL_SPEND_CEILING"
        status["message"] = (
            f"Estimated Coral narration ${estimate:.4f} exceeds the strict "
            f"${CORAL_VOICE_MAX_USD:.2f} maximum. Paid request blocked."
        )
        return status

    prior_status = str(record.get("status") or "")
    prior_fp = str(record.get("fingerprint") or "")
    if prior_status == "charged" and prior_fp == fingerprint and record.get("asset_id"):
        status["allowed"] = True
        status["reuse_existing"] = True
        status["code"] = "REUSE_EXISTING_NARRATION"
        status["message"] = (
            "Matching Coral narration was already paid for this project. "
            "Reusing the saved audio; no duplicate paid request."
        )
        return status

    if prior_status == "charged":
        status["code"] = "CORAL_SPEND_ALREADY_USED"
        status["message"] = (
            "This project already used its one paid Coral narration request. "
            "Duplicate spend is blocked."
        )
        return status

    if prior_status == "reserved" and prior_fp == fingerprint:
        status["code"] = "CORAL_REQUEST_IN_FLIGHT"
        status["message"] = (
            "A matching Coral narration request is already reserved. "
            "Duplicate paid submission blocked."
        )
        return status

    if prior_status == "reserved" and prior_fp and prior_fp != fingerprint:
        status["code"] = "CORAL_REQUEST_IN_FLIGHT"
        status["message"] = (
            "Another Coral narration reservation is in flight for this project. "
            "Duplicate paid submission blocked."
        )
        return status

    status["allowed"] = True
    status["code"] = "CORAL_SPEND_OK"
    status["message"] = (
        f"Coral narration estimate ${estimate:.4f} is within the ${CORAL_VOICE_MAX_USD:.2f} "
        "voice-only ceiling. One paid request may proceed."
    )
    return status


def build_reservation(evaluation: dict[str, Any], *, reserved_at: str) -> dict[str, Any]:
    if not evaluation.get("allowed") or evaluation.get("reuse_existing"):
        raise VoiceSpendBlocked(
            str(evaluation.get("code") or "CORAL_SPEND_BLOCKED"),
            str(evaluation.get("message") or "Coral narration spend blocked."),
        )
    return {
        "status": "reserved",
        "fingerprint": evaluation["fingerprint"],
        "voice": evaluation["voice"],
        "model": evaluation["model"],
        "estimated_usd": evaluation["estimated_usd"],
        "max_usd": CORAL_VOICE_MAX_USD,
        "include_whisper": bool(evaluation.get("include_whisper")),
        "paid_request_submitted": False,
        "reserved_at": reserved_at,
        "charged_at": None,
        "asset_id": None,
        "kind": "coral_voice_only",
    }


def mark_charged(reservation: dict[str, Any], *, asset_id: str, charged_at: str) -> dict[str, Any]:
    updated = dict(reservation or {})
    updated["status"] = "charged"
    updated["paid_request_submitted"] = True
    updated["asset_id"] = str(asset_id)
    updated["charged_at"] = charged_at
    return updated


def mark_released(reservation: dict[str, Any], *, released_at: str, reason: str = "") -> dict[str, Any]:
    """Clear an in-flight reservation after a failed provider attempt so a single retry can reserve again."""
    updated = dict(reservation or {})
    if str(updated.get("status") or "") == "charged":
        return updated
    return {
        "status": "released",
        "fingerprint": updated.get("fingerprint"),
        "voice": updated.get("voice"),
        "model": updated.get("model"),
        "estimated_usd": updated.get("estimated_usd"),
        "max_usd": CORAL_VOICE_MAX_USD,
        "include_whisper": updated.get("include_whisper"),
        "paid_request_submitted": False,
        "reserved_at": updated.get("reserved_at"),
        "released_at": released_at,
        "asset_id": None,
        "release_reason": str(reason or "")[:300],
        "kind": "coral_voice_only",
    }
