"""Synthetic subprocess recovery proof using disposable PostgreSQL.

This exercises an actual new Python process against the same isolated CI
database. It is not a hosted worker restart, an S3 durability test, or approval
to process customer data. Only synthetic CSV bytes are used.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.nova.work_revenue import operations_postgres_leases as leases
from app.core.nova.work_revenue.operations_private_input import persist_private_csv_input


class SyntheticDiskStore:
    """Test-only stand-in for a durable private object store; no customer data."""

    def __init__(self, directory: Path):
        self.directory = directory

    def store(self, *, organization_id, application_id, category,
              filename, content_type, stream):
        assert category.startswith("nova-csv-input-")
        target = self.directory / "synthetic-input.csv"
        raw = stream.read()
        target.write_bytes(raw)
        return "fake-private", "synthetic-input.csv", len(raw)


@pytest.fixture
def engine(monkeypatch):
    url = os.getenv("NOVA_CSV_CI_DATABASE_URL", "")
    if not url or "127.0.0.1" not in url or "postgresql" not in url:
        if os.getenv("CI", "").lower() == "true":
            pytest.fail("Disposable loopback PostgreSQL is mandatory in CI")
        pytest.skip("Requires disposable loopback PostgreSQL")
    engine = sa.create_engine(url)
    leases.lease_metadata.create_all(engine)
    monkeypatch.setenv("NOVA_OPERATIONS_LEASE_WORKER_ENABLED", "true")
    yield engine
    leases.lease_metadata.drop_all(engine)
    engine.dispose()


def test_synthetic_process_reloads_bound_private_input(engine, tmp_path):
    raw = b"Name\nAda\nAda\n"
    receipt = persist_private_csv_input(
        organization_id="synthetic-org", owner_user_id="synthetic-owner",
        job_id="subprocess-job", raw=raw,
        store=SyntheticDiskStore(tmp_path),
    )
    with Session(engine) as db:
        leases.enqueue(db, job_id="subprocess-job",
                       organization_id="synthetic-org",
                       owner_user_id="synthetic-owner",
                       input_sha256=receipt.sha256)
        assert leases.bind_private_input(
            db, job_id="subprocess-job", organization_id="synthetic-org",
            owner_user_id="synthetic-owner", input_sha256=receipt.sha256,
            storage_ref=receipt.storage_ref, input_size=receipt.size)
    engine.dispose()

    code = r"""
import hashlib
import os
from pathlib import Path
import sqlalchemy as sa
from sqlalchemy.orm import Session
from app.core.nova.work_revenue import operations_postgres_leases as leases
from app.core.nova.work_revenue.operations_private_input import load_private_csv_input
from app.core.nova.work_revenue.operations_csv_cleanup import clean_csv_text
from app.core.nova.work_revenue.operations_lease_worker import run_one

class SyntheticDiskStore:
    def retrieve(self, *, storage_ref):
        if storage_ref != "synthetic-input.csv":
            raise ValueError("unknown synthetic fixture")
        return (Path(os.environ["SYNTHETIC_CSV_TEST_DIR"]) / storage_ref).read_bytes(), "text/csv"

engine = sa.create_engine(os.environ["NOVA_CSV_CI_DATABASE_URL"])
def handler(claim):
    with Session(engine) as db:
        ref, size = leases.read_bound_input_metadata(db, claimed=claim)
    raw = load_private_csv_input(
        organization_id=claim.organization_id, owner_user_id=claim.owner_user_id,
        job_id=claim.job_id, storage_ref=ref, expected_sha256=claim.input_sha256,
        store=SyntheticDiskStore())
    assert len(raw) == size
    result = clean_csv_text(raw.decode("utf-8"))
    return hashlib.sha256(result.cleaned_csv.encode("utf-8")).hexdigest()

result = run_one(lambda: Session(engine), handler)
assert result == {"state": "completed", "job_id": "subprocess-job"}, result
engine.dispose()
"""
    env = dict(os.environ)
    env["NOVA_OPERATIONS_LEASE_WORKER_ENABLED"] = "true"
    env["SYNTHETIC_CSV_TEST_DIR"] = str(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=str(Path(__file__).resolve().parents[1]),
        env=env, capture_output=True, text=True, timeout=30, check=False,
    )
    assert completed.returncode == 0, completed.stderr[-3000:]
    with Session(engine) as db:
        row = db.execute(sa.select(leases.lease_jobs).where(
            leases.lease_jobs.c.job_id == "subprocess-job")).mappings().one()
        assert row["state"] == "COMPLETED"
        assert row["attempts"] == 1
        assert row["output_sha256"] == hashlib.sha256(b"Name\nAda\n").hexdigest()
        assert leases.claim(db) is None
