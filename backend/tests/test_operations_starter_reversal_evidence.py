from app.modules.marketing.starter_reversal import reversal_evidence
from app.modules.marketing.starter_entitlement_policy import transition_entitlement


def test_partial_refund_blocks_entitlement():
    assert reversal_evidence("charge.refunded", {"payment_intent": "pi_test", "livemode": False, "amount_refunded": 1}) == ("pi_test", "refunded")


def test_dispute_and_delayed_success():
    assert reversal_evidence("charge.dispute.created", {"payment_intent": {"id": "pi_test"}, "livemode": False}) == ("pi_test", "disputed")
    assert transition_entitlement("disputed", "paid") == "disputed"
    assert transition_entitlement("refunded", "paid") == "refunded"


def test_unrelated_or_incomplete_evidence_denied():
    for obj in ({"payment_intent": "ch_wrong", "livemode": False}, {"payment_intent": "pi_test", "livemode": True}, {"payment_intent": "pi_test"}, {"payment_intent": "pi_test", "livemode": False, "amount_refunded": 0}):
        assert reversal_evidence("charge.refunded", obj) is None
    assert reversal_evidence("invoice.paid", {"payment_intent": "pi_test", "livemode": False}) is None
