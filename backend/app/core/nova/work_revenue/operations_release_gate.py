"""Read-only offline release eligibility guard for synthetic CSV assignments.

This guard does not authenticate users, transmit artifacts or confer permission
to release customer data. Production must use trusted session-derived tenant
and reviewer authorization, secure storage and an independent delivery gate.
"""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from .operations_assignment_handoff import get_assignment_handoff
from .operations_job_queue import JobConflict, _valid_sha


@dataclass(frozen=True)
class ReleaseEligibility:
    tenant_id: str
    opportunity_id: str
    job_id: int
    output_sha256: str
    reviewer_id: str


def check_offline_release_eligibility(
    db: sqlite3.Connection, *, acting_tenant_id: str, opportunity_id: str,
) -> ReleaseEligibility:
    """Verify durable links, completed job and reviewed artifact, without bytes."""
    handoff = get_assignment_handoff(
        db, acting_tenant_id=acting_tenant_id, opportunity_id=opportunity_id,
    )
    if handoff is None:
        raise JobConflict("Assignment not found for tenant")
    row = db.execute(
        """SELECT j.state, j.output_sha256,
                  a.output_sha256, a.csv_text, a.review_state, a.reviewer_id
           FROM nova_operations_offline_jobs AS j
           LEFT JOIN nova_operations_offline_artifacts AS a
             ON a.tenant_id=j.tenant_id AND a.job_id=j.job_id
           WHERE j.tenant_id=? AND j.job_id=?""",
        (acting_tenant_id, handoff.job_id),
    ).fetchone()
    if row is None:
        raise JobConflict("Assignment job missing")
    state, job_hash, artifact_hash, csv_text, review_state, reviewer_id = row
    if state != "completed" or review_state != "approved":
        raise JobConflict("Completed and owner-reviewed artifact required")
    if (
        not _valid_sha(job_hash)
        or job_hash != artifact_hash
        or not isinstance(csv_text, str)
        or hashlib.sha256(csv_text.encode("utf-8")).hexdigest() != job_hash
        or not isinstance(reviewer_id, str)
        or not reviewer_id.strip()
        or len(reviewer_id) > 128
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in reviewer_id)
    ):
        raise JobConflict("Release artifact or reviewer integrity check failed")
    return ReleaseEligibility(
        tenant_id=acting_tenant_id,
        opportunity_id=opportunity_id,
        job_id=handoff.job_id,
        output_sha256=job_hash,
        reviewer_id=reviewer_id,
    )
