"""Staging-only signed-scope evidence table for Nova finance work.

Revision ID: 20261111_nova_bk_consent
Revises: 20261109_nova_csv_jobs

Never provisions client authorization. No default production DDL. A separate
approved production migration is mandatory after staging review.
"""
from __future__ import annotations

import os

import sqlalchemy as sa
from alembic import op

revision = "20261111_nova_bk_consent"
down_revision = "20261109_nova_csv_jobs"
branch_labels = None
depends_on = None

TABLE = "nova_bookkeeping_contract_authorizations"


def _staging_approved() -> bool:
    names = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
    envs = {os.getenv(k, "").strip().lower() for k in names if os.getenv(k)}
    return envs == {"staging"} and os.getenv(
        "NOVA_BOOKKEEPING_CONSENT_SCHEMA_APPROVED", ""
    ).strip() == "staging-only"


def upgrade() -> None:
    names = ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
    envs = {os.getenv(k, "").strip().lower() for k in names if os.getenv(k)}
    if "staging" in envs and not _staging_approved():
        raise RuntimeError("Explicit isolated staging bookkeeping schema approval required")
    if not _staging_approved():
        return
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("PostgreSQL required")
    if TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        TABLE,
        sa.Column("authorization_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("engagement_id", sa.String(32), nullable=False),
        sa.Column("task_id", sa.String(32), nullable=False),
        sa.Column("work_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("contract_ref_sha256", sa.String(64), nullable=False),
        sa.Column("client_ai_consent_ref_sha256", sa.String(64), nullable=False),
        sa.Column("data_processing_ref_sha256", sa.String(64), nullable=False),
        sa.Column("verified_by_user_id", sa.String(36), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "organization_id", "owner_user_id", "engagement_id",
            "task_id", "work_type", name="uq_nova_bookkeeping_consent_scope",
        ),
        sa.CheckConstraint(
            "status IN ('APPROVED','REVOKED')",
            name="ck_nova_bookkeeping_consent_status",
        ),
        sa.CheckConstraint(
            "work_type IN ('transaction_workpaper','receivables_aging','payables_aging')",
            name="ck_nova_bookkeeping_consent_work_type",
        ),
    )
    op.create_index(
        "ix_nova_bookkeeping_consent_owned", TABLE,
        ["organization_id", "owner_user_id", "engagement_id", "task_id", "work_type"],
    )


def downgrade() -> None:
    # Preserve consent provenance for audit/retention; disable feature instead.
    pass
