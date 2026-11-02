"""Offline artifact persistence and review tests."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_artifact_review import (
    ensure_artifact_schema, read_review_artifact, review_artifact, save_review_artifact,
)
from app.core.nova.work_revenue.operations_csv_runner import prepare_csv_job
from app.core.nova.work_revenue.operations_job_queue import JobConflict, ensure_schema


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "review.sqlite")
    ensure_schema(conn)
    ensure_artifact_schema(conn)
    yield conn
    conn.close()


def test_persist_and_owner_review(db):
    result = prepare_csv_job(
        db, tenant_id="tenant-a", request_id="one",
        raw_csv="Name\nAna\nAna\n", now=100,
    )
    save_review_artifact(
        db, tenant_id="tenant-a", job_id=result.job_id,
        csv_text=result.report.cleaned_csv,
        output_sha256=result.report.output_sha256,
    )
    assert read_review_artifact(db, tenant_id="tenant-b", job_id=result.job_id) is None
    assert read_review_artifact(db, tenant_id="tenant-a", job_id=result.job_id)[0] == "awaiting_review"
    assert review_artifact(db, tenant_id="tenant-a", job_id=result.job_id,
                           reviewer_id="owner", approve=True) == "approved"
    with pytest.raises(JobConflict):
        review_artifact(db, tenant_id="tenant-a", job_id=result.job_id,
                        reviewer_id="owner", approve=False)


def test_checksum_and_tenant_guard(db):
    result = prepare_csv_job(
        db, tenant_id="tenant-a", request_id="two",
        raw_csv="Name\nAna\n", now=100,
    )
    with pytest.raises(JobConflict):
        save_review_artifact(
            db, tenant_id="tenant-a", job_id=result.job_id,
            csv_text="tampered", output_sha256=result.report.output_sha256,
        )
    with pytest.raises(JobConflict):
        save_review_artifact(
            db, tenant_id="tenant-b", job_id=result.job_id,
            csv_text=result.report.cleaned_csv, output_sha256=result.report.output_sha256,
        )
