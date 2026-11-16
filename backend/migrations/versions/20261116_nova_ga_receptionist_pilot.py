"""Nova Growth Agent receptionist pilot tables (draft / prod-gated).

Revision ID: 20261116_nova_ga_receptionist
Revises: 20261112_nova_ga_retention

Additive only. Production-locked environments skip DDL.
Do not run against existing production databases without separate owner approval.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261116_nova_ga_receptionist"
down_revision = "20261112_nova_ga_retention"
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
    "nova_ga_calendar_oauth_states",
    "nova_ga_calendar_connections",
    "nova_ga_calendar_sync_jobs",
    "nova_ga_owner_notifications",
    "nova_ga_handoff_requests",
    "nova_ga_voice_agent_mappings",
    "nova_ga_voice_webhook_events",
    "nova_ga_voice_sessions",
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
        "nova_ga_calendar_oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("session_fingerprint", sa.String(128), nullable=False),
        sa.Column("state_hash", sa.String(128), nullable=False),
        sa.Column("code_verifier_encrypted", sa.Text(), nullable=True),
        sa.Column("redirect_uri", sa.String(500), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("state_hash", name="uq_nova_ga_oauth_state_hash"),
    )
    if "nova_ga_calendar_oauth_states" not in existing:
        op.create_index(
            "ix_nova_ga_oauth_org_exp",
            "nova_ga_calendar_oauth_states",
            ["organization_id", "expires_at"],
        )

    create(
        "nova_ga_calendar_connections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("calendar_id", sa.String(320), nullable=True),
        sa.Column("calendar_summary", sa.String(200), nullable=True),
        sa.Column("scopes_json", json_t, nullable=False),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("access_token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("connected_at", sa.DateTime(), nullable=True),
        sa.Column("disconnected_at", sa.DateTime(), nullable=True),
        sa.Column("meta_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", name="uq_nova_ga_calendar_org"),
    )
    if "nova_ga_calendar_connections" not in existing:
        op.create_index(
            "ix_nova_ga_calendar_status",
            "nova_ga_calendar_connections",
            ["organization_id", "status"],
        )

    create(
        "nova_ga_calendar_sync_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("appointment_id", sa.String(36), nullable=False),
        sa.Column("connection_id", sa.String(36), nullable=False),
        sa.Column("calendar_id", sa.String(320), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("operation_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("starts_at_utc", sa.DateTime(), nullable=True),
        sa.Column("ends_at_utc", sa.DateTime(), nullable=True),
        sa.Column("provider_etag", sa.String(200), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("claimed_by", sa.String(80), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("payload_json", json_t, nullable=False),
        sa.Column("result_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "organization_id",
            "appointment_id",
            "operation_version",
            name="uq_nova_ga_sync_appt_version",
        ),
    )
    if "nova_ga_calendar_sync_jobs" not in existing:
        op.create_index(
            "ix_nova_ga_sync_claim",
            "nova_ga_calendar_sync_jobs",
            ["status", "available_at", "lease_expires_at"],
        )
        op.create_index(
            "ix_nova_ga_sync_org_appt",
            "nova_ga_calendar_sync_jobs",
            ["organization_id", "appointment_id"],
        )

    create(
        "nova_ga_owner_notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("provider_message_id", sa.String(120), nullable=True),
        sa.Column("payload_redacted_json", json_t, nullable=False),
        sa.Column("claimed_by", sa.String(80), nullable=True),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("available_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_nova_ga_owner_notify_idem",
        ),
    )
    if "nova_ga_owner_notifications" not in existing:
        op.create_index(
            "ix_nova_ga_owner_notify_claim",
            "nova_ga_owner_notifications",
            ["status", "available_at", "lease_expires_at"],
        )
        op.create_index(
            "ix_nova_ga_owner_notify_org",
            "nova_ga_owner_notifications",
            ["organization_id", "created_at"],
        )

    create(
        "nova_ga_handoff_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=True),
        sa.Column("conversation_id", sa.String(36), nullable=True),
        sa.Column("appointment_id", sa.String(36), nullable=True),
        sa.Column("channel", sa.String(40), nullable=False),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("summary", sa.String(500), nullable=False),
        sa.Column("payload_redacted_json", json_t, nullable=False),
        sa.Column("acknowledged_by", sa.String(36), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    if "nova_ga_handoff_requests" not in existing:
        op.create_index(
            "ix_nova_ga_handoff_org_status",
            "nova_ga_handoff_requests",
            ["organization_id", "status", "created_at"],
        )

    create(
        "nova_ga_voice_agent_mappings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("external_number", sa.String(40), nullable=False),
        sa.Column("agent_label", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("kill_switch", sa.Boolean(), nullable=False),
        sa.Column("daily_call_limit", sa.Integer(), nullable=False),
        sa.Column("meta_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "provider",
            "external_number",
            name="uq_nova_ga_voice_provider_number",
        ),
    )
    if "nova_ga_voice_agent_mappings" not in existing:
        op.create_index(
            "ix_nova_ga_voice_org",
            "nova_ga_voice_agent_mappings",
            ["organization_id"],
        )

    create(
        "nova_ga_voice_webhook_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("call_sid", sa.String(80), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("signature_valid", sa.Boolean(), nullable=False),
        sa.Column("payload_redacted_json", json_t, nullable=False),
        sa.Column("result_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "event_id", name="uq_nova_ga_voice_event"),
    )
    if "nova_ga_voice_webhook_events" not in existing:
        op.create_index(
            "ix_nova_ga_voice_evt_org",
            "nova_ga_voice_webhook_events",
            ["organization_id", "created_at"],
        )

    create(
        "nova_ga_voice_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("call_sid", sa.String(80), nullable=False),
        sa.Column("caller_fingerprint", sa.String(128), nullable=True),
        sa.Column("contact_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("authorized_appointment_ids_json", json_t, nullable=False),
        sa.Column("usage_count", sa.Integer(), nullable=False),
        sa.Column("meta_json", json_t, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "call_sid", name="uq_nova_ga_voice_call"),
    )
    if "nova_ga_voice_sessions" not in existing:
        op.create_index(
            "ix_nova_ga_voice_sess_org",
            "nova_ga_voice_sessions",
            ["organization_id", "status"],
        )


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    for name in reversed(TABLES):
        if name in existing:
            op.drop_table(name)
