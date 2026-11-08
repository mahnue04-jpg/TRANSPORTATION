"""Offline owner-review artifact registry for Operations Agent CSV outputs.

The caller must authenticate the owner and provide authorized tenant_id.
Stores only a bounded CSV artifact in SQLite for fixture-scale validation.
Production should replace this with encrypted object storage, malware checks,
retention/erasure controls and audit logging before accepting customer data.
"""
from __future__ import annotations

import hashlib
import sqlite3

from .operations_job_queue import JobConflict


def ensure_artifact_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS nova_operations_offline_artifacts (
           tenant_id TEXT NOT NULL,
           job_id INTEGER NOT NULL,
           output_sha256 TEXT NOT NULL,
           csv_text TEXT NOT NULL,
           review_state TEXT NOT NULL DEFAULT 'awaiting_review'
             CHECK(review_state IN ('awaiting_review','approved','rejected')),
           reviewer_id TEXT,
           PRIMARY KEY(tenant_id, job_id),
           FOREIGN KEY(job_id) REFERENCES nova_operations_offline_jobs(job_id)
        )"""
    )
    db.commit()


def save_review_artifact(
    db: sqlite3.Connection, *, tenant_id: str, job_id: int,
    csv_text: str, output_sha256: str,
) -> None:
    if not tenant_id or not isinstance(csv_text, str) or len(csv_text.encode("utf-8")) > 1_000_000:
        raise JobConflict("Invalid artifact or size")
    if hashlib.sha256(csv_text.encode("utf-8")).hexdigest() != output_sha256:
        raise JobConflict("Artifact checksum mismatch")
    with db:
        row = db.execute(
            """SELECT output_sha256 FROM nova_operations_offline_jobs
               WHERE tenant_id=? AND job_id=? AND state='completed'""",
            (tenant_id, job_id),
        ).fetchone()
        if row is None or row[0] != output_sha256:
            raise JobConflict("Completed tenant job and checksum required")
        db.execute(
            """INSERT INTO nova_operations_offline_artifacts
               (tenant_id,job_id,output_sha256,csv_text)
               VALUES (?,?,?,?)
               ON CONFLICT(tenant_id,job_id) DO NOTHING""",
            (tenant_id, job_id, output_sha256, csv_text),
        )
        existing = db.execute(
            """SELECT output_sha256,csv_text FROM nova_operations_offline_artifacts
               WHERE tenant_id=? AND job_id=?""", (tenant_id, job_id),
        ).fetchone()
        if existing != (output_sha256, csv_text):
            raise JobConflict("Artifact already exists with different content")


def review_artifact(
    db: sqlite3.Connection, *, tenant_id: str, job_id: int,
    reviewer_id: str, approve: bool,
) -> str:
    if (
        not isinstance(tenant_id, str) or not tenant_id.strip()
        or not isinstance(reviewer_id, str) or not reviewer_id.strip()
        or len(reviewer_id) > 128
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in reviewer_id)
        or type(approve) is not bool
    ):
        raise JobConflict("Valid owner review identity and boolean decision required")
    state = "approved" if approve else "rejected"
    with db:
        cur = db.execute(
            """UPDATE nova_operations_offline_artifacts
               SET review_state=?, reviewer_id=?
               WHERE tenant_id=? AND job_id=? AND review_state='awaiting_review'""",
            (state, reviewer_id, tenant_id, job_id),
        )
        if cur.rowcount != 1:
            raise JobConflict("Artifact unavailable or already reviewed")
    return state


def read_review_artifact(
    db: sqlite3.Connection, *, tenant_id: str, job_id: int,
) -> tuple[str, str] | None:
    row = db.execute(
        """SELECT review_state,csv_text FROM nova_operations_offline_artifacts
           WHERE tenant_id=? AND job_id=?""", (tenant_id, job_id),
    ).fetchone()
    return (row[0], row[1]) if row else None


def complete_and_store_review_artifact(
    db: sqlite3.Connection, *, job, csv_text: str,
    output_sha256: str, now: int,
) -> None:
    """Atomically complete the leased job and retain its review artifact.

    A failed insert rolls back completion. The leased job remains running
    until lease expiry, when the queue can safely reclaim it.
    """
    from .operations_job_queue import _valid_sha

    if isinstance(now, bool) or not isinstance(now, int) or now < 0:
        raise JobConflict("Invalid artifact completion timestamp")
    if not isinstance(csv_text, str):
        raise JobConflict("Invalid CSV artifact")
    encoded = csv_text.encode("utf-8")
    if len(encoded) > 1_000_000 or not _valid_sha(output_sha256):
        raise JobConflict("Invalid artifact size or checksum")
    if hashlib.sha256(encoded).hexdigest() != output_sha256:
        raise JobConflict("Artifact checksum mismatch")
    if db.in_transaction:
        raise JobConflict("Caller must not hold an active transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        cur = db.execute(
            """UPDATE nova_operations_offline_jobs
               SET state='completed', output_sha256=?,
                   lease_until=NULL, lease_token=NULL
               WHERE job_id=? AND tenant_id=? AND state='running'
                 AND lease_token=? AND lease_until>?""",
            (output_sha256, job.job_id, job.tenant_id, job.lease_token, now),
        )
        if cur.rowcount != 1:
            raise JobConflict("Stale or expired job lease")
        db.execute(
            """INSERT INTO nova_operations_offline_artifacts
               (tenant_id,job_id,output_sha256,csv_text)
               VALUES (?,?,?,?)""",
            (job.tenant_id, job.job_id, output_sha256, csv_text),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
