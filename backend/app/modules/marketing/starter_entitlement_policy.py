"""Monotonic Starter entitlement policy; no Stripe API calls or database writes.

A signed webhook alone is not proof of which Starter order a refund/dispute
belongs to. A separate verified PaymentIntent/charge-to-checkout association
must be implemented before this policy may be wired to live authorization.
"""
from __future__ import annotations

BLOCKING_STATES = frozenset({"refund_pending", "refunded", "disputed", "chargeback"})
ACTIVE_STATE = "active"
PAID_EVENT_STATE = "paid"


def entitlement_allows_delivery(*, payment_status: str | None, entitlement_state: str | None) -> bool:
    """Fail closed on unverified or revoked entitlement, regardless of old paid flags."""
    return payment_status == PAID_EVENT_STATE and entitlement_state == ACTIVE_STATE


def transition_entitlement(current: str | None, event: str) -> str:
    """Revocation wins over delayed and duplicate payment-success notifications.

    Returns the existing restrictive state on retries. Restoring entitlement
    must be an explicit separately reviewed owner-authorized process.
    """
    if current in BLOCKING_STATES:
        return current
    if event in BLOCKING_STATES:
        return event
    if event == PAID_EVENT_STATE:
        return ACTIVE_STATE
    return current or "unverified"
