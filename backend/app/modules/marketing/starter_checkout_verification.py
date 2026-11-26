"""Verify one-time Starter checkout evidence after Stripe signature verification.

This helper does not verify signatures itself, charge money, or create tasks.
Only the Stripe webhook handler may apply its returned updates.
"""
from __future__ import annotations


def starter_checkout_outcome(lead, event_type: str, obj: dict, metadata: dict) -> str:
    """Return paid/pending/failed/expired or ignore; never trust metadata alone."""
    if lead.service_plan != "starter_49" or not event_type.startswith("checkout.session."):
        return "ignored"
    if (
        not lead.stripe_checkout_session_id
        or str(obj.get("id") or "") != lead.stripe_checkout_session_id
        or str(obj.get("customer") or "") != str(lead.stripe_customer_id or "")
        or str(metadata.get("nova_agent_plan") or "") != "starter_49"
    ):
        return "checkout_identity_mismatch"
    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        if (
            obj.get("mode") != "payment"
            or obj.get("currency") != "usd"
            or obj.get("amount_total") != 4900
        ):
            return "starter_payment_amount_mismatch"
        if obj.get("payment_status") == "paid":
            return "paid"
        return "already_paid" if lead.payment_status == "paid" else "pending"
    if event_type == "checkout.session.async_payment_failed":
        return "already_paid" if lead.payment_status == "paid" else "failed"
    if event_type == "checkout.session.expired":
        return "already_paid" if lead.payment_status == "paid" else "expired"
    return "ignored"
