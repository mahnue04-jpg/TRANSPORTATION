"""
backend/app/core/runtime_config.py

Centralized runtime configuration validation.
- Validates required and optional environment variables on startup.
- Never logs secret values — presence-only for sensitive vars.
- Returns a typed, safe dict; no exceptions escape this module.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("amicor.runtime_config")

# Required at runtime; absence = critical degradation
_REQUIRED_VARS: tuple[str, ...] = ("DATABASE_URL",)

# Optional; absence = degraded but non-fatal
_OPTIONAL_VARS: tuple[str, ...] = (
    "APP_ENV",
    "DEBUG",
    "REDIS_URL",
    "OPENAI_API_KEY",
    "SUPERVISION_LOG_RETENTION_DAYS",
)

# Secrets: validated for presence only, never included in log messages or response payloads
_SECRET_VARS: frozenset[str] = frozenset({"OPENAI_API_KEY", "DATABASE_URL"})


def validate_runtime_config() -> dict[str, Any]:
    """
    Validate runtime environment variables.

    Returns a safe, non-secret configuration summary dict:
    {
        "app_env": str,
        "debug": bool,
        "has_database_url": bool,
        "has_redis_url": bool,
        "has_openai_api_key": bool,
        "supervision_log_retention_days": int,
        "missing_required": list[str],  # secret names redacted
        "missing_optional": list[str],  # secret names redacted
        "validation_status": "ok" | "degraded" | "critical",
        "validated_at": str,  # ISO-8601 UTC
    }
    """
    missing_required: list[str] = []
    missing_optional: list[str] = []

    for var in _REQUIRED_VARS:
        if not os.environ.get(var, "").strip():
            missing_required.append(var)

    for var in _OPTIONAL_VARS:
        if not os.environ.get(var, "").strip():
            missing_optional.append(var)

    if missing_required:
        validation_status = "critical"
        # Only log non-secret var names in the message to avoid leaking secret name patterns
        loggable = [v for v in missing_required if v not in _SECRET_VARS]
        logger.error(
            "Runtime config validation CRITICAL: missing required vars — %s",
            ", ".join(loggable) if loggable else "[redacted secret vars]",
        )
    elif missing_optional:
        validation_status = "degraded"
        loggable = [v for v in missing_optional if v not in _SECRET_VARS]
        if loggable:
            logger.warning(
                "Runtime config validation DEGRADED: missing optional vars — %s",
                ", ".join(loggable),
            )
    else:
        validation_status = "ok"
        logger.info("Runtime config validation: all vars present (status=ok)")

    app_env = os.environ.get("APP_ENV", "development").strip() or "development"
    debug = os.environ.get("DEBUG", "false").strip().lower() in {"1", "true", "yes"}

    try:
        retention_days = int(os.environ.get("SUPERVISION_LOG_RETENTION_DAYS", "5"))
    except (ValueError, TypeError):
        retention_days = 5

    # Redact secret names from public output
    safe_missing_required = [v for v in missing_required if v not in _SECRET_VARS]
    safe_missing_optional = [v for v in missing_optional if v not in _SECRET_VARS]

    return {
        "app_env": app_env,
        "debug": debug,
        "has_database_url": bool(os.environ.get("DATABASE_URL", "").strip()),
        "has_redis_url": bool(os.environ.get("REDIS_URL", "").strip()),
        "has_openai_api_key": bool(os.environ.get("OPENAI_API_KEY", "").strip()),
        "supervision_log_retention_days": retention_days,
        "missing_required": safe_missing_required,
        "missing_optional": safe_missing_optional,
        "validation_status": validation_status,
        "validated_at": datetime.now(timezone.utc).isoformat(),
    }
