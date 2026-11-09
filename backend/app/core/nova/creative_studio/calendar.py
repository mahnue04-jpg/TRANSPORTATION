"""Creative Studio Autopilot content calendar (planning only).

These endpoints create, edit, list and cancel owner-scoped content entries.
They NEVER trigger generation, billing, social authorization or publishing.
"""
from __future__ import annotations

import json
import hashlib
import re
import tempfile
import threading
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.db_models import NovaCreativeCalendarEntry, NovaCreativeProject, NovaCreativeRenderClaim, NovaCreativeStoryboardRevision
from app.core.nova.creative_studio.models import CreativeAsset, GenerationJob, new_id
from app.core.nova.creative_studio.store import DbCreativeStudioStore
from app.core.nova.creative_studio.service import CreativeStudioError, get_service
from app.core.nova.creative_studio.offline_commercial import OfflineCommercialError, render_offline_montage
from app.core.nova.router import require_nova_access
from app.db.session import SessionLocal, get_db

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
    script: str = Field(default="", max_length=120000)
    content_mode: Mode = "faceless"
    channels: list[Channel] = Field(default_factory=list, max_length=4)
    scheduled_at: datetime
    duration_seconds: int = Field(default=30, ge=15, le=7200)

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
    script: str | None = Field(default=None, max_length=120000)
    content_mode: Mode | None = None
    channels: list[Channel] | None = Field(default=None, max_length=4)
    scheduled_at: datetime | None = None
    duration_seconds: int | None = Field(default=None, ge=15, le=7200)
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
        "duration_seconds": row.duration_seconds,
        "timeline_asset_ids": json.loads(row.timeline_json or "[]"),
        "chapters": json.loads(row.chapters_json or "[]"),
        "storyboard": json.loads(row.storyboard_json or "[]"),
        "narrator_voice": row.narrator_voice,
        "narrator_speed": row.narrator_speed,
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
        scheduled_at=payload.scheduled_at.isoformat(), duration_seconds=payload.duration_seconds,
        status="draft",
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
    if row.status == "canceled" and updates:
        raise HTTPException(status_code=409, detail="A canceled entry cannot be edited or reactivated.")
    if updates.get("status") == "approved" and not (updates.get("script", row.script) or "").strip():
        raise HTTPException(status_code=422, detail="Save a reviewed script before approval.")
    # Editing an approved plan invalidates its earlier approval unless the
    # same request explicitly reapproves the reviewed replacement.
    substantial = {"topic", "script", "content_mode", "channels", "scheduled_at", "duration_seconds"}
    if row.status == "approved" and substantial.intersection(updates) and "status" not in updates:
        updates["status"] = "ready_for_review"
    for key in ("topic", "script", "content_mode", "duration_seconds"):
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


