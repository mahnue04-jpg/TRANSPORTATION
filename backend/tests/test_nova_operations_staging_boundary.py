"""Static fail-closed checks for the unregistered Operations staging router.

Use AST inspection to avoid importing the production Work & Revenue router into
the lightweight offline CI. This is NOT an integration test of live JWT auth.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "app/core/nova/work_revenue/operations_staging_boundary.py"


def test_staging_approval_routes_remain_owner_gated_and_disabled():
    code = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(code)
    funcs = {
        node.name: node for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {"disabled_approval_staging", "disabled_review_staging"} <= funcs.keys()
    assert "Depends(require_nova_access)" in code
    assert "Depends(require_work_revenue_owner)" in code
    assert "owner_approval_identity(user)" in code
    assert "status_code=503" in code
    assert "approve_and_handoff_offline" not in code
    assert "review_approved_assignment_offline" not in code
    for function in funcs.values():
        calls = [
            n.func.id for n in ast.walk(function)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        assert "owner_approval_identity" in calls
        assert "HTTPException" in calls
        assert "Depends(require_work_revenue_owner)" in ast.unparse(function)


def test_staging_approval_router_not_registered_in_known_entrypoints():
    for path in (
        ROOT / "main.py",
        ROOT / "app/main.py",
        ROOT / "app/core/nova/router.py",
        ROOT / "app/core/nova/work_revenue/router.py",
    ):
        if path.exists():
            assert "operations_staging_boundary" not in path.read_text(encoding="utf-8")



def test_fastapi_runtime_router_keeps_guards_and_denies_owner_calls(monkeypatch):
    """Build the actual APIRouter from its AST without importing production auth.

    This verifies FastAPI route/dependency wiring and handler failure behavior;
    it is not a live JWT or authenticated HTTP integration test.
    """
    from types import SimpleNamespace
    from fastapi import APIRouter, Depends, HTTPException
    from fastapi.routing import APIRoute
    import pytest

    from app.core.nova.work_revenue import operations_owner_scope as scope

    def require_nova_access():
        return None

    def require_work_revenue_owner():
        return None

    monkeypatch.setattr(
        scope.NovaCoreService, "resolve_organization_scope",
        lambda user, requested: user.organization_id,
    )

    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "router"
                for target in node.targets
            )
        ) or (
            isinstance(node, ast.FunctionDef)
            and node.name in {"disabled_approval_staging", "disabled_review_staging"}
        )
    ]
    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")],
                level=0,
            ),
            *selected,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    namespace = {
        "APIRouter": APIRouter,
        "Depends": Depends,
        "HTTPException": HTTPException,
        "UserContext": type("UserContext", (), {}),
        "require_nova_access": require_nova_access,
        "require_work_revenue_owner": require_work_revenue_owner,
        "owner_approval_identity": scope.owner_approval_identity,
    }
    exec(compile(isolated, str(SOURCE), "exec"), namespace)
    router = namespace["router"]
    routes = [route for route in router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 2
    for route in routes:
        assert route.methods == {"POST"}
        required = [dep.call for dep in route.dependant.dependencies]
        assert require_nova_access in required
        assert require_work_revenue_owner in required
        owner = SimpleNamespace(organization_id="synthetic-tenant", user_id="owner-a")
        with pytest.raises(HTTPException) as stopped:
            route.endpoint(opportunity_id="synthetic-opportunity", user=owner)
        assert stopped.value.status_code == 503
        with pytest.raises(HTTPException) as denied:
            route.endpoint(
                opportunity_id="synthetic-opportunity",
                user=SimpleNamespace(organization_id="global", user_id="owner-a"),
            )
        assert denied.value.status_code == 403
