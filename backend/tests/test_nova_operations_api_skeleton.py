"""Contract checks for the disabled Operations CSV API skeleton.

These tests avoid real customer data, storage, and external integrations.
"""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/operations_csv_api.py"


def test_routes_remain_unregistered_and_fail_closed():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    routes = {
        "submit_csv_job", "csv_job_status", "csv_job_review", "csv_job_download"
    }
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert routes.issubset(functions)
    for name in routes:
        calls = [
            node for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == "_disabled"
        ]
        assert calls, f"{name} must fail closed until integration is approved"
    source = SOURCE.read_text(encoding="utf-8")
    assert 'Depends(require_nova_access)' in source
    assert 'Depends(require_work_revenue_owner)' in source
    assert "status_code=503" in source
    assert "include_router" not in source


def test_no_customer_data_or_paid_provider_calls_in_skeleton():
    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in ("UploadFile", "File(", "requests.", "httpx.", "fal_client", "stripe."):
        assert forbidden not in source


def test_no_implicit_router_registration_in_application_entrypoint():
    """The skeleton is intentionally not mounted by the application."""
    root = SOURCE.parents[3]
    candidate_paths = (
        root / "main.py",
        root / "app" / "main.py",
    )
    for candidate in candidate_paths:
        if candidate.exists():
            source = candidate.read_text(encoding="utf-8")
            assert "operations_csv_api" not in source



def test_disabled_routes_resolve_scope_using_owner_dependency():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    for name in ("submit_csv_job", "csv_job_status", "csv_job_review", "csv_job_download"):
        fn = functions[name]
        calls = [
            node.func.id for node in ast.walk(fn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "_owner_scope" in calls
        assert "_disabled" in calls
        assert calls.index("_owner_scope") < calls.index("_disabled")
        assert any(
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and any(
                isinstance(arg, ast.Name) and arg.id == "require_work_revenue_owner"
                for arg in default.args
            )
            for default in fn.args.defaults
        )
    scope = functions["_owner_scope"]
    assert any(
        isinstance(node, ast.Attribute)
        and node.attr == "resolve_organization_scope"
        for node in ast.walk(scope)
    )
    assert "get_current_user_context" not in SOURCE.read_text(encoding="utf-8")


def test_scope_rejects_global_fallback_and_blank_tenant():
    """Source contract: the disabled API must never accept a broad scope."""
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    scope = functions["_owner_scope"]
    literals = {
        node.value for node in ast.walk(scope)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert "global" in literals
    assert "Tenant-specific organization required" in literals
    assert any(
        isinstance(node, ast.Raise)
        for node in ast.walk(scope)
    )



def test_owner_scope_requires_session_tenant_even_for_privileged_user(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.core.nova.work_revenue import operations_csv_api as api

    seen = []

    def resolve(_user, requested):
        seen.append(requested)
        return "tenant-a"

    monkeypatch.setattr(api.NovaCoreService, "resolve_organization_scope", resolve)

    for invalid in (None, "", " ", "global", "GLOBAL"):
        with pytest.raises(HTTPException) as exc:
            api._owner_scope(SimpleNamespace(organization_id=invalid))
        assert exc.value.status_code == 403
    assert seen == []

    assert api._owner_scope(SimpleNamespace(organization_id="tenant-a")) == "tenant-a"
    assert seen == [None]


def test_owner_scope_rejects_resolver_tenant_switch(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.core.nova.work_revenue import operations_csv_api as api

    monkeypatch.setattr(
        api.NovaCoreService, "resolve_organization_scope",
        lambda _user, _requested: "different-tenant",
    )
    with pytest.raises(HTTPException) as exc:
        api._owner_scope(SimpleNamespace(organization_id="tenant-a"))
    assert exc.value.status_code == 403


def test_owner_scope_does_not_override_missing_authorization(monkeypatch):
    from types import SimpleNamespace

    import pytest
    from fastapi import HTTPException

    from app.core.nova.work_revenue import operations_csv_api as api

    def reject(_user, _requested):
        raise ValueError("Cross-tenant Nova access denied")

    monkeypatch.setattr(api.NovaCoreService, "resolve_organization_scope", reject)
    with pytest.raises(HTTPException) as exc:
        api._owner_scope(SimpleNamespace(organization_id="tenant-a"))
    assert exc.value.status_code == 403
