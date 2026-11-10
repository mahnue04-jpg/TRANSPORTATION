"""Synthetic HTTP tests for the owner-scoped Operations CSV endpoints.

Only the auth dependencies are replaced with a mock authorized owner; these
tests assert endpoint gates and do not certify real authentication, storage,
production deployment, or commercial customer processing.
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue import operations_owner_csv_api as csv_api
from app.core.nova.work_revenue.router import require_work_revenue_owner
from app.db.session import get_db


@pytest.fixture
def harness(monkeypatch):
    owner = SimpleNamespace(organization_id="org-alpha", user_id="owner-a")
    app = FastAPI()
    app.include_router(csv_api.router, prefix="/api/nova/work")
    app.dependency_overrides[require_nova_access] = lambda: owner
    app.dependency_overrides[require_work_revenue_owner] = lambda: owner
    app.dependency_overrides[get_db] = lambda: None
    monkeypatch.setenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "true")
    base = {
        "engagement_id": "eng-a",
        "organization_id": "org-alpha",
        "owner_user_id": "owner-a",
        "status": "ACTIVE",
        "blockers": None,
        "service": "Synthetic CSV cleanup",
        "tasks": [{
            "task_id": "task-a", "title": "Synthetic CSV cleanup task",
            "status": "READY", "classification": "NOVA",
            "responsible_party": "NOVA", "review_required": True,
            "required_owner_input": None, "blocked_reason": None,
            "depends_on_task_id": None,
        }],
    }
    monkeypatch.setattr(csv_api.service, "get_engagement", lambda *args, **kwargs: base)
    monkeypatch.setattr(csv_api.service, "list_engagements", lambda *args, **kwargs: [base])
    headers = {
        "Content-Type": "text/csv",
        "X-Nova-File-Name": "synthetic.csv",
        "X-Nova-Owner-Action": "process-csv-for-owner-review",
        "X-Nova-Scope-Confirmed": "owner-confirmed-client-authorization",
    }
    with TestClient(app) as client:
        yield client, base, headers


def _run(client, headers, engagement="eng-a", task="task-a", content=b"name,score\nAda,4\n"):
    return client.post(
        f"/api/nova/work/operations/engagements/{engagement}/tasks/{task}/csv-clean",
        content=content,
        headers=headers,
    )


def test_eligible_list_is_owner_scoped(harness):
    client, item, _ = harness
    response = client.get("/api/nova/work/operations/eligible-csv-tasks")
    assert response.status_code == 200
    assert [row["task_id"] for row in response.json()["tasks"]] == ["task-a"]
    item["owner_user_id"] = "owner-b"
    response = client.get("/api/nova/work/operations/eligible-csv-tasks")
    assert response.status_code == 200
    assert response.json()["tasks"] == []


def test_scoped_csv_return_is_review_only(harness):
    client, _, headers = harness
    response = _run(client, headers)
    assert response.status_code == 200, response.text
    assert response.headers["X-Nova-Delivery-Status"] == "owner-review-only-not-delivered"
    assert response.headers["X-Nova-Task-ID"] == "task-a"
    assert response.headers["Cache-Control"] == "no-store, private"
    assert response.headers["X-Nova-Owner-Review-Required"] == "true"


def test_scope_confirmation_is_required(harness):
    client, _, headers = harness
    headers = dict(headers)
    headers.pop("X-Nova-Scope-Confirmed")
    response = _run(client, headers)
    assert response.status_code == 403


@pytest.mark.parametrize("change", [
    {"organization_id": "org-beta"},
    {"owner_user_id": "owner-b"},
    {"status": "ARCHIVED"},
    {"blockers": "client data authorization pending"},
])
def test_engagement_scope_and_blockers_rechecked_on_post(harness, change):
    client, item, headers = harness
    item.update(change)
    assert _run(client, headers).status_code == 409


def test_inactive_or_wrong_task_rejected_after_selection(harness):
    client, item, headers = harness
    assert _run(client, headers, task="task-unknown").status_code == 404
    item["tasks"][0]["status"] = "COMPLETE"
    assert _run(client, headers).status_code == 409


def test_missing_owner_input_and_unfinished_dependency_block_post(harness):
    client, item, headers = harness
    item["tasks"][0]["required_owner_input"] = "approval"
    assert _run(client, headers).status_code == 409
    item["tasks"][0]["required_owner_input"] = None
    item["tasks"][0]["depends_on_task_id"] = "task-before"
    assert _run(client, headers).status_code == 409


def test_csv_size_and_type_fail_closed(harness):
    client, _, headers = harness
    assert _run(client, headers, content=b"x" * (csv_api.LIMIT_BYTES + 1)).status_code == 413
    wrong_type = dict(headers, **{"Content-Type": "application/json"})
    assert _run(client, wrong_type).status_code == 415


def test_flag_disabled_denies_get_and_post(harness, monkeypatch):
    client, _, headers = harness
    monkeypatch.setenv("NOVA_OPERATIONS_OWNER_CSV_ENABLED", "false")
    assert client.get("/api/nova/work/operations/eligible-csv-tasks").status_code == 503
    assert _run(client, headers).status_code == 503


def test_unrelated_nova_assignment_not_listed_or_executed(harness):
    client, item, headers = harness
    item["tasks"][0]["title"] = "Write marketing emails"
    assert client.get("/api/nova/work/operations/eligible-csv-tasks").json()["tasks"] == []
    assert _run(client, headers).status_code == 409
