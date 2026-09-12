"""Nova V2 Today APIs. Additive. Does not reuse Health command-center or NovaAction."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.today import service
from app.core.nova.today.schemas import (
    NovaTodayActionCreate,
    NovaTodayActionOut,
    NovaTodayApproveOut,
    NovaTodayApproveRequest,
    NovaTodayBrainOut,
    NovaTodayBrainRequest,
    NovaTodayDashboardOut,
    NovaTodayHistoryItem,
    NovaTodaySnoozeRequest,
)
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/today",
    tags=["nova-today"],
    dependencies=[Depends(require_nova_access)],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: Exception) -> None:
    if isinstance(exc, service.NovaTodayError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/dashboard", response_model=NovaTodayDashboardOut)
def today_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.dashboard(db, organization_id=_resolve_org(user, organization_id), user=user)
    except Exception as exc:
        _raise(exc)


@router.post("/ask", response_model=NovaTodayBrainOut)
def ask_today(
    payload: NovaTodayBrainRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.ask_today(
            db,
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except Exception as exc:
        _raise(exc)


@router.get("/history", response_model=list[NovaTodayHistoryItem])
def today_history(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.list_history(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/actions/{action_id}", response_model=NovaTodayActionOut)
def get_today_action(
    action_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.get_action(
            db,
            action_id,
            organization_id=_resolve_org(user, organization_id),
            user=user,
        )
    except Exception as exc:
        _raise(exc)


@router.get("/actions", response_model=list[NovaTodayActionOut])
def list_today_actions(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.list_actions(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.post("/actions", response_model=NovaTodayActionOut)
def create_today_action(
    payload: NovaTodayActionCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.create_action(
            db,
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/actions/{action_id}/approve", response_model=NovaTodayApproveOut)
def approve_today_action(
    action_id: str,
    payload: NovaTodayApproveRequest | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or NovaTodayApproveRequest()
    try:
        return service.approve_action(
            db,
            action_id,
            body,
            organization_id=_resolve_org(user, body.organization_id),
            user=user,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/actions/{action_id}/snooze", response_model=NovaTodayActionOut)
def snooze_today_action(
    action_id: str,
    payload: NovaTodaySnoozeRequest | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    body = payload or NovaTodaySnoozeRequest()
    try:
        return service.snooze_action(
            db,
            action_id,
            organization_id=_resolve_org(user, body.organization_id),
            user=user,
            hours=body.hours,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/actions/{action_id}/dismiss", response_model=NovaTodayActionOut)
def dismiss_today_action(
    action_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.dismiss_action(
            db,
            action_id,
            organization_id=_resolve_org(user, organization_id),
            user=user,
        )
    except Exception as exc:
        _raise(exc)


@router.post("/send")
def refuse_send(user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_send()
    except Exception as exc:
        _raise(exc)


@router.post("/file")
def refuse_file(user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_file()
    except Exception as exc:
        _raise(exc)


@router.post("/ledger")
def refuse_ledger(user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_ledger()
    except Exception as exc:
        _raise(exc)


@router.post("/call")
def refuse_call(user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_call()
    except Exception as exc:
        _raise(exc)
