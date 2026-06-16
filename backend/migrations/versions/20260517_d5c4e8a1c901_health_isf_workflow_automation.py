"""health_isf_workflow_automation

Revision ID: d5c4e8a1c901
Revises: b9f4c2d1a901
Create Date: 2026-05-17 23:30:00.000000

Adds workflow policies, executions, incidents, escalations, and audit logs.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d5c4e8a1c901"
down_revision: Union[str, None] = "b9f4c2d1a901"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "health_isf_automation_policies",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("auto_reassign_enabled", sa.Boolean(), nullable=False),
        sa.Column("auto_escalation_enabled", sa.Boolean(), nullable=False),
        sa.Column("allow_replay", sa.Boolean(), nullable=False),
        sa.Column("max_retry_attempts", sa.Integer(), nullable=False),
        sa.Column("stuck_ride_minutes", sa.Integer(), nullable=False),
        sa.Column("delayed_pickup_minutes", sa.Integer(), nullable=False),
        sa.Column("escalation_minutes", sa.Integer(), nullable=False),
        sa.Column("policy_rules", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_automation_policies_organization_id", "health_isf_automation_policies", ["organization_id"])
    op.create_index("ix_health_isf_automation_policies_scope", "health_isf_automation_policies", ["scope"])
    op.create_index("ix_health_isf_automation_policies_is_enabled", "health_isf_automation_policies", ["is_enabled"])

    op.create_table(
        "health_isf_workflow_executions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workflow_name", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("ride_id", sa.String(36), nullable=True),
        sa.Column("driver_id", sa.String(36), nullable=True),
        sa.Column("policy_id", sa.String(36), nullable=True),
        sa.Column("input_payload", sa.Text(), nullable=True),
        sa.Column("output_payload", sa.Text(), nullable=True),
        sa.Column("error_message", sa.String(1024), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("created_by_user_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["driver_id"], ["health_isf_drivers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["policy_id"], ["health_isf_automation_policies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ride_id"], ["health_isf_rides.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_workflow_executions_organization_id", "health_isf_workflow_executions", ["organization_id"])
    op.create_index("ix_health_isf_workflow_executions_workflow_name", "health_isf_workflow_executions", ["workflow_name"])
    op.create_index("ix_health_isf_workflow_executions_status", "health_isf_workflow_executions", ["status"])
    op.create_index("ix_health_isf_workflow_executions_trigger_type", "health_isf_workflow_executions", ["trigger_type"])
    op.create_index("ix_health_isf_workflow_executions_ride_id", "health_isf_workflow_executions", ["ride_id"])
    op.create_index("ix_health_isf_workflow_executions_driver_id", "health_isf_workflow_executions", ["driver_id"])
    op.create_index("ix_health_isf_workflow_executions_policy_id", "health_isf_workflow_executions", ["policy_id"])
    op.create_index("idx_workflow_exec_org_updated", "health_isf_workflow_executions", ["organization_id", "updated_at"])
    op.create_index("idx_workflow_exec_org_status", "health_isf_workflow_executions", ["organization_id", "status"])

    op.create_table(
        "health_isf_workflow_incidents",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workflow_execution_id", sa.String(36), nullable=True),
        sa.Column("ride_id", sa.String(36), nullable=True),
        sa.Column("driver_id", sa.String(36), nullable=True),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(512), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["driver_id"], ["health_isf_drivers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ride_id"], ["health_isf_rides.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workflow_execution_id"], ["health_isf_workflow_executions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_workflow_incidents_organization_id", "health_isf_workflow_incidents", ["organization_id"])
    op.create_index("ix_health_isf_workflow_incidents_status", "health_isf_workflow_incidents", ["status"])
    op.create_index("ix_health_isf_workflow_incidents_incident_type", "health_isf_workflow_incidents", ["incident_type"])
    op.create_index("ix_health_isf_workflow_incidents_ride_id", "health_isf_workflow_incidents", ["ride_id"])
    op.create_index("ix_health_isf_workflow_incidents_driver_id", "health_isf_workflow_incidents", ["driver_id"])
    op.create_index("idx_workflow_incident_org_status", "health_isf_workflow_incidents", ["organization_id", "status"])
    op.create_index("idx_workflow_incident_org_created", "health_isf_workflow_incidents", ["organization_id", "created_at"])

    op.create_table(
        "health_isf_workflow_escalations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workflow_execution_id", sa.String(36), nullable=True),
        sa.Column("incident_id", sa.String(36), nullable=False),
        sa.Column("escalation_level", sa.Integer(), nullable=False),
        sa.Column("target_queue", sa.String(128), nullable=False),
        sa.Column("target_role", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("summary", sa.String(512), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["incident_id"], ["health_isf_workflow_incidents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_execution_id"], ["health_isf_workflow_executions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_workflow_escalations_organization_id", "health_isf_workflow_escalations", ["organization_id"])
    op.create_index("ix_health_isf_workflow_escalations_status", "health_isf_workflow_escalations", ["status"])
    op.create_index("ix_health_isf_workflow_escalations_incident_id", "health_isf_workflow_escalations", ["incident_id"])
    op.create_index("ix_health_isf_workflow_escalations_target_queue", "health_isf_workflow_escalations", ["target_queue"])
    op.create_index("ix_health_isf_workflow_escalations_target_role", "health_isf_workflow_escalations", ["target_role"])
    op.create_index("idx_workflow_escalation_org_status", "health_isf_workflow_escalations", ["organization_id", "status"])
    op.create_index("idx_workflow_escalation_org_created", "health_isf_workflow_escalations", ["organization_id", "created_at"])

    op.create_table(
        "health_isf_workflow_audit_logs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workflow_execution_id", sa.String(36), nullable=True),
        sa.Column("incident_id", sa.String(36), nullable=True),
        sa.Column("escalation_id", sa.String(36), nullable=True),
        sa.Column("event_type", sa.String(128), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["platform_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["escalation_id"], ["health_isf_workflow_escalations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["incident_id"], ["health_isf_workflow_incidents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["health_isf_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_execution_id"], ["health_isf_workflow_executions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_isf_workflow_audit_logs_organization_id", "health_isf_workflow_audit_logs", ["organization_id"])
    op.create_index("ix_health_isf_workflow_audit_logs_event_type", "health_isf_workflow_audit_logs", ["event_type"])
    op.create_index("ix_health_isf_workflow_audit_logs_actor_user_id", "health_isf_workflow_audit_logs", ["actor_user_id"])
    op.create_index("ix_health_isf_workflow_audit_logs_created_at", "health_isf_workflow_audit_logs", ["created_at"])
    op.create_index("idx_workflow_audit_org_created", "health_isf_workflow_audit_logs", ["organization_id", "created_at"])


def downgrade() -> None:
    op.drop_table("health_isf_workflow_audit_logs")
    op.drop_table("health_isf_workflow_escalations")
    op.drop_table("health_isf_workflow_incidents")
    op.drop_table("health_isf_workflow_executions")
    op.drop_table("health_isf_automation_policies")