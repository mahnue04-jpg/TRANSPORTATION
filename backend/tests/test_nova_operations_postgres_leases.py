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
