"""Offline Operations Agent CSV job runner with explicit review gate.

Prototype only: no HTTP API, provider, customer upload or external send.
The caller controls tenant authorization and input/output storage. CSV content
is never stored in the job table; returned artifacts must be stored securely
before being shown to an owner for review.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from .operations_csv_cleanup import CleanupResult, clean_csv_text
from .operations_artifact_review import ensure_artifact_schema, complete_and_store_review_artifact
from .operations_job_queue import (
    JobConflict, claim_job, enqueue_job, fail_job, get_job_state,
)


@dataclass(frozen=True)
class PreparedCSVJob:
    job_id: int
    report: CleanupResult
    state: str


def prepare_csv_job(
    db: sqlite3.Connection, *, tenant_id: str, request_id: str, raw_csv: str,
    now: int, max_bytes: int = 1_000_000,
) -> PreparedCSVJob:
    """Process a bounded CSV fixture and leave the result awaiting owner review.

    Does not confirm delivery or payment. A separate storage/approval layer
    must retain the returned artifact before marking any real job delivered.
    """
    if not isinstance(raw_csv, str):
        raise JobConflict("CSV input must be text")
    fingerprint = hashlib.sha256(raw_csv.encode("utf-8")).hexdigest()
    job_id = enqueue_job(
        db, tenant_id=tenant_id, idempotency_key=request_id,
        kind="csv_cleanup", input_sha256=fingerprint,
    )
    state = get_job_state(db, tenant_id=tenant_id, job_id=job_id)
    if state not in ("queued", "running"):
        raise JobConflict("Job is not available for new execution")
    # Claim the exact idempotent request, never another queued tenant job.
    # Running jobs can be reclaimed only after their lease has expired.
    claim = claim_job(db, tenant_id=tenant_id, now=now, job_id=job_id)
    if claim is None:
        raise JobConflict("Job is not available for claim or lease recovery")
    try:
        report = clean_csv_text(raw_csv, max_bytes=max_bytes)
    except Exception:
        fail_job(db, job=claim, error_code="CSV_VALIDATION_FAILED", now=now)
        raise
    # The output must be retained for owner review before processing is marked done.
    # This is a prototype with local SQLite storage; never pass customer data here.
    ensure_artifact_schema(db)
    complete_and_store_review_artifact(
        db, job=claim, csv_text=report.cleaned_csv,
        output_sha256=report.output_sha256, now=now,
    )
    # Completed here means offline processing only, NOT reviewed or delivered.
    return PreparedCSVJob(job_id=job_id, report=report, state="awaiting_owner_review")
