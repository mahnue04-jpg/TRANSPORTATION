"""Additive Work & Revenue V2 tables. No production apply in this session.

Revision ID: 20260918_nova_work_revenue_v2
Revises: 20260909_nova_freight_settlement
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260918_nova_work_revenue_v2"
down_revision = "20260909_nova_freight_settlement"
branch_labels = None
depends_on = None


def _create_if_missing(inspector, name: str, factory) -> None:
    if name not in set(inspector.get_table_names()):
        factory()


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _create_if_missing(
        inspector,
        "nova_work_live_action_audits",
        lambda: (
            op.create_table(
                "nova_work_live_action_audits",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("audit_id", sa.String(32), nullable=False),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=False),
                sa.Column("action_type", sa.String(48), nullable=False),
                sa.Column("outcome", sa.String(24), nullable=False, server_default="blocked"),
                sa.Column("reason", sa.String(400), nullable=False),
                sa.Column("external_target", sa.String(220), nullable=True),
                sa.Column("idempotency_key", sa.String(120), nullable=True),
                sa.Column("supervised_action_id", sa.String(32), nullable=True),
                sa.Column("conditions_json", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ),
            op.create_index("ix_nova_work_live_audit_id", "nova_work_live_action_audits", ["audit_id"], unique=True),
            op.create_index(
                "ix_nova_work_live_audit_org",
                "nova_work_live_action_audits",
                ["organization_id", "created_at"],
            ),
            op.create_index(
                "ix_nova_work_live_audit_action",
                "nova_work_live_action_audits",
                ["organization_id", "action_type", "created_at"],
            ),
        ),
    )
    inspector = sa.inspect(op.get_bind())
    _create_if_missing(
        inspector,
        "nova_work_supervised_actions",
        lambda: (
            op.create_table(
                "nova_work_supervised_actions",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("supervised_action_id", sa.String(32), nullable=False),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=False),
                sa.Column("action_type", sa.String(48), nullable=False),
                sa.Column("status", sa.String(24), nullable=False, server_default="DRAFT"),
                sa.Column("capability", sa.String(48), nullable=False),
                sa.Column("title", sa.String(220), nullable=False),
                sa.Column("summary", sa.Text(), nullable=False),
                sa.Column("ref_type", sa.String(32), nullable=True),
                sa.Column("ref_id", sa.String(32), nullable=True),
                sa.Column("idempotency_key", sa.String(120), nullable=False),
                sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Chicago"),
                sa.Column("owner_approved", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("blocked_reason", sa.Text(), nullable=True),
                sa.Column("failure_reason", sa.Text(), nullable=True),
                sa.Column("owner_notes", sa.Text(), nullable=True),
                sa.Column("payload_json", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            ),
            op.create_index("ix_nova_work_sup_id", "nova_work_supervised_actions", ["supervised_action_id"], unique=True),
            op.create_index(
                "ix_nova_work_sup_org",
                "nova_work_supervised_actions",
                ["organization_id", "status", "created_at"],
            ),
            op.create_index(
                "ix_nova_work_sup_idem",
                "nova_work_supervised_actions",
                ["organization_id", "idempotency_key"],
                unique=True,
            ),
        ),
    )
    inspector = sa.inspect(op.get_bind())
    _create_if_missing(
        inspector,
        "nova_work_scheduler_jobs",
        lambda: (
            op.create_table(
                "nova_work_scheduler_jobs",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("job_id", sa.String(32), nullable=False),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=False),
                sa.Column("job_kind", sa.String(48), nullable=False),
                sa.Column("period_key", sa.String(80), nullable=False),
                sa.Column("status", sa.String(24), nullable=False, server_default="PREPARED"),
                sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Chicago"),
                sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("engagement_id", sa.String(32), nullable=True),
                sa.Column("opportunity_id", sa.String(32), nullable=True),
                sa.Column("supervised_action_id", sa.String(32), nullable=True),
                sa.Column("title", sa.String(220), nullable=False),
                sa.Column("notes", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            ),
            op.create_index("ix_nova_work_sched_id", "nova_work_scheduler_jobs", ["job_id"], unique=True),
            op.create_index(
                "ix_nova_work_sched_org",
                "nova_work_scheduler_jobs",
                ["organization_id", "status", "due_at"],
            ),
            op.create_index(
                "ix_nova_work_sched_period",
                "nova_work_scheduler_jobs",
                ["organization_id", "job_kind", "period_key"],
                unique=True,
            ),
        ),
    )
    inspector = sa.inspect(op.get_bind())
    _create_if_missing(
        inspector,
        "nova_work_payment_events",
        lambda: (
            op.create_table(
                "nova_work_payment_events",
                sa.Column("id", sa.String(36), primary_key=True),
                sa.Column("event_id", sa.String(32), nullable=False),
                sa.Column("organization_id", sa.String(36), nullable=False),
                sa.Column("owner_user_id", sa.String(36), nullable=False),
                sa.Column("entry_id", sa.String(32), nullable=True),
                sa.Column("engagement_id", sa.String(32), nullable=True),
                sa.Column("processor_status", sa.String(40), nullable=False, server_default="RECORDED"),
                sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
                sa.Column("currency", sa.String(12), nullable=False, server_default="USD"),
                sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
                sa.Column("idempotency_key", sa.String(120), nullable=False),
                sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("duplicate", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("applied_to_ledger", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column("notes", sa.Text(), nullable=True),
                sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            ),
            op.create_index("ix_nova_work_payevt_id", "nova_work_payment_events", ["event_id"], unique=True),
            op.create_index("ix_nova_work_payevt_org", "nova_work_payment_events", ["organization_id", "created_at"]),
            op.create_index(
                "ix_nova_work_payevt_idem",
                "nova_work_payment_events",
                ["organization_id", "idempotency_key"],
                unique=True,
            ),
        ),
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    for table in (
        "nova_work_payment_events",
        "nova_work_scheduler_jobs",
        "nova_work_supervised_actions",
        "nova_work_live_action_audits",
    ):
        if table in names:
            op.drop_table(table)
