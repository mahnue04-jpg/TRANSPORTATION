"""Customer PaymentIntent webhook processing for Amicor Ride and Deliver.

This module is separate from Stripe Connect onboarding (account.updated).
It never creates connected accounts and never starts a live driver payout.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.payments.models import (
    PAYMENT_FAILED,
    PAYMENT_PENDING,
    PAYMENT_SUCCEEDED,
    PAYOUT_NOT_STARTED,
    SERVICE_DELIVERY,
    SERVICE_RIDE,
    SUPPORTED_SERVICE_TYPES,
    AmicorCustomerPayment,
    AmicorCustomerPaymentEvent,
)

logger = logging.getLogger("amicor.payments.stripe")

EVENT_PAYMENT_SUCCEEDED = "payment_intent.succeeded"
EVENT_PAYMENT_FAILED = "payment_intent.payment_failed"
HANDLED_EVENT_TYPES = frozenset({EVENT_PAYMENT_SUCCEEDED, EVENT_PAYMENT_FAILED})

RESULT_PAID = "paid"
RESULT_PAYMENT_FAILED = "payment_failed"
RESULT_UNRELATED = "unrelated"
RESULT_UNKNOWN_SERVICE_TYPE = "unknown_service_type"
RESULT_MISSING_INTERNAL_SERVICE_ID = "missing_internal_service_id"
RESULT_MISSING_PAYMENT_INTENT = "missing_payment_intent"

# Zero-decimal currencies — Stripe amount is already major units.
_ZERO_DECIMAL_CURRENCIES = frozenset(
    {"bif", "clp", "djf", "gnf", "jpy", "kmf", "krw", "mga", "pyg", "rwf", "ugx", "vnd", "vuv", "xaf", "xof", "xpf"}
)
_PAN_LIKE = re.compile(r"\d{13,19}")


class StripePaymentWebhookNotConfigured(RuntimeError):
    """Raised when the customer-payment webhook secret is missing."""


def payment_webhook_secret() -> str:
    """Secret for the Ride/Deliver destination — not the Connect webhook secret."""
    return os.getenv("STRIPE_PAYMENT_WEBHOOK_SECRET", "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if isinstance(converted, dict):
            return converted
    return {}


def _clip_text(value: Any, *, max_len: int) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:max_len]


def _safe_failure_text(value: Any, *, max_len: int) -> str | None:
    text = _clip_text(value, max_len=max_len)
    if not text:
        return None
    return _PAN_LIKE.sub("[redacted]", text)


@dataclass(frozen=True)
class PaymentIntentMetadata:
    service_type: str | None
    service_type_valid: bool
    internal_service_id: str | None
    ride_id: str | None
    delivery_id: str | None
    customer_id: str | None
    driver_id: str | None
    organization_id: str | None
    pricing_version: str | None


def parse_payment_intent_metadata(raw: Any) -> PaymentIntentMetadata:
    metadata = raw if isinstance(raw, dict) else {}
    raw_service = str(metadata.get("service_type") or "").strip().upper()
    service_type = raw_service or None
    service_type_valid = service_type in SUPPORTED_SERVICE_TYPES

    ride_id = _clip_text(metadata.get("ride_id"), max_len=64)
    delivery_id = _clip_text(metadata.get("delivery_id"), max_len=64)
    internal = _clip_text(metadata.get("internal_service_id"), max_len=64)
    if internal is None:
        if service_type == SERVICE_RIDE:
            internal = ride_id
        elif service_type == SERVICE_DELIVERY:
            internal = delivery_id
        else:
            internal = ride_id or delivery_id

    if service_type == SERVICE_RIDE and ride_id is None:
        ride_id = internal
    if service_type == SERVICE_DELIVERY and delivery_id is None:
        delivery_id = internal

    return PaymentIntentMetadata(
        service_type=service_type,
        service_type_valid=service_type_valid,
        internal_service_id=internal,
        ride_id=ride_id,
        delivery_id=delivery_id,
        customer_id=_clip_text(metadata.get("customer_id"), max_len=64),
        driver_id=_clip_text(metadata.get("driver_id"), max_len=64),
        organization_id=_clip_text(metadata.get("organization_id"), max_len=36),
        pricing_version=_clip_text(metadata.get("pricing_version"), max_len=64),
    )


def amount_major_from_minor(amount_minor: int, currency: str) -> float:
    if currency in _ZERO_DECIMAL_CURRENCIES:
        return float(amount_minor)
    return round(amount_minor / 100.0, 2)


def extract_amount_minor(payment_intent: dict[str, Any], *, succeeded: bool) -> int:
    raw = payment_intent.get("amount_received") if succeeded else payment_intent.get("amount")
    if raw is None:
        raw = payment_intent.get("amount") or 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def _safe_failure_fields(payment_intent: dict[str, Any]) -> tuple[str | None, str | None]:
    error = _as_dict(payment_intent.get("last_payment_error"))
    code = _clip_text(error.get("code") or error.get("decline_code"), max_len=64)
    message = _safe_failure_text(error.get("message"), max_len=200)
    if code and message:
        combined = f"{code}: {message}"[:512]
    else:
        combined = message or code
    return code, combined


def verify_and_parse_payment_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    secret = payment_webhook_secret()
    if not secret:
        raise StripePaymentWebhookNotConfigured("STRIPE_PAYMENT_WEBHOOK_SECRET is not configured.")
    if not signature:
        raise ValueError("Missing Stripe-Signature header.")
    import stripe

    stripe.Webhook.construct_event(payload, signature, secret)
    raw = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Invalid Stripe webhook payload.")
    return parsed


def _log_result(
    *,
    event_id: str | None,
    payment_intent_id: str | None,
    service_type: str | None,
    internal_service_id: str | None,
    amount: float | None,
    currency: str | None,
    result: str,
    duplicate: bool = False,
) -> None:
    logger.info(
        "customer_payment_webhook event_id=%s payment_intent_id=%s service_type=%s "
        "internal_service_id=%s amount=%s currency=%s result=%s duplicate=%s",
        event_id,
        payment_intent_id,
        service_type,
        internal_service_id,
        amount,
        currency,
        result,
        duplicate,
    )


def _event_response(
    event_row: AmicorCustomerPaymentEvent,
    payment: AmicorCustomerPayment | None,
    *,
    duplicate: bool,
) -> dict[str, Any]:
    amount = None
    if event_row.amount_minor is not None and event_row.currency:
        amount = amount_major_from_minor(event_row.amount_minor, event_row.currency)
    elif payment is not None:
        amount = amount_major_from_minor(int(payment.amount_minor or 0), payment.currency or "usd")
    return {
        "handled": event_row.processing_result in {RESULT_PAID, RESULT_PAYMENT_FAILED},
        "duplicate": duplicate,
        "event_id": event_row.stripe_event_id,
        "event_type": event_row.event_type,
        "payment_intent_id": event_row.stripe_payment_intent_id,
        "service_type": event_row.service_type,
        "internal_service_id": event_row.internal_service_id,
        "amount": amount,
        "currency": event_row.currency or (payment.currency if payment is not None else None),
        "result": event_row.processing_result,
        "payment_status": payment.payment_status if payment is not None else None,
        "payout_status": payment.payout_status if payment is not None else PAYOUT_NOT_STARTED,
        "payment_id": event_row.payment_id,
    }


def _record_event(
    db: Session,
    *,
    event_id: str,
    event_type: str,
    payment_intent_id: str | None,
    service_type: str | None,
    internal_service_id: str | None,
    amount_minor: int | None,
    currency: str | None,
    result: str,
    payment_id: str | None,
) -> AmicorCustomerPaymentEvent:
    row = AmicorCustomerPaymentEvent(
        id=uuid4(),
        stripe_event_id=event_id,
        stripe_payment_intent_id=payment_intent_id,
        event_type=event_type,
        service_type=service_type,
        internal_service_id=internal_service_id,
        amount_minor=amount_minor,
        currency=currency,
        processing_result=result,
        payment_id=payment_id,
        created_at=now(),
    )
    db.add(row)
    return row


def _lookup_existing_event(db: Session, event_id: str) -> AmicorCustomerPaymentEvent | None:
    return (
        db.query(AmicorCustomerPaymentEvent)
        .filter(AmicorCustomerPaymentEvent.stripe_event_id == event_id)
        .first()
    )


def _get_payment_by_intent(db: Session, payment_intent_id: str) -> AmicorCustomerPayment | None:
    return (
        db.query(AmicorCustomerPayment)
        .filter(AmicorCustomerPayment.stripe_payment_intent_id == payment_intent_id)
        .first()
    )


def _maybe_enrich_from_ride(db: Session, payment: AmicorCustomerPayment) -> None:
    if payment.service_type != SERVICE_RIDE or not payment.internal_service_id:
        return
    try:
        from app.modules.health_isf.models import HealthISFRide
    except Exception:
        return
    try:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == payment.internal_service_id).first()
    except Exception:
        logger.info("customer_payment_ride_lookup_skipped payment_id=%s", payment.id)
        return
    if ride is None:
        return
    payment.ride_id = payment.ride_id or ride.id
    payment.organization_id = payment.organization_id or getattr(ride, "organization_id", None)
    payment.driver_id = payment.driver_id or getattr(ride, "driver_id", None)


def _maybe_sync_health_isf_transaction(db: Session, payment: AmicorCustomerPayment) -> None:
    """Update an existing ride payment row if one exists. Never settle or payout."""
    if payment.service_type != SERVICE_RIDE or not payment.internal_service_id:
        return
    try:
        from app.modules.health_isf.models import HealthISFPaymentTransaction
    except Exception:
        return
    try:
        tx = (
            db.query(HealthISFPaymentTransaction)
            .filter(HealthISFPaymentTransaction.gateway_payment_intent_id == payment.stripe_payment_intent_id)
            .first()
        )
        if tx is None:
            tx = (
                db.query(HealthISFPaymentTransaction)
                .filter(HealthISFPaymentTransaction.ride_id == payment.internal_service_id)
                .order_by(HealthISFPaymentTransaction.created_at.desc())
                .first()
            )
        if tx is None:
            return
        tx.gateway = "stripe"
        tx.gateway_payment_intent_id = payment.stripe_payment_intent_id
        tx.currency = payment.currency or tx.currency
        if payment.amount_minor:
            tx.amount_usd = amount_major_from_minor(int(payment.amount_minor), payment.currency or "usd")
        if payment.payment_status == PAYMENT_SUCCEEDED:
            tx.status = "succeeded"
            tx.failure_reason = None
            tx.paid_at = tx.paid_at or payment.paid_at or now()
        elif payment.payment_status == PAYMENT_FAILED:
            tx.status = "failed"
            tx.failure_reason = payment.failure_message
        tx.updated_at = now()
        payment.health_isf_payment_transaction_id = tx.id
    except Exception:
        logger.info(
            "customer_payment_health_isf_sync_skipped payment_id=%s payment_intent_id=%s",
            payment.id,
            payment.stripe_payment_intent_id,
        )


def _upsert_payment(
    db: Session,
    *,
    payment_intent_id: str,
    event_id: str,
    metadata: PaymentIntentMetadata,
    amount_minor: int,
    currency: str,
    succeeded: bool,
    failure_code: str | None,
    failure_message: str | None,
) -> AmicorCustomerPayment:
    payment = _get_payment_by_intent(db, payment_intent_id)
    stamp = now()
    if payment is None:
        payment = AmicorCustomerPayment(
            id=uuid4(),
            service_type=metadata.service_type or "",
            internal_service_id=metadata.internal_service_id or "",
            ride_id=metadata.ride_id,
            delivery_id=metadata.delivery_id,
            customer_id=metadata.customer_id,
            driver_id=metadata.driver_id,
            organization_id=metadata.organization_id,
            pricing_version=metadata.pricing_version,
            stripe_payment_intent_id=payment_intent_id,
            last_stripe_event_id=event_id,
            currency=currency,
            amount_minor=amount_minor,
            driver_earning_minor=None,
            amicor_share_minor=None,
            processing_fee_minor=None,
            refund_amount_minor=0,
            payment_status=PAYMENT_PENDING,
            payout_status=PAYOUT_NOT_STARTED,
            created_at=stamp,
            updated_at=stamp,
        )
        db.add(payment)
    else:
        payment.last_stripe_event_id = event_id
        payment.updated_at = stamp
        if metadata.customer_id:
            payment.customer_id = metadata.customer_id
        if metadata.driver_id:
            payment.driver_id = metadata.driver_id
        if metadata.organization_id:
            payment.organization_id = metadata.organization_id
        if metadata.pricing_version:
            payment.pricing_version = metadata.pricing_version
        if amount_minor:
            payment.amount_minor = amount_minor
        if currency:
            payment.currency = currency

    payment.payout_status = PAYOUT_NOT_STARTED
    if succeeded:
        if payment.payment_status != PAYMENT_SUCCEEDED:
            payment.payment_status = PAYMENT_SUCCEEDED
            payment.paid_at = stamp
        payment.failure_code = None
        payment.failure_message = None
    elif payment.payment_status != PAYMENT_SUCCEEDED:
        payment.payment_status = PAYMENT_FAILED
        payment.failure_code = failure_code
        payment.failure_message = failure_message
        payment.paid_at = None

    _maybe_enrich_from_ride(db, payment)
    _maybe_sync_health_isf_transaction(db, payment)
    return payment


def process_verified_payment_event(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    event_dict = _as_dict(event)
    event_id = _clip_text(event_dict.get("id"), max_len=128) or ""
    event_type = str(event_dict.get("type") or "")
    data = _as_dict(event_dict.get("data"))
    payment_intent = _as_dict(data.get("object"))
    payment_intent_id = _clip_text(payment_intent.get("id"), max_len=128)
    metadata = parse_payment_intent_metadata(payment_intent.get("metadata"))
    currency = str(payment_intent.get("currency") or "usd").strip().lower() or "usd"
    succeeded = event_type == EVENT_PAYMENT_SUCCEEDED
    amount_minor = extract_amount_minor(payment_intent, succeeded=succeeded) if payment_intent else None
    amount_major = (
        amount_major_from_minor(amount_minor, currency) if amount_minor is not None and currency else None
    )

    if event_id:
        existing = _lookup_existing_event(db, event_id)
        if existing is not None:
            payment = (
                _get_payment_by_intent(db, existing.stripe_payment_intent_id)
                if existing.stripe_payment_intent_id
                else None
            )
            if payment is None and existing.payment_id:
                payment = db.query(AmicorCustomerPayment).filter(AmicorCustomerPayment.id == existing.payment_id).first()
            _log_result(
                event_id=event_id,
                payment_intent_id=existing.stripe_payment_intent_id,
                service_type=existing.service_type,
                internal_service_id=existing.internal_service_id,
                amount=amount_major,
                currency=existing.currency,
                result=existing.processing_result,
                duplicate=True,
            )
            return _event_response(existing, payment, duplicate=True)

    if event_type not in HANDLED_EVENT_TYPES:
        row = _record_event(
            db,
            event_id=event_id or f"missing-event-{uuid4()}",
            event_type=event_type or "unknown",
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount_minor=amount_minor,
            currency=currency,
            result=RESULT_UNRELATED,
            payment_id=None,
        )
        db.commit()
        _log_result(
            event_id=row.stripe_event_id,
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount=amount_major,
            currency=currency,
            result=RESULT_UNRELATED,
        )
        return _event_response(row, None, duplicate=False)

    if not payment_intent_id:
        row = _record_event(
            db,
            event_id=event_id or f"missing-event-{uuid4()}",
            event_type=event_type,
            payment_intent_id=None,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount_minor=amount_minor,
            currency=currency,
            result=RESULT_MISSING_PAYMENT_INTENT,
            payment_id=None,
        )
        db.commit()
        _log_result(
            event_id=row.stripe_event_id,
            payment_intent_id=None,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount=amount_major,
            currency=currency,
            result=RESULT_MISSING_PAYMENT_INTENT,
        )
        return _event_response(row, None, duplicate=False)

    if not metadata.service_type_valid:
        row = _record_event(
            db,
            event_id=event_id or f"missing-event-{uuid4()}",
            event_type=event_type,
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount_minor=amount_minor,
            currency=currency,
            result=RESULT_UNKNOWN_SERVICE_TYPE,
            payment_id=None,
        )
        db.commit()
        _log_result(
            event_id=row.stripe_event_id,
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount=amount_major,
            currency=currency,
            result=RESULT_UNKNOWN_SERVICE_TYPE,
        )
        return _event_response(row, None, duplicate=False)

    if not metadata.internal_service_id:
        row = _record_event(
            db,
            event_id=event_id or f"missing-event-{uuid4()}",
            event_type=event_type,
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=None,
            amount_minor=amount_minor,
            currency=currency,
            result=RESULT_MISSING_INTERNAL_SERVICE_ID,
            payment_id=None,
        )
        db.commit()
        _log_result(
            event_id=row.stripe_event_id,
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=None,
            amount=amount_major,
            currency=currency,
            result=RESULT_MISSING_INTERNAL_SERVICE_ID,
        )
        return _event_response(row, None, duplicate=False)

    failure_code, failure_message = (None, None)
    if event_type == EVENT_PAYMENT_FAILED:
        failure_code, failure_message = _safe_failure_fields(payment_intent)

    try:
        payment = _upsert_payment(
            db,
            payment_intent_id=payment_intent_id,
            event_id=event_id,
            metadata=metadata,
            amount_minor=amount_minor or 0,
            currency=currency,
            succeeded=succeeded,
            failure_code=failure_code,
            failure_message=failure_message,
        )
        result = RESULT_PAID if succeeded else RESULT_PAYMENT_FAILED
        row = _record_event(
            db,
            event_id=event_id or f"missing-event-{uuid4()}",
            event_type=event_type,
            payment_intent_id=payment_intent_id,
            service_type=metadata.service_type,
            internal_service_id=metadata.internal_service_id,
            amount_minor=amount_minor,
            currency=currency,
            result=result,
            payment_id=payment.id,
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _lookup_existing_event(db, event_id) if event_id else None
        if existing is not None:
            payment = (
                _get_payment_by_intent(db, existing.stripe_payment_intent_id)
                if existing.stripe_payment_intent_id
                else None
            )
            _log_result(
                event_id=existing.stripe_event_id,
                payment_intent_id=existing.stripe_payment_intent_id,
                service_type=existing.service_type,
                internal_service_id=existing.internal_service_id,
                amount=amount_major,
                currency=existing.currency,
                result=existing.processing_result,
                duplicate=True,
            )
            return _event_response(existing, payment, duplicate=True)
        raise

    _log_result(
        event_id=row.stripe_event_id,
        payment_intent_id=payment_intent_id,
        service_type=metadata.service_type,
        internal_service_id=metadata.internal_service_id,
        amount=amount_major,
        currency=currency,
        result=result,
    )
    try:
        from app.modules.payments.rider_checkout import release_ride_after_payment

        release_ride_after_payment(db, payment=payment)
    except Exception:
        logger.exception(
            "customer_payment_dispatch_release_failed payment_intent_id=%s",
            payment_intent_id,
        )
    return _event_response(row, payment, duplicate=False)
