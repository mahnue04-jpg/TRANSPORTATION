"""Offline integration fixture: session-derived approval, job claim, review gate."""
import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue import operations_owner_scope as scope
from app.core.nova.work_revenue.operations_authenticated_handoff import (
    approve_and_handoff_offline, review_approved_assignment_offline,
)
from app.core.nova.work_revenue.operations_assignment_handoff import (
    claim_approved_assignment, ensure_handoff_schema,
)
from app.core.nova.work_revenue.operations_artifact_review import (
    ensure_artifact_schema,
)
from app.core.nova.work_revenue.operations_job_queue import (
    JobConflict, ensure_schema,
)

DIGEST = hashlib.sha256(b"Name\nSynthetic\n").hexdigest()


@pytest.fixture
def db(tmp_path):
    conn = sqlite3.connect(tmp_path / "auth-handoff.sqlite")
    ensure_schema(conn)
    ensure_handoff_schema(conn)
    ensure_artifact_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def direct_scope(monkeypatch):
    monkeypatch.setattr(
        scope.NovaCoreService, "resolve_organization_scope",
        lambda user, requested: user.organization_id,
    )


def owner(tenant="tenant-a", actor="owner-a"):
    # This simulates an already-authenticated server session. It does not
    # validate a JWT or prove that the actor has owner privileges.
    return SimpleNamespace(organization_id=tenant, user_id=actor)


def approve(db, actor=None):
    return approve_and_handoff_offline(
        db, authenticated_owner=actor or owner(),
        opportunity_id="synthetic-opportunity-1",
        approval_reference="synthetic-approval-1",
        input_sha256=DIGEST,
    )


def test_authenticated_fields_bind_approval_and_job(db):
    handoff = approve(db)
    assert handoff.tenant_id == "tenant-a"
    assert handoff.opportunity_id == "synthetic-opportunity-1"
    assert db.execute(
        """SELECT tenant_id, reviewer_id, input_sha256
           FROM nova_operations_offline_approvals"""
    ).fetchone() == ("tenant-a", "owner-a", DIGEST)
    assert approve(db) == handoff
    claim = claim_approved_assignment(
        db, acting_tenant_id="tenant-a",
        opportunity_id="synthetic-opportunity-1", now=100,
    )
    assert claim is not None and claim.job_id == handoff.job_id
    assert claim_approved_assignment(
        db, acting_tenant_id="tenant-b",
        opportunity_id="synthetic-opportunity-1", now=100,
    ) is None


def test_conflicting_authenticated_actor_cannot_replace_approval(db):
    approve(db)
    with pytest.raises(JobConflict, match="Conflicting owner approval"):
        approve(db, owner(actor="other-owner"))
    assert db.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_jobs"
    ).fetchone()[0] == 1


@pytest.mark.parametrize("bad", [
    owner(tenant="global"), owner(tenant=""), owner(actor=""),
    owner(actor="bad\nactor"),
])
def test_invalid_session_cannot_register_approval(db, bad):
    with pytest.raises(HTTPException) as exc:
        approve(db, bad)
    assert exc.value.status_code == 403
    assert db.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_approvals"
    ).fetchone()[0] == 0



def test_restart_after_approval_before_handoff_recovers_once(tmp_path):
    """Simulate interruption between two independently committed operations."""
    from app.core.nova.work_revenue.operations_assignment_handoff import (
        handoff_approved_opportunity, record_verified_owner_approval,
    )

    path = tmp_path / "approval-recovery.sqlite"
    conn = sqlite3.connect(path)
    ensure_schema(conn)
    ensure_handoff_schema(conn)
    record_verified_owner_approval(
        conn, acting_tenant_id="tenant-a", record_tenant_id="tenant-a",
        opportunity_id="synthetic-opportunity-1",
        approval_reference="synthetic-approval-1",
        input_sha256=DIGEST, reviewer_id="owner-a",
        reviewer_authorized=True,
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_jobs"
    ).fetchone()[0] == 0
    conn.close()

    recovered = sqlite3.connect(path)
    try:
        first = approve(recovered)
        assert approve(recovered) == first
        assert recovered.execute(
            "SELECT COUNT(*) FROM nova_operations_offline_jobs"
        ).fetchone()[0] == 1
        assert recovered.execute(
            "SELECT COUNT(*) FROM nova_operations_offline_handoffs"
        ).fetchone()[0] == 1
        with pytest.raises(JobConflict, match="Verified owner approval"):
            handoff_approved_opportunity(
                recovered, acting_tenant_id="tenant-a",
                record_tenant_id="tenant-a",
                opportunity_id="synthetic-opportunity-1",
                approval_reference="synthetic-approval-1",
                input_sha256="a" * 64,
            )
        assert recovered.execute(
            "SELECT COUNT(*) FROM nova_operations_offline_jobs"
        ).fetchone()[0] == 1
    finally:
        recovered.close()


