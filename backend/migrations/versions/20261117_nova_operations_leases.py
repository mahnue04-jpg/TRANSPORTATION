"""Staging-only PostgreSQL Operations lease metadata; no worker activation.

Revision ID: 20261117_nova_ops_leases
Revises: 20261109_nova_csv_jobs

Review-only migration. DDL is permitted only with an exact staging
environment and an explicit schema approval flag. Ambiguous staging is blocked.
Outside the explicitly authorized staging target this migration raises and must
NOT be marked applied. Production needs a separate reviewed migration.
"""
from __future__ import annotations

import os
import re

import sqlalchemy as sa
from alembic import op

revision = "20261117_nova_ops_leases"
down_revision = "20261109_nova_csv_jobs"
branch_labels = None
depends_on = None

TABLE = "nova_operations_processing_leases"


def _allowed() -> bool:
    environments = {
        os.getenv(name, "").strip().lower()
        for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
        if os.getenv(name)
    }
    return (environments == {"staging"} and
            os.getenv("NOVA_OPERATIONS_LEASE_SCHEMA_APPROVED", "").strip()
            == "staging-only")


def upgrade() -> None:
    environments = {
        os.getenv(name, "").strip().lower()
        for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")
        if os.getenv(name)
    }
    # Never report an unapplied migration as applied in production or other
    # environments. A silent no-op is unsafe for the Alembic version ledger.
    if not _allowed():
        raise RuntimeError("Explicit staging-only Operations lease schema approval required")
    expected_db = os.getenv("NOVA_OPERATIONS_EXPECTED_STAGING_DATABASE", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,63}", expected_db):
        raise RuntimeError("Exact approved Operations staging database name required")
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        raise RuntimeError("Operations lease metadata requires PostgreSQL")
    actual_db = bind.execute(sa.text("SELECT current_database()")).scalar_one()
    if actual_db != expected_db:
        raise RuntimeError("Connected PostgreSQL database does not match staging approval")
    if TABLE in sa.inspect(bind).get_table_names():
        raise RuntimeError("Lease table already exists; reconcile before migration")
    op.create_table(
        TABLE,
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_ref", sa.String(512), nullable=True),
        sa.Column("input_size", sa.Integer, nullable=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer, nullable=False, server_default="3"),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('QUEUED','RUNNING','COMPLETED','FAILED','CANCELLED',"
            "'NEEDS_RECONCILIATION')",
            name="ck_nova_operations_lease_state",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts BETWEEN 1 AND 10",
            name="ck_nova_operations_lease_attempts",
        ),
        sa.CheckConstraint(
            "(input_ref IS NULL AND input_size IS NULL) OR "
            "(input_ref IS NOT NULL AND input_size BETWEEN 1 AND 1000000)",
            name="ck_nova_operations_lease_input_binding",
        ),
    )
    op.create_index(
        "ix_nova_operations_lease_ready", TABLE,
        ["state", "available_at", "lease_until"],
    )


def downgrade() -> None:
    # An Alembic no-op downgrade would falsely lower alembic_version while
    # retaining the lease table and its forensic records. Explicitly refuse
    # until a separately approved retention-safe rollback is implemented.
    raise RuntimeError("Operations lease rollback requires separate owner approval")
