"""Atomic offline-only bridge from a session-derived identity into an assignment.

The future HTTP caller MUST separately enforce require_work_revenue_owner on a
verified server session. This module is NOT an authentication or delivery gate.
No customer data, routes, providers, or outbound actions are used here.
"""
from __future__ import annotations

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
