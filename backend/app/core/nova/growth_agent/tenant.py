"""Deny-by-default tenant resolution for Growth Agent."""

from __future__ import annotations

from fastapi import Depends, HTTPException

from app.auth import UserContext, get_current_user_context
from app.core.nova.growth_agent.errors import CrossTenantError, FeatureDisabledError, TenantRequiredError
from app.core.nova.growth_agent.flags import growth_agent_enabled
from app.core.nova.router import require_nova_access
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
    user: UserContext = Depends(require_nova_access),
) -> UserContext:
    """Authenticated Nova user; surface still gated by NOVA_GROWTH_AGENT_ENABLED."""
    if not growth_agent_enabled():
        raise HTTPException(status_code=404, detail="Growth Agent is disabled")
    if not user.organization_id and not user.user_id:
        raise HTTPException(status_code=403, detail="Authenticated owner required")
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
