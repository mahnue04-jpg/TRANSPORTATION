"""Staging-only bridge from reconciled Stripe TEST subscription to task entitlement.

A saved marketing lead by itself is NEVER proof of subscription entitlement.
Caller must have verified the Stripe webhook signature independently and
retrieved the exact subscription from Stripe; this pure function rechecks the
customer, plan, price, paid invoice, and period before allowing reservations.
Do not expose as a public route or attach to a production worker.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .operations_package_allowances import VerifiedEntitlement

PRICES = {"launch_99": 9900, "business_299": 29900}


class SubscriptionNotEntitled(ValueError):
    pass


def _id(value: Any) -> Any:
    return value.get("id") if isinstance(value, dict) else value


def _timestamp(value: Any) -> datetime:
    # Reject bool (subclass of int), float, missing, and implausible timestamps.
    if type(value) is not int or value < 1_600_000_000 or value > 4_000_000_000:
        raise SubscriptionNotEntitled("period_not_verified")
    return datetime.fromtimestamp(value, tz=timezone.utc)


def from_reconciled_test_subscription(
    *, plan: str, lead_id: str, saved_customer_id: str,
    saved_subscription_id: str, saved_payment_status: str,
    test_price_id: str, subscription: Mapping[str, Any],
    now: datetime,
) -> VerifiedEntitlement:
    """Fail closed: a verified current paid invoice is required for every period."""
    if plan not in PRICES or not lead_id or not saved_customer_id or not saved_subscription_id:
        raise SubscriptionNotEntitled("missing_saved_identity")
    if (not test_price_id.startswith("price_") or not now.tzinfo
            or saved_payment_status != "paid"):
        raise SubscriptionNotEntitled("not_reconciled_paid")
    if (subscription.get("livemode") is not False
            or _id(subscription.get("id")) != saved_subscription_id
            or not saved_subscription_id.startswith("sub_")
            or _id(subscription.get("customer")) != saved_customer_id
            or subscription.get("status") != "active"):
        raise SubscriptionNotEntitled("subscription_inactive_or_mismatched")
    metadata = subscription.get("metadata") or {}
    if not isinstance(metadata, dict) or any(metadata.get(key) != value for key, value in {
        "nova_product": "nova_anonymous_operations_agent",
        "nova_agent_lead_id": lead_id, "nova_agent_plan": plan,
    }.items()):
        raise SubscriptionNotEntitled("subscription_metadata_mismatch")
    items = (subscription.get("items") or {}).get("data") or []
    if (len(items) != 1 or items[0].get("quantity") != 1
            or _id(items[0].get("price")) != test_price_id):
        raise SubscriptionNotEntitled("price_mismatch")
    item = items[0]
    start = _timestamp(item.get("current_period_start"))
    end = _timestamp(item.get("current_period_end"))
    if not (start <= now.astimezone(timezone.utc) < end):
        raise SubscriptionNotEntitled("period_inactive")
    invoice = subscription.get("latest_invoice") or {}
    if (not isinstance(invoice, dict) or invoice.get("status") != "paid"
            or invoice.get("paid") is not True
            or invoice.get("currency") != "usd"
            or type(invoice.get("amount_paid")) is not int
            or invoice.get("amount_paid") != PRICES[plan]
            or _id(invoice.get("subscription")) != saved_subscription_id
            or _id(invoice.get("customer")) != saved_customer_id):
        raise SubscriptionNotEntitled("invoice_not_verified")
    # A paid historical invoice must not grant tasks during a different period.
    lines = (invoice.get("lines") or {}).get("data") or []
    if not any(
        _id(line.get("subscription")) == saved_subscription_id
        and (line.get("period") or {}).get("start") == int(start.timestamp())
        and (line.get("period") or {}).get("end") == int(end.timestamp())
        for line in lines if isinstance(line, dict)
    ):
        raise SubscriptionNotEntitled("invoice_period_mismatch")
    return VerifiedEntitlement(
        plan=plan, customer_id=saved_customer_id, paid=True, status="active",
        subscription_id=saved_subscription_id, period_start=start, period_end=end,
    )
