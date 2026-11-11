"""Default-off accounting scope and API test guards; synthetic only."""
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

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


def test_legacy_csv_task_label_does_not_authorize_bookkeeping():
    # Ordinary CSV cleanup authorization must not authorize finance work.
    task_value = task(bookkeeping_work_type=None, title="CSV cleanup")
    assert not scope._trusted_eligible_task(task_value, set(), "receivables_aging")
