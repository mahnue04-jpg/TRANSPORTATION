"""Offline-only release gate tests using synthetic records and CSV bytes."""
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
from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, claim_job, ensure_schema,
)
from app.core.nova.work_revenue.operations_release_gate import (
    check_offline_release_eligibility,
)

CSV = "Name\nAna\n"
DIGEST = hashlib.sha256(CSV.encode("utf-8")).hexdigest()


@pytest.fixture
def assignment(tmp_path):
    db = sqlite3.connect(tmp_path / "release.sqlite")
    ensure_schema(db)
    ensure_handoff_schema(db)
    ensure_artifact_schema(db)
    record_verified_owner_approval(
        db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
        opportunity_id="lead-1", approval_reference="approved-1",
        input_sha256="a" * 64, reviewer_id="owner-1",
        reviewer_authorized=True,
    )
    link = handoff_approved_opportunity(
        db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
        opportunity_id="lead-1", approval_reference="approved-1",
        input_sha256="a" * 64,
    )
    yield db, link.job_id
    db.close()


def gate(db, tenant="tenant-a"):
    return check_offline_release_eligibility(
        db, acting_tenant_id=tenant, opportunity_id="lead-1",
    )


def finish(db, job_id):
    claim = claim_job(db, tenant_id="tenant-a", job_id=job_id, now=100)
    complete_and_store_review_artifact(
        db, job=claim, csv_text=CSV, output_sha256=DIGEST, now=101,
    )


def test_queued_and_unreviewed_jobs_cannot_pass_release(assignment):
    db, job_id = assignment
    with pytest.raises(JobConflict, match="owner-reviewed"):
        gate(db)
    finish(db, job_id)
    with pytest.raises(JobConflict, match="owner-reviewed"):
        gate(db)


def test_approved_artifact_passes_metadata_only_and_tenant_isolated(assignment):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(db, tenant_id="tenant-a", job_id=job_id,
                    reviewer_id="owner-1", approve=True)
    result = gate(db)
    assert result.job_id == job_id
    assert result.output_sha256 == DIGEST
    assert not hasattr(result, "csv_text")
    with pytest.raises(JobConflict, match="not found"):
        gate(db, tenant="tenant-b")


def test_rejected_artifact_cannot_pass_release(assignment):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(db, tenant_id="tenant-a", job_id=job_id,
                    reviewer_id="owner-1", approve=False)
    with pytest.raises(JobConflict, match="owner-reviewed"):
        gate(db)


@pytest.mark.parametrize("table,column,value", [
    ("nova_operations_offline_artifacts", "csv_text", "tampered"),
    ("nova_operations_offline_artifacts", "output_sha256", "b" * 64),
    ("nova_operations_offline_artifacts", "reviewer_id", "bad\nreviewer"),
    ("nova_operations_offline_jobs", "output_sha256", "b" * 64),
])
def test_corrupted_review_records_fail_closed(assignment, table, column, value):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(db, tenant_id="tenant-a", job_id=job_id,
                    reviewer_id="owner-1", approve=True)
    db.execute(f"UPDATE {table} SET {column}=? WHERE job_id=?", (value, job_id))
    db.commit()
    with pytest.raises(JobConflict, match="integrity"):
        gate(db)


def test_approval_link_tampering_blocks_release(assignment):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(db, tenant_id="tenant-a", job_id=job_id,
                    reviewer_id="owner-1", approve=True)
    db.execute("UPDATE nova_operations_offline_approvals SET approval_reference='wrong'")
    db.commit()
    with pytest.raises(JobConflict, match="inconsistent"):
        gate(db)


def test_different_reviewer_cannot_pass_release_gate(assignment):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(
        db, tenant_id="tenant-a", job_id=job_id,
        reviewer_id="other-owner", approve=True,
    )
    with pytest.raises(JobConflict, match="integrity"):
        gate(db)


def test_tampered_approval_reviewer_blocks_release(assignment):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(
        db, tenant_id="tenant-a", job_id=job_id,
        reviewer_id="owner-1", approve=True,
    )
    db.execute(
        "UPDATE nova_operations_offline_approvals SET reviewer_id=?",
        ("different-owner",),
    )
    db.commit()
    with pytest.raises(JobConflict, match="integrity"):
        gate(db)


def test_release_eligibility_persists_across_database_restart(tmp_path):
    path = tmp_path / "persisted-release.sqlite"
    db = sqlite3.connect(path)
    ensure_schema(db)
    ensure_handoff_schema(db)
    ensure_artifact_schema(db)
    record_verified_owner_approval(
        db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
        opportunity_id="lead-1", approval_reference="approved-1",
        input_sha256="a" * 64, reviewer_id="owner-1",
        reviewer_authorized=True,
    )
    link = handoff_approved_opportunity(
        db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
        opportunity_id="lead-1", approval_reference="approved-1",
        input_sha256="a" * 64,
    )
    finish(db, link.job_id)
    review_artifact(
        db, tenant_id="tenant-a", job_id=link.job_id,
        reviewer_id="owner-1", approve=True,
    )
    assert gate(db).output_sha256 == DIGEST
    db.close()

    reopened = sqlite3.connect(path)
    try:
        assert gate(reopened).job_id == link.job_id
        assert gate(reopened).output_sha256 == DIGEST
        with pytest.raises(JobConflict, match="not found"):
            gate(reopened, tenant="tenant-b")
        # A prior approval is durable; a second review must not overwrite it.
        with pytest.raises(JobConflict, match="already reviewed"):
            review_artifact(
                reopened, tenant_id="tenant-a", job_id=link.job_id,
                reviewer_id="other-owner", approve=False,
            )
    finally:
        reopened.close()


def test_release_gate_rejects_missing_approval_reviewer(assignment):
    db, job_id = assignment
    finish(db, job_id)
    review_artifact(
        db, tenant_id="tenant-a", job_id=job_id,
        reviewer_id="owner-1", approve=True,
    )
    db.execute(
        "UPDATE nova_operations_offline_approvals SET reviewer_id=''"
    )
    db.commit()
    with pytest.raises(JobConflict, match="integrity"):
        gate(db)
