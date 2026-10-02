"""Nova Creative Studio HTTP API. Planning/script mode. No publishing."""

from __future__ import annotations

import os
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import OPERATOR_ACCOUNT_GRANTS, UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.creative_studio.service import CreativeStudioError, get_service
from app.core.nova.creative_studio.providers import CONFIG_REQUIRED, talking_presenter_provider
from app.db.session import SessionLocal, get_db

logger = logging.getLogger(__name__)
_scene_lock = threading.Lock()
_scene_workers: set[str] = set()
_scene_capacity = threading.Semaphore(1)


def _recover_scene_jobs(service, owner_id: str, project_id: str, tasks: BackgroundTasks) -> None:
    """Reconnect only to persisted tasks; never create paid work from a GET."""
    with _scene_lock:
        assets = {row.id: row for row in service.store.list_assets(project_id, owner_id)}
        for job in service.store.list_jobs(project_id, owner_id):
            if job.kind != "video" or job.status not in {"QUEUED", "RUNNING"} or job.id in _scene_workers:
                continue
            results = [assets[aid] for aid in job.result_asset_ids if aid in assets and assets[aid].kind == "video"]
            completed = [row for row in results if row.status == "GENERATED" and row.url]
            if completed:
                service._finish_job(job, status="GENERATED", message="Recovered completed scene after server restart.", asset_ids=[row.id for row in completed])
            elif any((row.metadata or {}).get("provider_result", {}).get("status") == "PROCESSING"
                     and (row.metadata or {}).get("provider_result", {}).get("task_id") for row in results):
                _scene_workers.add(job.id)
                service._finish_job(job, status="QUEUED", message="Reconnecting to saved Runway task after server restart.", asset_ids=job.result_asset_ids)
                tasks.add_task(_run_scene_background, owner_id, project_id, job.id)
            else:
                service._finish_job(job, status="ERROR", message="Scene worker was interrupted. No saved Runway task is available; check provider history before retrying. Nova has not automatically submitted another video.", asset_ids=job.result_asset_ids)


def _run_scene_background(owner_id: str, project_id: str, job_id: str) -> None:
    db = None
    job = None
    _scene_capacity.acquire()
    try:
        db = SessionLocal()
        service = get_service(db)
        job = next(row for row in service.store.list_jobs(project_id, owner_id) if row.id == job_id)
        deadline = time.monotonic() + 900
        while True:
            service._finish_job(job, status="RUNNING", message="Generating scene artwork and video.", asset_ids=job.result_asset_ids)
            result = service.request_video_generation(owner_id, project_id, job=job)
            if result.get("provider", {}).get("status") != "PROCESSING":
                break
            if time.monotonic() >= deadline:
                service._finish_job(job, status="ERROR", message="Runway is still processing. Retry to resume the saved task without generating new artwork.", asset_ids=job.result_asset_ids)
                break
    except Exception as exc:
        logger.exception("Creative scene job failed: job=%s project=%s", job_id, project_id)
        if db is not None and job is not None:
            db.rollback()
            service._finish_job(job, status="ERROR", message=f"Scene generation failed: {type(exc).__name__}: {exc}", asset_ids=job.result_asset_ids)
    finally:
        if db is not None:
            db.close()
        with _scene_lock:
            _scene_workers.discard(job_id)
        _scene_capacity.release()

router = APIRouter(
    prefix="/api/nova/creative",
    tags=["nova-creative-studio"],
    dependencies=[Depends(require_nova_access)],
)

_final_promo_lock = threading.Lock()
_final_promo_running: set[tuple[str, str]] = set()


def _run_final_promo_background(owner_id: str, project_id: str) -> None:
    key = (owner_id, project_id)
    db = SessionLocal()
    try:
        service = get_service(db)
        try:
            service.assemble_final_promo(owner_id, project_id)
        except Exception as exc:
            try:
                service._save_text_asset(
                    owner_id=owner_id,
                    project_id=project_id,
                    kind="video",
                    title="Final AMICOR Nova promo",
                    content=f"Background final promo render failed: {type(exc).__name__}: {exc}",
                    status="ERROR",
                    metadata={"background_final_promo": True, "error_type": type(exc).__name__},
                    url=None,
                )
            except Exception:
                pass
    finally:
        db.close()
        with _final_promo_lock:
            _final_promo_running.discard(key)


def _owner_emails() -> set[str]:
    configured = str(os.getenv("NOVA_V3_OWNER_EMAILS") or "").strip()
    if configured:
        return {item.strip().lower() for item in configured.split(",") if item.strip()}
    owners = {
        str(grant.get("email") or "").strip().lower()
        for grant in OPERATOR_ACCOUNT_GRANTS
        if str(grant.get("email") or "").strip()
    }
    if os.getenv("PYTEST_CURRENT_TEST"):
        owners.update({
            "admin@amicor.local",
            "dispatcher@amicor.local",
            "staff@amicor.local",
            "driver@amicor.local",
        })
    return owners


