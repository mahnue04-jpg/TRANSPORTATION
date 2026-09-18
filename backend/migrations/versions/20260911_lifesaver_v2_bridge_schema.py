"""Lifesaver AI Care Cloud V2 hardware-bridge schema.

Revision ID: 20260911_lifesaver_v2_bridge_schema
Revises: 20260911_lifesaver_v2_hardware_schema

Scope:
    Additive V2 objects and columns only:
      A. lifesaver_device_pairings
      B. lifesaver_device_capabilities
      C. lifesaver_safety_events
      D. lifesaver_hardware_sessions
      E. extra columns on existing V2 hardware tables

Safety:
    - Inspector-guarded create / alter
    - No foreign keys to Health ISF, Delivery, Freight, Nova, or payments
    - No media blobs or live vendor credentials
    - Downgrade drops only these four new lifesaver_* tables and added columns

Do not apply this revision to production from this pass. Local / throwaway DBs only.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_lifesaver_v2_bridge_schema"
down_revision = "20260911_lifesaver_v2_hardware_schema"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _names() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    inspector = _inspector()
    if table not in set(inspector.get_table_names()):
        return set()
    return {item["name"] for item in inspector.get_columns(table)}


def _indexes(table: str) -> set[str]:
    inspector = _inspector()
    if table not in set(inspector.get_table_names()):
        return set()
    return {item["name"] for item in inspector.get_indexes(table) if item.get("name")}


def _create_index(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns)


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    names = _names()

    if "lifesaver_devices" in names:
        _add_column("lifesaver_devices", sa.Column("adapter_type", sa.String(32), nullable=False, server_default="simulated"))
        _add_column("lifesaver_devices", sa.Column("pairing_state", sa.String(32), nullable=False, server_default="PAIRED"))
        _add_column("lifesaver_devices", sa.Column("hardware_model", sa.String(64), nullable=True))
        _add_column("lifesaver_devices", sa.Column("local_ip", sa.String(64), nullable=True))
        _add_column("lifesaver_devices", sa.Column("pairing_token", sa.String(64), nullable=True))

    if "lifesaver_device_commands" in names:
        _add_column("lifesaver_device_commands", sa.Column("client_command_id", sa.String(64), nullable=True))
        _add_column("lifesaver_device_commands", sa.Column("lifecycle_status", sa.String(32), nullable=False, server_default="COMPLETED"))
        _add_column("lifesaver_device_commands", sa.Column("adapter_type", sa.String(32), nullable=False, server_default="simulated"))
        _add_column("lifesaver_device_commands", sa.Column("response_code", sa.String(32), nullable=True))
        _add_column("lifesaver_device_commands", sa.Column("error_message", sa.String(256), nullable=True))
        _add_column("lifesaver_device_commands", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        _add_column("lifesaver_device_commands", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        _create_index("ix_lifesaver_device_commands_client_command_id", "lifesaver_device_commands", ["client_command_id"])

    if "lifesaver_device_events" in names:
        _add_column("lifesaver_device_events", sa.Column("confidence", sa.String(16), nullable=True))
        _add_column("lifesaver_device_events", sa.Column("review_status", sa.String(32), nullable=False, server_default="NEEDS_REVIEW"))
        _add_column("lifesaver_device_events", sa.Column("escalation_state", sa.String(32), nullable=False, server_default="none"))
        _add_column("lifesaver_device_events", sa.Column("acknowledged_by", sa.String(36), nullable=True))
        _add_column("lifesaver_device_events", sa.Column("source", sa.String(32), nullable=False, server_default="simulated"))
        _add_column("lifesaver_device_events", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))

    if "lifesaver_video_sessions" in names:
        _add_column("lifesaver_video_sessions", sa.Column("session_phase", sa.String(32), nullable=False, server_default="REQUESTED"))
        _add_column("lifesaver_video_sessions", sa.Column("participant_role", sa.String(32), nullable=False, server_default="user"))

    if "lifesaver_device_pairings" not in names:
        op.create_table(
            "lifesaver_device_pairings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=True),
            sa.Column("device_type", sa.String(32), nullable=False),
            sa.Column("hardware_model", sa.String(64), nullable=True),
            sa.Column("serial_number", sa.String(64), nullable=True),
            sa.Column("local_ip", sa.String(64), nullable=True),
            sa.Column("pairing_state", sa.String(32), nullable=False, server_default="DISCOVERED"),
            sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("pairing_token", sa.String(64), nullable=True),
            sa.Column("capabilities_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_device_pairings_organization_id", "lifesaver_device_pairings", ["organization_id"])
        _create_index("ix_lifesaver_device_pairings_profile_id", "lifesaver_device_pairings", ["profile_id"])
        _create_index("ix_lifesaver_device_pairings_device_id", "lifesaver_device_pairings", ["device_id"])
        _create_index("ix_lifesaver_pair_org_state", "lifesaver_device_pairings", ["organization_id", "pairing_state"])

    if "lifesaver_device_capabilities" not in names:
        op.create_table(
            "lifesaver_device_capabilities",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=False),
            sa.Column("capability_name", sa.String(64), nullable=False),
            sa.Column("present", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_device_capabilities_organization_id", "lifesaver_device_capabilities", ["organization_id"])
        _create_index("ix_lifesaver_device_capabilities_device_id", "lifesaver_device_capabilities", ["device_id"])
        _create_index("ix_lifesaver_dcap_org_device", "lifesaver_device_capabilities", ["organization_id", "device_id"])

    if "lifesaver_safety_events" not in names:
        op.create_table(
            "lifesaver_safety_events",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("event_type", sa.String(64), nullable=False),
            sa.Column("confidence", sa.String(16), nullable=False, server_default="low"),
            sa.Column("source", sa.String(32), nullable=False, server_default="simulated"),
            sa.Column("review_status", sa.String(32), nullable=False, server_default="NEEDS_REVIEW"),
            sa.Column("escalation_state", sa.String(32), nullable=False, server_default="none"),
            sa.Column("summary", sa.String(256), nullable=False),
            sa.Column("simulated", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("emergency_services_contacted", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("acknowledged_by", sa.String(36), nullable=True),
            sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_safety_events_organization_id", "lifesaver_safety_events", ["organization_id"])
        _create_index("ix_lifesaver_safety_events_device_id", "lifesaver_safety_events", ["device_id"])
        _create_index("ix_lifesaver_safety_events_profile_id", "lifesaver_safety_events", ["profile_id"])
        _create_index("ix_lifesaver_safety_events_created_at", "lifesaver_safety_events", ["created_at"])
        _create_index("ix_lifesaver_safety_org_device", "lifesaver_safety_events", ["organization_id", "device_id", "created_at"])

    if "lifesaver_hardware_sessions" not in names:
        op.create_table(
            "lifesaver_hardware_sessions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("device_id", sa.String(36), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("video_session_id", sa.String(36), nullable=True),
            sa.Column("session_phase", sa.String(32), nullable=False, server_default="REQUESTED"),
            sa.Column("participant_role", sa.String(32), nullable=False, server_default="user"),
            sa.Column("media_stored", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_hardware_sessions_organization_id", "lifesaver_hardware_sessions", ["organization_id"])
        _create_index("ix_lifesaver_hardware_sessions_device_id", "lifesaver_hardware_sessions", ["device_id"])
        _create_index("ix_lifesaver_hsession_org_device", "lifesaver_hardware_sessions", ["organization_id", "device_id"])


def downgrade() -> None:
    names = _names()
    for table in (
        "lifesaver_hardware_sessions",
        "lifesaver_safety_events",
        "lifesaver_device_capabilities",
        "lifesaver_device_pairings",
    ):
        if table in names:
            op.drop_table(table)

    if "lifesaver_video_sessions" in _names():
        cols = _columns("lifesaver_video_sessions")
        with op.batch_alter_table("lifesaver_video_sessions") as batch:
            if "participant_role" in cols:
                batch.drop_column("participant_role")
            if "session_phase" in cols:
                batch.drop_column("session_phase")

    if "lifesaver_device_events" in _names():
        cols = _columns("lifesaver_device_events")
        with op.batch_alter_table("lifesaver_device_events") as batch:
            for name in ("acknowledged_at", "source", "acknowledged_by", "escalation_state", "review_status", "confidence"):
                if name in cols:
                    batch.drop_column(name)

    if "lifesaver_device_commands" in _names():
        cols = _columns("lifesaver_device_commands")
        with op.batch_alter_table("lifesaver_device_commands") as batch:
            for name in (
                "completed_at",
                "started_at",
                "error_message",
                "response_code",
                "adapter_type",
                "lifecycle_status",
                "client_command_id",
            ):
                if name in cols:
                    batch.drop_column(name)

    if "lifesaver_devices" in _names():
        cols = _columns("lifesaver_devices")
        with op.batch_alter_table("lifesaver_devices") as batch:
            for name in ("pairing_token", "local_ip", "hardware_model", "pairing_state", "adapter_type"):
                if name in cols:
                    batch.drop_column(name)
