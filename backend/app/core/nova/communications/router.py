"""Nova Communications APIs. Authenticated wrapper over existing email/calendar stores."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.communications import service
from app.core.nova.communications.schemas import (
    NovaCommsBrainOut,
    NovaCommsBrainRequest,
    NovaCommsContactOut,
    NovaCommsDashboardOut,
    NovaCommsDraftCreate,
    NovaCommsDraftOut,
    NovaCommsEventCreate,
    NovaCommsEventOut,
    NovaCommsMessageCreate,
    NovaCommsMessageOut,
    NovaCommsMessageUpdate,
    NovaCommsNotificationOut,
    NovaCommsSendRequest,
)
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/communications",
    tags=["nova-communications"],
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
    if isinstance(exc, service.NovaCommunicationsError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/dashboard", response_model=NovaCommsDashboardOut)
def communications_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.dashboard(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/messages", response_model=list[NovaCommsMessageOut])
def list_messages(
    important: bool = False,
    unread: bool = False,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.message_out(row)
        for row in service.list_messages(
            db, organization_id=org_id, user=user, important_only=important, unread_only=unread
        )
    ]


@router.post("/messages", response_model=NovaCommsMessageOut)
def create_message(
    payload: NovaCommsMessageCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.message_out(
            service.create_message(db, payload, organization_id=org_id, user=user),
            include_body=True,
        )
    except service.NovaCommunicationsError as exc:
        _raise(exc)


@router.get("/messages/{message_id}", response_model=NovaCommsMessageOut)
def get_message(
    message_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.message_out(
            service.get_message(db, message_id, organization_id=org_id, user=user),
            include_body=True,
        )
    except service.NovaCommunicationsError as exc:
        _raise(exc)


@router.patch("/messages/{message_id}", response_model=NovaCommsMessageOut)
def update_message(
    message_id: str,
    payload: NovaCommsMessageUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.message_out(
            service.update_message(db, message_id, payload, organization_id=org_id, user=user),
            include_body=True,
        )
    except service.NovaCommunicationsError as exc:
        _raise(exc)


@router.get("/drafts", response_model=list[NovaCommsDraftOut])
def list_drafts(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return [service.draft_out(row) for row in service.list_drafts(db, user=user)]


@router.post("/drafts", response_model=NovaCommsDraftOut)
def create_draft(
    payload: NovaCommsDraftCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return service.draft_out(service.create_draft(db, payload, organization_id=org_id, user=user))


@router.post("/send")
def send_email(
    payload: NovaCommsSendRequest,
    user: UserContext = Depends(get_current_user_context),
):
    _resolve_org(user, payload.organization_id)
    try:
        service.send_blocked(payload)
    except service.NovaCommunicationsError as exc:
        _raise(exc)


@router.get("/events", response_model=list[NovaCommsEventOut])
def list_events(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return [service.event_out(row) for row in service.list_events(db, user=user)]


@router.post("/events", response_model=NovaCommsEventOut)
def create_event(
    payload: NovaCommsEventCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.event_out(service.create_event(db, payload, organization_id=org_id, user=user))
    except service.NovaCommunicationsError as exc:
        _raise(exc)


@router.get("/contacts", response_model=list[NovaCommsContactOut])
def list_contacts(
    q: str | None = Query(default=None, max_length=180),
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    contacts = service.derive_contacts(db, organization_id=org_id, user=user)
    if q:
        needle = q.lower()
        contacts = [
            row
            for row in contacts
            if needle in row.name.lower() or needle in (row.email or "").lower()
        ]
    return contacts


@router.get("/notifications", response_model=list[NovaCommsNotificationOut])
def list_notifications(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.list_notifications(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.post("/notifications/{notification_id}/read", response_model=NovaCommsNotificationOut)
def read_notification(
    notification_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        row = service.mark_notification_read(
            db, notification_id, organization_id=org_id, user=user
        )
        return NovaCommsNotificationOut(
            notification_id=row.notification_id,
            kind=row.kind,
            title=row.title,
            detail=row.detail,
            link=row.link,
            read=row.read,
            created_at=row.created_at,
        )
    except service.NovaCommunicationsError as exc:
        _raise(exc)


@router.post("/ask", response_model=NovaCommsBrainOut)
def ask_communications(
    payload: NovaCommsBrainRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.ask_communications(db, payload, organization_id=org_id, user=user)
    except service.NovaCommunicationsError as exc:
        _raise(exc)
