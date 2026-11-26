"""Read-only validation of exact tenant-bound Starter sandbox subscription evidence."""
from datetime import datetime, timezone

from .starter_self_service import allows_starter_feature


def _id(value):
    return value.get("id") if isinstance(value, dict) else value


def verify_starter_feature(*, feature, tenant_id, row, subscription, now):
    """Inputs must originate from trusted DB and freshly retrieved Stripe records."""
    try:
        if row.tenant_id != tenant_id or row.plan_key != "starter":
            return False
        if row.subscription_status != "active":
            return False
        if not row.stripe_customer_id or not row.stripe_subscription_id:
            return False
        if not row.stripe_subscription_id.startswith("sub_"):
            return False
        if (subscription.get("id") != row.stripe_subscription_id
                or _id(subscription.get("customer")) != row.stripe_customer_id
                or subscription.get("livemode") is not False
                or subscription.get("status") != "active"):
            return False
        metadata = subscription["metadata"]
        if any(metadata.get(k) != v for k, v in {
            "nova_product": "nova_saas", "nova_tenant_id": tenant_id,
            "nova_plan_key": "starter",
        }.items()):
            return False
        items = subscription["items"]
        if items.get("has_more") is not False or len(items["data"]) != 1:
            return False
        item = items["data"][0]
        price = item["price"]
        item_id = item["id"]
        if not isinstance(item_id, str) or not item_id.startswith("si_"):
            return False
        if (type(item["quantity"]) is not int or item["quantity"] != 1
                or price["id"] != row.stripe_price_id
                or price["livemode"] is not False
                or price["unit_amount"] != 999 or price["currency"] != "usd"
                or price["recurring"]["interval"] != "month"
                or price["recurring"]["interval_count"] != 1):
            return False
        start, end = item["current_period_start"], item["current_period_end"]
        if type(start) is not int or type(end) is not int:
            return False
        period_start = datetime.fromtimestamp(start, timezone.utc)
        period_end = datetime.fromtimestamp(end, timezone.utc)
        if now.utcoffset() is None or not period_start <= now < period_end:
            return False
        invoice = subscription["latest_invoice"]
        if (invoice["livemode"] is not False or invoice["status"] != "paid"
                or invoice["currency"] != "usd" or invoice["amount_paid"] != 999
                or _id(invoice["customer"]) != row.stripe_customer_id):
            return False
        parent = invoice["parent"]
        if (parent["type"] != "subscription_details"
                or _id(parent["subscription_details"]["subscription"]) != row.stripe_subscription_id):
            return False
        lines = invoice["lines"]
        if lines.get("has_more") is not False or len(lines["data"]) != 1:
            return False
        line = lines["data"][0]
        details = line["parent"]["subscription_item_details"]
        if (line["parent"]["type"] != "subscription_item_details"
                or details["proration"] is not False
                or _id(details["subscription"]) != row.stripe_subscription_id
                or _id(details["subscription_item"]) != item_id
                or line["pricing"]["type"] != "price_details"
                or _id(line["pricing"]["price_details"]["price"]) != price["id"]
                or type(line["quantity"]) is not int or line["quantity"] != 1
                or line["period"]["start"] != start or line["period"]["end"] != end):
            return False
        return allows_starter_feature(feature=feature, tenant_id=tenant_id,
            verified_tenant_id=metadata["nova_tenant_id"], recorded_plan=row.plan_key,
            status=subscription["status"], recorded_price=price["id"],
            verified_subscription=True, verified_paid_invoice=True,
            stripe_livemode=subscription["livemode"], current_period_end=period_end, now=now)
    except (AttributeError, KeyError, TypeError, ValueError, OverflowError, OSError):
        return False
