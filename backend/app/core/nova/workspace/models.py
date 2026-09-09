"""Nova-owned workspace tables. Not Health, Delivery, or Freight records."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class NovaWorkspaceProject(Base):
    __tablename__ = "nova_workspace_projects"
    __table_args__ = (
        Index("ix_nova_ws_projects_workspace_id", "workspace_id", unique=True),
        Index("ix_nova_ws_projects_org_owner", "organization_id", "owner_user_id"),
        Index("ix_nova_ws_projects_org_updated", "organization_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NovaWorkspaceFile(Base):
    __tablename__ = "nova_workspace_files"
    __table_args__ = (
        Index("ix_nova_ws_files_file_id", "file_id", unique=True),
        Index("ix_nova_ws_files_org_owner", "organization_id", "owner_user_id"),
        Index("ix_nova_ws_files_workspace", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    file_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    upload_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NovaWorkspaceConversation(Base):
    __tablename__ = "nova_workspace_conversations"
    __table_args__ = (
        Index("ix_nova_ws_conv_id", "conversation_id", unique=True),
        Index("ix_nova_ws_conv_org_owner", "organization_id", "owner_user_id"),
        Index("ix_nova_ws_conv_workspace", "workspace_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    conversation_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(180), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="nova_ask")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NovaWorkspaceMessage(Base):
    __tablename__ = "nova_workspace_messages"
    __table_args__ = (
        Index("ix_nova_ws_msg_conversation", "conversation_id", "created_at"),
        Index("ix_nova_ws_msg_org", "organization_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    message_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    conversation_id: Mapped[str] = mapped_column(String(32), nullable=False)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkspaceSearch(Base):
    __tablename__ = "nova_workspace_searches"
    __table_args__ = (
        Index("ix_nova_ws_search_org_owner", "organization_id", "owner_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    search_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    query: Mapped[str] = mapped_column(String(400), nullable=False)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)


class NovaWorkspaceActivity(Base):
    __tablename__ = "nova_workspace_activity"
    __table_args__ = (
        Index("ix_nova_ws_activity_org_owner", "organization_id", "owner_user_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    activity_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    ref_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False)
