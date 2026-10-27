"""HTTP surface for the default-off synthetic media slice."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field

from app.auth import UserContext, get_current_user_context
from app.core.nova.intelligence.audit import record_audit
from app.core.nova.intelligence.demo import render_demo_page
from app.core.nova.intelligence.flags import media_enabled
from app.core.nova.intelligence.jobs import (
    QuotaError,
    RejectedSource,
    create_job,
    erase_job,
    public_result,
    public_status,
    visible_job,
)
from app.core.nova.intelligence.messages import (
    MEDIA_TYPE_REJECTED,
    NOT_FOUND,
    SIZE_REJECTED,
    TENANT_REQUIRED,
)

_QUOTA_DETAILS = {MEDIA_TYPE_REJECTED, SIZE_REJECTED}


class FlaggedRoute(APIRoute):
    """Hide every route until the flag is exactly enabled, before auth runs."""

    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request: Request):
            if not media_enabled():
                return JSONResponse(status_code=404, content={"detail": NOT_FOUND})
            return await original(request)

        return guarded


class SourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=500)


class JobIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: SourceIn
    media_type: str = Field(min_length=1, max_length=64)
    declared_bytes: int
    options: dict[str, Any] | None = None


router = APIRouter(route_class=FlaggedRoute, tags=["nova-intelligence-media"])


def _tenant_id(user: UserContext) -> str:
    tenant_id = (user.organization_id or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=403, detail=TENANT_REQUIRED)
    return tenant_id


def _quota_detail(exc: QuotaError) -> str:
    if exc.detail in _QUOTA_DETAILS:
        return exc.detail
    return SIZE_REJECTED


@router.post("/api/nova/intelligence/media/jobs", status_code=201)
def create_media_job(
    body: JobIn,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, str]:
    tenant_id = _tenant_id(user)
    try:
        job = create_job(
            tenant_id=tenant_id,
            source_type=body.source.type,
            source_value=body.source.value,
            media_type=body.media_type,
            declared_bytes=body.declared_bytes,
        )
    except RejectedSource:
        raise HTTPException(status_code=400, detail=RejectedSource.detail) from None
    except QuotaError as exc:
        raise HTTPException(status_code=400, detail=_quota_detail(exc)) from None
    record_audit(
        job_id=job.job_id,
        tenant_id=job.tenant_id,
        status=job.status,
        fixture_id=job.fixture_id,
    )
    return {"job_id": job.job_id, "status": job.status}


@router.get("/api/nova/intelligence/media/jobs/{job_id}")
def read_media_job(
    job_id: str,
    user: UserContext = Depends(get_current_user_context),
) -> dict:
    job = visible_job(job_id, _tenant_id(user))
    if job is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return public_status(job)


@router.get("/api/nova/intelligence/media/jobs/{job_id}/result")
def read_media_result(
    job_id: str,
    user: UserContext = Depends(get_current_user_context),
) -> dict:
    job = visible_job(job_id, _tenant_id(user))
    if job is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return public_result(job)


@router.delete("/api/nova/intelligence/media/jobs/{job_id}")
def delete_media_job(
    job_id: str,
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, str]:
    tenant_id = _tenant_id(user)
    erased = erase_job(job_id, tenant_id)
    if erased is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    record_audit(
        job_id=erased.job_id,
        tenant_id=erased.tenant_id,
        status="erased",
        fixture_id=erased.fixture_id,
    )
    return {"job_id": erased.job_id, "status": "erased"}


@router.get("/nova/intelligence/media-demo")
def media_demo(user: UserContext = Depends(get_current_user_context)) -> HTMLResponse:
    _tenant_id(user)
    response = HTMLResponse(content=render_demo_page())
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
