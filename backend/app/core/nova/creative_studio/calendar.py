"""Creative Studio Autopilot content calendar (planning only).

These endpoints create, edit, list and cancel owner-scoped content entries.
They NEVER trigger generation, billing, social authorization or publishing.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.db_models import NovaCreativeCalendarEntry, NovaCreativeProject
from app.core.nova.creative_studio.models import new_id
from app.core.nova.router import require_nova_access
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/creative",
    tags=["nova-creative-calendar"],
    dependencies=[Depends(require_nova_access)],
)
Channel = Literal["TikTok", "Instagram", "Facebook", "YouTube Shorts"]
Mode = Literal["faceless", "presenter", "drama", "education"]
State = Literal["draft", "ready_for_review", "approved", "canceled"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CalendarCreate(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    script: str = Field(default="", max_length=15000)
    content_mode: Mode = "faceless"
    channels: list[Channel] = Field(default_factory=list, max_length=4)
    scheduled_at: datetime

    @field_validator("topic")
    @classmethod
    def meaningful_topic(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Topic cannot be blank.")
        return result

    @field_validator("scheduled_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("A timezone offset is required for scheduled_at.")
        return value.astimezone(timezone.utc)


class CalendarUpdate(BaseModel):
    topic: str | None = Field(default=None, min_length=1, max_length=300)
    script: str | None = Field(default=None, max_length=15000)
    content_mode: Mode | None = None
    channels: list[Channel] | None = Field(default=None, max_length=4)
    scheduled_at: datetime | None = None
    status: State | None = None

    @field_validator("topic")
    @classmethod
    def meaningful_topic(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Topic cannot be blank.")
        return value.strip() if value is not None else None

    @field_validator("scheduled_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("A timezone offset is required for scheduled_at.")
            return value.astimezone(timezone.utc)
        return None


def _project(db: Session, owner: str, project_id: str):
    row = db.query(NovaCreativeProject).filter_by(id=project_id, owner_id=owner).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return row


def _entry(db: Session, owner: str, project_id: str, entry_id: str) -> NovaCreativeCalendarEntry:
    row = db.query(NovaCreativeCalendarEntry).filter_by(
        id=entry_id, owner_id=owner, project_id=project_id
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Calendar entry not found.")
    return row


def _as_dict(row: NovaCreativeCalendarEntry) -> dict:
    return {
        "id": row.id, "project_id": row.project_id, "topic": row.topic,
        "script": row.script, "content_mode": row.content_mode,
        "channels": json.loads(row.channels_json), "scheduled_at": row.scheduled_at,
        "status": row.status, "created_at": row.created_at,
        "updated_at": row.updated_at, "publishing_enabled": False,
        "message": "Planning only. Approval does not schedule or publish a post.",
    }


@router.post("/projects/{project_id}/calendar")
def add_calendar_entry(
    project_id: str, payload: CalendarCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    now = _now()
    row = NovaCreativeCalendarEntry(
        id=new_id("calendar"), owner_id=user.user_id, project_id=project_id,
        topic=payload.topic, script=payload.script, content_mode=payload.content_mode,
        channels_json=json.dumps(sorted(set(payload.channels))),
        scheduled_at=payload.scheduled_at.isoformat(), status="draft",
        created_at=now, updated_at=now,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _as_dict(row)


@router.get("/projects/{project_id}/calendar")
def list_calendar_entries(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    rows = db.query(NovaCreativeCalendarEntry).filter_by(
        owner_id=user.user_id, project_id=project_id
    ).order_by(NovaCreativeCalendarEntry.scheduled_at.asc()).limit(500).all()
    return {"count": len(rows), "entries": [_as_dict(row) for row in rows],
            "publishing_enabled": False}


@router.patch("/projects/{project_id}/calendar/{entry_id}")
def edit_calendar_entry(
    project_id: str, entry_id: str, payload: CalendarUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    row = _entry(db, user.user_id, project_id, entry_id)
    updates = payload.model_dump(exclude_unset=True)
    if row.status == "canceled" and updates.get("status") not in (None, "canceled"):
        raise HTTPException(status_code=409, detail="A canceled entry cannot be reactivated.")
    if updates.get("status") == "approved" and not (updates.get("script", row.script)).strip():
        raise HTTPException(status_code=422, detail="Save a reviewed script before approval.")
    for key in ("topic", "script", "content_mode"):
        if key in updates:
            setattr(row, key, updates[key])
    if "channels" in updates:
        row.channels_json = json.dumps(sorted(set(updates["channels"])))
    if "scheduled_at" in updates:
        if updates["scheduled_at"] is None:
            raise HTTPException(status_code=422, detail="Scheduled date cannot be cleared.")
        row.scheduled_at = updates["scheduled_at"].isoformat()
    if "status" in updates:
        if updates["status"] is None:
            raise HTTPException(status_code=422, detail="Status cannot be cleared.")
        row.status = updates["status"]
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return _as_dict(row)


@router.post("/projects/{project_id}/calendar/{entry_id}/cancel")
def cancel_calendar_entry(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    row = _entry(db, user.user_id, project_id, entry_id)
    row.status = "canceled"
    row.updated_at = _now()
    db.commit()
    db.refresh(row)
    return _as_dict(row)
