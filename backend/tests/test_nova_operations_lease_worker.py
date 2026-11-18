"""Synthetic single-run worker acceptance against ephemeral loopback PostgreSQL."""
import os
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_postgres_leases as leases
from app.core.nova.work_revenue.operations_lease_worker import run_one


@pytest.fixture
def engine(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Ephemeral loopback PostgreSQL is mandatory in CI")
        pytest.skip("No disposable PostgreSQL configured")
    engine = sa.create_engine(url)
    leases.lease_metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    yield engine
    leases.lease_metadata.drop_all(engine)
    engine.dispose()


def seed(engine, job_id):
    with Session(engine) as db:
        leases.enqueue(db, job_id=job_id, organization_id="test-org",
                       owner_user_id="test-owner", input_sha256="a" * 64)


def test_claim_handler_complete_with_fresh_sessions(engine):
    seed(engine, "synthetic-worker-1")
    seen = []
    def handler(claim):
        seen.append((claim.job_id, claim.attempts))
        return "b" * 64
    factory = lambda: Session(engine)
    assert run_one(factory, handler)["state"] == "completed"
    assert seen == [("synthetic-worker-1", 1)]
    assert run_one(factory, handler)["state"] == "idle"
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-worker-1")).mappings().one()
        assert row["state"] == "COMPLETED"
        assert row["output_sha256"] == "b" * 64


def test_failed_handler_requeues_but_never_reports_success(engine):
    seed(engine, "synthetic-worker-2")
    factory = lambda: Session(engine)
    def broken(_claim):
        raise RuntimeError("synthetic interruption")
    outcome = run_one(factory, broken, retry_delay_seconds=0)
    assert outcome == {"state": "queued", "job_id": "synthetic-worker-2"}
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-worker-2")).mappings().one()
        assert row["attempts"] == 1 and row["state"] == "QUEUED"


def test_handler_cancellation_never_commits_or_requeues(engine):
    seed(engine, "synthetic-worker-3")
    factory = lambda: Session(engine)
    def cancel_during_work(claim):
        with factory() as db:
            assert leases.cancel(db, job_id=claim.job_id,
                                 organization_id=claim.organization_id,
                                 owner_user_id=claim.owner_user_id)
        return "b" * 64
    assert run_one(factory, cancel_during_work)["state"] == "stale"
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-worker-3")).mappings().one()
        assert row["state"] == "CANCELLED"
        assert row["output_sha256"] is None


def test_default_off_does_not_claim(engine, monkeypatch):
    seed(engine, "synthetic-worker-4")
    monkeypatch.delenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED")
    with pytest.raises(leases.LeaseBlocked, match="disabled"):
        run_one(lambda: Session(engine), lambda _: "b" * 64)


def test_handler_success_with_ambiguous_db_completion_requires_reconciliation(engine, monkeypatch):
    seed(engine, "synthetic-worker-uncertain")
    factory = lambda: Session(engine)
    actual_complete = leases.complete
    calls = {"complete": 0, "handler": 0}

    def uncertain_commit(*args, **kwargs):
        calls["complete"] += 1
        raise RuntimeError("synthetic database connection lost after handler")

    def handler(_claimed):
        calls["handler"] += 1
        return "b" * 64

    monkeypatch.setattr(leases, "complete", uncertain_commit)
    result = run_one(factory, handler, retry_delay_seconds=0)
    assert result == {"state": "needs_reconciliation", "job_id": "synthetic-worker-uncertain"}
    assert calls == {"complete": 1, "handler": 1}
    monkeypatch.setattr(leases, "complete", actual_complete)
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-worker-uncertain"
        )).mappings().one()
        assert row["state"] == "NEEDS_RECONCILIATION"
        assert row["output_sha256"] == "b" * 64
        assert row["lease_token"] is None
        assert row["attempts"] == 1
        assert leases.claim(db) is None


def test_revoked_lease_at_completion_is_not_requeued(engine):
    seed(engine, "synthetic-worker-revoked")
    factory = lambda: Session(engine)

    def revoke_before_complete(claim):
        with factory() as db:
            assert leases.cancel(db, job_id=claim.job_id,
                                 organization_id=claim.organization_id,
                                 owner_user_id=claim.owner_user_id)
        return "b" * 64

    assert run_one(factory, revoke_before_complete) == {
        "state": "stale", "job_id": "synthetic-worker-revoked"
    }
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-worker-revoked"
        )).mappings().one()
        assert row["state"] == "CANCELLED" and row["attempts"] == 1


def test_ambiguous_completion_with_failed_hold_is_not_claimed_safe(engine, monkeypatch):
    seed(engine, "synthetic-worker-hold-failed")
    factory = lambda: Session(engine)
    def uncertain(*args, **kwargs):
        raise RuntimeError("synthetic completion connection loss")
    def hold_fails(*args, **kwargs):
        raise RuntimeError("synthetic reconciliation database outage")
    monkeypatch.setattr(leases, "complete", uncertain)
    monkeypatch.setattr(leases, "hold_for_reconciliation", hold_fails)
    assert run_one(factory, lambda _claim: "b" * 64) == {
        "state": "reconciliation_hold_unverified",
        "job_id": "synthetic-worker-hold-failed",
    }
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-worker-hold-failed",
        )).mappings().one()
        assert row["state"] == "RUNNING"


def test_strict_worker_does_not_run_unbound_input(engine):
    seed(engine, "synthetic-strict-unbound")
    invoked = []
    result = run_one(
        lambda: Session(engine),
        lambda claim: invoked.append(claim.job_id) or "b" * 64,
        require_bound_input=True,
    )
    assert result == {"state": "idle", "job_id": None}
    assert invoked == []
    with Session(engine) as db:
        state = db.execute(sa.select(leases.lease_jobs.c.state).where(
            leases.lease_jobs.c.job_id == "synthetic-strict-unbound",
        )).scalar_one()
        assert state == "QUEUED"
