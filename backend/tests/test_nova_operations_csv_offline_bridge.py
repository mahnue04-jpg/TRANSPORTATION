"""Isolated synthetic assignment->CSV job integration tests; no real data."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_csv_offline_bridge import (
    prepare_synthetic_scoped_csv,
)
from app.core.nova.work_revenue.operations_artifact_review import read_review_artifact
from app.core.nova.work_revenue.operations_job_queue import JobConflict, get_job_state


def fixture_engagement(**changes):
    engagement = {
        "engagement_id": "eng-1",
        "organization_id": "org-a",
        "owner_user_id": "owner-a",
        "status": "ACTIVE",
        "blockers": None,
        "tasks": [{
            "task_id": "task-1",
            "title": "CSV cleanup",
            "status": "READY",
            "classification": "NOVA",
            "responsible_party": "NOVA",
            "review_required": True,
            "required_owner_input": None,
            "blocked_reason": None,
            "depends_on_task_id": None,
        }],
    }
    engagement.update(changes)
    return engagement


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    connection = sqlite3.connect(tmp_path / "synthetic_work_queue.sqlite")
    yield connection
    connection.close()


def submit(db, *, eng=None, org="org-a", user="owner-a",
           request="req-1", task="task-1", now=100,
           csv="Name\nAna\nAna\n"):
    return prepare_synthetic_scoped_csv(
        db, owner_org=org, owner_user=user,
        engagement=eng if eng is not None else fixture_engagement(),
        task_id=task, request_id=request,
        synthetic_csv=csv, now=now,
    )


def test_synthetic_assignment_creates_review_only_artifact(db):
    result = submit(db)
    assert result.state == "awaiting_owner_review"
    assert result.report.duplicate_rows_removed == 1
    assert get_job_state(db, tenant_id="org-a:owner-a", job_id=result.job_id) == "completed"
    artifact = read_review_artifact(db, tenant_id="org-a:owner-a", job_id=result.job_id)
    assert artifact == ("awaiting_review", result.report.cleaned_csv)
    assert read_review_artifact(db, tenant_id="org-b:owner-b", job_id=result.job_id) is None


def test_request_replay_never_creates_second_completed_job(db):
    first = submit(db)
    with pytest.raises(JobConflict):
        submit(db)
    count = db.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_jobs WHERE tenant_id=?",
        ("org-a:owner-a",),
    ).fetchone()[0]
    assert count == 1
    assert first.job_id > 0


@pytest.mark.parametrize("changes", [
    {"status": "ARCHIVED"},
    {"blockers": "owner review missing"},
    {"owner_user_id": "owner-b"},
    {"organization_id": "org-b"},
])
def test_unauthorized_engagement_creates_no_job(db, changes):
    with pytest.raises(JobConflict):
        submit(db, eng=fixture_engagement(**changes))
    exists = db.execute(
        "SELECT name FROM sqlite_master WHERE name='nova_operations_offline_jobs'"
    ).fetchone()
    assert exists is None


def test_unrelated_or_blocked_task_denied_before_enqueue(db):
    eng = fixture_engagement()
    eng["tasks"][0]["title"] = "Write customer email"
    with pytest.raises(JobConflict):
        submit(db, eng=eng)
    eng["tasks"][0]["title"] = "CSV cleanup"
    eng["tasks"][0]["required_owner_input"] = "client permission"
    with pytest.raises(JobConflict):
        submit(db, eng=eng)


def test_distinct_assignments_do_not_share_idempotency_identity(db):
    first = submit(db)
    another = fixture_engagement(engagement_id="eng-2")
    second = submit(db, eng=another)
    assert first.job_id != second.job_id


def test_production_mode_rejects_before_storage_creation(db, monkeypatch):
    monkeypatch.delenv("TESTING", raising=False)
    with pytest.raises(JobConflict, match="restricted to synthetic tests"):
        submit(db)
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE name='nova_operations_offline_jobs'"
    ).fetchone() is None
