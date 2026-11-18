"""Read-only owner-scoped recovery diagnosis for queued Operations CSV jobs.

Never mutates job state, retries a worker, lists a private bucket, or delivers a
file. This is a development-only control-plane component. It deliberately does
not return private object references, hashes, or customer CSV contents.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import operations_customer_csv_jobs as csvjobs
from . import operations_postgres_leases as leases


def inspect_recovery(
    db: Session, *, organization_id: str, owner_user_id: str,
    job_id: str, now: datetime | None = None,
) -> dict:
    leases._guard(db)
    csvjobs.require_runtime(db)
    if not all(isinstance(v, str) and v.strip() and len(v) <= 36
               for v in (organization_id, owner_user_id, job_id)):
        raise leases.LeaseBlocked("Exact owner and job scope required")
    now = now or datetime.now(timezone.utc)
    job = db.execute(sa.select(
        csvjobs.jobs.c.status, csvjobs.jobs.c.input_sha256,
        csvjobs.jobs.c.output_sha256, csvjobs.jobs.c.output_ref,
    ).where(
        csvjobs.jobs.c.id == job_id,
        csvjobs.jobs.c.organization_id == organization_id,
        csvjobs.jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    lease = db.execute(sa.select(leases.lease_jobs).where(
        leases.lease_jobs.c.job_id == job_id,
        leases.lease_jobs.c.organization_id == organization_id,
        leases.lease_jobs.c.owner_user_id == owner_user_id,
    )).mappings().first()
    if not job or not lease:
        raise leases.LeaseBlocked("Queued job not found in authorized scope")

    status = job["status"]
    state = lease["state"]
    bound = bool(lease["input_ref"]) and bool(lease["input_size"])
    output_ready = (bool(job["output_ref"])
                    and leases._sha(job["output_sha256"]))
    same_input = leases._sha(job["input_sha256"]) and (
        job["input_sha256"] == lease["input_sha256"])
    same_output = output_ready and leases._sha(lease["output_sha256"]) and (
        job["output_sha256"] == lease["output_sha256"])
    finalized = status in ("AWAITING_REVIEW", "APPROVED_FOR_DOWNLOAD")

    # A cancel that lands after the review copy is committed is not a clean
    # cancel. Owners need the finalized-output classification so the private
    # artifact is not reported as if no review copy exists.
    if state == "CANCELLED" and not finalized:
        result = "cancelled"
    elif state == "NEEDS_RECONCILIATION":
        result = "owner_reconciliation_required"
    elif state == "FAILED":
        result = "failed_owner_review_required"
    elif not same_input:
        result = "metadata_mismatch"
    elif state == "COMPLETED":
        result = ("completed_for_owner_review"
                  if same_output and finalized
                  else "completed_metadata_mismatch")
    elif finalized:
        result = "output_finalized_without_completed_lease"
    elif state == "QUEUED":
        result = ("queued_ready_for_supervised_processing" if bound
                  else "input_binding_incomplete")
    elif state == "RUNNING":
        expiry = lease["lease_until"]
        if expiry is None:
            result = "invalid_processing_lease"
        else:
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            result = ("expired_processing_lease"
                      if expiry <= now else "processing_in_progress")
    else:
        result = "unknown_state"

    return {
        "job_id": job_id,
        "job_status": status,
        "lease_status": state,
        "recovery_result": result,
        "attempts": lease["attempts"],
        "input_bound": bound,
        "owner_action_required": result not in (
            "queued_ready_for_supervised_processing",
            "processing_in_progress", "completed_for_owner_review",
        ),
        "safe_to_auto_retry": False,
        "may_release": False,
        "delivered": False,
    }
