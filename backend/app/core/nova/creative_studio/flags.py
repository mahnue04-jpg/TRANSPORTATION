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


def video_provider_configured() -> bool:
    """Runway Dev credential for real AI video generation."""
    return bool(
        str(
            os.getenv("RUNWAYML_API_SECRET")
            or os.getenv("NOVA_CREATIVE_VIDEO_API_KEY")
            or ""
        ).strip()
    )


def video_provider_live_enabled() -> bool:
    """Credentials alone never activate cost-bearing video generation."""
    return _env_true("NOVA_CREATIVE_VIDEO_LIVE_ENABLED")


def voice_provider_configured() -> bool:
    """Reuse the existing OpenAI server credential for speech generation."""
    return bool(str(os.getenv("OPENAI_API_KEY") or "").strip())


def voice_provider_live_enabled() -> bool:
    """Credentials alone never activate cost-bearing voice generation."""
    return _env_true("NOVA_CREATIVE_VOICE_LIVE_ENABLED")


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
        "PLANNING_MODE_AVAILABLE": True,
        "MODE": "PLANNING_SCRIPT_STORYBOARD",
    }
