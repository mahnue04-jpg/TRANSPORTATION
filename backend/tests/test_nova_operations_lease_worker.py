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
