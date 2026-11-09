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
from app.core.nova.creative_studio.db_models import NovaCreativeCalendarEntry, NovaCreativeProject, NovaCreativeRenderClaim
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


def _assemble_chapter_master(db: Session, owner_id: str, project_id: str, entry_id: str):
    """Combine verified finished chapter assets into one private 10-30m master."""
    import os
    import shutil
    from app.core.nova.creative_studio import private_object_storage as remote
    from app.core.nova.creative_studio.chapter_master import (
        ChapterMasterError, join_chapters,
    )

    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the chapter plan before exporting.")
    if not 600 <= entry.duration_seconds <= 1800:
        raise HTTPException(status_code=422, detail="Master export currently supports 10–30 minutes.")
    if not remote.enabled():
        raise HTTPException(status_code=503, detail="Private durable object storage is required for long-form masters.")
    chapters = json.loads(entry.chapters_json or "[]")
    if not 2 <= len(chapters) <= 12 or sum(int(ch["duration_seconds"]) for ch in chapters) != entry.duration_seconds:
        raise HTTPException(status_code=422, detail="Create 2–12 completed chapters totaling the planned duration.")
    store = DbCreativeStudioStore(db)
    assets = store.list_assets(project_id, owner_id)
    selected = []
    for index, chapter in enumerate(chapters):
        matches = [
            asset for asset in assets if asset.kind == "video"
            and (asset.metadata or {}).get("pipeline") == "calendar_saved_clip_assembly"
            and (asset.metadata or {}).get("calendar_entry_id") == entry_id
            and (asset.metadata or {}).get("chapter_index") == index
            and (asset.metadata or {}).get("source_asset_ids") == chapter["asset_ids"]
            and abs(float((asset.metadata or {}).get("duration_seconds") or 0) -
                    float(chapter["duration_seconds"])) <= 5
        ]
        if not matches:
            raise HTTPException(status_code=422, detail=f"Chapter {index + 1} needs a completed MP4 before export.")
        selected.append(matches[-1])
    signature = hashlib.sha256(
        (entry_id + "|" + str(entry.duration_seconds) + "|" +
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
        output = root / "finished-master.mp4"
        try:
            measured = join_chapters(files, output, expected_seconds=entry.duration_seconds)
        except (ChapterMasterError, OSError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        digest = hashlib.sha256()
        with output.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        sha = digest.hexdigest()
        filename = new_id("imported_video") + ".mp4"
        try:
            ref = remote.put_original_file(owner_id, project_id, filename, output, sha)
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
                    "source_asset_ids": [a.id for a in selected], "sha256": sha,
                    **measured, "quality_state": "OWNER_REVIEW_REQUIRED",
                    "commercial_complete": False, "publish_ready": False,
                    "captions_verified": False, "rights_review_required": True,
                    "paid_provider_charges": False,
                },
            ))
        except Exception:
            remote.delete_original(ref, owner_id, project_id)
            raise
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
    """Initial bounded master export, not a resumable 2h production worker."""
    return await run_in_threadpool(
        _assemble_chapter_master, db, user.user_id, project_id, entry_id,
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
    try:
        store = DbCreativeStudioStore(db)
        job = next((row for row in store.list_jobs(project_id, owner_id)
                    if row.id == job_id), None)
        if job is None or job.status != "QUEUED":
            return
        if not _claim_queued_master(db, owner_id, project_id, entry_id, job_id):
            # Another process already claimed this work, or it was canceled.
            return
        job.status = "RUNNING"
        job.message = "Combining previously saved chapters into a private MP4."
        job.updated_at = _now()
        store.save_job(job)
        try:
            result = _assemble_chapter_master(db, owner_id, project_id, entry_id)
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
        job.updated_at = _now()
        store.save_job(job)
        _finish_master_claim(db, owner_id, project_id, entry_id, job_id, job.status)
    finally:
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
    if latest.status not in {"QUEUED", "RUNNING"} or locally_running:
        return {"status": latest.status, "job": latest.as_dict()}

    # If the process died after saving the master but before updating its job,
    # recover only a verifiably persisted file created after the job began.
    candidates = [
        asset for asset in store.list_assets(project_id, owner_id)
        if asset.kind == "video"
        and (asset.metadata or {}).get("pipeline") == "calendar_chapter_master"
        and (asset.metadata or {}).get("calendar_entry_id") == entry_id
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
            return {"status": "GENERATED", "job": latest.as_dict(),
                    "message": "A previously completed private master was verified and recovered."}
    return {
        "status": "INTERRUPTED_UNCONFIRMED", "job": latest.as_dict(),
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
    if not 600 <= entry.duration_seconds <= 1800:
        raise HTTPException(status_code=422, detail="Master export supports 10–30 minutes.")
    if not remote.enabled():
        raise HTTPException(status_code=503, detail="Private durable storage is required.")
    chapters = json.loads(entry.chapters_json or "[]")
    if not 2 <= len(chapters) <= 12:
        raise HTTPException(status_code=422, detail="Save 2–12 completed chapters first.")
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
        if claim is None:
            db.add(NovaCreativeRenderClaim(
                claim_key=claim_key, owner_id=user.user_id, project_id=project_id,
                entry_id=entry_id, job_id=fresh_id, state="QUEUED", updated_at=now,
            ))
        else:
            # Reclaim only a terminal state; never silently restart a stuck job.
            claim.job_id = fresh_id
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


@router.get("/projects/{project_id}/calendar/{entry_id}/master-status")
def chapter_master_job_status(
    project_id: str, entry_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    _project(db, user.user_id, project_id)
    _entry(db, user.user_id, project_id, entry_id)
    return _master_job_status(db, user.user_id, project_id, entry_id)
