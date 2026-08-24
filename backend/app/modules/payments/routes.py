"""Public customer-payment webhook routes.

Kept separate from POST /api/platform-ops/driver-onboarding/stripe/webhook
so Connect account.updated handling stays unchanged.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.payments.models import ensure_payments_schema
from app.modules.payments.stripe_payments import (
    StripePaymentWebhookNotConfigured,
    process_verified_payment_event,
    verify_and_parse_payment_webhook,
)

logger = logging.getLogger("amicor.payments.routes")

router = APIRouter(prefix="/api/payments", tags=["payments"])

try:
    ensure_payments_schema()
except Exception:
    pass


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
