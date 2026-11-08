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

from app.auth import UserContext, get_current_user_context
from app.core.nova.creative_studio.db_models import NovaCreativeCalendarEntry, NovaCreativeProject
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


class LongFormAssemblyIn(BaseModel):
    """Ordered video asset IDs already saved in this same owner's Studio project."""
    asset_ids: list[str] = Field(default_factory=list, max_length=16)


def _assemble_calendar_video(db: Session, owner_id: str, project_id: str,
                             entry_id: str, asset_ids: list[str]):
    import os
    from app.core.nova.creative_studio import private_object_storage as remote
    from app.core.nova.creative_studio.long_form_assembly import (
        LongFormAssemblyError, assemble_clips,
    )
    _project(db, owner_id, project_id)
    entry = _entry(db, owner_id, project_id, entry_id)
    if entry.status != "approved":
        raise HTTPException(status_code=409, detail="Approve the plan before assembling its video.")
    if not 120 <= entry.duration_seconds <= 600:
        raise HTTPException(status_code=422, detail="This first long-form assembler supports 2–10 minutes. Longer productions need the queued storage workflow.")
    # The stored timeline is authoritative once configured. The client can
    # send an empty list to request the saved order on later sessions.
    stored_timeline = json.loads(entry.timeline_json or "[]")
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
        (entry_id + "|" + str(entry.duration_seconds) + "|" + "|".join(
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
            measured = assemble_clips(clip_paths, output, target_seconds=entry.duration_seconds)
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
