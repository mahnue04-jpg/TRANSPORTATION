"""Nova Autonomy Phase 1 router. Bypassed when NOVA_AUTONOMY_PHASE1 is off."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.autonomy import executor, ledger
from app.core.nova.autonomy.models import AutonomyApproveRequest, AutonomyIntentCreate, AutonomyIntentOut
from app.core.nova.autonomy.policy import phase1_enabled
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.today import service as today
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/autonomy",
    tags=["nova-autonomy"],
    dependencies=[Depends(require_nova_access)],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    if requested and user.organization_id and requested != user.organization_id:
        raise HTTPException(status_code=403, detail="Cross-tenant Nova access denied")
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: Exception) -> None:
    if isinstance(exc, executor.AutonomyError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


def _require_flag() -> None:
    if not phase1_enabled():
        raise HTTPException(status_code=404, detail="Autonomy Phase 1 is off.")


@router.post("/intents", response_model=AutonomyIntentOut)
def create_autonomy_intent(
    payload: AutonomyIntentCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _require_flag()
    try:
        return executor.create_intent(
            db,
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/intents/{audit_id}/approve", response_model=AutonomyIntentOut)
def approve_autonomy_intent(
    audit_id: str,
    payload: AutonomyApproveRequest | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _require_flag()
    body = payload or AutonomyApproveRequest()
    try:
        return executor.approve_intent(
            db,
            audit_id,
            body,
            organization_id=_resolve_org(user, body.organization_id),
            user=user,
        )
    except Exception as exc:
        _raise(exc)


@router.get("/intents/{audit_id}", response_model=AutonomyIntentOut)
def get_autonomy_intent(
    audit_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _require_flag()
    try:
        return executor.get_intent(
            db, audit_id, organization_id=_resolve_org(user, organization_id)
        )
    except Exception as exc:
        _raise(exc)


@router.get("/ledger", response_model=list[AutonomyIntentOut])
def list_autonomy_ledger(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _require_flag()
    return ledger.list_ledger(db, organization_id=_resolve_org(user, organization_id))


@router.get("/history", response_model=list[AutonomyIntentOut])
def autonomy_history(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _require_flag()
    org_id = _resolve_org(user, organization_id)
    today.list_history(db, organization_id=org_id, user=user)
    return ledger.list_ledger(db, organization_id=org_id)
