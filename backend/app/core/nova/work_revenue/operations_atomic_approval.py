"""Offline atomic artifact approval and audit transaction.

Uses a single isolated SQLite connection for metadata and audit. This code
does not authorize reviewers; production callers must authenticate reviewers,
validate their role, enforce job ownership and use production migrations.
No storage bytes or customer API are handled here.
"""
from __future__ import annotations

import sqlite3
import time

from .operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope, artifact_storage_key,
    authorize_tenant_job,
)


def approve_artifact_with_audit(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    job: TenantJobScope, artifact_id: str,
    authenticated_actor_id: str, occurred_at: int | None = None,
) -> int:
    """Commit an approval and audit event together or roll both back.

    A separate authorization layer must prove reviewer privilege. The actor
    identifier comes from trusted server context, not user-supplied input.
    """
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=job)
    key = artifact_storage_key(
        acting_tenant_id=acting_tenant_id, job=job, artifact_id=artifact_id
    )
    actor = authenticated_actor_id
    if (
        not isinstance(actor, str) or not actor or len(actor) > 128
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in actor)
    ):
        raise TenantAccessDenied("Valid authenticated actor required")
    stamp = int(time.time()) if occurred_at is None else occurred_at
    if isinstance(stamp, bool) or not isinstance(stamp, int) or stamp < 0:
        raise ValueError("Invalid audit timestamp")
    if connection.in_transaction:
        raise TenantAccessDenied("Requires dedicated transaction")
    connection.execute("BEGIN IMMEDIATE")
    try:
        result = connection.execute(
            """UPDATE operations_csv_artifact_manifest
               SET approved_for_download = 1
               WHERE tenant_id = ? AND job_id = ? AND artifact_id = ?
                 AND storage_key = ? AND approved_for_download = 0""",
            (job.tenant_id, job.job_id, artifact_id, key),
        )
        if result.rowcount != 1:
            raise TenantAccessDenied("Artifact absent or already approved")
        event = connection.execute(
            """INSERT INTO operations_csv_audit_events
               (tenant_id, job_id, artifact_id, actor_id, action, occurred_at)
               VALUES (?, ?, ?, ?, 'artifact_approved', ?)""",
            (job.tenant_id, job.job_id, artifact_id, actor, stamp),
        )
        event_id = int(event.lastrowid)
        connection.commit()
        return event_id
    except BaseException:
        connection.rollback()
        raise
