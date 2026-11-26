"""Staging-only bridge from reconciled Stripe TEST subscription to task entitlement.

A saved marketing lead by itself is NEVER proof of subscription entitlement.
The caller must verify the webhook signature independently and retrieve the
exact subscription using the Stripe API. This function rechecks the customer,
plan, price, paid invoice, and period before allowing reservations.
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


def _invoice_subscription(invoice: dict) -> Any:
    if "parent" not in invoice:
        return _id(invoice.get("subscription")) if invoice.get("paid") is True else None
    parent = invoice["parent"]
    if not isinstance(parent, dict) or parent.get("type") != "subscription_details":
        return None
    details = parent.get("subscription_details")
    if not isinstance(details, dict):
        return None
    return _id(details.get("subscription"))


def _line_subscription(line: dict) -> Any:
    if "parent" not in line:
        return _id(line.get("subscription"))
    parent = line["parent"]
    if not isinstance(parent, dict) or parent.get("type") != "subscription_item_details":
        return None
    details = parent.get("subscription_item_details")
    if not isinstance(details, dict) or details.get("proration") is not False:
        return None
    return _id(details.get("subscription"))


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
            or invoice.get("livemode", False) is not False
            or invoice.get("paid", True) is not True
            or invoice.get("currency") != "usd"
            or type(invoice.get("amount_paid")) is not int
            or invoice.get("amount_paid") != PRICES[plan]
            or _invoice_subscription(invoice) != saved_subscription_id
            or _id(invoice.get("customer")) != saved_customer_id):
        raise SubscriptionNotEntitled("invoice_not_verified")
    # Current Stripe invoice lines must bind the exact subscription item and price.
    # Legacy fixtures retain their separate compatibility path in staging only.
    if "parent" in invoice:
        item_id = item.get("id")
        line_list = invoice.get("lines") or {}
        current_lines = line_list.get("data") or []
        if (not isinstance(item_id, str) or not item_id.startswith("si_")
                or line_list.get("has_more") is not False or len(current_lines) != 1):
            raise SubscriptionNotEntitled("invoice_item_price_mismatch")
        line = current_lines[0]
        if not isinstance(line, dict):
            raise SubscriptionNotEntitled("invoice_item_price_mismatch")
        parent = line.get("parent") or {}
        details = parent.get("subscription_item_details") or {}
        pricing = line.get("pricing") or {}
        price_details = pricing.get("price_details") or {}
        if (parent.get("type") != "subscription_item_details"
                or _id(details.get("subscription_item")) != item_id
                or pricing.get("type") != "price_details"
                or _id(price_details.get("price")) != test_price_id
                or type(line.get("quantity")) is not int or line["quantity"] != 1):
            raise SubscriptionNotEntitled("invoice_item_price_mismatch")
    # A paid historical invoice must not grant tasks during a different period.
    lines = (invoice.get("lines") or {}).get("data") or []
    if not any(
        _line_subscription(line) == saved_subscription_id
        and (line.get("period") or {}).get("start") == int(start.timestamp())
        and (line.get("period") or {}).get("end") == int(end.timestamp())
        for line in lines if isinstance(line, dict)
    ):
        raise SubscriptionNotEntitled("invoice_period_mismatch")
    return VerifiedEntitlement(
        plan=plan, customer_id=saved_customer_id, paid=True, status="active",
        subscription_id=saved_subscription_id, period_start=start, period_end=end,
    )
