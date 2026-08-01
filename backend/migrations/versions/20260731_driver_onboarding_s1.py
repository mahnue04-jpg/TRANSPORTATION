"""platform_ops driver onboarding tables

Revision ID: 20260731_driver_onboarding_s1
Revises: 20260729_advance_scheduling
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260731_driver_onboarding_s1"
down_revision = "20260729_advance_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "platform_driver_onboarding_applications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="draft"),
        sa.Column("status_reason", sa.String(length=512), nullable=True),
        sa.Column("legal_first_name", sa.String(length=128), nullable=True),
        sa.Column("legal_middle_name", sa.String(length=128), nullable=True),
        sa.Column("legal_last_name", sa.String(length=128), nullable=True),
        sa.Column("date_of_birth", sa.Date(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("mobile_phone", sa.String(length=32), nullable=True),
        sa.Column("home_address", sa.String(length=256), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=True),
        sa.Column("zip_code", sa.String(length=16), nullable=True),
        sa.Column("emergency_contact_name", sa.String(length=128), nullable=True),
        sa.Column("emergency_contact_phone", sa.String(length=32), nullable=True),
        sa.Column("preferred_language", sa.String(length=64), nullable=True),
        sa.Column("drivers_license_number", sa.String(length=64), nullable=True),
        sa.Column("license_issuing_state", sa.String(length=32), nullable=True),
        sa.Column("license_expiration_date", sa.Date(), nullable=True),
        sa.Column("years_driving_experience", sa.Integer(), nullable=True),
        sa.Column("employment_type", sa.String(length=32), nullable=True),
        sa.Column("availability_days_json", sa.Text(), nullable=True),
        sa.Column("availability_start_time", sa.String(length=8), nullable=True),
        sa.Column("availability_end_time", sa.String(length=8), nullable=True),
        sa.Column("willing_weekends", sa.Boolean(), nullable=True),
        sa.Column("willing_wheelchair", sa.Boolean(), nullable=True),
        sa.Column("service_area_counties", sa.Text(), nullable=True),
        sa.Column("declaration_valid_license", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("declaration_mvr_authorization", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("declaration_background_authorization", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("declaration_drug_alcohol_policy", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("declaration_truthful_information", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("electronic_signature", sa.String(length=256), nullable=True),
        sa.Column("signed_date", sa.Date(), nullable=True),
        sa.Column("assigned_reviewer_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column("applicant_access_token_hash", sa.String(length=128), nullable=True),
        sa.Column("activated_driver_id", sa.String(length=36), nullable=True),
        sa.Column("onboarding_gate_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_driver_onboarding_org_status", "platform_driver_onboarding_applications", ["organization_id", "status"])
    op.create_index("ix_platform_driver_onboarding_applications_organization_id", "platform_driver_onboarding_applications", ["organization_id"])
    op.create_index("ix_platform_driver_onboarding_applications_status", "platform_driver_onboarding_applications", ["status"])
    op.create_index("ix_platform_driver_onboarding_applications_email", "platform_driver_onboarding_applications", ["email"])
    op.create_index("ix_platform_driver_onboarding_applications_mobile_phone", "platform_driver_onboarding_applications", ["mobile_phone"])
    op.create_index("ix_platform_driver_onboarding_applications_assigned_reviewer_id", "platform_driver_onboarding_applications", ["assigned_reviewer_id"])
    op.create_index("ix_platform_driver_onboarding_applications_applicant_access_token_hash", "platform_driver_onboarding_applications", ["applicant_access_token_hash"])
    op.create_index("ix_platform_driver_onboarding_applications_activated_driver_id", "platform_driver_onboarding_applications", ["activated_driver_id"])

    op.create_table(
        "platform_driver_onboarding_documents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("platform_driver_onboarding_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("storage_backend", sa.String(length=32), nullable=False, server_default="local_dev"),
        sa.Column("storage_ref", sa.String(length=512), nullable=True),
        sa.Column("original_filename", sa.String(length=256), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("review_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.Date(), nullable=True),
        sa.Column("status_only_value", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_driver_onboarding_documents_application_id", "platform_driver_onboarding_documents", ["application_id"])
    op.create_index("ix_platform_driver_onboarding_documents_organization_id", "platform_driver_onboarding_documents", ["organization_id"])
    op.create_index("ix_platform_driver_onboarding_documents_category", "platform_driver_onboarding_documents", ["category"])
    op.create_index("ix_platform_driver_onboarding_doc_app_cat", "platform_driver_onboarding_documents", ["application_id", "category"])

    op.create_table(
        "platform_driver_onboarding_audit_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("platform_driver_onboarding_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=True),
        sa.Column("to_status", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_driver_onboarding_audit_events_application_id", "platform_driver_onboarding_audit_events", ["application_id"])
    op.create_index("ix_platform_driver_onboarding_audit_events_organization_id", "platform_driver_onboarding_audit_events", ["organization_id"])
    op.create_index("ix_platform_driver_onboarding_audit_events_event_type", "platform_driver_onboarding_audit_events", ["event_type"])

    op.create_table(
        "platform_driver_onboarding_internal_notes",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("application_id", sa.String(length=36), sa.ForeignKey("platform_driver_onboarding_applications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("author_user_id", sa.String(length=36), nullable=False),
        sa.Column("note_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_platform_driver_onboarding_internal_notes_application_id", "platform_driver_onboarding_internal_notes", ["application_id"])


def downgrade() -> None:
    op.drop_table("platform_driver_onboarding_internal_notes")
    op.drop_table("platform_driver_onboarding_audit_events")
    op.drop_table("platform_driver_onboarding_documents")
    op.drop_table("platform_driver_onboarding_applications")
