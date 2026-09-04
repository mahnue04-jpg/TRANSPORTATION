"""Public customer-payment webhook routes plus rider sandbox checkout.

Kept separate from POST /api/platform-ops/driver-onboarding/stripe/webhook
so Connect account.updated handling stays unchanged.

Does not create or alter database tables. Production schema is Alembic-only.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.db.session import get_db
from app.modules.payments.rider_checkout import (
    create_rider_checkout,
    quote_rider_fare,
    rider_payment_status,
    stripe_publishable_key,
)
from app.modules.payments.stripe_payments import (
    StripePaymentWebhookNotConfigured,
    process_verified_payment_event,
    verify_and_parse_payment_webhook,
)

logger = logging.getLogger("amicor.payments.routes")

router = APIRouter(prefix="/api/payments", tags=["payments"])

_require_rider_payment_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_RIDER,
)


class RiderFareQuoteRequest(BaseModel):
    pickup_address: str
    dropoff_address: str
    ride_type: str = "healthcare"
    pickup_latitude: float | None = None
    pickup_longitude: float | None = None
    dropoff_latitude: float | None = None
    dropoff_longitude: float | None = None


class RiderCheckoutRequest(BaseModel):
    rider_name: str
    rider_phone: str
    pickup_address: str
    dropoff_address: str
    ride_type: str = "healthcare"
    notes: str | None = None
    trip_type: str = "one_way"
    pickup_latitude: float | None = None
    pickup_longitude: float | None = None
    dropoff_latitude: float | None = None
    dropoff_longitude: float | None = None
    scheduled_time: Any | None = None
    service_date: Any | None = None
    pickup_time: Any | None = None
    arrival_time: Any | None = None
    return_pickup_type: str | None = None
    return_pickup_time: Any | None = None
    recurrence: str = "none"
    recurrence_weekdays: list[str] | None = None
    recurrence_start_date: Any | None = None
    recurrence_end_date: Any | None = None
    return_pickup_address: str | None = None
    return_dropoff_address: str | None = None
    same_driver_preference: bool = False
    client_timezone: str | None = None
    client_request_key: str | None = Field(default=None)


@router.post("/stripe/webhook")
async def stripe_customer_payment_webhook(
    request: Request,
    db: Session = Depends(get_db),
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
) -> dict[str, Any]:
    payload = await request.body()
    try:
        event = verify_and_parse_payment_webhook(payload, stripe_signature)
    except StripePaymentWebhookNotConfigured as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe webhook.") from exc
    except Exception as exc:
        import stripe

        signature_error = getattr(stripe, "SignatureVerificationError", None)
        if signature_error is not None and isinstance(exc, signature_error):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe signature.") from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Stripe webhook.") from exc
    result = process_verified_payment_event(db, event)
    return {"received": True, **result}


@router.get("/stripe/publishable-key")
def get_stripe_publishable_key(
    _: None = Depends(_require_rider_payment_access),
) -> dict[str, Any]:
    key = stripe_publishable_key()
    return {
        "publishable_key": key or None,
        "configured": bool(key),
        "sandbox": True,
    }


@router.post("/rider/fare-quote")
def create_rider_fare_quote(
    payload: RiderFareQuoteRequest,
    user: UserContext = Depends(get_current_user_context),
    _: None = Depends(_require_rider_payment_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ = user
    try:
        return quote_rider_fare(
            db,
            pickup_address=payload.pickup_address,
            dropoff_address=payload.dropoff_address,
            ride_type=payload.ride_type,
            pickup_latitude=payload.pickup_latitude,
            pickup_longitude=payload.pickup_longitude,
            dropoff_latitude=payload.dropoff_latitude,
            dropoff_longitude=payload.dropoff_longitude,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/rider/checkout")
def start_rider_checkout(
    payload: RiderCheckoutRequest,
    user: UserContext = Depends(get_current_user_context),
    _: None = Depends(_require_rider_payment_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    extra = {
        "service_date": payload.service_date,
        "pickup_time": payload.pickup_time,
        "arrival_time": payload.arrival_time,
        "return_pickup_type": payload.return_pickup_type,
        "return_pickup_time": payload.return_pickup_time,
        "recurrence": payload.recurrence,
        "recurrence_weekdays": payload.recurrence_weekdays,
        "recurrence_start_date": payload.recurrence_start_date,
        "recurrence_end_date": payload.recurrence_end_date,
        "return_pickup_address": payload.return_pickup_address,
        "return_dropoff_address": payload.return_dropoff_address,
        "same_driver_preference": payload.same_driver_preference,
        "client_timezone": payload.client_timezone,
        "recurring": str(payload.recurrence or "none").lower() == "weekly",
    }
    try:
        return create_rider_checkout(
            db,
            organization_id=str(user.organization_id),
            user_id=user.user_id,
            rider_name=payload.rider_name,
            rider_phone=payload.rider_phone,
            pickup_address=payload.pickup_address,
            dropoff_address=payload.dropoff_address,
            ride_type=payload.ride_type,
            notes=payload.notes,
            scheduled_time=payload.scheduled_time or payload.arrival_time or payload.pickup_time,
            trip_type=payload.trip_type,
            pickup_latitude=payload.pickup_latitude,
            pickup_longitude=payload.pickup_longitude,
            dropoff_latitude=payload.dropoff_latitude,
            dropoff_longitude=payload.dropoff_longitude,
            extra_request_kwargs=extra,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rider checkout is temporarily unavailable.",
        ) from exc


@router.get("/rider/payment-status/{request_id}")
def get_rider_payment_status(
    request_id: str,
    user: UserContext = Depends(get_current_user_context),
    _: None = Depends(_require_rider_payment_access),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return rider_payment_status(
            db,
            request_id=request_id,
            organization_id=str(user.organization_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
