"""Offline-only bridge from an authenticated owner session into assignment approval.

The caller MUST first enforce require_work_revenue_owner on a verified server
session. This module does not authenticate users or register an HTTP endpoint.
Never accept tenant_id, reviewer_id, or reviewer_authorized from request data.
"""
from __future__ import annotations

import sqlite3

from app.auth import UserContext
from .operations_owner_scope import owner_approval_identity
from .operations_assignment_handoff import (
    AssignmentHandoff,
    handoff_approved_opportunity,
    record_verified_owner_approval,
)


def approve_and_handoff_offline(
    db: sqlite3.Connection, *,
    authenticated_owner: UserContext,
    opportunity_id: str,
    approval_reference: str,
    input_sha256: str,
) -> AssignmentHandoff:
    """Persist synthetic owner approval and handoff without external actions.

    The owner access guard is a prerequisite enforced by the future server
    adapter, not by this helper. Non-atomic between the two SQLite operations:
    a retry after interruption must rely on durable idempotency.
    """
    tenant_id, reviewer_id = owner_approval_identity(authenticated_owner)
    record_verified_owner_approval(
        db,
        acting_tenant_id=tenant_id,
        record_tenant_id=tenant_id,
        opportunity_id=opportunity_id,
        approval_reference=approval_reference,
        input_sha256=input_sha256,
        reviewer_id=reviewer_id,
        reviewer_authorized=True,
    )
    return handoff_approved_opportunity(
        db,
        acting_tenant_id=tenant_id,
        record_tenant_id=tenant_id,
        opportunity_id=opportunity_id,
        approval_reference=approval_reference,
        input_sha256=input_sha256,
    )
