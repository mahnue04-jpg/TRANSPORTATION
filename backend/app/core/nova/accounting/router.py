"""Nova V2 accounting APIs. Read-only. No payment, payout, or ledger writes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.accounting import service
from app.core.nova.accounting.schemas import NovaAccountingSummaryOut
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/accounting",
    tags=["nova-accounting"],
    dependencies=[Depends(require_nova_access)],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


@router.get("/summary", response_model=NovaAccountingSummaryOut)
def accounting_summary(
    organization_id: str | None = None,
    window: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.summary(
            db,
            organization_id=_resolve_org(user, organization_id),
            user=user,
            window=window,
        )
    except service.NovaAccountingError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc


@router.post("/pay")
def refuse_pay(user: UserContext = Depends(get_current_user_context)):
    raise HTTPException(status_code=403, detail="Accounting is read-only. Payments are not created here.")


@router.post("/payout")
def refuse_payout(user: UserContext = Depends(get_current_user_context)):
    raise HTTPException(status_code=403, detail="Accounting is read-only. Payouts are not created here.")


@router.post("/invoice")
def refuse_invoice(user: UserContext = Depends(get_current_user_context)):
    raise HTTPException(status_code=403, detail="Accounting is read-only. Invoices are not created here.")


@router.post("/refund")
def refuse_refund(user: UserContext = Depends(get_current_user_context)):
    raise HTTPException(status_code=403, detail="Accounting is read-only. Refunds are not created here.")
