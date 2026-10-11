"""Forward-only repair for casting revisions that stamped without DDL.

Revision ID: 20261011_casting_schema_repair
Revises: 20261010_casting_audit_consent

Production ``alembic upgrade heads`` records the earlier casting revisions and
returns before creating tables. This revision creates any missing casting tables
only outside production. It does not drop tables on downgrade and does not run
against a production environment.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261011_casting_schema_repair"
down_revision = "20261010_casting_audit_consent"
branch_labels = None
depends_on = None


def _production_schema_locked() -> bool:
    """Match casting_flags.casting_production_locked without importing the app."""
    import os
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def _exists(name: str) -> bool:
    return name in set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    if _production_schema_locked():
        return
    if not _exists("nova_casting_organizations"):
        op.create_table(
            "nova_casting_organizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("nova_tenant_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("verification_status", sa.String(12), nullable=False, server_default="PENDING"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.UniqueConstraint("nova_tenant_id", "id", name="uq_nova_casting_org_tenant_id"),
            sa.CheckConstraint(
                "verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')",
                name="ck_nova_casting_org_verification",
            ),
        )
        op.create_index(
            "ix_nova_casting_organizations_nova_tenant_id",
            "nova_casting_organizations",
            ["nova_tenant_id"],
        )
    if not _exists("nova_casting_memberships"):
        op.create_table(
            "nova_casting_memberships",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("nova_tenant_id", sa.String(36), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("casting_role", sa.String(16), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_nova_casting_org_user"),
            sa.ForeignKeyConstraint(
                ["nova_tenant_id", "organization_id"],
                ["nova_casting_organizations.nova_tenant_id", "nova_casting_organizations.id"],
                name="fk_nova_casting_member_tenant_org",
            ),
            sa.CheckConstraint(
                "casting_role IN ('organizer', 'reviewer')",
                name="ck_nova_casting_membership_role",
            ),
        )
        op.create_index(
            "ix_nova_casting_membership_active_org",
            "nova_casting_memberships",
            ["organization_id", "active"],
        )
        op.create_index(
            "ix_nova_casting_membership_user",
            "nova_casting_memberships",
            ["user_id", "organization_id"],
        )
    if not _exists("nova_casting_campaigns"):
        op.create_table(
            "nova_casting_campaigns",
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
            sa.CheckConstraint("minimum_age >= 18", name="ck_nova_casting_campaign_minimum_age"),
        )
        op.create_index("ix_nova_casting_campaign_owner", "nova_casting_campaigns", ["owner_id", "created_at"])
    if not _exists("nova_casting_applications"):
        op.create_table(
            "nova_casting_applications",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("campaign_id", sa.String(48), sa.ForeignKey("nova_casting_campaigns.id"), nullable=False),
            sa.Column("applicant_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("consent_version", sa.String(32), nullable=True),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id", "campaign_id"],
                ["nova_casting_campaigns.owner_id", "nova_casting_campaigns.id"],
                name="fk_nova_casting_application_campaign_owner",
            ),
            sa.UniqueConstraint("owner_id", "id", name="uq_nova_casting_application_owner_id"),
            sa.UniqueConstraint("campaign_id", "applicant_id", name="uq_nova_casting_campaign_applicant"),
            sa.CheckConstraint(
                "status IN ('DRAFT', 'SUBMITTED', 'WITHDRAWN')",
                name="ck_nova_casting_application_status",
            ),
        )
        op.create_index(
            "ix_nova_casting_application_owner",
            "nova_casting_applications",
            ["owner_id", "campaign_id"],
        )
    if not _exists("nova_casting_reviews"):
        op.create_table(
            "nova_casting_reviews",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("application_id", sa.String(48), sa.ForeignKey("nova_casting_applications.id"), nullable=False),
            sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("stage", sa.String(16), nullable=False, server_default="New"),
            sa.Column("score", sa.Integer(), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id", "application_id"],
                ["nova_casting_applications.owner_id", "nova_casting_applications.id"],
                name="fk_nova_casting_review_application_owner",
            ),
            sa.UniqueConstraint("application_id", "reviewer_id", name="uq_nova_casting_application_reviewer"),
            sa.CheckConstraint("score IS NULL OR (score >= 1 AND score <= 5)", name="ck_nova_casting_review_score"),
            sa.CheckConstraint(
                "stage IN ('New', 'In review', 'Callback', 'Closed')",
                name="ck_nova_casting_review_stage",
            ),
        )
        op.create_index("ix_nova_casting_review_owner", "nova_casting_reviews", ["owner_id", "application_id"])
    if not _exists("nova_casting_media"):
        op.create_table(
            "nova_casting_media",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("application_id", sa.String(48), sa.ForeignKey("nova_casting_applications.id"), nullable=False),
            sa.Column("storage_key", sa.String(300), nullable=False),
            sa.Column("mime_type", sa.String(80), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id", "application_id"],
                ["nova_casting_applications.owner_id", "nova_casting_applications.id"],
                name="fk_nova_casting_media_application_owner",
            ),
            sa.CheckConstraint(
                "status IN ('PENDING', 'QUARANTINED', 'CLEAN', 'REJECTED')",
                name="ck_nova_casting_media_status",
            ),
            sa.CheckConstraint("byte_size > 0 AND byte_size <= 262144000", name="ck_nova_casting_media_size"),
            sa.CheckConstraint(
                "mime_type IN ('video/mp4', 'video/quicktime', 'video/webm')",
                name="ck_nova_casting_media_mime",
            ),
        )
        op.create_index(
            "ix_nova_casting_media_owner_application",
            "nova_casting_media",
            ["owner_id", "application_id"],
        )
    if not _exists("nova_casting_consent_events"):
        op.create_table(
            "nova_casting_consent_events",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("application_id", sa.String(48), nullable=False),
            sa.Column("applicant_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("consent_version", sa.String(32), nullable=False),
            sa.Column("minimum_age_attested", sa.Integer(), nullable=False),
            sa.Column("accepted", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.ForeignKeyConstraint(
                ["owner_id", "application_id"],
                ["nova_casting_applications.owner_id", "nova_casting_applications.id"],
                name="fk_nova_casting_consent_application_owner",
            ),
            sa.CheckConstraint("minimum_age_attested >= 18", name="ck_nova_casting_consent_minimum_age"),
            sa.CheckConstraint("accepted = true", name="ck_nova_casting_consent_accepted"),
            sa.CheckConstraint("length(consent_version) > 0", name="ck_nova_casting_consent_version"),
        )
        op.create_index(
            "ix_nova_casting_consent_application",
            "nova_casting_consent_events",
            ["owner_id", "application_id"],
        )
    if not _exists("nova_casting_audit_events"):
        op.create_table(
            "nova_casting_audit_events",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("actor_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("object_id", sa.String(48), nullable=False),
            sa.Column("occurred_at", sa.String(64), nullable=False),
            sa.CheckConstraint(
                "action IN ('campaign.created', 'application.submitted', 'application.withdrawn', "
                "'review.updated', 'callback.proposed', 'media.quarantined', 'media.approved')",
                name="ck_nova_casting_audit_action",
            ),
        )
        op.create_index(
            "ix_nova_casting_audit_organization",
            "nova_casting_audit_events",
            ["organization_id", "occurred_at"],
        )


def downgrade():
    """Forward-only. Earlier revisions own table removal outside production."""
    return
