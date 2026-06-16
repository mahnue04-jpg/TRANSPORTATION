"""Phase 36 assistant execution/memory/event router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import UserContext, get_current_user_context, require_auth
from app.core.nova.assistant_contract import normalize_client_event_payload
from app.core.nova.assistant_execution_service import (
    create_operational_note,
    get_execution_by_id,
    get_recent_executions,
    get_recent_operational_events,
    get_recent_memory,
    log_operational_event,
)

router = APIRouter(
    prefix="/api/assistant",
    tags=["assistant-workflow"],
    dependencies=[Depends(require_auth)],
)


class AssistantClientEventRequest(BaseModel):
    event_type: str = Field(default="client", max_length=64)
    event_name: str = Field(default="event", max_length=96)
    status: str = Field(default="info", max_length=24)
    session_id: str | None = Field(default=None, max_length=128)
    route: str | None = Field(default=None, max_length=128)
    correlation_id: str | None = Field(default=None, max_length=96)
    payload: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=512)


class AssistantOperationalNoteRequest(BaseModel):
    title: str = Field(default="Operational note", max_length=128)
    note: str = Field(..., min_length=1, max_length=5000)
    session_id: str | None = Field(default=None, max_length=128)
    scope: str = Field(default="operational_note", max_length=64)


@router.get("/executions")
def assistant_recent_executions(
    limit: int = Query(default=20, ge=1, le=100),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    items = get_recent_executions(str(user.user_id), limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/executions/{execution_id}")
def assistant_execution_detail(
    execution_id: str,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    item = get_execution_by_id(str(user.user_id), execution_id)
    if not item:
        raise HTTPException(status_code=404, detail="Execution record not found")
    return item


@router.get("/memory")
def assistant_recent_memory(
    session_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    items = get_recent_memory(str(user.user_id), session_id=session_id, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/events")
def assistant_recent_events(
    session_id: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    items = get_recent_operational_events(str(user.user_id), session_id=session_id, limit=limit)
    return {"items": items, "count": len(items)}


@router.post("/memory/notes")
def assistant_create_note(
    payload: AssistantOperationalNoteRequest,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    return create_operational_note(
        user_id=str(user.user_id),
        role=str(user.role),
        session_id=payload.session_id,
        title=payload.title,
        note=payload.note,
        scope=payload.scope,
    )


@router.post("/events")
def assistant_client_event(
    payload: dict[str, Any] | None = None,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    normalized = normalize_client_event_payload(payload)
    logged = log_operational_event(
        user_id=str(user.user_id),
        role=str(user.role),
        event_type=normalized["event_type"],
        event_name=normalized["event_name"],
        status=normalized["status"],
        session_id=normalized["session_id"],
        route=normalized["route"],
        correlation_id=normalized["correlation_id"],
        payload=normalized["payload"],
        error_message=normalized["error_message"],
    )
    return {"status": "logged", "event": logged or normalized}
