"""Pure paid-subscription access policy; not a route or payment verifier."""
from __future__ import annotations

from datetime import datetime, timezone

from app.core.nova.billing.plans import PLAN_KEYS


def allows_paid_plan(
    *,
    required_plan: str,
    recorded_plan: str | None,
    status: str | None,
    expected_price: str | None,
    recorded_price: str | None,
    verified_subscription: bool,
    current_period_end: datetime | None,
    now: datetime,
) -> bool:
    """Require verified, unexpired, exact-plan subscription evidence.

    Callers must derive verified_subscription and recorded fields from trusted,
    tenant-bound billing evidence, never from request data. Does not implement
    quota enforcement, tier inheritance, trials, or one-time task access.
    """
    if required_plan not in PLAN_KEYS or recorded_plan != required_plan:
        return False
    if verified_subscription is not True or status != "active":
        return False
    if not expected_price or expected_price != recorded_price:
        return False
    if current_period_end is None or current_period_end.utcoffset() is None or now.utcoffset() is None:
        return False
    return current_period_end.astimezone(timezone.utc) > now.astimezone(timezone.utc)
