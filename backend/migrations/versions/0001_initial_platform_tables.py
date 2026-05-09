"""Initial platform tables

Creates all 8 platform_* tables:
  platform_users, platform_conversations, platform_messages,
  platform_uploads, platform_memory, platform_provider_logs,
  platform_refresh_tokens, platform_audit_logs

Revision ID: 0001
Revises: None
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── platform_users ──────────────────────────────────────────────────────
    op.create_table(
        "platform_users",
        sa.Column("id",              sa.String(36),    primary_key=True),
        sa.Column("email",           sa.String(320),   nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(256),   nullable=False),
        sa.Column("display_name",    sa.String(128),   nullable=True),
        sa.Column("is_active",       sa.Boolean(),     nullable=False, server_default="1"),
        sa.Column("is_verified",     sa.Boolean(),     nullable=False, server_default="0"),
        sa.Column("created_at",      sa.DateTime(),    nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_login",      sa.DateTime(),    nullable=True),
    )

    # ── platform_conversations ───────────────────────────────────────────────
    op.create_table(
        "platform_conversations",
        sa.Column("id",         sa.String(36),  primary_key=True),
        sa.Column("user_id",    sa.String(36),  sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title",      sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(),  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(),  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # ── platform_messages ───────────────────────────────────────────────────
    op.create_table(
        "platform_messages",
        sa.Column("id",              sa.Integer(),   primary_key=True, autoincrement=True),
        sa.Column("conversation_id", sa.String(36),  sa.ForeignKey("platform_conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id",         sa.String(36),  nullable=True),
        sa.Column("role",            sa.String(16),  nullable=False),
        sa.Column("content",         sa.Text(),      nullable=False),
        sa.Column("created_at",      sa.DateTime(),  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # ── platform_uploads ────────────────────────────────────────────────────
    op.create_table(
        "platform_uploads",
        sa.Column("id",            sa.String(36),  primary_key=True),
        sa.Column("user_id",       sa.String(36),  sa.ForeignKey("platform_users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("filename",      sa.String(512), nullable=False),
        sa.Column("content_type",  sa.String(128), nullable=False),
        sa.Column("size_bytes",    sa.Integer(),   nullable=False),
        sa.Column("ocr_method",    sa.String(64),  nullable=True),
        sa.Column("ocr_confidence",sa.Float(),     nullable=True),
        sa.Column("ocr_word_count",sa.Integer(),   nullable=True),
        sa.Column("created_at",    sa.DateTime(),  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # ── platform_memory ─────────────────────────────────────────────────────
    op.create_table(
        "platform_memory",
        sa.Column("id",         sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("user_id",    sa.String(36), sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("summary",    sa.Text(),     nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    # ── platform_provider_logs ───────────────────────────────────────────────
    op.create_table(
        "platform_provider_logs",
        sa.Column("id",            sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("provider_name", sa.String(64), nullable=False),
        sa.Column("success",       sa.Boolean(),  nullable=False),
        sa.Column("latency_ms",    sa.Integer(),  nullable=True),
        sa.Column("error_msg",     sa.Text(),     nullable=True),
        sa.Column("endpoint",      sa.String(512),nullable=True),
        sa.Column("created_at",    sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_provider_logs_name_ts", "provider_name", "created_at"),
    )

    # ── platform_refresh_tokens ──────────────────────────────────────────────
    op.create_table(
        "platform_refresh_tokens",
        sa.Column("id",         sa.String(36),  primary_key=True),
        sa.Column("user_id",    sa.String(36),  sa.ForeignKey("platform_users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(256), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(),  nullable=False),
        sa.Column("created_at", sa.DateTime(),  nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("revoked",    sa.Boolean(),   nullable=False, server_default="0"),
    )

    # ── platform_audit_logs ──────────────────────────────────────────────────
    op.create_table(
        "platform_audit_logs",
        sa.Column("id",          sa.Integer(),  primary_key=True, autoincrement=True),
        sa.Column("user_id",     sa.String(36), nullable=True),
        sa.Column("request_id",  sa.String(36), nullable=True),
        sa.Column("action",      sa.String(64), nullable=True),
        sa.Column("path",        sa.String(512),nullable=False),
        sa.Column("method",      sa.String(10), nullable=False),
        sa.Column("status_code", sa.Integer(),  nullable=False),
        sa.Column("ip_address",  sa.String(64), nullable=True),
        sa.Column("latency_ms",  sa.Integer(),  nullable=True),
        sa.Column("created_at",  sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Index("ix_audit_logs_user_ts", "user_id", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("platform_audit_logs")
    op.drop_table("platform_refresh_tokens")
    op.drop_table("platform_provider_logs")
    op.drop_table("platform_memory")
    op.drop_table("platform_uploads")
    op.drop_table("platform_messages")
    op.drop_table("platform_conversations")
    op.drop_table("platform_users")
