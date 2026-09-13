"""Local hardware mode. Production and unset values stay on mock."""
from __future__ import annotations

import os

MODE_MOCK = "mock"
MODE_LOCAL_PI = "local_pi"
VALID_MODES = frozenset({MODE_MOCK, MODE_LOCAL_PI})


def environment_name() -> str:
    return (os.getenv("AMICOR_ENVIRONMENT") or "").strip().lower()


def is_production() -> bool:
    return environment_name() in {"production", "prod"}


def hardware_mode() -> str:
    from app.modules.lifesaver.staging import lifesaver_staging_isolated

    if is_production() or lifesaver_staging_isolated():
        return MODE_MOCK
    raw = (os.getenv("AMICOR_LIFESAVER_HARDWARE_MODE") or MODE_MOCK).strip().lower()
    if raw in VALID_MODES:
        return raw
    return MODE_MOCK


def local_pi_enabled() -> bool:
    return hardware_mode() == MODE_LOCAL_PI


def prototype_panel_available() -> bool:
    from app.modules.lifesaver.staging import lifesaver_staging_isolated

    return not is_production() and not lifesaver_staging_isolated()


def configured_pi_host() -> str:
    return (os.getenv("AMICOR_LIFESAVER_PI_HOST") or "127.0.0.1").strip() or "127.0.0.1"


def snapshot() -> dict:
    return {
        "mode": hardware_mode(),
        "default_mode": MODE_MOCK,
        "local_pi_enabled": local_pi_enabled(),
        "prototype_panel_available": prototype_panel_available(),
        "configured_host": configured_pi_host() if local_pi_enabled() else None,
        "production": is_production(),
        "real_camera_streaming": False,
        "emergency_services_enabled": False,
    }