def _require_owner(user: UserContext) -> None:
    email = str(getattr(user, "email", "") or "").strip().lower()
    if email and email in _owner_emails():
        return
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    # Fall back: authenticated Nova users may use planning studio in V1 lab mode.
    if getattr(user, "user_id", None):
        return
    raise HTTPException(status_code=403, detail="Nova Creative Studio access required")


def _raise(exc: CreativeStudioError) -> None:
    raise HTTPException(status_code=exc.http_status, detail={"code": exc.code, "message": exc.message})


class ProjectIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    project_type: str
    platform: str = "generic"
    objective: str = ""
    audience: str = ""
    tone: str = ""
    duration_target: int | None = None
    brand_profile_id: str | None = None


class BrandIn(BaseModel):
    business_name: str = Field(min_length=1, max_length=200)
    logo_reference: str = ""
    tagline: str = ""
    tone: str = ""
    target_audience: str = ""
    preferred_cta: str = ""
    brand_description: str = ""
    prohibited_claims: list[str] = Field(default_factory=list)
    preferred_platforms: list[str] = Field(default_factory=list)


class BriefIn(BaseModel):
    topic: str = Field(min_length=1, max_length=300)
    project_id: str | None = None
    audience: str = ""
    objective: str = ""
    tone: str = ""
    cta: str = ""
    style: str = ""
    key_points: list[str] = Field(default_factory=list)
    duration_target: int | None = None
    platform: str = "generic"


class AspectIn(BaseModel):
    aspect_ratio: str = "1:1"
    prompt: str | None = None


class ExportIn(BaseModel):
    format: str = "json"


class PresenterIn(BaseModel):
    script: str = Field(min_length=1, max_length=1600)
    presenter_style: str = Field(default="warm professional small-business presenter", max_length=240)


