"""AI Approval Engine tables

Revision ID: 20260808_approval_engine
Revises: 20260731_driver_onboarding_s1
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260808_approval_engine"
down_revision = "20260731_driver_onboarding_s1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_engine_cases",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False, server_default="driver"),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("display_badge", sa.String(32), nullable=True),
        sa.Column("legal_name", sa.String(256), nullable=True),
        sa.Column("contact_phone", sa.String(32), nullable=True),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("age_verification_status", sa.String(32), nullable=True),
        sa.Column("license_number_masked", sa.String(64), nullable=True),
        sa.Column("license_state", sa.String(32), nullable=True),
        sa.Column("license_expiration", sa.Date(), nullable=True),
        sa.Column("license_verification_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("mvr_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("mvr_review_date", sa.Date(), nullable=True),
        sa.Column("mvr_next_review_due", sa.Date(), nullable=True),
        sa.Column("background_study_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("fingerprint_status", sa.String(32), nullable=False, server_default="NOT_REQUIRED"),
        sa.Column("medical_qualification_status", sa.String(32), nullable=True),
        sa.Column("behind_wheel_eval_status", sa.String(32), nullable=True),
        sa.Column("vehicle_ids_json", sa.Text(), nullable=True),
        sa.Column("vehicle_registration_status", sa.String(32), nullable=True),
        sa.Column("vehicle_registration_expiration", sa.Date(), nullable=True),
        sa.Column("insurance_status", sa.String(32), nullable=True),
        sa.Column("insurance_expiration", sa.Date(), nullable=True),
        sa.Column("inspection_status", sa.String(32), nullable=True),
        sa.Column("inspection_expiration", sa.Date(), nullable=True),
        sa.Column("approved_service_tiers_json", sa.Text(), nullable=True),
        sa.Column("requested_service_tiers_json", sa.Text(), nullable=True),
        sa.Column("contractor_agreement_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("w9_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("payout_setup_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("workflow_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("activation_status", sa.String(32), nullable=False, server_default="NOT_ACTIVE"),
        sa.Column("suspension_restriction_reason", sa.Text(), nullable=True),
        sa.Column("owner_approval_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("owner_approval_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_actor_id", sa.String(36), nullable=True),
        sa.Column("readiness_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("compliance_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("last_ai_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_required_action", sa.Text(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("platform_ops_application_id", sa.String(36), nullable=True),
        sa.Column("health_isf_driver_id", sa.String(36), nullable=True),
        sa.Column("health_isf_application_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_engine_cases_organization_id", "approval_engine_cases", ["organization_id"])
    op.create_index("ix_approval_engine_cases_workflow_status", "approval_engine_cases", ["workflow_status"])
    op.create_index("ix_approval_engine_cases_display_badge", "approval_engine_cases", ["display_badge"])
    op.create_index("ix_approval_cases_org_status", "approval_engine_cases", ["organization_id", "workflow_status"])
    op.create_index("ix_approval_cases_org_badge", "approval_engine_cases", ["organization_id", "display_badge"])
    op.create_index("ix_approval_engine_cases_platform_ops_application_id", "approval_engine_cases", ["platform_ops_application_id"])
    op.create_index("ix_approval_engine_cases_health_isf_driver_id", "approval_engine_cases", ["health_isf_driver_id"])

    op.create_table(
        "approval_engine_requirements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("requirement_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("service_tier", sa.String(64), nullable=False),
        sa.Column("timing", sa.String(64), nullable=False, server_default="required_before_activation"),
        sa.Column("traffic_light", sa.String(16), nullable=False, server_default="red"),
        sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_legal_block", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("expiration_date", sa.Date(), nullable=True),
        sa.Column("verification_source", sa.String(128), nullable=True),
        sa.Column("evidence_ref", sa.String(512), nullable=True),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_req_case_key", "approval_engine_requirements", ["case_id", "requirement_key"])

    op.create_table(
        "approval_engine_external_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("result_status", sa.String(32), nullable=True),
        sa.Column("result_actor_type", sa.String(16), nullable=True),
        sa.Column("result_actor_id", sa.String(36), nullable=True),
        sa.Column("evidence_ref", sa.String(512), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "approval_engine_training_modules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="assigned"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("evidence_ref", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_training_case_key", "approval_engine_training_modules", ["case_id", "module_key"])

    op.create_table(
        "approval_engine_vehicles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("approval_engine_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("health_isf_vehicle_id", sa.String(36), nullable=True),
        sa.Column("make", sa.String(64), nullable=True),
        sa.Column("model", sa.String(64), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("vin_ref", sa.String(128), nullable=True),
        sa.Column("registration_expiration", sa.Date(), nullable=True),
        sa.Column("insurance_expiration", sa.Date(), nullable=True),
        sa.Column("inspection_expiration", sa.Date(), nullable=True),
        sa.Column("service_capability", sa.String(64), nullable=False, server_default="AMBULATORY"),
        sa.Column("ambulatory_eligible", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("wheelchair_capable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("wheelchair_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vehicle_status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "approval_engine_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("approval_engine_cases.id", ondelete="SET NULL"), nullable=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("actor_type", sa.String(16), nullable=False, server_default="SYSTEM"),
        sa.Column("actor_id", sa.String(36), nullable=True),
        sa.Column("previous_status", sa.String(32), nullable=True),
        sa.Column("new_status", sa.String(32), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_ref", sa.String(512), nullable=True),
        sa.Column("approval_id", sa.String(36), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_audit_org_created", "approval_engine_audit_events", ["organization_id", "created_at"])
    op.create_index("ix_approval_audit_entity", "approval_engine_audit_events", ["entity_type", "entity_id"])


def downgrade() -> None:
    op.drop_table("approval_engine_audit_events")
    op.drop_table("approval_engine_vehicles")
    op.drop_table("approval_engine_training_modules")
    op.drop_table("approval_engine_external_tasks")
    op.drop_table("approval_engine_requirements")
    op.drop_table("approval_engine_cases")