def test_replay_with_different_fingerprint_cannot_change_approved_job(db):
    first = approve(db)
    with pytest.raises(JobConflict, match="Conflicting owner approval"):
        approve_and_handoff_offline(
            db, authenticated_owner=owner(),
            opportunity_id="synthetic-opportunity-1",
            approval_reference="synthetic-approval-1",
            input_sha256="b" * 64,
        )
    assert db.execute(
        "SELECT job_id, input_sha256 FROM nova_operations_offline_jobs"
    ).fetchone() == (first.job_id, DIGEST)



def test_atomic_handoff_rolls_back_when_job_insert_fails(db):
    """A failed job write must not leave a fresh approval behind."""
    db.execute(
        """CREATE TRIGGER reject_synthetic_job
           BEFORE INSERT ON nova_operations_offline_jobs
           BEGIN
             SELECT RAISE(ABORT, 'synthetic job insert failure');
           END"""
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="synthetic job insert failure"):
        approve(db)
    assert db.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_approvals"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_handoffs"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT COUNT(*) FROM nova_operations_offline_jobs"
    ).fetchone()[0] == 0


def test_atomic_handoff_rolls_back_when_link_insert_fails(db):
    """A failed handoff write must not leave approval or orphaned job."""
    db.execute(
        """CREATE TRIGGER reject_synthetic_handoff
           BEFORE INSERT ON nova_operations_offline_handoffs
           BEGIN
             SELECT RAISE(ABORT, 'synthetic handoff insert failure');
           END"""
    )
    db.commit()
    with pytest.raises(sqlite3.IntegrityError, match="synthetic handoff insert failure"):
        approve(db)
    for table in (
        "nova_operations_offline_approvals",
        "nova_operations_offline_handoffs",
        "nova_operations_offline_jobs",
    ):
        assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0



def test_two_connections_reuse_one_approved_job_after_restart(tmp_path):
    """Independent sessions must not multiply jobs for the same approval."""
    path = tmp_path / "two-session-handoff.sqlite"
    first_db = sqlite3.connect(path)
    ensure_schema(first_db)
    ensure_handoff_schema(first_db)
    second_db = sqlite3.connect(path)
    try:
        first = approve(first_db)
        second = approve(second_db)
        assert second == first
        for table in (
            "nova_operations_offline_approvals",
            "nova_operations_offline_jobs",
            "nova_operations_offline_handoffs",
        ):
            assert first_db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 1
        with pytest.raises(JobConflict, match="Conflicting owner approval"):
            approve(second_db, owner(actor="different-owner"))
        assert approve(first_db) == first
    finally:
        first_db.close()
        second_db.close()


def test_concurrent_write_lock_cannot_create_partial_assignment(tmp_path):
    """Second connection fails safely while another SQLite writer holds the lock."""
    path = tmp_path / "locked-approval.sqlite"
    first_db = sqlite3.connect(path)
    ensure_schema(first_db)
    ensure_handoff_schema(first_db)
    second_db = sqlite3.connect(path, timeout=0)
    try:
        first_db.execute("BEGIN IMMEDIATE")
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            approve(second_db)
        first_db.rollback()
        assert approve(second_db).tenant_id == "tenant-a"
        for table in (
            "nova_operations_offline_approvals",
            "nova_operations_offline_jobs",
            "nova_operations_offline_handoffs",
        ):
            assert first_db.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0] == 1
    finally:
        if first_db.in_transaction:
            first_db.rollback()
        first_db.close()
        second_db.close()



def test_session_approved_csv_lifecycle_requires_owner_review_after_restart(tmp_path):
    """Exercise the complete synthetic handoff; release stays metadata-only."""
    from app.core.nova.work_revenue.operations_artifact_review import (
        complete_and_store_review_artifact, review_artifact,
    )
    from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text
    from app.core.nova.work_revenue.operations_release_gate import (
        check_offline_release_eligibility,
    )

    path = tmp_path / "full-session-flow.sqlite"
    conn = sqlite3.connect(path)
    ensure_schema(conn)
    ensure_handoff_schema(conn)
    ensure_artifact_schema(conn)
    raw = "Name\nSynthetic\nSynthetic\n"
    raw_digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    link = approve_and_handoff_offline(
        conn, authenticated_owner=owner(),
        opportunity_id="synthetic-opportunity-1",
        approval_reference="synthetic-approval-1",
        input_sha256=raw_digest,
    )
    conn.close()

    conn = sqlite3.connect(path)
    try:
        with pytest.raises(JobConflict, match="owner-reviewed"):
            check_offline_release_eligibility(
                conn, acting_tenant_id="tenant-a",
                opportunity_id="synthetic-opportunity-1",
            )
        job = claim_approved_assignment(
            conn, acting_tenant_id="tenant-a",
            opportunity_id="synthetic-opportunity-1", now=100,
        )
        assert job.job_id == link.job_id
        cleaned = clean_csv_text(raw)
        assert cleaned.input_sha256 == job.input_sha256
        assert cleaned.duplicate_rows_removed == 1
        complete_and_store_review_artifact(
            conn, job=job, csv_text=cleaned.cleaned_csv,
            output_sha256=cleaned.output_sha256, now=101,
        )
        with pytest.raises(JobConflict, match="owner-reviewed"):
            check_offline_release_eligibility(
                conn, acting_tenant_id="tenant-a",
                opportunity_id="synthetic-opportunity-1",
            )
        assert review_artifact(
            conn, tenant_id="tenant-a", job_id=link.job_id,
            reviewer_id="owner-a", approve=True,
        ) == "approved"
    finally:
        conn.close()

    reopened = sqlite3.connect(path)
    try:
        ready = check_offline_release_eligibility(
            reopened, acting_tenant_id="tenant-a",
            opportunity_id="synthetic-opportunity-1",
        )
        assert ready.job_id == link.job_id
        assert ready.reviewer_id == "owner-a"
        assert ready.output_sha256 == cleaned.output_sha256
        assert not hasattr(ready, "csv_text")
        with pytest.raises(JobConflict, match="not found"):
            check_offline_release_eligibility(
                reopened, acting_tenant_id="tenant-b",
                opportunity_id="synthetic-opportunity-1",
            )
    finally:
        reopened.close()


