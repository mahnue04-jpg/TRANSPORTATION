"""Owner-scope scheduler unique period. V2 tables only. Not applied to production.

Revision ID: 20260918_nova_work_revenue_v2_owner_scheduler
Revises: 20260918_nova_work_revenue_v2_hardening
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260918_nova_work_revenue_v2_owner_scheduler"
down_revision = "20260918_nova_work_revenue_v2_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nova_work_scheduler_jobs" not in set(inspector.get_table_names()):
        return
    op.execute("DROP INDEX IF EXISTS ix_nova_work_sched_period")
    op.create_index(
        "ix_nova_work_sched_period",
        "nova_work_scheduler_jobs",
        ["organization_id", "owner_user_id", "job_kind", "period_key"],
        unique=True,
    )


def downgrade() -> None:
    # Do not revert to org-only uniqueness; that reintroduces owner collision.
    return
