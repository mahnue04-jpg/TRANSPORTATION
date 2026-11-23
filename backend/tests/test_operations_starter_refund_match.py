"""Synthetic correlation tests; no API calls, DB writes, or real Stripe records."""
from types import SimpleNamespace

import pytest

from app.modules.marketing.starter_refund_match import matched_starter_revocation


def lead(**overrides):
    values = {
        "lead_type": "anonymous_operations",
        "service_plan": "starter_49",
        "stripe_checkout_session_id": "cs_test_starter",
        "starter_paid_session_id": "cs_test_starter",
        "starter_payment_intent_id": "pi_test_starter",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.parametrize("event_type,expected", [
    ("charge.refunded", "refund_pending"),
    ("charge.dispute.created", "disputed"),
    ("charge.dispute.closed", "disputed"),
])
def test_exact_payment_intent_matches_revocation(event_type, expected):
    assert matched_starter_revocation(
        lead=lead(), event_type=event_type,
        event_object={"id": "ch_test_a", "payment_intent": "pi_test_starter"},
    ) == expected


@pytest.mark.parametrize("different", [
    {"starter_payment_intent_id": None},
    {"starter_payment_intent_id": "pi_test_other"},
    {"stripe_checkout_session_id": "cs_test_other"},
    {"starter_paid_session_id": None},
    {"service_plan": "launch_99"},
    {"lead_type": "other"},
])
def test_wrong_or_missing_paid_order_is_ignored(different):
    assert matched_starter_revocation(
        lead=lead(**different), event_type="charge.refunded",
        event_object={"payment_intent": "pi_test_starter"},
    ) is None


def test_missing_or_wrong_event_payment_intent_is_not_matched():
    for obj in ({}, {"payment_intent": None},
                {"payment_intent": "pi_test_other"},
                {"metadata": {"nova_agent_lead_id": "synthetic-lead"}}):
        assert matched_starter_revocation(
            lead=lead(), event_type="charge.refunded", event_object=obj,
        ) is None


def test_unsupported_event_and_fake_metadata_cannot_revoke():
    assert matched_starter_revocation(
        lead=lead(), event_type="invoice.paid",
        event_object={"payment_intent": "pi_test_starter"},
    ) is None


def test_stripe_expanded_payment_intent_is_supported():
    assert matched_starter_revocation(
        lead=lead(), event_type="charge.dispute.created",
        event_object={"payment_intent": {"id": "pi_test_starter"}},
    ) == "disputed"
