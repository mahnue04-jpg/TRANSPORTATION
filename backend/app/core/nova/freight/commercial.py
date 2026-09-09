"""Nova freight quotes, invoices, and TEST customer charges. No Delivery/Health billing."""
from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.nova.freight.models import (
    NovaFreightInvoice,
    NovaFreightPaymentEvent,
    NovaFreightQuote,
    NovaFreightShipment,
    NovaFreightShipmentEvent,
)
from app.core.nova.freight.money import from_minor_units, money, to_minor_units
from app.core.nova.freight.payout_config import split_customer_amount
from app.core.nova.freight.rates import suggested_quote
from app.core.nova.freight.schemas import (
    NovaFreightCustomerQuoteOut,
    NovaFreightInvoiceOut,
    NovaFreightQuoteOut,
    NovaFreightQuoteUpdate,
)
from app.core.nova.freight.service import NovaFreightError, get_shipment
from app.core.nova.freight.stripe_checkout import (
    get_nova_freight_stripe_client,
    get_nova_freight_stripe_override,
    sanitize_stripe_error,
    stripe_publishable_key,
)
from app.helpers import now, uuid4

QUOTE_STATUSES = ("draft", "suggested", "adjusted", "finalized")
INVOICE_STATUSES = ("draft", "ready", "payment_pending", "paid", "failed", "void")


def _new_quote_id() -> str:
    return "NFQ-" + uuid4().replace("-", "")[:10].upper()


def _new_invoice_id() -> str:
    return "NFI-" + uuid4().replace("-", "")[:10].upper()


def _new_event_id() -> str:
    return "NFE-" + uuid4().replace("-", "")[:10].upper()


def _add_event(
    db: Session,
    shipment: NovaFreightShipment,
    *,
    event_type: str,
    actor_user_id: str | None,
    actor_role: str | None,
    notes: str | None,
    quote_id: str | None = None,
    invoice_id: str | None = None,
) -> None:
    db.add(
        NovaFreightShipmentEvent(
            event_id=_new_event_id(),
            shipment_id=shipment.shipment_id,
            organization_id=shipment.organization_id,
            status_before=shipment.status,
            status_after=shipment.status,
            event_type=event_type,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            notes=notes,
            source="nova_freight_commercial",
            quote_id=quote_id,
            invoice_id=invoice_id,
            created_at=now(),
        )
    )


def _get_quote(db: Session, shipment_id: str, organization_id: str) -> NovaFreightQuote | None:
    return (
        db.query(NovaFreightQuote)
        .filter(
            NovaFreightQuote.shipment_id == shipment_id,
            NovaFreightQuote.organization_id == organization_id,
        )
        .first()
    )


def _get_active_invoice(db: Session, shipment_id: str, organization_id: str) -> NovaFreightInvoice | None:
    return (
        db.query(NovaFreightInvoice)
        .filter(
            NovaFreightInvoice.shipment_id == shipment_id,
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.invoice_status != "void",
        )
        .order_by(NovaFreightInvoice.created_at.desc())
        .first()
    )


def calculate_suggested_quote(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    estimated_miles: object = None,
    estimated_hours: object = None,
    other_surcharge: object = None,
    discount_amount: object = None,
) -> dict:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    return suggested_quote(
        equipment_type=shipment.equipment_type,
        estimated_miles=estimated_miles,
        estimated_hours=estimated_hours,
        weight=shipment.weight,
        pallet_count=shipment.pallet_count,
        hazardous=shipment.hazardous,
        temperature_controlled=shipment.temperature_controlled,
        fragile=shipment.fragile,
        other_surcharge=other_surcharge,
        discount_amount=discount_amount,
    )


