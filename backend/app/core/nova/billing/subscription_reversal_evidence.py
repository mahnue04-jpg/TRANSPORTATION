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


def _plain(value):
    return value.to_dict_recursive() if hasattr(value, "to_dict_recursive") else value


def verify_current_invoice_payment(client, *, plan, customer_id, subscription):
    """Retrieve fresh evidence using a caller's already-verified TEST client.

    No payment mutation. Deny unsupported invoice or provider response shapes.
    """
    try:
        invoice = subscription["latest_invoice"]
        invoice_id = invoice["id"]
        if (invoice["livemode"] is not False or invoice["status"] != "paid"
                or _id(invoice["customer"]) != customer_id
                or not isinstance(invoice_id, str) or not invoice_id.startswith("in_")):
            return False
        payments = _plain(client.v1.invoice_payments.list({"invoice": invoice_id, "limit": 2}))
        if payments["has_more"] is not False or len(payments["data"]) != 1:
            return False
        payment = payments["data"][0]
        intent_id = _id(payment["payment"]["payment_intent"])
        if not isinstance(intent_id, str) or not intent_id.startswith("pi_"):
            return False
        intent = _plain(client.v1.payment_intents.retrieve(intent_id))
        charge_id = _id(intent["latest_charge"])
        if not isinstance(charge_id, str) or not charge_id.startswith("ch_"):
            return False
        charge = _plain(client.v1.charges.retrieve(charge_id))
        return unreversed_monthly_payment(plan=plan, customer_id=customer_id,
            invoice_id=invoice_id, invoice_payments=payments, payment_intent=intent, charge=charge)
    except Exception:
        return False
