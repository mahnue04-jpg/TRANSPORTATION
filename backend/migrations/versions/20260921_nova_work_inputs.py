"""Add engagement-level Work & Revenue source inputs.

Revision ID: 20260921_nova_work_inputs
Revises: 20260918_nova_v3_live_infra
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260921_nova_work_inputs"
down_revision = "20260918_nova_v3_live_infra"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "nova_work_inputs" in set(inspector.get_table_names()):
        return
    op.create_table(
        "nova_work_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("input_id", sa.String(32), nullable=False, unique=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("engagement_id", sa.String(32), nullable=False),
        sa.Column("input_kind", sa.String(40), nullable=False, server_default="SOURCE_DATA"),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("storage_ref", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="AVAILABLE"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_nova_work_input_id", "nova_work_inputs", ["input_id"], unique=True)
    op.create_index(
        "ix_nova_work_input_engagement",
        "nova_work_inputs",
        ["organization_id", "engagement_id", "is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("nova_work_inputs")
