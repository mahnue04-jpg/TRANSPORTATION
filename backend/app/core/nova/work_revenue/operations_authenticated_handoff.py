"""Atomic offline-only bridge from a session-derived identity into an assignment.

The future HTTP caller MUST separately enforce require_work_revenue_owner on a
verified server session. This module is NOT an authentication or delivery gate.
No customer data, routes, providers, or outbound actions are used here.
"""
from __future__ import annotations

import hashlib
import sqlite3

from app.auth import UserContext

from .operations_assignment_handoff import AssignmentHandoff, _identifier
from .operations_job_queue import JobConflict, _valid_sha
from .operations_owner_scope import owner_approval_identity


def approve_and_handoff_offline(
    db: sqlite3.Connection, *,
    authenticated_owner: UserContext,
    opportunity_id: str,
    approval_reference: str,
    input_sha256: str,
) -> AssignmentHandoff:
    """Atomically persist a synthetic approval, queue job, and handoff.

    Tenant and reviewer come from the supplied server-session object, not from
    independent client fields. This does not verify that object or owner role.
    A future authenticated HTTP adapter must do that before invoking this.
    """
    tenant_id, reviewer_id = owner_approval_identity(authenticated_owner)
    if (
        not _identifier(opportunity_id)
        or not _identifier(approval_reference)
        or not _valid_sha(input_sha256)
    ):
        raise JobConflict("Valid opportunity, approval and input fingerprint required")
    if db.in_transaction:
        raise JobConflict("Atomic handoff requires a dedicated transaction")

    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            """INSERT INTO nova_operations_offline_approvals
               (tenant_id, opportunity_id, approval_reference, input_sha256, reviewer_id)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, opportunity_id) DO NOTHING""",
            (tenant_id, opportunity_id, approval_reference, input_sha256, reviewer_id),
        )
        approved = db.execute(
            """SELECT approval_reference, input_sha256, reviewer_id
               FROM nova_operations_offline_approvals
               WHERE tenant_id=? AND opportunity_id=?""",
            (tenant_id, opportunity_id),
        ).fetchone()
        if approved != (approval_reference, input_sha256, reviewer_id):
            raise JobConflict("Conflicting owner approval evidence")

        db.execute(
            """INSERT INTO nova_operations_offline_jobs
               (tenant_id, idempotency_key, kind, input_sha256, max_attempts)
               VALUES (?, ?, 'csv_cleanup', ?, 3)
               ON CONFLICT(tenant_id, idempotency_key) DO NOTHING""",
            (tenant_id, "opportunity:" + opportunity_id, input_sha256),
        )
        job = db.execute(
            """SELECT job_id, kind, input_sha256, max_attempts
               FROM nova_operations_offline_jobs
               WHERE tenant_id=? AND idempotency_key=?""",
            (tenant_id, "opportunity:" + opportunity_id),
        ).fetchone()
        if job is None or job[1:] != ("csv_cleanup", input_sha256, 3):
            raise JobConflict("Opportunity already refers to a different job")
        job_id = int(job[0])

        db.execute(
            """INSERT INTO nova_operations_offline_handoffs
               (tenant_id, opportunity_id, approval_reference, job_id, input_sha256)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(tenant_id, opportunity_id) DO NOTHING""",
            (tenant_id, opportunity_id, approval_reference, job_id, input_sha256),
        )
        linked = db.execute(
            """SELECT approval_reference, job_id, input_sha256
               FROM nova_operations_offline_handoffs
               WHERE tenant_id=? AND opportunity_id=?""",
            (tenant_id, opportunity_id),
        ).fetchone()
        if linked != (approval_reference, job_id, input_sha256):
            raise JobConflict("Opportunity handoff conflicts with existing approval")
        db.commit()
        return AssignmentHandoff(tenant_id, opportunity_id, approval_reference, job_id)
    except BaseException:
        db.rollback()
        raise



