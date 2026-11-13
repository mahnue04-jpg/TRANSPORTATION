"""Offline durable job queue prototype for Nova Operations Agent.

Uses an explicit SQLite connection; no HTTP endpoints, external tool calls,
payments, provider access or background workers. Callers must enforce auth and
tenant ownership and keep sensitive input out of payload fingerprints.
"""
from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass


class JobConflict(ValueError):
    """Job conflict, invalid state or stale lease."""


@dataclass(frozen=True)
class ClaimedJob:
    job_id: int
    tenant_id: str
    kind: str
    input_sha256: str
    attempts: int
    lease_token: str


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute(
        """CREATE TABLE IF NOT EXISTS nova_operations_offline_jobs (
          job_id INTEGER PRIMARY KEY AUTOINCREMENT,
          tenant_id TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          kind TEXT NOT NULL,
          input_sha256 TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'queued'
            CHECK(state IN ('queued','running','completed','failed','cancelled')),
          attempts INTEGER NOT NULL DEFAULT 0,
          max_attempts INTEGER NOT NULL DEFAULT 3,
          available_at INTEGER NOT NULL DEFAULT 0,
          lease_until INTEGER,
          lease_token TEXT,
          output_sha256 TEXT,
          last_error_code TEXT,
          UNIQUE(tenant_id, idempotency_key)
        )"""
    )
    db.commit()


def _valid_sha(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def enqueue_job(
    db: sqlite3.Connection, *, tenant_id: str, idempotency_key: str,
    kind: str, input_sha256: str, max_attempts: int = 3,
) -> int:
    identities = (tenant_id, idempotency_key, kind)
    if any(
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 256
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in value)
        for value in identities
    ):
        raise JobConflict("Invalid job identity")
    if (
        not _valid_sha(input_sha256)
        or isinstance(max_attempts, bool)
        or not isinstance(max_attempts, int)
        or not 1 <= max_attempts <= 10
    ):
        raise JobConflict("Invalid fingerprint or retry limit")
    # Atomic upsert and consistency check: same key cannot silently replace input.
    with db:
        db.execute(
            """INSERT INTO nova_operations_offline_jobs
            (tenant_id, idempotency_key, kind, input_sha256, max_attempts)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, idempotency_key) DO NOTHING""",
            (tenant_id, idempotency_key, kind, input_sha256, max_attempts),
        )
        row = db.execute(
            """SELECT job_id, kind, input_sha256, max_attempts
               FROM nova_operations_offline_jobs
               WHERE tenant_id=? AND idempotency_key=?""",
            (tenant_id, idempotency_key),
        ).fetchone()
        if row is None or row[1:] != (kind, input_sha256, max_attempts):
            raise JobConflict("Idempotency key reused with different job")
        return int(row[0])


def claim_job(
    db: sqlite3.Connection, *, tenant_id: str, now: int, lease_seconds: int = 60,
    job_id: int | None = None,
) -> ClaimedJob | None:
    if (
        not isinstance(tenant_id, str)
        or not tenant_id.strip()
        or len(tenant_id) > 256
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in tenant_id)
        or isinstance(now, bool) or not isinstance(now, int) or now < 0
        or isinstance(lease_seconds, bool)
        or not isinstance(lease_seconds, int)
        or not 1 <= lease_seconds <= 3600
        or (job_id is not None and (
            isinstance(job_id, bool) or not isinstance(job_id, int) or job_id <= 0
        ))
    ):
        raise JobConflict("Invalid tenant, clock, job ID or lease duration")
    token = secrets.token_hex(24)
    # BEGIN IMMEDIATE serializes claims across independent SQLite connections.
    db.execute("BEGIN IMMEDIATE")
    try:
        # An exhausted job may crash on its final leased attempt. It must
        # become visibly FAILED once that lease expires, not remain RUNNING
        # indefinitely while being ineligible for any future claim.
        db.execute(
            """UPDATE nova_operations_offline_jobs
               SET state='failed', lease_until=NULL, lease_token=NULL,
                   last_error_code='MAX_ATTEMPTS_EXHAUSTED'
               WHERE tenant_id=? AND state='running'
                 AND attempts>=max_attempts AND lease_until<=?
                 AND (? IS NULL OR job_id=?)""",
            (tenant_id, now, job_id, job_id),
        )
        row = db.execute(
            """SELECT job_id, kind, input_sha256, attempts
               FROM nova_operations_offline_jobs
               WHERE tenant_id=? AND attempts < max_attempts
                 AND ((state='queued' AND available_at<=?)
                   OR (state='running' AND lease_until<=?))
                 AND (? IS NULL OR job_id=?)
               ORDER BY job_id LIMIT 1""",
            (tenant_id, now, now, job_id, job_id),
        ).fetchone()
        if row is None:
            db.commit()
            return None
        job_id, kind, fingerprint, attempts = row
        db.execute(
            """UPDATE nova_operations_offline_jobs
               SET state='running', attempts=attempts+1,
                   lease_until=?, lease_token=?, last_error_code=NULL
               WHERE job_id=? AND tenant_id=?""",
            (now + lease_seconds, token, job_id, tenant_id),
        )
        db.commit()
        return ClaimedJob(job_id, tenant_id, kind, fingerprint, attempts + 1, token)
    except Exception:
        db.rollback()
        raise


def complete_job(
    db: sqlite3.Connection, *, job: ClaimedJob, output_sha256: str, now: int,
) -> None:
    if not _valid_sha(output_sha256):
        raise JobConflict("Invalid output checksum")
    if isinstance(now, bool) or not isinstance(now, int) or now < 0:
        raise JobConflict("Invalid completion timestamp")
    with db:
        cur = db.execute(
            """UPDATE nova_operations_offline_jobs
               SET state='completed', output_sha256=?, lease_until=NULL, lease_token=NULL
               WHERE job_id=? AND tenant_id=? AND state='running'
                 AND lease_token=? AND lease_until>?""",
            (output_sha256, job.job_id, job.tenant_id, job.lease_token, now),
        )
        if cur.rowcount != 1:
            raise JobConflict("Stale or expired job lease")


def fail_job(
    db: sqlite3.Connection, *, job: ClaimedJob, error_code: str,
    now: int, retry_delay_seconds: int = 30,
) -> None:
    if (
        not isinstance(error_code, str)
        or not error_code.strip()
        or len(error_code) > 80
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in error_code)
        or isinstance(now, bool) or not isinstance(now, int) or now < 0
        or isinstance(retry_delay_seconds, bool)
        or not isinstance(retry_delay_seconds, int)
        or retry_delay_seconds < 0
        or retry_delay_seconds > 86400
    ):
        raise JobConflict("Invalid error code, clock or retry delay")
    with db:
        cur = db.execute(
            """UPDATE nova_operations_offline_jobs
               SET state=CASE WHEN attempts>=max_attempts THEN 'failed' ELSE 'queued' END,
                   available_at=?, last_error_code=?, lease_until=NULL, lease_token=NULL
               WHERE job_id=? AND tenant_id=? AND state='running'
                 AND lease_token=? AND lease_until>?""",
            (now + retry_delay_seconds, error_code, job.job_id, job.tenant_id, job.lease_token, now),
        )
        if cur.rowcount != 1:
            raise JobConflict("Stale or expired job lease")


def get_job_state(db: sqlite3.Connection, *, tenant_id: str, job_id: int) -> str | None:
    row = db.execute(
        "SELECT state FROM nova_operations_offline_jobs WHERE tenant_id=? AND job_id=?",
        (tenant_id, job_id),
    ).fetchone()
    return row[0] if row else None
