"""End-to-end offline Operations Agent CSV assignment acceptance test.

Synthetic fixture only. No network, production deployment, or customer data.
"""
import sqlite3

from app.core.nova.work_revenue.operations_artifact_review import (
    read_review_artifact, review_artifact,
)
from app.core.nova.work_revenue.operations_csv_runner import prepare_csv_job
from app.core.nova.work_revenue.operations_job_queue import ensure_schema, get_job_state


def test_offline_assignment_survives_restart_and_requires_review(tmp_path):
    path = tmp_path / "assignment.sqlite"
    db = sqlite3.connect(path)
    ensure_schema(db)
    result = prepare_csv_job(
        db, tenant_id="demo-tenant", request_id="demo-001",
        raw_csv="Name,Email\nAna,a@example.com\nAna,a@example.com\nBen,b@example.com\n",
        now=100,
    )
    assert result.report.input_rows == 3
    assert result.report.output_rows == 2
    assert result.report.duplicate_rows_removed == 1
    assert result.state == "awaiting_owner_review"
    assert get_job_state(db, tenant_id="demo-tenant", job_id=result.job_id) == "completed"
    db.close()

    reopened = sqlite3.connect(path)
    assert read_review_artifact(reopened, tenant_id="other-tenant", job_id=result.job_id) is None
    state, csv_text = read_review_artifact(reopened, tenant_id="demo-tenant", job_id=result.job_id)
    assert state == "awaiting_review"
    assert csv_text == "Name,Email\nAna,a@example.com\nBen,b@example.com\n"
    assert review_artifact(
        reopened, tenant_id="demo-tenant", job_id=result.job_id,
        reviewer_id="synthetic-owner", approve=True,
    ) == "approved"
    assert read_review_artifact(reopened, tenant_id="demo-tenant", job_id=result.job_id)[0] == "approved"
    reopened.close()
