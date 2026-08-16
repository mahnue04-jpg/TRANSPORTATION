"""Approval Engine external verification adapter columns

Revision ID: 20260809_approval_external_adapters
Revises: 20260808_approval_engine
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260809_approval_external_adapters"
down_revision = "20260808_approval_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approval_engine_requirements",
        sa.Column("external_status", sa.String(32), nullable=False, server_default="NOT_STARTED"),
    )
    op.add_column("approval_engine_requirements", sa.Column("verification_date", sa.Date(), nullable=True))
    op.add_column("approval_engine_requirements", sa.Column("evidence_source", sa.String(256), nullable=True))
    op.add_column("approval_engine_requirements", sa.Column("provider_key", sa.String(64), nullable=True))
    op.add_column(
        "approval_engine_requirements",
        sa.Column("provider_reference_id", sa.String(128), nullable=True),
    )
    op.add_column("approval_engine_requirements", sa.Column("reviewer_source", sa.String(16), nullable=True))

    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("requirement_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("external_status", sa.String(32), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("evidence_source", sa.String(256), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("provider_key", sa.String(64), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("provider_reference_id", sa.String(128), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("verification_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("expiration_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "approval_engine_external_tasks",
        sa.Column("audit_history_json", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_approval_engine_external_tasks_requirement_key",
        "approval_engine_external_tasks",
        ["requirement_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_engine_external_tasks_requirement_key",
        table_name="approval_engine_external_tasks",
    )
    for col in (
        "audit_history_json",
        "expiration_date",
        "verification_date",
        "provider_reference_id",
        "provider_key",
        "evidence_source",
        "external_status",
        "requirement_key",
    ):
        op.drop_column("approval_engine_external_tasks", col)
    for col in (
        "reviewer_source",
        "provider_reference_id",
        "provider_key",
        "evidence_source",
        "verification_date",
        "external_status",
    ):
        op.drop_column("approval_engine_requirements", col)
