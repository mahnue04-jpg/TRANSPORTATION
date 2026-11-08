"""Offline, tenant-scoped handoff from an approved opportunity to a CSV job.

No identity authentication, external sending, customer data, or production API.
The caller MUST independently verify owner approval and derive tenant identity
from authenticated server context. Only synthetic SHA-256 fingerprints are stored.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .operations_job_queue import JobConflict, _valid_sha


@dataclass(frozen=True)
class AssignmentHandoff:
    tenant_id: str
    opportunity_id: str
    approval_reference: str
    job_id: int


def _identifier(value: str) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 256
        and bool(value.strip())
        and all(ord(ch) >= 32 and ord(ch) != 127 for ch in value)
    )


def ensure_handoff_schema(db: sqlite3.Connection) -> None:
    if db.in_transaction:
        raise JobConflict("Handoff schema requires a separate transaction")
    with db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS nova_operations_offline_handoffs (
                tenant_id TEXT NOT NULL,
                opportunity_id TEXT NOT NULL,
                approval_reference TEXT NOT NULL,
                job_id INTEGER NOT NULL,
                input_sha256 TEXT NOT NULL,
                PRIMARY KEY (tenant_id, opportunity_id),
                UNIQUE (tenant_id, job_id),
                FOREIGN KEY (job_id) REFERENCES nova_operations_offline_jobs(job_id)
            )"""
        )


def handoff_approved_opportunity(
    db: sqlite3.Connection, *, acting_tenant_id: str, record_tenant_id: str,
    opportunity_id: str, approval_reference: str, input_sha256: str,
) -> AssignmentHandoff:
    """Atomically create a stable assignment link and its queued CSV job.

    An approval reference is an opaque externally verified identifier, NOT proof
    of authorization. No user-provided tenant identity is trusted here.
    """
    if not _identifier(acting_tenant_id) or acting_tenant_id != record_tenant_id:
        raise JobConflict("Tenant mismatch or missing authenticated tenant")
    if not _identifier(opportunity_id) or not _identifier(approval_reference):
        raise JobConflict("Valid opportunity and owner approval references required")
    if not _valid_sha(input_sha256):
        raise JobConflict("Valid SHA-256 input fingerprint required")
    if db.in_transaction:
        raise JobConflict("Handoff requires a dedicated transaction")

    key = "opportunity:" + opportunity_id
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            """INSERT INTO nova_operations_offline_jobs
                (tenant_id, idempotency_key, kind, input_sha256, max_attempts)
               VALUES (?, ?, 'csv_cleanup', ?, 3)
               ON CONFLICT(tenant_id, idempotency_key) DO NOTHING""",
            (acting_tenant_id, key, input_sha256),
        )
        row = db.execute(
            """SELECT job_id, kind, input_sha256, max_attempts
               FROM nova_operations_offline_jobs
               WHERE tenant_id=? AND idempotency_key=?""",
            (acting_tenant_id, key),
        ).fetchone()
        if row is None or row[1:] != ("csv_cleanup", input_sha256, 3):
            raise JobConflict("Opportunity already refers to a different job")
        job_id = int(row[0])
        db.execute(
            """INSERT INTO nova_operations_offline_handoffs
                (tenant_id, opportunity_id, approval_reference, job_id, input_sha256)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, opportunity_id) DO NOTHING""",
            (acting_tenant_id, opportunity_id, approval_reference, job_id, input_sha256),
        )
        linked = db.execute(
            """SELECT approval_reference, job_id, input_sha256
               FROM nova_operations_offline_handoffs
               WHERE tenant_id=? AND opportunity_id=?""",
            (acting_tenant_id, opportunity_id),
        ).fetchone()
        if linked != (approval_reference, job_id, input_sha256):
            raise JobConflict("Opportunity handoff conflicts with existing approval")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return AssignmentHandoff(acting_tenant_id, opportunity_id, approval_reference, job_id)


def get_assignment_handoff(
    db: sqlite3.Connection, *, acting_tenant_id: str, opportunity_id: str,
) -> AssignmentHandoff | None:
    if not _identifier(acting_tenant_id) or not _identifier(opportunity_id):
        raise JobConflict("Valid tenant and opportunity identifiers required")
    row = db.execute(
        """SELECT approval_reference, job_id FROM nova_operations_offline_handoffs
           WHERE tenant_id=? AND opportunity_id=?""",
        (acting_tenant_id, opportunity_id),
    ).fetchone()
    return (
        AssignmentHandoff(acting_tenant_id, opportunity_id, row[0], int(row[1]))
        if row else None
    )
