"""Optional Growth campaign review table. Draft; no automatic activation.

Revision is additive and returns without DDL unless a future owner-approved
staging migration run explicitly sets NOVA_GA_CAMPAIGN_SCHEMA_APPROVED=true.
Production is always locked. Existing Growth/Studio tables remain untouched.
"""
from __future__ import annotations

import os

from alembic import op
import sqlalchemy as sa

revision = "20261118_nova_ga_campaign_review"
down_revision = "20261112_nova_ga_retention"
branch_labels = None
depends_on = None


def _approved() -> bool:
    if any(os.getenv(name, "").strip().lower() in {"prod", "production"}
           for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV")):
        return False
    return (
        os.getenv("NOVA_GA_CAMPAIGN_SCHEMA_APPROVED") == "true"
        and os.getenv("NOVA_GA_CAMPAIGN_SCHEMA_STAGING_ONLY") == "true"
    )


def upgrade() -> None:
    if not _approved():
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
