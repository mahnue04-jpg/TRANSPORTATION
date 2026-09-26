"""Public AMICOR Nova founding-customer signup and dedicated SaaS webhook."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import (
    UserContext,
    _RATE_LIMIT_AUTH,
    check_rate_limit,
    get_current_user_context,
)
from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
from app.core.nova.signup.service import (
    SignupError,
    activate_free_signup,
    create_signup,
    customer_access,
    offer_payload,
    process_webhook,
    signup_status,
    start_checkout,
    verify_webhook,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/nova/signup", tags=["nova-signup"])


class NovaSignupRequest(BaseModel):
    business_name: str = Field(min_length=3, max_length=128)
    contact_name: str = Field(min_length=2, max_length=128)
    email: str
    phone: str = Field(min_length=7, max_length=40)
    industry: str = Field(min_length=2, max_length=128)
    password: str
    terms_accepted: bool


class NovaCheckoutRequest(BaseModel):
    signup_id: str


def _raise(exc: Exception) -> None:
    if isinstance(exc, SignupError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/offer")
def get_nova_signup_offer(db: Session = Depends(get_db)):
    ensure_nova_signup_schema()
    return offer_payload(db)


@router.post("")
@router.post("/")
def post_nova_signup(req: NovaSignupRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"nova-signup:{ip}", limit=_RATE_LIMIT_AUTH)
    try:
        row = create_signup(
            db,
            business_name=req.business_name,
            contact_name=req.contact_name,
            email=req.email,
            phone=req.phone,
            industry=req.industry,
            password=req.password,
            terms_accepted=req.terms_accepted,
        )
        started = start_checkout(db, signup_id=row.id)
    except Exception as exc:
        _raise(exc)
        raise
    if "password" in str(started).lower() and req.password in str(started):
        raise HTTPException(status_code=500, detail="Signup response leaked credentials")
    return started


@router.post("/free")
def post_nova_free_signup(req: NovaSignupRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"nova-free-signup:{ip}", limit=_RATE_LIMIT_AUTH)
    try:
        row = create_signup(
            db,
            business_name=req.business_name,
            contact_name=req.contact_name,
            email=req.email,
            phone=req.phone,
            industry=req.industry,
            password=req.password,
            terms_accepted=req.terms_accepted,
        )
        result = activate_free_signup(db, signup_id=row.id)
    except Exception as exc:
        _raise(exc)
        raise
    if "password" in str(result).lower() and req.password in str(result):
        raise HTTPException(status_code=500, detail="Signup response leaked credentials")
    return result


@router.post("/checkout")
def post_nova_checkout(req: NovaCheckoutRequest, request: Request, db: Session = Depends(get_db)):
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "anon")
    check_rate_limit(f"nova-signup-checkout:{ip}", limit=_RATE_LIMIT_AUTH)
    try:
        return start_checkout(db, signup_id=req.signup_id)
    except Exception as exc:
        _raise(exc)
        raise


@router.post("/me/upgrade")
def post_nova_free_upgrade(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_nova_signup_schema()
    from app.core.nova.signup.models import NovaCustomerTenant
    tenant = (
        db.query(NovaCustomerTenant)
        .filter(NovaCustomerTenant.organization_id == str(user.organization_id or ""))
        .first()
    )
    if tenant is None:
        raise HTTPException(status_code=404, detail="Nova customer account not found")
    try:
        return start_checkout(db, signup_id=tenant.signup_id)
    except Exception as exc:
        _raise(exc)
        raise


@router.get("/me/access")
def get_nova_customer_access(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return customer_access(db, organization_id=user.organization_id, user_id=user.user_id)


@router.get("/{signup_id}")
def get_nova_signup_status(signup_id: str, db: Session = Depends(get_db)):
    try:
        body = signup_status(db, signup_id)
    except Exception as exc:
        _raise(exc)
        raise
    return body


@router.post("/stripe/webhook")
async def nova_saas_stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    db: Session = Depends(get_db),
):
    payload = await request.body()
    try:
        event = verify_webhook(payload, stripe_signature)
        result = process_webhook(db, event)
    except SignupError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return {"ok": True, **result}
