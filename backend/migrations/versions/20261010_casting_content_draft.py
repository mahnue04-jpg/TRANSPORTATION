"""Draft casting application/review/media migration — staging review only.

Revision ID: 20261010_casting_content_draft
Revises: 20261010_casting_org_draft
"""
from alembic import op
import sqlalchemy as sa

revision = "20261010_casting_content_draft"
down_revision = "20261010_casting_org_draft"
branch_labels = None
depends_on = None


def _production_schema_locked() -> bool:
    """Match casting_flags.casting_production_locked without importing the app."""
    import os
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def upgrade():
    if _production_schema_locked():
        return
    op.create_table("nova_casting_campaigns",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("minimum_age", sa.Integer(), nullable=False, server_default="18"),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.UniqueConstraint("owner_id", "id", name="uq_nova_casting_campaign_owner_id"),
        sa.CheckConstraint("category IN ('reality', 'beauty', 'film')", name="ck_nova_casting_category"),
        sa.CheckConstraint("status IN ('DRAFT', 'CLOSED')", name="ck_nova_casting_campaign_status"),
        sa.CheckConstraint("minimum_age >= 18", name="ck_nova_casting_campaign_minimum_age"))
    op.create_index("ix_nova_casting_campaign_owner", "nova_casting_campaigns", ["owner_id", "created_at"])
    op.create_table("nova_casting_applications",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(48), sa.ForeignKey("nova_casting_campaigns.id"), nullable=False),
        sa.Column("applicant_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
        sa.Column("consent_version", sa.String(32), nullable=True),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["owner_id", "campaign_id"], ["nova_casting_campaigns.owner_id", "nova_casting_campaigns.id"], name="fk_nova_casting_application_campaign_owner"),
        sa.UniqueConstraint("owner_id", "id", name="uq_nova_casting_application_owner_id"),
        sa.UniqueConstraint("campaign_id", "applicant_id", name="uq_nova_casting_campaign_applicant"),
        sa.CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'WITHDRAWN')", name="ck_nova_casting_application_status"))
    op.create_index("ix_nova_casting_application_owner", "nova_casting_applications", ["owner_id", "campaign_id"])
    op.create_table("nova_casting_reviews",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(48), sa.ForeignKey("nova_casting_applications.id"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False, server_default="New"),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["owner_id", "application_id"], ["nova_casting_applications.owner_id", "nova_casting_applications.id"], name="fk_nova_casting_review_application_owner"),
        sa.UniqueConstraint("application_id", "reviewer_id", name="uq_nova_casting_application_reviewer"),
        sa.CheckConstraint("score IS NULL OR (score >= 1 AND score <= 5)", name="ck_nova_casting_review_score"),
        sa.CheckConstraint("stage IN ('New', 'In review', 'Callback', 'Closed')", name="ck_nova_casting_review_stage"))
    op.create_index("ix_nova_casting_review_owner", "nova_casting_reviews", ["owner_id", "application_id"])
    op.create_table("nova_casting_media",
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(48), sa.ForeignKey("nova_casting_applications.id"), nullable=False),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("mime_type", sa.String(80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["owner_id", "application_id"], ["nova_casting_applications.owner_id", "nova_casting_applications.id"], name="fk_nova_casting_media_application_owner"),
        sa.CheckConstraint("status IN ('PENDING', 'QUARANTINED', 'CLEAN', 'REJECTED')", name="ck_nova_casting_media_status"),
        sa.CheckConstraint("byte_size > 0 AND byte_size <= 262144000", name="ck_nova_casting_media_size"),
        sa.CheckConstraint("mime_type IN ('video/mp4', 'video/quicktime', 'video/webm')", name="ck_nova_casting_media_mime"))
    op.create_index("ix_nova_casting_media_owner_application", "nova_casting_media", ["owner_id", "application_id"])


def downgrade():
    if _production_schema_locked():
        return
    op.drop_index("ix_nova_casting_media_owner_application", table_name="nova_casting_media")
    op.drop_table("nova_casting_media")
    op.drop_index("ix_nova_casting_review_owner", table_name="nova_casting_reviews")
    op.drop_table("nova_casting_reviews")
    op.drop_index("ix_nova_casting_application_owner", table_name="nova_casting_applications")
    op.drop_table("nova_casting_applications")
    op.drop_index("ix_nova_casting_campaign_owner", table_name="nova_casting_campaigns")
    op.drop_table("nova_casting_campaigns")
