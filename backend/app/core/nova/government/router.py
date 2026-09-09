"""Nova Government APIs. Organization/research only. No agency submission."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.communications.service import draft_out
from app.core.nova.government import service
from app.core.nova.government.schemas import (
    NovaGovBrainOut,
    NovaGovBrainRequest,
    NovaGovChecklistCreate,
    NovaGovChecklistOut,
    NovaGovDashboardOut,
    NovaGovDraftLink,
    NovaGovProgramCreate,
    NovaGovProgramOut,
    NovaGovSearchRequest,
    NovaGovSourceCreate,
    NovaGovSourceOut,
    NovaGovWorkCreate,
    NovaGovWorkOut,
    NovaGovWorkUpdate,
)
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/government",
    tags=["nova-government"],
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
    if isinstance(exc, service.NovaGovernmentError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/dashboard", response_model=NovaGovDashboardOut)
def government_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.dashboard(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/items", response_model=list[NovaGovWorkOut])
def list_items(
    status: str | None = None,
    category: str | None = None,
    government_level: str | None = None,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.work_out(row)
        for row in service.list_items(
            db,
            organization_id=org_id,
            user=user,
            status=status,
            category=category,
            government_level=government_level,
        )
    ]


@router.post("/items", response_model=NovaGovWorkOut)
def create_item(
    payload: NovaGovWorkCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.work_out(service.create_item(db, payload, organization_id=org_id, user=user))
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.get("/items/{item_id}", response_model=NovaGovWorkOut)
def get_item(
    item_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.work_out(service.get_item(db, item_id, organization_id=org_id, user=user))
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.patch("/items/{item_id}", response_model=NovaGovWorkOut)
def update_item(
    item_id: str,
    payload: NovaGovWorkUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.work_out(
            service.update_item(db, item_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.get("/items/{item_id}/checklist", response_model=list[NovaGovChecklistOut])
def list_checklist(
    item_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return [
            service.checklist_out(row)
            for row in service.list_checklist(db, item_id, organization_id=org_id, user=user)
        ]
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.post("/items/{item_id}/checklist", response_model=NovaGovChecklistOut)
def add_checklist(
    item_id: str,
    payload: NovaGovChecklistCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.checklist_out(
            service.add_checklist(db, item_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.post("/checklist/{checklist_id}/complete", response_model=NovaGovChecklistOut)
def complete_checklist(
    checklist_id: str,
    completed: bool = True,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.checklist_out(
            service.toggle_checklist(
                db, checklist_id, organization_id=org_id, user=user, completed=completed
            )
        )
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.get("/items/{item_id}/sources", response_model=list[NovaGovSourceOut])
def list_sources(
    item_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return [
            service.source_out(row)
            for row in service.list_sources(db, item_id, organization_id=org_id, user=user)
        ]
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.post("/items/{item_id}/sources", response_model=NovaGovSourceOut)
def add_source(
    item_id: str,
    payload: NovaGovSourceCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.source_out(
            service.add_source(db, item_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.post("/items/{item_id}/calendar", response_model=NovaGovWorkOut)
def link_calendar(
    item_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.work_out(
            service.link_deadline_to_calendar(db, item_id, organization_id=org_id, user=user)
        )
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.post("/items/{item_id}/draft")
def link_draft(
    item_id: str,
    payload: NovaGovDraftLink,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        row, draft = service.link_draft(db, item_id, payload, organization_id=org_id, user=user)
        return {"item": service.work_out(row), "draft": draft_out(draft), "sent": False}
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.post("/items/{item_id}/file")
def refuse_file(item_id: str, user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_filing()
    except service.NovaGovernmentError as exc:
        _raise(exc)


@router.get("/programs", response_model=list[NovaGovProgramOut])
def list_programs(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        NovaGovProgramOut(
            program_id=row.program_id,
            program_name=row.program_name,
            agency=row.agency,
            eligibility=row.eligibility,
            amount_range=row.amount_range,
            deadline=row.deadline,
            status=row.status,
            requirements=row.requirements,
            attachments_note=row.attachments_note,
            contact_info=row.contact_info,
            notes=row.notes,
        )
        for row in service.list_programs(db, organization_id=org_id, user=user)
    ]


@router.post("/programs", response_model=NovaGovProgramOut)
def create_program(
    payload: NovaGovProgramCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    row = service.create_program(db, payload, organization_id=org_id, user=user)
    return NovaGovProgramOut(
        program_id=row.program_id,
        program_name=row.program_name,
        agency=row.agency,
        eligibility=row.eligibility,
        amount_range=row.amount_range,
        deadline=row.deadline,
        status=row.status,
        requirements=row.requirements,
        attachments_note=row.attachments_note,
        contact_info=row.contact_info,
        notes=row.notes,
    )


@router.post("/search")
def search_government(
    payload: NovaGovSearchRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    return service.search_government(db, payload, organization_id=org_id, user=user)


@router.post("/ask", response_model=NovaGovBrainOut)
def ask_government(
    payload: NovaGovBrainRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.ask_government(db, payload, organization_id=org_id, user=user)
    except service.NovaGovernmentError as exc:
        _raise(exc)
