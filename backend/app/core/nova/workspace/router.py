"""Nova Workspace APIs. Separate from Health /workspace and frozen Freight."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile, Form
from sqlalchemy.orm import Session
import logging
from typing import Literal

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
    NovaWorkspaceTransferCreate,
)
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/workspace",
    tags=["nova-workspace"],
    dependencies=[Depends(require_nova_access)],
)


@router.post("/transcribe")
def transcribe_speech(audio: UploadFile = File(...),
    user: UserContext = Depends(get_current_user_context),
    language: Literal["en", "so", "ar", "fr", "es"] = Form("so")):
    """Return original multilingual speech as reviewable text, without saving the recording."""
    from app.ai import get_client
    allowed = {"audio/webm": "webm", "audio/mp4": "mp4", "audio/ogg": "ogg", "audio/wav": "wav", "audio/mpeg": "mp3"}
    content_type = (audio.content_type or "").split(";")[0]
    if content_type not in allowed:
        raise HTTPException(415, "Unsupported audio format. Try typing your request.")
    try:
        data = audio.file.read(10_000_001)
    finally:
        audio.file.close()
    if not data or len(data) > 10_000_000:
        raise HTTPException(413, "Recording must contain audio and be under 10 MB.")
    # Somali is not a supported explicit language hint for this model. Allow
    # detection and request original Somali text rather than sending a rejected code.
    language = language if isinstance(language, str) else "so"
    names = {"en": "English", "so": "Somali", "ar": "Arabic", "fr": "French", "es": "Spanish"}
    kwargs = dict(model="gpt-4o-transcribe",
        file=("speech." + allowed[content_type], data, content_type),
        prompt=f"Transcribe the {names[language]} speech in its original language. Do not translate it into English.")
    if language != "so":
        kwargs["language"] = language
    try:
        result = get_client().audio.transcriptions.create(**kwargs)
    except Exception as exc:
        # Never log recordings, transcripts, request bodies or provider error text.
        logging.getLogger(__name__).warning("workspace_transcription_failed type=%s status=%s",
            type(exc).__name__, getattr(exc, "status_code", None))
        raise HTTPException(503, "Speech transcription is unavailable. Please type your request or try again.") from exc
    text = str(result.text or "").strip()
    if not text or len(text) > 4000:
        raise HTTPException(422, "No usable short transcript returned. Try a shorter recording or type your request.")
    return {"text": text, "language": language, "review_required": True}


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


@router.post("/transfers")
def prepare_transfer(payload: NovaWorkspaceTransferCreate,
    user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    from . import transfers
    try:
        return transfers.prepare(db, payload.workspace_id, payload.recipient_email,
            payload.include_conversations, payload.include_file_text,
            organization_id=_resolve_org(user, None), user=user)
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.get("/transfers")
def incoming_transfers(user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    from . import transfers
    return transfers.incoming(db, user=user)


@router.post("/transfers/{transfer_id}/accept")
def accept_transfer(transfer_id: str,
    user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    from . import transfers
    try:
        return transfers.accept(db, transfer_id, organization_id=_resolve_org(user, None), user=user)
    except service.NovaWorkspaceError as exc:
        _raise(exc)


@router.post("/transfers/{transfer_id}/cancel")
def cancel_transfer(transfer_id: str,
    user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    from . import transfers
    try:
        return transfers.cancel(db, transfer_id, organization_id=_resolve_org(user, None), user=user)
    except service.NovaWorkspaceError as exc:
        _raise(exc)


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


@router.get("/files/{file_id}", response_model=NovaWorkspaceFileOut)
def get_file(
    file_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.file_out(
            service.get_file(db, file_id, organization_id=org_id, user=user, touch=True)
        )
    except service.NovaWorkspaceError as exc:
        _raise(exc)


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
