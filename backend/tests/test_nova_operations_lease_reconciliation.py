"""Read-only held job reconciliation tests against disposable PostgreSQL."""
import hashlib
import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_postgres_leases as leases
from app.core.nova.work_revenue.operations_lease_reconciliation import inspect_held_job


@pytest.fixture
def engine(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Ephemeral loopback PostgreSQL required in CI")
        pytest.skip("Disposable PostgreSQL unavailable")
    engine = sa.create_engine(url)
    leases.lease_metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    yield engine
    leases.lease_metadata.drop_all(engine)
    engine.dispose()


def prepare_held(engine, raw=b"synthetic,review\nAda,ready\n", job_id="synthetic-held"):
    expected = hashlib.sha256(raw).hexdigest()
    with Session(engine) as db:
        leases.enqueue(db, job_id=job_id, organization_id="org-a",
                       owner_user_id="owner-a", input_sha256="a" * 64)
        claimed = leases.claim(db)
        assert claimed and claimed.job_id == job_id
        assert leases.hold_for_reconciliation(
            db, claimed=claimed, expected_output_sha256=expected)
    return raw


def test_read_only_match_does_not_approve_or_release(engine):
    raw = prepare_held(engine)
    with Session(engine) as db:
        before = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-held")).mappings().one()
        result = inspect_held_job(
            db, job_id="synthetic-held", organization_id="org-a",
            owner_user_id="owner-a",
            artifact_reader=lambda org, owner, job: raw)
        after = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "synthetic-held")).mappings().one()
        assert result == {"job_id": "synthetic-held",
                          "result": "digest_matches", "may_release": False}
        assert dict(before) == dict(after)
        assert leases.claim(db) is None


def test_mismatch_missing_and_unavailable_all_fail_closed(engine):
    prepare_held(engine)
    with Session(engine) as db:
        def inspect(reader):
            return inspect_held_job(
                db, job_id="synthetic-held", organization_id="org-a",
                owner_user_id="owner-a", artifact_reader=reader)
        assert inspect(lambda *_: b"wrong")["result"] == "digest_mismatch"
        assert inspect(lambda *_: None)["result"] == "artifact_missing"
        assert inspect(lambda *_: (_ for _ in ()).throw(IOError("offline")))["result"] == "artifact_unavailable"
        assert inspect(lambda *_: "not bytes")["result"] == "artifact_invalid"
        assert inspect(lambda *_: b"x" * (1024 * 1024 + 1))["result"] == "artifact_invalid"
        assert all(inspect(lambda *_: None)[k] is False for k in ("may_release",))


def test_cross_owner_cannot_read_artifact(engine):
    raw = prepare_held(engine)
    called = []
    with Session(engine) as db:
        with pytest.raises(leases.LeaseBlocked, match="authorized scope"):
            inspect_held_job(
                db, job_id="synthetic-held", organization_id="org-a",
                owner_user_id="another-owner",
                artifact_reader=lambda *args: called.append(args) or raw)
    assert called == []


def test_nonheld_jobs_are_not_reconciled(engine):
    with Session(engine) as db:
        leases.enqueue(db, job_id="queued", organization_id="org-a",
                       owner_user_id="owner-a", input_sha256="a" * 64)
        with pytest.raises(leases.LeaseBlocked, match="not on reconciliation"):
            inspect_held_job(
                db, job_id="queued", organization_id="org-a",
                owner_user_id="owner-a", artifact_reader=lambda *_: b"data")


def test_feature_disabled_blocks_reader(engine, monkeypatch):
    prepare_held(engine)
    monkeypatch.delenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED")
    called = []
    with Session(engine) as db:
        with pytest.raises(leases.LeaseBlocked, match="disabled"):
            inspect_held_job(
                db, job_id="synthetic-held", organization_id="org-a",
                owner_user_id="owner-a",
                artifact_reader=lambda *_: called.append(True) or b"test")
    assert not called
