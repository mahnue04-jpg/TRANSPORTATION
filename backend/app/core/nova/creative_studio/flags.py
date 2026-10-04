"""Creative Studio guardrails. Defaults stay OFF for live media providers."""

from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}


def _env_true(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in _TRUE


EXTERNAL_SUBMISSION_ENABLED = False
FINANCIAL_EXECUTION_ENABLED = False
EXTERNAL_PUBLISHING_ENABLED = False
CLIENT_CONTACT_ENABLED = False


def image_provider_configured() -> bool:
    """Use the existing server-side OpenAI credential; never expose its value."""
    return bool(str(os.getenv("OPENAI_API_KEY") or "").strip())


def image_provider_live_enabled() -> bool:
    """Credentials alone never activate cost-bearing image generation."""
    return _env_true("NOVA_CREATIVE_IMAGE_LIVE_ENABLED")


def selected_video_provider() -> str:
    return str(os.getenv("NOVA_CREATIVE_VIDEO_PROVIDER") or "runway").strip().lower()


def video_provider_configured() -> bool:
    """Check only the selected provider's credential without exposing it."""
    selected = selected_video_provider()
    if selected in {"fal", "kling", "fal_kling"}:
        return bool(str(os.getenv("FAL_KEY") or "").strip())
    if selected not in {"runway", "runway_video"}:
        return False
    return bool(str(os.getenv("RUNWAYML_API_SECRET") or os.getenv("NOVA_CREATIVE_VIDEO_API_KEY") or "").strip())


def video_provider_live_enabled() -> bool:
    """Switching providers never implicitly activates new paid generation."""
    enabled = _env_true("NOVA_CREATIVE_VIDEO_LIVE_ENABLED")
    if selected_video_provider() in {"fal", "kling", "fal_kling"}:
        return enabled and _env_true("NOVA_CREATIVE_KLING_LIVE_ENABLED")
    return enabled


def voice_provider_configured() -> bool:
    """Reuse the existing OpenAI server credential for speech generation."""
    return bool(str(os.getenv("OPENAI_API_KEY") or "").strip())


def voice_provider_live_enabled() -> bool:
    """Credentials alone never activate cost-bearing voice generation."""
    return _env_true("NOVA_CREATIVE_VOICE_LIVE_ENABLED")


def talking_presenter_provider_configured() -> bool:
    """D-ID API credential for talking presenter generation."""
    return bool(str(os.getenv("DID_API_KEY") or "").strip())


def talking_presenter_provider_live_enabled() -> bool:
    """Credentials alone never activate cost-bearing talking presenter generation."""
    return _env_true("NOVA_CREATIVE_TALKING_PRESENTER_LIVE_ENABLED")


def creative_guardrails() -> dict[str, bool | str]:
    return {
        "EXTERNAL_SUBMISSION_ENABLED": EXTERNAL_SUBMISSION_ENABLED,
        "FINANCIAL_EXECUTION_ENABLED": FINANCIAL_EXECUTION_ENABLED,
        "EXTERNAL_PUBLISHING_ENABLED": EXTERNAL_PUBLISHING_ENABLED,
        "CLIENT_CONTACT_ENABLED": CLIENT_CONTACT_ENABLED,
        "IMAGE_PROVIDER_CONFIGURED": image_provider_configured(),
        "IMAGE_PROVIDER_LIVE_ENABLED": image_provider_live_enabled(),
        "VIDEO_PROVIDER_CONFIGURED": video_provider_configured(),
        "VIDEO_PROVIDER_LIVE_ENABLED": video_provider_live_enabled(),
        "VOICE_PROVIDER_CONFIGURED": voice_provider_configured(),
        "VOICE_PROVIDER_LIVE_ENABLED": voice_provider_live_enabled(),
        "TALKING_PRESENTER_PROVIDER_CONFIGURED": talking_presenter_provider_configured(),
        "TALKING_PRESENTER_PROVIDER_LIVE_ENABLED": talking_presenter_provider_live_enabled(),
        "PLANNING_MODE_AVAILABLE": True,
        "MODE": "PLANNING_SCRIPT_STORYBOARD",
    }
