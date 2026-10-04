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
from app.core.nova.creative_studio.providers import CONFIG_REQUIRED, talking_presenter_provider, video_provider
from app.db.session import SessionLocal, get_db
from app.core.nova.creative_studio.drama import SAMPLE

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


class DramaCharacterIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=600)
    voice: str = Field(min_length=1, max_length=30)


class DramaIn(BaseModel):
    setting: str = Field(min_length=1, max_length=1000)
    characters: list[DramaCharacterIn] = Field(min_length=2, max_length=2)
    dialogue: str = Field(min_length=1, max_length=3500)


_drama_lock = threading.Lock()
_drama_workers: set[str] = set()


def _run_drama_background(owner_id: str, project_id: str, job_id: str, action: str):
    db = SessionLocal()
    try:
        service = get_service(db)
        job = next(row for row in service.store.list_jobs(project_id, owner_id) if row.id == job_id)
        service._finish_job(job, status="RUNNING", message=f"Short drama {action} in progress.", asset_ids=[])
        if action == "voices":
            service.generate_drama_voices(owner_id, project_id, job=job)
        else:
            service.assemble_drama(owner_id, project_id, job=job)
    except Exception:
        logger.exception("Short drama worker failed: %s", job_id)
    finally:
        db.close()
        with _drama_lock:
            _drama_workers.discard(job_id)


@router.get("/drama/sample")
def drama_sample(user: UserContext = Depends(get_current_user_context)):
    _require_owner(user)
    return SAMPLE


