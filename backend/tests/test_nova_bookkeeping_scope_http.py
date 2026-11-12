"""Default-off accounting scope and API test guards; synthetic only."""
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.core.nova.router import require_nova_access
from app.core.nova.work_revenue.owner_auth import require_work_revenue_owner
from app.db.session import get_db

from app.core.nova.work_revenue import bookkeeping_scope as scope
from app.core.nova.work_revenue import bookkeeping_durable_jobs as finance
from app.core.nova.work_revenue import operations_owner_csv_api as api


def task(**kwargs):
    data = {
        "bookkeeping_work_type": "receivables_aging",
        "classification": "NOVA", "responsible_party": "NOVA",
        "review_required": True, "status": "READY", "blocked_reason": "",
        "required_owner_input": "", "depends_on_task_id": None,
        "title": "Invoice review",
    }
    data.update(kwargs)
    return data


def test_structured_task_fails_closed_on_labels():
    assert scope._trusted_eligible_task(task(), set(), "receivables_aging")
    assert scope._trusted_eligible_task(task(bookkeeping_work_type=None), set(), "receivables_aging", verified_contract_scope=True)
    assert not scope._trusted_eligible_task(task(bookkeeping_work_type="payables_aging"), set(), "receivables_aging", verified_contract_scope=True)
    assert not scope._trusted_eligible_task(
        task(bookkeeping_work_type=None, title="Receivables aging CSV workpaper"),
        set(), "receivables_aging",
    )
    for changes in (
        {"classification": "OWNER"}, {"responsible_party": "HUMAN"},
        {"review_required": False}, {"status": "COMPLETE"},
        {"blocked_reason": "waiting"}, {"required_owner_input": "signature"},
        {"depends_on_task_id": "unresolved"},
    ):
        assert not scope._trusted_eligible_task(task(**changes), set(), "receivables_aging")
    assert scope._trusted_eligible_task(
        task(depends_on_task_id="task-done"), {"task-done"}, "receivables_aging",
    )


def test_digest_validation_requires_real_looking_evidence():
    assert scope._digest("a" * 64)
    assert not scope._digest("0" * 64)
    assert not scope._digest("A" * 64)
    assert not scope._digest("1" * 63)
    assert not scope._digest("")


def test_consent_schema_not_present_never_opens_processing():
    engine = sa.create_engine("sqlite:///:memory:")
    owner = SimpleNamespace(organization_id="org-a", user_id="owner-a")
    with Session(engine) as db:
        with pytest.raises(scope.ConsentNotVerified, match="schema unavailable"):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="eng-a",
                task_id="task-a", work_type="receivables_aging",
            )
    engine.dispose()


def test_missing_owner_identity_blocked():
    engine = sa.create_engine("sqlite:///:memory:")
    owner = SimpleNamespace(organization_id="global", user_id="owner-a")
    with Session(engine) as db:
        with pytest.raises(scope.ConsentNotVerified, match="Valid organization"):
            scope.resolve_bookkeeping_assignment(
                db, owner=owner, engagement_id="eng-a",
                task_id="task-a", work_type="receivables_aging",
            )
    engine.dispose()


def test_accounting_route_runtime_is_off_by_default(monkeypatch):
    monkeypatch.delenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", raising=False)
    engine = sa.create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        with pytest.raises(finance.BookkeepingJobBlocked, match="disabled"):
            finance.require_bookkeeping_runtime(db)
    engine.dispose()


def test_accounting_routes_exist_under_owner_router():
    paths = {route.path for route in api.router.routes}
    base = "/operations/durable/bookkeeping"
    assert f"{base}/engagements/{{engagement_id}}/tasks/{{task_id}}/{{work_type}}/jobs" in paths
    assert f"{base}/jobs/{{job_id}}" in paths
    assert f"{base}/jobs/{{job_id}}/review" in paths
    assert f"{base}/jobs/{{job_id}}/download" in paths
    assert f"{base}/jobs/{{job_id}}/recover" in paths


def test_legacy_csv_task_label_does_not_authorize_bookkeeping():
    # Ordinary CSV cleanup authorization must not authorize finance work.
    task_value = task(bookkeeping_work_type=None, title="CSV cleanup")
    assert not scope._trusted_eligible_task(task_value, set(), "receivables_aging")


def test_real_http_endpoint_defaults_off_and_refuses_unverified_consent(monkeypatch):
    app = FastAPI()
    app.include_router(api.router)
    user = SimpleNamespace(organization_id="org-a", user_id="owner-a")
    engine = sa.create_engine("sqlite:///:memory:")
    with Session(engine) as db:
        app.dependency_overrides[require_nova_access] = lambda: user
        app.dependency_overrides[require_work_revenue_owner] = lambda: user
        app.dependency_overrides[get_db] = lambda: db
        url = "/operations/durable/bookkeeping/engagements/eng-a/tasks/task-a/receivables_aging/jobs"
        with TestClient(app) as client:
            payload = b"invoice_id,customer,invoice_date,due_date,amount,paid\\nA1,Client,2026-11-01,2026-11-10,20,0\\n"
            headers = {"Content-Type": "text/csv", "Idempotency-Key": "test-a",
                       "X-Nova-File-Name": "invoices.csv", "X-Nova-As-Of": "2026-11-11"}
            monkeypatch.delenv("NOVA_BOOKKEEPING_DURABLE_ENABLED", raising=False)
            disabled = client.post(url, content=payload, headers=headers)
            assert disabled.status_code == 503
            monkeypatch.setattr(api.bk_jobs, "require_bookkeeping_runtime", lambda session: None)
            missing = client.post(url, content=payload, headers=headers)
            assert missing.status_code == 403
    engine.dispose()
