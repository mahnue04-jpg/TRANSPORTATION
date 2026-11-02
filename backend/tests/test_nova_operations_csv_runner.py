"""Offline CSV runner contract tests."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_job_queue import JobConflict, ensure_schema, get_job_state
from app.core.nova.work_revenue.operations_csv_runner import prepare_csv_job
from app.core.nova.work_revenue.operations_artifact_review import read_review_artifact


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "runner.sqlite")
    ensure_schema(conn)
    yield conn
    conn.close()


def test_processing_returns_reviewable_artifact(db):
    result = prepare_csv_job(
        db, tenant_id="demo", request_id="request-1",
        raw_csv="Name,Email\nAna,a@example.com\nAna,a@example.com\n",
        now=100,
    )
    assert result.state == "awaiting_owner_review"
    stored = read_review_artifact(db, tenant_id="demo", job_id=result.job_id)
    assert stored == ("awaiting_review", result.report.cleaned_csv)
    assert result.report.duplicate_rows_removed == 1
    assert get_job_state(db, tenant_id="demo", job_id=result.job_id) == "completed"


def test_reused_request_does_not_rerun(db):
    args = dict(tenant_id="demo", request_id="same", raw_csv="Name\nAna\n", now=100)
    prepare_csv_job(db, **args)
    with pytest.raises(JobConflict):
        prepare_csv_job(db, **args)


def test_invalid_csv_not_marked_complete(db):
    with pytest.raises(Exception):
        prepare_csv_job(
            db, tenant_id="demo", request_id="invalid",
            raw_csv="Name,Email\nAna\n", now=100,
        )
    state = db.execute(
        "SELECT state FROM nova_operations_offline_jobs WHERE tenant_id=? AND idempotency_key=?",
        ("demo", "invalid"),
    ).fetchone()[0]
    assert state == "queued"
