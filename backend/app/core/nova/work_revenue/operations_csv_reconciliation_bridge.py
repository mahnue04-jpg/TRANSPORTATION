"""Read-only linkage from a held lease to an existing private CSV artifact.

This does not introduce a worker, migrate data, approve a job, or release files.
The customer CSV row must already contain a durable private object reference.
All lookups are owner-scoped and both runtime flags must be explicitly enabled.
"""
from __future__ import annotations

import hmac

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import operations_customer_csv_jobs as csvjobs
from . import operations_postgres_leases as leases
from .operations_lease_reconciliation import inspect_held_job


def inspect_held_csv_artifact(
    db: Session, *, job_id: str, organization_id: str, owner_user_id: str,
) -> dict:
    """Inspect existing owner-scoped CSV output; never change state.

    This is a development-only diagnostic. The lease and CSV job use the same
    job ID by explicit caller convention, not by an enforced foreign key.
    A checksum match is evidence only, never approval or delivery authorization.
    """
    leases._guard(db)
    csvjobs.require_runtime(db)
    # Read the CSV record first, only under the exact same organization/owner.
    # Do not expose the private object reference in the returned diagnostic.
    row = db.execute(sa.select(
        csvjobs.jobs.c.status,
        csvjobs.jobs.c.input_sha256,
        csvjobs.jobs.c.output_sha256,
        csvjobs.jobs.c.output_ref,
    ).where(
        csvjobs.jobs.c.id == job_id,
        csvjobs.jobs.c.organization_id == organization_id,
        csvjobs.jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    if row is None:
        raise leases.LeaseBlocked("Linked customer CSV job not found in authorized scope")
    if row["status"] not in ("AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD"):
        raise leases.LeaseBlocked("Linked CSV output has not been finalized")
    if not leases._sha(row["output_sha256"]) or not row["output_ref"]:
        return {"job_id": job_id, "result": "missing_csv_artifact",
                "may_release": False}
    # Validate lease scope, state and exact job input and expected output first.
    held = db.execute(sa.select(
        leases.lease_jobs.c.state,
        leases.lease_jobs.c.input_sha256,
        leases.lease_jobs.c.output_sha256,
    ).where(
        leases.lease_jobs.c.job_id == job_id,
        leases.lease_jobs.c.organization_id == organization_id,
        leases.lease_jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    if held is None or held["state"] != "NEEDS_RECONCILIATION":
        raise leases.LeaseBlocked("Linked lease is not held for owner reconciliation")
    if (not leases._sha(held["input_sha256"])
            or not leases._sha(held["output_sha256"])
            or not hmac.compare_digest(held["input_sha256"], row["input_sha256"])
            or not hmac.compare_digest(held["output_sha256"], row["output_sha256"])):
        return {"job_id": job_id, "result": "metadata_digest_mismatch",
                "may_release": False}
    storage_ref = row["output_ref"]

    def read_private(org: str, owner: str, requested_job: str) -> bytes:
        if (org, owner, requested_job) != (organization_id, owner_user_id, job_id):
            raise leases.LeaseBlocked("Private read scope mismatch")
        content, _content_type = csvjobs._store().retrieve(storage_ref=storage_ref)
        return content

    # Rechecks lease scope/state; no state mutation or remote delivery.
    return inspect_held_job(
        db, job_id=job_id, organization_id=organization_id,
        owner_user_id=owner_user_id, artifact_reader=read_private,
        max_bytes=1_000_000,
    )
