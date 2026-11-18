"""Synthetic PostgreSQL-only lease/fencing tests (no worker or real customer files).

Uses the disposable loopback PostgreSQL supplied by the existing Operations CI
job; this test creates and drops only its own lease table.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import os
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_postgres_leases as leases


@pytest.fixture
def database(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Disposable loopback PostgreSQL required in CI")
        pytest.skip("Disposable loopback PostgreSQL unavailable")
    engine = sa.create_engine(url)
    leases.lease_metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    yield engine
    leases.lease_metadata.drop_all(engine)
    engine.dispose()


def seed(engine, job_id="synthetic-a"):
    with Session(engine) as db:
        leases.enqueue(db, job_id=job_id, organization_id="org-a",
                       owner_user_id="owner-a", input_sha256="a" * 64)


def test_lease_claim_recovery_and_stale_fence(database):
    seed(database)
    now = datetime.now(timezone.utc)
    with Session(database) as db:
        first = leases.claim(db, now=now, lease_seconds=60)
        assert first and first.attempts == 1
    # New DB session simulates disconnected client/restart. A claim remains
    # leased until expiration. No claim is possible before it expires.
    with Session(database) as db:
        assert leases.claim(db, now=now + timedelta(seconds=20)) is None
    with Session(database) as db:
        second = leases.claim(db, now=now + timedelta(seconds=61))
        assert second and second.job_id == first.job_id
        assert second.token != first.token and second.attempts == 2
        with pytest.raises(leases.LeaseBlocked, match="Stale"):
            leases.complete(db, claimed=first, output_sha256="b" * 64,
                            now=now + timedelta(seconds=62))
        leases.complete(db, claimed=second, output_sha256="b" * 64,
                        now=now + timedelta(seconds=62))
        assert leases.claim(db, now=now + timedelta(seconds=120)) is None


def test_two_workers_claim_only_once(database):
    seed(database)
    gate = Barrier(2)
    def try_claim():
        with Session(database) as db:
            gate.wait(timeout=10)
            return leases.claim(db)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(try_claim)
        b = pool.submit(try_claim)
        claims = [a.result(timeout=15), b.result(timeout=15)]
    assert sum(claim is not None for claim in claims) == 1


def test_failed_claim_retries_and_exhausts(database):
    seed(database)
    now = datetime.now(timezone.utc)
    for attempt in (1, 2, 3):
        with Session(database) as db:
            claimed = leases.claim(db, now=now + timedelta(seconds=attempt * 40))
            assert claimed and claimed.attempts == attempt
            result = leases.fail_or_retry(
                db, claimed=claimed,
                now=now + timedelta(seconds=attempt * 40),
                retry_delay_seconds=1)
            assert result == ("FAILED" if attempt == 3 else "QUEUED")
    with Session(database) as db:
        assert leases.claim(db, now=now + timedelta(hours=1)) is None


def test_default_disabled_and_fingerprint_scope_reuse(database, monkeypatch):
    seed(database)
    with Session(database) as db:
        with pytest.raises(leases.LeaseBlocked, match="different"):
            leases.enqueue(db, job_id="synthetic-a", organization_id="org-b",
                           owner_user_id="owner-a", input_sha256="a" * 64)
        monkeypatch.delenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED")
        with pytest.raises(leases.LeaseBlocked, match="disabled"):
            leases.claim(db)


def test_renew_extends_only_current_lease(database):
    seed(database, "synthetic-renew")
    now = datetime.now(timezone.utc)
    with Session(database) as db:
        current = leases.claim(db, now=now, lease_seconds=30)
        assert current
        leases.renew(db, claimed=current, now=now + timedelta(seconds=10),
                     lease_seconds=60)
        assert leases.claim(db, now=now + timedelta(seconds=40)) is None
        with pytest.raises(leases.LeaseBlocked, match="expired"):
            leases.renew(db, claimed=current, now=now + timedelta(seconds=71))
        leases.complete(db, claimed=current, output_sha256="b" * 64,
                        now=now + timedelta(seconds=60))


def test_expired_exhausted_claim_is_terminal_and_not_reclaimed(database):
    seed(database, "synthetic-exhaust")
    now = datetime.now(timezone.utc)
    with Session(database) as db:
        db.execute(sa.update(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-exhaust"
        ).values(attempts=2))
        db.commit()
        final = leases.claim(db, now=now, lease_seconds=10)
        assert final and final.attempts == 3
        assert leases.claim(db, now=now + timedelta(seconds=11)) is None
        assert leases.exhaust_expired(db, now=now + timedelta(seconds=11)) == 1
        assert leases.exhaust_expired(db, now=now + timedelta(seconds=12)) == 0
        with pytest.raises(leases.LeaseBlocked):
            leases.complete(db, claimed=final, output_sha256="b" * 64,
                            now=now + timedelta(seconds=12))
        state = db.execute(sa.select(leases.lease_jobs.c.state).where(
            leases.lease_jobs.c.job_id == "synthetic-exhaust")).scalar_one()
        assert state == "FAILED"


def test_cancel_fences_active_worker_and_prevents_reclaim(database):
    seed(database, "synthetic-cancel")
    now = datetime.now(timezone.utc)
    with Session(database) as db:
        active = leases.claim(db, now=now, lease_seconds=120)
        assert active is not None
    with Session(database) as db:
        assert leases.cancel(db, job_id=active.job_id,
                             organization_id=active.organization_id,
                             owner_user_id=active.owner_user_id,
                             now=now + timedelta(seconds=1))
        assert not leases.cancel(db, job_id=active.job_id,
                                 organization_id=active.organization_id,
                                 owner_user_id=active.owner_user_id,
                                 now=now + timedelta(seconds=2))
        assert leases.claim(db, now=now + timedelta(seconds=200)) is None
        with pytest.raises(leases.LeaseBlocked, match="Stale"):
            leases.complete(db, claimed=active, output_sha256="b" * 64,
                            now=now + timedelta(seconds=3))
        with pytest.raises(leases.LeaseBlocked, match="Stale"):
            leases.renew(db, claimed=active, now=now + timedelta(seconds=3))


def test_cancel_wrong_tenant_is_noop_and_current_worker_can_complete(database):
    seed(database, "synthetic-other-tenant")
    now = datetime.now(timezone.utc)
    with Session(database) as db:
        active = leases.claim(db, now=now, lease_seconds=60)
        assert active is not None
        assert not leases.cancel(db, job_id=active.job_id,
                                 organization_id="another-org",
                                 owner_user_id=active.owner_user_id,
                                 now=now + timedelta(seconds=1))
        leases.complete(db, claimed=active, output_sha256="b" * 64,
                        now=now + timedelta(seconds=2))


def test_expired_worker_cannot_retry_before_new_claim(database):
    seed(database, "synthetic-expired-fail")
    now = datetime.now(timezone.utc)
    with Session(database) as db:
        active = leases.claim(db, now=now, lease_seconds=5)
        assert active is not None
        with pytest.raises(leases.LeaseBlocked, match="Stale"):
            leases.fail_or_retry(db, claimed=active,
                                 now=now + timedelta(seconds=6))
        recovered = leases.claim(db, now=now + timedelta(seconds=7),
                                 lease_seconds=60)
        assert recovered is not None and recovered.token != active.token


def test_concurrent_duplicate_enqueue_is_idempotent(database):
    gate = Barrier(2)

    def submit():
        with Session(database) as db:
            gate.wait(timeout=10)
            leases.enqueue(db, job_id="same-job", organization_id="org-a",
                           owner_user_id="owner-a", input_sha256="a" * 64)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(submit)
        second = pool.submit(submit)
        first.result(timeout=20)
        second.result(timeout=20)
    with Session(database) as db:
        rows = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "same-job")).mappings().all()
        assert len(rows) == 1
        assert rows[0]["state"] == "QUEUED"
        assert rows[0]["attempts"] == 0
