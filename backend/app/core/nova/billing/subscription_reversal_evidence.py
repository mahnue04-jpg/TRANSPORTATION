"""Staging-only, read-only payment reversal evidence for monthly plans.

Not a webhook handler. Callers must retrieve the exact invoice's complete payment
list and referenced PaymentIntent/Charge from the same trusted Stripe TEST account.
A paid invoice alone does not establish absence of a refund or dispute.
This deliberately supports only one full card payment; unsupported shapes deny.
"""
from __future__ import annotations

AMOUNTS = {"starter": 999, "launch_99": 9900, "business_299": 29900}


def _id(value):
    return value.get("id") if isinstance(value, dict) else value


def unreversed_monthly_payment(*, plan, customer_id, invoice_id,
                               invoice_payments, payment_intent, charge):
    """Return False on missing, inconsistent, partial or reversed evidence."""
    try:
        amount = AMOUNTS[plan]
        if not isinstance(customer_id, str) or not customer_id.startswith("cus_"):
            return False
        if not isinstance(invoice_id, str) or not invoice_id.startswith("in_"):
            return False
        if invoice_payments["has_more"] is not False or len(invoice_payments["data"]) != 1:
            return False
        payment = invoice_payments["data"][0]
        if (payment["livemode"] is not False or _id(payment["invoice"]) != invoice_id
                or payment["status"] != "paid" or payment["currency"] != "usd"
                or type(payment["amount_paid"]) is not int or payment["amount_paid"] != amount):
            return False
        reference = payment["payment"]
        intent_id = _id(reference["payment_intent"])
        if reference["type"] != "payment_intent" or not isinstance(intent_id, str) or not intent_id.startswith("pi_"):
            return False
        if (payment_intent["id"] != intent_id or payment_intent["livemode"] is not False
                or _id(payment_intent["customer"]) != customer_id
                or payment_intent["status"] != "succeeded" or payment_intent["currency"] != "usd"
                or type(payment_intent["amount_received"]) is not int
                or payment_intent["amount_received"] != amount):
            return False
        charge_id = _id(payment_intent["latest_charge"])
        if not isinstance(charge_id, str) or not charge_id.startswith("ch_"):
            return False
        return (
            charge["id"] == charge_id and charge["livemode"] is False
            and _id(charge["payment_intent"]) == intent_id
            and _id(charge["customer"]) == customer_id
            and charge["currency"] == "usd"
            and type(charge["amount_captured"]) is int and charge["amount_captured"] == amount
            and charge["status"] == "succeeded" and charge["paid"] is True
            and charge["captured"] is True and charge["refunded"] is False
            and type(charge["amount_refunded"]) is int and charge["amount_refunded"] == 0
            and charge["disputed"] is False
        )
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return False
