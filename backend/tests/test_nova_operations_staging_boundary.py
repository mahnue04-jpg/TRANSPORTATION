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


    # Exercise request routing and dependency overrides through a real ASGI
    # TestClient. These overrides are synthetic and do not validate JWTs.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_nova_access] = lambda: None
    paths = [
        "/api/nova/work/operations/owner-approvals/synthetic-opportunity",
        "/api/nova/work/operations/owner-approvals/synthetic-opportunity/review",
    ]
    with TestClient(app) as client:
        def no_session():
            raise HTTPException(status_code=401, detail="synthetic unauthenticated")

        app.dependency_overrides[require_work_revenue_owner] = no_session
        for path in paths:
            response = client.post(path)
            assert response.status_code == 401
        app.dependency_overrides[require_work_revenue_owner] = lambda: SimpleNamespace(
            organization_id="synthetic-tenant", user_id="owner-a",
        )
        for path in paths:
            response = client.post(path)
            assert response.status_code == 503
            assert "disabled" in response.json()["detail"].lower()
        app.dependency_overrides[require_work_revenue_owner] = lambda: SimpleNamespace(
            organization_id="global", user_id="owner-a",
        )
        for path in paths:
            response = client.post(path)
            assert response.status_code == 403



def test_real_work_revenue_owner_guard_denies_nonowners():
    """Execute the genuine owner guard body, not a replacement allowlist check.

    Only heavy router imports are isolated. This does not verify signed JWT
    parsing, persistence of owner grants, or a production user session.
    """
    from types import SimpleNamespace
    from fastapi import Depends, HTTPException
    import pytest

    owner_source = (
        ROOT / "app/core/nova/work_revenue/router.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(owner_source)
    target = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "require_work_revenue_owner"
    )
    isolated = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__",
                names=[ast.alias(name="annotations")], level=0,
            ),
            target,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(isolated)
    grants = {"owner@synthetic.invalid"}
    access_seen = []

    def customer_access(_db, *, organization_id, user_id):
        access_seen.append((organization_id, user_id))
        return {"nova_saas_customer": True}

    namespace = {
        "Depends": Depends,
        "get_current_user_context": lambda: None,
        "get_db": lambda: None,
        "HTTPException": HTTPException,
        "_work_revenue_owner_emails": lambda: grants,
        "customer_access": customer_access,
    }
    exec(compile(isolated, "work_revenue/router.py", "exec"), namespace)
    guard = namespace["require_work_revenue_owner"]
    owner = SimpleNamespace(
        email="owner@synthetic.invalid",
        organization_id="tenant-a",
        user_id="owner-001",
    )
    assert guard(user=owner, db=object()) is owner
    assert access_seen == []
    customer = SimpleNamespace(
        email="customer@synthetic.invalid",
        organization_id="tenant-a",
        user_id="customer-001",
    )
    with pytest.raises(HTTPException) as denied:
        guard(user=customer, db=object())
    assert denied.value.status_code == 403
    assert access_seen == [("tenant-a", "customer-001")]
    access_seen.clear()
    # Non-owner must also be denied when SaaS classification is absent.
    namespace["customer_access"] = lambda _db, **kwargs: {
        "nova_saas_customer": False,
    }
    with pytest.raises(HTTPException) as denied_again:
        guard(user=customer, db=object())
    assert denied_again.value.status_code == 403



def test_http_routes_enforce_actual_owner_guard_with_synthetic_session(monkeypatch):
    """HTTP wiring with the production owner guard body; JWT is substituted.

    Both real functions are extracted from source to avoid unrelated imports.
    We substitute session lookup and customer lookup, not the owner guard.
    """
    from types import SimpleNamespace
    from fastapi import APIRouter, Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from app.core.nova.work_revenue import operations_owner_scope as scope

    owner_tree = ast.parse(
        (ROOT / "app/core/nova/work_revenue/router.py").read_text(encoding="utf-8")
    )
    guard_node = next(
        node for node in owner_tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "require_work_revenue_owner"
    )
    namespace = {
        "Depends": Depends,
        "HTTPException": HTTPException,
        "get_current_user_context": lambda: None,
        "get_db": lambda: None,
        "_work_revenue_owner_emails": lambda: {"owner@synthetic.invalid"},
        "customer_access": lambda db, **kwargs: {"nova_saas_customer": True},
    }
    guard_tree = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0,
            ),
            guard_node,
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(guard_tree)
    exec(compile(guard_tree, "work_revenue/router.py", "exec"), namespace)
    real_guard = namespace["require_work_revenue_owner"]

    def require_nova_access():
        return None

    stage_tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [
        node for node in stage_tree.body
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets)
        ) or (
            isinstance(node, ast.FunctionDef)
            and node.name in {"disabled_approval_staging", "disabled_review_staging"}
        )
    ]
    stage_module = ast.Module(
        body=[
            ast.ImportFrom(
                module="__future__", names=[ast.alias(name="annotations")], level=0,
            ),
            *selected,
        ], type_ignores=[],
    )
    ast.fix_missing_locations(stage_module)
    stage_ns = {
        "APIRouter": APIRouter, "Depends": Depends,
        "HTTPException": HTTPException,
        "require_nova_access": require_nova_access,
        "require_work_revenue_owner": real_guard,
        "owner_approval_identity": scope.owner_approval_identity,
    }
    exec(compile(stage_module, str(SOURCE), "exec"), stage_ns)
    monkeypatch.setattr(
        scope.NovaCoreService, "resolve_organization_scope",
        lambda user, requested: user.organization_id,
    )
    app = FastAPI()
    app.include_router(stage_ns["router"])
    app.dependency_overrides[real_guard.__defaults__[0].dependency] = (
        lambda: SimpleNamespace(
            email="customer@synthetic.invalid",
            organization_id="tenant-a",
            user_id="customer-001",
        )
    )
    app.dependency_overrides[real_guard.__defaults__[1].dependency] = lambda: object()
    paths = [
        "/api/nova/work/operations/owner-approvals/example",
        "/api/nova/work/operations/owner-approvals/example/review",
    ]
    with TestClient(app) as client:
        for path in paths:
            assert client.post(path).status_code == 403
        app.dependency_overrides[real_guard.__defaults__[0].dependency] = (
            lambda: SimpleNamespace(
                email="owner@synthetic.invalid",
                organization_id="tenant-a",
                user_id="owner-001",
            )
        )
        for path in paths:
            response = client.post(path)
            assert response.status_code == 503
            assert "disabled" in response.json()["detail"].lower()
