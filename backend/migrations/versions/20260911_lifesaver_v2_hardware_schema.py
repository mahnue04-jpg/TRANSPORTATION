"""Lifesaver AI Care Cloud V2 hardware foundation schema.

Revision ID: 20260911_lifesaver_v2_hardware_schema
Revises: 20260911_lifesaver_phase2_schema

Scope:
    Additive V2 objects only:
      A. lifesaver_devices
      B. lifesaver_device_commands
      C. lifesaver_device_events
      D. lifesaver_video_sessions

Safety:
    - Inspector-guarded create
    - No foreign keys to Health ISF, Delivery, Freight, Nova, or payments
    - No media blobs, tokens, or vendor device credentials
    - Downgrade drops only these four lifesaver_* tables

Do not apply this revision to production from this pass. Local / throwaway DBs only.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_lifesaver_v2_hardware_schema"
down_revision = "20260911_lifesaver_phase2_schema"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _names() -> set[str]:
    return set(_inspector().get_table_names())


def _indexes(table: str) -> set[str]:
    inspector = _inspector()
    if table not in set(inspector.get_table_names()):
        return set()
    return {item["name"] for item in inspector.get_indexes(table) if item.get("name")}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def upgrade() -> None:
    names = _names()

    if "lifesaver_devices" not in names:
        op.create_table(
            "lifesaver_devices",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=True),
            sa.Column("device_type", sa.String(32), nullable=False),
            sa.Column("display_name", sa.String(160), nullable=False),
            sa.Column("serial_number", sa.String(64), nullable=True),
            sa.Column("firmware_version", sa.String(32), nullable=True),
            sa.Column("software_version", sa.String(32), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="OFFLINE"),
            sa.Column("adapter_name", sa.String(64), nullable=False, server_default="simulated"),
            sa.Column("state_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_lifesaver_devices_organization_id", "lifesaver_devices", ["organization_id"])
        op.create_index("ix_lifesaver_devices_profile_id", "lifesaver_devices", ["profile_id"])
        op.create_index("ix_lifesaver_devices_org_profile", "lifesaver_devices", ["organization_id", "profile_id"])
        op.create_index("ix_lifesaver_devices_org_type", "lifesaver_devices", ["organization_id", "device_type"])
        op.create_index("uq_lifesaver_device_org_serial", "lifesaver_devices", ["organization_id", "serial_number"], unique=True)

    if "lifesaver_device_commands" not in names:
        op.create_table(
            "lifesaver_device_commands",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("actor_user_id", sa.String(36), nullable=False),
            sa.Column("command", sa.String(64), nullable=False),
            sa.Column("outcome", sa.String(32), nullable=False, server_default="accepted"),
            sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_lifesaver_device_commands_organization_id", "lifesaver_device_commands", ["organization_id"])
        op.create_index("ix_lifesaver_device_commands_device_id", "lifesaver_device_commands", ["device_id"])
        op.create_index("ix_lifesaver_device_commands_profile_id", "lifesaver_device_commands", ["profile_id"])
        op.create_index("ix_lifesaver_device_commands_created_at", "lifesaver_device_commands", ["created_at"])
        op.create_index("ix_lifesaver_dcmd_org_device", "lifesaver_device_commands", ["organization_id", "device_id", "created_at"])

    if "lifesaver_device_events" not in names:
        op.create_table(
            "lifesaver_device_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="needs_human_review"),
            sa.Column("summary", sa.String(256), nullable=False),
            sa.Column("emergency_services_contacted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_lifesaver_device_events_organization_id", "lifesaver_device_events", ["organization_id"])
        op.create_index("ix_lifesaver_device_events_device_id", "lifesaver_device_events", ["device_id"])
        op.create_index("ix_lifesaver_device_events_profile_id", "lifesaver_device_events", ["profile_id"])
        op.create_index("ix_lifesaver_device_events_created_at", "lifesaver_device_events", ["created_at"])
        op.create_index("ix_lifesaver_devent_org_device", "lifesaver_device_events", ["organization_id", "device_id", "created_at"])

    if "lifesaver_video_sessions" not in names:
        op.create_table(
            "lifesaver_video_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("requested_by_user_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(32), nullable=False, server_default="requested"),
            sa.Column("provider", sa.String(32), nullable=False, server_default="local_simulation"),
            sa.Column("privacy_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("media_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_lifesaver_video_sessions_organization_id", "lifesaver_video_sessions", ["organization_id"])
        op.create_index("ix_lifesaver_video_sessions_device_id", "lifesaver_video_sessions", ["device_id"])
        op.create_index("ix_lifesaver_video_sessions_profile_id", "lifesaver_video_sessions", ["profile_id"])
        op.create_index("ix_lifesaver_vsession_org_device", "lifesaver_video_sessions", ["organization_id", "device_id"])


def downgrade() -> None:
    names = _names()
    for table in (
        "lifesaver_video_sessions",
        "lifesaver_device_events",
        "lifesaver_device_commands",
        "lifesaver_devices",
    ):
        if table in names:
            op.drop_table(table)
