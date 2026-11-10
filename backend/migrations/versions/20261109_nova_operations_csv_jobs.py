"""Staging-gated durable Operations CSV job metadata.

Revision ID: 20261109_nova_csv_jobs
Revises: 20261012_casting_org_name

DDL is deliberately limited to explicitly authorized isolated staging.
Production and other environments can stamp the Alembic revision, but cannot
create the table from this migration. A separate reviewed production release
migration must be prepared after staging acceptance.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "20261109_nova_csv_jobs"
down_revision = "20261012_casting_org_name"
branch_labels = None
depends_on = None

TABLE = "nova_operations_customer_csv_jobs"


def _staging_approved() -> bool:
    names = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
    environments = {os.getenv(name, "").strip().lower() for name in names if os.getenv(name)}
    return (
        environments == {"staging"}
        and os.getenv("NOVA_OPERATIONS_CSV_SCHEMA_APPROVED", "").strip() == "staging-only"
    )


def upgrade() -> None:
    # Never touch live or ambiguous environments. Staging without explicit
    # approval must FAIL instead of silently stamping the revision and leaving
    # the required table absent.
    raw_envs = {os.getenv(name, "").strip().lower()
                for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
                if os.getenv(name)}
    if "staging" in raw_envs and not _staging_approved():
        raise RuntimeError("Staging CSV schema approval required")
    if not _staging_approved():
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required for durable customer CSV metadata")
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
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("output_ref", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reviewer_user_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "organization_id", "owner_user_id", "request_key",
            name="uq_nova_customer_csv_request",
        ),
        sa.CheckConstraint(
            "status IN ('PROCESSING','FAILED','AWAITING_REVIEW',"
            "'APPROVED_FOR_DOWNLOAD','REJECTED')",
            name="ck_nova_customer_csv_status",
        ),
    )
    op.create_index(
        "ix_nova_customer_csv_owned", TABLE,
        ["organization_id", "owner_user_id", "engagement_id",
         "task_id", "updated_at"],
    )


def downgrade() -> None:
    # Preserve forensic records; reversions disable the runtime feature.
    # Schema removal requires a separately approved data-retention plan.
    pass
