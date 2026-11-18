"""Growth campaign review table (draft / prod-gated).

Additive only. Staging, dev, and disposable databases create the table.
Production is locked: when AMICOR_ENVIRONMENT, ENVIRONMENT, or APP_ENV is
production or prod, upgrade returns without DDL and Alembic stamps the
revision. Downgrade does not drop the table. Existing Growth/Studio tables
remain untouched.

DDL cannot wait on a later env-flag flip. Alembic records this revision as
soon as upgrade() returns, so a no-op on the first non-production run would
skip create_table forever.
"""
from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

revision = "20261118_nova_ga_campaign_review"
down_revision = "20261112_nova_ga_retention"
branch_labels = None
depends_on = None


def _production_schema_locked() -> bool:
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def upgrade() -> None:
    if _production_schema_locked():
        return
    bind = op.get_bind()
    if "nova_ga_campaign_asset_reviews" in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        "nova_ga_campaign_asset_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(128), nullable=False),
        sa.Column("studio_project_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
        sa.UniqueConstraint("organization_id", "campaign_id",
                            name="uq_nova_ga_campaign_org_ref"),
    )
    op.create_index(
        "ix_nova_ga_campaign_owner", "nova_ga_campaign_asset_reviews",
        ["organization_id", "owner_user_id", "created_at"],
    )


def downgrade() -> None:
    # Deliberately no destructive downgrade. Any removal would require a
    # separate backup+owner-approved deletion change.
    return