@router.post("/projects/{project_id}/drama/plan")
def save_drama_plan(project_id: str, payload: DramaIn,
                    user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _require_owner(user)
    try:
        return get_service(db).save_drama_plan(user.user_id, project_id, payload.model_dump())
    except CreativeStudioError as exc:
        _raise(exc)


@router.post("/projects/{project_id}/drama/{action}")
def generate_drama(project_id: str, action: str, background_tasks: BackgroundTasks,
                   user: UserContext = Depends(get_current_user_context), db: Session = Depends(get_db)):
    _require_owner(user)
    if action not in {"voices", "render"}:
        raise HTTPException(status_code=404, detail="Unknown drama action")
    service = get_service(db)
    try:
        service._drama_plan(user.user_id, project_id)
        kind = "voice" if action == "voices" else "short_video_assembly"
        with _drama_lock:
            for row in service.store.list_jobs(project_id, user.user_id):
                if row.kind != kind or row.status not in {"QUEUED", "RUNNING"}:
                    continue
                if row.id in _drama_workers:
                    return {"status": "PROCESSING", "job": row.as_dict(), "already_running": True}
                service._finish_job(row, status="ERROR", message="Worker was interrupted; retry reuses completed dialogue assets.", asset_ids=row.result_asset_ids)
            job = service._start_job(user.user_id, project_id, kind)
            service._finish_job(job, status="QUEUED", message=f"Short drama {action} queued.", asset_ids=[])
            _drama_workers.add(job.id)
            background_tasks.add_task(_run_drama_background, user.user_id, project_id, job.id, action)
        return {"status": "PROCESSING", "job": job.as_dict()}
    except CreativeStudioError as exc:
        _raise(exc)


class ExportIn(BaseModel):
    format: str = "json"


class PresenterIn(BaseModel):
    script: str = Field(min_length=1, max_length=1600)
    presenter_style: str = Field(default="warm professional small-business presenter", max_length=240)
    presenter_mode: str = Field(default="head", pattern="^(head|half_body|full_body)$")
    motion_style: str = Field(default="calm_professional", pattern="^(calm_professional|friendly_explainer|energetic_promo)$")
    framing: str = Field(default="close_up", pattern="^(close_up|waist_up|full_frame)$")
    output_preset: str = Field(default="9:16", pattern="^(9:16|1:1|16:9)$")


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
        presenter_meta = {
            "presenter_style": payload.presenter_style,
            "presenter_mode": payload.presenter_mode,
            "motion_style": payload.motion_style,
            "framing": {"half_body": "waist_up", "full_body": "full_frame"}.get(payload.presenter_mode, payload.framing),
            "output_preset": payload.output_preset,
            "talking_presenter": payload.presenter_mode == "head",
            "lip_sync": payload.presenter_mode == "head",
            "body_motion_review_required": payload.presenter_mode != "head",
            "preview": True,
        }
        service._save_text_asset(
            owner_id=user.user_id,
            project_id=project_id,
            kind="presenter_script",
            title="Talking presenter preview script",
            content=payload.script,
            status="GENERATED",
            metadata=presenter_meta,
            url=None,
        )

        # Talking-head mode keeps the dedicated D-ID lip-sync path.
        if payload.presenter_mode == "head":
            provider_name = str(os.getenv("NOVA_TALKING_PRESENTER_PROVIDER") or "").strip()
            if not provider_name:
                return {
                    "status": "CONFIG_REQUIRED",
                    "message": "Presenter script is saved. Connect a lip-sync/talking-avatar provider before Nova generates a real talking face.",
                    "script": payload.script,
                    **presenter_meta,
                }
            images = [
                asset for asset in service.store.list_assets(project_id, user.user_id)
                if asset.kind == "image" and asset.url and str(asset.status or "").upper() == "GENERATED"
            ]
            if not images:
                return {
                    "status": "CONFIG_REQUIRED",
                    "message": "Generate or select a clean presenter image before creating the talking presenter preview.",
                    "script": payload.script,
                    **presenter_meta,
                }
            presenter_image = images[-1]
            result = talking_presenter_provider().generate(
                presenter_image_url=str(presenter_image.url),
                script=payload.script,
            )
            source_image_asset_id = presenter_image.id
            title = "Talking presenter preview"
        else:
            # Half/full-body motion uses a newly generated clean source image and
            # the existing motion-video provider instead of pretending D-ID head
            # animation is full-body movement.
            motion_provider = video_provider()
            motion_status = motion_provider.status()
            if motion_status.status != "AVAILABLE":
                return {
                    "status": motion_status.status,
                    "message": motion_status.message,
                    "script": payload.script,
                    **presenter_meta,
                    "publish_ready": False,
                }
            framing_text = {
                "half_body": "waist-up presenter with both hands visible and natural arm gestures",
                "full_body": "full-body standing presenter visible head-to-toe with room for natural body movement",
            }[payload.presenter_mode]
            motion_text = {
                "calm_professional": "calm professional gestures, subtle natural movement",
                "friendly_explainer": "friendly explanatory hand gestures and relaxed natural movement",
                "energetic_promo": "confident energetic promotional gestures while staying professional",
            }[payload.motion_style]
            source_prompt = (
                "Photorealistic business presenter, " + framing_text + ". "
                "Professional modern small-business setting, clean lighting, realistic anatomy, natural hands, "
                "camera-ready wardrobe, no text, no logos, no watermarks, no provider marks. "
                "Keep the presenter centered and leave safe space for captions and an official AMICOR logo overlay later. "
                "Aspect ratio " + payload.output_preset + "."
            )
            image_result = service.request_image_generation(
                user.user_id,
                project_id,
                aspect_ratio=payload.output_preset,
                prompt=source_prompt,
            )
            source_url = str(image_result.get("url") or "").strip()
            if not source_url:
                provider_info = image_result.get("provider") or {}
                return {
                    "status": str(provider_info.get("status") or "ERROR"),
                    "message": provider_info.get("message") or "Nova could not generate a clean presenter source image.",
                    "script": payload.script,
                    **presenter_meta,
                }
            source_asset = image_result.get("asset") or {}
            source_image_asset_id = source_asset.get("id")
            motion_prompt = (
                f"{framing_text}; {motion_text}. The presenter addresses the camera naturally. "
                "Keep facial identity stable, preserve realistic hands and body proportions, avoid text and logos, "
                "and do not add watermarks. This is a clean business social-media presenter shot."
            )
            result = motion_provider.generate(
                brief={
                    "project_id": project_id,
                    "title": "Nova presenter motion",
                    "objective": payload.script[:600],
                    "platform": "TikTok" if payload.output_preset == "9:16" else "YouTube",
                    "aspect_ratio": payload.output_preset,
                    "prompt_text": motion_prompt,
                    "prompt_image_url": source_url,
                }
            )
            title = "Half-body presenter motion" if payload.presenter_mode == "half_body" else "Full-body presenter motion"

        status = str(result.get("status") or CONFIG_REQUIRED)
        generated_url = str(result.get("url") or "").strip() if result.get("asset_generated") else None
        provider_watermark_free = bool(result.get("watermark_free", False))
        # Body-motion video has no narration/lip-sync adapter and still needs
        # visual review of actual head-to-toe movement before final delivery.
        publish_ready = bool(generated_url and provider_watermark_free and payload.presenter_mode == "head")
        quality_state = "PUBLISH_READY" if publish_ready else ("PREVIEW_ONLY" if generated_url else status)

        asset = service._save_text_asset(
            owner_id=user.user_id,
            project_id=project_id,
            kind="presenter_video",
            title=title,
            content=payload.script,
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={
                **presenter_meta,
                "source_image_asset_id": source_image_asset_id,
                "provider_result": result,
                "quality_state": quality_state,
                "publish_ready": publish_ready,
                "watermark_policy": "Nova never removes provider watermarks. Use a provider output licensed and delivered watermark-free for final publishing.",
            },
            url=generated_url,
        )
        message = result.get("message")
        if generated_url and not publish_ready:
            message = (
                f"{message or 'Presenter render generated.'} " +
                ("Saved as PREVIEW_ONLY: review actual body movement; narration and lip-sync are not generated by this motion path. "
                 if payload.presenter_mode != "head" else "Saved as PREVIEW_ONLY until the provider confirms a licensed watermark-free final output. ")
            )
        return {
            "status": status,
            "message": message,
            "script": payload.script,
            **presenter_meta,
            "quality_state": quality_state,
            "publish_ready": publish_ready,
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
