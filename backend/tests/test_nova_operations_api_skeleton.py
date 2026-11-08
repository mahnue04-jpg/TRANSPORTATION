"""Fail-closed Operations CSV API and real tenant scope checks."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue import operations_owner_scope as scope

SOURCE = Path(__file__).resolve().parents[1] / "app/core/nova/work_revenue/operations_csv_api.py"


def test_routes_remain_unregistered_and_fail_closed():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    routes = {"submit_csv_job", "csv_job_status", "csv_job_review", "csv_job_download"}
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    assert routes.issubset(functions)
    for name in routes:
        calls = [
            node.func.id for node in ast.walk(functions[name])
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        assert "resolve_operations_owner_scope" in calls
        assert "_disabled" in calls
        assert calls.index("resolve_operations_owner_scope") < calls.index("_disabled")
        assert any(
            isinstance(default, ast.Call)
            and isinstance(default.func, ast.Name)
            and default.func.id == "Depends"
            and any(isinstance(arg, ast.Name) and arg.id == "require_work_revenue_owner"
                    for arg in default.args)
            for default in functions[name].args.defaults
        )
    source = SOURCE.read_text(encoding="utf-8")
    assert "Depends(require_nova_access)" in source
    assert "Depends(require_work_revenue_owner)" in source
    assert "status_code=503" in source
    assert "include_router" not in source
    assert "get_current_user_context" not in source


def test_no_customer_data_or_paid_provider_calls_in_skeleton():
    source = SOURCE.read_text(encoding="utf-8")
    for forbidden in ("UploadFile", "File(", "requests.", "httpx.", "fal_client", "stripe."):
        assert forbidden not in source


def test_no_implicit_router_registration_in_application_entrypoint():
    root = SOURCE.parents[3]
    for candidate in (root / "main.py", root / "app" / "main.py"):
        if candidate.exists():
            assert "operations_csv_api" not in candidate.read_text(encoding="utf-8")


@pytest.mark.parametrize("invalid", [None, "", " ", "global", "GLOBAL", " tenant-a "])
def test_owner_scope_rejects_missing_or_broad_session_tenant(monkeypatch, invalid):
    seen = []

    def resolver(_user, requested):
        seen.append(requested)
        return "tenant-a"

    monkeypatch.setattr(scope.NovaCoreService, "resolve_organization_scope", resolver)
    with pytest.raises(HTTPException) as exc:
        scope.resolve_operations_owner_scope(SimpleNamespace(organization_id=invalid))
    assert exc.value.status_code == 403
    assert seen == []


def test_owner_scope_accepts_concrete_session_tenant(monkeypatch):
    seen = []

    def resolver(_user, requested):
        seen.append(requested)
        return "tenant-a"

    monkeypatch.setattr(scope.NovaCoreService, "resolve_organization_scope", resolver)
    assert scope.resolve_operations_owner_scope(
        SimpleNamespace(organization_id="tenant-a")
    ) == "tenant-a"
    assert seen == [None]


def test_owner_scope_rejects_resolver_tenant_switch(monkeypatch):
    monkeypatch.setattr(
        scope.NovaCoreService, "resolve_organization_scope",
        lambda _user, _requested: "other-tenant",
    )
    with pytest.raises(HTTPException) as exc:
        scope.resolve_operations_owner_scope(SimpleNamespace(organization_id="tenant-a"))
    assert exc.value.status_code == 403


def test_owner_scope_preserves_authorization_denial(monkeypatch):
    def denied(_user, _requested):
        raise ValueError("Cross-tenant Nova access denied")

    monkeypatch.setattr(scope.NovaCoreService, "resolve_organization_scope", denied)
    with pytest.raises(HTTPException) as exc:
        scope.resolve_operations_owner_scope(SimpleNamespace(organization_id="tenant-a"))
    assert exc.value.status_code == 403