def test_wrong_reviewer_cannot_make_session_approved_artifact_releasable(db):
    from app.core.nova.work_revenue.operations_artifact_review import (
        complete_and_store_review_artifact, review_artifact,
    )
    from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text
    from app.core.nova.work_revenue.operations_release_gate import (
        check_offline_release_eligibility,
    )

    raw = "Name\nSynthetic\n"
    link = approve_and_handoff_offline(
        db, authenticated_owner=owner(),
        opportunity_id="synthetic-opportunity-1",
        approval_reference="synthetic-approval-1",
        input_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
    job = claim_approved_assignment(
        db, acting_tenant_id="tenant-a",
        opportunity_id="synthetic-opportunity-1", now=100,
    )
    cleaned = clean_csv_text(raw)
    assert cleaned.input_sha256 == job.input_sha256
    complete_and_store_review_artifact(
        db, job=job, csv_text=cleaned.cleaned_csv,
        output_sha256=cleaned.output_sha256, now=101,
    )
    review_artifact(
        db, tenant_id="tenant-a", job_id=link.job_id,
        reviewer_id="different-reviewer", approve=True,
    )
    with pytest.raises(JobConflict, match="integrity"):
        check_offline_release_eligibility(
            db, acting_tenant_id="tenant-a",
            opportunity_id="synthetic-opportunity-1",
        )



def test_session_review_uses_approved_actor_and_rejects_replay(db):
    from app.core.nova.work_revenue.operations_artifact_review import (
        complete_and_store_review_artifact,
    )
    from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text
    from app.core.nova.work_revenue.operations_release_gate import (
        check_offline_release_eligibility,
    )

    raw = "Name\nSynthetic\n"
    link = approve_and_handoff_offline(
        db, authenticated_owner=owner(),
        opportunity_id="synthetic-opportunity-1",
        approval_reference="synthetic-approval-1",
        input_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    )
    job = claim_approved_assignment(
        db, acting_tenant_id="tenant-a",
        opportunity_id="synthetic-opportunity-1", now=100,
    )
    cleaned = clean_csv_text(raw)
    complete_and_store_review_artifact(
        db, job=job, csv_text=cleaned.cleaned_csv,
        output_sha256=cleaned.output_sha256, now=101,
    )
    with pytest.raises(JobConflict, match="Review actor"):
        review_approved_assignment_offline(
            db, authenticated_owner=owner(actor="other-owner"),
            opportunity_id="synthetic-opportunity-1", approve=True,
        )
    with pytest.raises(JobConflict, match="unavailable"):
        review_approved_assignment_offline(
            db, authenticated_owner=owner(tenant="tenant-b"),
            opportunity_id="synthetic-opportunity-1", approve=True,
        )
    assert review_approved_assignment_offline(
        db, authenticated_owner=owner(),
        opportunity_id="synthetic-opportunity-1", approve=True,
    ) == "approved"
    with pytest.raises(JobConflict, match="already reviewed"):
        review_approved_assignment_offline(
            db, authenticated_owner=owner(),
            opportunity_id="synthetic-opportunity-1", approve=False,
        )
    ready = check_offline_release_eligibility(
        db, acting_tenant_id="tenant-a",
        opportunity_id="synthetic-opportunity-1",
    )
    assert ready.job_id == link.job_id
    assert ready.reviewer_id == "owner-a"


def test_session_review_denies_uncompleted_job_and_nonboolean_choice(db):
    approve(db)
    with pytest.raises(JobConflict, match="boolean"):
        review_approved_assignment_offline(
            db, authenticated_owner=owner(),
            opportunity_id="synthetic-opportunity-1", approve="yes",
        )
    with pytest.raises(JobConflict, match="Completed artifact"):
        review_approved_assignment_offline(
            db, authenticated_owner=owner(),
            opportunity_id="synthetic-opportunity-1", approve=True,
        )
