"""Enterprise security and multi-tenant foundation tests."""

from __future__ import annotations

import pytest

from fastapi import HTTPException

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_ANALYTICS_READONLY,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
)
from app.modules.health_isf.security import (
    authorize_subscription,
    enforce_tenant_scope,
    enforce_entity_tenant,
    ensure_write_access,
    ensure_admin_action,
)


def _ctx(role: str, org_id: str | None = "org_1") -> UserContext:
    return UserContext(
        user_id="user_1",
        email="user@example.com",
        role=role,
        organization_id=org_id,
        organization_name="Org",
    )


def test_rbac_write_permissions():
    ensure_write_access(_ctx(ROLE_ADMIN))
    ensure_write_access(_ctx(ROLE_SUPER_ADMIN_SUPPORT))
    ensure_write_access(_ctx(ROLE_DISPATCHER))

    with pytest.raises(HTTPException):
        ensure_write_access(_ctx(ROLE_DRIVER))
    with pytest.raises(HTTPException):
        ensure_write_access(_ctx(ROLE_PROVIDER))
    with pytest.raises(HTTPException):
        ensure_write_access(_ctx(ROLE_ANALYTICS_READONLY))


def test_admin_only_actions_protected():
    ensure_admin_action(_ctx(ROLE_ADMIN))
    ensure_admin_action(_ctx(ROLE_SUPER_ADMIN_SUPPORT))

    with pytest.raises(HTTPException):
        ensure_admin_action(_ctx(ROLE_DISPATCHER))


def test_tenant_scope_enforcement():
    dispatcher = _ctx(ROLE_DISPATCHER, org_id="org_1")
    assert enforce_tenant_scope(dispatcher, None) == "org_1"
    assert enforce_tenant_scope(dispatcher, "org_1") == "org_1"

    with pytest.raises(HTTPException):
        enforce_tenant_scope(dispatcher, "org_2")


def test_super_admin_can_scope_any_tenant():
    super_admin = _ctx(ROLE_SUPER_ADMIN_SUPPORT, org_id=None)
    assert enforce_tenant_scope(super_admin, "org_9") == "org_9"


def test_cross_tenant_entity_access_blocked():
    user = _ctx(ROLE_DISPATCHER, org_id="org_1")
    enforce_entity_tenant(user, "org_1")

    with pytest.raises(HTTPException):
        enforce_entity_tenant(user, "org_2")


def test_websocket_subscription_authorization_matrix():
    authorize_subscription(_ctx(ROLE_DISPATCHER), "dispatcher_board")
    authorize_subscription(_ctx(ROLE_DRIVER), "driver_dashboard")
    authorize_subscription(_ctx(ROLE_ANALYTICS_READONLY), "ride_updates")

    with pytest.raises(HTTPException):
        authorize_subscription(_ctx(ROLE_DRIVER), "dispatcher_board")
    with pytest.raises(HTTPException):
        authorize_subscription(_ctx(ROLE_PROVIDER), "dispatcher_board")


def test_privilege_escalation_prevention():
    analytics = _ctx(ROLE_ANALYTICS_READONLY, org_id="org_1")

    with pytest.raises(HTTPException):
        ensure_write_access(analytics)

    with pytest.raises(HTTPException):
        ensure_admin_action(analytics)
