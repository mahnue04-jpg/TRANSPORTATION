from datetime import datetime, timedelta, timezone

import pytest

from app.core.nova.work_revenue.operations_subscription_entitlement import (
    SubscriptionNotEntitled, from_reconciled_test_subscription,
)

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)
START, END = NOW - timedelta(days=1), NOW + timedelta(days=29)


def fixture(plan="launch_99"):
    amount = {"launch_99": 9900, "business_299": 29900}[plan]
    subscription = {
        "id": "sub_synthetic", "livemode": False,
        "customer": "cus_synthetic", "status": "active",
        "metadata": {"nova_product": "nova_anonymous_operations_agent",
                     "nova_agent_lead_id": "lead_synthetic", "nova_agent_plan": plan},
        "items": {"data": [{"quantity": 1, "price": "price_synthetic",
                            "current_period_start": int(START.timestamp()),
                            "current_period_end": int(END.timestamp())}]},
        "latest_invoice": {
            "status": "paid", "paid": True, "currency": "usd", "amount_paid": amount,
            "customer": "cus_synthetic", "subscription": "sub_synthetic",
            "lines": {"data": [{
                "subscription": "sub_synthetic",
                "period": {"start": int(START.timestamp()), "end": int(END.timestamp())},
            }]},
        },
    }
    return subscription


def reconcile(subscription, plan="launch_99", **kw):
    params = dict(
        plan=plan, lead_id="lead_synthetic",
        saved_customer_id="cus_synthetic",
        saved_subscription_id="sub_synthetic", saved_payment_status="paid",
        test_price_id="price_synthetic", subscription=subscription, now=NOW,
    )
    params.update(kw)
    return from_reconciled_test_subscription(**params)


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_matching_test_paid_subscription(plan):
    e = reconcile(fixture(plan), plan=plan)
    assert e.paid and e.status == "active" and e.subscription_id == "sub_synthetic"
    assert e.period_start == START and e.period_end == END


def current_api_fixture(plan="launch_99"):
    subscription = fixture(plan)
    subscription["items"]["data"][0]["id"] = "si_synthetic"
    invoice = subscription["latest_invoice"]
    invoice["lines"]["has_more"] = False
    invoice.pop("paid")
    invoice["livemode"] = False
    invoice["parent"] = {
        "type": "subscription_details",
        "subscription_details": {"subscription": invoice.pop("subscription")},
    }
    line = invoice["lines"]["data"][0]
    line["parent"] = {
        "type": "subscription_item_details",
        "subscription_item_details": {
            "subscription": line.pop("subscription"),
            "subscription_item": "si_synthetic",
            "proration": False,
        },
    }
    line["pricing"] = {"type": "price_details", "price_details": {"price": "price_synthetic"}}
    line["quantity"] = 1
    return subscription


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_matching_current_stripe_invoice_shape(plan):
    entitlement = reconcile(current_api_fixture(plan), plan=plan)
    assert entitlement.paid and entitlement.period_start == START and entitlement.period_end == END


def test_current_stripe_invoice_rejects_mismatched_parent():
    subscription = current_api_fixture()
    subscription["latest_invoice"]["parent"]["subscription_details"]["subscription"] = "sub_other"
    with pytest.raises(SubscriptionNotEntitled, match="invoice_not_verified"):
        reconcile(subscription)


def test_current_stripe_invoice_rejects_proration_as_period_evidence():
    subscription = current_api_fixture()
    line = subscription["latest_invoice"]["lines"]["data"][0]
    line["parent"]["subscription_item_details"]["proration"] = True
    with pytest.raises(SubscriptionNotEntitled, match="invoice_period_mismatch"):
        reconcile(subscription)


@pytest.mark.parametrize("change", [
    lambda s: s.update(status="canceled"),
    lambda s: s.update(status="past_due"),
    lambda s: s.update(livemode=True),
    lambda s: s.update(customer="cus_other"),
    lambda s: s["metadata"].update(nova_agent_plan="business_299"),
    lambda s: s["items"]["data"][0].update(quantity=2),
    lambda s: s["items"]["data"][0].update(price="price_wrong"),
    lambda s: s["latest_invoice"].update(status="open"),
    lambda s: s["latest_invoice"].update(amount_paid=4900),
    lambda s: s["latest_invoice"].update(subscription="sub_other"),
    lambda s: s["latest_invoice"]["lines"]["data"][0]["period"].update(end=int((END+timedelta(days=1)).timestamp())),
    lambda s: s["items"]["data"][0].update(current_period_end=int(NOW.timestamp())),
])
def test_mismatched_or_unpaid_subscription_is_denied(change):
    s = fixture()
    change(s)
    with pytest.raises(SubscriptionNotEntitled):
        reconcile(s)


def test_saved_failed_payment_is_denied():
    with pytest.raises(SubscriptionNotEntitled):
        reconcile(fixture(), saved_payment_status="failed")


def test_subscription_not_for_one_time_starter():
    with pytest.raises(SubscriptionNotEntitled):
        reconcile(fixture(), plan="starter_49")


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_renewal_requires_fresh_paid_invoice(plan):
    sub = current_api_fixture(plan)
    sub["cancel_at_period_end"] = True
    assert reconcile(sub, plan=plan).period_end == END
    with pytest.raises(SubscriptionNotEntitled):
        reconcile(sub, plan=plan, now=END)
    item = sub["items"]["data"][0]
    next_end = END + timedelta(days=30)
    item.update(current_period_start=int(END.timestamp()),
                current_period_end=int(next_end.timestamp()))
    sub["cancel_at_period_end"] = False
    with pytest.raises(SubscriptionNotEntitled, match="invoice_period_mismatch"):
        reconcile(sub, plan=plan, now=END)
    invoice = sub["latest_invoice"]
    invoice["lines"]["data"][0]["period"] = {
        "start": int(END.timestamp()), "end": int(next_end.timestamp())}
    invoice["status"] = "open"
    with pytest.raises(SubscriptionNotEntitled):
        reconcile(sub, plan=plan, now=END)
    invoice["status"] = "paid"
    entitlement = reconcile(sub, plan=plan, now=END)
    assert entitlement.period_start == END and entitlement.period_end == next_end
    sub["status"] = "canceled"
    with pytest.raises(SubscriptionNotEntitled):
        reconcile(sub, plan=plan, now=END)


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
@pytest.mark.parametrize("change", [
    lambda s: s["latest_invoice"]["lines"].update(has_more=True),
    lambda s: s["latest_invoice"]["lines"]["data"][0]["parent"]["subscription_item_details"].update(subscription_item="si_other"),
    lambda s: s["latest_invoice"]["lines"]["data"][0]["pricing"]["price_details"].update(price="price_other"),
    lambda s: s["latest_invoice"]["lines"]["data"][0].update(quantity=2),
])
def test_current_invoice_requires_exact_item_and_price(plan, change):
    sub = current_api_fixture(plan)
    change(sub)
    with pytest.raises(SubscriptionNotEntitled, match="invoice_item_price_mismatch"):
        reconcile(sub, plan=plan)


@pytest.mark.parametrize("plan", ["launch_99", "business_299"])
def test_hosted_acceptance_requires_current_invoice(plan):
    with pytest.raises(SubscriptionNotEntitled, match="current_invoice_required"):
        reconcile(fixture(plan), plan=plan, require_current_invoice=True)
    assert reconcile(current_api_fixture(plan), plan=plan, require_current_invoice=True).paid
