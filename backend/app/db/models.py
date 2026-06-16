"""
SQLAlchemy ORM models for platform tables.
These supplement (not replace) the legacy sqlite3 tables in database.py.
All new tables are prefixed with `platform_` to avoid collisions.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index,
    Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.helpers import now, uuid4


# ── Users ─────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "platform_users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="staff", index=True)
    organization_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    conversations: Mapped[list["Conversation"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    uploads: Mapped[list["Upload"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ── Conversations ──────────────────────────────────────────────────────────────

class Conversation(Base):
    __tablename__ = "platform_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(256), default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    user: Mapped["User"] = relationship(back_populates="conversations")
    messages: Mapped[list["PlatformMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan",
        order_by="PlatformMessage.id",
    )


# ── Messages (platform version, linked to conversations) ──────────────────────

class PlatformMessage(Base):
    __tablename__ = "platform_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("platform_conversations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ── Uploads ────────────────────────────────────────────────────────────────────

class Upload(Base):
    __tablename__ = "platform_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    ocr_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_word_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    user: Mapped["User | None"] = relationship(back_populates="uploads")


# ── Memory records ─────────────────────────────────────────────────────────────

class MemoryRecord(Base):
    __tablename__ = "platform_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Provider logs ──────────────────────────────────────────────────────────────

class ProviderLog(Base):
    __tablename__ = "platform_provider_logs"
    __table_args__ = (
        Index("ix_provider_logs_name_created", "provider_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    endpoint: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Refresh tokens ─────────────────────────────────────────────────────────────

class RefreshToken(Base):
    __tablename__ = "platform_refresh_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    user: Mapped["User"] = relationship(back_populates="refresh_tokens")


# ── Audit logs ─────────────────────────────────────────────────────────────────

class AuditLog(Base):
    __tablename__ = "platform_audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    method: Mapped[str] = mapped_column(String(16), nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Integration accounts (OAuth/SMTP/Provider config) ───────────────────────

class IntegrationAccount(Base):
    __tablename__ = "platform_integrations"
    __table_args__ = (
        Index("ix_integrations_user_service", "user_id", "service"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(32), nullable=False)  # email | calendar
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # gmail | outlook | smtp
    account_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Email drafts (multi-draft platform store) ────────────────────────────────

class EmailDraftRecord(Base):
    __tablename__ = "platform_email_drafts"
    __table_args__ = (
        Index("ix_email_drafts_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="smtp")
    to_recipients: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    cc_recipients: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    bcc_recipients: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    subject: Mapped[str] = mapped_column(String(512), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachments_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Calendar events (provider-synced + local) ────────────────────────────────

class CalendarEventRecord(Base):
    __tablename__ = "platform_calendar_events"
    __table_args__ = (
        Index("ix_calendar_events_user_start", "user_id", "start_time"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    external_event_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    attendees_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    reminder_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="confirmed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Search cache ──────────────────────────────────────────────────────────────

class SearchCacheRecord(Base):
    __tablename__ = "platform_search_cache"
    __table_args__ = (
        Index("ix_search_cache_query_created", "query_key", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    query_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    query_text: Mapped[str] = mapped_column(String(512), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    news_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ── Semantic memory vectors ───────────────────────────────────────────────────

class MemoryVectorRecord(Base):
    __tablename__ = "platform_memory_vectors"
    __table_args__ = (
        Index("ix_memory_vectors_user_created", "user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="conversation")
    text_chunk: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_json: Mapped[str] = mapped_column(Text, nullable=False)
    priority_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Workflow templates and execution history ─────────────────────────────────

class WorkflowTemplate(Base):
    __tablename__ = "platform_workflows"
    __table_args__ = (
        Index("ix_workflows_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reusable_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_chain_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorkflowRunRecord(Base):
    __tablename__ = "platform_workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_workflow_created", "workflow_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workflow_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_results_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="completed")
    error_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Assistant governance durability (Phase 14) ──────────────────────────────

class AssistantPreviewRecord(Base):
    __tablename__ = "platform_assistant_preview_records"
    __table_args__ = (
        Index("ix_assistant_preview_intent", "intent_id", unique=True),
        Index("ix_assistant_preview_token", "token_id", unique=True),
        Index("ix_assistant_preview_correlation", "correlation_id", "created_at"),
        Index("ix_assistant_preview_session", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    token_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    supervision_classification: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    nonce: Mapped[str] = mapped_column(String(64), nullable=False)
    intent_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dependency_graph_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    safety_classification_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AssistantGovernanceLedger(Base):
    __tablename__ = "platform_assistant_governance_ledger"
    __table_args__ = (
        Index("ix_assistant_gov_sequence", "sequence", unique=True),
        Index("ix_assistant_gov_event", "event_id", unique=True),
        Index("ix_assistant_gov_correlation", "correlation_id", "created_at"),
        Index("ix_assistant_gov_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    intent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    token_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    sensitivity_tier: Mapped[str] = mapped_column(String(32), nullable=False)
    supervision_classification: Mapped[str] = mapped_column(String(64), nullable=False)
    dry_run_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    execution_disabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    workflow_dispatch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    canonical_payload: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    current_event_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AssistantExecutionRecord(Base):
    __tablename__ = "platform_assistant_execution_records"
    __table_args__ = (
        Index("ix_assistant_exec_execution", "execution_id", unique=True),
        Index("ix_assistant_exec_intent", "intent_id", "created_at"),
        Index("ix_assistant_exec_user_status", "user_id", "status", "created_at"),
        Index("ix_assistant_exec_session", "session_id", "created_at"),
        Index("ix_assistant_exec_correlation", "correlation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    supervision_classification: Mapped[str] = mapped_column(String(64), nullable=False)
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AssistantOperationalEventRecord(Base):
    __tablename__ = "platform_assistant_operational_events"
    __table_args__ = (
        Index("ix_assistant_ops_event_id", "event_id", unique=True),
        Index("ix_assistant_ops_user_created", "user_id", "created_at"),
        Index("ix_assistant_ops_session", "session_id", "created_at"),
        Index("ix_assistant_ops_type", "event_type", "event_name", "created_at"),
        Index("ix_assistant_ops_correlation", "correlation_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    route: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_name: Mapped[str] = mapped_column(String(96), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="info")
    correlation_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AssistantMemoryEntry(Base):
    __tablename__ = "platform_assistant_memory_entries"
    __table_args__ = (
        Index("ix_assistant_memory_entry_id", "entry_id", unique=True),
        Index("ix_assistant_memory_user_type", "user_id", "memory_type", "created_at"),
        Index("ix_assistant_memory_session", "session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entry_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    memory_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(128), nullable=False)
    content_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Driver compliance domain (Phase 24) ─────────────────────────────────────

class DriverComplianceProfile(Base):
    __tablename__ = "platform_driver_compliance_profiles"
    __table_args__ = (
        Index("ix_driver_compliance_driver", "driver_id", unique=True),
        Index("ix_driver_compliance_status", "compliance_status", "approval_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    driver_id: Mapped[str] = mapped_column(String(36), nullable=False)
    onboarding_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    compliance_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    background_check_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    background_check_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    license_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    license_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    insurance_provider: Mapped[str | None] = mapped_column(String(128), nullable=True)
    insurance_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vehicle_registration_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vehicle_inspection_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    medical_transport_certified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    training_completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceDocumentMetadata(Base):
    __tablename__ = "platform_compliance_documents"
    __table_args__ = (
        Index("ix_compliance_doc_driver", "driver_id", "type"),
        Index("ix_compliance_doc_status", "verification_status", "expiration_date"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    driver_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expiration_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ComplianceAuditEvent(Base):
    __tablename__ = "platform_compliance_audit_events"
    __table_args__ = (
        Index("ix_compliance_audit_sequence", "sequence", unique=True),
        Index("ix_compliance_audit_org_created", "organization_id", "created_at"),
        Index("ix_compliance_audit_driver_created", "target_driver_id", "created_at"),
        Index("ix_compliance_audit_role", "actor_role", "created_at"),
        Index("ix_compliance_audit_correlation", "correlation_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    target_driver_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[str] = mapped_column(Text, nullable=False)
    new_state: Mapped[str] = mapped_column(Text, nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceDocumentEvidence(Base):
    __tablename__ = "platform_compliance_document_evidence"
    __table_args__ = (
        Index("ix_compliance_evidence_doc", "document_id", unique=True),
        Index("ix_compliance_evidence_driver", "driver_id", "created_at"),
        Index("ix_compliance_evidence_lineage", "lineage_root_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    driver_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    storage_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="local_abstraction")
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, default="application/octet-stream")
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False, default="operational")
    encryption_status: Mapped[str] = mapped_column(String(32), nullable=False, default="encrypted_at_rest")
    uploaded_by: Mapped[str] = mapped_column(String(36), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    immutable_reference_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replaces_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lineage_root_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceDocumentLineageEvent(Base):
    __tablename__ = "platform_compliance_document_lineage_events"
    __table_args__ = (
        Index("ix_compliance_lineage_seq", "sequence", unique=True),
        Index("ix_compliance_lineage_doc", "document_id", "created_at"),
        Index("ix_compliance_lineage_root", "lineage_root_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    driver_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False)
    immutable_reference_id: Mapped[str] = mapped_column(String(96), nullable=False)
    superseded_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    replaces_document_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lineage_root_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceSignedAccessGrant(Base):
    __tablename__ = "platform_compliance_signed_access_grants"
    __table_args__ = (
        Index("ix_compliance_access_signed_id", "signed_access_id", unique=True),
        Index("ix_compliance_access_doc", "document_id", "created_at"),
        Index("ix_compliance_access_expires", "expires_at", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    signed_access_id: Mapped[str] = mapped_column(String(96), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    generated_by_role: Mapped[str] = mapped_column(String(32), nullable=False)
    accessed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    accessed_by_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    access_reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceExportBundle(Base):
    __tablename__ = "platform_compliance_export_bundles"
    __table_args__ = (
        Index("ix_compliance_export_export_id", "export_id", unique=True),
        Index("ix_compliance_export_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    export_id: Mapped[str] = mapped_column(String(96), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_driver_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    generated_by: Mapped[str] = mapped_column(String(36), nullable=False)
    generated_by_role: Mapped[str] = mapped_column(String(32), nullable=False)
    export_scope: Mapped[str] = mapped_column(String(128), nullable=False)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False, default="regulatory")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceSupervisorHandoffEvent(Base):
    __tablename__ = "platform_compliance_supervisor_handoff_events"
    __table_args__ = (
        Index("ix_compliance_handoff_seq", "sequence", unique=True),
        Index("ix_compliance_handoff_driver", "target_driver_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    target_driver_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_supervisor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    countersign_supervisor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    escalation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_reassignment_from: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ComplianceRetentionEvent(Base):
    __tablename__ = "platform_compliance_retention_events"
    __table_args__ = (
        Index("ix_compliance_retention_seq", "sequence", unique=True),
        Index("ix_compliance_retention_doc", "document_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    retention_class: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    release_workflow_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsTask(Base):
    __tablename__ = "platform_operations_tasks"
    __table_args__ = (
        Index("ix_operations_task_task_id", "task_id", unique=True),
        Index("ix_operations_task_org_created", "organization_id", "created_at"),
        Index("ix_operations_task_priority", "priority", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="operational")
    priority: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    target_driver_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(32), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsAssignmentEvent(Base):
    __tablename__ = "platform_operations_assignment_events"
    __table_args__ = (
        Index("ix_operations_assign_seq", "sequence", unique=True),
        Index("ix_operations_assign_task", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    assigned_to: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    assigned_to_role: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsEscalationEvent(Base):
    __tablename__ = "platform_operations_escalation_events"
    __table_args__ = (
        Index("ix_operations_escalation_seq", "sequence", unique=True),
        Index("ix_operations_escalation_task", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    escalation_level: Mapped[str] = mapped_column(String(64), nullable=False)
    routed_to: Mapped[str] = mapped_column(String(36), nullable=False)
    routed_to_role: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsAcknowledgementEvent(Base):
    __tablename__ = "platform_operations_acknowledgement_events"
    __table_args__ = (
        Index("ix_operations_ack_seq", "sequence", unique=True),
        Index("ix_operations_ack_task", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    acknowledgement_type: Mapped[str] = mapped_column(String(64), nullable=False, default="task_acknowledged")
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsNotificationEvent(Base):
    __tablename__ = "platform_operations_notification_events"
    __table_args__ = (
        Index("ix_operations_notification_seq", "sequence", unique=True),
        Index("ix_operations_notification_task", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(64), nullable=False)
    notification_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="role_scoped")
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsHandoffEvent(Base):
    __tablename__ = "platform_operations_handoff_events"
    __table_args__ = (
        Index("ix_operations_handoff_seq", "sequence", unique=True),
        Index("ix_operations_handoff_task", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    from_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    from_role: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    to_role: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsResolutionEvent(Base):
    __tablename__ = "platform_operations_resolution_events"
    __table_args__ = (
        Index("ix_operations_resolution_seq", "sequence", unique=True),
        Index("ix_operations_resolution_task", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resolution_state: Mapped[str] = mapped_column(String(48), nullable=False, default="resolution_requested")
    resolution_reason: Mapped[str] = mapped_column(Text, nullable=False)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by_role: Mapped[str] = mapped_column(String(32), nullable=False)
    requires_dual_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supervisor_approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsClosureApprovalEvent(Base):
    __tablename__ = "platform_operations_closure_approval_events"
    __table_args__ = (
        Index("ix_operations_closure_approval_seq", "sequence", unique=True),
        Index("ix_operations_closure_approval_task", "task_id", "created_at"),
        Index("ix_operations_closure_approval_resolution", "resolution_event_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    resolution_event_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    approval_action: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    supervisor_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    closure_achieved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsSLAThresholdEvent(Base):
    __tablename__ = "platform_operations_sla_threshold_events"
    __table_args__ = (
        Index("ix_operations_sla_threshold_seq", "sequence", unique=True),
        Index("ix_operations_sla_threshold_task", "task_id", "created_at"),
        Index("ix_operations_sla_threshold_metric", "threshold_metric", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    threshold_metric: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="advisory")
    threshold_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observed_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsProjectionCheckpoint(Base):
    __tablename__ = "platform_operations_projection_checkpoints"
    __table_args__ = (
        Index("ix_operations_projection_checkpoint_seq", "sequence", unique=True),
        Index("ix_operations_projection_checkpoint_org", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    checkpoint_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    stream_name: Mapped[str] = mapped_column(String(64), nullable=False, default="ops_orchestration_live")
    replay_start_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replay_end_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projection_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    projection_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsStreamCursor(Base):
    __tablename__ = "platform_operations_stream_cursors"
    __table_args__ = (
        Index("ix_operations_stream_cursor_seq", "sequence", unique=True),
        Index("ix_operations_stream_cursor_org", "organization_id", "created_at"),
        Index("ix_operations_stream_cursor_actor", "organization_id", "actor_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    cursor_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    stream_name: Mapped[str] = mapped_column(String(64), nullable=False, default="ops_orchestration_live")
    cursor_position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checkpoint_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRegion(Base):
    __tablename__ = "platform_operations_regions"
    __table_args__ = (
        Index("ix_operations_region_seq", "sequence", unique=True),
        Index("ix_operations_region_org_region", "organization_id", "region_code", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    region_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    region_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    region_name: Mapped[str] = mapped_column(String(128), nullable=False)
    governance_scope: Mapped[str] = mapped_column(String(64), nullable=False, default="isolated")
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRegionMembership(Base):
    __tablename__ = "platform_operations_region_memberships"
    __table_args__ = (
        Index("ix_operations_region_membership_seq", "sequence", unique=True),
        Index("ix_operations_region_membership_region_actor", "organization_id", "region_id", "member_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    membership_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    member_user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    member_role: Mapped[str] = mapped_column(String(32), nullable=False)
    membership_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsFederatedQueueSnapshot(Base):
    __tablename__ = "platform_operations_federated_queue_snapshots"
    __table_args__ = (
        Index("ix_operations_federated_queue_seq", "sequence", unique=True),
        Index("ix_operations_federated_queue_org_region", "organization_id", "region_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    escalated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    handoff_pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acknowledged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRegionalProjectionEvent(Base):
    __tablename__ = "platform_operations_regional_projection_events"
    __table_args__ = (
        Index("ix_operations_regional_projection_seq", "sequence", unique=True),
        Index("ix_operations_regional_projection_org_region", "organization_id", "region_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_event_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsCapacityForecastEvent(Base):
    __tablename__ = "platform_operations_capacity_forecast_events"
    __table_args__ = (
        Index("ix_operations_capacity_forecast_seq", "sequence", unique=True),
        Index("ix_operations_capacity_forecast_org_region", "organization_id", "region_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    forecast_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    forecast_window: Mapped[str] = mapped_column(String(64), nullable=False, default="next_30m")
    pressure_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    saturation_risk: Mapped[str] = mapped_column(String(32), nullable=False, default="normal")
    advisory_note: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsContinuityCheckpoint(Base):
    __tablename__ = "platform_operations_continuity_checkpoints"
    __table_args__ = (
        Index("ix_operations_continuity_checkpoint_seq", "sequence", unique=True),
        Index("ix_operations_continuity_checkpoint_org_region", "organization_id", "region_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    continuity_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    continuity_state: Mapped[str] = mapped_column(String(64), nullable=False, default="stable")
    unresolved_handoffs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    continuity_risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    checkpoint_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsCrossRegionHandoffEvent(Base):
    __tablename__ = "platform_operations_cross_region_handoff_events"
    __table_args__ = (
        Index("ix_operations_cross_region_handoff_seq", "sequence", unique=True),
        Index("ix_operations_cross_region_handoff_org_regions", "organization_id", "source_region_id", "target_region_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    handoff_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_region_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    handoff_state: Mapped[str] = mapped_column(String(48), nullable=False, default="handoff_requested")
    handoff_reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsReplaySession(Base):
    __tablename__ = "platform_operations_replay_sessions"
    __table_args__ = (
        Index("ix_operations_replay_session_seq", "sequence", unique=True),
        Index("ix_operations_replay_session_org", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    session_name: Mapped[str] = mapped_column(String(128), nullable=False)
    source_after_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_until_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsReplayFrame(Base):
    __tablename__ = "platform_operations_replay_frames"
    __table_args__ = (
        Index("ix_operations_replay_frame_seq", "sequence", unique=True),
        Index("ix_operations_replay_frame_session", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    replay_frame_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_event_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    source_event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    frame_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsSimulationScenario(Base):
    __tablename__ = "platform_operations_simulation_scenarios"
    __table_args__ = (
        Index("ix_operations_simulation_scenario_seq", "sequence", unique=True),
        Index("ix_operations_simulation_scenario_org", "organization_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    scenario_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    scenario_name: Mapped[str] = mapped_column(String(128), nullable=False)
    scenario_type: Mapped[str] = mapped_column(String(64), nullable=False, default="operational_replay")
    baseline_window: Mapped[str] = mapped_column(String(64), nullable=False, default="historical")
    hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsSimulationProjection(Base):
    __tablename__ = "platform_operations_simulation_projections"
    __table_args__ = (
        Index("ix_operations_simulation_projection_seq", "sequence", unique=True),
        Index("ix_operations_simulation_projection_session", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    projection_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    frame_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    projection_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    projection_type: Mapped[str] = mapped_column(String(64), nullable=False)
    projection_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsTimelineBranch(Base):
    __tablename__ = "platform_operations_timeline_branches"
    __table_args__ = (
        Index("ix_operations_timeline_branch_seq", "sequence", unique=True),
        Index("ix_operations_timeline_branch_session", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    branch_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    branch_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    branch_name: Mapped[str] = mapped_column(String(128), nullable=False)
    branch_type: Mapped[str] = mapped_column(String(64), nullable=False, default="deterministic_replay")
    branch_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    base_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    branch_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsForecastComparison(Base):
    __tablename__ = "platform_operations_forecast_comparisons"
    __table_args__ = (
        Index("ix_operations_forecast_comparison_seq", "sequence", unique=True),
        Index("ix_operations_forecast_comparison_session", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    comparison_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    comparison_metric: Mapped[str] = mapped_column(String(64), nullable=False)
    baseline_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    simulated_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    delta_value: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    comparison_status: Mapped[str] = mapped_column(String(32), nullable=False, default="advisory")
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsReplayEvidenceEvent(Base):
    __tablename__ = "platform_operations_replay_evidence_events"
    __table_args__ = (
        Index("ix_operations_replay_evidence_seq", "sequence", unique=True),
        Index("ix_operations_replay_evidence_session", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    evidence_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsContinuitySimulation(Base):
    __tablename__ = "platform_operations_continuity_simulations"
    __table_args__ = (
        Index("ix_operations_continuity_simulation_seq", "sequence", unique=True),
        Index("ix_operations_continuity_simulation_session", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    continuity_simulation_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    continuity_state: Mapped[str] = mapped_column(String(64), nullable=False, default="stable")
    continuity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    validation_checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernancePrediction(Base):
    __tablename__ = "platform_operations_governance_predictions"
    __table_args__ = (
        Index("ix_operations_governance_prediction_seq", "sequence", unique=True),
        Index("ix_operations_governance_prediction_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    prediction_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    prediction_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    governance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prediction_label: Mapped[str] = mapped_column(String(32), nullable=False, default="stable")
    prediction_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsConstraintProfile(Base):
    __tablename__ = "platform_operations_constraint_profiles"
    __table_args__ = (
        Index("ix_operations_constraint_profile_seq", "sequence", unique=True),
        Index("ix_operations_constraint_profile_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    constraint_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    constraint_status: Mapped[str] = mapped_column(String(32), nullable=False, default="stable")
    pressure_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRiskForecast(Base):
    __tablename__ = "platform_operations_risk_forecasts"
    __table_args__ = (
        Index("ix_operations_risk_forecast_seq", "sequence", unique=True),
        Index("ix_operations_risk_forecast_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_forecast_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    risk_domain: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    forecast_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsCapacityPrediction(Base):
    __tablename__ = "platform_operations_capacity_predictions"
    __table_args__ = (
        Index("ix_operations_capacity_prediction_seq", "sequence", unique=True),
        Index("ix_operations_capacity_prediction_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    capacity_prediction_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    capacity_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    projected_capacity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pressure_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    prediction_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceDriftEvent(Base):
    __tablename__ = "platform_operations_governance_drift_events"
    __table_args__ = (
        Index("ix_operations_governance_drift_seq", "sequence", unique=True),
        Index("ix_operations_governance_drift_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    drift_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    drift_dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    drift_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    drift_status: Mapped[str] = mapped_column(String(32), nullable=False, default="stable")
    drift_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsOptimizationRecommendation(Base):
    __tablename__ = "platform_operations_optimization_recommendations"
    __table_args__ = (
        Index("ix_operations_optimization_recommendation_seq", "sequence", unique=True),
        Index("ix_operations_optimization_recommendation_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    recommendation_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recommendation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    recommendation_title: Mapped[str] = mapped_column(String(128), nullable=False)
    recommendation_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsAnomalyForecast(Base):
    __tablename__ = "platform_operations_anomaly_forecasts"
    __table_args__ = (
        Index("ix_operations_anomaly_forecast_seq", "sequence", unique=True),
        Index("ix_operations_anomaly_forecast_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    anomaly_forecast_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    anomaly_type: Mapped[str] = mapped_column(String(64), nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    anomaly_severity: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    forecast_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsConstraintViolationProjection(Base):
    __tablename__ = "platform_operations_constraint_violation_projections"
    __table_args__ = (
        Index("ix_operations_constraint_violation_seq", "sequence", unique=True),
        Index("ix_operations_constraint_violation_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    violation_projection_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    constraint_name: Mapped[str] = mapped_column(String(64), nullable=False)
    violation_probability: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    mitigation_priority: Mapped[str] = mapped_column(String(32), nullable=False, default="review")
    projection_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceTrend(Base):
    __tablename__ = "platform_operations_governance_trends"
    __table_args__ = (
        Index("ix_operations_governance_trend_seq", "sequence", unique=True),
        Index("ix_operations_governance_trend_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    trend_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    trend_metric: Mapped[str] = mapped_column(String(64), nullable=False)
    trend_direction: Mapped[str] = mapped_column(String(32), nullable=False, default="stable")
    trend_slope: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trend_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsDecisionProvenance(Base):
    __tablename__ = "platform_operations_decision_provenance"
    __table_args__ = (
        Index("ix_operations_decision_provenance_seq", "sequence", unique=True),
        Index("ix_operations_decision_provenance_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    provenance_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    decision_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    provenance_status: Mapped[str] = mapped_column(String(32), nullable=False, default="traceable")
    provenance_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceMemory(Base):
    __tablename__ = "platform_operations_governance_memory"
    __table_args__ = (
        Index("ix_operations_governance_memory_seq", "sequence", unique=True),
        Index("ix_operations_governance_memory_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    memory_window: Mapped[str] = mapped_column(String(64), nullable=False)
    memory_density: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    memory_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsAdvisoryReasoningChain(Base):
    __tablename__ = "platform_operations_advisory_reasoning_chains"
    __table_args__ = (
        Index("ix_operations_reasoning_chain_seq", "sequence", unique=True),
        Index("ix_operations_reasoning_chain_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning_chain_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    chain_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chain_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceRationale(Base):
    __tablename__ = "platform_operations_governance_rationales"
    __table_args__ = (
        Index("ix_operations_governance_rationale_seq", "sequence", unique=True),
        Index("ix_operations_governance_rationale_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    rationale_type: Mapped[str] = mapped_column(String(64), nullable=False)
    rationale_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    rationale_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsOperationalAncestry(Base):
    __tablename__ = "platform_operations_operational_ancestry"
    __table_args__ = (
        Index("ix_operations_operational_ancestry_seq", "sequence", unique=True),
        Index("ix_operations_operational_ancestry_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    ancestry_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    ancestry_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    ancestry_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ancestry_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsTrendMemory(Base):
    __tablename__ = "platform_operations_trend_memory"
    __table_args__ = (
        Index("ix_operations_trend_memory_seq", "sequence", unique=True),
        Index("ix_operations_trend_memory_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    trend_memory_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    trend_window: Mapped[str] = mapped_column(String(64), nullable=False)
    trend_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    trend_memory_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceExplanation(Base):
    __tablename__ = "platform_operations_governance_explanations"
    __table_args__ = (
        Index("ix_operations_governance_explanation_seq", "sequence", unique=True),
        Index("ix_operations_governance_explanation_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    explanation_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    explanation_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    explanation_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRecommendationLineage(Base):
    __tablename__ = "platform_operations_recommendation_lineage"
    __table_args__ = (
        Index("ix_operations_recommendation_lineage_seq", "sequence", unique=True),
        Index("ix_operations_recommendation_lineage_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendation_lineage_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    lineage_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    lineage_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lineage_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsDecisionSnapshot(Base):
    __tablename__ = "platform_operations_decision_snapshots"
    __table_args__ = (
        Index("ix_operations_decision_snapshot_seq", "sequence", unique=True),
        Index("ix_operations_decision_snapshot_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_snapshot_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    decision_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsHistoricalGovernanceState(Base):
    __tablename__ = "platform_operations_historical_governance_states"
    __table_args__ = (
        Index("ix_operations_historical_governance_state_seq", "sequence", unique=True),
        Index("ix_operations_historical_governance_state_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    historical_state_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    state_window: Mapped[str] = mapped_column(String(64), nullable=False)
    state_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    state_json: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsPolicyConstraint(Base):
    __tablename__ = "platform_operations_policy_constraints"
    __table_args__ = (
        Index("ix_operations_policy_constraint_seq", "sequence", unique=True),
        Index("ix_operations_policy_constraint_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    scenario_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    framework_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    regulation_family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    policy_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    operational_domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_requirements: Mapped[str] = mapped_column(Text, nullable=False)
    rationale_template: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsPolicyConstraintVersion(Base):
    __tablename__ = "platform_operations_policy_constraint_versions"
    __table_args__ = (
        Index("ix_operations_policy_constraint_version_seq", "sequence", unique=True),
        Index("ix_operations_policy_constraint_version_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_version_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version_label: Mapped[str] = mapped_column(String(32), nullable=False)
    version_status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    version_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRegulatoryFramework(Base):
    __tablename__ = "platform_operations_regulatory_frameworks"
    __table_args__ = (
        Index("ix_operations_regulatory_framework_seq", "sequence", unique=True),
        Index("ix_operations_regulatory_framework_scope", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    framework_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    framework_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    regulation_family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    framework_priority: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    framework_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsFrameworkRuleMapping(Base):
    __tablename__ = "platform_operations_framework_rule_mappings"
    __table_args__ = (
        Index("ix_operations_framework_rule_mapping_seq", "sequence", unique=True),
        Index("ix_operations_framework_rule_mapping_scope", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    framework_rule_mapping_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    framework_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    regulation_family: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    operational_domain: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_requirements: Mapped[str] = mapped_column(Text, nullable=False)
    mapping_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceRationaleChain(Base):
    __tablename__ = "platform_operations_governance_rationale_chains"
    __table_args__ = (
        Index("ix_operations_governance_rationale_chain_seq", "sequence", unique=True),
        Index("ix_operations_governance_rationale_chain_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale_chain_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    decision_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    chain_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    chain_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rationale_segment_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    chain_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsConstraintEvaluation(Base):
    __tablename__ = "platform_operations_constraint_evaluations"
    __table_args__ = (
        Index("ix_operations_constraint_evaluation_seq", "sequence", unique=True),
        Index("ix_operations_constraint_evaluation_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_evaluation_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    framework_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evaluation_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    evaluation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="review")
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    evaluation_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsConstraintViolation(Base):
    __tablename__ = "platform_operations_constraint_violations"
    __table_args__ = (
        Index("ix_operations_constraint_violation_event_seq", "sequence", unique=True),
        Index("ix_operations_constraint_violation_event_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_violation_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    framework_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    violation_level: Mapped[str] = mapped_column(String(32), nullable=False, default="low")
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    violation_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsPolicyScoreSnapshot(Base):
    __tablename__ = "platform_operations_policy_score_snapshots"
    __table_args__ = (
        Index("ix_operations_policy_score_snapshot_seq", "sequence", unique=True),
        Index("ix_operations_policy_score_snapshot_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_score_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    policy_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    weighted_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_status: Mapped[str] = mapped_column(String(32), nullable=False, default="stable")
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    score_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsRegulatoryEvidenceRef(Base):
    __tablename__ = "platform_operations_regulatory_evidence_refs"
    __table_args__ = (
        Index("ix_operations_regulatory_evidence_ref_seq", "sequence", unique=True),
        Index("ix_operations_regulatory_evidence_ref_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    regulatory_evidence_ref_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    policy_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    framework_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    evidence_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class OperationsGovernanceDecisionTrace(Base):
    __tablename__ = "platform_operations_governance_decision_traces"
    __table_args__ = (
        Index("ix_operations_governance_decision_trace_seq", "sequence", unique=True),
        Index("ix_operations_governance_decision_trace_scope", "organization_id", "replay_session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    governance_decision_trace_event_id: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    replay_session_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    decision_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    policy_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    framework_name: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trace_stage: Mapped[str] = mapped_column(String(64), nullable=False)
    ancestry_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    rationale_segment_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    trace_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    immutable_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    correlation_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    replay_parent_event_id: Mapped[str | None] = mapped_column(String(96), nullable=True)
    replay_lineage_ref: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    immutable_audit_ref: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_role: Mapped[str] = mapped_column(String(32), nullable=False)
    advisory_flags: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

