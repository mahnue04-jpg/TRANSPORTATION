"""Offline SQLite artifact registry prototype for Operations CSV jobs.

Not connected to the HTTP API or production storage. Caller-supplied tenant
identity MUST come from authenticated server context, never a request body.
This is a prototype contract, not a replacement for production migrations,
transactional job ownership, private object storage, or audit logging.
"""
from __future__ import annotations

import sqlite3

from .operations_artifact_manifest import ArtifactManifest
from .operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope, artifact_storage_key,
    authorize_tenant_job,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations_csv_artifact_manifest (
 tenant_id TEXT NOT NULL,
 job_id TEXT NOT NULL,
 artifact_id TEXT NOT NULL,
 storage_key TEXT NOT NULL,
 byte_count INTEGER NOT NULL CHECK (byte_count > 0),
 sha256_hex TEXT NOT NULL,
 approved_for_download INTEGER NOT NULL DEFAULT 0
   CHECK (approved_for_download IN (0, 1)),
 PRIMARY KEY (tenant_id, job_id, artifact_id)
);
"""


def initialize_registry(connection: sqlite3.Connection) -> None:
    """Initialize isolated test schema. Not a production migration."""
    with connection:
        connection.execute(_SCHEMA)


def save_manifest(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    manifest: ArtifactManifest,
) -> None:
    if not isinstance(manifest, ArtifactManifest):
        raise TenantAccessDenied("Trusted artifact manifest is required")
    authorize_tenant_job(
        acting_tenant_id=acting_tenant_id, job=manifest.job
    )
    key = artifact_storage_key(
        acting_tenant_id=acting_tenant_id, job=manifest.job,
        artifact_id=manifest.artifact_id,
    )
    if manifest.storage_key != key or manifest.byte_count <= 0:
        raise TenantAccessDenied("Artifact metadata is invalid")
    if (
        not isinstance(manifest.sha256_hex, str)
        or len(manifest.sha256_hex) != 64
        or any(ch not in "0123456789abcdef" for ch in manifest.sha256_hex)
    ):
        raise TenantAccessDenied("Artifact digest is invalid")
    if manifest.approved_for_download:
        raise TenantAccessDenied("New artifacts require separate approval")
    with connection:
        connection.execute(
            """INSERT INTO operations_csv_artifact_manifest
               (tenant_id, job_id, artifact_id, storage_key,
                byte_count, sha256_hex, approved_for_download)
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (manifest.job.tenant_id, manifest.job.job_id, manifest.artifact_id,
             key, manifest.byte_count, manifest.sha256_hex),
        )


def load_manifest(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    job: TenantJobScope, artifact_id: str,
) -> ArtifactManifest:
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=job)
    key = artifact_storage_key(
        acting_tenant_id=acting_tenant_id, job=job, artifact_id=artifact_id
    )
    row = connection.execute(
        """SELECT storage_key, byte_count, sha256_hex, approved_for_download
           FROM operations_csv_artifact_manifest
           WHERE tenant_id = ? AND job_id = ? AND artifact_id = ?""",
        (job.tenant_id, job.job_id, artifact_id),
    ).fetchone()
    if row is None or row[0] != key:
        raise TenantAccessDenied("Artifact is not accessible")
    return ArtifactManifest(
        job=job, artifact_id=artifact_id, storage_key=row[0],
        byte_count=row[1], sha256_hex=row[2],
        approved_for_download=(row[3] == 1),
    )


def approve_download(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    job: TenantJobScope, artifact_id: str,
) -> None:
    """Owner-scoped approval record; approval authority remains caller's duty."""
    load_manifest(
        connection, acting_tenant_id=acting_tenant_id,
        job=job, artifact_id=artifact_id,
    )
    with connection:
        result = connection.execute(
            """UPDATE operations_csv_artifact_manifest
               SET approved_for_download = 1
               WHERE tenant_id = ? AND job_id = ? AND artifact_id = ?""",
            (job.tenant_id, job.job_id, artifact_id),
        )
        if result.rowcount != 1:
            raise TenantAccessDenied("Artifact approval failed")
