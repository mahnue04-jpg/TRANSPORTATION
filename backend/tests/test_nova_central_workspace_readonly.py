"""HTTP regression for the default-off Central Workspace readiness route.

Dependency overrides represent synthetic signed-in users. They do NOT prove
the JWT backend itself; app auth regression must gate any staged enablement.
"""
import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import ROLE_ADMIN, ROLE_STAFF, UserContext, create_access_token
from app.core.nova.workspace import central_journey_readonly as module


def _user(role=ROLE_ADMIN, org="org-A", user_id="synthetic-owner"):
    return UserContext(
        user_id=user_id, email="nobody@example.invalid",
        role=role, organization_id=org,
    )


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(module.router)
    # Override only for synthetic HTTP unit coverage; do not use in runtime.
    from app.auth import get_current_user_context
    app.dependency_overrides[get_current_user_context] = lambda: _user()
    yield app
    app.dependency_overrides.clear()


def _request(api):
    token = create_access_token({
        "sub": "synthetic-owner", "role": "admin",
        "organization_id": "org-A", "auth_version": 0,
    })
    with TestClient(api) as client:
        return client.get("/central/journeys", headers={"Authorization": "Bearer " + token})


def test_default_off_is_not_found(monkeypatch, api):
    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", raising=False)
    # Role gate intentionally overridden for isolated route response test.
    role_gate = inspect.signature(module.list_central_journeys).parameters["_role_guard"].default.dependency
    api.dependency_overrides[role_gate] = lambda: object()
    assert _request(api).status_code == 404


def test_explicit_flag_returns_empty_not_connected_view(monkeypatch, api):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    role_gate = inspect.signature(module.list_central_journeys).parameters["_role_guard"].default.dependency
    api.dependency_overrides[role_gate] = lambda: object()
    response = _request(api)
    assert response.status_code == 200
    assert response.json() == {
        "mode": "read_only",
        "integration_status": "not_connected",
        "journeys": [],
        "approval_actions_enabled": False,
        "customer_data_connected": False,
    }


@pytest.mark.parametrize("role,org,uid", [
    (ROLE_STAFF, "org-A", "u1"),
    (ROLE_ADMIN, "", "u1"),
    (ROLE_ADMIN, "global", "u1"),
    (ROLE_ADMIN, "org-A", ""),
])
def test_missing_or_unauthorized_owner_rejected(monkeypatch, api, role, org, uid):
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    from app.auth import get_current_user_context
    api.dependency_overrides[get_current_user_context] = lambda: _user(role, org, uid)
    role_gate = inspect.signature(module.list_central_journeys).parameters["_role_guard"].default.dependency
    api.dependency_overrides[role_gate] = lambda: object()
    assert _request(api).status_code == 403


def test_route_requires_actual_auth_dependencies():
    route = next(r for r in module.router.routes if r.path.endswith("/journeys"))
    dependency_names = [d.call.__name__ for d in route.dependant.dependencies]
    assert "get_current_user_context" in dependency_names
    assert "_dependency" in dependency_names
    guard = inspect.signature(module.list_central_journeys).parameters["_role_guard"].default.dependency
    assert any(ROLE_ADMIN in v.cell_contents for v in (guard.__closure__ or ())
               if isinstance(v.cell_contents, set))


def test_readonly_only_get_route():
    assert [r.methods for r in module.router.routes] == [{"GET"}]


def test_mounted_workspace_route_defaults_off(monkeypatch):
    """Exercise the real Workspace router mount, not just the nested router."""
    from app.auth import get_current_user_context
    from app.core.nova.router import require_nova_access
    from app.core.nova.workspace.router import router as workspace_router

    monkeypatch.delenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", raising=False)
    app = FastAPI()
    app.include_router(workspace_router)
    app.dependency_overrides[get_current_user_context] = lambda: _user()
    app.dependency_overrides[require_nova_access] = lambda: object()
    guard = inspect.signature(module.list_central_journeys).parameters["_role_guard"].default.dependency
    app.dependency_overrides[guard] = lambda: object()
    with TestClient(app) as client:
        token = create_access_token({
            "sub": "synthetic-owner", "role": "admin",
            "organization_id": "org-A", "auth_version": 0,
        })
        response = client.get("/api/nova/workspace/central/journeys", headers={"Authorization": "Bearer " + token})
    assert response.status_code == 404


def test_mounted_workspace_route_is_empty_on_opt_in(monkeypatch):
    from app.auth import get_current_user_context
    from app.core.nova.router import require_nova_access
    from app.core.nova.workspace.router import router as workspace_router

    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    app = FastAPI()
    app.include_router(workspace_router)
    app.dependency_overrides[get_current_user_context] = lambda: _user()
    app.dependency_overrides[require_nova_access] = lambda: object()
    guard = inspect.signature(module.list_central_journeys).parameters["_role_guard"].default.dependency
    app.dependency_overrides[guard] = lambda: object()
    token = create_access_token({
        "sub": "synthetic-owner", "role": "admin",
        "organization_id": "org-A", "auth_version": 0,
    })
    with TestClient(app) as client:
        response = client.get(
            "/api/nova/workspace/central/journeys",
            headers={"Authorization": "Bearer " + token},
        )
    assert response.status_code == 200
    assert response.json()["integration_status"] == "not_connected"
    assert response.json()["journeys"] == []



def test_real_auth_dependency_rejects_anonymous_request(monkeypatch):
    """No auth overrides: exercise the actual JWT-aware dependency chain."""
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.get("/central/journeys")
    assert response.status_code == 401


def test_real_auth_dependency_rejects_invalid_bearer(monkeypatch):
    """Malformed credentials must not reach a read-only data response."""
    monkeypatch.setenv("NOVA_CENTRAL_JOURNEY_READONLY_ENABLED", "true")
    app = FastAPI()
    app.include_router(module.router)
    with TestClient(app) as client:
        response = client.get(
            "/central/journeys",
            headers={"Authorization": "Bearer definitely-not-a-valid-jwt"},
        )
    assert response.status_code == 401
