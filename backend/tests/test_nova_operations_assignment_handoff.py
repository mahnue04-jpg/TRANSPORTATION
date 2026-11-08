"""Offline synthetic approved-opportunity handoff tests."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_assignment_handoff import (
    ensure_handoff_schema, get_assignment_handoff, handoff_approved_opportunity,
    record_verified_owner_approval, claim_approved_assignment,
)
from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, claim_job, ensure_schema, get_job_state,
)


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "handoff.sqlite")
    ensure_schema(conn)
    ensure_handoff_schema(conn)
    yield conn
    conn.close()


def handoff(db, tenant="tenant-a", record_tenant="tenant-a",
            opportunity="lead-one", approval="owner-approved-1",
            fingerprint="a" * 64):
    record_verified_owner_approval(
        db, acting_tenant_id=tenant, record_tenant_id=record_tenant,
        opportunity_id=opportunity, approval_reference=approval,
        input_sha256=fingerprint, reviewer_id="owner-1",
        reviewer_authorized=True,
    )
    return handoff_approved_opportunity(
        db, acting_tenant_id=tenant, record_tenant_id=record_tenant,
        opportunity_id=opportunity, approval_reference=approval,
        input_sha256=fingerprint,
    )


def test_repeated_handoff_is_idempotent_and_exactly_one_job(db):
    first = handoff(db)
    assert handoff(db) == first
    assert get_job_state(db, tenant_id="tenant-a", job_id=first.job_id) == "queued"
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 1
    claim = claim_job(db, tenant_id="tenant-a", now=100, job_id=first.job_id)
    assert claim is not None and claim.job_id == first.job_id


def test_cross_tenant_handoff_denied_and_invisible(db):
    first = handoff(db)
    with pytest.raises(JobConflict, match="owner approval|Tenant"):
        handoff(db, tenant="tenant-b", record_tenant="tenant-a")
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_approvals").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 1
    assert get_assignment_handoff(db, acting_tenant_id="tenant-b",
                                  opportunity_id="lead-one") is None
    assert get_assignment_handoff(db, acting_tenant_id="tenant-a",
                                  opportunity_id="lead-one") == first


def test_conflicting_approval_and_fingerprint_rollback(db):
    original = handoff(db)
    for approval, fingerprint in (("different", "a" * 64),
                                  ("owner-approved-1", "b" * 64)):
        with pytest.raises(JobConflict):
            handoff(db, approval=approval, fingerprint=fingerprint)
    assert handoff(db) == original
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 1


@pytest.mark.parametrize("opportunity,approval", [
    ("", "yes"), ("lead\nother", "yes"), ("lead", ""),
    ("lead", "bad\x00approval"),
])
def test_invalid_identifiers_do_not_enqueue(db, opportunity, approval):
    with pytest.raises(JobConflict):
        handoff(db, opportunity=opportunity, approval=approval)
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 0


def test_restart_retains_approved_handoff(tmp_path):
    file = tmp_path / "restart.sqlite"
    first = sqlite3.connect(file)
    ensure_schema(first)
    ensure_handoff_schema(first)
    original = handoff(first)
    first.close()
    second = sqlite3.connect(file)
    assert get_assignment_handoff(
        second, acting_tenant_id="tenant-a", opportunity_id="lead-one",
    ) == original
    assert handoff(second) == original
    second.close()


def test_unregistered_approval_cannot_create_job(db):
    with pytest.raises(JobConflict, match="Verified owner approval"):
        handoff_approved_opportunity(
            db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
            opportunity_id="lead-one", approval_reference="fake-reference",
            input_sha256="a" * 64,
        )
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 0


def test_unverified_reviewer_cannot_register_approval(db):
    with pytest.raises(JobConflict, match="Authenticated owner approval"):
        record_verified_owner_approval(
            db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
            opportunity_id="lead-one", approval_reference="owner-approved-1",
            input_sha256="a" * 64, reviewer_id="owner-1",
            reviewer_authorized=False,
        )
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_approvals").fetchone()[0] == 0


def test_matching_approval_is_required_for_same_fingerprint(db):
    record_verified_owner_approval(
        db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
        opportunity_id="lead-one", approval_reference="owner-approved-1",
        input_sha256="a" * 64, reviewer_id="owner-1",
        reviewer_authorized=True,
    )
    with pytest.raises(JobConflict, match="Verified owner approval"):
        handoff_approved_opportunity(
            db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
            opportunity_id="lead-one", approval_reference="different",
            input_sha256="a" * 64,
        )
    assert db.execute("SELECT COUNT(*) FROM nova_operations_offline_jobs").fetchone()[0] == 0


def test_conflicting_approval_registration_preserves_original(db):
    first = handoff(db)
    with pytest.raises(JobConflict, match="Conflicting owner approval"):
        record_verified_owner_approval(
            db, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
            opportunity_id="lead-one", approval_reference="second-approval",
            input_sha256="a" * 64, reviewer_id="owner-1",
            reviewer_authorized=True,
        )
    assert get_assignment_handoff(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one",
    ) == first
    row = db.execute(
        """SELECT approval_reference FROM nova_operations_offline_approvals
           WHERE tenant_id=? AND opportunity_id=?""",
        ("tenant-a", "lead-one"),
    ).fetchone()
    assert row == ("owner-approved-1",)


def test_same_opportunity_identifier_is_isolated_between_tenants(db):
    first = handoff(db)
    second = handoff(db, tenant="tenant-b", record_tenant="tenant-b")
    assert second.job_id != first.job_id
    assert get_assignment_handoff(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one",
    ) == first
    assert get_assignment_handoff(
        db, acting_tenant_id="tenant-b", opportunity_id="lead-one",
    ) == second


@pytest.mark.parametrize("table,column,value", [
    ("nova_operations_offline_approvals", "approval_reference", "tampered-approval"),
    ("nova_operations_offline_approvals", "input_sha256", "b" * 64),
    ("nova_operations_offline_handoffs", "input_sha256", "b" * 64),
    ("nova_operations_offline_jobs", "tenant_id", "tenant-b"),
    ("nova_operations_offline_jobs", "kind", "other_job"),
    ("nova_operations_offline_jobs", "input_sha256", "b" * 64),
])
def test_corrupted_assignment_links_fail_closed(db, table, column, value):
    original = handoff(db)
    db.execute(
        f"UPDATE {table} SET {column}=?",
        (value,),
    )
    db.commit()
    with pytest.raises(JobConflict, match="inconsistent"):
        get_assignment_handoff(
            db, acting_tenant_id="tenant-a", opportunity_id="lead-one",
        )


def test_missing_linked_job_fails_closed(db):
    first = handoff(db)
    db.execute("DELETE FROM nova_operations_offline_jobs WHERE job_id=?", (first.job_id,))
    db.commit()
    with pytest.raises(JobConflict, match="inconsistent"):
        get_assignment_handoff(
            db, acting_tenant_id="tenant-a", opportunity_id="lead-one",
        )


def test_guarded_claim_requires_approved_link(db):
    with pytest.raises(JobConflict, match="Tenant"):
        handoff_approved_opportunity(
            db, acting_tenant_id="tenant-b", record_tenant_id="tenant-a",
            opportunity_id="lead-one", approval_reference="owner-approved-1",
            input_sha256="a" * 64,
        )
    assert claim_approved_assignment(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one", now=100,
    ) is None
    job = handoff(db)
    claim = claim_approved_assignment(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one", now=100,
    )
    assert claim is not None and claim.job_id == job.job_id
    assert claim_approved_assignment(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one", now=101,
    ) is None
    assert claim_approved_assignment(
        db, acting_tenant_id="tenant-b", opportunity_id="lead-one", now=101,
    ) is None


def test_guarded_claim_rejects_changed_approval_without_mutating_job(db):
    link = handoff(db)
    db.execute(
        "UPDATE nova_operations_offline_approvals SET approval_reference='tampered'"
    )
    db.commit()
    assert claim_approved_assignment(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one", now=100,
    ) is None
    assert get_job_state(db, tenant_id="tenant-a", job_id=link.job_id) == "queued"


def test_guarded_claim_expiry_retry_fences_old_worker(db):
    link = handoff(db)
    first = claim_approved_assignment(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one",
        now=100, lease_seconds=10,
    )
    second = claim_approved_assignment(
        db, acting_tenant_id="tenant-a", opportunity_id="lead-one",
        now=110, lease_seconds=20,
    )
    assert first.job_id == second.job_id == link.job_id
    assert first.lease_token != second.lease_token
    assert second.attempts == 2


@pytest.mark.parametrize("bad_clock", [None, True, -1, "100"])
def test_guarded_claim_rejects_invalid_clock(db, bad_clock):
    handoff(db)
    with pytest.raises(JobConflict, match="Invalid assignment claim"):
        claim_approved_assignment(
            db, acting_tenant_id="tenant-a",
            opportunity_id="lead-one", now=bad_clock,
        )


@pytest.mark.parametrize("table,column,value", [
    ("nova_operations_offline_approvals", "approval_reference", "tampered"),
    ("nova_operations_offline_approvals", "reviewer_id", "bad\nreviewer"),
    ("nova_operations_offline_handoffs", "input_sha256", "b" * 64),
    ("nova_operations_offline_jobs", "kind", "different"),
])
def test_guarded_claim_rejects_corrupt_link_before_lease(db, table, column, value):
    assigned = handoff(db)
    db.execute(f"UPDATE {table} SET {column}=?", (value,))
    db.commit()
    with pytest.raises(JobConflict, match="inconsistent|reviewer"):
        claim_approved_assignment(
            db, acting_tenant_id="tenant-a", opportunity_id="lead-one", now=100,
        )
    assert get_job_state(db, tenant_id="tenant-a", job_id=assigned.job_id) == "queued"
