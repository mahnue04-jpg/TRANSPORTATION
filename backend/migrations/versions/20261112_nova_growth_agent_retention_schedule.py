"""Growth Agent scheduled retention durable runs (draft / prod-gated).

Revision ID: 20261112_nova_ga_retention
Revises: 20261112_nova_ga_worker

Additive only. Production-locked environments skip DDL.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261112_nova_ga_retention"
down_revision = "20261112_nova_ga_worker"
branch_labels = None
depends_on = None


def _production_schema_locked() -> bool:
    import os

    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def _json_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return JSONB()
    return sa.JSON()


def upgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "nova_ga_retention_schedule_runs" in existing:
        return
    json_t = _json_type()
    op.create_table(
        "nova_ga_retention_schedule_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("window_key", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("mode", sa.String(20), nullable=False, server_default="dry_run"),
        sa.Column("claimed_by", sa.String(80), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("batch_limit", sa.Integer(), nullable=False, server_default="500"),
        sa.Column("result_json", json_t, nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "organization_id",
            "window_key",
            name="uq_nova_ga_retention_org_window",
        ),
    )
    op.create_index(
        "ix_nova_ga_retention_claim",
        "nova_ga_retention_schedule_runs",
        ["status", "available_at", "lease_expires_at"],
    )
    op.create_index(
        "ix_nova_ga_retention_org",
        "nova_ga_retention_schedule_runs",
        ["organization_id", "created_at"],
    )


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "nova_ga_retention_schedule_runs" not in existing:
        return
    op.drop_index("ix_nova_ga_retention_org", table_name="nova_ga_retention_schedule_runs")
    op.drop_index("ix_nova_ga_retention_claim", table_name="nova_ga_retention_schedule_runs")
    op.drop_table("nova_ga_retention_schedule_runs")
