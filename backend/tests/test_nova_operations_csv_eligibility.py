"""Regression tests for shared Operations CSV eligibility gates.

These tests cover the pure predicates used by both eligible-task discovery and
the processing endpoint. Full HTTP auth, browser, persistence and staging tests
are separate release requirements.
"""
from app.core.nova.work_revenue.operations_owner_csv_api import (
    _completed_task_ids,
    _eligible_engagement,
    _eligible_task,
)


def engagement(**changes):
    item = {
        "organization_id": "org-owner",
        "owner_user_id": "owner-1",
        "status": "ACTIVE",
        "blockers": None,
        "tasks": [],
    }
    item.update(changes)
    return item


def task(**changes):
    item = {
        "task_id": "task-1",
        "classification": "NOVA",
        "responsible_party": "NOVA",
        "status": "READY",
        "review_required": True,
        "blocked_reason": None,
        "required_owner_input": None,
        "depends_on_task_id": None,
    }
    item.update(changes)
    return item


def test_owner_engagement_must_match_both_org_and_user():
    assert _eligible_engagement(engagement(), "org-owner", "owner-1")
    assert not _eligible_engagement(engagement(), "another-org", "owner-1")
    assert not _eligible_engagement(engagement(), "org-owner", "another-owner")


def test_archived_blocked_and_unscoped_engagements_are_ineligible():
    assert not _eligible_engagement(engagement(status="ARCHIVED"), "org-owner", "owner-1")
    assert not _eligible_engagement(engagement(status="BLOCKED"), "org-owner", "owner-1")
    assert not _eligible_engagement(engagement(blockers="client consent missing"), "org-owner", "owner-1")
    assert not _eligible_engagement(engagement(owner_user_id=None), "org-owner", "owner-1")


def test_supervised_ready_task_is_eligible():
    assert _eligible_task(task(), set())
    assert _eligible_task(task(status="IN_PROGRESS"), set())


def test_unreviewed_other_party_or_completed_tasks_are_rejected():
    assert not _eligible_task(task(review_required=False), set())
    assert not _eligible_task(task(classification="OWNER"), set())
    assert not _eligible_task(task(responsible_party="OWNER"), set())
    assert not _eligible_task(task(status="COMPLETE"), set())
    assert not _eligible_task(task(status="CANCELLED"), set())


def test_blockers_and_missing_owner_inputs_block_csv_processing():
    assert not _eligible_task(task(blocked_reason="Awaiting approval"), set())
    assert not _eligible_task(task(required_owner_input="data use consent"), set())


def test_task_dependency_must_be_complete():
    child = task(depends_on_task_id="parent-1")
    assert not _eligible_task(child, set())
    assert _eligible_task(child, {"parent-1"})
    e = engagement(tasks=[
        task(task_id="parent-1", status="COMPLETE"),
        task(task_id="parent-2", status="IN_PROGRESS"),
    ])
    assert _completed_task_ids(e) == {"parent-1"}
    assert not _eligible_task(task(depends_on_task_id="parent-2"), _completed_task_ids(e))


def test_engagement_detail_never_leaks_other_owner_tasks(monkeypatch):
    """Regression for owner filtering on nested tasks in same organization."""
    from types import SimpleNamespace
    import pytest
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.session import Base
    from app.core.nova.work_revenue import service
    from app.core.nova.work_revenue.models import NovaWorkEngagement, NovaWorkTask

    db_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        db_engine,
        tables=[NovaWorkEngagement.__table__, NovaWorkTask.__table__],
    )
    monkeypatch.setattr(service, "_ensure", lambda: None)
    viewer = SimpleNamespace(user_id="owner-1", role="dispatcher")
    other = SimpleNamespace(user_id="owner-2", role="dispatcher")
    with Session(db_engine) as db:
        db.add(NovaWorkEngagement(
            engagement_id="eng-1", organization_id="org-owner",
            owner_user_id="owner-1", client_name="Synthetic Client",
            service="Synthetic CSV cleanup", status="ACTIVE",
        ))
        db.add(NovaWorkTask(
            task_id="task-owner", engagement_id="eng-1",
            organization_id="org-owner", owner_user_id="owner-1",
            title="Owner CSV task", status="READY",
        ))
        db.add(NovaWorkTask(
            task_id="task-other-owner", engagement_id="eng-1",
            organization_id="org-owner", owner_user_id="owner-2",
            title="Private task of another owner", status="READY",
        ))
        db.commit()
        detail = service.get_engagement(
            db, "eng-1", organization_id="org-owner", user=viewer,
        )
        assert [task["task_id"] for task in detail["tasks"]] == ["task-owner"]
        with pytest.raises(service.NovaWorkError) as denied:
            service.get_engagement(
                db, "eng-1", organization_id="org-owner", user=other,
            )
        assert denied.value.status_code == 404
    db_engine.dispose()
