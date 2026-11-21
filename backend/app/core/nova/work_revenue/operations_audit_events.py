"""Isolated SQLite audit contract for Operations CSV actions.

Prototype only. Does not attach to HTTP routes or production workflows.
SQLite triggers guard against normal UPDATE/DELETE statements, but this is
NOT tamper-proof logging against a database administrator. Production requires
restricted credentials, durable audit export, retention and monitoring.
Do not log spreadsheet contents, tokens, secrets, or raw storage paths.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass

from .operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope, artifact_storage_key,
    authorize_tenant_job,
)

_ACTIONS = frozenset({
    "upload_started", "upload_finished", "upload_failed",
    "artifact_linked", "artifact_approved", "artifact_downloaded",
    "recovery_reviewed",
})
_ARTIFACT_ACTIONS = frozenset({
    "artifact_linked", "artifact_approved", "artifact_downloaded",
})
_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations_csv_audit_events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,
 tenant_id TEXT NOT NULL,
 job_id TEXT NOT NULL,
 artifact_id TEXT,
 actor_id TEXT NOT NULL,
 action TEXT NOT NULL,
 occurred_at INTEGER NOT NULL
);
CREATE TRIGGER IF NOT EXISTS operations_csv_audit_no_update
BEFORE UPDATE ON operations_csv_audit_events
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS operations_csv_audit_no_delete
BEFORE DELETE ON operations_csv_audit_events
BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END;
"""


@dataclass(frozen=True)
class AuditEvent:
    event_id: int
    tenant_id: str
    job_id: str
    artifact_id: str | None
    actor_id: str
    action: str
    occurred_at: int


def initialize_audit_events(connection: sqlite3.Connection) -> None:
    with connection:
        connection.executescript(_SCHEMA)


def record_audit_event(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    job: TenantJobScope, actor_id: str, action: str,
    artifact_id: str | None = None, occurred_at: int | None = None,
) -> int:
    """Append a scoped event; callers must authenticate/authorize actor.

    Authenticated actor IDs must be supplied by trusted server context. This
    helper validates identifiers but is not an access-control substitute.
    """
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=job)
    if not isinstance(actor_id, str) or not actor_id or len(actor_id) > 128:
        raise TenantAccessDenied("Authenticated actor is required")
    if any(ord(c) < 32 or ord(c) == 127 for c in actor_id):
        raise TenantAccessDenied("Invalid authenticated actor")
    if action not in _ACTIONS:
        raise ValueError("Unsupported audit action")
    if action in _ARTIFACT_ACTIONS and artifact_id is None:
        raise ValueError("Artifact ID required for this action")
    if artifact_id is not None:
        artifact_storage_key(
            acting_tenant_id=acting_tenant_id,
            job=job, artifact_id=artifact_id,
        )
    timestamp = int(time.time()) if occurred_at is None else occurred_at
    if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0:
        raise ValueError("Invalid event time")
    with connection:
        cursor = connection.execute(
            """INSERT INTO operations_csv_audit_events
               (tenant_id, job_id, artifact_id, actor_id, action, occurred_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (job.tenant_id, job.job_id, artifact_id, actor_id, action, timestamp),
        )
    return int(cursor.lastrowid)


def list_job_audit_events(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    job: TenantJobScope,
) -> tuple[AuditEvent, ...]:
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=job)
    rows = connection.execute(
        """SELECT event_id, tenant_id, job_id, artifact_id,
                  actor_id, action, occurred_at
           FROM operations_csv_audit_events
           WHERE tenant_id = ? AND job_id = ?
           ORDER BY event_id""",
        (job.tenant_id, job.job_id),
    ).fetchall()
    return tuple(AuditEvent(*row) for row in rows)
