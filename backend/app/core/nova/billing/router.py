"""Nova tenant-scoped Stripe Checkout, Billing Portal, webhook, and subscription status."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.billing.schema_ensure import ensure_nova_billing_schema
from app.core.nova.billing.service import (
    BillingError,
    process_webhook,
    start_checkout,
    start_portal,
    subscription_status,
    verify_webhook,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/nova/billing", tags=["nova-billing"])


class CheckoutRequest(BaseModel):
    plan_key: str = Field(min_length=3, max_length=32)
    tenant_id: str | None = None


class PortalRequest(BaseModel):
    tenant_id: str | None = None


def _raise(exc: Exception) -> None:
    if isinstance(exc, BillingError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.post("/checkout")
def post_nova_billing_checkout(
    req: CheckoutRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_nova_billing_schema()
    try:
        return start_checkout(db, user=user, plan_key=req.plan_key, tenant_id=req.tenant_id)
    except Exception as exc:
        _raise(exc)
        raise


@router.post("/portal")
def post_nova_billing_portal(
    req: PortalRequest | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_nova_billing_schema()
    body = req or PortalRequest()
    try:
        return start_portal(db, user=user, tenant_id=body.tenant_id)
    except Exception as exc:
        _raise(exc)
        raise


@router.get("/subscription")
def get_nova_billing_subscription(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_nova_billing_schema()
    try:
        return subscription_status(db, user=user)
    except Exception as exc:
        _raise(exc)
        raise


@router.post("/webhook")
async def nova_billing_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    try:
        event = verify_webhook(payload, stripe_signature)
        result = process_webhook(db, event)
    except BillingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True, **result}
