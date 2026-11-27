"""Nova Growth Agent tenant-safe tables (draft / prod-gated).

Revision ID: 20261112_nova_growth_agent
Revises: 20261012_casting_org_name

Safe plan, dev and disposable databases only:

- Do not run DDL against production until owner review. When AMICOR_ENVIRONMENT,
  ENVIRONMENT, or APP_ENV is production or prod, upgrade/downgrade return without
  DDL (stamp-only on production ``alembic upgrade heads``).
- Additive only. Does not alter Delivery, Health ISF, Work & Revenue, or Creative
  Studio tables.
- Downgrade drops Growth Agent tables only when not production-locked.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261112_nova_growth_agent"
down_revision = "20261012_casting_org_name"
branch_labels = None
depends_on = None


def _production_schema_locked() -> bool:
    import os

    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def _json_type():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        return JSONB()
    return sa.JSON()


TABLES = (
    "nova_ga_business_profiles",
    "nova_ga_widget_installations",
    "nova_ga_contacts",
    "nova_ga_contact_identities",
    "nova_ga_lead_events",
    "nova_ga_conversations",
    "nova_ga_conversation_messages",
    "nova_ga_consent_records",
    "nova_ga_workflow_definitions",
    "nova_ga_workflow_runs",
    "nova_ga_delivery_attempts",
    "nova_ga_appointment_services",
    "nova_ga_availability_rules",
    "nova_ga_appointments",
    "nova_ga_integration_connections",
    "nova_ga_usage_events",
    "nova_ga_audit_events",
    "nova_ga_idempotency_keys",
)


def upgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    json_t = _json_type()

    def create(name: str, *cols, **kwargs):
        if name in existing:
            return
        op.create_table(name, *cols, **kwargs)

    create(
        "nova_ga_business_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("business_name", sa.String(200), nullable=False),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("operating_hours_json", json_t, nullable=False),
        sa.Column("services_json", json_t, nullable=False),
        sa.Column("faqs_json", json_t, nullable=False),
        sa.Column("contact_email", sa.String(320), nullable=True),
        sa.Column("handoff_phone", sa.String(40), nullable=True),
        sa.Column("escalation_settings_json", json_t, nullable=False),
        sa.Column("branding_json", json_t, nullable=False),
        sa.Column("plan_code", sa.String(40), nullable=False),
        sa.Column("agent_paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("agent_disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("activated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("setup_checklist_json", json_t, nullable=False),
        sa.Column("quiet_hours_json", json_t, nullable=False),
        sa.Column("is_synthetic_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", name="uq_nova_ga_profile_org"),
    )
    create(
        "nova_ga_widget_installations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("token_hash", sa.String(128), nullable=False),
        sa.Column("branding_json", json_t, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "domain", name="uq_nova_ga_widget_org_domain"),
    )
    create(
        "nova_ga_contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("lead_state", sa.String(40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("dedupe_fingerprint", sa.String(128), nullable=False),
        sa.Column("do_not_contact", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_synthetic_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_contact_identities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("external_id", sa.String(320), nullable=False),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "channel",
            "external_id",
            name="uq_nova_ga_identity_org_channel_ext",
        ),
    )
    create(
        "nova_ga_lead_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_conversations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=True),
        sa.Column("widget_installation_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("handler", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(300), nullable=True),
        sa.Column("is_synthetic_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_conversation_messages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("faq_id", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_consent_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("collection_source", sa.String(80), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("evidence_json", json_t, nullable=False),
    )
    create(
        "nova_ga_workflow_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("steps_json", json_t, nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_nova_ga_workflow_org_code"),
    )
    create(
        "nova_ga_workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preview_json", json_t, nullable=False),
        sa.Column("scheduled_for", sa.DateTime(), nullable=True),
        sa.Column("stop_reason", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_delivery_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("workflow_run_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("cost_estimate_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("payload_redacted_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_nova_ga_delivery_idem"),
    )
    create(
        "nova_ga_appointment_services",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "code", name="uq_nova_ga_svc_org_code"),
    )
    create(
        "nova_ga_availability_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("day_of_week", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("exception_date", sa.String(10), nullable=True),
        sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_appointments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("service_id", sa.String(36), nullable=False),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("starts_at_utc", sa.DateTime(), nullable=False),
        sa.Column("ends_at_utc", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("is_synthetic_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "starts_at_utc",
            "service_id",
            name="uq_nova_ga_appt_slot",
        ),
    )
    create(
        "nova_ga_integration_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("secret_ref", sa.String(200), nullable=True),
        sa.Column("config_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "provider", name="uq_nova_ga_integ_org_provider"),
    )
    create(
        "nova_ga_usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("meter", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit_cost_usd", sa.Float(), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("billed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("meta_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_audit_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("entity_type", sa.String(80), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("payload_redacted_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    create(
        "nova_ga_idempotency_keys",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(80), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("response_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "scope", "key", name="uq_nova_ga_idem_org_scope_key"),
    )


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in reversed(TABLES):
        if name in existing:
            op.drop_table(name)
