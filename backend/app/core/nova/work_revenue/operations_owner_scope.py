"""Resolve a concrete Operations tenant from an already authenticated owner.

This module does not grant owner access, mount routes or create jobs.
The calling HTTP boundary must enforce require_work_revenue_owner first.
"""
from __future__ import annotations

from fastapi import HTTPException

from app.auth import UserContext
from app.core.nova.service import NovaCoreService


def resolve_operations_owner_scope(user: UserContext) -> str:
    """Never accept a global, missing, or switched tenant for Operations."""
    session_org = getattr(user, "organization_id", None)
    if (
        not isinstance(session_org, str)
        or not session_org.strip()
        or session_org != session_org.strip()
        or session_org.lower() == "global"
    ):
        raise HTTPException(status_code=403, detail="Tenant-specific organization required")
    try:
        org_id = NovaCoreService.resolve_organization_scope(user, None)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Authenticated organization required") from exc
    if (
        not isinstance(org_id, str)
        or not org_id.strip()
        or org_id.lower() == "global"
        or org_id != session_org
    ):
        raise HTTPException(status_code=403, detail="Tenant-specific organization required")
    return org_id



def owner_approval_identity(user: UserContext) -> tuple[str, str]:
    """Return tenant and actor IDs sourced only from the authenticated session.

    The HTTP boundary must enforce owner access first. This function does not
    record an approval or imply that a particular opportunity was approved.
    """
    tenant_id = resolve_operations_owner_scope(user)
    actor_id = getattr(user, "user_id", None)
    if (
        not isinstance(actor_id, str)
        or not actor_id.strip()
        or actor_id != actor_id.strip()
        or len(actor_id) > 256
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in actor_id)
    ):
        raise HTTPException(status_code=403, detail="Authenticated actor required")
    return tenant_id, actor_id
