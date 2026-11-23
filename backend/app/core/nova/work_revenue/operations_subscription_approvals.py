"""Staging-only owner approval evidence schema and checks.

No startup DDL; schema must be explicitly reviewed and migrated. An approval
receipt is not automatically created from an existing task status or note.
Only a trusted authenticated owner action may create one in a future endpoint.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .operations_package_usage_ledger import AllowanceBlocked

metadata = sa.MetaData()
approvals = sa.Table(
    "nova_operations_subscription_task_scope_approvals", metadata,
    sa.Column("approval_id", sa.String(64), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("lead_id", sa.String(36), nullable=False),
    sa.Column("task_fingerprint", sa.String(64), nullable=False),
    sa.Column("decision", sa.String(16), nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint("organization_id", "owner_user_id", "task_id", "lead_id", "task_fingerprint",
                        name="uq_nova_ops_subscription_scope_decision"),
)


def require_saved_owner_scope_approval(
    db: Session, *, organization_id: str, owner_user_id: str,
    engagement_id: str, task_id: str, lead_id: str,
    task_fingerprint: str,
) -> None:
    """Read exact owner decision: absence, missing migration or rejection deny."""
    if (
        os.getenv("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_STAGING_ENABLED") != "true"
        or os.getenv("APP_ENV") != "staging"
        or os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").lower() == "true"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").lower() == "true"
        or db.get_bind().dialect.name != "postgresql"
    ):
        raise AllowanceBlocked("subscription_approval_ledger_disabled")
    if not sa.inspect(db.get_bind()).has_table(approvals.name):
        raise AllowanceBlocked("approval_migration_required")
    if not all((organization_id, owner_user_id, engagement_id, task_id, lead_id)):
        raise AllowanceBlocked("approval_scope_missing")
    if (not isinstance(task_fingerprint, str) or len(task_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in task_fingerprint)):
        raise AllowanceBlocked("approval_fingerprint_invalid")

    records = db.execute(sa.select(approvals.c.decision).where(
        approvals.c.organization_id == organization_id,
        approvals.c.owner_user_id == owner_user_id,
        approvals.c.engagement_id == engagement_id,
        approvals.c.task_id == task_id,
        approvals.c.lead_id == lead_id,
        approvals.c.task_fingerprint == task_fingerprint,
    )).scalars().all()
    if len(records) != 1 or records[0] != "APPROVED":
        raise AllowanceBlocked("explicit_owner_approval_missing")
