"""Full runner recovery after injected artifact write failure."""
import sqlite3

import pytest

from app.core.nova.work_revenue.operations_csv_runner import prepare_csv_job
from app.core.nova.work_revenue.operations_job_queue import get_job_state, ensure_schema
from app.core.nova.work_revenue.operations_artifact_review import read_review_artifact, ensure_artifact_schema


def test_runner_recovers_after_atomic_artifact_failure_and_restart(tmp_path):
    path = tmp_path / "failure.sqlite"
    db = sqlite3.connect(path)
    ensure_schema(db)
    ensure_artifact_schema(db)
    db.execute(
        """CREATE TRIGGER fail_artifact BEFORE INSERT ON nova_operations_offline_artifacts
           BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END"""
    )
    db.commit()
    raw = "Name\nAna\n"
    with pytest.raises(sqlite3.IntegrityError, match="injected storage failure"):
        prepare_csv_job(db, tenant_id="tenant-a", request_id="request-1", raw_csv=raw, now=100)
    job_id = db.execute(
        "SELECT job_id FROM nova_operations_offline_jobs WHERE tenant_id='tenant-a'"
    ).fetchone()[0]
    assert get_job_state(db, tenant_id="tenant-a", job_id=job_id) == "running"
    assert read_review_artifact(db, tenant_id="tenant-a", job_id=job_id) is None
    db.execute("DROP TRIGGER fail_artifact")
    db.commit()
    db.close()

    restarted = sqlite3.connect(path)
    result = prepare_csv_job(
        restarted, tenant_id="tenant-a", request_id="request-1", raw_csv=raw, now=161,
    )
    assert result.job_id == job_id
    assert get_job_state(restarted, tenant_id="tenant-a", job_id=job_id) == "completed"
    assert read_review_artifact(restarted, tenant_id="tenant-a", job_id=job_id) == (
        "awaiting_review", "Name\nAna\n",
    )
    restarted.close()
