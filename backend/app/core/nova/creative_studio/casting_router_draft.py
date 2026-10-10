"""Dormant Nova-authenticated casting router, not included by app.main.

A real route must additionally use database-backed membership verification and
application retrieval. For now this router exposes no applicant records.
"""
from fastapi import APIRouter, Depends, HTTPException
from app.auth import UserContext, get_current_user_context

router = APIRouter(prefix="/api/nova/casting", tags=["Nova Casting (inactive)"])


@router.get("/readiness")
def casting_readiness(user: UserContext = Depends(get_current_user_context)):
    """Authenticated diagnostic only; refuses production readiness."""
    if not user.user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return {"enabled": False, "applications_enabled": False, "media_uploads_enabled": False}
