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
