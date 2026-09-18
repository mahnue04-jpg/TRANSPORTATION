"""Additive Work & Revenue V2 hardening. V2 tables only. Not applied to production.

Revision ID: 20260918_nova_work_revenue_v2_hardening
Revises: 20260918_nova_work_revenue_v2
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260918_nova_work_revenue_v2_hardening"
down_revision = "20260918_nova_work_revenue_v2"
branch_labels = None
depends_on = None


def _columns(inspector, table: str) -> set[str]:
    if table not in set(inspector.get_table_names()):
        return set()
    return {col["name"] for col in inspector.get_columns(table)}


def _add_column(inspector, table: str, column: sa.Column) -> None:
    if table not in set(inspector.get_table_names()):
        return
    if column.name in _columns(inspector, table):
        return
    op.add_column(table, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_audit_events", sa.Column("idempotency_key", sa.String(120), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_audit_events", sa.Column("approval_ref", sa.String(32), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_audit_events", sa.Column("reason", sa.String(400), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_audit_events", sa.Column("source", sa.String(80), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_supervised_actions", sa.Column("approval_status", sa.String(24), nullable=False, server_default="NONE"))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_supervised_actions", sa.Column("approval_fingerprint", sa.String(64), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_supervised_actions", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_supervised_actions", sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_supervised_actions", sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_supervised_actions", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    inspector = sa.inspect(bind)
    _add_column(inspector, "nova_work_payment_events", sa.Column("historical", sa.Boolean(), nullable=False, server_default=sa.false()))
    inspector = sa.inspect(bind)
    names = set(inspector.get_table_names())
    if "nova_work_historical_corrections" not in names:
        op.create_table(
            "nova_work_historical_corrections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("correction_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("owner_user_id", sa.String(36), nullable=False),
            sa.Column("entry_id", sa.String(32), nullable=True),
            sa.Column("engagement_id", sa.String(32), nullable=True),
            sa.Column("opportunity_id", sa.String(32), nullable=True),
            sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(12), nullable=False, server_default="USD"),
            sa.Column("reason", sa.String(400), nullable=False),
            sa.Column("classification", sa.String(40), nullable=False, server_default="HISTORICAL"),
            sa.Column("applied_to_current_totals", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("idempotency_key", sa.String(120), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_work_hist_id", "nova_work_historical_corrections", ["correction_id"], unique=True)
        op.create_index("ix_nova_work_hist_org", "nova_work_historical_corrections", ["organization_id", "created_at"])
        op.create_index(
            "ix_nova_work_hist_idem",
            "nova_work_historical_corrections",
            ["organization_id", "owner_user_id", "idempotency_key"],
            unique=True,
        )
    inspector = sa.inspect(bind)
    for table, old_name, columns in (
        (
            "nova_work_supervised_actions",
            "ix_nova_work_sup_idem",
            ["organization_id", "owner_user_id", "idempotency_key"],
        ),
        (
            "nova_work_payment_events",
            "ix_nova_work_payevt_idem",
            ["organization_id", "owner_user_id", "idempotency_key"],
        ),
    ):
        if table not in set(inspector.get_table_names()):
            continue
        op.execute(f"DROP INDEX IF EXISTS {old_name}")
        op.create_index(old_name, table, columns, unique=True)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_work_historical_corrections" in names:
        op.drop_table("nova_work_historical_corrections")
    # Owner-scoped unique indexes remain; reverting them would reintroduce the isolation defect.
    # Additive audit/approval columns are left in place on downgrade to avoid data loss.
