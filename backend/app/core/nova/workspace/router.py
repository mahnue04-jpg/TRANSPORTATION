"""Nova Workspace APIs. Separate from Health /workspace and frozen Freight."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.workspace import service
from app.core.nova.workspace.schemas import (
    NovaWorkspaceBrainOut,
    NovaWorkspaceBrainRequest,
    NovaWorkspaceConversationCreate,
    NovaWorkspaceConversationOut,
    NovaWorkspaceConversationUpdate,
    NovaWorkspaceDashboardOut,
    NovaWorkspaceFileCreate,
    NovaWorkspaceFileOut,
    NovaWorkspaceProjectCreate,
    NovaWorkspaceProjectOut,
    NovaWorkspaceProjectUpdate,
    NovaWorkspaceSearchOut,
)
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/workspace",
    tags=["nova-workspace"],
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
    if isinstance(exc, service.NovaWorkspaceError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/dashboard", response_model=NovaWorkspaceDashboardOut)
def workspace_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return service.dashboard(db, organization_id=org_id, user=user)


@router.get("/projects", response_model=list[NovaWorkspaceProjectOut])
def list_projects(
    include_archived: bool = False,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.project_out(row)
        for row in service.list_projects(
            db, organization_id=org_id, user=user, include_archived=include_archived
        )
    ]


@router.post("/projects", response_model=NovaWorkspaceProjectOut)
def create_project(
    payload: NovaWorkspaceProjectCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.project_out(
            service.create_project(db, payload, organization_id=org_id, user=user)
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.get("/projects/{workspace_id}", response_model=NovaWorkspaceProjectOut)
def get_project(
    workspace_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.project_out(
            service.get_project(db, workspace_id, organization_id=org_id, user=user, touch=True)
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.patch("/projects/{workspace_id}", response_model=NovaWorkspaceProjectOut)
def update_project(
    workspace_id: str,
    payload: NovaWorkspaceProjectUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.project_out(
            service.update_project(db, workspace_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.post("/projects/{workspace_id}/archive", response_model=NovaWorkspaceProjectOut)
def archive_project(
    workspace_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.project_out(
            service.archive_project(db, workspace_id, organization_id=org_id, user=user)
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.get("/files", response_model=list[NovaWorkspaceFileOut])
def list_files(
    workspace_id: str | None = None,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.file_out(row)
        for row in service.list_files(
            db, organization_id=org_id, user=user, workspace_id=workspace_id
        )
    ]


@router.post("/files", response_model=NovaWorkspaceFileOut)
def add_file(
    payload: NovaWorkspaceFileCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.file_out(service.add_file(db, payload, organization_id=org_id, user=user))
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.get("/conversations", response_model=list[NovaWorkspaceConversationOut])
def list_conversations(
    workspace_id: str | None = None,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.conversation_out(row, preview=preview)
        for row, preview in service.list_conversations(
            db, organization_id=org_id, user=user, workspace_id=workspace_id
        )
    ]


@router.post("/conversations", response_model=NovaWorkspaceConversationOut)
def create_conversation(
    payload: NovaWorkspaceConversationCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.conversation_out(
            service.create_conversation(db, payload, organization_id=org_id, user=user)
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.get("/conversations/{conversation_id}", response_model=NovaWorkspaceConversationOut)
def get_conversation(
    conversation_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        row, messages = service.get_conversation(
            db, conversation_id, organization_id=org_id, user=user, touch=True
        )
        return service.conversation_out(row, messages=messages)
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.patch("/conversations/{conversation_id}", response_model=NovaWorkspaceConversationOut)
def update_conversation(
    conversation_id: str,
    payload: NovaWorkspaceConversationUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.conversation_out(
            service.update_conversation(
                db, conversation_id, payload, organization_id=org_id, user=user
            )
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.get("/search", response_model=NovaWorkspaceSearchOut)
def search_workspace(
    q: str = Query(..., min_length=2, max_length=400),
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.search_workspace(db, q, organization_id=org_id, user=user)
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.post("/ask", response_model=NovaWorkspaceBrainOut)
def ask_workspace(
    payload: NovaWorkspaceBrainRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.ask_workspace(db, payload, organization_id=org_id, user=user)
    except service.NovaWorkspaceError as exc:
        _raise(exc)
