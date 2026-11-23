"""Refund/dispute entitlement invariants without Stripe or database writes."""
import pytest

from app.modules.marketing.starter_entitlement_policy import (
    BLOCKING_STATES, entitlement_allows_delivery, transition_entitlement,
)


def test_paid_without_explicit_active_entitlement_never_allows_delivery():
    for state in (None, "unverified", "refund_pending", "refunded", "disputed", "chargeback"):
        assert not entitlement_allows_delivery(payment_status="paid", entitlement_state=state)
    assert entitlement_allows_delivery(payment_status="paid", entitlement_state="active")
    assert not entitlement_allows_delivery(payment_status="pending", entitlement_state="active")


@pytest.mark.parametrize("blocked", sorted(BLOCKING_STATES))
def test_refund_dispute_states_are_irreversible_on_replayed_success(blocked):
    assert transition_entitlement("active", blocked) == blocked
    assert transition_entitlement(blocked, "paid") == blocked
    assert transition_entitlement(blocked, blocked) == blocked
    assert not entitlement_allows_delivery(payment_status="paid", entitlement_state=blocked)


def test_paid_event_activates_only_nonrevoked_entitlement():
    assert transition_entitlement("unverified", "paid") == "active"
    assert transition_entitlement("active", "paid") == "active"
    assert transition_entitlement(None, "unknown") == "unverified"


def test_unknown_event_cannot_restore_revoked_entitlement():
    assert transition_entitlement("disputed", "unknown") == "disputed"
    assert transition_entitlement("refunded", "paid") == "refunded"
