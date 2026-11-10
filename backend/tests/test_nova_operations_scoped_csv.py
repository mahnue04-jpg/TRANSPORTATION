"""Authorization contract for scoped Operations CSV processing, no production DB."""
from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from fastapi import Depends, Header, HTTPException, Request
from fastapi.responses import Response
import pytest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "app/core/nova/work_revenue/operations_owner_csv_api.py"
BASE = {"engagement_id": "eng-1", "organization_id": "tenant-1",
        "status": "ACTIVE", "blockers": "", "tasks": [
            {"task_id": "task-1", "classification": "NOVA",
             "responsible_party": "NOVA", "review_required": True,
             "status": "READY", "blocked_reason": ""}
        ]}


def _run(monkeypatch, *, engagement=None, confirmed=True, action=True):
    monkeypatch.setenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "true")
    record = dict(BASE if engagement is None else engagement)
    calls = []
    def get_engagement(db, engagement_id, *, organization_id, user):
        calls.append((engagement_id, organization_id))
        return record
    async def clean(request, owner_action, filename, owner):
        calls.append(("clean", owner.organization_id))
        return Response(b"Col\ncleaned\n", media_type="text/csv")
    source = ast.parse(API.read_text(encoding="utf-8"))
    fn = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "scoped_owner_csv_cleanup")
    # Strip decorators because this tests the function's checks, not route wiring.
    fn.decorator_list = []
    namespace = {
        "os": __import__("os"), "HTTPException": HTTPException,
        "Header": Header, "Depends": Depends, "Request": Request,
        "Response": Response, "UserContext": object,
        "Session": object, "get_db": lambda: None,
        "require_work_revenue_owner": lambda: None,
        "service": SimpleNamespace(get_engagement=get_engagement,
                                    NovaWorkError=type("NovaWorkError", (Exception,), {})),
        "owner_csv_cleanup": clean,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[
        ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
        fn], type_ignores=[])), str(API), "exec"), namespace)
    func = namespace["scoped_owner_csv_cleanup"]
    async def invoke():
        return await func("eng-1", "task-1", object(), filename="sample.csv",
            owner_action=("process-csv-for-owner-review" if action else "wrong"),
            scope_confirmed=("owner-confirmed-client-authorization" if confirmed else None),
            owner=SimpleNamespace(organization_id="tenant-1"), db=object())
    return invoke, calls


def test_scoped_processing_requires_real_engagement_and_owner_consent(monkeypatch):
    invoke, calls = _run(monkeypatch)
    response = asyncio.run(invoke())
    assert response.status_code == 200
    assert response.headers["x-nova-engagement-id"] == "eng-1"
    assert response.headers["x-nova-task-id"] == "task-1"
    assert response.headers["x-nova-delivery-status"] == "owner-review-only-not-delivered"
    assert calls == [("eng-1", "tenant-1"), ("clean", "tenant-1")]


@pytest.mark.parametrize("change", [
    {"organization_id": "another-tenant"},
    {"status": "COMPLETE"},
    {"status": "PENDING"},
    {"blockers": "Awaiting signature"},
    {"tasks": []},
    {"tasks": [{"task_id": "task-1", "classification": "HUMAN", "responsible_party": "HUMAN",
                "review_required": True, "status": "READY"}]},
    {"tasks": [{"task_id": "task-1", "classification": "NOVA", "responsible_party": "NOVA",
                "review_required": False, "status": "READY"}]},
    {"tasks": [{"task_id": "task-1", "classification": "NOVA", "responsible_party": "NOVA",
                "review_required": True, "status": "READY", "blocked_reason": "missing data"}]},
])
def test_scoped_processing_rejects_unready_work(monkeypatch, change):
    engagement = dict(BASE)
    engagement.update(change)
    invoke, calls = _run(monkeypatch, engagement=engagement)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(invoke())
    assert exc.value.status_code in (404, 409)
    assert not any(x[0] == "clean" for x in calls)


def test_scoped_processing_needs_owner_authorization(monkeypatch):
    invoke, calls = _run(monkeypatch, confirmed=False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(invoke())
    assert exc.value.status_code == 403
    assert calls == []


def test_scoped_endpoint_protected_by_parent_owner_router():
    route_source = (ROOT / "app/core/nova/work_revenue/router.py").read_text()
    csv_source = API.read_text()
    assert "router.include_router(owner_csv_router)" in route_source
    assert "Depends(require_work_revenue_owner)" in csv_source
    assert "Depends(require_nova_access)" in csv_source
    assert '/engagements/{engagement_id}/tasks/{task_id}/csv-clean' in csv_source
