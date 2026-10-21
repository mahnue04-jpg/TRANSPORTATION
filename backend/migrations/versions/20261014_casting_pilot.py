"""Sandbox tables for Casting pilot intake, review, and unsent messages.

Revision ID: 20261014_casting_pilot
Revises: 20261012_casting_org_name

Safe plan, dev and disposable databases only:

- Production and prod environment names return without DDL. ``alembic upgrade
  heads`` on production only stamps the revision.
- If the casting organization, campaign, or platform user tables are absent,
  upgrade returns. It does not create those tables and it does not enable
  public intake.
- Downgrade drops only the pilot tables. It does not drop campaigns,
  applications, media, consent, or audit rows from the earlier casting revisions.
- Message rows cannot record a sent delivery. ``delivery_state`` is constrained
  to ``not_sent``.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261014_casting_pilot"
down_revision = "20261012_casting_org_name"
branch_labels = None
depends_on = None

_PILOT_TABLES = (
    "nova_casting_rubrics",
    "nova_casting_schedules",
    "nova_casting_intakes",
    "nova_casting_pilot_messages",
    "nova_casting_suppressions",
    "nova_casting_pilot_audit",
    "nova_casting_roles",
)
_PARENTS = ("platform_users", "nova_casting_organizations", "nova_casting_campaigns")


def _production_schema_locked() -> bool:
    import os
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def _names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    present = _names(bind)
    if any(name not in present for name in _PARENTS):
        return
    if "nova_casting_roles" not in present:
        op.create_table(
            "nova_casting_roles",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
            sa.Column("campaign_id", sa.String(48), sa.ForeignKey("nova_casting_campaigns.id"), nullable=False),
            sa.Column("title", sa.String(80), nullable=False),
            sa.Column("requirements", sa.Text(), nullable=False, server_default=""),
            sa.Column("deadline", sa.String(64), nullable=False),
            sa.Column("questions_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("minimum_age", sa.Integer(), nullable=False, server_default="18"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.CheckConstraint("minimum_age >= 18", name="ck_nova_casting_role_minimum_age"),
            sa.CheckConstraint("length(title) > 0", name="ck_nova_casting_role_title"),
        )
        op.create_index("ix_nova_casting_role_campaign", "nova_casting_roles", ["organization_id", "campaign_id"])
    if "nova_casting_intakes" not in present:
        op.create_table(
            "nova_casting_intakes",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
            sa.Column("campaign_id", sa.String(48), sa.ForeignKey("nova_casting_campaigns.id"), nullable=False),
            sa.Column("role_id", sa.String(48), sa.ForeignKey("nova_casting_roles.id"), nullable=False),
            sa.Column("applicant_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("display_name", sa.String(80), nullable=False, server_default=""),
            sa.Column("contact_email", sa.String(320), nullable=False, server_default=""),
            sa.Column("video_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("answers_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("age_years", sa.Integer(), nullable=False),
            sa.Column("consent_version", sa.String(32), nullable=False),
            sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
            sa.Column("consent_expires_at", sa.String(64), nullable=False),
            sa.Column("consent_revoked_at", sa.String(64), nullable=False, server_default=""),
            sa.Column("receipt", sa.String(16), nullable=False),
            sa.Column("status", sa.String(12), nullable=False, server_default="DRAFT"),
            sa.Column("stage", sa.String(16), nullable=False, server_default="New"),
            sa.Column("shortlisted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("minimized", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'WITHDRAWN')", name="ck_nova_casting_intake_status"),
            sa.CheckConstraint("stage IN ('New', 'In review', 'Callback', 'Closed')", name="ck_nova_casting_intake_stage"),
            sa.CheckConstraint("retention_days >= 1 AND retention_days <= 365", name="ck_nova_casting_intake_retention"),
            sa.CheckConstraint("age_years >= 18", name="ck_nova_casting_intake_age"),
        )
        op.create_index("ix_nova_casting_intake_org", "nova_casting_intakes", ["organization_id", "campaign_id"])
    if "nova_casting_rubrics" not in present:
        op.create_table(
            "nova_casting_rubrics",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("application_id", sa.String(48), sa.ForeignKey("nova_casting_intakes.id"), nullable=False),
            sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("criterion", sa.String(32), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.CheckConstraint("score >= 1 AND score <= 5", name="ck_nova_casting_rubric_score"),
            sa.CheckConstraint(
                "criterion IN ('preparation', 'clarity', 'reliability', 'instructions_followed')",
                name="ck_nova_casting_rubric_criterion",
            ),
        )
        op.create_index("ix_nova_casting_rubrics_organization_id", "nova_casting_rubrics", ["organization_id"])
    if "nova_casting_pilot_messages" not in present:
        op.create_table(
            "nova_casting_pilot_messages",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("application_id", sa.String(48), nullable=False, server_default=""),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("channel", sa.String(16), nullable=False, server_default="email"),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("idempotency_key", sa.String(64), nullable=False),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("approved_by", sa.String(36), nullable=False, server_default=""),
            sa.Column("delivery_state", sa.String(16), nullable=False, server_default="not_sent"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.CheckConstraint("kind IN ('confirmation', 'invite', 'reminder', 'update')", name="ck_nova_casting_pilot_message_kind"),
            sa.CheckConstraint("status IN ('draft', 'approved', 'suppressed', 'failed_closed')", name="ck_nova_casting_pilot_message_status"),
            sa.CheckConstraint("channel IN ('email', 'sms', 'whatsapp')", name="ck_nova_casting_pilot_message_channel"),
            sa.CheckConstraint("delivery_state = 'not_sent'", name="ck_nova_casting_pilot_message_delivery"),
            sa.CheckConstraint("attempt_count >= 0", name="ck_nova_casting_pilot_message_attempts"),
            sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_nova_casting_pilot_message_key"),
        )
    if "nova_casting_suppressions" not in present:
        op.create_table(
            "nova_casting_suppressions",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("contact_email", sa.String(320), nullable=False),
            sa.Column("reason", sa.String(16), nullable=False),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.CheckConstraint("reason IN ('stop', 'unsubscribe')", name="ck_nova_casting_suppression_reason"),
            sa.UniqueConstraint("organization_id", "contact_email", name="uq_nova_casting_suppression_contact"),
        )
    if "nova_casting_schedules" not in present:
        op.create_table(
            "nova_casting_schedules",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
            sa.Column("campaign_id", sa.String(48), sa.ForeignKey("nova_casting_campaigns.id"), nullable=False),
            sa.Column("role_id", sa.String(48), sa.ForeignKey("nova_casting_roles.id"), nullable=False),
            sa.Column("timezone", sa.String(64), nullable=False),
            sa.Column("starts_at", sa.String(64), nullable=False),
            sa.Column("ends_at", sa.String(64), nullable=False),
            sa.Column("location_label", sa.String(120), nullable=False),
            sa.Column("document_url", sa.String(500), nullable=False, server_default=""),
            sa.Column("updated_at", sa.String(64), nullable=False),
            sa.UniqueConstraint("organization_id", "role_id", name="uq_nova_casting_schedule_role"),
        )
    if "nova_casting_pilot_audit" not in present:
        op.create_table(
            "nova_casting_pilot_audit",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("actor_id", sa.String(36), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("object_id", sa.String(48), nullable=False),
            sa.Column("occurred_at", sa.String(64), nullable=False),
            sa.CheckConstraint(
                "action IN ('role.created', 'intake.saved', 'intake.submitted', 'consent.revoked', "
                "'intake.minimized', 'review.updated', 'rubric.recorded', 'message.drafted', "
                "'message.approved', 'message.retried', 'suppression.recorded', 'schedule.saved', "
                "'export.requested')",
                name="ck_nova_casting_pilot_audit_action",
            ),
        )
        op.create_index("ix_nova_casting_pilot_audit_org", "nova_casting_pilot_audit", ["organization_id", "occurred_at"])


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    present = _names(bind)
    for name in _PILOT_TABLES:
        if name in present:
            op.drop_table(name)
