"""Pure unit tests; no paid provider requests."""
from app.core.nova.creative_studio.spending_policy import (
    SpendingEntry, can_reserve, committed_cents,
)


def test_spending_reservations_do_not_exceed_204_cents():
    entries = [SpendingEntry("voice-1", 3)]
    assert can_reserve(cap_cents=204, estimate_cents=201, request_key="render-1", entries=entries)
    assert not can_reserve(cap_cents=204, estimate_cents=202, request_key="render-2", entries=entries)


def test_duplicate_request_key_is_rejected():
    entries = [SpendingEntry("voice-1", 3)]
    assert not can_reserve(cap_cents=204, estimate_cents=3, request_key="voice-1", entries=entries)


def test_uncertain_job_keeps_its_reservation():
    entries = [SpendingEntry("video-1", 180, status="uncertain")]
    assert committed_cents(entries) == 180
    assert not can_reserve(cap_cents=204, estimate_cents=25, request_key="video-2", entries=entries)


def test_released_reservation_does_not_count():
    entries = [SpendingEntry("voice-1", 3, status="released")]
    assert committed_cents(entries) == 0
    assert can_reserve(cap_cents=204, estimate_cents=204, request_key="video-1", entries=entries)


def test_actual_charge_is_counted():
    entries = [SpendingEntry("voice-1", 3, actual_cents=4, status="charged")]
    assert committed_cents(entries) == 4
    assert not can_reserve(cap_cents=204, estimate_cents=201, request_key="video-1", entries=entries)
