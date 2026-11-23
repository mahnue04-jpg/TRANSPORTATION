"""No-network tests for Starter paid-session checks; webhook verifies signatures first."""
from types import SimpleNamespace
import pytest

from app.modules.marketing.starter_checkout_verification import starter_checkout_outcome


def lead(status="pending"):
    return SimpleNamespace(
        service_plan="starter_49", payment_status=status,
        stripe_checkout_session_id="cs_test_exact",
        stripe_customer_id="cus_exact",
    )


def event(**overrides):
    data = {"id": "cs_test_exact", "customer": "cus_exact", "mode": "payment",
            "currency": "usd", "amount_total": 4900, "payment_status": "paid"}
    data.update(overrides)
    return data


META = {"nova_agent_plan": "starter_49"}


def test_exact_paid_checkout_is_eligible():
    assert starter_checkout_outcome(lead(), "checkout.session.completed", event(), META) == "paid"
    assert starter_checkout_outcome(lead(), "checkout.session.async_payment_succeeded", event(), META) == "paid"


@pytest.mark.parametrize("wrong,expected", [
    ({"id": "cs_test_other"}, "checkout_identity_mismatch"),
    ({"customer": "cus_other"}, "checkout_identity_mismatch"),
    ({"amount_total": 0}, "starter_payment_amount_mismatch"),
    ({"amount_total": 4800}, "starter_payment_amount_mismatch"),
    ({"mode": "subscription"}, "starter_payment_amount_mismatch"),
    ({"currency": "eur"}, "starter_payment_amount_mismatch"),
])
def test_reject_wrong_identity_or_payment_details(wrong, expected):
    assert starter_checkout_outcome(lead(), "checkout.session.completed", event(**wrong), META) == expected


def test_reject_wrong_plan_and_unstored_session():
    assert starter_checkout_outcome(lead(), "checkout.session.completed", event(),
                                    {"nova_agent_plan": "launch_99"}) == "checkout_identity_mismatch"
    candidate = lead()
    candidate.stripe_checkout_session_id = None
    assert starter_checkout_outcome(candidate, "checkout.session.completed", event(), META) == "checkout_identity_mismatch"


def test_no_payment_required_is_not_paid():
    assert starter_checkout_outcome(lead(), "checkout.session.completed",
                                    event(payment_status="no_payment_required"), META) == "pending"


def test_out_of_order_events_cannot_demote_paid_order():
    for typ in ("checkout.session.completed", "checkout.session.async_payment_failed",
                "checkout.session.expired"):
        obj = event(payment_status="unpaid")
        assert starter_checkout_outcome(lead("paid"), typ, obj, META) == "already_paid"


def test_invoice_cannot_pay_one_time_starter():
    assert starter_checkout_outcome(lead(), "invoice.paid", event(), META) == "ignored"


def test_async_failure_and_expiry_for_unpaid():
    assert starter_checkout_outcome(lead(), "checkout.session.async_payment_failed", event(), META) == "failed"
    assert starter_checkout_outcome(lead(), "checkout.session.expired", event(), META) == "expired"