@router.post("/projects/{project_id}/calendar/{entry_id}/prepare")
def prepare_calendar_content(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Save approved script as real Studio text assets, without launching providers.

    Repeated preparation of the same approved revision reuses existing assets;
    edits revoke approval and require another review before preparing again.
    """
    _project(db, user.user_id, project_id)
    row = _entry(db, user.user_id, project_id, entry_id)
    if row.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the reviewed script before preparing production assets.")
    script = row.script.strip()
    if not script:
        raise HTTPException(status_code=422, detail="An approved script is required.")
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    store = DbCreativeStudioStore(db)
    existing = {}
    for asset in store.list_assets(project_id, user.user_id):
        meta = asset.metadata or {}
        if (meta.get("source") == "autopilot_calendar" and
                meta.get("calendar_entry_id") == entry_id and
                meta.get("script_sha256") == digest and
                asset.kind in {"script", "voiceover", "subtitle"}):
            existing[asset.kind] = asset

    generated = []
    for kind, title in (
        ("script", "Calendar — approved script"),
        ("voiceover", "Calendar — reviewed narration"),
        ("subtitle", "Calendar — caption source text"),
    ):
        asset = existing.get(kind)
        if asset is None:
            asset = store.save_asset(CreativeAsset(
                id=new_id("casset"), owner_id=user.user_id, project_id=project_id,
                kind=kind, title=title, content=script,
                status="GENERATED",
                metadata={
                    "source": "autopilot_calendar",
                    "calendar_entry_id": entry_id,
                    "script_sha256": digest,
                    "content_mode": row.content_mode,
                    "reviewed_text_only": True,
                    "media_generated": False,
                    "publish_ready": False,
                },
            ))
        generated.append(asset)
    return {
        "status": "PREPARED_TEXT_ONLY", "entry_id": entry_id,
        "assets": [asset.as_dict() for asset in generated],
        "reused": len(existing) == 3,
        "media_generated": False, "published": False,
        "message": "Approved script, narration text and caption text saved in this Studio project. No video, speech or social post was generated.",
    }


def _preview_scenes(script: str) -> list[dict]:
    """Fit short owner-reviewed narration into six beats, without rewriting it."""
    text = " ".join(script.split())
    words = text.split()
    if not 8 <= len(words) <= 55 or len(text) > 450:
        raise HTTPException(
            status_code=422,
            detail="The offline 30-second preview needs 8–55 words (up to 450 characters). Shorten or split longer scripts into episodes.",
        )
    # Split by word counts, preserving the exact reviewed words and their order.
    beats = min(6, max(2, (len(words) + 9) // 10))
    result = []
    for index in range(beats):
        segment = words[index * len(words) // beats:(index + 1) * len(words) // beats]
        line = " ".join(segment)
        result.append({
            "heading": ("Hook", "Problem", "Capabilities", "Process", "Progress", "CTA")[index],
            "voiceover_text": line,
            "subtitle_text": line,
            "duration_seconds": 30.0 / beats,
        })
    return result


def _render_calendar_preview(db: Session, owner_id: str, project_id: str, entry_id: str):
    """Render a local AMICOR-branded preview and archive its bytes as an owner import."""
    from app.core.nova.creative_studio import private_object_storage as remote
    import os

    project = _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the reviewed script before rendering.")
    if entry.content_mode not in {"faceless", "education"}:
        raise HTTPException(status_code=422, detail="This offline preview supports faceless and education only. Presenter and drama need their dedicated renderers.")
    if os.getenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "").lower() in {"1", "true", "yes"} and not remote.enabled():
        raise HTTPException(status_code=503, detail="Durable private video storage must be enabled before rendering.")
    if entry.duration_seconds != 30:
        raise HTTPException(status_code=422, detail="The current offline renderer only supports the 30-second preview. Longer videos require the long-form production workflow, which is not yet enabled.")
    script = entry.script.strip()
    scenes = _preview_scenes(script)
    digest = hashlib.sha256(script.encode("utf-8")).hexdigest()
    store = DbCreativeStudioStore(db)
    service = get_service(db)

    for asset in store.list_assets(project_id, owner_id):
        meta = asset.metadata or {}
        if (asset.kind == "video" and meta.get("calendar_entry_id") == entry_id and
                meta.get("script_sha256") == digest and
                meta.get("pipeline") == "calendar_offline_preview"):
            try:
                if str(asset.url or "").startswith("private-studio-s3://"):
                    if remote.enabled() and remote.object_exists(asset.url, owner_id, project_id, meta.get("sha256", "")):
                        return _preview_result(project_id, asset, reused=True)
                else:
                    path, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == meta.get("sha256"):
                        return _preview_result(project_id, asset, reused=True)
            except Exception:
                pass  # A missing preview can safely be rerendered without provider fees.

    with tempfile.TemporaryDirectory(prefix="nova-calendar-preview-") as scratch:
        root = Path(scratch)
        video = root / "preview.mp4"
        narration = root / "narration.wav"
        try:
            rendered = render_offline_montage(scenes, output_mp4=video, audio_wav=narration, vertical=True)
        except OfflineCommercialError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        if not rendered.get("audio_present") or not video.is_file():
            raise HTTPException(status_code=422, detail="No playable narrated video was produced.")
        try:
            imported = service.import_finished_video(
                owner_id, project_id, video.read_bytes(), content_type="video/mp4"
            )
        except CreativeStudioError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
        asset = next((a for a in store.list_assets(project_id, owner_id)
                      if a.id == imported["asset"]["id"]), None)
        if asset is None:
            raise HTTPException(status_code=500, detail="Video asset was not saved.")
        asset.metadata = {
            **(asset.metadata or {}),
            "calendar_entry_id": entry_id, "script_sha256": digest,
            "pipeline": "calendar_offline_preview", "quality_state": "PREVIEW_ONLY",
            "preview_brand": "AMICOR Nova", "paid_provider_charges": False,
            "captions_burned_in": bool(rendered.get("captions_burned_in")),
            "captions_timing_verified": False, "narration_license_status": "AMBER",
            "publish_ready": False, "commercial_complete": False,
            "media_generated": True, "external_publishing": False,
        }
        asset = store.save_asset(asset)
    return _preview_result(project_id, asset, reused=False)


def _preview_result(project_id: str, asset: CreativeAsset, *, reused: bool):
    return {
        "status": "PREVIEW_RENDERED", "asset": asset.as_dict(),
        "reused": reused, "media_generated": True, "published": False,
        "publish_ready": False, "quality_state": "PREVIEW_ONLY",
        "download_url": (
            f"/api/nova/creative/projects/{project_id}/assets/{asset.id}/file"
        ),
        "message": (
            "AMICOR-branded local title-card MP4 with narration and captions. "
            "Not AI-generated scene footage, presenter lip-sync, or commercial-ready. "
            "Narration license and caption timing require review before publication."
        ),
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/render-preview")
async def render_calendar_preview(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    # Do not occupy the event loop during local ffmpeg rendering. Uses no paid provider.
    return await run_in_threadpool(_render_calendar_preview, db, user.user_id, project_id, entry_id)


class TimelineIn(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=16)


@router.put("/projects/{project_id}/calendar/{entry_id}/timeline")
def save_calendar_timeline(
    project_id: str, entry_id: str, payload: TimelineIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Persist ordered clip choices; no rendering, billing or publishing."""
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status == "canceled":
        raise HTTPException(status_code=409, detail="Canceled plans cannot be edited.")
    if len(payload.asset_ids) != len(set(payload.asset_ids)):
        raise HTTPException(status_code=422, detail="The timeline cannot contain duplicate clips.")
    assets = {a.id: a for a in DbCreativeStudioStore(db).list_assets(project_id, user.user_id)}
    for asset_id in payload.asset_ids:
        asset = assets.get(asset_id)
        if not asset or asset.kind != "video" or not asset.url:
            raise HTTPException(status_code=422, detail="Timeline clips must belong to this Studio project.")
    previous = json.loads(entry.timeline_json or "[]")
    if previous != payload.asset_ids:
        entry.timeline_json = json.dumps(payload.asset_ids)
        if entry.status == "approved":
            entry.status = "ready_for_review"
        entry.updated_at = _now()
        db.commit()
        db.refresh(entry)
    return _as_dict(entry)


class ChapterIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    duration_seconds: int = Field(ge=120, le=600)
    revision_note: str = Field(default="", max_length=2000)
    asset_ids: list[str] = Field(default_factory=list, max_length=16)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Chapter title cannot be blank.")
        return value


class ChaptersIn(BaseModel):
    chapters: list[ChapterIn] = Field(min_length=1, max_length=24)


@router.put("/projects/{project_id}/calendar/{entry_id}/chapters")
def save_calendar_chapters(
    project_id: str, entry_id: str, payload: ChaptersIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Persist reusable long-form chapters with their own ordered source clips."""
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status == "canceled":
        raise HTTPException(status_code=409, detail="Canceled plans cannot be changed.")
    if sum(ch.duration_seconds for ch in payload.chapters) != entry.duration_seconds:
        raise HTTPException(status_code=422, detail="Chapter lengths must add up to the planned video duration.")
    store = DbCreativeStudioStore(db)
    assets = {a.id: a for a in store.list_assets(project_id, user.user_id)}
    chapters = []
    for index, ch in enumerate(payload.chapters):
        if len(ch.asset_ids) != len(set(ch.asset_ids)):
            raise HTTPException(status_code=422, detail="Duplicate clip in a chapter.")
        if any(aid not in assets or assets[aid].kind != "video" or not assets[aid].url for aid in ch.asset_ids):
            raise HTTPException(status_code=422, detail="Each chapter must reference clips in this project.")
        chapters.append({
            "index": index, "title": ch.title, "duration_seconds": ch.duration_seconds,
            "revision_note": ch.revision_note,
            "asset_ids": list(ch.asset_ids),
        })
    canonical = json.dumps(chapters)
    if (entry.chapters_json or "[]") != canonical:
        entry.chapters_json = canonical
        if entry.status == "approved":
            entry.status = "ready_for_review"
        entry.updated_at = _now()
        db.commit()
        db.refresh(entry)
    return _as_dict(entry)


class ChapterClipReplacementIn(BaseModel):
    old_asset_id: str = Field(min_length=1, max_length=48)
    new_asset_id: str = Field(min_length=1, max_length=48)


@router.post("/projects/{project_id}/calendar/{entry_id}/chapters/{chapter_index}/replace-clip")
def replace_calendar_chapter_clip(
    project_id: str, entry_id: str, chapter_index: int,
    payload: ChapterClipReplacementIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Explicitly replace ONE clip in a chapter; never alter finished MP4s.

    Replacement must be a completed, verified, review-only assembled scene
    video from the same owner/project. All other chapter clips retain order.
    The entire plan returns for approval before any further assembly.
    """
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status == "canceled":
        raise HTTPException(status_code=409, detail="Canceled plans cannot be modified.")
    chapters = json.loads(entry.chapters_json or "[]")
    if not 0 <= chapter_index < len(chapters):
        raise HTTPException(status_code=404, detail="Chapter not found.")
    old_id, new_id_value = payload.old_asset_id, payload.new_asset_id
    if old_id == new_id_value:
        raise HTTPException(status_code=422, detail="Choose a different replacement clip.")
    selected = chapters[chapter_index]
    existing = list(selected.get("asset_ids") or [])
    if existing.count(old_id) != 1:
        raise HTTPException(status_code=409, detail="The source clip is no longer present exactly once in this chapter.")
    if new_id_value in existing:
        raise HTTPException(status_code=422, detail="The replacement is already in this chapter.")
    store = DbCreativeStudioStore(db)
    assets = {a.id: a for a in store.list_assets(project_id, user.user_id)}
    replacement = assets.get(new_id_value)
    if (replacement is None or replacement.kind != "video" or not replacement.url
            or (replacement.metadata or {}).get("pipeline") != "calendar_assembled_scene_preview"
            or (replacement.metadata or {}).get("publish_ready") is not False):
        raise HTTPException(
            status_code=422,
            detail="Choose a saved review-only assembled storyboard MP4 from this Studio project.",
        )
    # Check current stored file before committing a reference to it.
    from app.core.nova.creative_studio import private_object_storage as remote
    media_sha = str((replacement.metadata or {}).get("sha256") or "")
    if not media_sha:
        raise HTTPException(status_code=409, detail="Replacement MP4 has no verified checksum.")
    service = get_service(db)
    try:
        if str(replacement.url).startswith("private-studio-s3://"):
            valid = remote.enabled() and remote.object_exists(
                replacement.url, user.user_id, project_id, media_sha
            )
        else:
            local_path, media_type, _ = service.open_asset_file(
                user.user_id, project_id, new_id_value
            )
            valid = (media_type == "video/mp4" and local_path.is_file()
                     and hashlib.sha256(local_path.read_bytes()).hexdigest() == media_sha)
    except Exception:
        valid = False
    if not valid:
        raise HTTPException(status_code=409, detail="Replacement MP4 could not be verified.")
    updated = existing.copy()
    updated[updated.index(old_id)] = new_id_value
    selected["asset_ids"] = updated
    entry.chapters_json = json.dumps(chapters)
    if entry.status == "approved":
        entry.status = "ready_for_review"
    entry.updated_at = _now()
    db.commit()
    db.refresh(entry)
    return {
        "status": "REPLACEMENT_SAVED_REVIEW_REQUIRED",
        "chapter_index": chapter_index,
        "replaced_asset_id": old_id,
        "replacement_asset_id": new_id_value,
        "new_chapter_asset_ids": updated,
        "calendar": _as_dict(entry),
        "assembled_chapter_changed": False,
        "originals_preserved": True,
        "published": False,
        "message": "Chapter clip reference updated; approve the chapter plan and rebuild the affected chapter before master export.",
    }


def _chapter_rebuild_plan(db: Session, owner_id: str, project_id: str, entry_id: str) -> dict:
    """Describe current chapter outputs without rendering or billing.

    A matching source list is necessary but not sufficient: the saved MP4
    must also be accessible and checksum-verified before it is reusable.
    """
    from app.core.nova.creative_studio import private_object_storage as remote
    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    chapters = json.loads(entry.chapters_json or "[]")
    store = DbCreativeStudioStore(db)
    service = get_service(db)
    assets = store.list_assets(project_id, owner_id)
    states = []
    for index, chapter in enumerate(chapters):
        matches = [
            asset for asset in assets
            if asset.kind == "video" and bool(asset.url)
            and (asset.metadata or {}).get("pipeline") == "calendar_saved_clip_assembly"
            and (asset.metadata or {}).get("calendar_entry_id") == entry_id
            and (asset.metadata or {}).get("chapter_index") == index
            and (asset.metadata or {}).get("source_asset_ids") == chapter.get("asset_ids", [])
            and abs(float((asset.metadata or {}).get("duration_seconds") or 0)
                    - int(chapter["duration_seconds"])) <= 5
        ]
        verified = None
        for asset in reversed(matches):
            meta = asset.metadata or {}
            digest = str(meta.get("sha256") or "")
            if not digest:
                continue
            try:
                if str(asset.url).startswith("private-studio-s3://"):
                    valid = remote.enabled() and remote.object_exists(
                        asset.url, owner_id, project_id, digest
                    )
                else:
                    local, media_type, _ = service.open_asset_file(
                        owner_id, project_id, asset.id
                    )
                    valid = (
                        media_type == "video/mp4" and local.is_file()
                        and hashlib.sha256(local.read_bytes()).hexdigest() == digest
                    )
                if valid:
                    verified = asset
                    break
            except (CreativeStudioError, OSError, ValueError):
                continue
        states.append({
            "chapter_index": index, "title": chapter.get("title", f"Chapter {index+1}"),
            "status": "REUSABLE" if verified is not None else "NEEDS_REBUILD",
            "asset_id": verified.id if verified is not None else None,
            "asset_sha256": str((verified.metadata or {}).get("sha256") or "") if verified is not None else None,
            "source_clip_count": len(chapter.get("asset_ids") or []),
        })
    missing = [row["chapter_index"] for row in states if row["status"] == "NEEDS_REBUILD"]
    # A version token binds customer confirmation to exact verified chapter
    # assets and current saved plan, not merely chapter counts.
    version = hashlib.sha256(json.dumps({
        "entry_id": entry_id,
        "duration_seconds": entry.duration_seconds,
        "chapters": chapters,
        "verified_assets": [
            {"asset_id": row["asset_id"], "sha256": row["asset_sha256"]}
            for row in states
        ],
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "version_sha256": version,
        "plan_status": entry.status,
        "chapters": states,
        "reusable_chapters": len(states) - len(missing),
        "needs_rebuild_indices": missing,
        "master_ready": entry.status == "approved" and len(states) >= 2 and not missing,
        "published": False, "paid_provider_charges": False,
        "message": (
            "Review and approve the plan before rebuilding chapters."
            if entry.status != "approved"
            else "Rebuild only missing or changed chapters; completed originals remain saved."
        ),
    }


@router.get("/projects/{project_id}/calendar/{entry_id}/chapter-rebuild-plan")
def chapter_rebuild_plan(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return _chapter_rebuild_plan(db, user.user_id, project_id, entry_id)


@router.post("/projects/{project_id}/calendar/{entry_id}/chapters/{chapter_index}/rebuild")
async def rebuild_affected_chapter(
    project_id: str, entry_id: str, chapter_index: int,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Rebuild one changed chapter from its approved, saved clip list.

    This is intentionally a separate explicit user action. Reusing a verified
    existing chapter returns its asset without running FFmpeg.
    """
    plan = _chapter_rebuild_plan(db, user.user_id, project_id, entry_id)
    if plan["plan_status"] != "approved":
        raise HTTPException(status_code=409, detail="Reapprove the revised chapter plan before rebuilding.")
    chapter = next(
        (row for row in plan["chapters"] if row["chapter_index"] == chapter_index), None
    )
    if chapter is None:
        raise HTTPException(status_code=404, detail="Chapter not found.")
    if chapter["status"] == "REUSABLE":
        saved = next(
            (a for a in DbCreativeStudioStore(db).list_assets(project_id, user.user_id)
             if a.id == chapter["asset_id"]), None
        )
        if saved is None:
            raise HTTPException(status_code=409, detail="Verified chapter disappeared; check readiness again.")
        return {**_assembly_result(project_id, saved, reused=True),
                "chapter_index": chapter_index, "remaining": plan["needs_rebuild_indices"]}
    result = await run_in_threadpool(
        _assemble_calendar_video, db, user.user_id, project_id, entry_id,
        [], chapter_index,
    )
    return {**result, "chapter_index": chapter_index,
            "message": "Affected chapter saved for review. Recheck readiness before exporting the master."}


class LongFormAssemblyIn(BaseModel):
    """Ordered video asset IDs already saved in this same owner's Studio project."""
    asset_ids: list[str] = Field(default_factory=list, max_length=16)


def _assemble_calendar_video(db: Session, owner_id: str, project_id: str,
                             entry_id: str, asset_ids: list[str],
                             chapter_index: int | None = None):
    import os
    from app.core.nova.creative_studio import private_object_storage as remote
    from app.core.nova.creative_studio.long_form_assembly import (
        LongFormAssemblyError, assemble_clips,
    )
    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the plan before assembling its video.")
    target_duration = entry.duration_seconds
    if chapter_index is not None:
        chapters = json.loads(entry.chapters_json or "[]")
        if not 0 <= chapter_index < len(chapters):
            raise HTTPException(status_code=404, detail="Chapter not found.")
        chapter = chapters[chapter_index]
        target_duration = int(chapter["duration_seconds"])
        stored_timeline = chapter["asset_ids"]
    else:
        stored_timeline = json.loads(entry.timeline_json or "[]")
    if not 120 <= target_duration <= 600:
        raise HTTPException(status_code=422, detail="The current assembler supports 2–10 minutes per chapter.")
    if not asset_ids:
        asset_ids = stored_timeline
    elif stored_timeline and asset_ids != stored_timeline:
        raise HTTPException(status_code=409, detail="Your saved timeline differs. Save the new order and reapprove before assembling.")
    if not 2 <= len(asset_ids) <= 16 or len(set(asset_ids)) != len(asset_ids):
        raise HTTPException(status_code=422, detail="Choose 2–16 distinct saved video clips.")
    if os.getenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "").lower() in {"1", "true", "yes"} and not remote.enabled():
        raise HTTPException(status_code=503, detail="Durable private video storage is required.")
    service = get_service(db)
    store = DbCreativeStudioStore(db)
    available = {item.id: item for item in store.list_assets(project_id, owner_id)}
    sources = []
    for asset_id in asset_ids:
        asset = available.get(asset_id)
        if asset is None or asset.kind != "video" or not asset.url:
            raise HTTPException(status_code=422, detail="Every segment must be a saved video in your selected Studio project.")
        sources.append(asset)
    signature = hashlib.sha256(
        (entry_id + "|chapter:" + str(chapter_index) + "|" + str(target_duration) + "|" + "|".join(
            f"{a.id}:{(a.metadata or {}).get('sha256', '')}" for a in sources
        )).encode("utf-8")
    ).hexdigest()
    for asset in available.values():
        meta = asset.metadata or {}
        if asset.kind != "video" or meta.get("assembly_signature") != signature:
            continue
        try:
            if str(asset.url).startswith("private-studio-s3://"):
                if remote.enabled() and remote.object_exists(asset.url, owner_id, project_id, meta.get("sha256", "")):
                    return _assembly_result(project_id, asset, reused=True)
            else:
                path, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == meta.get("sha256"):
                    return _assembly_result(project_id, asset, reused=True)
        except Exception:
            pass

    with tempfile.TemporaryDirectory(prefix="nova-calendar-assembly-") as scratch:
        directory = Path(scratch)
        clip_paths = []
        for index, asset in enumerate(sources):
            target = directory / f"clip-{index:02d}.mp4"
            if str(asset.url).startswith("private-studio-s3://"):
                stream, _, _ = service.open_private_remote_asset(owner_id, project_id, asset.id)
                try:
                    with target.open("wb") as handle:
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                            if handle.tell() > 128 * 1024 * 1024:
                                raise HTTPException(status_code=422, detail="Source clip exceeds the size limit.")
                finally:
                    stream.close()
            else:
                path, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                if path.stat().st_size > 128 * 1024 * 1024:
                    raise HTTPException(status_code=422, detail="Source clip exceeds the size limit.")
                import shutil
                shutil.copyfile(path, target)
            clip_paths.append(target)
        output = directory / "long-form.mp4"
        try:
            measured = assemble_clips(clip_paths, output, target_seconds=target_duration)
        except LongFormAssemblyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        try:
            saved = service.import_finished_video(
                owner_id, project_id, output.read_bytes(),
                content_type="video/mp4", max_duration_seconds=600,
            )
        except CreativeStudioError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
        assembled = next(
            (a for a in store.list_assets(project_id, owner_id)
             if a.id == saved["asset"]["id"]), None
        )
        if assembled is None:
            raise HTTPException(status_code=500, detail="Assembled video was not saved.")
        assembled.metadata = {
            **(assembled.metadata or {}),
            "assembly_signature": signature, "calendar_entry_id": entry_id,
            "chapter_index": chapter_index,
            "source_asset_ids": asset_ids, "segment_count": measured["segment_count"],
            "pipeline": "calendar_saved_clip_assembly", "duration_seconds": measured["duration_seconds"],
            "quality_state": "OWNER_REVIEW_REQUIRED", "publish_ready": False,
            "commercial_complete": False, "captions_verified": False,
            "audio_review_required": True, "rights_review_required": True,
            "paid_provider_charges": False, "external_publishing": False,
        }
        assembled = store.save_asset(assembled)
    return _assembly_result(project_id, assembled, reused=False)


def _assembly_result(project_id: str, asset: CreativeAsset, *, reused: bool):
    return {
        "status": "ASSEMBLED_REVIEW_REQUIRED", "asset": asset.as_dict(),
        "download_url": f"/api/nova/creative/projects/{project_id}/assets/{asset.id}/file",
        "reused": reused, "media_generated": True,
        "published": False, "publish_ready": False,
        "message": "Combined saved clips into one MP4. Review audio, captions, visual continuity, rights, and completeness before publishing.",
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/chapters/{chapter_index}/assemble")
async def assemble_calendar_chapter(
    project_id: str, entry_id: str, chapter_index: int,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Build one already-approved chapter from its saved ordered clips.

    The output remains a review-only MP4. Individual chapters can be finished
    separately; this is not a claim that a 2-hour final master can yet be exported.
    """
    return await run_in_threadpool(
        _assemble_calendar_video, db, user.user_id, project_id, entry_id,
        [], chapter_index,
    )


@router.post("/projects/{project_id}/calendar/{entry_id}/assemble")
async def assemble_calendar_video(
    project_id: str, entry_id: str, payload: LongFormAssemblyIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return await run_in_threadpool(
        _assemble_calendar_video, db, user.user_id, project_id, entry_id, payload.asset_ids,
    )


# This bounded in-process worker is for local/staging feature development.
# A durable, distributed queue is required for unattended production long renders.
_calendar_assembly_lock = threading.Lock()
_calendar_assembly_active: set[tuple[str, str, str]] = set()
_calendar_assembly_logger = logging.getLogger(__name__)


def _run_calendar_assembly_job(owner_id: str, project_id: str, entry_id: str,
                               job_id: str, asset_ids: list[str]) -> None:
    key = (owner_id, project_id, entry_id)
    db = SessionLocal()
    try:
        store = DbCreativeStudioStore(db)
        job = next((j for j in store.list_jobs(project_id, owner_id) if j.id == job_id), None)
        if job is None:
            return
        job.status = "RUNNING"
        job.message = "Assembling saved clips; no paid provider calls."
        job.updated_at = _now()
        store.save_job(job)
        try:
            output = _assemble_calendar_video(db, owner_id, project_id, entry_id, asset_ids)
            asset = output["asset"]
            job.status = "GENERATED"
            job.result_asset_ids = [asset["id"]]
            job.message = "Combined MP4 saved. Review video and audio before publishing."
        except Exception as exc:
            db.rollback()
            _calendar_assembly_logger.warning(
                "Studio calendar assembly failed: job=%s error_class=%s",
                job_id, type(exc).__name__,
            )
            job.status = "ERROR"
            job.message = "Assembly could not be completed. Saved source clips were preserved."
        job.updated_at = _now()
        store.save_job(job)
    finally:
        db.close()
        with _calendar_assembly_lock:
            _calendar_assembly_active.discard(key)


@router.post("/projects/{project_id}/calendar/{entry_id}/assemble-job")
def start_calendar_assembly_job(
    project_id: str, entry_id: str, payload: LongFormAssemblyIn,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Start a non-paid background assembly, then poll the persisted Studio job.

    This staging worker is in-process; it does not resume after worker restarts.
    It must not be marketed as a durable distributed long-form queue.
    """
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the timeline before assembling.")
    if not 120 <= entry.duration_seconds <= 600:
        raise HTTPException(status_code=422, detail="Background assembly currently supports 2–10 minutes.")
    order = payload.asset_ids or json.loads(entry.timeline_json or "[]")
    if len(order) < 2 or len(order) > 16 or len(order) != len(set(order)):
        raise HTTPException(status_code=422, detail="Select 2–16 distinct saved clips.")
    saved_order = json.loads(entry.timeline_json or "[]")
    if saved_order and saved_order != order:
        raise HTTPException(status_code=409, detail="Timeline changed; save and reapprove it.")
    assets = {a.id: a for a in DbCreativeStudioStore(db).list_assets(project_id, user.user_id)}
    if any(aid not in assets or assets[aid].kind != "video" or not assets[aid].url for aid in order):
        raise HTTPException(status_code=422, detail="Selected clips must exist in your project.")
    key = (user.user_id, project_id, entry_id)
    with _calendar_assembly_lock:
        if key in _calendar_assembly_active:
            return {"status": "ALREADY_RUNNING", "message": "This calendar plan is already assembling."}
        # Do not launch a duplicate against a persisted queued/running job.
        jobs = DbCreativeStudioStore(db).list_jobs(project_id, user.user_id)
        for previous in jobs:
            if previous.kind == "calendar_assembly:" + entry_id and previous.status in {"QUEUED", "RUNNING"}:
                return {"status": "ALREADY_RUNNING", "job": previous.as_dict(),
                        "message": "An unfinished assembly exists; inspect its status before retrying."}
        _calendar_assembly_active.add(key)
    try:
        now = _now()
        job = GenerationJob(
            id=new_id("cjob"), owner_id=user.user_id, project_id=project_id,
            kind="calendar_assembly:" + entry_id, status="QUEUED",
            message="Queued offline assembly; paid providers are off.",
            # Before completion these IDs are the ordered source clips, so a
            # restart can reconcile any finished output without resubmitting.
            result_asset_ids=list(order),
            created_at=now, updated_at=now,
        )
        saved = DbCreativeStudioStore(db).save_job(job)
        background_tasks.add_task(
            _run_calendar_assembly_job, user.user_id, project_id, entry_id, saved.id, list(order)
        )
        return {
            "status": "QUEUED", "job": saved.as_dict(),
            "poll_url": f"/api/nova/creative/projects/{project_id}/jobs/{saved.id}",
            "publishing_enabled": False, "paid_provider_charges": False,
        }
    except Exception:
        with _calendar_assembly_lock:
            _calendar_assembly_active.discard(key)
        raise


def _reconcile_saved_assembly(db: Session, owner_id: str, project_id: str,
                              entry_id: str, job: GenerationJob) -> bool:
    """Confirm a saved result if the worker stopped after storing the MP4.

    Only a real, accessible owner-scoped output matching the ordered job
    inputs is eligible; no work is submitted or billed during reconciliation.
    """
    from app.core.nova.creative_studio import private_object_storage as remote

    original_order = list(job.result_asset_ids or [])
    if len(original_order) < 2:
        return False
    service = get_service(db)
    store = DbCreativeStudioStore(db)
    candidates = [
        asset for asset in store.list_assets(project_id, owner_id)
        if asset.kind == "video"
        and (asset.metadata or {}).get("pipeline") == "calendar_saved_clip_assembly"
        and (asset.metadata or {}).get("calendar_entry_id") == entry_id
        and (asset.metadata or {}).get("source_asset_ids") == original_order
        and asset.created_at >= job.created_at
    ]
    for asset in reversed(candidates):
        digest = str((asset.metadata or {}).get("sha256") or "")
        if not digest:
            continue
        try:
            if str(asset.url or "").startswith("private-studio-s3://"):
                confirmed = remote.enabled() and remote.object_exists(
                    asset.url, owner_id, project_id, digest
                )
            else:
                path, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                confirmed = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest
        except Exception:
            confirmed = False
        if confirmed:
            job.status = "GENERATED"
            job.result_asset_ids = [asset.id]
            job.message = "Recovered verified assembled MP4 after interrupted job status update; owner review required."
            job.updated_at = _now()
            store.save_job(job)
            return True
    return False


@router.get("/projects/{project_id}/calendar/{entry_id}/assembly-status")
def calendar_assembly_status(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return the latest durable assembly record without creating work or charges."""
    _project(db, user.user_id, project_id)
    _entry(db, user.user_id, project_id, entry_id)
    jobs = DbCreativeStudioStore(db).list_jobs(project_id, user.user_id)
    latest = next((job for job in jobs if job.kind == "calendar_assembly:" + entry_id), None)
    if latest is None:
        return {"status": "NOT_STARTED", "job": None}
    key = (user.user_id, project_id, entry_id)
    with _calendar_assembly_lock:
        running_here = key in _calendar_assembly_active
    if latest.status in {"QUEUED", "RUNNING"} and not running_here:
        if _reconcile_saved_assembly(db, user.user_id, project_id, entry_id, latest):
            return {
                "status": "GENERATED", "job": latest.as_dict(),
                "message": "Verified saved MP4 recovered. Review and download it in Studio.",
            }
        return {
            "status": "INTERRUPTED_UNCONFIRMED", "job": latest.as_dict(),
            "message": (
                "This process has no active worker. Another worker may still be processing, "
                "or the render may have been interrupted. No work was restarted and no "
                "completion was claimed without a verified output."
            ),
        }
    return {"status": latest.status, "job": latest.as_dict()}



def _master_export_limit_seconds() -> int:
    """Extended long-form exports are opt-in; default remains one hour."""
    import os
    return (7200 if os.getenv("NOVA_STUDIO_EXTENDED_MASTER_EXPORTS", "").lower()
            in {"1", "true", "yes"} else 3600)


def _assemble_chapter_master(db: Session, owner_id: str, project_id: str, entry_id: str,
                             checkpoint=None, pinned=None):
    """Combine verified chapter assets into one private 10–60m master."""
    import os
    import shutil
    from app.core.nova.creative_studio import private_object_storage as remote
    from app.core.nova.creative_studio.chapter_master import ChapterMasterError
    from app.core.nova.creative_studio.resumable_master import (
        normalize_chapter, join_normalized_chapters,
    )

    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if not isinstance(pinned, dict) or not isinstance(pinned.get("chapters"), list):
        raise HTTPException(status_code=409, detail="Export has no approved pinned chapter selection.")
    pinned_duration = pinned.get("duration_seconds")
    if type(pinned_duration) is not int:
        raise HTTPException(status_code=409, detail="Pinned duration is invalid.")
    if not 600 <= pinned_duration <= _master_export_limit_seconds():
        raise HTTPException(status_code=422, detail="Master export duration exceeds the configured 10–60 or 10–120 minute limit.")
    if not remote.enabled():
        raise HTTPException(status_code=503, detail="Private durable object storage is required for long-form masters.")
    # Extended export needs enough scratch space for all downloaded chapters
    # plus the joined master; never start a large job without headroom.
    if pinned_duration > 3600:
        import shutil
        if shutil.disk_usage(tempfile.gettempdir()).free < 4 * 1024 * 1024 * 1024:
            raise HTTPException(status_code=503, detail="Insufficient scratch disk for extended video export.")
    chapters = pinned["chapters"]
    if not 2 <= len(chapters) <= 24 or any(
            row.get("chapter_index") != i or not isinstance(row.get("asset_id"), str)
            or not isinstance(row.get("sha256"), str) or len(row["sha256"]) != 64
            for i, row in enumerate(chapters)):
        raise HTTPException(status_code=409, detail="Pinned chapter selection is invalid.")
    store = DbCreativeStudioStore(db)
    assets = store.list_assets(project_id, owner_id)
    if checkpoint is not None:
        checkpoint("VERIFYING_CHAPTERS", {"chapter_count": len(chapters)})
    selected = []
    for index, chapter in enumerate(chapters):
        matches = [asset for asset in assets
                   if asset.id == chapter["asset_id"] and asset.kind == "video"
                   and (asset.metadata or {}).get("pipeline") == "calendar_saved_clip_assembly"
                   and (asset.metadata or {}).get("calendar_entry_id") == entry_id
                   and (asset.metadata or {}).get("chapter_index") == index
                   and (asset.metadata or {}).get("sha256") == chapter["sha256"]]
        if len(matches) != 1:
            raise HTTPException(status_code=409, detail=f"Pinned chapter {index + 1} changed or is missing.")
        selected.append(matches[0])
    signature = hashlib.sha256(
        (entry_id + "|" + str(pinned_duration) + "|" +
         "|".join(f"{a.id}:{(a.metadata or {}).get('sha256','')}" for a in selected)).encode("utf-8")
    ).hexdigest()
    for asset in assets:
        meta = asset.metadata or {}
        if (meta.get("pipeline") == "calendar_chapter_master" and
                meta.get("master_signature") == signature and
                str(asset.url or "").startswith("private-studio-s3://")):
            try:
                if remote.object_exists(asset.url, owner_id, project_id, str(meta.get("sha256") or "")):
                    return _master_result(project_id, asset, reused=True)
            except Exception:
                pass
    service = get_service(db)
    with tempfile.TemporaryDirectory(prefix="nova-master-") as scratch:
        root = Path(scratch)
        files = []
        for index, asset in enumerate(selected):
            output = root / f"chapter-{index:02d}.mp4"
            ref = str(asset.url or "")
            if ref.startswith("private-studio-s3://"):
                stream, _, _ = service.open_private_remote_asset(owner_id, project_id, asset.id)
                try:
                    with output.open("wb") as handle:
                        while True:
                            chunk = stream.read(1024 * 1024)
                            if not chunk:
                                break
                            handle.write(chunk)
                            if handle.tell() > 128 * 1024 * 1024:
                                raise HTTPException(status_code=422, detail="Chapter exceeds 128 MiB.")
                finally:
                    stream.close()
            else:
                source, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                if source.stat().st_size > 128 * 1024 * 1024:
                    raise HTTPException(status_code=422, detail="Chapter exceeds 128 MiB.")
                shutil.copyfile(source, output)
            digest = str((asset.metadata or {}).get("sha256") or "")
            if not digest or hashlib.sha256(output.read_bytes()).hexdigest() != digest:
                raise HTTPException(status_code=422, detail="Chapter checksum verification failed.")
            files.append(output)
        # Normalize chapters independently. Persist only verified canonical
        # segments; after an interruption, already finished segments are reused.
        normalized_files = []
        for index, (source, chapter_asset) in enumerate(zip(files, selected)):
            source_sha = str((chapter_asset.metadata or {}).get("sha256") or "")
            segment_signature = hashlib.sha256(
                (entry_id + "|normalized-v1|" + str(index) + "|" +
                 chapter_asset.id + "|" + source_sha).encode("utf-8")
            ).hexdigest()
            normalized_path = root / f"normalized-{index:02d}.mp4"
            reusable = next((
                candidate for candidate in store.list_assets(project_id, owner_id)
                if candidate.kind == "video"
                and (candidate.metadata or {}).get("pipeline") == "chapter_normalized_checkpoint"
                and (candidate.metadata or {}).get("segment_signature") == segment_signature
                and str(candidate.url or "").startswith("private-studio-s3://")
            ), None)
            reused_segment = False
            if reusable is not None:
                reusable_sha = str((reusable.metadata or {}).get("sha256") or "")
                try:
                    if reusable_sha and remote.object_exists(
                            reusable.url, owner_id, project_id, reusable_sha):
                        stream, _, _ = service.open_private_remote_asset(
                            owner_id, project_id, reusable.id
                        )
                        try:
                            with normalized_path.open("wb") as handle:
                                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                    handle.write(chunk)
                                    if handle.tell() > 128 * 1024 * 1024:
                                        raise ValueError("Checkpoint is oversized")
                        finally:
                            stream.close()
                        if hashlib.sha256(normalized_path.read_bytes()).hexdigest() == reusable_sha:
                            reused_segment = True
                except Exception:
                    reused_segment = False
                    normalized_path.unlink(missing_ok=True)
            if not reused_segment:
                try:
                    normalize_chapter(source, normalized_path)
                except ChapterMasterError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                normalized_sha = hashlib.sha256(normalized_path.read_bytes()).hexdigest()
                normalized_filename = new_id("imported_video") + ".mp4"
                try:
                    segment_ref = remote.put_original_file(
                        owner_id, project_id, normalized_filename, normalized_path,
                        normalized_sha, max_bytes=128 * 1024 * 1024,
                    )
                except Exception as exc:
                    raise HTTPException(
                        status_code=503, detail="Could not preserve chapter checkpoint."
                    ) from exc
                try:
                    store.save_asset(CreativeAsset(
                        id=new_id("casset"), owner_id=owner_id, project_id=project_id,
                        kind="video", title=f"Master checkpoint chapter {index + 1}",
                        content="Private normalized segment for recoverable assembly.",
                        status="GENERATED", url=segment_ref,
                        metadata={
                            "pipeline": "chapter_normalized_checkpoint",
                            "calendar_entry_id": entry_id,
                            "chapter_index": index,
                            "source_asset_id": chapter_asset.id,
                            "source_sha256": source_sha,
                            "segment_signature": segment_signature,
                            "sha256": normalized_sha,
                            "quality_state": "INTERNAL_CHECKPOINT",
                            "publish_ready": False,
                        },
                    ))
                except Exception:
                    remote.delete_original(segment_ref, owner_id, project_id)
                    raise
            normalized_files.append(normalized_path)
            if checkpoint is not None:
                checkpoint("RENDERING_MASTER", {
                    "completed_segments": len(normalized_files),
                    "total_segments": len(files),
                })
        output = root / "finished-master.mp4"
        try:
            measured = join_normalized_chapters(
                normalized_files, output, expected_seconds=pinned_duration
            )
        except (ChapterMasterError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        digest = hashlib.sha256()
        with output.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        if checkpoint is not None:
            checkpoint("UPLOADING_MASTER", {"master_sha256": sha, "bytes": output.stat().st_size})
        filename = new_id("imported_video") + ".mp4"
        try:
            ref = remote.put_original_file(
                owner_id, project_id, filename, output, sha,
                max_bytes=(2 * 1024 * 1024 * 1024 if pinned_duration > 3600
                           else 512 * 1024 * 1024),
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Long-form private storage unavailable; no video registered.") from exc
        try:
            asset = store.save_asset(CreativeAsset(
                id=new_id("casset"), owner_id=owner_id, project_id=project_id,
                kind="video", title="Completed chapter master — owner review",
                content="Assembled from existing saved chapters; no paid media generation.",
                status="GENERATED", url=ref,
                metadata={
                    "source": "chapter_master", "pipeline": "calendar_chapter_master",
                    "calendar_entry_id": entry_id, "master_signature": signature,
                    "pinned_version_sha256": pinned.get("version_sha256"),
                    "source_asset_ids": [a.id for a in selected], "sha256": sha,
                    "file_size_bytes": output.stat().st_size,
                    **measured, "quality_state": "OWNER_REVIEW_REQUIRED",
                    "commercial_complete": False, "publish_ready": False,
                    "captions_verified": False, "rights_review_required": True,
                    "paid_provider_charges": False,
                },
            ))
        except Exception:
            remote.delete_original(ref, owner_id, project_id)
            raise
    if checkpoint is not None:
        checkpoint("SAVED_MASTER", {"asset_id": asset.id, "master_sha256": sha})
    return _master_result(project_id, asset, reused=False)


def _master_result(project_id: str, asset: CreativeAsset, *, reused: bool):
    return {
        "status": "MASTER_SAVED_REVIEW_REQUIRED", "asset": asset.as_dict(),
        "download_url": f"/api/nova/creative/projects/{project_id}/assets/{asset.id}/file",
        "reused": reused, "published": False, "publish_ready": False,
        "message": "Combined chapter master saved privately. Review footage, captions, audio continuity, rights and completeness.",
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/export-master")
async def export_calendar_master(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Legacy synchronous route intentionally closed: use pinned saved jobs."""
    raise HTTPException(
        status_code=409,
        detail="Use the version-confirmed Update Final Master workflow. Unpinned synchronous exports are disabled.",
    )


def _master_claim_key(owner_id: str, project_id: str, entry_id: str) -> str:
    return hashlib.sha256(
        (owner_id + ":" + project_id + ":" + entry_id).encode("utf-8")
    ).hexdigest()


def _claim_queued_master(db: Session, owner_id: str, project_id: str,
                         entry_id: str, job_id: str) -> bool:
    """Atomic SQL compare-and-swap: exactly one process can run a queued export.

    An interrupted RUNNING export is intentionally not retried automatically.
    """
    key = _master_claim_key(owner_id, project_id, entry_id)
    updated = db.execute(
        update(NovaCreativeRenderClaim)
        .where(
            NovaCreativeRenderClaim.claim_key == key,
            NovaCreativeRenderClaim.owner_id == owner_id,
            NovaCreativeRenderClaim.project_id == project_id,
            NovaCreativeRenderClaim.entry_id == entry_id,
            NovaCreativeRenderClaim.job_id == job_id,
            NovaCreativeRenderClaim.state == "QUEUED",
        )
        .values(state="RUNNING", updated_at=_now())
    )
    db.commit()
    return updated.rowcount == 1


def _write_master_checkpoint(owner_id: str, project_id: str,
                             entry_id: str, job_id: str, stage: str,
                             details: dict | None = None) -> None:
    """Record verified processing stage for the exact active SQL claim."""
    if stage not in {"VERIFYING_CHAPTERS", "RENDERING_MASTER",
                     "UPLOADING_MASTER", "SAVED_MASTER"}:
        raise ValueError("Invalid checkpoint stage")
    db = SessionLocal()
    try:
        current = db.get(NovaCreativeRenderClaim, _master_claim_key(owner_id, project_id, entry_id))
        if current is None or current.job_id != job_id or current.state != "RUNNING":
            raise RuntimeError("Master claim is no longer active")
        saved = json.loads(current.checkpoint_json or "{}")
        pinned = saved.get("pinned_master")
        if not isinstance(pinned, dict):
            raise RuntimeError("Export has no pinned approved chapter snapshot")
        updated = db.execute(
            update(NovaCreativeRenderClaim)
            .where(
                NovaCreativeRenderClaim.claim_key == _master_claim_key(owner_id, project_id, entry_id),
                NovaCreativeRenderClaim.job_id == job_id,
                NovaCreativeRenderClaim.state == "RUNNING",
            )
            .values(
                checkpoint_json=json.dumps({
                    "pinned_master": pinned,
                    "stage": stage, "details": details or {}, "updated_at": _now(),
                }, sort_keys=True),
                updated_at=_now(),
            )
        )
        db.commit()
        if updated.rowcount != 1:
            raise RuntimeError("Render claim is no longer active")
    finally:
        db.close()


def _heartbeat_master_claim(owner_id: str, project_id: str, entry_id: str,
                            job_id: str, stop: threading.Event) -> None:
    """Refresh this specific RUNNING SQL claim while FFmpeg is processing.

    A separate SQL session avoids sharing a session across threads. The
    heartbeat never renews a different job or a terminal claim.
    """
    claim_key = _master_claim_key(owner_id, project_id, entry_id)
    while not stop.wait(20):
        db = SessionLocal()
        try:
            result = db.execute(
                update(NovaCreativeRenderClaim)
                .where(
                    NovaCreativeRenderClaim.claim_key == claim_key,
                    NovaCreativeRenderClaim.owner_id == owner_id,
                    NovaCreativeRenderClaim.project_id == project_id,
                    NovaCreativeRenderClaim.entry_id == entry_id,
                    NovaCreativeRenderClaim.job_id == job_id,
                    NovaCreativeRenderClaim.state == "RUNNING",
                )
                .values(updated_at=_now())
            )
            db.commit()
            if result.rowcount != 1:
                return
        except Exception:
            db.rollback()
            _calendar_assembly_logger.warning(
                "Creative Studio master heartbeat could not be persisted job=%s",
                job_id,
            )
        finally:
            db.close()


def _finish_master_claim(db: Session, owner_id: str, project_id: str,
                         entry_id: str, job_id: str, state: str) -> None:
    claim = db.get(NovaCreativeRenderClaim, _master_claim_key(owner_id, project_id, entry_id))
    if claim is not None and claim.job_id == job_id:
        claim.state = state
        claim.updated_at = _now()
        db.commit()


# The master-export worker runs only within this application process. Records
# remain in SQL; actual restart-resumable queues are a later production gate.
_master_export_lock = threading.Lock()
_master_export_active: set[tuple[str, str, str]] = set()


def _run_chapter_master_job(owner_id: str, project_id: str,
                            entry_id: str, job_id: str) -> None:
    key = (owner_id, project_id, entry_id)
    db = SessionLocal()
    heartbeat_stop = threading.Event()
    heartbeat_thread: threading.Thread | None = None
    try:
        store = DbCreativeStudioStore(db)
        job = next((row for row in store.list_jobs(project_id, owner_id)
                    if row.id == job_id), None)
        if job is None or job.status != "QUEUED":
            return
        if not _claim_queued_master(db, owner_id, project_id, entry_id, job_id):
            # Another process already claimed this work, or it was canceled.
            return
        claim = db.get(NovaCreativeRenderClaim, _master_claim_key(owner_id, project_id, entry_id))
        saved = json.loads(claim.checkpoint_json or "{}") if claim and claim.job_id == job_id else {}
        pinned = saved.get("pinned_master")
        if not isinstance(pinned, dict):
            # Let the normal job failure handler mark this claim ERROR instead
            # of abandoning a RUNNING claim outside the guarded try/except.
            pinned = {}
        job.status = "RUNNING"
        job.message = "Combining pinned approved chapters into a private MP4."
        job.updated_at = _now()
        store.save_job(job)
        heartbeat_thread = threading.Thread(
            target=_heartbeat_master_claim,
            args=(owner_id, project_id, entry_id, job_id, heartbeat_stop),
            name="nova-master-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = _assemble_chapter_master(
                db, owner_id, project_id, entry_id, pinned=pinned,
                checkpoint=lambda stage, details: _write_master_checkpoint(
                    owner_id, project_id, entry_id, job_id, stage, details
                ),
            )
            job.status = "GENERATED"
            job.result_asset_ids = [result["asset"]["id"]]
            job.message = "Finished chapter master saved. Owner review is required."
        except Exception as exc:
            db.rollback()
            _calendar_assembly_logger.warning(
                "Studio chapter master failed job=%s error_class=%s",
                job_id, type(exc).__name__,
            )
            job.status = "ERROR"
            job.message = "Master export could not finish. Existing chapters remain saved."
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=5)
        job.updated_at = _now()
        store.save_job(job)
        _finish_master_claim(db, owner_id, project_id, entry_id, job_id, job.status)
    finally:
        heartbeat_stop.set()
        db.close()
        with _master_export_lock:
            _master_export_active.discard(key)


def _master_job_status(db: Session, owner_id: str,
                       project_id: str, entry_id: str) -> dict:
    from app.core.nova.creative_studio import private_object_storage as remote
    store = DbCreativeStudioStore(db)
    latest = next((job for job in store.list_jobs(project_id, owner_id)
                   if job.kind == "calendar_master:" + entry_id), None)
    if latest is None:
        return {"status": "NOT_STARTED", "job": None}
    key = (owner_id, project_id, entry_id)
    with _master_export_lock:
        locally_running = key in _master_export_active
    claim = db.get(NovaCreativeRenderClaim, _master_claim_key(owner_id, project_id, entry_id))
    checkpoint = (json.loads(claim.checkpoint_json or "{}")
                  if claim is not None and claim.job_id == latest.id else {})
    if latest.status == "GENERATED":
        return {"status": latest.status, "job": latest.as_dict(), "checkpoint": checkpoint}
    if latest.status not in {"QUEUED", "RUNNING", "ERROR"}:
        return {"status": latest.status, "job": latest.as_dict(), "checkpoint": checkpoint}
    if locally_running and latest.status in {"QUEUED", "RUNNING"}:
        return {"status": latest.status, "job": latest.as_dict(), "checkpoint": checkpoint}
    # With an external worker the web process cannot observe its local lock.
    # Only declare interrupted after a conservative lease grace period, never
    # claim completion without a remotely verified master.
    if claim is not None and claim.job_id == latest.id and claim.state in {"QUEUED", "RUNNING"}:
        from datetime import timedelta
        try:
            since = datetime.fromisoformat(claim.updated_at)
            if since.tzinfo is None:
                since = since.replace(tzinfo=timezone.utc)
            elapsed = datetime.now(timezone.utc) - since
            # Worker refreshes RUNNING claims every 20 seconds. Allow an
            # outage buffer but avoid labeling a dead worker as active for 75m.
            grace = timedelta(minutes=3 if claim.state == "RUNNING" else 5)
            if elapsed <= grace:
                return {"status": claim.state, "job": latest.as_dict(),
                        "message": "The export is queued or claimed by a render worker.",
                        "checkpoint": checkpoint}
        except (ValueError, TypeError):
            pass

    # Recover only an asset produced for this exact pinned job version;
    # older masters for the same entry must not be accepted as this result.
    expected_version = (checkpoint.get("pinned_master") or {}).get("version_sha256")
    # Legacy jobs without a pinned selection are unconfirmed, not recoverable.
    if not isinstance(expected_version, str) or len(expected_version) != 64:
        return {"status": "INTERRUPTED_UNCONFIRMED", "job": latest.as_dict(),
                "checkpoint": checkpoint,
                "message": "No approved chapter snapshot is attached to this job."}
    candidates = [
        asset for asset in store.list_assets(project_id, owner_id)
        if asset.kind == "video"
        and (asset.metadata or {}).get("pipeline") == "calendar_chapter_master"
        and (asset.metadata or {}).get("calendar_entry_id") == entry_id
        and (asset.metadata or {}).get("pinned_version_sha256") == expected_version
        and asset.created_at >= latest.created_at
        and str(asset.url or "").startswith("private-studio-s3://")
    ]
    for asset in reversed(candidates):
        digest = (asset.metadata or {}).get("sha256") or ""
        try:
            verified = bool(digest) and remote.enabled() and remote.object_exists(
                asset.url, owner_id, project_id, digest
            )
        except Exception:
            verified = False
        if verified:
            latest.status = "GENERATED"
            latest.result_asset_ids = [asset.id]
            latest.message = "Verified saved master recovered after interrupted job update."
            latest.updated_at = _now()
            store.save_job(latest)
            if claim is not None and claim.job_id == latest.id:
                claim.state = "GENERATED"
                claim.updated_at = _now()
                db.commit()
            return {"status": "GENERATED", "job": latest.as_dict(),
                    "checkpoint": checkpoint,
                    "message": "A previously completed private master was verified and recovered."}
    if latest.status == "ERROR":
        return {
            "status": "ERROR", "job": latest.as_dict(),
            "checkpoint": checkpoint, "resumable": bool(
                claim is not None and claim.job_id == latest.id and claim.state == "ERROR"
            ),
            "message": "The export failed. Verified saved chapters and normalized checkpoints can be reused with an explicit resume.",
        }
    return {
        "status": "INTERRUPTED_UNCONFIRMED", "job": latest.as_dict(),
        "checkpoint": checkpoint,
        "message": "No active worker was found here; another worker may still be running. "
                   "No new render was submitted or charged.",
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/export-master-job")
def start_chapter_master_job(
    project_id: str, entry_id: str, background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Queue owner-controlled local master export without holding the browser open."""
    from app.core.nova.creative_studio import private_object_storage as remote
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve all chapters first.")
    if not 600 <= entry.duration_seconds <= _master_export_limit_seconds():
        raise HTTPException(status_code=422, detail="Master export exceeds the configured 60 or 120 minute limit.")
    if not remote.enabled():
        raise HTTPException(status_code=503, detail="Private durable storage is required.")
    chapters = json.loads(entry.chapters_json or "[]")
    if not 2 <= len(chapters) <= 24:
        raise HTTPException(status_code=422, detail="Save 2–24 completed chapters first.")
    readiness = _chapter_rebuild_plan(db, user.user_id, project_id, entry_id)
    if not readiness["master_ready"]:
        raise HTTPException(status_code=409, detail={
            "message": "Master export blocked: rebuild or verify the current chapter MP4s first.",
            "needs_rebuild_indices": readiness["needs_rebuild_indices"],
        })
    key = (user.user_id, project_id, entry_id)
    with _master_export_lock:
        if key in _master_export_active:
            return {"status": "ALREADY_RUNNING",
                    "message": "This project's master export is already running."}
        latest = next(
            (j for j in DbCreativeStudioStore(db).list_jobs(project_id, user.user_id)
             if j.kind == "calendar_master:" + entry_id),
            None,
        )
        if latest is not None and latest.status in {"QUEUED", "RUNNING"}:
            return {"status": "ALREADY_RUNNING", "job": latest.as_dict(),
                    "message": "Check the saved master job before submitting again."}
        _master_export_active.add(key)
    try:
        now = _now()
        fresh_id = new_id("cjob")
        claim_key = _master_claim_key(user.user_id, project_id, entry_id)
        claim = db.get(NovaCreativeRenderClaim, claim_key)
        if claim is not None and claim.state in {"QUEUED", "RUNNING"}:
            with _master_export_lock:
                _master_export_active.discard(key)
            return {"status": "ALREADY_RUNNING",
                    "message": "The database already has an active export claim."}
        pinned = {
            "version_sha256": readiness["version_sha256"],
            "duration_seconds": entry.duration_seconds,
            "chapters": [{
                "chapter_index": row["chapter_index"],
                "asset_id": row["asset_id"],
                "sha256": row["asset_sha256"],
            } for row in readiness["chapters"]],
        }
        snapshot = json.dumps({"pinned_master": pinned, "stage": "QUEUED"}, sort_keys=True)
        if claim is None:
            db.add(NovaCreativeRenderClaim(
                claim_key=claim_key, owner_id=user.user_id, project_id=project_id,
                entry_id=entry_id, job_id=fresh_id, state="QUEUED", updated_at=now,
                checkpoint_json=snapshot,
            ))
        else:
            # Reclaim only a terminal state; never silently restart a stuck job.
            claim.job_id = fresh_id
            claim.checkpoint_json = snapshot
            claim.state = "QUEUED"
            claim.updated_at = now
        try:
            db.flush()
            job = DbCreativeStudioStore(db).save_job(GenerationJob(
                id=fresh_id, owner_id=user.user_id, project_id=project_id,
                kind="calendar_master:" + entry_id, status="QUEUED",
                message="Queued local master export with no paid-provider calls.",
                created_at=now, updated_at=now,
            ))
        except IntegrityError:
            db.rollback()
            with _master_export_lock:
                _master_export_active.discard(key)
            return {"status": "ALREADY_RUNNING",
                    "message": "Another worker claimed this export."}
        # When a dedicated worker is enabled, the committed SQL claim is its
        # queue; the web process must not execute a second in-process task.
        import os
        dedicated = os.getenv("NOVA_STUDIO_MASTER_WORKER_ENABLED", "").lower() in {"1", "true", "yes"}
        if not dedicated:
            background_tasks.add_task(
                _run_chapter_master_job, user.user_id, project_id, entry_id, job.id
            )
        return {
            "status": "QUEUED", "job": job.as_dict(),
            "status_url": f"/api/nova/creative/projects/{project_id}/calendar/{entry_id}/master-status",
            "paid_provider_charges": False, "publishing_enabled": False,
        }
    except Exception:
        with _master_export_lock:
            _master_export_active.discard(key)
        raise


class ConfirmedMasterUpdateIn(BaseModel):
    version_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    confirm_rebuild: bool = False


class MasterReviewIn(BaseModel):
    footage_ok: bool
    audio_ok: bool
    captions_ok: bool
    continuity_ok: bool
    rights_reviewed: bool
    notes: str = Field(default="", max_length=2000)
    correction_chapter_index: int | None = Field(default=None, ge=0, le=23)
    correction_category: Literal["footage", "audio", "captions", "continuity", "rights", "general"] = "general"


def _verified_master_assets(db: Session, owner_id: str, project_id: str,
                            entry_id: str) -> list[CreativeAsset]:
    """Find only fully persisted private masters owned by this account."""
    from app.core.nova.creative_studio import private_object_storage as remote
    store = DbCreativeStudioStore(db)
    verified = []
    for asset in reversed(store.list_assets(project_id, owner_id)):
        meta = asset.metadata or {}
        digest = str(meta.get("sha256") or "")
        if (asset.kind != "video" or meta.get("pipeline") != "calendar_chapter_master"
                or meta.get("calendar_entry_id") != entry_id
                or not str(asset.url or "").startswith("private-studio-s3://")
                or len(digest) != 64):
            continue
        try:
            if remote.enabled() and remote.object_exists(asset.url, owner_id, project_id, digest):
                verified.append(asset)
        except Exception:
            continue
    return verified


@router.get("/projects/{project_id}/calendar/{entry_id}/master-versions")
def get_master_versions(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    _entry(db, user.user_id, project_id, entry_id)
    masters = _verified_master_assets(db, user.user_id, project_id, entry_id)
    return {
        "masters": [{
            "asset_id": asset.id,
            "created_at": asset.created_at,
            "file_sha256": (asset.metadata or {}).get("sha256"),
            "file_size_bytes": (asset.metadata or {}).get("file_size_bytes"),
            "pinned_version_sha256": (asset.metadata or {}).get("pinned_version_sha256"),
            "duration_seconds": (asset.metadata or {}).get("duration_seconds"),
            "review": (asset.metadata or {}).get("master_quality_review"),
            "chapter_count": len((asset.metadata or {}).get("source_asset_ids") or []),
            "download_url": f"/api/nova/creative/projects/{project_id}/assets/{asset.id}/file",
            "commercial_complete": False, "publish_ready": False,
        } for asset in masters[:30]],
        "published": False,
        "message": "Verified saved master versions. Quality review does not grant commercial rights or publishing permission.",
    }


@router.put("/projects/{project_id}/calendar/{entry_id}/masters/{asset_id}/review")
def review_master_version(
    project_id: str, entry_id: str, asset_id: str, payload: MasterReviewIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Save an owner quality review for the exact verified master MP4."""
    _project(db, user.user_id, project_id)
    _entry(db, user.user_id, project_id, entry_id)
    master = next((item for item in _verified_master_assets(
        db, user.user_id, project_id, entry_id) if item.id == asset_id), None)
    if master is None:
        raise HTTPException(status_code=404, detail="The private master is missing or unverified.")
    source_ids = (master.metadata or {}).get("source_asset_ids") or []
    if payload.correction_chapter_index is not None and not (
            0 <= payload.correction_chapter_index < len(source_ids)):
        raise HTTPException(status_code=422, detail="The affected chapter does not exist in this saved master.")
    checks = [
        payload.footage_ok, payload.audio_ok, payload.captions_ok,
        payload.continuity_ok, payload.rights_reviewed,
    ]
    status = "REVIEW_PASSED" if all(checks) else "CHANGES_REQUIRED"
    review = {
        "status": status,
        "correction_chapter_index": payload.correction_chapter_index,
        "correction_category": payload.correction_category,
        "source_chapter_asset_id": (source_ids[payload.correction_chapter_index]
            if payload.correction_chapter_index is not None else None),
        "footage_ok": payload.footage_ok,
        "audio_ok": payload.audio_ok,
        "captions_ok": payload.captions_ok,
        "continuity_ok": payload.continuity_ok,
        "rights_reviewed": payload.rights_reviewed,
        "notes": payload.notes.strip(),
        "reviewed_by": user.user_id,
        "reviewed_at": _now(),
        "file_sha256": (master.metadata or {}).get("sha256"),
    }
    master.metadata = {
        **(master.metadata or {}),
        "master_quality_review": review,
        "quality_state": "MASTER_REVIEW_PASSED" if all(checks)
                         else "MASTER_CHANGES_REQUIRED",
        "commercial_complete": False,
        "publish_ready": False,
        "external_publishing": False,
    }
    DbCreativeStudioStore(db).save_asset(master)
    return {
        "status": status, "asset_id": asset_id, "review": review,
        "published": False, "publish_ready": False,
        "message": "Quality review saved for this exact MP4. Publishing and commercial clearance remain separate.",
    }




@router.get("/projects/{project_id}/calendar/{entry_id}/masters/{asset_id}/correction-plan")
def master_chapter_correction_plan(
    project_id: str, entry_id: str, asset_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Match saved master feedback to its historical chapter, not a guessed current one."""
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    master = next((a for a in _verified_master_assets(
        db, user.user_id, project_id, entry_id) if a.id == asset_id), None)
    if master is None:
        raise HTTPException(status_code=404, detail="Verified saved master not found.")
    review = (master.metadata or {}).get("master_quality_review") or {}
    if review.get("status") != "CHANGES_REQUIRED":
        raise HTTPException(status_code=409, detail="Save a changes-required review of this master first.")
    index = review.get("correction_chapter_index")
    source_ids = (master.metadata or {}).get("source_asset_ids") or []
    if type(index) is not int or index < 0 or index >= len(source_ids):
        raise HTTPException(status_code=422, detail="Choose an affected chapter in this master's quality review.")
    chapters = json.loads(entry.chapters_json or "[]")
    current_chapter = chapters[index] if index < len(chapters) else None
    original_id = source_ids[index]
    # Current plan's chapter asset must still resolve to the exact MP4 from
    # the reviewed master before we claim the historical chapter matches.
    readiness = _chapter_rebuild_plan(db, user.user_id, project_id, entry_id)
    now = next((row for row in readiness["chapters"]
                if row["chapter_index"] == index), None)
    same_output = bool(now and now["asset_id"] == original_id)
    return {
        "status": "CORRECTION_BRIEF",
        "source_master_asset_id": asset_id,
        "source_master_sha256": (master.metadata or {}).get("sha256"),
        "historical_chapter_asset_id": original_id,
        "chapter_index": index,
        "correction_category": review.get("correction_category", "general"),
        "notes": review.get("notes") or "",
        "current_chapter": current_chapter,
        "current_plan_matches_reviewed_chapter": same_output,
        "current_plan_status": entry.status,
        "can_open_current_editor": current_chapter is not None,
        "saved": False, "rendered": False, "published": False,
        "message": ("The current chapter matches this master. Review edits in the chapter editor."
                    if same_output else
                    "The current chapter is different from the reviewed master. Compare before editing; no changes were applied."),
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/masters/{asset_id}/assistant/chapter-revision-proposal")
def propose_master_chapter_revision(
    project_id: str, entry_id: str, asset_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """No-cost correction brief, preserving every saved chapter and source clip."""
    plan = master_chapter_correction_plan(
        project_id, entry_id, asset_id, user=user, db=db
    )
    if not plan["current_plan_matches_reviewed_chapter"]:
        raise HTTPException(
            status_code=409,
            detail="The current chapter differs from the reviewed master. Compare versions before suggesting edits.",
        )
    notes = str(plan["notes"] or "").strip()
    if not notes:
        raise HTTPException(
            status_code=422,
            detail="Add specific correction notes in the saved master review first.",
        )
    category = plan["correction_category"]
    if category not in {"footage", "audio", "captions", "continuity", "rights", "general"}:
        category = "general"
    chapter = dict(plan["current_chapter"])
    index = plan["chapter_index"]
    summary = (f"Review of master {asset_id}, chapter {index + 1} "
               f"({category}): {notes}")[:2000]
    chapter["revision_note"] = summary
    return {
        "status": "DRAFT_CHAPTER_REVISION",
        "chapter_index": index,
        "source_master_asset_id": asset_id,
        "historical_chapter_asset_id": plan["historical_chapter_asset_id"],
        "proposed_chapter": chapter,
        "original_chapter": plan["current_chapter"],
        "message": "A revision brief was prepared. Make the real changes in the editor before saving.",
        "model_called": False, "saved": False, "rendered": False, "published": False,
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/update-final-master")
def update_final_master(
    project_id: str, entry_id: str, payload: ConfirmedMasterUpdateIn,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Queue a new final master only for an explicitly confirmed ready version.

    Produces a separate review-only master, preserving prior exports.
    Existing active master SQL claims remain authoritative for deduplication.
    """
    if not payload.confirm_rebuild:
        raise HTTPException(status_code=422, detail="Confirm the updated master export.")
    plan = _chapter_rebuild_plan(db, user.user_id, project_id, entry_id)
    if not plan["master_ready"]:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Update blocked. Reapprove and finish rebuilding changed chapters first.",
                "needs_rebuild_indices": plan["needs_rebuild_indices"],
            },
        )
    if payload.version_sha256 != plan["version_sha256"]:
        raise HTTPException(
            status_code=409,
            detail="Chapter plan changed since review. Refresh readiness and confirm again.",
        )
    result = start_chapter_master_job(project_id, entry_id, background_tasks, user, db)
    return {
        **result,
        "confirmed_version_sha256": plan["version_sha256"],
        "original_masters_preserved": True,
        "publish_ready": False,
        "published": False,
    }


@router.post("/projects/{project_id}/calendar/{entry_id}/resume-master-job")
def resume_failed_master_job(
    project_id: str, entry_id: str, background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Explicitly resume a confirmed failed master, reusing verified segments.

    Unknown/interrupted running jobs are NOT resumed because a remote worker
    might still be active. This action cannot enable providers or posting.
    """
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the plan before resuming.")
    status = _master_job_status(db, user.user_id, project_id, entry_id)
    if status["status"] == "GENERATED":
        return {"status": "ALREADY_COMPLETED", "job": status["job"],
                "message": "The completed master was recovered; no new render started."}
    if status["status"] != "ERROR" or not status.get("resumable"):
        raise HTTPException(
            status_code=409,
            detail="Only a confirmed failed job can be resumed. Unconfirmed interrupted workers require operator recovery.",
        )
    return start_chapter_master_job(project_id, entry_id, background_tasks, user, db)


@router.get("/projects/{project_id}/calendar/{entry_id}/master-status")
def chapter_master_job_status(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    _entry(db, user.user_id, project_id, entry_id)
    return _master_job_status(db, user.user_id, project_id, entry_id)


class CaptionCueIn(BaseModel):
    start_seconds: float = Field(ge=0, le=600)
    end_seconds: float = Field(gt=0, le=600)
    text: str = Field(min_length=1, max_length=240)


class StoryboardSceneIn(BaseModel):
    heading: str = Field(min_length=1, max_length=120)
    visual_note: str = Field(default="", max_length=1500)
    revision_note: str = Field(default="", max_length=2000)
    narration: str = Field(default="", max_length=6000)
    duration_seconds: int = Field(ge=1, le=600)
    visual_asset_id: str | None = Field(default=None, max_length=48)
    transition: Literal["cut", "fade"] = "cut"
    caption_cues: list[CaptionCueIn] = Field(default_factory=list, max_length=30)

    @field_validator("heading")
    @classmethod
    def strip_heading(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Scene heading cannot be blank")
        return value


class StoryboardIn(BaseModel):
    scenes: list[StoryboardSceneIn] = Field(min_length=1, max_length=60)
    narrator_voice: Literal["en-us", "en-gb"] = "en-us"
    narrator_speed: int = Field(default=148, ge=110, le=185)


@router.put("/projects/{project_id}/calendar/{entry_id}/storyboard")
def save_calendar_storyboard(
    project_id: str, entry_id: str, payload: StoryboardIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Save reviewed planning-only scenes without touching generated media."""
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    if entry.status == "canceled":
        raise HTTPException(status_code=409, detail="Canceled plans cannot be edited.")
    total = sum(scene.duration_seconds for scene in payload.scenes)
    if total != entry.duration_seconds:
        raise HTTPException(
            status_code=422,
            detail="Scene durations must add up to the planned video duration.",
        )
    images = {
        a.id: a for a in DbCreativeStudioStore(db).list_assets(project_id, user.user_id)
        if a.kind == "image" and a.url
    }
    for scene in payload.scenes:
        if scene.visual_asset_id and scene.visual_asset_id not in images:
            raise HTTPException(status_code=422, detail="Scene images must belong to the selected Studio project.")
        previous_end = 0.0
        for cue in scene.caption_cues:
            if cue.end_seconds > scene.duration_seconds or cue.start_seconds >= cue.end_seconds:
                raise HTTPException(status_code=422, detail="Caption intervals must fit within their scene.")
            if cue.start_seconds < previous_end:
                raise HTTPException(status_code=422, detail="Caption intervals cannot overlap or be out of order.")
            previous_end = cue.end_seconds
    scenes = [
        {
            "index": index, "heading": scene.heading,
            "visual_note": scene.visual_note, "revision_note": scene.revision_note,
            "narration": scene.narration,
            "duration_seconds": scene.duration_seconds,
            "visual_asset_id": scene.visual_asset_id,
            "transition": scene.transition,
            "caption_cues": [cue.model_dump() for cue in scene.caption_cues],
        }
        for index, scene in enumerate(payload.scenes)
    ]
    canonical = json.dumps(scenes, ensure_ascii=False)
    if ((entry.storyboard_json or "[]") != canonical
            or entry.narrator_voice != payload.narrator_voice
            or entry.narrator_speed != payload.narrator_speed):
        # Capture the previous saved version (including before the revision
        # table existed), then the new version; both commit with the change.
        from sqlalchemy import select
        def snapshot(json_scenes: str, voice: str, speed: int) -> None:
            digest = hashlib.sha256(
                json.dumps({"scenes": json.loads(json_scenes or "[]"),
                            "voice": voice, "speed": speed},
                           sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            exists = db.execute(
                select(NovaCreativeStoryboardRevision.id).where(
                    NovaCreativeStoryboardRevision.owner_id == user.user_id,
                    NovaCreativeStoryboardRevision.project_id == project_id,
                    NovaCreativeStoryboardRevision.entry_id == entry_id,
                    NovaCreativeStoryboardRevision.source_sha256 == digest,
                ).limit(1)
            ).first()
            if not exists:
                db.add(NovaCreativeStoryboardRevision(
                    id=new_id("crev"), owner_id=user.user_id, project_id=project_id,
                    entry_id=entry_id, scenes_json=json_scenes,
                    narrator_voice=voice, narrator_speed=speed,
                    source_sha256=digest, created_at=_now(),
                ))
        if entry.storyboard_json and entry.storyboard_json != "[]":
            snapshot(entry.storyboard_json, entry.narrator_voice, entry.narrator_speed)
        snapshot(canonical, payload.narrator_voice, payload.narrator_speed)
        entry.storyboard_json = canonical
        entry.narrator_voice = payload.narrator_voice
        entry.narrator_speed = payload.narrator_speed
        if entry.status == "approved":
            entry.status = "ready_for_review"
        entry.updated_at = _now()
        db.commit()
        db.refresh(entry)
    return _as_dict(entry)


def _render_storyboard_preview(db: Session, owner_id: str, project_id: str,
                               entry_id: str) -> dict:
    """Produce a short preview from owner-approved scene text, no paid calls.

    The existing renderer clamps scenes to <=12s and synthesizes only the first
    1800 narration characters; reject mismatched plans rather than silently
    changing duration or truncating customer copy.
    """
    from app.core.nova.creative_studio import private_object_storage as remote
    import os

    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the current storyboard before rendering.")
    if entry.content_mode not in {"faceless", "education"}:
        raise HTTPException(status_code=422, detail="Offline storyboard preview is only for faceless and education; other styles require their dedicated renderer.")
    scenes = json.loads(entry.storyboard_json or "[]")
    if not scenes or len(scenes) > 60:
        raise HTTPException(status_code=422, detail="Save a storyboard with up to 60 scenes first.")
    planned = sum(int(scene.get("duration_seconds") or 0) for scene in scenes)
    if planned != entry.duration_seconds or not 15 <= planned <= 120:
        raise HTTPException(status_code=422, detail="This local storyboard preview supports 15–120 seconds. Use chapter production for longer videos.")
    if any(not 2 <= int(scene.get("duration_seconds") or 0) <= 12 for scene in scenes):
        raise HTTPException(status_code=422, detail="Each local preview scene must last 2–12 seconds. Edit scene timing or use chapter production.")
    narration = " ".join(str(scene.get("narration") or "").strip() for scene in scenes).strip()
    if any(not str(scene.get("narration") or "").strip() for scene in scenes):
        raise HTTPException(status_code=422, detail="Every preview scene needs narration so captions can stay within its planned time.")
    if not narration or len(narration) > 1800:
        raise HTTPException(status_code=422, detail="The local narrator needs 1–1800 characters. Shorten narration or use chapter production.")
    if os.getenv("NOVA_STUDIO_REQUIRE_DURABLE_IMPORTS", "").lower() in {"1", "true", "yes"} and not remote.enabled():
        raise HTTPException(status_code=503, detail="Durable private storage is required before preview rendering.")

    signature = hashlib.sha256(
        json.dumps({"scenes": scenes, "voice": entry.narrator_voice, "speed": entry.narrator_speed}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    store = DbCreativeStudioStore(db)
    service = get_service(db)
    for asset in store.list_assets(project_id, owner_id):
        meta = asset.metadata or {}
        if (asset.kind != "video"
                or meta.get("pipeline") != "calendar_storyboard_preview"
                or meta.get("calendar_entry_id") != entry_id
                or meta.get("storyboard_sha256") != signature):
            continue
        digest = str(meta.get("sha256") or "")
        try:
            if asset.url and asset.url.startswith("private-studio-s3://"):
                exists = bool(digest) and remote.enabled() and remote.object_exists(
                    asset.url, owner_id, project_id, digest
                )
            else:
                file_path, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                exists = bool(digest) and file_path.is_file() and hashlib.sha256(file_path.read_bytes()).hexdigest() == digest
            if exists:
                return {
                    **_preview_result(project_id, asset, reused=True),
                    "preview_source": "approved_storyboard",
                }
        except Exception:
            pass

    saved_assets = {
        a.id: a for a in store.list_assets(project_id, owner_id)
        if a.kind == "image" and a.url
    }
    render_scenes = []
    for scene in scenes:
        item = {
            "heading": scene["heading"],
            "voiceover_text": scene["narration"],
            "subtitle_text": scene["narration"],
            "duration_seconds": scene["duration_seconds"],
            "transition": scene.get("transition", "cut"),
            "caption_by_scene": True,
            "caption_cues": scene.get("caption_cues") or [],
        }
        visual_id = scene.get("visual_asset_id")
        if visual_id:
            visual = saved_assets.get(visual_id)
            if visual is None:
                raise HTTPException(status_code=422, detail="A selected storyboard image is unavailable.")
            try:
                image_path, media_type, _ = service.open_asset_file(owner_id, project_id, visual_id)
            except CreativeStudioError as exc:
                raise HTTPException(status_code=422, detail="A selected image could not be read.") from exc
            if media_type not in {"image/png", "image/jpeg", "image/webp"}:
                raise HTTPException(status_code=422, detail="Storyboard visuals must be image assets.")
            item["visual_image_path"] = str(image_path)
        render_scenes.append(item)
    with tempfile.TemporaryDirectory(prefix="nova-storyboard-preview-") as scratch:
        root = Path(scratch)
        output = root / "storyboard-preview.mp4"
        try:
            measured = render_offline_montage(
                render_scenes, output_mp4=output, audio_wav=root / "narration.wav",
                vertical=True, voice=entry.narrator_voice, speed=entry.narrator_speed,
            )
        except OfflineCommercialError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        if not measured.get("audio_present") or not output.is_file():
            raise HTTPException(status_code=422, detail="Narrated storyboard preview was not produced.")
        if abs(float(measured.get("duration_seconds") or 0) - planned) > 3:
            raise HTTPException(status_code=422, detail="Rendered duration does not match the approved storyboard.")
        try:
            imported = service.import_finished_video(
                owner_id, project_id, output.read_bytes(), content_type="video/mp4",
            )
        except CreativeStudioError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
        asset = next((item for item in store.list_assets(project_id, owner_id)
                      if item.id == imported["asset"]["id"]), None)
        if asset is None:
            raise HTTPException(status_code=500, detail="Preview output was not saved.")
        asset.metadata = {
            **(asset.metadata or {}),
            "pipeline": "calendar_storyboard_preview",
            "calendar_entry_id": entry_id, "storyboard_sha256": signature,
            "quality_state": "PREVIEW_ONLY", "publish_ready": False,
            "preview_brand": "AMICOR Nova", "captions_timing_verified": False,
            "narration_license_status": "AMBER", "commercial_complete": False,
            "caption_timing_mode": "estimated_within_measured_scene_speech_window",
            "scene_audio_aligned": bool(measured.get("narration_scene_audio_aligned")),
            "word_timestamps_verified": False,
            "transition_mode": "cut_or_fade_in_from_black",
            "customer_images_used": any(scene.get("visual_asset_id") for scene in scenes),
            "visual_notes_rendered": False, "presenter_lip_sync": False,
            "paid_provider_charges": False, "external_publishing": False,
        }
        asset = store.save_asset(asset)
    return {**_preview_result(project_id, asset, reused=False),
            "preview_source": "approved_storyboard"}


@router.post("/projects/{project_id}/calendar/{entry_id}/render-storyboard-preview")
async def render_storyboard_preview(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return await run_in_threadpool(
        _render_storyboard_preview, db, user.user_id, project_id, entry_id,
    )


class StoryboardPreviewReviewIn(BaseModel):
    narration_ok: bool
    captions_ok: bool
    visuals_ok: bool
    playback_ok: bool
    notes: str = Field(default="", max_length=2000)
    correction_scene_index: int | None = Field(default=None, ge=0, le=59)
    correction_category: Literal["narration", "captions", "visuals", "playback", "general"] = "general"


@router.put("/projects/{project_id}/calendar/{entry_id}/previews/{asset_id}/review")
def review_storyboard_preview(
    project_id: str, entry_id: str, asset_id: str,
    payload: StoryboardPreviewReviewIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Record manual QA on this exact saved MP4; never authorize publishing."""
    _project(db, user.user_id, project_id)
    entry = _entry(db, user.user_id, project_id, entry_id)
    store = DbCreativeStudioStore(db)
    asset = next((
        row for row in store.list_assets(project_id, user.user_id)
        if row.id == asset_id
    ), None)
    meta = asset.metadata or {} if asset is not None else {}
    if (asset is None or asset.kind != "video" or not asset.url
            or meta.get("pipeline") != "calendar_storyboard_preview"
            or meta.get("calendar_entry_id") != entry_id):
        raise HTTPException(status_code=404, detail="Saved storyboard preview not found in this project.")
    current_signature = hashlib.sha256(
        json.dumps({
            "scenes": json.loads(entry.storyboard_json or "[]"),
            "voice": entry.narrator_voice,
            "speed": entry.narrator_speed,
        }, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if meta.get("storyboard_sha256") != current_signature:
        raise HTTPException(
            status_code=409,
            detail="The storyboard has changed since this MP4 was rendered. Render a current preview before reviewing.",
        )
    from app.core.nova.creative_studio import private_object_storage as remote
    digest = str(meta.get("sha256") or "")
    if not digest:
        raise HTTPException(status_code=409, detail="Preview has no verifiable stored checksum.")
    service = get_service(db)
    try:
        if str(asset.url).startswith("private-studio-s3://"):
            verified = remote.enabled() and remote.object_exists(
                asset.url, user.user_id, project_id, digest
            )
        else:
            media_path, _, _ = service.open_asset_file(user.user_id, project_id, asset.id)
            verified = media_path.is_file() and hashlib.sha256(media_path.read_bytes()).hexdigest() == digest
    except Exception:
        verified = False
    if not verified:
        raise HTTPException(status_code=409, detail="Preview file could not be verified. Review was not saved.")

    saved_scenes = json.loads(entry.storyboard_json or "[]")
    if (payload.correction_scene_index is not None and payload.correction_scene_index >= len(saved_scenes)):
        raise HTTPException(status_code=422, detail="The correction scene does not exist in this storyboard.")
    review = {
        "correction_scene_index": payload.correction_scene_index,
        "correction_category": payload.correction_category,
        "narration_ok": payload.narration_ok,
        "captions_ok": payload.captions_ok,
        "visuals_ok": payload.visuals_ok,
        "playback_ok": payload.playback_ok,
        "notes": payload.notes.strip(),
        "reviewed_at": _now(),
        "reviewed_by": user.user_id,
        "status": "REVIEW_PASSED" if all([
            payload.narration_ok, payload.captions_ok,
            payload.visuals_ok, payload.playback_ok,
        ]) else "CHANGES_REQUIRED",
    }
    asset.metadata = {
        **meta, "storyboard_preview_review": review,
        "quality_state": "PREVIEW_REVIEWED" if review["status"] == "REVIEW_PASSED" else "PREVIEW_CHANGES_REQUIRED",
        "publish_ready": False, "commercial_complete": False,
        "external_publishing": False,
    }
    store.save_asset(asset)
    return {
        "status": review["status"], "review": review,
        "asset_id": asset.id, "published": False, "publish_ready": False,
        "message": "Quality review saved for this MP4 only. Commercial and publishing approval remain separate.",
    }


@router.get("/projects/{project_id}/calendar/{entry_id}/storyboard-revisions")
def list_storyboard_revisions(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """List immutable snapshots for comparison without reverting current work."""
    _project(db, user.user_id, project_id)
    _entry(db, user.user_id, project_id, entry_id)
    records = (
        db.query(NovaCreativeStoryboardRevision)
        .filter_by(owner_id=user.user_id, project_id=project_id, entry_id=entry_id)
        .order_by(NovaCreativeStoryboardRevision.created_at.desc())
        .limit(40).all()
    )
    return {
        "revisions": [{
            "id": row.id,
            "saved_at": row.created_at,
            "sha256": row.source_sha256,
            "narrator_voice": row.narrator_voice,
            "narrator_speed": row.narrator_speed,
            "scenes": json.loads(row.scenes_json),
        } for row in records],
        "restored": False, "published": False,
    }


def _storyboard_segment_hash(scene: dict, entry: NovaCreativeCalendarEntry, index: int) -> str:
    # v2 marks CTA-free reusable segments; never mix with older QC previews.
    return hashlib.sha256(json.dumps({
        "scene": scene, "voice": entry.narrator_voice,
        "speed": entry.narrator_speed, "scene_index": index,
        "render_profile": "offline-captioned-no-cta-v2",
    }, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _render_single_storyboard_scene(db: Session, owner_id: str,
                                    project_id: str, entry_id: str,
                                    scene_index: int) -> dict:
    """Render exactly one approved 2-12s scene as a protected QC-only MP4."""
    from app.core.nova.creative_studio import private_object_storage as remote
    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the current storyboard before rendering.")
    if entry.content_mode not in {"faceless", "education"}:
        raise HTTPException(status_code=422, detail="Local scene preview requires faceless or education mode.")
    scenes = json.loads(entry.storyboard_json or "[]")
    if not 0 <= scene_index < len(scenes):
        raise HTTPException(status_code=404, detail="Storyboard scene not found.")
    scene = scenes[scene_index]
    seconds = int(scene.get("duration_seconds") or 0)
    if not 2 <= seconds <= 12:
        raise HTTPException(status_code=422, detail="This local scene preview supports 2-12 seconds.")
    narration = str(scene.get("narration") or "").strip()
    if not narration or len(narration) > 450:
        raise HTTPException(status_code=422, detail="Scene narration must be 1-450 characters.")
    store = DbCreativeStudioStore(db)
    service = get_service(db)
    key = _storyboard_segment_hash(scene, entry, scene_index)
    for asset in reversed(store.list_assets(project_id, owner_id)):
        meta = asset.metadata or {}
        if (asset.kind == "video" and
                meta.get("pipeline") == "calendar_scene_segment" and
                meta.get("source_sha256") == key and
                meta.get("calendar_entry_id") == entry_id):
            digest = str(meta.get("sha256") or "")
            try:
                if asset.url and str(asset.url).startswith("private-studio-s3://"):
                    valid = bool(digest) and remote.enabled() and remote.object_exists(
                        asset.url, owner_id, project_id, digest)
                else:
                    stored, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                    valid = bool(digest) and stored.is_file() and hashlib.sha256(
                        stored.read_bytes()).hexdigest() == digest
                if valid:
                    return {**_preview_result(project_id, asset, reused=True),
                            "scene_index": scene_index}
            except Exception:
                pass
    item = {
        "heading": scene["heading"], "voiceover_text": narration,
        "subtitle_text": narration, "duration_seconds": seconds,
        "transition": scene.get("transition", "cut"), "caption_by_scene": True,
        "caption_cues": scene.get("caption_cues") or [],
    }
    visual_id = scene.get("visual_asset_id")
    if visual_id:
        if not any(a.id == visual_id and a.kind == "image" for a in store.list_assets(project_id, owner_id)):
            raise HTTPException(status_code=422, detail="Selected visual is missing from this project.")
        try:
            image_path, media_type, _ = service.open_asset_file(owner_id, project_id, visual_id)
        except CreativeStudioError as exc:
            raise HTTPException(status_code=422, detail="Scene visual is unavailable.") from exc
        if media_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise HTTPException(status_code=422, detail="Scene visual is not a supported image.")
        item["visual_image_path"] = str(image_path)
    with tempfile.TemporaryDirectory(prefix="nova-scene-qc-") as scratch:
        root = Path(scratch)
        output = root / "scene-review.mp4"
        try:
            measured = render_offline_montage(
                [item], output_mp4=output, audio_wav=root / "narration.wav",
                vertical=True, voice=entry.narrator_voice, speed=entry.narrator_speed,
                include_cta=False,
            )
        except OfflineCommercialError as exc:
            raise HTTPException(status_code=422, detail=exc.message) from exc
        if (not output.is_file() or not measured.get("audio_present")
                or abs(float(measured.get("duration_seconds") or 0) - seconds) > 2):
            raise HTTPException(status_code=422, detail="Verified single-scene MP4 was not produced.")
        try:
            imported = service.import_finished_video(
                owner_id, project_id, output.read_bytes(), content_type="video/mp4"
            )
        except CreativeStudioError as exc:
            raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
    asset = next((a for a in store.list_assets(project_id, owner_id)
                  if a.id == imported["asset"]["id"]), None)
    if asset is None:
        raise HTTPException(status_code=500, detail="Scene preview file was not saved.")
    # The existing protected importer can deduplicate byte-identical media
    # from a different workflow. Never relabel someone else's saved original.
    if imported.get("reused"):
        old_meta = asset.metadata or {}
        if (old_meta.get("pipeline") != "calendar_scene_segment"
                or old_meta.get("source_sha256") != key
                or old_meta.get("calendar_entry_id") != entry_id):
            raise HTTPException(
                status_code=409,
                detail="Identical video belongs to another saved asset. Original preserved; scene preview not relabeled.",
            )
        return {**_preview_result(project_id, asset, reused=True),
                "scene_index": scene_index}
    asset.metadata = {
        **(asset.metadata or {}), "pipeline": "calendar_scene_segment",
        "source_sha256": key, "calendar_entry_id": entry_id,
        "scene_index": scene_index, "quality_state": "SCENE_SEGMENT_REVIEW_ONLY",
        "concat_ready": True, "render_profile": "offline-captioned-no-cta-v2",
        "commercial_complete": False, "publish_ready": False,
        "captions_timing_verified": False, "external_publishing": False,
        "paid_provider_charges": False,
    }
    asset = store.save_asset(asset)
    return {**_preview_result(project_id, asset, reused=False),
            "scene_index": scene_index}


@router.post("/projects/{project_id}/calendar/{entry_id}/scenes/{scene_index}/render-preview")
async def render_single_storyboard_scene(
    project_id: str, entry_id: str, scene_index: int,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return await run_in_threadpool(
        _render_single_storyboard_scene, db, user.user_id,
        project_id, entry_id, scene_index,
    )


def _assemble_saved_storyboard_segments(db: Session, owner_id: str,
                                        project_id: str, entry_id: str) -> dict:
    """Build a short private MP4 from existing, *verified* CTA-free scene segments.

    Missing or changed scenes must be rendered independently first. There are
    no paid calls, no implicit generation, and no changes to original videos.
    """
    import subprocess
    from app.core.nova.creative_studio import private_object_storage as remote
    from app.core.nova.creative_studio.video_import import validate_video
    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved" or entry.content_mode not in {"faceless", "education"}:
        raise HTTPException(status_code=409, detail="Approve a faceless/education storyboard before assembly.")
    scenes = json.loads(entry.storyboard_json or "[]")
    duration = sum(int(s.get("duration_seconds") or 0) for s in scenes)
    if (not 1 <= len(scenes) <= 60 or duration != entry.duration_seconds
            or not 15 <= duration <= 120
            or any(not 2 <= int(s.get("duration_seconds") or 0) <= 12 for s in scenes)):
        raise HTTPException(status_code=422, detail="Saved-scene assembly supports approved 15-120s plans with 2-12s scenes.")
    store = DbCreativeStudioStore(db)
    service = get_service(db)
    assets = store.list_assets(project_id, owner_id)
    candidates = []
    missing = []
    for index, scene in enumerate(scenes):
        key = _storyboard_segment_hash(scene, entry, index)
        matches = [a for a in assets if a.kind == "video" and a.url
                   and (a.metadata or {}).get("pipeline") == "calendar_scene_segment"
                   and (a.metadata or {}).get("calendar_entry_id") == entry_id
                   and (a.metadata or {}).get("source_sha256") == key
                   and (a.metadata or {}).get("concat_ready") is True]
        if not matches:
            missing.append(index + 1)
        candidates.append(matches[-1] if matches else None)
    if missing:
        raise HTTPException(status_code=409, detail={
            "message": "Render these approved scenes before assembling; no existing files were changed.",
            "missing_scene_numbers": missing,
        })
    overall = hashlib.sha256(json.dumps({
        "scene_hashes": [_storyboard_segment_hash(s, entry, i) for i,s in enumerate(scenes)],
        "profile": "concat-scene-v1",
    }, sort_keys=True).encode("utf-8")).hexdigest()
    for asset in reversed(assets):
        meta = asset.metadata or {}
        if (meta.get("pipeline") == "calendar_assembled_scene_preview"
                and meta.get("calendar_entry_id") == entry_id
                and meta.get("assembly_signature") == overall):
            digest = str(meta.get("sha256") or "")
            try:
                if str(asset.url).startswith("private-studio-s3://"):
                    valid = bool(digest) and remote.enabled() and remote.object_exists(
                        asset.url, owner_id, project_id, digest)
                else:
                    local, _, _ = service.open_asset_file(owner_id, project_id, asset.id)
                    valid = bool(digest) and local.is_file() and hashlib.sha256(local.read_bytes()).hexdigest() == digest
                if valid:
                    return {**_preview_result(project_id, asset, reused=True),
                            "reused_scene_segments": len(scenes)}
            except Exception:
                pass
    with tempfile.TemporaryDirectory(prefix="nova-scene-join-") as scratch:
        root = Path(scratch)
        sources = []
        for index, asset in enumerate(candidates):
            assert asset is not None
            target = root / f"scene-{index:02d}.mp4"
            digest = str((asset.metadata or {}).get("sha256") or "")
            if not digest:
                raise HTTPException(status_code=409, detail="A segment has no stored checksum.")
            try:
                if str(asset.url).startswith("private-studio-s3://"):
                    if not remote.enabled() or not remote.object_exists(
                            asset.url, owner_id, project_id, digest):
                        raise ValueError("Remote segment is not verified")
                    stream_info = service.open_private_remote_asset(owner_id, project_id, asset.id)
                    if stream_info is None:
                        raise ValueError("Remote segment not found")
                    stream = stream_info[0]
                    try:
                        with target.open("wb") as handle:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                handle.write(chunk)
                                if handle.tell() > 128 * 1024 * 1024:
                                    raise ValueError("Segment exceeds secure size limit")
                    finally:
                        stream.close()
                else:
                    local, media_type, _ = service.open_asset_file(owner_id, project_id, asset.id)
                    if media_type != "video/mp4" or local.stat().st_size > 128 * 1024 * 1024:
                        raise ValueError("Invalid local segment")
                    import shutil
                    shutil.copyfile(local, target)
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise ValueError("Segment checksum mismatch")
                measured = validate_video(target)
                if abs(measured["duration_seconds"] - scenes[index]["duration_seconds"]) > 1.5:
                    raise ValueError("Segment duration mismatch")
            except (CreativeStudioError, OSError, ValueError) as exc:
                raise HTTPException(status_code=409, detail=f"Scene {index + 1} failed media verification; source videos remain saved.") from exc
            sources.append(target)
        manifest = root / "input.txt"
        manifest.write_text("".join(f"file '{path.as_posix()}'\n" for path in sources), encoding="utf-8")
        output = root / "joined.mp4"
        try:
            process = subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(manifest),
                "-map", "0:v:0", "-map", "0:a:0", "-c", "copy",
                "-movflags", "+faststart", str(output),
            ], capture_output=True, timeout=240)
            if process.returncode != 0 or not output.is_file():
                raise ValueError("Scene assembly failed")
            final = validate_video(output)
            if abs(final["duration_seconds"] - duration) > 2:
                raise ValueError("Joined scene timing differs from the approved plan")
            imported = service.import_finished_video(
                owner_id, project_id, output.read_bytes(), content_type="video/mp4"
            )
        except (subprocess.TimeoutExpired, OSError, ValueError, CreativeStudioError) as exc:
            raise HTTPException(status_code=422, detail="Could not verify the assembled MP4. Saved scenes are unchanged.") from exc
    asset = next((a for a in store.list_assets(project_id, owner_id)
                  if a.id == imported["asset"]["id"]), None)
    if asset is None:
        raise HTTPException(status_code=500, detail="Finished assembled MP4 was not saved.")
    if imported.get("reused"):
        meta = asset.metadata or {}
        if (meta.get("pipeline") != "calendar_assembled_scene_preview"
                or meta.get("assembly_signature") != overall
                or meta.get("calendar_entry_id") != entry_id):
            raise HTTPException(status_code=409, detail="Identical MP4 belongs to an existing original. No asset was relabeled.")
        return {**_preview_result(project_id, asset, reused=True),
                "reused_scene_segments": len(scenes)}
    asset.metadata = {
        **(asset.metadata or {}),
        "pipeline": "calendar_assembled_scene_preview",
        "calendar_entry_id": entry_id,
        "assembly_signature": overall,
        "quality_state": "PREVIEW_ONLY", "publish_ready": False,
        "commercial_complete": False, "external_publishing": False,
        "scene_segments_reused": len(scenes),
        "final_cta_added": False, "captions_timing_verified": False,
        "paid_provider_charges": False,
    }
    asset = store.save_asset(asset)
    return {**_preview_result(project_id, asset, reused=False),
            "reused_scene_segments": len(scenes)}


@router.post("/projects/{project_id}/calendar/{entry_id}/assemble-scene-previews")
async def assemble_saved_storyboard_segments(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return await run_in_threadpool(
        _assemble_saved_storyboard_segments, db, user.user_id, project_id, entry_id,
    )