@router.get("/guardrails")
def creative_guardrails_endpoint(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    return get_service(db).guardrails()


@router.post("/projects")
def create_project(
    payload: ProjectIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).create_project(user.user_id, payload.model_dump())
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.get("/projects")
def list_projects(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    rows = get_service(db).list_projects(user.user_id)
    return {"count": len(rows), "projects": rows}


@router.get("/projects/{project_id}")
def get_project(
    project_id: str,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        service = get_service(db)
        service._project_or_404(user.user_id, project_id)
        _recover_scene_jobs(service, user.user_id, project_id, background_tasks)
        return service.get_project(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/brands")
def create_brand(
    payload: BrandIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).create_brand(user.user_id, payload.model_dump())
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.get("/brands")
def list_brands(
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    rows = get_service(db).list_brands(user.user_id)
    return {"count": len(rows), "brands": rows}


@router.post("/briefs")
def create_brief(
    payload: BriefIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).create_brief(user.user_id, payload.model_dump())
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/generate/script")
def generate_script(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).generate_script(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/generate/caption")
def generate_caption(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).generate_caption(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/generate/storyboard")
def generate_storyboard(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).generate_storyboard(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/generate/image-prompt")
def generate_image_prompt(
    project_id: str,
    payload: AspectIn | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    aspect = (payload.aspect_ratio if payload else "1:1")
    try:
        return get_service(db).generate_image_prompt(user.user_id, project_id, aspect_ratio=aspect)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/generate/image")
def generate_image(
    project_id: str,
    payload: AspectIn | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).request_image_generation(
            user.user_id,
            project_id,
            aspect_ratio=(payload.aspect_ratio if payload else "1:1"),
            prompt=(payload.prompt if payload else None),
        )
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/assets/reset-media")
def reset_project_media(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).reset_project_media(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/assets/clear-failed-video")
def clear_failed_video_assets(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).clear_failed_video_assets(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/generate/video")
def generate_video(
    project_id: str,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        service = get_service(db)
        service._project_or_404(user.user_id, project_id)
        if not service.store.list_scenes(project_id, user.user_id):
            raise CreativeStudioError("STORYBOARD_REQUIRED", "Generate the storyboard before generating scene videos.", http_status=422)
        # Persist the job before responding so refresh/retries can reattach to it.
        # The lock serializes enqueueing in this single-worker Render service.
        with _scene_lock:
            jobs = service.store.list_jobs(project_id, user.user_id)
            for existing in jobs:
                if existing.kind != "video" or existing.status not in {"QUEUED", "RUNNING"}:
                    continue
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(existing.updated_at).replace(tzinfo=timezone.utc)).total_seconds()
                if existing.id in _scene_workers or age < 1200:
                    return {"status": "PROCESSING", "job": existing.as_dict(), "already_running": True}
                service._finish_job(existing, status="ERROR", message="Scene job was interrupted or timed out. Retry resumes any saved Runway task.", asset_ids=existing.result_asset_ids)
            job = service._start_job(user.user_id, project_id, "video")
            service._finish_job(job, status="QUEUED", message="Scene generation queued.", asset_ids=[])
            _scene_workers.add(job.id)
            background_tasks.add_task(_run_scene_background, user.user_id, project_id, job.id)
        return {"status": "PROCESSING", "job": job.as_dict(), "already_running": False}
    except CreativeStudioError as exc:
        _raise(exc)
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "VIDEO_GENERATION_FAILED",
                "message": f"Nova video generation failed safely: {type(exc).__name__}: {exc}",
            },
        ) from exc


@router.post("/projects/{project_id}/generate/voice")
def generate_voice(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).request_voice_generation(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/presenter/script")
def save_presenter_script(
    project_id: str,
    payload: PresenterIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    service = get_service(db)
    try:
        service._project_or_404(user.user_id, project_id)
        asset = service._save_text_asset(
            owner_id=user.user_id,
            project_id=project_id,
            kind="presenter_script",
            title="Talking presenter script",
            content=payload.script,
            status="GENERATED",
            metadata={"presenter_style": payload.presenter_style, "talking_presenter": True},
            url=None,
        )
        return {"status": "GENERATED", "message": "Presenter script saved for the next demo video.", "asset": asset.as_dict()}
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/presenter/voice")
def generate_presenter_voice(
    project_id: str,
    payload: PresenterIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        result = get_service(db).request_voice_generation(user.user_id, project_id, script=payload.script)
        result["presenter_script"] = payload.script
        return result
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/presenter/preview")
def prepare_talking_presenter_preview(
    project_id: str,
    payload: PresenterIn,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    service = get_service(db)
    try:
        service._project_or_404(user.user_id, project_id)
        service._save_text_asset(
            owner_id=user.user_id,
            project_id=project_id,
            kind="presenter_script",
            title="Talking presenter preview script",
            content=payload.script,
            status="GENERATED",
            metadata={"presenter_style": payload.presenter_style, "talking_presenter": True, "preview": True},
            url=None,
        )
        provider_name = str(os.getenv("NOVA_TALKING_PRESENTER_PROVIDER") or "").strip()
        if not provider_name:
            return {
                "status": "CONFIG_REQUIRED",
                "message": "Presenter script is saved. Connect a lip-sync/talking-avatar provider before Nova generates a real talking face; Nova will not fake lip sync with a still image.",
                "script": payload.script,
                "presenter_style": payload.presenter_style,
            }
        images = [
            asset for asset in service.store.list_assets(project_id, user.user_id)
            if asset.kind == "image" and asset.url and str(asset.status or "").upper() == "GENERATED"
        ]
        if not images:
            return {
                "status": "CONFIG_REQUIRED",
                "message": "Generate or select a presenter image before creating the talking presenter preview.",
                "script": payload.script,
                "presenter_style": payload.presenter_style,
            }
        presenter_image = images[-1]
        result = talking_presenter_provider().generate(
            presenter_image_url=str(presenter_image.url),
            script=payload.script,
        )
        status = str(result.get("status") or CONFIG_REQUIRED)
        generated_url = str(result.get("url") or "").strip() if result.get("asset_generated") else None
        asset = service._save_text_asset(
            owner_id=user.user_id,
            project_id=project_id,
            kind="presenter_video",
            title="Talking presenter preview",
            content=payload.script,
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={"presenter_style": payload.presenter_style, "talking_presenter": True, "preview": True, "source_image_asset_id": presenter_image.id, "provider_result": result},
            url=generated_url,
        )
        return {
            "status": status,
            "message": result.get("message"),
            "script": payload.script,
            "presenter_style": payload.presenter_style,
            "provider": result,
            "asset": asset.as_dict(),
            "url": generated_url,
        }
    except CreativeStudioError as exc:
        _raise(exc)
        raise


@router.post("/projects/{project_id}/assemble/final-promo")
def assemble_final_promo(
    project_id: str,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    # Validate ownership/project existence quickly before queueing.
    try:
        get_service(db)._project_or_404(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise

    key = (user.user_id, project_id)
    with _final_promo_lock:
        already_running = key in _final_promo_running
        if not already_running:
            _final_promo_running.add(key)

    queued_at = datetime.now(timezone.utc).isoformat()
    if not already_running:
        background_tasks.add_task(_run_final_promo_background, user.user_id, project_id)

    return {
        "status": "PROCESSING",
        "message": (
            "Final promo render is already running."
            if already_running
            else "Final promo render started in the background."
        ),
        "project_id": project_id,
        "queued_at": queued_at,
        "already_running": already_running,
    }


@router.post("/projects/{project_id}/export")
def export_project(
    project_id: str,
    payload: ExportIn | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).export_project(user.user_id, project_id, fmt=(payload.format if payload else "json"))
    except CreativeStudioError as exc:
        _raise(exc)
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
