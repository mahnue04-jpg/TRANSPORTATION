"""Growth Agent worker leases, shared rate limits, heartbeats (draft / prod-gated).

Revision ID: 20261112_nova_ga_worker
Revises: 20261112_nova_growth_agent

Additive only. Production-locked environments skip DDL.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261112_nova_ga_worker"
down_revision = "20261112_nova_growth_agent"
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


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)} if table in sa.inspect(bind).get_table_names() else set()
    return column in cols


def upgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    json_t = _json_type()

    if "nova_ga_delivery_attempts" in existing:
        if not _has_column("nova_ga_delivery_attempts", "max_attempts"):
            op.add_column(
                "nova_ga_delivery_attempts",
                sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            )
        if not _has_column("nova_ga_delivery_attempts", "claimed_by"):
            op.add_column("nova_ga_delivery_attempts", sa.Column("claimed_by", sa.String(80), nullable=True))
        if not _has_column("nova_ga_delivery_attempts", "claimed_at"):
            op.add_column("nova_ga_delivery_attempts", sa.Column("claimed_at", sa.DateTime(), nullable=True))
        if not _has_column("nova_ga_delivery_attempts", "lease_expires_at"):
            op.add_column("nova_ga_delivery_attempts", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
        if not _has_column("nova_ga_delivery_attempts", "available_at"):
            op.add_column("nova_ga_delivery_attempts", sa.Column("available_at", sa.DateTime(), nullable=True))

    if "nova_ga_rate_limit_counters" not in existing:
        op.create_table(
            "nova_ga_rate_limit_counters",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("bucket_key", sa.String(160), nullable=False),
            sa.Column("window_start", sa.Integer(), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint(
                "organization_id",
                "bucket_key",
                "window_start",
                name="uq_nova_ga_rate_org_bucket_window",
            ),
        )

    if "nova_ga_worker_heartbeats" not in existing:
        op.create_table(
            "nova_ga_worker_heartbeats",
            sa.Column("worker_id", sa.String(80), primary_key=True),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("jobs_claimed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("jobs_completed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("jobs_failed", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_beat_at", sa.DateTime(), nullable=False),
            sa.Column("meta_json", json_t, nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    if "nova_ga_worker_heartbeats" in existing:
        op.drop_table("nova_ga_worker_heartbeats")
    if "nova_ga_rate_limit_counters" in existing:
        op.drop_table("nova_ga_rate_limit_counters")
    if "nova_ga_delivery_attempts" in existing:
        for col in ("available_at", "lease_expires_at", "claimed_at", "claimed_by", "max_attempts"):
            if _has_column("nova_ga_delivery_attempts", col):
                op.drop_column("nova_ga_delivery_attempts", col)
