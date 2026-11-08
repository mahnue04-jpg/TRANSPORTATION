"""Offline integration fixture: session-derived approval, job claim, review gate."""
import hashlib
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.nova.work_revenue import operations_owner_scope as scope
from app.core.nova.work_revenue.operations_authenticated_handoff import (
    approve_and_handoff_offline,
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
