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
    return bool(str(os.getenv("NOVA_CREATIVE_VIDEO_API_KEY") or "").strip())


def voice_provider_configured() -> bool:
    return bool(str(os.getenv("NOVA_CREATIVE_VOICE_API_KEY") or "").strip())


def creative_guardrails() -> dict[str, bool | str]:
    return {
        "EXTERNAL_SUBMISSION_ENABLED": EXTERNAL_SUBMISSION_ENABLED,
        "FINANCIAL_EXECUTION_ENABLED": FINANCIAL_EXECUTION_ENABLED,
        "EXTERNAL_PUBLISHING_ENABLED": EXTERNAL_PUBLISHING_ENABLED,
        "CLIENT_CONTACT_ENABLED": CLIENT_CONTACT_ENABLED,
        "IMAGE_PROVIDER_CONFIGURED": image_provider_configured(),
        "IMAGE_PROVIDER_LIVE_ENABLED": image_provider_live_enabled(),
        "VIDEO_PROVIDER_CONFIGURED": video_provider_configured(),
        "VOICE_PROVIDER_CONFIGURED": voice_provider_configured(),
        "PLANNING_MODE_AVAILABLE": True,
        "MODE": "PLANNING_SCRIPT_STORYBOARD",
    }
