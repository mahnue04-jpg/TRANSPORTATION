"""Offline synthetic approved-opportunity handoff tests."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_assignment_handoff import (
    ensure_handoff_schema, get_assignment_handoff, handoff_approved_opportunity,
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
    with pytest.raises(JobConflict, match="Tenant"):
        handoff(db, tenant="tenant-b", record_tenant="tenant-a")
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
