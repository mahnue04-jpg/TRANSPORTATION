"""Sandbox-only tables for the Casting pilot. Startup create_all omits them."""
from __future__ import annotations

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

_ACTIONS = (
    "role.created", "intake.saved", "intake.submitted", "consent.revoked",
    "intake.minimized", "review.updated", "rubric.recorded", "message.drafted",
    "message.approved", "message.retried", "suppression.recorded", "schedule.saved",
    "export.requested",
)


class NovaCastingRole(Base):
    __tablename__ = "nova_casting_roles"
    __table_args__ = (
        Index("ix_nova_casting_role_campaign", "organization_id", "campaign_id"),
        CheckConstraint("minimum_age >= 18", name="ck_nova_casting_role_minimum_age"),
        CheckConstraint("length(title) > 0", name="ck_nova_casting_role_title"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("nova_casting_organizations.id"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_campaigns.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    requirements: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    deadline: Mapped[str] = mapped_column(String(64), nullable=False)
    questions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    minimum_age: Mapped[int] = mapped_column(Integer, nullable=False, default=18, server_default="18")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingIntake(Base):
    __tablename__ = "nova_casting_intakes"
    __table_args__ = (
        Index("ix_nova_casting_intake_org", "organization_id", "campaign_id"),
        CheckConstraint("status IN ('DRAFT', 'SUBMITTED', 'WITHDRAWN')", name="ck_nova_casting_intake_status"),
        CheckConstraint("stage IN ('New', 'In review', 'Callback', 'Closed')", name="ck_nova_casting_intake_stage"),
        CheckConstraint("retention_days >= 1 AND retention_days <= 365", name="ck_nova_casting_intake_retention"),
        CheckConstraint("age_years >= 18", name="ck_nova_casting_intake_age"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("nova_casting_organizations.id"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_campaigns.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_roles.id"), nullable=False)
    applicant_id: Mapped[str] = mapped_column(String(36), ForeignKey("platform_users.id"), nullable=False)
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="", server_default="")
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False, default="", server_default="")
    video_url: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    answers_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    age_years: Mapped[int] = mapped_column(Integer, nullable=False)
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30, server_default="30")
    consent_expires_at: Mapped[str] = mapped_column(String(64), nullable=False)
    consent_revoked_at: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    receipt: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT", server_default="DRAFT")
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="New", server_default="New")
    shortlisted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    minimized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingRubric(Base):
    __tablename__ = "nova_casting_rubrics"
    __table_args__ = (
        CheckConstraint("score >= 1 AND score <= 5", name="ck_nova_casting_rubric_score"),
        CheckConstraint(
            "criterion IN ('preparation', 'clarity', 'reliability', 'instructions_followed')",
            name="ck_nova_casting_rubric_criterion",
        ),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    application_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_intakes.id"), nullable=False)
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("platform_users.id"), nullable=False)
    criterion: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingPilotMessage(Base):
    __tablename__ = "nova_casting_pilot_messages"
    __table_args__ = (
        Index("uq_nova_casting_pilot_message_key", "organization_id", "idempotency_key", unique=True),
        CheckConstraint(
            "kind IN ('confirmation', 'invite', 'reminder', 'update')",
            name="ck_nova_casting_pilot_message_kind",
        ),
        CheckConstraint(
            "status IN ('draft', 'approved', 'suppressed', 'failed_closed')",
            name="ck_nova_casting_pilot_message_status",
        ),
        CheckConstraint(
            "channel IN ('email', 'sms', 'whatsapp')",
            name="ck_nova_casting_pilot_message_channel",
        ),
        CheckConstraint("delivery_state = 'not_sent'", name="ck_nova_casting_pilot_message_delivery"),
        CheckConstraint("attempt_count >= 0", name="ck_nova_casting_pilot_message_attempts"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    application_id: Mapped[str] = mapped_column(String(48), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="email", server_default="email")
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    approved_by: Mapped[str] = mapped_column(String(36), nullable=False, default="", server_default="")
    delivery_state: Mapped[str] = mapped_column(String(16), nullable=False, default="not_sent", server_default="not_sent")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingSuppression(Base):
    __tablename__ = "nova_casting_suppressions"
    __table_args__ = (
        Index("uq_nova_casting_suppression_contact", "organization_id", "contact_email", unique=True),
        CheckConstraint("reason IN ('stop', 'unsubscribe')", name="ck_nova_casting_suppression_reason"),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingSchedule(Base):
    __tablename__ = "nova_casting_schedules"
    __table_args__ = (
        Index("uq_nova_casting_schedule_role", "organization_id", "role_id", unique=True),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("nova_casting_organizations.id"), nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_campaigns.id"), nullable=False)
    role_id: Mapped[str] = mapped_column(String(48), ForeignKey("nova_casting_roles.id"), nullable=False)
    timezone_name: Mapped[str] = mapped_column("timezone", String(64), nullable=False)
    starts_at: Mapped[str] = mapped_column(String(64), nullable=False)
    ends_at: Mapped[str] = mapped_column(String(64), nullable=False)
    location_label: Mapped[str] = mapped_column(String(120), nullable=False)
    document_url: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCastingPilotAudit(Base):
    __tablename__ = "nova_casting_pilot_audit"
    __table_args__ = (
        Index("ix_nova_casting_pilot_audit_org", "organization_id", "occurred_at"),
        CheckConstraint(
            "action IN (" + ", ".join(repr(item) for item in _ACTIONS) + ")",
            name="ck_nova_casting_pilot_audit_action",
        ),
    )
    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    object_id: Mapped[str] = mapped_column(String(48), nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(64), nullable=False)
