"""Deny-by-default tenant resolution for Growth Agent."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from app.auth import (
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.growth_agent.errors import CrossTenantError, FeatureDisabledError, TenantRequiredError
from app.core.nova.growth_agent.flags import growth_agent_enabled
from app.core.nova.service import NovaCoreService


def require_growth_agent_enabled() -> None:
    if not growth_agent_enabled():
        raise FeatureDisabledError()


def resolve_org(
    user: UserContext,
    requested_organization_id: str | None = None,
) -> str:
    """Resolve org scope. Absent tenant context → deny (no global fallback)."""
    try:
        org_id = NovaCoreService.resolve_organization_scope(user, requested_organization_id)
    except ValueError as exc:
        raise CrossTenantError(str(exc)) from exc
    if not org_id or org_id == "global":
        raise TenantRequiredError("Growth Agent requires an organization_id; global scope is denied")
    return org_id


def require_growth_owner(
    user: UserContext = Depends(get_current_user_context),
    _role_gate=Depends(require_any_role(ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT)),
) -> UserContext:
    """Admin-level Nova session required for Growth Agent management APIs.

    The role dependency validates active JWT/authorized roles against the DB.
    A defense-in-depth check on UserContext.role also denies role mismatch.
    This does not authorize external sends, paid services or production rollout.
    """
    if not growth_agent_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent is disabled")
    if user.role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise HTTPException(status_code=403, detail="Growth Agent owner role required")
    if not user.user_id or not user.organization_id:
        raise HTTPException(status_code=403, detail="Growth Agent tenant and owner required")
    return user


def org_from_user(
    user: UserContext = Depends(get_current_user_context),
    organization_id: str | None = None,
) -> str:
    if not growth_agent_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent is disabled")
    try:
        return resolve_org(user, organization_id)
    except (TenantRequiredError, CrossTenantError) as exc:
        raise HTTPException(status_code=exc.http_status, detail=exc.message) from exc
