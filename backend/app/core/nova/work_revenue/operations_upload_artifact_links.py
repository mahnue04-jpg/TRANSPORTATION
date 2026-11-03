"""Isolated SQLite mapping between active upload leases and artifact IDs.

Offline contract only. This does not create storage objects, authorize API
requests, delete artifacts, or migrate production schema. Callers must derive
acting tenant from authenticated server context, never client data.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .operations_tenant_scope import (
    TenantAccessDenied, artifact_storage_key, authorize_tenant_job,
)
from .operations_upload_leases import UploadLease, _now

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations_csv_upload_artifact_links (
 tenant_id TEXT NOT NULL,
 job_id TEXT NOT NULL,
 artifact_id TEXT NOT NULL,
 lease_token TEXT NOT NULL,
 storage_key TEXT NOT NULL,
 PRIMARY KEY (tenant_id, job_id, artifact_id)
);
"""


@dataclass(frozen=True)
class ArtifactUploadLink:
    tenant_id: str
    job_id: str
    artifact_id: str
    lease_token: str
    storage_key: str


def initialize_upload_artifact_links(connection: sqlite3.Connection) -> None:
    with connection:
        connection.execute(_SCHEMA)


def link_artifact_to_active_upload(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    lease: UploadLease, artifact_id: str, now: int | None = None,
) -> ArtifactUploadLink:
    """Persist immutable linkage only for the current unexpired lease.

    The SELECT and INSERT run under BEGIN IMMEDIATE to prevent another SQLite
    writer from replacing the lease between ownership verification and insert.
    A production database will need equivalent transactional locking.
    """
    if not isinstance(lease, UploadLease):
        raise TenantAccessDenied("Active upload lease required")
    authorize_tenant_job(
        acting_tenant_id=acting_tenant_id, job=lease.job
    )
    key = artifact_storage_key(
        acting_tenant_id=acting_tenant_id,
        job=lease.job, artifact_id=artifact_id,
    )
    timestamp = _now(now)
    if connection.in_transaction:
        raise TenantAccessDenied("Caller transaction state is not supported")
    connection.execute("BEGIN IMMEDIATE")
    try:
        active = connection.execute(
            """SELECT 1 FROM operations_csv_upload_leases
               WHERE tenant_id = ? AND job_id = ? AND lease_token = ?
                 AND state = 'active' AND expires_at > ?""",
            (lease.job.tenant_id, lease.job.job_id, lease.token, timestamp),
        ).fetchone()
        if not active:
            raise TenantAccessDenied("Upload lease is not current")
        connection.execute(
            """INSERT INTO operations_csv_upload_artifact_links
               (tenant_id, job_id, artifact_id, lease_token, storage_key)
               VALUES (?, ?, ?, ?, ?)""",
            (lease.job.tenant_id, lease.job.job_id,
             artifact_id, lease.token, key),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return ArtifactUploadLink(
        tenant_id=lease.job.tenant_id, job_id=lease.job.job_id,
        artifact_id=artifact_id, lease_token=lease.token, storage_key=key,
    )


def list_job_artifact_links(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    lease: UploadLease,
) -> tuple[ArtifactUploadLink, ...]:
    """Read only records owned by the authenticated tenant and job."""
    if not isinstance(lease, UploadLease):
        raise TenantAccessDenied("Upload job required")
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=lease.job)
    rows = connection.execute(
        """SELECT tenant_id, job_id, artifact_id, lease_token, storage_key
           FROM operations_csv_upload_artifact_links
           WHERE tenant_id = ? AND job_id = ?
           ORDER BY artifact_id""",
        (lease.job.tenant_id, lease.job.job_id),
    ).fetchall()
    return tuple(ArtifactUploadLink(*row) for row in rows)


def linked_storage_keys(connection: sqlite3.Connection) -> frozenset[str]:
    """Internal recovery inventory only, not exposed to customer requests."""
    return frozenset(
        row[0] for row in connection.execute(
            "SELECT storage_key FROM operations_csv_upload_artifact_links"
        ).fetchall()
    )
