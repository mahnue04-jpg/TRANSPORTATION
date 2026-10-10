"""Staging feature gate for Nova Casting reads.

The default is off. Production environments cannot enable reads through the
flag. This module does not upload media, publish campaigns, or collect applicants.
"""
from __future__ import annotations

import os

_TRUE = {"1", "true", "yes", "on"}
_PRODUCTION = {"production", "prod"}


def casting_production_locked() -> bool:
    """True when this process must not expose casting reads or apply casting DDL."""
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if str(os.getenv(name) or "").strip().lower() in _PRODUCTION:
            return True
    return False


def casting_staging_reads_enabled() -> bool:
    """Explicit opt-in for non-production read routes. Unset or production stays off."""
    if casting_production_locked():
        return False
    return str(os.getenv("NOVA_CASTING_STAGING_READS") or "").strip().lower() in _TRUE
