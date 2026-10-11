"""Staging feature gate for Nova Casting.

Reads and disposable sandbox writes stay off unless every configured environment
name agrees on one explicit non-production value and NOVA_CASTING_STAGING_READS
is set. Production cannot opt in. Public intake and media uploads stay off.
"""
from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}
_PRODUCTION = {"production", "prod"}
_ALLOWLIST = frozenset({
    "development", "dev", "test", "testing", "local", "staging", "disposable",
})
_ENV_NAMES = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")


def _environment_values() -> list[str]:
    values = []
    for name in _ENV_NAMES:
        raw = os.getenv(name)
        if raw is None:
            continue
        text = str(raw).strip().lower()
        if text:
            values.append(text)
    return values


def casting_production_locked() -> bool:
    """True when any environment name says this process is production."""
    return any(value in _PRODUCTION for value in _environment_values())


def casting_nonproduction_allowlisted() -> bool:
    """True only when set environment names agree on one allowlisted value.

    Absent, unknown, production, and conflicting values fail closed.
    """
    values = _environment_values()
    if not values or casting_production_locked():
        return False
    if any(value not in _ALLOWLIST for value in values):
        return False
    return len(set(values)) == 1


def casting_staging_reads_enabled() -> bool:
    """Explicit opt-in for non-production read routes."""
    if not casting_nonproduction_allowlisted():
        return False
    return str(os.getenv("NOVA_CASTING_STAGING_READS") or "").strip().lower() in _TRUE


def casting_sandbox_writes_enabled() -> bool:
    """Disposable test workflows use the same opt-in as staging reads.

    This does not publish campaigns, open public intake, or enable media uploads.
    """
    return casting_staging_reads_enabled()
