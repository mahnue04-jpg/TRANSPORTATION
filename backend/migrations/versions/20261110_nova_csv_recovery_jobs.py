"""Isolated-staging-only recoverable CSV queue schema.

Revision ID: 20261110_nova_csv_recovery
Revises: 20261109_nova_csv_jobs

Never add customer-job tables to production without separate migration review.
"""
from __future__ import annotations
import os
import sqlalchemy as sa
from alembic import op

revision = "20261110_nova_csv_recovery"
down_revision = "20261109_nova_csv_jobs"
branch_labels = None
depends_on = None

TABLE = "nova_operations_csv_recovery_jobs"


def _approved_staging():
    names = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
    envs = {os.getenv(name, "").strip().lower() for name in names if os.getenv(name)}
    return (envs == {"staging"} and
            os.getenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "").strip() == "staging-only")


def upgrade():
    envs = {os.getenv(name, "").strip().lower() for name in
            ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV") if os.getenv(name)}
    if "staging" in envs and not _approved_staging():
        raise RuntimeError("Explicit isolated staging schema approval required")
    if not _approved_staging():
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Recoverable customer CSV needs PostgreSQL")
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("engagement_id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("request_key", sa.String(120), nullable=False),
        sa.Column("input_ref", sa.String(512)),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_ref", sa.String(512)),
        sa.Column("output_sha256", sa.String(64)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("lease_token", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organization_id", "owner_user_id", "request_key",
                            name="uq_nova_csv_recovery_request"),
        sa.CheckConstraint(
            "status IN ('UPLOADING','QUEUED','RUNNING','AWAITING_REVIEW',"
            "'APPROVED_FOR_DOWNLOAD','REJECTED','FAILED')",
            name="ck_nova_csv_recovery_status",
        ),
        sa.CheckConstraint("attempts >= 0 AND max_attempts BETWEEN 1 AND 10",
                           name="ck_nova_csv_recovery_attempts"),
    )
    op.create_index("ix_nova_csv_recovery_owner", TABLE,
                    ["organization_id", "owner_user_id", "updated_at"])
    op.create_index("ix_nova_csv_recovery_available", TABLE,
                    ["status", "available_at", "lease_until"])


def downgrade():
    # Customer metadata and references must survive application rollbacks.
    pass
