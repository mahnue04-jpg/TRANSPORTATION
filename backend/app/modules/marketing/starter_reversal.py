"""Conservative, signed-event Starter reversal matching; no remote calls."""
from __future__ import annotations

REVERSALS = {
    "charge.refunded": "refunded",
    "charge.dispute.created": "disputed",
    "charge.dispute.funds_withdrawn": "disputed",
}


def reversal_evidence(event_type: str, obj: dict) -> tuple[str, str] | None:
    state = REVERSALS.get(event_type)
    intent = obj.get("payment_intent")
    if isinstance(intent, dict):
        intent = intent.get("id")
    if not state or not isinstance(intent, str) or not intent.startswith("pi_") or len(intent) > 128:
        return None
    if obj.get("livemode") is not False:
        return None
    if event_type == "charge.refunded":
        amount = obj.get("amount_refunded")
        if type(amount) is not int or amount <= 0:
            return None
    return intent, state
