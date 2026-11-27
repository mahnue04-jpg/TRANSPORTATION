"""Verify Launch/Business subscription checkout evidence after signature check.

Does not verify signatures, charge money, or fulfill tasks. Only the Operations
Agent webhook may apply returned updates.
"""
from __future__ import annotations

from app.core.nova.billing.operations_catalog import LIVE_OPERATIONS_PRICES
from app.modules.marketing.operations_billing import AGENT_PLANS, subscription_test_price

SUBSCRIPTION_PLANS = frozenset({"launch_99", "business_299"})


def _price_id_from_session(obj: dict) -> str | None:
    items = obj.get("line_items")
    if isinstance(items, dict):
        items = items.get("data")
    if not isinstance(items, list) or len(items) != 1:
        return None
    item = items[0]
    if not isinstance(item, dict) or item.get("quantity") not in (1, None):
        return None
    price = item.get("price")
    if isinstance(price, dict):
        price = price.get("id")
    return str(price) if isinstance(price, str) and price.startswith("price_") else None


def subscription_checkout_outcome(
    lead, event_type: str, obj: dict, metadata: dict, *, expected_livemode: bool,
) -> str:
    """Return paid/pending/failed/expired or ignore for monthly Operations plans."""
    plan = str(getattr(lead, "service_plan", "") or "")
    if plan not in SUBSCRIPTION_PLANS or not event_type.startswith(("checkout.session.", "invoice.")):
        return "ignored"
    if (
        not lead.stripe_checkout_session_id
        or str(obj.get("customer") or "") != str(lead.stripe_customer_id or "")
        or str(metadata.get("nova_agent_plan") or plan) != plan
        or obj.get("livemode") is not expected_livemode
    ):
        return "checkout_identity_mismatch"

    expected_amount = int(AGENT_PLANS[plan]["amount_cents"])
    expected_price = (
        LIVE_OPERATIONS_PRICES[plan] if expected_livemode
        else subscription_test_price(plan)
    )
    if not expected_price:
        return "subscription_price_unconfigured"

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        if str(obj.get("id") or "") != lead.stripe_checkout_session_id:
            return "checkout_identity_mismatch"
        if obj.get("mode") != "subscription" or obj.get("currency") != "usd":
            return "subscription_checkout_mismatch"
        amount = obj.get("amount_total")
        if amount is not None and amount != expected_amount:
            return "subscription_payment_amount_mismatch"
        price_id = _price_id_from_session(obj)
        if price_id is not None and price_id != expected_price:
            return "subscription_price_mismatch"
        if obj.get("payment_status") in {"paid", "no_payment_required"}:
            return "paid"
        return "already_paid" if lead.payment_status == "paid" else "pending"

    if event_type == "invoice.paid":
        if obj.get("currency") != "usd" or obj.get("status") != "paid":
            return "subscription_invoice_mismatch"
        amount_paid = obj.get("amount_paid")
        if type(amount_paid) is not int or amount_paid != expected_amount:
            return "subscription_payment_amount_mismatch"
        return "paid"

    if event_type in {"checkout.session.async_payment_failed", "invoice.payment_failed"}:
        return "already_paid" if lead.payment_status == "paid" else "failed"
    if event_type == "checkout.session.expired":
        return "already_paid" if lead.payment_status == "paid" else "expired"
    return "ignored"


def subscription_id_from_object(obj: dict) -> str | None:
    subscription = obj.get("subscription")
    if isinstance(subscription, dict):
        subscription = subscription.get("id")
    if isinstance(subscription, str) and subscription.startswith("sub_"):
        return subscription
    parent = obj.get("parent")
    if isinstance(parent, dict) and parent.get("type") == "subscription_details":
        details = parent.get("subscription_details") or {}
        subscription = details.get("subscription")
        if isinstance(subscription, dict):
            subscription = subscription.get("id")
        if isinstance(subscription, str) and subscription.startswith("sub_"):
            return subscription
    return None
