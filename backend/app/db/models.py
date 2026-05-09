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
