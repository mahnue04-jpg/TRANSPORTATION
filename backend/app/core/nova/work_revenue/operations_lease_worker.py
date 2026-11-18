"""Explicit single-job Operations lease executor, development-only.

NO scheduler, HTTP route, startup hook, external transport or customer processing.
The caller must provide an independently authorized deterministic handler and a
session factory. For now this is a synthetic acceptance helper; any real handler
must have idempotent private artifact writes, revocation checks and reconciliation.
"""
from __future__ import annotations

from collections.abc import Callable
from sqlalchemy.orm import Session

from . import operations_postgres_leases as leases


def run_one(
    session_factory: Callable[[], Session],
    handler: Callable[[leases.LeaseClaim], str],
    *,
    lease_seconds: int = 60,
    retry_delay_seconds: int = 30,
) -> dict:
    """Claim once, perform injected work, and fence completion on a fresh session.

    Business/job execution is never automatic. An external caller must guard
    runtime authorization, source input persistence and output verification.
    The handler returns only a SHA256 of already-persisted output. The lease
    does not itself prove that such an artifact exists.
    """
    with session_factory() as db:
        claimed = leases.claim(db, lease_seconds=lease_seconds)
    if claimed is None:
        return {"state": "idle", "job_id": None}
    try:
        output_sha256 = handler(claimed)
        with session_factory() as db:
            leases.complete(db, claimed=claimed, output_sha256=output_sha256)
        return {"state": "completed", "job_id": claimed.job_id}
    except Exception:
        # The handler may have written an artifact before failing. Retrying
        # without artifact reconciliation is NOT safe for real customer work.
        # This runner is synthetic-only until an idempotent handler is wired.
        with session_factory() as db:
            try:
                state = leases.fail_or_retry(
                    db, claimed=claimed, retry_delay_seconds=retry_delay_seconds
                )
            except leases.LeaseBlocked:
                # Lost lease/cancellation: never requeue a superseded claim.
                return {"state": "stale", "job_id": claimed.job_id}
        return {"state": state.lower(), "job_id": claimed.job_id}
