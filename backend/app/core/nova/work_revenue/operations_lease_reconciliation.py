"""Read-only reconciliation inspection for held Operations lease jobs.

Development-only: the current lease schema contains an expected SHA256 but NO
durable private output reference. The injected reader is a synthetic fixture
until authenticated private object lookup is wired and audited. No approvals,
state transitions, automatic retries, downloads, or customer delivery.
"""
from __future__ import annotations

import hashlib
import hmac
from collections.abc import Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import operations_postgres_leases as leases


def inspect_held_job(
    db: Session, *,
    job_id: str,
    organization_id: str,
    owner_user_id: str,
    artifact_reader: Callable[[str, str, str], bytes | None],
    max_bytes: int = 1024 * 1024,
) -> dict:
    """Inspect exact owner scope; never expose private content or mutate state.

    The artifact reader must be an authorized, private, bounded lookup that
    independently verifies immutable artifact provenance; a matching digest
    alone is NOT authorization to approve, retry, or deliver any output.
    """
    leases._guard(db)
    if type(max_bytes) is not int or not 1 <= max_bytes <= 1024 * 1024:
        raise leases.LeaseBlocked("Invalid read limit")
    if not all(isinstance(v, str) and v.strip() and len(v) <= 36
               for v in (job_id, organization_id, owner_user_id)):
        raise leases.LeaseBlocked("Invalid job scope")
    row = db.execute(sa.select(
        leases.lease_jobs.c.state,
        leases.lease_jobs.c.output_sha256,
    ).where(
        leases.lease_jobs.c.job_id == job_id,
        leases.lease_jobs.c.organization_id == organization_id,
        leases.lease_jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    if row is None:
        raise leases.LeaseBlocked("Job not found in authorized scope")
    if row["state"] != "NEEDS_RECONCILIATION":
        raise leases.LeaseBlocked("Job is not on reconciliation hold")
    expected = row["output_sha256"]
    if not leases._sha(expected):
        return {"job_id": job_id, "result": "missing_expected_digest",
                "may_release": False}
    try:
        contents = artifact_reader(organization_id, owner_user_id, job_id)
    except Exception:
        return {"job_id": job_id, "result": "artifact_unavailable",
                "may_release": False}
    if contents is None:
        return {"job_id": job_id, "result": "artifact_missing",
                "may_release": False}
    if not isinstance(contents, bytes) or len(contents) > max_bytes:
        return {"job_id": job_id, "result": "artifact_invalid",
                "may_release": False}
    actual = hashlib.sha256(contents).hexdigest()
    result = "digest_matches" if hmac.compare_digest(actual, expected) else "digest_mismatch"
    return {"job_id": job_id, "result": result, "may_release": False}
