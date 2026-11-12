"""Growth Agent capability flags. Production defaults remain OFF.

Live send / calendar / voice / Stripe are hard-coded False. Only the surface
enable flag and demo mode may be toggled via environment for local/staging.
"""

from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}


def _env_enabled(name: str) -> bool:
    return str(os.getenv(name) or "").strip().lower() in _TRUE


def growth_agent_enabled() -> bool:
    """Master surface flag. When false, authenticated APIs return 404."""
    return _env_enabled("NOVA_GROWTH_AGENT_ENABLED")


def demo_mode_enabled() -> bool:
    """Owner-only synthetic demo seeding. Never uses real customer data."""
    if not growth_agent_enabled():
        return False
    return _env_enabled("NOVA_GROWTH_AGENT_DEMO_MODE")


def widget_public_enabled() -> bool:
    """Public widget chat endpoints. Still requires signed install token."""
    if not growth_agent_enabled():
        return False
    return _env_enabled("NOVA_GROWTH_AGENT_WIDGET_ENABLED")


def background_worker_enabled() -> bool:
    """Mock delivery worker only. Default off. Never enables live transports."""
    if not growth_agent_enabled():
        return False
    return _env_enabled("NOVA_GROWTH_AGENT_BACKGROUND_WORKER")


def retention_delete_enabled() -> bool:
    """Explicit opt-in for destructive retention cleanup. Default off."""
    if not growth_agent_enabled():
        return False
    return _env_enabled("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED")


# Hard-off live capabilities — cannot be enabled via headers or UI alone.
REAL_EMAIL_SEND = False
REAL_SMS_SEND = False
REAL_CALENDAR_WRITE = False
REAL_VOICE = False
REAL_STRIPE_CHARGES = False
BULK_COLD_OUTREACH = False
HEADER_CAN_ENABLE_LIVE = False
# Backward-compatible alias: always False for live; use background_worker_enabled() for mock worker.
BACKGROUND_WORKER_ENABLED = False


def live_flags() -> dict[str, bool]:
    return {
        "GROWTH_AGENT_ENABLED": growth_agent_enabled(),
        "DEMO_MODE": demo_mode_enabled(),
        "WIDGET_PUBLIC_ENABLED": widget_public_enabled(),
        "BACKGROUND_WORKER_MOCK": background_worker_enabled(),
        "RETENTION_DELETE_ENABLED": retention_delete_enabled(),
        "REAL_EMAIL_SEND": REAL_EMAIL_SEND,
        "REAL_SMS_SEND": REAL_SMS_SEND,
        "REAL_CALENDAR_WRITE": REAL_CALENDAR_WRITE,
        "REAL_VOICE": REAL_VOICE,
        "REAL_STRIPE_CHARGES": REAL_STRIPE_CHARGES,
        "BACKGROUND_WORKER_ENABLED": False,  # live worker hard-off; mock uses BACKGROUND_WORKER_MOCK
        "BULK_COLD_OUTREACH": BULK_COLD_OUTREACH,
        "HEADER_CAN_ENABLE_LIVE": HEADER_CAN_ENABLE_LIVE,
        "MOCK_TRANSPORT_ONLY": True,
        "CONSENT_REQUIRED_FOR_MARKETING": True,
        "TRANSACTIONAL_SEPARATE_FROM_MARKETING": True,
    }
