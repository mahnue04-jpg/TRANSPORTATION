"""ecosystem integration tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-09 00:00:00
"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_integrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("account_email", sa.String(320), nullable=True),
        sa.Column("access_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("meta_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_integrations_user_service", "platform_integrations", ["user_id", "service"])

    op.create_table(
        "platform_email_drafts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="smtp"),
        sa.Column("to_recipients", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("cc_recipients", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("bcc_recipients", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("subject", sa.String(512), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("attachments_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_email_drafts_user_updated", "platform_email_drafts", ["user_id", "updated_at"])

    op.create_table(
        "platform_calendar_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="local"),
        sa.Column("external_event_id", sa.String(256), nullable=True),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="UTC"),
        sa.Column("attendees_json", sa.Text(), nullable=True),
        sa.Column("reminder_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="confirmed"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_calendar_events_user_start", "platform_calendar_events", ["user_id", "start_time"])

    op.create_table(
        "platform_search_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("query_key", sa.String(128), nullable=False),
        sa.Column("query_text", sa.String(512), nullable=False),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("news_mode", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("response_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_search_cache_query_created", "platform_search_cache", ["query_key", "created_at"])

    op.create_table(
        "platform_memory_vectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("source", sa.String(64), nullable=False, server_default="conversation"),
        sa.Column("text_chunk", sa.Text(), nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_memory_vectors_user_created", "platform_memory_vectors", ["user_id", "created_at"])

    op.create_table(
        "platform_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reusable_prompt", sa.Text(), nullable=True),
        sa.Column("action_chain_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_workflows_user_updated", "platform_workflows", ["user_id", "updated_at"])

    op.create_table(
        "platform_workflow_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("step_results_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="completed"),
        sa.Column("error_msg", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_workflow_runs_workflow_created", "platform_workflow_runs", ["workflow_id", "created_at"])


def downgrade() -> None:
    op.drop_table("platform_workflow_runs")
    op.drop_table("platform_workflows")
    op.drop_table("platform_memory_vectors")
    op.drop_table("platform_search_cache")
    op.drop_table("platform_calendar_events")
    op.drop_table("platform_email_drafts")
    op.drop_table("platform_integrations")
