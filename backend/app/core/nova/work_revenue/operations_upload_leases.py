"""Durable SQLite upload lease contract for isolated Operations CSV tests.

Offline only: no HTTP route, job processor, storage deletion or production
migration. The server must derive acting tenant from an authenticated session.
A production worker needs transactional authorization, clock policy, crash
recovery, and a durable job-state machine in the main database.
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from uuid import uuid4

from .operations_tenant_scope import (
    TenantAccessDenied, TenantJobScope, authorize_tenant_job,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations_csv_upload_leases (
 tenant_id TEXT NOT NULL,
 job_id TEXT NOT NULL,
 lease_token TEXT NOT NULL,
 expires_at INTEGER NOT NULL,
 state TEXT NOT NULL CHECK (state IN ('active', 'finished', 'failed')),
 PRIMARY KEY (tenant_id, job_id)
);
"""


@dataclass(frozen=True)
class UploadLease:
    job: TenantJobScope
    token: str
    expires_at: int
    state: str


def initialize_upload_leases(connection: sqlite3.Connection) -> None:
    with connection:
        connection.execute(_SCHEMA)


def _now(value: int | None) -> int:
    now = int(time.time()) if value is None else value
    if isinstance(now, bool) or not isinstance(now, int) or now < 0:
        raise ValueError("Invalid lease clock")
    return now


def _ttl(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 3600:
        raise ValueError("Invalid lease duration")
    return value


def acquire_upload_lease(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    job: TenantJobScope, now: int | None = None, ttl_seconds: int = 300,
) -> UploadLease:
    """Reserve a job only if no active, unexpired lease exists."""
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=job)
    now_value = _now(now)
    expires = now_value + _ttl(ttl_seconds)
    token = str(uuid4())
    with connection:
        result = connection.execute(
            """INSERT INTO operations_csv_upload_leases
               (tenant_id, job_id, lease_token, expires_at, state)
               VALUES (?, ?, ?, ?, 'active')
               ON CONFLICT (tenant_id, job_id) DO UPDATE SET
                 lease_token = excluded.lease_token,
                 expires_at = excluded.expires_at,
                 state = 'active'
               WHERE operations_csv_upload_leases.state != 'active'
                  OR operations_csv_upload_leases.expires_at <= ?""",
            (job.tenant_id, job.job_id, token, expires, now_value),
        )
        if result.rowcount != 1:
            raise TenantAccessDenied("Upload lease is already held")
    return UploadLease(job=job, token=token, expires_at=expires, state="active")


def renew_upload_lease(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    lease: UploadLease, now: int | None = None, ttl_seconds: int = 300,
) -> UploadLease:
    if not isinstance(lease, UploadLease):
        raise TenantAccessDenied("Upload lease is required")
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=lease.job)
    now_value = _now(now)
    expires = now_value + _ttl(ttl_seconds)
    with connection:
        result = connection.execute(
            """UPDATE operations_csv_upload_leases SET expires_at = ?
               WHERE tenant_id = ? AND job_id = ? AND lease_token = ?
                 AND state = 'active' AND expires_at > ?""",
            (expires, lease.job.tenant_id, lease.job.job_id,
             lease.token, now_value),
        )
        if result.rowcount != 1:
            raise TenantAccessDenied("Upload lease cannot be renewed")
    return UploadLease(
        job=lease.job, token=lease.token, expires_at=expires, state="active"
    )


def finish_upload_lease(
    connection: sqlite3.Connection, *, acting_tenant_id: str,
    lease: UploadLease, success: bool, now: int | None = None,
) -> None:
    if not isinstance(lease, UploadLease) or not isinstance(success, bool):
        raise TenantAccessDenied("Valid upload completion required")
    authorize_tenant_job(acting_tenant_id=acting_tenant_id, job=lease.job)
    now_value = _now(now)
    with connection:
        result = connection.execute(
            """UPDATE operations_csv_upload_leases SET state = ?
               WHERE tenant_id = ? AND job_id = ? AND lease_token = ?
                 AND state = 'active' AND expires_at > ?""",
            ("finished" if success else "failed",
             lease.job.tenant_id, lease.job.job_id, lease.token, now_value),
        )
        if result.rowcount != 1:
            raise TenantAccessDenied("Upload completion rejected")


def active_lease_expirations(
    connection: sqlite3.Connection, *, at: int | None = None,
) -> dict[tuple[str, str], int]:
    """Server-only inventory; no destructive actions or client response."""
    now_value = _now(at)
    rows = connection.execute(
        """SELECT tenant_id, job_id, expires_at
           FROM operations_csv_upload_leases
           WHERE state = 'active' AND expires_at > ?""", (now_value,),
    ).fetchall()
    return {(tenant, job): expires for tenant, job, expires in rows}
