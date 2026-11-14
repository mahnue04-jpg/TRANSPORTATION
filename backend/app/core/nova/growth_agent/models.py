"""SQLAlchemy models for Nova Growth Agent. Every row is organization-scoped."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class GaBusinessProfile(Base):
    __tablename__ = "nova_ga_business_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", name="uq_nova_ga_profile_org"),
        Index("ix_nova_ga_profile_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    operating_hours_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    services_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    faqs_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    contact_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    handoff_phone: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    escalation_settings_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    branding_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    plan_code: Mapped[str] = mapped_column(String(40), nullable=False, default="starter")
    agent_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    agent_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    setup_checklist_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    quiet_hours_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaCampaign(Base):
    """Owner-reviewed Studio campaign. Widget token is a public embed token, never owner auth."""
    __tablename__ = "nova_ga_campaigns"
    __table_args__ = (Index("ix_nova_ga_campaign_org", "organization_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    studio_project_id: Mapped[str] = mapped_column(String(48), nullable=False)
    widget_installation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    public_widget_token: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaWidgetInstallation(Base):
    __tablename__ = "nova_ga_widget_installations"
    __table_args__ = (
        UniqueConstraint("organization_id", "domain", name="uq_nova_ga_widget_org_domain"),
        Index("ix_nova_ga_widget_token_hash", "token_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    branding_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaContact(Base):
    __tablename__ = "nova_ga_contacts"
    __table_args__ = (
        Index("ix_nova_ga_contact_org", "organization_id"),
        Index("ix_nova_ga_contact_org_state", "organization_id", "lead_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lead_state: Mapped[str] = mapped_column(String(40), nullable=False, default="new")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    dedupe_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    do_not_contact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaContactIdentity(Base):
    __tablename__ = "nova_ga_contact_identities"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "channel",
            "external_id",
            name="uq_nova_ga_identity_org_channel_ext",
        ),
        Index("ix_nova_ga_identity_contact", "organization_id", "contact_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)  # email|phone|web
    external_id: Mapped[str] = mapped_column(String(320), nullable=False)  # hashed or normalized
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaLeadEvent(Base):
    __tablename__ = "nova_ga_lead_events"
    __table_args__ = (Index("ix_nova_ga_lead_evt_org", "organization_id", "contact_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaConversation(Base):
    __tablename__ = "nova_ga_conversations"
    __table_args__ = (Index("ix_nova_ga_conv_org", "organization_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    widget_installation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="open")  # open|handed_off|closed
    handler: Mapped[str] = mapped_column(String(20), nullable=False, default="ai")  # ai|human
    subject: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaConversationMessage(Base):
    __tablename__ = "nova_ga_conversation_messages"
    __table_args__ = (Index("ix_nova_ga_msg_conv", "organization_id", "conversation_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # visitor|assistant|human|system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    faq_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaConsentRecord(Base):
    __tablename__ = "nova_ga_consent_records"
    __table_args__ = (
        Index("ix_nova_ga_consent_org_contact", "organization_id", "contact_id", "channel", "purpose"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False)  # transactional|marketing
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # opted_in|opted_out
    collection_source: Mapped[str] = mapped_column(String(80), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)


class GaWorkflowDefinition(Base):
    __tablename__ = "nova_ga_workflow_definitions"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_nova_ga_workflow_org_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    purpose: Mapped[str] = mapped_column(String(40), nullable=False, default="transactional")
    steps_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaWorkflowRun(Base):
    __tablename__ = "nova_ga_workflow_runs"
    __table_args__ = (Index("ix_nova_ga_run_org", "organization_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    # draft|preview|awaiting_approval|approved|running|completed|suppressed|failed|cancelled
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    preview_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    scheduled_for: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    stop_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaDeliveryAttempt(Base):
    __tablename__ = "nova_ga_delivery_attempts"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_nova_ga_delivery_idem"),
        Index("ix_nova_ga_delivery_run", "organization_id", "workflow_run_id"),
        Index("ix_nova_ga_delivery_claim", "status", "available_at", "claimed_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workflow_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="mock")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    # queued|running|sent_mock|failed|suppressed|retrying
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    cost_estimate_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payload_redacted_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    claimed_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaRateLimitCounter(Base):
    """Atomic shared rate-limit windows suitable for multi-worker enforcement."""

    __tablename__ = "nova_ga_rate_limit_counters"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "bucket_key",
            "window_start",
            name="uq_nova_ga_rate_org_bucket_window",
        ),
        Index("ix_nova_ga_rate_org_bucket", "organization_id", "bucket_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    bucket_key: Mapped[str] = mapped_column(String(160), nullable=False)
    window_start: Mapped[int] = mapped_column(Integer, nullable=False)  # epoch seconds floor
    count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaWorkerHeartbeat(Base):
    """Process heartbeats for mock worker diagnostics (no PII)."""

    __tablename__ = "nova_ga_worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="stopped")
    # running|stopping|stopped
    jobs_claimed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    jobs_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_beat_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaRetentionScheduleRun(Base):
    """Durable scheduled retention runs — duplicate-protected per org+window.

    Default processing is dry-run. Destructive mode requires a separate delete flag.
    """

    __tablename__ = "nova_ga_retention_schedule_runs"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "window_key",
            name="uq_nova_ga_retention_org_window",
        ),
        Index("ix_nova_ga_retention_claim", "status", "available_at", "lease_expires_at"),
        Index("ix_nova_ga_retention_org", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    window_key: Mapped[str] = mapped_column(String(40), nullable=False)  # e.g. 2026-11-12
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="pending")
    # pending|running|completed|failed|skipped
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="dry_run")
    # dry_run|delete
    claimed_by: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    available_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    batch_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=500)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_code: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class GaAppointmentService(Base):
    __tablename__ = "nova_ga_appointment_services"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_nova_ga_svc_org_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaAvailabilityRule(Base):
    __tablename__ = "nova_ga_availability_rules"
    __table_args__ = (Index("ix_nova_ga_avail_org", "organization_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)  # 0=Mon .. 6=Sun
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)  # minutes from midnight local
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    exception_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)  # YYYY-MM-DD
    is_closed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaAppointment(Base):
    __tablename__ = "nova_ga_appointments"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "starts_at_utc",
            "service_id",
            name="uq_nova_ga_appt_slot",
        ),
        Index("ix_nova_ga_appt_org_time", "organization_id", "starts_at_utc"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service_id: Mapped[str] = mapped_column(String(36), nullable=False)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="confirmed")
    # confirmed|rescheduled|cancelled
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    is_synthetic_demo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaIntegrationConnection(Base):
    """Provider connection metadata. Secrets never stored in plaintext."""

    __tablename__ = "nova_ga_integration_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider", name="uq_nova_ga_integ_org_provider"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)  # mock_email|mock_sms|google|microsoft
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="disabled")
    secret_ref: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)  # vault ref only
    config_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)


class GaUsageEvent(Base):
    __tablename__ = "nova_ga_usage_events"
    __table_args__ = (Index("ix_nova_ga_usage_org", "organization_id", "meter"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    meter: Mapped[str] = mapped_column(String(40), nullable=False)  # tokens|sms|email|minutes
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unit_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="mock")
    billed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # always False for now
    meta_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaAuditEvent(Base):
    __tablename__ = "nova_ga_audit_events"
    __table_args__ = (Index("ix_nova_ga_audit_org", "organization_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    payload_redacted_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


class GaIdempotencyKey(Base):
    __tablename__ = "nova_ga_idempotency_keys"
    __table_args__ = (
        UniqueConstraint("organization_id", "scope", "key", name="uq_nova_ga_idem_org_scope_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=_utcnow)


GROWTH_AGENT_TABLES = (
    GaCampaign.__table__,
    GaBusinessProfile.__table__,
    GaWidgetInstallation.__table__,
    GaContact.__table__,
    GaContactIdentity.__table__,
    GaLeadEvent.__table__,
    GaConversation.__table__,
    GaConversationMessage.__table__,
    GaConsentRecord.__table__,
    GaWorkflowDefinition.__table__,
    GaWorkflowRun.__table__,
    GaDeliveryAttempt.__table__,
    GaAppointmentService.__table__,
    GaAvailabilityRule.__table__,
    GaAppointment.__table__,
    GaIntegrationConnection.__table__,
    GaUsageEvent.__table__,
    GaAuditEvent.__table__,
    GaIdempotencyKey.__table__,
    GaRateLimitCounter.__table__,
    GaWorkerHeartbeat.__table__,
    GaRetentionScheduleRun.__table__,
)

LEAD_STATES = ("new", "contacted", "qualified", "booked", "closed")
