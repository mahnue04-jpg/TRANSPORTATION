"""Enterprise RBAC and tenant-scoping helpers for Health ISF."""

from __future__ import annotations

from fastapi import HTTPException

from app.auth import (
    UserContext,
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_ANALYTICS_READONLY,
    ROLE_SUPER_ADMIN_SUPPORT,
    normalize_role,
    is_super_admin,
)


ALLOWED_SUBSCRIPTIONS_BY_ROLE = {
    ROLE_ADMIN: {"dispatcher_board", "driver_dashboard", "ride_updates", "driver_availability", "workflow_events", "escalation_queue", "incident_updates"},
    ROLE_SUPER_ADMIN_SUPPORT: {"dispatcher_board", "driver_dashboard", "ride_updates", "driver_availability", "workflow_events", "escalation_queue", "incident_updates"},
    ROLE_DISPATCHER: {"dispatcher_board", "ride_updates", "driver_availability", "workflow_events", "escalation_queue", "incident_updates"},
    ROLE_STAFF: {"dispatcher_board", "ride_updates", "driver_availability", "workflow_events"},
    ROLE_SUPERVISOR: {"dispatcher_board", "ride_updates", "driver_availability", "workflow_events", "escalation_queue", "incident_updates"},
    ROLE_DRIVER: {"driver_dashboard"},
    ROLE_PROVIDER: {"ride_updates"},
    ROLE_ANALYTICS_READONLY: {"ride_updates", "driver_availability"},
}

_SUBSCRIPTION_ALIASES = {
    "dispatcher": "dispatcher_board",
    "dispatcher-board": "dispatcher_board",
    "rides": "ride_updates",
    "ride": "ride_updates",
    "drivers": "driver_availability",
    "driver-status": "driver_availability",
    "workflow": "workflow_events",
    "workflows": "workflow_events",
}


def _canonicalize_subscription_type(subscription_type: str) -> str:
    raw = str(subscription_type or "").strip().lower()
    if not raw:
        return ""
    return _SUBSCRIPTION_ALIASES.get(raw, raw)


def enforce_tenant_scope(user: UserContext, requested_org_id: str | None) -> str:
    """Return effective org_id if permitted; raise on cross-tenant access."""
    if is_super_admin(user):
        effective_org_id = requested_org_id or user.organization_id
        if not effective_org_id:
            raise HTTPException(status_code=400, detail="organization_id required for super-admin scope")
        return effective_org_id

    if not user.organization_id:
        raise HTTPException(status_code=403, detail="User missing organization scope")

    if requested_org_id and requested_org_id != user.organization_id:
        raise HTTPException(status_code=403, detail="Cross-tenant access denied")

    return user.organization_id


def enforce_entity_tenant(user: UserContext, entity_org_id: str) -> None:
    if is_super_admin(user):
        return
    if not user.organization_id or user.organization_id != entity_org_id:
        raise HTTPException(status_code=403, detail="Entity is outside tenant boundary")


def authorize_subscription(user: UserContext, subscription_type: str) -> str:
    role = normalize_role(user.role)
    canonical_type = _canonicalize_subscription_type(subscription_type)
    if not canonical_type:
        raise HTTPException(status_code=400, detail="subscription_type required")
    allowed = ALLOWED_SUBSCRIPTIONS_BY_ROLE.get(role, set())
    if canonical_type not in allowed:
        raise HTTPException(status_code=403, detail="Subscription not allowed for role")
    return canonical_type


def ensure_read_access(user: UserContext) -> None:
    role = normalize_role(user.role)
    if role not in {
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_DISPATCHER,
        ROLE_STAFF,
        ROLE_SUPERVISOR,
        ROLE_DRIVER,
        ROLE_PROVIDER,
        ROLE_ANALYTICS_READONLY,
    }:
        raise HTTPException(status_code=403, detail="Role cannot access Health ISF")


def ensure_write_access(user: UserContext) -> None:
    role = normalize_role(user.role)
    if role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_DISPATCHER}:
        raise HTTPException(status_code=403, detail="Role cannot perform write actions")


def ensure_admin_action(user: UserContext) -> None:
    role = normalize_role(user.role)
    if role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise HTTPException(status_code=403, detail="Admin action not permitted")
