"""Fail-closed Operations plan allowance decisions.

Pure policy: a caller MUST provide already-verified Stripe subscription and paid
billing-period evidence. This module does not authorize payments, modify records,
or imply that a caller's string inputs are trusted. Staging only until integrated
with a durable transactionally locked entitlement and usage ledger.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

LIMITS = {"starter_49": 1, "launch_99": 3, "business_299": 10}
SUBSCRIPTIONS = frozenset({"launch_99", "business_299"})


@dataclass(frozen=True)
class VerifiedEntitlement:
    plan: str
    customer_id: str
    paid: bool
    status: str
    subscription_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    payment_id: str | None = None


def can_accept_task(
    entitlement: VerifiedEntitlement, *,
    customer_id: str,
    now: datetime,
    accepted_unique_tasks: frozenset[str],
    request_key: str,
) -> tuple[bool, str]:
    """Return (allowed, reason); *never* a production authorization on its own.

    accepted_unique_tasks must come from the same customer+plan+verified period,
    locked under a transaction. Repeated request keys are idempotent.
    """
    if entitlement.plan not in LIMITS or not customer_id or customer_id != entitlement.customer_id:
        return False, "plan_or_customer_mismatch"
    if not entitlement.paid or entitlement.status != "active":
        return False, "payment_or_entitlement_inactive"
    if not request_key or len(request_key) > 128:
        return False, "invalid_request_key"
    if now.tzinfo is None:
        return False, "timezone_required"
    if entitlement.plan in SUBSCRIPTIONS:
        start, end = entitlement.period_start, entitlement.period_end
        if (
            not entitlement.subscription_id
            or not entitlement.subscription_id.startswith("sub_")
            or start is None or end is None
            or start.tzinfo is None or end.tzinfo is None
            or not (start.astimezone(timezone.utc) <= now.astimezone(timezone.utc)
                    < end.astimezone(timezone.utc))
        ):
            return False, "unverified_billing_period"
    elif not entitlement.payment_id or not entitlement.payment_id.startswith(("pi_", "cs_")):
        return False, "unverified_one_time_payment"
    if request_key in accepted_unique_tasks:
        return True, "existing_task_idempotent"
    if len(accepted_unique_tasks) >= LIMITS[entitlement.plan]:
        return False, "allowance_exhausted"
    return True, "new_task_allowed"
