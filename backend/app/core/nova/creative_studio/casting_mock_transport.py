"""In-process message transport for the Casting sandbox.

This module does not import a mail, SMS, or HTTP client. A mock receipt means
the disposable transport accepted a preview. It is not delivery.
"""
from __future__ import annotations

MOCK_PROVIDER = "disposable-mock"
MOCK_OUTCOMES = frozenset({"mock_accepted", "mock_failed", "suppressed", "opted_out"})


class MockTransport:
    """Record one attempt. ``fail`` forces a failure without leaving the process."""

    def __init__(self, *, fail: bool = False):
        self.fail = bool(fail)
        self.calls: list[dict] = []

    def dispatch(
        self,
        *,
        message_id: str,
        idempotency_key: str,
        channel: str,
        outcome_override: str | None,
        prior_receipt: str,
        attempt: int,
    ) -> dict:
        if channel not in {"email", "sms", "whatsapp"}:
            raise ValueError("channel")
        if outcome_override not in {None, "suppressed", "opted_out"}:
            raise ValueError("outcome")
        self.calls.append({
            "message_id": message_id,
            "idempotency_key": idempotency_key,
            "channel": channel,
            "attempt": attempt,
            "provider": MOCK_PROVIDER,
        })
        if outcome_override in {"suppressed", "opted_out"}:
            return _result(outcome_override, "")
        if prior_receipt:
            return _result("mock_accepted", prior_receipt, idempotent=True)
        if self.fail:
            return _result("mock_failed", "", failure="Disposable mock rejected this attempt. Nothing was delivered.")
        receipt = "MOCK-" + str(message_id).replace("-", "")[:12].upper()
        return _result("mock_accepted", receipt)


def _result(outcome: str, receipt: str, *, failure: str = "", idempotent: bool = False) -> dict:
    return {
        "outcome": outcome,
        "mock_receipt": receipt,
        "mock_failure": failure,
        "provider": MOCK_PROVIDER,
        "external_delivery": False,
        "delivered": False,
        "real_delivery": False,
        "idempotent": idempotent,
    }
