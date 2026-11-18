"""Read-only orphan-candidate inventory for one scoped Operations CSV job.

This function does NOT contact S3, list arbitrary buckets, delete objects,
log customer data, retry a job or authorize any customer delivery. A future
isolated-staging integration must inject a private, authenticated, bounded
listing that enforces the exact organization/job prefix on the provider side.
It cannot prove whether an object is safe to delete or whether another process
is currently writing it.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import operations_customer_csv_jobs as csvjobs
from . import operations_postgres_leases as leases


class OrphanAuditBlocked(ValueError):
    pass


def inspect_job_private_objects(
    db: Session, *, organization_id: str, owner_user_id: str,
    job_id: str, list_private_keys: Callable[[str], Iterable[str]],
    max_objects: int = 1000,
) -> dict:
    """Classify private object references without returning the private keys."""
    csvjobs.require_runtime(db)
    leases._guard(db)
    if not all(isinstance(value, str) and value.isascii()
               and 0 < len(value) <= 36
               and all(ch.isalnum() or ch in "-_" for ch in value)
               for value in (organization_id, owner_user_id, job_id)):
        raise OrphanAuditBlocked("Exact private job identity required")
    if type(max_objects) is not int or not 1 <= max_objects <= 1000:
        raise OrphanAuditBlocked("Invalid audit limit")
    if not callable(list_private_keys):
        raise OrphanAuditBlocked("Authorized private listing required")

    job = db.execute(sa.select(
        csvjobs.jobs.c.status, csvjobs.jobs.c.output_ref,
    ).where(
        csvjobs.jobs.c.id == job_id,
        csvjobs.jobs.c.organization_id == organization_id,
        csvjobs.jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    lease = db.execute(sa.select(
        leases.lease_jobs.c.state, leases.lease_jobs.c.input_ref,
    ).where(
        leases.lease_jobs.c.job_id == job_id,
        leases.lease_jobs.c.organization_id == organization_id,
        leases.lease_jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    if job is None or lease is None:
        raise OrphanAuditBlocked("Job not found in exact owner scope")

    prefix = f"{organization_id}/{job_id}/"
    known = {value for value in (job["output_ref"], lease["input_ref"])
             if isinstance(value, str) and value}
    if any(not value.startswith(prefix) for value in known):
        raise OrphanAuditBlocked("Bound object reference outside job scope")

    try:
        supplied = list_private_keys(prefix)
        keys = []
        for key in supplied:
            if len(keys) >= max_objects:
                raise OrphanAuditBlocked("Object listing exceeds audit limit")
            if not isinstance(key, str) or not key.startswith(prefix):
                raise OrphanAuditBlocked("Private listing escaped job prefix")
            if key in keys:
                raise OrphanAuditBlocked("Duplicate object in private listing")
            keys.append(key)
    except OrphanAuditBlocked:
        raise
    except Exception as exc:
        raise OrphanAuditBlocked("Private inventory unavailable") from exc

    observed = set(keys)
    bound = known & observed
    candidates = observed - known
    missing_bound = known - observed
    return {
        "job_id": job_id,
        "lease_status": lease["state"],
        "job_status": job["status"],
        "objects_seen": len(keys),
        "bound_objects_present": len(bound),
        "orphan_candidates": len(candidates),
        "bound_objects_missing": len(missing_bound),
        "requires_manual_reconciliation": bool(candidates or missing_bound),
        "safe_to_delete": False,
        "delete_performed": False,
        "may_release": False,
        "delivered": False,
    }


def inspect_job_s3_objects(
    db: Session, *, organization_id: str, owner_user_id: str, job_id: str,
    s3_client, private_bucket: str, max_objects: int = 1000,
) -> dict:
    """Use a supplied read-only, isolated S3 client for exact-job audit.

    Authorization MUST have been independently checked by the caller. This
    function checks exact scope in PostgreSQL before invoking S3. It does not
    add an HTTP route, instantiate production credentials, or mutate storage.
    """
    from .operations_orphan_s3_listing import list_scoped_s3_keys

    return inspect_job_private_objects(
        db, organization_id=organization_id, owner_user_id=owner_user_id,
        job_id=job_id, max_objects=max_objects,
        list_private_keys=lambda prefix: list_scoped_s3_keys(
            s3_client, bucket=private_bucket, prefix=prefix,
            max_objects=max_objects),
    )
