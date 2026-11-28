"""Staging-only owner approval evidence schema and checks.

No startup DDL; schema must be explicitly reviewed and migrated. An approval
receipt is not automatically created from an existing task status or note.
Only a trusted authenticated owner action may create one in a future endpoint.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .operations_commercial_mode import resolve_operations_mode
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
    expected_livemode: bool = False,
) -> None:
    """Read exact owner decision: absence, missing migration or rejection deny."""
    if type(expected_livemode) is not bool:
        raise AllowanceBlocked("invalid_payment_mode")
    if expected_livemode:
        if (os.getenv("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_LIVE_ENABLED") != "true"
                or os.getenv("APP_ENV") != "production"
                or os.getenv("AMICOR_ENVIRONMENT") != "production"
                or os.getenv("NOVA_STRIPE_LIVE_ENABLED") != "true"
                or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") != "true"
                or db.get_bind().dialect.name != "postgresql"):
            raise AllowanceBlocked("subscription_approval_live_disabled")
    else:
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


def subscription_approval_write_mode() -> str | None:
    return resolve_operations_mode(
        staging_flags=("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_STAGING_ENABLED",),
        live_flags=("NOVA_OPERATIONS_SUBSCRIPTION_APPROVAL_LIVE_ENABLED",),
    )


def record_staging_owner_scope_decision(
    db: Session, *, authenticated_user, organization_id: str,
    engagement_id: str, task_id: str, lead_id: str,
    task_fingerprint: str, decision: str,
) -> dict:
    """Save or revoke a scope decision. No work is executed.

    Only a trusted server component may supply authenticated_user from the
    session dependency. The operation is gated and stored in PostgreSQL.
    Every change is accompanied by an append-only decision event.
    """
    mode = require_approval_write(db)
    live = mode == "live"
    user_id = str(getattr(authenticated_user, "user_id", "") or "")
    user_org = str(getattr(authenticated_user, "organization_id", "") or "")
    role = str(getattr(authenticated_user, "role", "") or "").lower()
    if (not user_id or user_org != organization_id or role not in {"admin", "super_admin_support"}):
        raise AllowanceBlocked("authenticated_owner_required")
    if decision not in {"APPROVED", "REJECTED", "REVOKED"}:
        raise AllowanceBlocked("invalid_approval_decision")
    if not all((engagement_id, task_id, lead_id)):
        raise AllowanceBlocked("approval_scope_missing")
    if (not isinstance(task_fingerprint, str) or len(task_fingerprint) != 64
            or any(c not in "0123456789abcdef" for c in task_fingerprint)):
        raise AllowanceBlocked("approval_fingerprint_invalid")
    if not sa.inspect(db.get_bind()).has_table(approval_events.name):
        raise AllowanceBlocked("approval_events_migration_required")
    from app.core.nova.work_revenue.models import NovaWorkEngagement, NovaWorkTask
    from app.modules.marketing.models import MarketingWebsiteLead
    engagement = db.execute(sa.select(NovaWorkEngagement).where(
        NovaWorkEngagement.engagement_id == engagement_id,
        NovaWorkEngagement.organization_id == organization_id,
        NovaWorkEngagement.owner_user_id == user_id,
    )).scalar_one_or_none()
    task = db.execute(sa.select(NovaWorkTask).where(
        NovaWorkTask.task_id == task_id,
        NovaWorkTask.engagement_id == engagement_id,
        NovaWorkTask.organization_id == organization_id,
        NovaWorkTask.owner_user_id == user_id,
    )).scalar_one_or_none()
    lead = db.get(MarketingWebsiteLead, lead_id)
    email = str(lead.work_email or "") if lead is not None else ""
    if (engagement is None or task is None or task.review_required is not True
            or lead is None or lead.lead_type != "anonymous_operations"
            or lead.service_plan not in {"launch_99", "business_299"}):
        raise AllowanceBlocked("synthetic_task_scope_mismatch")
    if live and email.lower().endswith(".invalid"):
        raise AllowanceBlocked("live_task_scope_mismatch")
    if not live and not email.endswith(".invalid"):
        raise AllowanceBlocked("synthetic_task_scope_mismatch")

    from datetime import datetime, timezone
    from uuid import uuid4
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    timestamp = datetime.now(timezone.utc)
    approval_id = uuid4().hex
    event_id = uuid4().hex
    scope = {
        "organization_id": organization_id, "owner_user_id": user_id,
        "engagement_id": engagement_id, "task_id": task_id,
        "lead_id": lead_id, "task_fingerprint": task_fingerprint,
    }
    try:
        # Unique constraint serializes competing approve/revoke decisions.
        stmt = pg_insert(approvals).values(
            approval_id=approval_id, **scope, decision=decision,
            decided_at=timestamp,
        ).on_conflict_do_update(
            constraint="uq_nova_ops_subscription_scope_decision",
            set_={"decision": decision, "decided_at": timestamp},
        )
        db.execute(stmt)
        db.execute(sa.insert(approval_events).values(
            event_id=event_id, **scope, decision=decision,
            decided_at=timestamp,
        ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"decision": decision, "event_id": event_id, "task_id": task_id,
            "executed": False, "mode": mode}


# Append-only audit events. This table must be explicitly migrated alongside
# the current decision table. No code path updates/deletes event records.
approval_events = sa.Table(
    "nova_operations_subscription_scope_approval_events", metadata,
    sa.Column("event_id", sa.String(64), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("lead_id", sa.String(36), nullable=False),
    sa.Column("task_fingerprint", sa.String(64), nullable=False),
    sa.Column("decision", sa.String(16), nullable=False),
    sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
)


def require_approval_staging(db: Session) -> None:
    """Backward-compatible staging-only gate used by older callers/tests."""
    require_approval_write(db)


def require_approval_write(db: Session) -> str:
    mode = subscription_approval_write_mode()
    if mode is None or db.get_bind().dialect.name != "postgresql":
        raise AllowanceBlocked("subscription_approval_ledger_disabled")
    if not sa.inspect(db.get_bind()).has_table(approvals.name):
        raise AllowanceBlocked("approval_migration_required")
    return mode
