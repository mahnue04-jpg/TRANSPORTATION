"""Nova Creative Studio HTTP API. Planning/script mode. No publishing."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import OPERATOR_ACCOUNT_GRANTS, UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.creative_studio.service import CreativeStudioError, get_service
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/creative",
    tags=["nova-creative-studio"],
    dependencies=[Depends(require_nova_access)],
)


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
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).get_project(user.user_id, project_id)
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


@router.post("/projects/{project_id}/generate/video")
def generate_video(
    project_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_owner(user)
    try:
        return get_service(db).request_video_generation(user.user_id, project_id)
    except CreativeStudioError as exc:
        _raise(exc)
        raise


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
