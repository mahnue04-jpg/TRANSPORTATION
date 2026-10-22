"""Shared Nova screen language. Voice interpretation and bidirectional text stay unavailable."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.language.catalog import SUPPORTED, status
from app.core.nova.language.guards import assess_operations_task
from app.core.nova.router import require_nova_access
from app.db.session import get_db
from .models import NovaLanguagePreference

router = APIRouter(
    prefix="/api/nova/language",
    tags=["nova-language"],
    dependencies=[Depends(require_nova_access)],
)


class LanguageUpdate(BaseModel):
    screen_language: str = Field(min_length=2, max_length=8)


class TaskGuardIn(BaseModel):
    text: str = Field(default="", max_length=8000)
    requested_language: str = Field(default="en", max_length=8)


def _payload(code: str, persisted: bool) -> dict:
    body = status(code)
    body["persisted"] = persisted
    body["workspace_fallback"] = False
    return body


def _owned(db: Session, user: UserContext) -> NovaLanguagePreference | None:
    row = db.get(NovaLanguagePreference, user.user_id)
    if row is None:
        return None
    org = user.organization_id or ""
    if row.organization_id != org:
        return None
    return row


@router.get("")
def read_language(
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    row = _owned(db, user)
    if row is None or row.screen_language not in SUPPORTED:
        return _payload("en", False)
    return _payload(row.screen_language, True)


@router.put("")
def update_language(
    payload: LanguageUpdate,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    code = payload.screen_language.strip().lower()
    if code not in SUPPORTED:
        raise HTTPException(422, "That screen language is not in the shared Nova catalog yet.")
    org = user.organization_id or ""
    row = db.get(NovaLanguagePreference, user.user_id)
    if row is None:
        row = NovaLanguagePreference(
            user_id=user.user_id,
            organization_id=org,
            screen_language=code,
            updated_at=datetime.now(timezone.utc),
        )
        db.add(row)
    else:
        row.organization_id = org
        row.screen_language = code
        row.updated_at = datetime.now(timezone.utc)
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    return _payload(code, True)


@router.post("/task-guard")
def task_guard(
    payload: TaskGuardIn,
    response: Response,
    user: UserContext = Depends(get_current_user_context),
):
    """Operations Agent language check. The task text is returned unchanged."""
    del user
    response.headers["Cache-Control"] = "no-store"
    return assess_operations_task(payload.text, payload.requested_language)
