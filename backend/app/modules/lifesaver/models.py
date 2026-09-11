"""Lifesaver ORM tables. All names use the lifesaver_ prefix and are additive."""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4

logger = logging.getLogger("amicor.lifesaver.models")


class LifesaverProfile(Base):
    __tablename__ = "lifesaver_profiles"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_lifesaver_profile_org_user"),
        Index("ix_lifesaver_profiles_org_role", "organization_id", "profile_role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    profile_role: Mapped[str] = mapped_column(String(32), nullable=False, default="member")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="America/Chicago")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    accessibility_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverConsent(Base):
    __tablename__ = "lifesaver_consents"
    __table_args__ = (
        UniqueConstraint("profile_id", "consent_type", name="uq_lifesaver_consent_profile_type"),
        Index("ix_lifesaver_consents_org_profile", "organization_id", "profile_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    consent_type: Mapped[str] = mapped_column(String(64), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverCareCircleMember(Base):
    __tablename__ = "lifesaver_care_circle_members"
    __table_args__ = (
        UniqueConstraint("member_profile_id", "caregiver_profile_id", name="uq_lifesaver_circle_pair"),
        Index("ix_lifesaver_circle_org_member", "organization_id", "member_profile_id"),
        Index("ix_lifesaver_circle_org_caregiver", "organization_id", "caregiver_profile_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    member_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    caregiver_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    caregiver_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="invited")
    permissions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    invited_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifesaverMedication(Base):
    __tablename__ = "lifesaver_medications"
    __table_args__ = (Index("ix_lifesaver_meds_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    instructions: Mapped[str | None] = mapped_column(String(512), nullable=True)
    schedule_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverReminder(Base):
    __tablename__ = "lifesaver_reminders"
    __table_args__ = (
        Index("ix_lifesaver_reminders_org_profile_due", "organization_id", "profile_id", "due_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled", index=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverAppointment(Base):
    __tablename__ = "lifesaver_appointments"
    __table_args__ = (Index("ix_lifesaver_appts_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverWellnessCheckin(Base):
    __tablename__ = "lifesaver_wellness_checkins"
    __table_args__ = (Index("ix_lifesaver_wellness_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    mood: Mapped[str] = mapped_column(String(32), nullable=False)
    energy: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class LifesaverJournalEntry(Base):
    __tablename__ = "lifesaver_journal_entries"
    __table_args__ = (Index("ix_lifesaver_journal_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class LifesaverHealthReading(Base):
    __tablename__ = "lifesaver_health_readings"
    __table_args__ = (
        Index("ix_lifesaver_readings_org_profile_type", "organization_id", "profile_id", "reading_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reading_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value_primary: Mapped[float] = mapped_column(Float, nullable=False)
    value_secondary: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user_entered")
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    device_alias: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverTransportConnection(Base):
    __tablename__ = "lifesaver_transport_connections"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile_id", name="uq_lifesaver_transport_profile"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="not_connected")
    status_text: Mapped[str] = mapped_column(String(256), nullable=False, default="Not connected")
    external_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverTransportRequest(Base):
    __tablename__ = "lifesaver_transport_requests"
    __table_args__ = (Index("ix_lifesaver_treq_org_profile", "organization_id", "profile_id", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    appointment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_label: Mapped[str] = mapped_column(String(160), nullable=False)
    destination_label: Mapped[str] = mapped_column(String(160), nullable=False)
    accessibility_needs: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mobility_note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    companion_needed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested", index=True)
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    confirmed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverNotificationOutbox(Base):
    __tablename__ = "lifesaver_notification_outbox"
    __table_args__ = (
        Index("ix_lifesaver_outbox_org_profile_status", "organization_id", "profile_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    recipient_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    recipient_role: Mapped[str] = mapped_column(String(32), nullable=False, default="caregiver")
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="email")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued_local", index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    redacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverSosDemonstration(Base):
    __tablename__ = "lifesaver_sos_demonstrations"
    __table_args__ = (Index("ix_lifesaver_sos_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    confirmed_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifesaverAlert(Base):
    __tablename__ = "lifesaver_alerts"
    __table_args__ = (
        Index("ix_lifesaver_alerts_org_caregiver", "organization_id", "caregiver_profile_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    member_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    caregiver_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    alert_type: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    requires_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    acknowledged_by_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class LifesaverHandoff(Base):
    __tablename__ = "lifesaver_handoffs"
    __table_args__ = (Index("ix_lifesaver_handoffs_org_member", "organization_id", "member_profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    member_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    from_caregiver_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_caregiver_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    note: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifesaverCareTask(Base):
    __tablename__ = "lifesaver_care_tasks"
    __table_args__ = (Index("ix_lifesaver_tasks_org_member", "organization_id", "member_profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    member_profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    assigned_caregiver_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    created_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverConversation(Base):
    __tablename__ = "lifesaver_conversations"
    __table_args__ = (Index("ix_lifesaver_conv_org_profile", "organization_id", "profile_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverConversationMessage(Base):
    __tablename__ = "lifesaver_conversation_messages"
    __table_args__ = (Index("ix_lifesaver_messages_conv", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverAuditEvent(Base):
    __tablename__ = "lifesaver_audit_events"
    __table_args__ = (
        Index("ix_lifesaver_audit_org_actor", "organization_id", "actor_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


LIFESAVER_MODELS = (
    LifesaverProfile,
    LifesaverConsent,
    LifesaverCareCircleMember,
    LifesaverMedication,
    LifesaverReminder,
    LifesaverAppointment,
    LifesaverWellnessCheckin,
    LifesaverJournalEntry,
    LifesaverHealthReading,
    LifesaverTransportConnection,
    LifesaverTransportRequest,
    LifesaverNotificationOutbox,
    LifesaverSosDemonstration,
    LifesaverAlert,
    LifesaverHandoff,
    LifesaverCareTask,
    LifesaverConversation,
    LifesaverConversationMessage,
    LifesaverAuditEvent,
)


def ensure_lifesaver_schema() -> None:
    """Create additive lifesaver_* tables and columns when they are not yet present."""
    from sqlalchemy import inspect, text

    from app.db.session import engine

    try:
        inspector = inspect(engine)
        existing = set(inspector.get_table_names())
        missing = [model for model in LIFESAVER_MODELS if model.__tablename__ not in existing]
        if missing:
            Base.metadata.create_all(bind=engine, tables=[model.__table__ for model in missing])
            logger.info("lifesaver schema ensured tables=%s", ",".join(m.__tablename__ for m in missing))
        if LifesaverHealthReading.__tablename__ in set(inspector.get_table_names()):
            cols = {col["name"] for col in inspect(engine).get_columns(LifesaverHealthReading.__tablename__)}
            alters = []
            if "device_alias" not in cols:
                alters.append("ALTER TABLE lifesaver_health_readings ADD COLUMN device_alias VARCHAR(64)")
            if "ingestion_status" not in cols:
                alters.append(
                    "ALTER TABLE lifesaver_health_readings ADD COLUMN ingestion_status VARCHAR(32) DEFAULT 'accepted'"
                )
            if alters:
                with engine.begin() as conn:
                    for stmt in alters:
                        conn.execute(text(stmt))
                logger.info("lifesaver reading columns ensured")
    except Exception as exc:
        logger.warning("lifesaver schema ensure skipped: %s", type(exc).__name__)
