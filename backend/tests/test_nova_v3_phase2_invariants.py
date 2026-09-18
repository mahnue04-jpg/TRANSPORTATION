"""Local V1/V2 invariant checks that remain safe to run beside V3 Phase 2."""
from __future__ import annotations

from app.core.nova.v3.flags import live_flags
from app.core.nova.work_revenue.flags import engine_guardrails


def test_v3_live_flags_remain_hard_off() -> None:
    flags = live_flags()
    for key, value in flags.items():
        if key == "MOCK_TRANSPORT_ONLY":
            assert value is True
        else:
            assert value is False


def test_v1_engine_guardrails_remain_off() -> None:
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guards["INVOICE_SEND_ENABLED"] is False
