"""Explicit Operations commercial mode gates.

Defaults keep every path disabled. Live mode never activates from a Stripe key
alone; callers must pass the dedicated feature flags for that surface.
"""
from __future__ import annotations

import os
from typing import Iterable


def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() == "true"


def _falsy_or_unset_as_false(name: str) -> bool:
    return os.getenv(name, "false").strip().lower() == "false"


def operations_test_mode(*, extra_enabled: Iterable[str] = ()) -> bool:
    if not (
        os.getenv("APP_ENV") == "staging"
        and os.getenv("AMICOR_ENVIRONMENT") == "staging"
        and _falsy_or_unset_as_false("NOVA_STRIPE_LIVE_ENABLED")
        and _falsy_or_unset_as_false("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED")
    ):
        return False
    return all(_truthy(flag) for flag in extra_enabled)


def operations_live_mode(*, extra_enabled: Iterable[str] = ()) -> bool:
    if not (
        os.getenv("APP_ENV") == "production"
        and os.getenv("AMICOR_ENVIRONMENT") == "production"
        and _truthy("NOVA_STRIPE_LIVE_ENABLED")
        and _truthy("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED")
    ):
        return False
    return all(_truthy(flag) for flag in extra_enabled)


def resolve_operations_mode(*, staging_flags: Iterable[str], live_flags: Iterable[str]) -> str | None:
    """Return 'test', 'live', or None. Never infers mode from credentials."""
    if operations_live_mode(extra_enabled=live_flags):
        return "live"
    if operations_test_mode(extra_enabled=staging_flags):
        return "test"
    return None
