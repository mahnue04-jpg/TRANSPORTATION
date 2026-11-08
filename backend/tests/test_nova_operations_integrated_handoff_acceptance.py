"""Synthetic Work & Revenue to Operations Agent offline acceptance journey.

No user authentication, production API, external delivery or payment.
"""
import hashlib
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_assignment_handoff import (
    ensure_handoff_schema, handoff_approved_opportunity,
    record_verified_owner_approval,
)
from app.core.nova.work_revenue.operations_artifact_review import (
    complete_and_store_review_artifact, ensure_artifact_schema, review_artifact,
)
from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text
from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, claim_job, ensure_schema, get_job_state,
)
from app.core.nova.work_revenue.operations_release_gate import (
    check_offline_release_eligibility,
)

RAW = "Name,Email\nAna,a@example.com\nAna,a@example.com\nBen,b@example.com\n"
TENANT = "synthetic-tenant"
OPPORTUNITY = "synthetic-lead-001"
REVIEWER = "synthetic-owner"


def release(db, tenant=TENANT):
    return check_offline_release_eligibility(
        db, acting_tenant_id=tenant, opportunity_id=OPPORTUNITY,
    )


def test_synthetic_opportunity_to_reviewed_csv_survives_restart(tmp_path):
    path = tmp_path / "joined-workflow.sqlite"
    db = sqlite3.connect(path)
    ensure_schema(db)
    ensure_handoff_schema(db)
    ensure_artifact_schema(db)
    fingerprint = hashlib.sha256(RAW.encode("utf-8")).hexdigest()

    # A supplied reference alone must never create an assignment.
    with pytest.raises(JobConflict, match="Verified owner approval"):
        handoff_approved_opportunity(
            db, acting_tenant_id=TENANT, record_tenant_id=TENANT,
            opportunity_id=OPPORTUNITY, approval_reference="approval-001",
            input_sha256=fingerprint,
        )
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 0

    # Authorization is simulated by the test fixture, not performed by this module.
    record_verified_owner_approval(
        db, acting_tenant_id=TENANT, record_tenant_id=TENANT,
        opportunity_id=OPPORTUNITY, approval_reference="approval-001",
        input_sha256=fingerprint, reviewer_id=REVIEWER,
        reviewer_authorized=True,
    )
    assignment = handoff_approved_opportunity(
        db, acting_tenant_id=TENANT, record_tenant_id=TENANT,
        opportunity_id=OPPORTUNITY, approval_reference="approval-001",
        input_sha256=fingerprint,
    )
    assert handoff_approved_opportunity(
        db, acting_tenant_id=TENANT, record_tenant_id=TENANT,
        opportunity_id=OPPORTUNITY, approval_reference="approval-001",
        input_sha256=fingerprint,
    ) == assignment
    assert get_job_state(db, tenant_id=TENANT, job_id=assignment.job_id) == "queued"
    db.close()

    db = sqlite3.connect(path)
    with pytest.raises(JobConflict, match="owner-reviewed"):
        release(db)
    claim = claim_job(db, tenant_id=TENANT, job_id=assignment.job_id, now=100)
    assert claim.input_sha256 == fingerprint
    report = clean_csv_text(RAW)
    assert report.input_sha256 == fingerprint
    assert report.duplicate_rows_removed == 1
    assert report.output_rows == 2
    complete_and_store_review_artifact(
        db, job=claim, csv_text=report.cleaned_csv,
        output_sha256=report.output_sha256, now=101,
    )
    with pytest.raises(JobConflict, match="owner-reviewed"):
        release(db)
    assert review_artifact(
        db, tenant_id=TENANT, job_id=assignment.job_id,
        reviewer_id=REVIEWER, approve=True,
    ) == "approved"
    allowed = release(db)
    assert allowed.job_id == assignment.job_id
    assert allowed.output_sha256 == report.output_sha256
    assert allowed.reviewer_id == REVIEWER
    assert not hasattr(allowed, "csv_text")
    with pytest.raises(JobConflict, match="not found"):
        release(db, tenant="another-tenant")
    db.close()

    reopened = sqlite3.connect(path)
    try:
        assert release(reopened) == allowed
        assert claim_job(
            reopened, tenant_id=TENANT, job_id=assignment.job_id, now=1000,
        ) is None
        assert reopened.execute(
            "SELECT COUNT(*) FROM nova_operations_offline_jobs"
        ).fetchone()[0] == 1
    finally:
        reopened.close()
