"""Dormant Nova-authenticated casting router, not included by app.main.

A real route must additionally use database-backed membership verification and
application retrieval. For now this router exposes no applicant records.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from .casting_access import CastingAccessDenied
from .casting_db_reads import read_casting_application_for_nova_user
from app.auth import UserContext, get_current_user_context

router = APIRouter(prefix="/api/nova/casting", tags=["Nova Casting (inactive)"])


@router.get("/readiness")
def casting_readiness(user: UserContext = Depends(get_current_user_context)):
    """Authenticated diagnostic only; refuses production readiness."""
    if not user.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"enabled": False, "applications_enabled": False, "media_uploads_enabled": False}


@router.get("/organizations/{organization_id}/applications/{application_id}")
def casting_application_read_draft(
    organization_id: str,
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Explicitly disabled until casting tables and membership checks are deployed."""
    CASTING_READ_ENABLED = False
    if not CASTING_READ_ENABLED:
        raise HTTPException(status_code=503, detail="Casting application access is not enabled")
    if not user.organization_id:
        raise HTTPException(status_code=403, detail="Casting membership not verified")
    try:
        return read_casting_application_for_nova_user(
            db=db, user_id=user.user_id, tenant_id=user.organization_id,
            organization_id=organization_id, application_id=application_id,
        )
    except CastingAccessDenied:
        raise HTTPException(status_code=404, detail="Application unavailable")
