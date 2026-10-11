"""Nova-authenticated casting reads. Registered on the existing API and default-off.

Production cannot enable these routes. The module does not import casting tables
at import time, does not accept uploads, and does not publish campaigns.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context

from .casting_access import CastingAccessDenied
from .casting_flags import casting_sandbox_writes_enabled, casting_staging_reads_enabled
from .casting_router_sandbox import sandbox_router

router = APIRouter(prefix="/api/nova/casting", tags=["Nova Casting (inactive)"])
CASTING_READS_DISABLED_DETAIL = "Casting application access is not enabled"


class CastingApplicationRead(BaseModel):
    id: str
    campaign_id: str
    status: str
    created_at: str


class CastingCampaignRead(BaseModel):
    id: str
    title: str
    category: str
    status: str
    created_at: str
    minimum_age: int


def casting_read_session():
    if not casting_staging_reads_enabled():
        raise HTTPException(status_code=503, detail=CASTING_READS_DISABLED_DETAIL)
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _session_identity(user: UserContext) -> tuple[str, str]:
    user_id = str(user.user_id or "").strip()
    tenant_id = str(user.organization_id or "").strip()
    if not user_id or not tenant_id:
        raise HTTPException(status_code=404, detail="Application unavailable")
    return user_id, tenant_id


@router.get("/readiness")
def casting_readiness(user: UserContext = Depends(get_current_user_context)):
    """Authenticated diagnostic. Intake and uploads stay off even when reads are staged."""
    if not user.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {
        "enabled": False,
        "applications_enabled": False,
        "media_uploads_enabled": False,
        "staging_reads_enabled": casting_staging_reads_enabled(),
        "sandbox_writes_enabled": casting_sandbox_writes_enabled(),
    }


router.include_router(sandbox_router)


@router.get(
    "/organizations/{organization_id}/applications/{application_id}",
    response_model=CastingApplicationRead,
)
def casting_application_read_draft(
    organization_id: str,
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_read_session),
):
    """Read one application. Identity comes from the Nova session, not the query string."""
    if not casting_staging_reads_enabled():
        raise HTTPException(status_code=503, detail=CASTING_READS_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    from .casting_db_reads import read_casting_application_for_nova_user
    try:
        return read_casting_application_for_nova_user(
            db=db, user_id=user_id, tenant_id=tenant_id,
            organization_id=organization_id, application_id=application_id,
        )
    except CastingAccessDenied:
        raise HTTPException(status_code=404, detail="Application unavailable")


@router.get(
    "/organizations/{organization_id}/campaigns/{campaign_id}",
    response_model=CastingCampaignRead,
)
def casting_campaign_read_draft(
    organization_id: str,
    campaign_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(casting_read_session),
):
    """Read one unpublished campaign for a verified member of that organization."""
    if not casting_staging_reads_enabled():
        raise HTTPException(status_code=503, detail=CASTING_READS_DISABLED_DETAIL)
    user_id, tenant_id = _session_identity(user)
    from .casting_db_reads import read_casting_campaign_for_nova_user
    try:
        return read_casting_campaign_for_nova_user(
            db=db, user_id=user_id, tenant_id=tenant_id,
            organization_id=organization_id, campaign_id=campaign_id,
        )
    except CastingAccessDenied:
        raise HTTPException(status_code=404, detail="Campaign unavailable")
