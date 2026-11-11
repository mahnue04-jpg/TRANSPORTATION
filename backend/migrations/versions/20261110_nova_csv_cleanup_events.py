"""Isolated staging-only audit table for CSV object cleanup debt.

Revision ID: 20261110_nova_csv_cleanup
Revises: 20261110_nova_csv_recovery
"""
from __future__ import annotations

import os
import sqlalchemy as sa
from alembic import op

revision = "20261110_nova_csv_cleanup"
down_revision = "20261110_nova_csv_recovery"
branch_labels = None
depends_on = None

TABLE = "nova_operations_csv_cleanup_events"


def _approved_staging() -> bool:
    envs = {
        os.getenv(name, "").strip().lower()
        for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
        if os.getenv(name)
    }
    return envs == {"staging"} and os.getenv(
        "NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", ""
    ).strip() == "staging-only"


def upgrade():
    envs = {
        os.getenv(name, "").strip().lower()
        for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
        if os.getenv(name)
    }
    if "staging" in envs and not _approved_staging():
        raise RuntimeError("Explicit isolated staging schema approval required")
    if not _approved_staging():
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Cleanup audit requires isolated PostgreSQL")
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("storage_ref", sa.String(512), nullable=False),
        sa.Column("failure_code", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "failure_code IN ('INPUT_DELETE_FAILED','OUTPUT_DELETE_FAILED')",
            name="ck_nova_csv_cleanup_code",
        ),
    )
    op.create_index(
        "ix_nova_csv_cleanup_unresolved",
        TABLE, ["organization_id", "owner_user_id", "resolved_at"],
    )


def downgrade():
    # Do not erase evidence of failed deletion during rollbacks.
    pass
