"""Nova V2 payments readiness APIs. Read-only. No Stripe, payout, or webhook writes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.auth import (
    UserContext,
    _bearer,
    _jwt_verify,
    extract_access_token,
    get_current_user,
    resolve_session_role,
)
from app.core.nova.payments import service
from app.core.nova.payments.schemas import NovaPaymentsReadinessOut
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/payments",
    tags=["nova-payments-readiness"],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    if requested and str(requested) != str(user.organization_id or ""):
        raise HTTPException(status_code=403, detail="Cross-tenant Nova access denied")
    if user.organization_id:
        return str(user.organization_id)
    raise HTTPException(status_code=400, detail="Organization scope is required for payments readiness.")


def require_readiness_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
    x_applicant_token: str | None = Header(default=None, alias="X-Applicant-Token"),
) -> UserContext:
    token = extract_access_token(creds, request)
    if (x_applicant_token or "").strip() and not token:
        raise HTTPException(status_code=403, detail="Applicant tokens cannot access payments readiness.")
    user = get_current_user(request, creds, db)
    payload = _jwt_verify(token) if token else {}
    context = UserContext(
        user_id=user.id,
        email=user.email,
        role=resolve_session_role(user, payload),
        organization_name=getattr(user, "organization_name", None),
        organization_id=getattr(user, "organization_id", None),
    )
    if (x_applicant_token or "").strip():
        raise HTTPException(status_code=403, detail="Applicant tokens cannot access payments readiness.")
    return context


@router.get("/readiness", response_model=NovaPaymentsReadinessOut)
def payments_readiness(
    organization_id: str | None = None,
    user: UserContext = Depends(require_readiness_user),
    db: Session = Depends(get_db),
):
    try:
        return service.readiness(
            db,
            organization_id=_resolve_org(user, organization_id),
            user=user,
        )
    except service.NovaPaymentsReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.get("/readiness/verify", response_model=NovaPaymentsReadinessOut)
def payments_readiness_test_verify(
    organization_id: str | None = None,
    user: UserContext = Depends(require_readiness_user),
    db: Session = Depends(get_db),
):
    try:
        return service.readiness_with_test_verification(
            db,
            organization_id=_resolve_org(user, organization_id),
            user=user,
        )
    except service.NovaPaymentsReadinessError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/pay")
def refuse_pay(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Payments are not created here.")


@router.post("/payout")
def refuse_payout(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Payouts are not created here.")


@router.post("/activate")
def refuse_activate(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Drivers are not activated here.")


@router.post("/onboard")
def refuse_onboard(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Onboarding links are not created here.")


@router.post("/webhook")
def refuse_webhook(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Webhooks are not registered here.")


@router.post("/connect")
def refuse_connect(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Connect accounts are not created here.")


@router.post("/refund")
def refuse_refund(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Refunds are not created here.")


@router.post("/live")
def refuse_live(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. LIVE Stripe is not activated here.")


@router.post("/key")
def refuse_key(user: UserContext = Depends(require_readiness_user)):
    raise HTTPException(status_code=403, detail="Payments readiness is read-only. Keys are not rotated here.")
