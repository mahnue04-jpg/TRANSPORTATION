"""Staging-only draft casting organization and membership tables.

Revision ID: 20261010_casting_org_draft
Revises: 20261009_nova_ws_transfer

Do not run in production. Migration creates no casting routes or users.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261010_casting_org_draft"
down_revision = "20261009_nova_ws_transfer"
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
        "nova_casting_organizations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("nova_tenant_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("verification_status", sa.String(12), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.UniqueConstraint("nova_tenant_id", "id", name="uq_nova_casting_org_tenant_id"),
        sa.CheckConstraint("verification_status IN ('PENDING', 'VERIFIED', 'REJECTED')", name="ck_nova_casting_org_verification"),
    )
    op.create_index("ix_nova_casting_organizations_nova_tenant_id", "nova_casting_organizations", ["nova_tenant_id"])
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
        sa.CheckConstraint("casting_role IN ('organizer', 'reviewer')", name="ck_nova_casting_membership_role"),
    )
    op.create_index("ix_nova_casting_membership_active_org", "nova_casting_memberships", ["organization_id", "active"])
    op.create_index("ix_nova_casting_membership_user", "nova_casting_memberships", ["user_id", "organization_id"])


def downgrade():
    if _production_schema_locked():
        return
    op.drop_index("ix_nova_casting_membership_user", table_name="nova_casting_memberships")
    op.drop_index("ix_nova_casting_membership_active_org", table_name="nova_casting_memberships")
    op.drop_table("nova_casting_memberships")
    op.drop_index("ix_nova_casting_organizations_nova_tenant_id", table_name="nova_casting_organizations")
    op.drop_table("nova_casting_organizations")
