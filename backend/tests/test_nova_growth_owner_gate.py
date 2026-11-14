"""Focused authorization regression for Growth Agent owner management APIs.

Run: pytest -q backend/tests/test_nova_growth_owner_gate.py
No database, provider calls, migrations, or external network required.
"""
import pytest
from fastapi import HTTPException

from app.auth import ROLE_ADMIN, ROLE_DISPATCHER, ROLE_DRIVER, ROLE_STAFF, ROLE_SUPER_ADMIN_SUPPORT, UserContext
from app.core.nova.growth_agent import tenant


def _user(role, *, org="test-tenant", user_id="synthetic-user"):
    return UserContext(
        user_id=user_id, email="synthetic@example.invalid",
        role=role, organization_id=org,
    )


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT])
def test_admin_roles_allowed_when_feature_on(monkeypatch, role):
    monkeypatch.setattr(tenant, "growth_agent_enabled", lambda: True)
    user = _user(role)
    assert tenant.require_growth_owner(user=user, _role_gate=object()) is user


@pytest.mark.parametrize("role", [ROLE_DISPATCHER, ROLE_DRIVER, ROLE_STAFF, "analytics_readonly"])
def test_non_owner_role_denied_when_feature_on(monkeypatch, role):
    monkeypatch.setattr(tenant, "growth_agent_enabled", lambda: True)
    with pytest.raises(HTTPException) as raised:
        tenant.require_growth_owner(user=_user(role), _role_gate=object())
    assert raised.value.status_code == 403


@pytest.mark.parametrize("role", [ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT])
def test_missing_tenant_or_identity_denied(monkeypatch, role):
    monkeypatch.setattr(tenant, "growth_agent_enabled", lambda: True)
    for org, ident in [(None, "synthetic-user"), ("test-tenant", "")]:
        with pytest.raises(HTTPException) as raised:
            tenant.require_growth_owner(user=_user(role, org=org, user_id=ident), _role_gate=object())
        assert raised.value.status_code == 403


def test_disabled_remains_not_found(monkeypatch):
    monkeypatch.setattr(tenant, "growth_agent_enabled", lambda: False)
    with pytest.raises(HTTPException) as raised:
        tenant.require_growth_owner(user=_user(ROLE_ADMIN), _role_gate=object())
    assert raised.value.status_code == 404


def test_owner_route_dependency_is_admin_only():
    # Ensure the actual FastAPI dependency is not the broad require_nova_access.
    import inspect
    from fastapi.params import Depends
    params = inspect.signature(tenant.require_growth_owner).parameters
    gate = params["_role_gate"].default
    assert isinstance(gate, Depends)
    assert gate.dependency is not None
    assert gate.dependency.__name__ == "_dependency"
    # Verify the role restriction in the dependency closure, not just its name.
    closure = gate.dependency.__closure__ or ()
    scopes = [cell.cell_contents for cell in closure]
    assert {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT} in scopes
    # Full JWT/session authorization is also covered by auth RBAC regressions.