def review_approved_assignment_offline(
    db: sqlite3.Connection, *,
    authenticated_owner: UserContext,
    opportunity_id: str,
    approve: bool,
) -> str:
    """Review a synthetic deliverable only as its original approving actor.

    The caller must first authenticate and authorize the session at the
    server boundary. This helper does not grant roles or deliver artifacts.
    """
    from .operations_assignment_handoff import get_assignment_handoff

    tenant_id, actor_id = owner_approval_identity(authenticated_owner)
    if not _identifier(opportunity_id) or type(approve) is not bool:
        raise JobConflict("Valid opportunity and boolean review decision required")
    if db.in_transaction:
        raise JobConflict("Owner review requires a dedicated transaction")

    db.execute("BEGIN IMMEDIATE")
    try:
        handoff = get_assignment_handoff(
            db, acting_tenant_id=tenant_id, opportunity_id=opportunity_id,
        )
        if handoff is None:
            raise JobConflict("Assignment unavailable for owner review")
        approved = db.execute(
            """SELECT reviewer_id FROM nova_operations_offline_approvals
               WHERE tenant_id=? AND opportunity_id=?""",
            (tenant_id, opportunity_id),
        ).fetchone()
        if approved is None or approved[0] != actor_id:
            raise JobConflict("Review actor does not match recorded approval")
        artifact = db.execute(
            """SELECT a.csv_text, a.output_sha256, j.output_sha256
               FROM nova_operations_offline_artifacts AS a
               JOIN nova_operations_offline_jobs AS j
                 ON j.tenant_id=a.tenant_id AND j.job_id=a.job_id
               WHERE a.tenant_id=? AND a.job_id=?
                 AND a.review_state='awaiting_review' AND j.state='completed'""",
            (tenant_id, handoff.job_id),
        ).fetchone()
        if artifact is None:
            raise JobConflict("Completed artifact unavailable or already reviewed")
        csv_text, artifact_hash, job_hash = artifact
        if (
            not isinstance(csv_text, str)
            or not _valid_sha(artifact_hash)
            or artifact_hash != job_hash
            or hashlib.sha256(csv_text.encode("utf-8")).hexdigest() != artifact_hash
        ):
            raise JobConflict("Review artifact integrity check failed")
        if len(actor_id) > 128:
            raise JobConflict("Reviewer identity exceeds artifact review limit")
        state = "approved" if approve else "rejected"
        updated = db.execute(
            """UPDATE nova_operations_offline_artifacts
               SET review_state=?, reviewer_id=?
               WHERE tenant_id=? AND job_id=?
                 AND review_state='awaiting_review'
                 AND EXISTS (
                   SELECT 1 FROM nova_operations_offline_jobs AS j
                   WHERE j.tenant_id=? AND j.job_id=? AND j.state='completed'
                     AND j.output_sha256=nova_operations_offline_artifacts.output_sha256
                 )""",
            (state, actor_id, tenant_id, handoff.job_id, tenant_id, handoff.job_id),
        )
        if updated.rowcount != 1:
            raise JobConflict("Completed artifact unavailable or already reviewed")
        db.commit()
        return state
    except BaseException:
        db.rollback()
        raise



def preview_approved_assignment_offline(
    db: sqlite3.Connection, *,
    authenticated_owner: UserContext,
    opportunity_id: str,
) -> tuple[str, str]:
    """Read a bounded synthetic CSV for its recorded approving actor only.

    This is an offline review preview, NOT an externally callable download.
    The server boundary must independently validate JWT and owner access.
    """
    from .operations_assignment_handoff import get_assignment_handoff

    tenant_id, actor_id = owner_approval_identity(authenticated_owner)
    if not _identifier(opportunity_id) or len(actor_id) > 128:
        raise JobConflict("Valid opportunity and reviewer identity required")
    handoff = get_assignment_handoff(
        db, acting_tenant_id=tenant_id, opportunity_id=opportunity_id,
    )
    if handoff is None:
        raise JobConflict("Assignment unavailable for owner preview")
    row = db.execute(
        """SELECT a.csv_text, a.output_sha256, j.output_sha256,
                  a.review_state, p.reviewer_id
           FROM nova_operations_offline_artifacts AS a
           JOIN nova_operations_offline_jobs AS j
             ON j.tenant_id=a.tenant_id AND j.job_id=a.job_id
           JOIN nova_operations_offline_approvals AS p
             ON p.tenant_id=a.tenant_id AND p.opportunity_id=?
           WHERE a.tenant_id=? AND a.job_id=? AND j.state='completed'""",
        (opportunity_id, tenant_id, handoff.job_id),
    ).fetchone()
    if row is None:
        raise JobConflict("Completed artifact unavailable for owner preview")
    csv_text, artifact_hash, job_hash, review_state, recorded_reviewer = row
    if recorded_reviewer != actor_id:
        raise JobConflict("Preview actor does not match recorded approval")
    if (
        not isinstance(csv_text, str)
        or len(csv_text.encode("utf-8")) > 1_000_000
        or not _valid_sha(artifact_hash)
        or artifact_hash != job_hash
        or hashlib.sha256(csv_text.encode("utf-8")).hexdigest() != artifact_hash
        or review_state not in ("awaiting_review", "approved", "rejected")
    ):
        raise JobConflict("Preview artifact integrity check failed")
    return review_state, csv_text
