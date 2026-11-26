"""Synthetic fixtures for monthly payment reversal evidence; no Stripe calls."""
import pytest

from app.core.nova.billing.subscription_reversal_evidence import (
    AMOUNTS, unreversed_monthly_payment,
)


def fixture(plan):
    amount = AMOUNTS[plan]
    return dict(plan=plan, customer_id="cus_synthetic", invoice_id="in_synthetic",
        invoice_payments={"has_more": False, "data": [{
            "livemode": False, "invoice": "in_synthetic", "status": "paid",
            "currency": "usd", "amount_paid": amount,
            "payment": {"type": "payment_intent", "payment_intent": "pi_synthetic"},
        }]},
        payment_intent={"id": "pi_synthetic", "livemode": False,
            "customer": "cus_synthetic", "status": "succeeded", "currency": "usd",
            "amount_received": amount, "latest_charge": "ch_synthetic"},
        charge={"id": "ch_synthetic", "livemode": False, "payment_intent": "pi_synthetic",
            "customer": "cus_synthetic", "currency": "usd", "amount_captured": amount,
            "status": "succeeded", "paid": True, "captured": True,
            "refunded": False, "amount_refunded": 0, "disputed": False})


@pytest.mark.parametrize("plan", sorted(AMOUNTS))
def test_exact_unreversed_payment(plan):
    assert unreversed_monthly_payment(**fixture(plan))


@pytest.mark.parametrize("plan", sorted(AMOUNTS))
@pytest.mark.parametrize("path,value", [
    (("charge", "amount_refunded"), 1),
    (("charge", "refunded"), True),
    (("charge", "disputed"), True),
    (("charge", "livemode"), True),
    (("charge", "customer"), "cus_other"),
    (("charge", "payment_intent"), "pi_other"),
    (("charge", "id"), "ch_other"),
    (("charge", "captured"), False),
    (("charge", "paid"), False),
    (("charge", "amount_captured"), 0),
    (("payment_intent", "livemode"), True),
    (("payment_intent", "status"), "requires_payment_method"),
    (("payment_intent", "amount_received"), 0),
    (("payment_intent", "customer"), "cus_other"),
    (("invoice_payments", "has_more"), True),
    (("invoice_payments", "data", 0, "invoice"), "in_other"),
    (("invoice_payments", "data", 0, "livemode"), True),
    (("invoice_payments", "data", 0, "status"), "open"),
    (("invoice_payments", "data", 0, "amount_paid"), 0),
    (("invoice_payments", "data", 0, "payment", "type"), "payment_record"),
])
def test_bad_or_reversed_evidence(plan, path, value):
    evidence = fixture(plan)
    target = evidence
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert not unreversed_monthly_payment(**evidence)


@pytest.mark.parametrize("plan", sorted(AMOUNTS))
def test_missing_or_multiple_payments_denied(plan):
    evidence = fixture(plan)
    evidence["invoice_payments"]["data"].append(
        evidence["invoice_payments"]["data"][0].copy())
    assert not unreversed_monthly_payment(**evidence)
    evidence = fixture(plan)
    evidence["invoice_payments"]["data"].clear()
    assert not unreversed_monthly_payment(**evidence)
    evidence = fixture(plan)
    del evidence["charge"]["disputed"]
    assert not unreversed_monthly_payment(**evidence)


def test_one_time_plan_not_accepted():
    evidence = fixture("starter")
    evidence["plan"] = "starter_49"
    assert not unreversed_monthly_payment(**evidence)
