"""Draft casting consent and audit tables — staging review only.

Revision ID: 20261010_casting_audit_consent
Revises: 20261010_casting_content_draft

No applicant names, contact details, dates of birth, or media object keys.
Production environments record this revision without creating tables.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261010_casting_audit_consent"
down_revision = "20261010_casting_content_draft"
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
    if _production_schema_locked():
        return
    op.drop_index("ix_nova_casting_audit_organization", table_name="nova_casting_audit_events")
    op.drop_table("nova_casting_audit_events")
    op.drop_index("ix_nova_casting_consent_application", table_name="nova_casting_consent_events")
    op.drop_table("nova_casting_consent_events")
