"""Validate the Stripe PaymentIntent on an already identity-matched paid session.

This helper is called only after the webhook's signature verification and
Checkout Session identity/amount validation. No remote API, database or I/O.
"""


def verified_starter_payment_intent(event_object: dict, existing: str | None) -> str | None:
    intent = event_object.get("payment_intent")
    if isinstance(intent, dict):
        intent = intent.get("id")
    if not isinstance(intent, str) or not intent.startswith("pi_") or len(intent) > 128:
        return None
    if existing and existing != intent:
        return None
    return intent
