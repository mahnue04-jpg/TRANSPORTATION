"""Lifesaver AI Care Cloud V1 Phase 1 schema.

Revision ID: 20260911_lifesaver_phase1_schema
Revises: 20260909_nova_freight_settlement

Scope:
    Additive creation of Phase 1 lifesaver_* tables only. These tables were
    previously created at runtime by ensure_lifesaver_schema() and were never
    recorded in Alembic history.

Safety:
    - Lifesaver-only table names
    - Inspector-guarded create (no-op if a local/runtime table already exists)
    - No foreign keys to Health ISF, Nova, Delivery, Freight, or Stripe
    - No data rewrite
    - Downgrade drops only lifesaver_* Phase 1 tables created here

Do not apply this revision to production from this closeout. Prepare only.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_lifesaver_phase1_schema"
down_revision = "20260909_nova_freight_settlement"
branch_labels = None
depends_on = None


def _names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if table not in set(inspector.get_table_names()):
        return set()
    return {item["name"] for item in inspector.get_indexes(table) if item.get("name")}


def _create_index(name: str, table: str, columns: list[str], unique: bool = False) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    names = _names()

    if "lifesaver_profiles" not in names:
        op.create_table(
            "lifesaver_profiles",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False),
            sa.Column("display_name", sa.String(128), nullable=True),
            sa.Column("profile_role", sa.String(32), nullable=False, server_default="member"),
            sa.Column("timezone", sa.String(64), nullable=False, server_default="America/Chicago"),
            sa.Column("locale", sa.String(16), nullable=False, server_default="en"),
            sa.Column("accessibility_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("organization_id", "user_id", name="uq_lifesaver_profile_org_user"),
        )
        _create_index("ix_lifesaver_profiles_organization_id", "lifesaver_profiles", ["organization_id"])
        _create_index("ix_lifesaver_profiles_user_id", "lifesaver_profiles", ["user_id"])
        _create_index("ix_lifesaver_profiles_created_at", "lifesaver_profiles", ["created_at"])
        _create_index("ix_lifesaver_profiles_org_role", "lifesaver_profiles", ["organization_id", "profile_role"])

    if "lifesaver_consents" not in names:
        op.create_table(
            "lifesaver_consents",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("consent_type", sa.String(64), nullable=False),
            sa.Column("granted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("version", sa.String(32), nullable=False),
            sa.Column("actor_user_id", sa.String(36), nullable=False),
            sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("profile_id", "consent_type", name="uq_lifesaver_consent_profile_type"),
        )
        _create_index("ix_lifesaver_consents_organization_id", "lifesaver_consents", ["organization_id"])
        _create_index("ix_lifesaver_consents_profile_id", "lifesaver_consents", ["profile_id"])
        _create_index("ix_lifesaver_consents_org_profile", "lifesaver_consents", ["organization_id", "profile_id"])

    if "lifesaver_care_circle_members" not in names:
        op.create_table(
            "lifesaver_care_circle_members",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("member_profile_id", sa.String(36), nullable=False),
            sa.Column("caregiver_profile_id", sa.String(36), nullable=False),
            sa.Column("caregiver_user_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="invited"),
            sa.Column("permissions_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("invited_by_user_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("member_profile_id", "caregiver_profile_id", name="uq_lifesaver_circle_pair"),
        )
        _create_index("ix_lifesaver_circle_organization_id", "lifesaver_care_circle_members", ["organization_id"])
        _create_index("ix_lifesaver_circle_member_profile_id", "lifesaver_care_circle_members", ["member_profile_id"])
        _create_index("ix_lifesaver_circle_caregiver_profile_id", "lifesaver_care_circle_members", ["caregiver_profile_id"])
        _create_index("ix_lifesaver_circle_caregiver_user_id", "lifesaver_care_circle_members", ["caregiver_user_id"])
        _create_index("ix_lifesaver_circle_org_member", "lifesaver_care_circle_members", ["organization_id", "member_profile_id"])
        _create_index("ix_lifesaver_circle_org_caregiver", "lifesaver_care_circle_members", ["organization_id", "caregiver_profile_id"])

    if "lifesaver_medications" not in names:
        op.create_table(
            "lifesaver_medications",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("instructions", sa.String(512), nullable=True),
            sa.Column("schedule_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_meds_organization_id", "lifesaver_medications", ["organization_id"])
        _create_index("ix_lifesaver_meds_profile_id", "lifesaver_medications", ["profile_id"])
        _create_index("ix_lifesaver_meds_org_profile", "lifesaver_medications", ["organization_id", "profile_id"])

    if "lifesaver_reminders" not in names:
        op.create_table(
            "lifesaver_reminders",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("kind", sa.String(32), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="scheduled"),
            sa.Column("source_type", sa.String(32), nullable=True),
            sa.Column("source_id", sa.String(36), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_reminders_organization_id", "lifesaver_reminders", ["organization_id"])
        _create_index("ix_lifesaver_reminders_profile_id", "lifesaver_reminders", ["profile_id"])
        _create_index("ix_lifesaver_reminders_due_at", "lifesaver_reminders", ["due_at"])
        _create_index("ix_lifesaver_reminders_status", "lifesaver_reminders", ["status"])
        _create_index("ix_lifesaver_reminders_org_profile_due", "lifesaver_reminders", ["organization_id", "profile_id", "due_at"])

    if "lifesaver_appointments" not in names:
        op.create_table(
            "lifesaver_appointments",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("location", sa.String(256), nullable=True),
            sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("notes", sa.String(512), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="scheduled"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_appts_organization_id", "lifesaver_appointments", ["organization_id"])
        _create_index("ix_lifesaver_appts_profile_id", "lifesaver_appointments", ["profile_id"])
        _create_index("ix_lifesaver_appts_starts_at", "lifesaver_appointments", ["starts_at"])
        _create_index("ix_lifesaver_appts_org_profile", "lifesaver_appointments", ["organization_id", "profile_id"])

    if "lifesaver_wellness_checkins" not in names:
        op.create_table(
            "lifesaver_wellness_checkins",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("mood", sa.String(32), nullable=False),
            sa.Column("energy", sa.String(32), nullable=False),
            sa.Column("notes", sa.String(512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_wellness_organization_id", "lifesaver_wellness_checkins", ["organization_id"])
        _create_index("ix_lifesaver_wellness_profile_id", "lifesaver_wellness_checkins", ["profile_id"])
        _create_index("ix_lifesaver_wellness_created_at", "lifesaver_wellness_checkins", ["created_at"])
        _create_index("ix_lifesaver_wellness_org_profile", "lifesaver_wellness_checkins", ["organization_id", "profile_id"])

    if "lifesaver_journal_entries" not in names:
        op.create_table(
            "lifesaver_journal_entries",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_journal_organization_id", "lifesaver_journal_entries", ["organization_id"])
        _create_index("ix_lifesaver_journal_profile_id", "lifesaver_journal_entries", ["profile_id"])
        _create_index("ix_lifesaver_journal_created_at", "lifesaver_journal_entries", ["created_at"])
        _create_index("ix_lifesaver_journal_org_profile", "lifesaver_journal_entries", ["organization_id", "profile_id"])

    if "lifesaver_health_readings" not in names:
        op.create_table(
            "lifesaver_health_readings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("reading_type", sa.String(32), nullable=False),
            sa.Column("value_primary", sa.Float(), nullable=False),
            sa.Column("value_secondary", sa.Float(), nullable=True),
            sa.Column("unit", sa.String(32), nullable=False),
            sa.Column("source", sa.String(32), nullable=False, server_default="user_entered"),
            sa.Column("note", sa.String(256), nullable=True),
            sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_readings_organization_id", "lifesaver_health_readings", ["organization_id"])
        _create_index("ix_lifesaver_readings_profile_id", "lifesaver_health_readings", ["profile_id"])
        _create_index("ix_lifesaver_readings_recorded_at", "lifesaver_health_readings", ["recorded_at"])
        _create_index(
            "ix_lifesaver_readings_org_profile_type",
            "lifesaver_health_readings",
            ["organization_id", "profile_id", "reading_type"],
        )

    if "lifesaver_transport_connections" not in names:
        op.create_table(
            "lifesaver_transport_connections",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="not_connected"),
            sa.Column("status_text", sa.String(256), nullable=False, server_default="Not connected"),
            sa.Column("external_reference", sa.String(64), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.UniqueConstraint("organization_id", "profile_id", name="uq_lifesaver_transport_profile"),
        )
        _create_index("ix_lifesaver_tconn_organization_id", "lifesaver_transport_connections", ["organization_id"])
        _create_index("ix_lifesaver_tconn_profile_id", "lifesaver_transport_connections", ["profile_id"])

    if "lifesaver_sos_demonstrations" not in names:
        op.create_table(
            "lifesaver_sos_demonstrations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("note", sa.String(256), nullable=True),
            sa.Column("confirmed_by_user_id", sa.String(36), nullable=True),
            sa.Column("acknowledged_by_user_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        )
        _create_index("ix_lifesaver_sos_organization_id", "lifesaver_sos_demonstrations", ["organization_id"])
        _create_index("ix_lifesaver_sos_profile_id", "lifesaver_sos_demonstrations", ["profile_id"])
        _create_index("ix_lifesaver_sos_org_profile", "lifesaver_sos_demonstrations", ["organization_id", "profile_id"])

    if "lifesaver_alerts" not in names:
        op.create_table(
            "lifesaver_alerts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("member_profile_id", sa.String(36), nullable=False),
            sa.Column("caregiver_profile_id", sa.String(36), nullable=True),
            sa.Column("alert_type", sa.String(32), nullable=False),
            sa.Column("severity", sa.String(32), nullable=False, server_default="info"),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("message", sa.String(512), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="open"),
            sa.Column("requires_ack", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("acknowledged_by_user_id", sa.String(36), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_alerts_organization_id", "lifesaver_alerts", ["organization_id"])
        _create_index("ix_lifesaver_alerts_member_profile_id", "lifesaver_alerts", ["member_profile_id"])
        _create_index("ix_lifesaver_alerts_caregiver_profile_id", "lifesaver_alerts", ["caregiver_profile_id"])
        _create_index("ix_lifesaver_alerts_created_at", "lifesaver_alerts", ["created_at"])
        _create_index(
            "ix_lifesaver_alerts_org_caregiver",
            "lifesaver_alerts",
            ["organization_id", "caregiver_profile_id", "status"],
        )

    if "lifesaver_handoffs" not in names:
        op.create_table(
            "lifesaver_handoffs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("member_profile_id", sa.String(36), nullable=False),
            sa.Column("from_caregiver_id", sa.String(36), nullable=False),
            sa.Column("to_caregiver_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("note", sa.String(256), nullable=True),
            sa.Column("created_by_user_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        _create_index("ix_lifesaver_handoffs_organization_id", "lifesaver_handoffs", ["organization_id"])
        _create_index("ix_lifesaver_handoffs_member_profile_id", "lifesaver_handoffs", ["member_profile_id"])
        _create_index("ix_lifesaver_handoffs_org_member", "lifesaver_handoffs", ["organization_id", "member_profile_id"])

    if "lifesaver_care_tasks" not in names:
        op.create_table(
            "lifesaver_care_tasks",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("member_profile_id", sa.String(36), nullable=False),
            sa.Column("assigned_caregiver_id", sa.String(36), nullable=True),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="open"),
            sa.Column("created_by_user_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_tasks_organization_id", "lifesaver_care_tasks", ["organization_id"])
        _create_index("ix_lifesaver_tasks_member_profile_id", "lifesaver_care_tasks", ["member_profile_id"])
        _create_index("ix_lifesaver_tasks_org_member", "lifesaver_care_tasks", ["organization_id", "member_profile_id"])

    if "lifesaver_conversations" not in names:
        op.create_table(
            "lifesaver_conversations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_conv_organization_id", "lifesaver_conversations", ["organization_id"])
        _create_index("ix_lifesaver_conv_profile_id", "lifesaver_conversations", ["profile_id"])
        _create_index("ix_lifesaver_conv_org_profile", "lifesaver_conversations", ["organization_id", "profile_id"])

    if "lifesaver_conversation_messages" not in names:
        op.create_table(
            "lifesaver_conversation_messages",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("conversation_id", sa.String(36), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_messages_organization_id", "lifesaver_conversation_messages", ["organization_id"])
        _create_index("ix_lifesaver_messages_conversation_id", "lifesaver_conversation_messages", ["conversation_id"])
        _create_index("ix_lifesaver_messages_profile_id", "lifesaver_conversation_messages", ["profile_id"])
        _create_index("ix_lifesaver_messages_conv", "lifesaver_conversation_messages", ["conversation_id", "created_at"])

    if "lifesaver_audit_events" not in names:
        op.create_table(
            "lifesaver_audit_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("actor_user_id", sa.String(36), nullable=False),
            sa.Column("actor_profile_id", sa.String(36), nullable=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("resource_type", sa.String(64), nullable=False),
            sa.Column("resource_id", sa.String(36), nullable=True),
            sa.Column("outcome", sa.String(16), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_audit_organization_id", "lifesaver_audit_events", ["organization_id"])
        _create_index("ix_lifesaver_audit_actor_user_id", "lifesaver_audit_events", ["actor_user_id"])
        _create_index("ix_lifesaver_audit_action", "lifesaver_audit_events", ["action"])
        _create_index("ix_lifesaver_audit_created_at", "lifesaver_audit_events", ["created_at"])
        _create_index(
            "ix_lifesaver_audit_org_actor",
            "lifesaver_audit_events",
            ["organization_id", "actor_user_id", "created_at"],
        )


def downgrade() -> None:
    """Drop Phase 1 lifesaver_* tables only. No Health ISF / Nova / Delivery tables."""
    names = _names()
    for table in (
        "lifesaver_audit_events",
        "lifesaver_conversation_messages",
        "lifesaver_conversations",
        "lifesaver_care_tasks",
        "lifesaver_handoffs",
        "lifesaver_alerts",
        "lifesaver_sos_demonstrations",
        "lifesaver_transport_connections",
        "lifesaver_health_readings",
        "lifesaver_journal_entries",
        "lifesaver_wellness_checkins",
        "lifesaver_appointments",
        "lifesaver_reminders",
        "lifesaver_medications",
        "lifesaver_care_circle_members",
        "lifesaver_consents",
        "lifesaver_profiles",
    ):
        if table in names:
            op.drop_table(table)