def _apply_breakdown(row: NovaFreightQuote, breakdown: dict, *, quoted_amount: Decimal) -> None:
    row.pricing_method = str(breakdown["pricing_method"])
    row.currency = str(breakdown["currency"])
    row.base_rate = money(breakdown["base_rate"])
    row.mileage_amount = money(breakdown["mileage_amount"])
    row.time_amount = money(breakdown["time_amount"])
    row.equipment_surcharge = money(breakdown["equipment_surcharge"])
    row.special_handling_surcharge = money(breakdown["special_handling_surcharge"])
    row.fuel_surcharge = money(breakdown["fuel_surcharge"])
    row.other_surcharge = money(breakdown["other_surcharge"])
    row.discount_amount = money(breakdown["discount_amount"])
    row.tax_amount = money(breakdown["tax_amount"])
    row.suggested_amount = money(breakdown["suggested_amount"])
    row.quoted_amount = money(quoted_amount)
    row.total_customer_amount = money(quoted_amount)
    _customer, row.estimated_carrier_cost, row.estimated_amicor_margin = split_customer_amount(quoted_amount)


def save_quote(
    db: Session,
    shipment_id: str,
    payload: NovaFreightQuoteUpdate,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightQuote:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    existing = _get_quote(db, shipment_id, organization_id)
    if existing and existing.pricing_status == "finalized":
        raise NovaFreightError("Finalized quotes cannot be edited", status_code=409)
    breakdown = calculate_suggested_quote(
        db,
        shipment_id,
        organization_id=organization_id,
        estimated_miles=payload.estimated_miles,
        estimated_hours=payload.estimated_hours,
        other_surcharge=payload.other_surcharge,
        discount_amount=payload.discount_amount,
    )
    quoted = money(payload.quoted_amount) if payload.quoted_amount is not None else money(breakdown["suggested_amount"])
    if quoted < money(0):
        raise NovaFreightError("Quoted amount cannot be negative", status_code=409)
    method = "manual_override" if payload.quoted_amount is not None else "rate_engine"
    stamp = now()
    created = existing is None
    row = existing or NovaFreightQuote(
        quote_id=_new_quote_id(),
        shipment_id=shipment.shipment_id,
        organization_id=organization_id,
    )
    _apply_breakdown(row, breakdown, quoted_amount=quoted)
    row.pricing_method = method
    row.pricing_status = "adjusted" if payload.quoted_amount is not None else "suggested"
    row.estimated_miles = money(payload.estimated_miles) if payload.estimated_miles is not None else None
    row.estimated_hours = money(payload.estimated_hours) if payload.estimated_hours is not None else None
    row.quote_notes = payload.quote_notes
    row.customer_notes = payload.customer_notes
    row.quoted_by_user_id = actor_user_id
    row.quoted_at = stamp
    row.last_adjusted_by_user_id = actor_user_id
    row.last_adjusted_at = stamp
    row.updated_at = stamp
    if created:
        db.add(row)
    db.flush()
    _add_event(
        db,
        shipment,
        event_type="quote_created" if created else "quote_updated",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"amount={row.quoted_amount} suggested={row.suggested_amount} method={row.pricing_method}",
        quote_id=row.quote_id,
    )
    db.commit()
    db.refresh(row)
    return row


def finalize_quote(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightQuote:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    row = _get_quote(db, shipment_id, organization_id)
    if row is None:
        raise NovaFreightError("Quote must be calculated before it can be finalized", status_code=409)
    if row.pricing_status == "finalized":
        return row
    stamp = now()
    row.pricing_status = "finalized"
    row.finalized_by_user_id = actor_user_id
    row.finalized_at = stamp
    row.updated_at = stamp
    shipment.quoted_amount = row.quoted_amount
    shipment.amicor_margin = row.estimated_amicor_margin
    shipment.updated_at = stamp
    _add_event(
        db,
        shipment,
        event_type="quote_finalized",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"amount={row.quoted_amount} previous_status={shipment.status}",
        quote_id=row.quote_id,
    )
    db.commit()
    db.refresh(row)
    return row


def get_quote_or_404(db: Session, shipment_id: str, *, organization_id: str) -> NovaFreightQuote:
    get_shipment(db, shipment_id, organization_id=organization_id)
    row = _get_quote(db, shipment_id, organization_id)
    if row is None:
        raise NovaFreightError("Quote not found", status_code=404)
    return row


def customer_quote_view(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
) -> NovaFreightCustomerQuoteOut:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    quote = _get_quote(db, shipment_id, organization_id)
    invoice = _get_active_invoice(db, shipment_id, organization_id)
    payment_status = "unpaid"
    if invoice is not None:
        if invoice.invoice_status == "paid":
            payment_status = "paid"
        elif invoice.invoice_status in {"payment_pending", "failed", "ready"}:
            payment_status = invoice.invoice_status
    return NovaFreightCustomerQuoteOut(
        shipment_id=shipment.shipment_id,
        pickup_address=shipment.pickup_address,
        pickup_city=shipment.pickup_city,
        pickup_state=shipment.pickup_state,
        pickup_zip=shipment.pickup_zip,
        delivery_address=shipment.delivery_address,
        delivery_city=shipment.delivery_city,
        delivery_state=shipment.delivery_state,
        delivery_zip=shipment.delivery_zip,
        commodity=shipment.commodity,
        weight=shipment.weight,
        equipment_type=shipment.equipment_type,
        quoted_amount=quote.quoted_amount if quote else None,
        currency=quote.currency if quote else shipment.currency,
        pricing_status=quote.pricing_status if quote else "unquoted",
        quoted_at=quote.quoted_at if quote else None,
        customer_notes=quote.customer_notes if quote else None,
        payment_status=payment_status,
        invoice_status=invoice.invoice_status if invoice else None,
        invoice_id=invoice.invoice_id if invoice else None,
        total_amount=invoice.total_amount if invoice else (quote.quoted_amount if quote else None),
    )


def create_invoice(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightInvoice:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    if shipment.status != "completed":
        raise NovaFreightError("Customer invoices are created after shipment completion", status_code=409)
    quote = _get_quote(db, shipment_id, organization_id)
    if quote is None or quote.pricing_status != "finalized":
        raise NovaFreightError("A finalized quote is required before invoicing", status_code=409)
    existing = _get_active_invoice(db, shipment_id, organization_id)
    if existing is not None:
        return existing
    surcharge = money(
        quote.equipment_surcharge + quote.special_handling_surcharge + quote.fuel_surcharge + quote.other_surcharge
    )
    subtotal = money(quote.base_rate + quote.mileage_amount + quote.time_amount + surcharge)
    stamp = now()
    voided_count = (
        db.query(NovaFreightInvoice)
        .filter(
            NovaFreightInvoice.shipment_id == shipment.shipment_id,
            NovaFreightInvoice.organization_id == organization_id,
            NovaFreightInvoice.invoice_status == "void",
        )
        .count()
    )
    row = NovaFreightInvoice(
        invoice_id=_new_invoice_id(),
        shipment_id=shipment.shipment_id,
        organization_id=organization_id,
        quote_id=quote.quote_id,
        customer_user_id=shipment.shipper_user_id,
        amount_subtotal=subtotal,
        surcharge_total=surcharge,
        discount_total=quote.discount_amount,
        tax_total=quote.tax_amount,
        total_amount=quote.quoted_amount,
        total_amount_minor=to_minor_units(quote.quoted_amount),
        currency=quote.currency,
        invoice_status="draft",
        idempotency_key=f"nova-freight-invoice:{organization_id}:{shipment.shipment_id}:{voided_count}",
        created_at=stamp,
        updated_at=stamp,
    )
    try:
        db.add(row)
        db.flush()
        _add_event(
            db,
            shipment,
            event_type="invoice_created",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            notes=f"invoice={row.invoice_id} amount={row.total_amount}",
            quote_id=quote.quote_id,
            invoice_id=row.invoice_id,
        )
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError:
        db.rollback()
        existing_after = _get_active_invoice(db, shipment_id, organization_id)
        if existing_after is not None:
            return existing_after
        raise NovaFreightError("Invoice already exists", status_code=409)


def finalize_invoice(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightInvoice:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    row = _get_active_invoice(db, shipment_id, organization_id)
    if row is None:
        row = create_invoice(
            db,
            shipment_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
        )
        shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    if row.invoice_status in {"ready", "payment_pending", "paid"}:
        return row
    if row.invoice_status == "void":
        raise NovaFreightError("Void invoices cannot be finalized", status_code=409)
    quote = _get_quote(db, shipment_id, organization_id)
    if quote is None or money(row.total_amount) != money(quote.quoted_amount):
        raise NovaFreightError("Invoice total must match the finalized quote", status_code=409)
    stamp = now()
    row.invoice_status = "ready"
    row.finalized_at = stamp
    row.updated_at = stamp
    _add_event(
        db,
        shipment,
        event_type="invoice_finalized",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"invoice={row.invoice_id} amount={row.total_amount}",
        invoice_id=row.invoice_id,
        quote_id=row.quote_id,
    )
    db.commit()
    db.refresh(row)
    return row


def get_invoice_or_404(db: Session, shipment_id: str, *, organization_id: str) -> NovaFreightInvoice:
    get_shipment(db, shipment_id, organization_id=organization_id)
    row = _get_active_invoice(db, shipment_id, organization_id)
    if row is None:
        raise NovaFreightError("Invoice not found", status_code=404)
    return row


def void_invoice(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
) -> NovaFreightInvoice:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    row = get_invoice_or_404(db, shipment_id, organization_id=organization_id)
    if row.invoice_status == "paid":
        raise NovaFreightError("Paid invoices cannot be voided", status_code=409)
    row.invoice_status = "void"
    row.updated_at = now()
    _add_event(
        db,
        shipment,
        event_type="invoice_voided",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"invoice={row.invoice_id}",
        invoice_id=row.invoice_id,
    )
    db.commit()
    db.refresh(row)
    return row


def start_customer_payment(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
    requested_amount: Decimal | None,
) -> dict:
    shipment = get_shipment(db, shipment_id, organization_id=organization_id)
    invoice = get_invoice_or_404(db, shipment_id, organization_id=organization_id)
    if invoice.invoice_status == "void":
        raise NovaFreightError("Void invoices cannot be charged", status_code=409)
    if invoice.invoice_status == "draft":
        raise NovaFreightError("Finalize the invoice before charging the customer", status_code=409)
    if invoice.invoice_status == "paid":
        return _payment_payload(invoice, reused=True)
    if requested_amount is not None and money(requested_amount) != money(invoice.total_amount):
        raise NovaFreightError("Client-provided amount does not match the finalized invoice", status_code=409)
    if money(invoice.total_amount) <= money(0):
        raise NovaFreightError("Invoice amount must be greater than zero", status_code=409)
    if invoice.stripe_payment_intent_id and invoice.invoice_status == "payment_pending":
        return _payment_payload(invoice, reused=True)
    try:
        client = get_nova_freight_stripe_client()
        created = client.create_payment_intent(
            amount_minor=int(invoice.total_amount_minor),
            currency=invoice.currency,
            metadata={
                "service_type": "NOVA_FREIGHT",
                "shipment_id": shipment.shipment_id,
                "invoice_id": invoice.invoice_id,
                "organization_id": organization_id,
            },
            idempotency_key=f"nova-freight-pay:{invoice.invoice_id}:{invoice.total_amount_minor}",
        )
    except ValueError as exc:
        raise NovaFreightError(str(exc), status_code=503) from exc
    except Exception as exc:
        raise NovaFreightError(f"Stripe TEST payment could not be created: {sanitize_stripe_error(exc)}", status_code=503) from exc
    intent_id = str(created.get("id") or "")
    if not intent_id:
        raise NovaFreightError("Stripe did not return a TEST PaymentIntent", status_code=503)
    invoice.stripe_payment_intent_id = intent_id
    invoice.invoice_status = "payment_pending"
    invoice.failure_reason = None
    invoice.updated_at = now()
    _add_event(
        db,
        shipment,
        event_type="payment_started",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        notes=f"invoice={invoice.invoice_id} payment_ref={intent_id}",
        invoice_id=invoice.invoice_id,
    )
    db.commit()
    db.refresh(invoice)
    return _payment_payload(invoice, client_secret=created.get("client_secret"), reused=False)


def confirm_customer_payment(
    db: Session,
    shipment_id: str,
    *,
    organization_id: str,
    actor_user_id: str | None,
    actor_role: str | None,
    simulate: str | None = None,
) -> NovaFreightInvoice:
    invoice = get_invoice_or_404(db, shipment_id, organization_id=organization_id)
    if not invoice.stripe_payment_intent_id:
        raise NovaFreightError("No Stripe TEST payment has been started", status_code=409)
    client = get_nova_freight_stripe_client()
    override = get_nova_freight_stripe_override()
    if simulate and override is not None and hasattr(override, simulate):
        getattr(override, simulate)(invoice.stripe_payment_intent_id)
    intent = client.retrieve_payment_intent(invoice.stripe_payment_intent_id)
    apply_payment_intent_result(
        db,
        intent,
        event_id=f"confirm:{invoice.invoice_id}:{intent.get('status')}",
        event_type="payment_intent.confirm",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
    )
    return get_invoice_or_404(db, shipment_id, organization_id=organization_id)


def apply_payment_intent_result(
    db: Session,
    intent: dict,
    *,
    event_id: str,
    event_type: str,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
) -> dict:
    existing_event = (
        db.query(NovaFreightPaymentEvent)
        .filter(NovaFreightPaymentEvent.stripe_event_id == event_id)
        .first()
    )
    if existing_event is not None:
        return {"duplicate": True, "result": existing_event.processing_result, "invoice_id": existing_event.invoice_id}
    metadata = intent.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    invoice_id = str(metadata.get("invoice_id") or "")
    shipment_id = str(metadata.get("shipment_id") or "")
    organization_id = str(metadata.get("organization_id") or "")
    intent_id = str(intent.get("id") or "")
    invoice = None
    if invoice_id:
        invoice = db.query(NovaFreightInvoice).filter(NovaFreightInvoice.invoice_id == invoice_id).first()
    if invoice is None and intent_id:
        invoice = (
            db.query(NovaFreightInvoice)
            .filter(NovaFreightInvoice.stripe_payment_intent_id == intent_id)
            .first()
        )
    if invoice is None:
        db.add(
            NovaFreightPaymentEvent(
                stripe_event_id=event_id,
                stripe_payment_intent_id=intent_id or None,
                event_type=event_type,
                processing_result="unrelated",
            )
        )
        db.commit()
        return {"duplicate": False, "result": "unrelated"}
    if organization_id and invoice.organization_id != organization_id:
        raise NovaFreightError("Payment organization does not match invoice", status_code=403)
    amount_minor = int(intent.get("amount_received") or intent.get("amount") or invoice.total_amount_minor)
    if amount_minor and amount_minor != int(invoice.total_amount_minor):
        raise NovaFreightError("Stripe amount does not match the finalized invoice", status_code=409)
    shipment = get_shipment(db, invoice.shipment_id, organization_id=invoice.organization_id)
    status = str(intent.get("status") or "")
    if status == "succeeded":
        if invoice.invoice_status != "paid":
            invoice.invoice_status = "paid"
            invoice.paid_at = now()
            invoice.failure_reason = None
            invoice.updated_at = now()
            _add_event(
                db,
                shipment,
                event_type="payment_succeeded",
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                notes=f"invoice={invoice.invoice_id} payment_ref={intent_id} amount={invoice.total_amount}",
                invoice_id=invoice.invoice_id,
            )
        result = "paid"
    else:
        error = intent.get("last_payment_error") or {}
        reason = str(error.get("message") or error.get("code") or "payment_failed")[:512]
        if invoice.invoice_status != "paid":
            invoice.invoice_status = "failed"
            invoice.failure_reason = reason
            invoice.updated_at = now()
            _add_event(
                db,
                shipment,
                event_type="payment_failed",
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                notes=f"invoice={invoice.invoice_id} payment_ref={intent_id}",
                invoice_id=invoice.invoice_id,
            )
        result = "failed"
    db.add(
        NovaFreightPaymentEvent(
            stripe_event_id=event_id,
            stripe_payment_intent_id=intent_id or None,
            invoice_id=invoice.invoice_id,
            shipment_id=invoice.shipment_id,
            organization_id=invoice.organization_id,
            event_type=event_type,
            processing_result=result,
            amount_minor=amount_minor,
        )
    )
    db.commit()
    return {"duplicate": False, "result": result, "invoice_id": invoice.invoice_id, "shipment_id": invoice.shipment_id}


def process_nova_freight_webhook(db: Session, event: dict) -> dict:
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if not event_id:
        raise NovaFreightError("Webhook event id is required", status_code=400)
    data = event.get("data") or {}
    intent = data.get("object") if isinstance(data, dict) else {}
    if not isinstance(intent, dict):
        intent = {}
    metadata = intent.get("metadata") or {}
    if not isinstance(metadata, dict) or str(metadata.get("service_type") or "") != "NOVA_FREIGHT":
        existing = db.query(NovaFreightPaymentEvent).filter(NovaFreightPaymentEvent.stripe_event_id == event_id).first()
        if existing:
            return {"duplicate": True, "result": "unrelated"}
        db.add(
            NovaFreightPaymentEvent(
                stripe_event_id=event_id,
                stripe_payment_intent_id=str(intent.get("id") or "") or None,
                event_type=event_type or "unknown",
                processing_result="unrelated",
            )
        )
        db.commit()
        return {"duplicate": False, "result": "unrelated"}
    return apply_payment_intent_result(db, intent, event_id=event_id, event_type=event_type)


def verify_nova_freight_webhook(payload: bytes, signature: str | None) -> dict:
    import os

    secret = (os.getenv("STRIPE_NOVA_FREIGHT_WEBHOOK_SECRET") or os.getenv("STRIPE_PAYMENT_WEBHOOK_SECRET") or "").strip()
    if get_nova_freight_stripe_override() is not None and not signature:
        parsed = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload))
        if not isinstance(parsed, dict):
            raise NovaFreightError("Invalid webhook payload", status_code=400)
        return parsed
    if not secret:
        raise NovaFreightError("Nova freight webhook secret is not configured", status_code=503)
    if not signature:
        raise NovaFreightError("Missing Stripe-Signature header", status_code=400)
    import stripe

    stripe.Webhook.construct_event(payload, signature, secret)
    parsed = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload))
    if not isinstance(parsed, dict):
        raise NovaFreightError("Invalid webhook payload", status_code=400)
    return parsed


def _payment_payload(invoice: NovaFreightInvoice, *, client_secret: str | None = None, reused: bool) -> dict:
    return {
        "invoice_id": invoice.invoice_id,
        "shipment_id": invoice.shipment_id,
        "invoice_status": invoice.invoice_status,
        "total_amount": invoice.total_amount,
        "currency": invoice.currency,
        "stripe_payment_intent_id": invoice.stripe_payment_intent_id,
        "client_secret": client_secret,
        "publishable_key": stripe_publishable_key() or None,
        "sandbox": True,
        "reused": reused,
    }


def quote_out(row: NovaFreightQuote) -> NovaFreightQuoteOut:
    return NovaFreightQuoteOut.model_validate(row)


def invoice_out(row: NovaFreightInvoice) -> NovaFreightInvoiceOut:
    return NovaFreightInvoiceOut.model_validate(row)


def payout_record_count(db: Session, shipment_id: str) -> int:
    return 0
