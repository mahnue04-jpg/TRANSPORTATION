"""Pure Stripe refund/dispute correlation for one-time Starter orders.

Caller must first authenticate Stripe webhook signature. No metadata-derived
order matching: payment_intent must equal the identifier captured from the
previously verified Starter Checkout Session. No database writes or Stripe API.
"""
from __future__ import annotations

from typing import Any


REVOCATION_EVENTS = {
    "charge.refunded": "refund_pending",
    "charge.dispute.created": "disputed",
    "charge.dispute.closed": "disputed",
}


def _stripe_id(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("id")
    return value.strip() if isinstance(value, str) else ""


def matched_starter_revocation(
    *,
    lead: Any,
    event_type: str,
    event_object: dict,
) -> str | None:
    """Return restrictive entitlement state for an *exact* paid intent match.

    Returns None for unsupported or unrelated events; never infer identity from
    mutable metadata, customer email, an unrelated charge, or lead IDs.
    """
    state = REVOCATION_EVENTS.get(event_type)
    if state is None or not isinstance(event_object, dict):
        return None
    if (
        getattr(lead, "lead_type", None) != "anonymous_operations"
        or getattr(lead, "service_plan", None) != "starter_49"
        or not getattr(lead, "starter_paid_session_id", None)
        or getattr(lead, "starter_paid_session_id", None)
        != getattr(lead, "stripe_checkout_session_id", None)
    ):
        return None
    known_intent = _stripe_id(getattr(lead, "starter_payment_intent_id", None))
    event_intent = _stripe_id(event_object.get("payment_intent"))
    if not known_intent or not event_intent or event_intent != known_intent:
        return None
    if not known_intent.startswith("pi_"):
        return None
    return state
