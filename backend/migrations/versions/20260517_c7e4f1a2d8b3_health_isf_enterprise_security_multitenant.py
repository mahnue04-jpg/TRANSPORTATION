"""health_isf_enterprise_security_multitenant

Revision ID: c7e4f1a2d8b3
Revises: b9f4c2d1a901
Create Date: 2026-05-17 23:10:00.000000

Adds enterprise security and multi-tenant foundation tables/columns.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c7e4f1a2d8b3"
down_revision: Union[str, None] = "b9f4c2d1a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("platform_users", sa.Column("organization_id", sa.String(36), nullable=True))
    op.create_index("ix_platform_users_organization_id", "platform_users", ["organization_id"])

    op.create_table(
        "health_isf_security_audit_actions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("action_type", sa.String(64), nullable=False),
        sa.Column("target_user_id", sa.String(36), nullable=True),
        sa.Column("ride_id", sa.String(36), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["target_user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ride_id"], ["health_isf_rides.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_security_audit_actions_organization_id", "health_isf_security_audit_actions", ["organization_id"])
    op.create_index("ix_health_isf_security_audit_actions_actor_user_id", "health_isf_security_audit_actions", ["actor_user_id"])
    op.create_index("ix_health_isf_security_audit_actions_action_type", "health_isf_security_audit_actions", ["action_type"])
    op.create_index("ix_health_isf_security_audit_actions_target_user_id", "health_isf_security_audit_actions", ["target_user_id"])
    op.create_index("ix_health_isf_security_audit_actions_ride_id", "health_isf_security_audit_actions", ["ride_id"])
    op.create_index("ix_health_isf_security_audit_actions_created_at", "health_isf_security_audit_actions", ["created_at"])
    op.create_index("idx_sec_audit_org_created", "health_isf_security_audit_actions", ["organization_id", "created_at"])

    op.create_table(
        "health_isf_security_suspicious_activity",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=True),
        sa.Column("user_id", sa.String(36), nullable=True),
        sa.Column("activity_type", sa.String(64), nullable=False),
        sa.Column("source_ip", sa.String(64), nullable=True),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_security_suspicious_activity_organization_id", "health_isf_security_suspicious_activity", ["organization_id"])
    op.create_index("ix_health_isf_security_suspicious_activity_user_id", "health_isf_security_suspicious_activity", ["user_id"])
    op.create_index("ix_health_isf_security_suspicious_activity_activity_type", "health_isf_security_suspicious_activity", ["activity_type"])
    op.create_index("ix_health_isf_security_suspicious_activity_created_at", "health_isf_security_suspicious_activity", ["created_at"])


def downgrade() -> None:
    op.drop_table("health_isf_security_suspicious_activity")
    op.drop_table("health_isf_security_audit_actions")
    op.drop_index("ix_platform_users_organization_id", table_name="platform_users")
    op.drop_column("platform_users", "organization_id")
