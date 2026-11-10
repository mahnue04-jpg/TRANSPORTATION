"""Dedicated Creative Studio master-export worker.

Run from backend directory:
  python -m app.core.nova.creative_studio.master_worker

Opt-in service. Requires an already initialized shared SQL database and private
S3-compatible storage. No paid providers, web sessions, or publishing access.

This first worker processes saved QUEUED 10–30 minute master jobs. It does not
auto-retry uncertain RUNNING jobs after a crash; they need output reconciliation
and explicit owner review to prevent duplicate exports.
"""
from __future__ import annotations

import logging
import os
import signal
import time

from app.core.nova.creative_studio.db_models import NovaCreativeRenderClaim
from app.core.nova.creative_studio.calendar import _run_chapter_master_job
from app.db.session import SessionLocal

_logger = logging.getLogger(__name__)
_stop = False


def _request_stop(_signum, _frame):
    global _stop
    _stop = True


def run_one_queued() -> bool:
    """Read a small batch; SQL compare-and-swap in runner is authoritative."""
    with SessionLocal() as db:
        claims = (
            db.query(NovaCreativeRenderClaim)
            .filter(NovaCreativeRenderClaim.state == "QUEUED")
            .order_by(NovaCreativeRenderClaim.updated_at.asc())
            .limit(10)
            .all()
        )
        candidates = [
            (c.owner_id, c.project_id, c.entry_id, c.job_id)
            for c in claims
        ]
    if not candidates:
        return False
    # The runner atomically compares state=QUEUED before processing.
    # A competing web worker or another queue worker may claim first.
    processed_without_error = False
    for owner_id, project_id, entry_id, job_id in candidates:
        if _stop:
            return False
        try:
            _run_chapter_master_job(owner_id, project_id, entry_id, job_id)
            processed_without_error = True
        except Exception:
            # Preserve fail-closed claim state for operator reconciliation.
            # One corrupt job must not starve other independent projects.
            _logger.exception("Creative Studio master job failed unexpectedly during worker poll.")
    # If all candidates unexpectedly failed before being claimable, back off
    # rather than hammering the shared SQL database in a tight loop.
    return processed_without_error


def main() -> None:
    if os.getenv("NOVA_STUDIO_MASTER_WORKER_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit("Set NOVA_STUDIO_MASTER_WORKER_ENABLED=true to start the opt-in worker.")
    if os.getenv("NOVA_STUDIO_PRIVATE_OBJECT_STORAGE", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit("Private durable object storage must be enabled for master worker.")
    poll = max(2, min(60, int(os.getenv("NOVA_STUDIO_MASTER_WORKER_POLL_SECONDS", "5"))))
    logging.basicConfig(level=logging.INFO)
    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)
    _logger.info("Creative Studio private master worker started.")
    while not _stop:
        try:
            had_jobs = run_one_queued()
        except Exception:
            # No SQL credentials, personal files, or provider URLs in the logs.
            _logger.exception("Creative Studio master worker could not complete poll.")
            had_jobs = False
        if not had_jobs:
            for _ in range(poll):
                if _stop:
                    break
                time.sleep(1)
    _logger.info("Creative Studio master worker stopped.")


if __name__ == "__main__":
    main()
