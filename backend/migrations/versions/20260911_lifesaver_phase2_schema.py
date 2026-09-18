"""Lifesaver AI Care Cloud V1 Phase 2 schema.

Revision ID: 20260911_lifesaver_phase2_schema
Revises: 20260911_lifesaver_phase1_schema

Scope:
    Additive Phase 2 objects only:
      A. lifesaver_transport_requests
      B. lifesaver_notification_outbox
      C. lifesaver_health_readings.device_alias (nullable)
      D. lifesaver_health_readings.ingestion_status (NOT NULL, default 'accepted')

Safety:
    - Inspector-guarded create / ALTER
    - No foreign keys to Health ISF ride tables
    - appointment_id is a nullable string reference, not an FK
    - No credentials, tokens, message bodies, or reading values beyond existing Phase 1 columns
    - Downgrade drops only Phase 2 tables and the two additive reading columns

Do not apply this revision to production from this closeout. Prepare only.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260911_lifesaver_phase2_schema"
down_revision = "20260911_lifesaver_phase1_schema"
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
    return {col["name"] for col in inspector.get_columns(table)}


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

    if "lifesaver_transport_requests" not in names:
        op.create_table(
            "lifesaver_transport_requests",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("appointment_id", sa.String(36), nullable=True),
            sa.Column("pickup_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("pickup_label", sa.String(160), nullable=False),
            sa.Column("destination_label", sa.String(160), nullable=False),
            sa.Column("accessibility_needs", sa.String(256), nullable=True),
            sa.Column("mobility_note", sa.String(256), nullable=True),
            sa.Column("companion_needed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status", sa.String(32), nullable=False, server_default="requested"),
            sa.Column("created_by_user_id", sa.String(36), nullable=False),
            sa.Column("confirmed_by_user_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_treq_organization_id", "lifesaver_transport_requests", ["organization_id"])
        _create_index("ix_lifesaver_treq_profile_id", "lifesaver_transport_requests", ["profile_id"])
        _create_index("ix_lifesaver_treq_appointment_id", "lifesaver_transport_requests", ["appointment_id"])
        _create_index("ix_lifesaver_treq_status", "lifesaver_transport_requests", ["status"])
        _create_index(
            "ix_lifesaver_treq_org_profile",
            "lifesaver_transport_requests",
            ["organization_id", "profile_id", "status"],
        )

    if "lifesaver_notification_outbox" not in names:
        op.create_table(
            "lifesaver_notification_outbox",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("organization_id", sa.String(64), nullable=False),
            sa.Column("profile_id", sa.String(36), nullable=False),
            sa.Column("recipient_profile_id", sa.String(36), nullable=True),
            sa.Column("recipient_role", sa.String(32), nullable=False, server_default="caregiver"),
            sa.Column("notification_type", sa.String(64), nullable=False),
            sa.Column("channel", sa.String(16), nullable=False, server_default="email"),
            sa.Column("status", sa.String(32), nullable=False, server_default="queued_local"),
            sa.Column("title", sa.String(160), nullable=False),
            sa.Column("reason", sa.String(256), nullable=True),
            sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        _create_index("ix_lifesaver_outbox_organization_id", "lifesaver_notification_outbox", ["organization_id"])
        _create_index("ix_lifesaver_outbox_profile_id", "lifesaver_notification_outbox", ["profile_id"])
        _create_index("ix_lifesaver_outbox_recipient_profile_id", "lifesaver_notification_outbox", ["recipient_profile_id"])
        _create_index("ix_lifesaver_outbox_status", "lifesaver_notification_outbox", ["status"])
        _create_index("ix_lifesaver_outbox_created_at", "lifesaver_notification_outbox", ["created_at"])
        _create_index(
            "ix_lifesaver_outbox_org_profile_status",
            "lifesaver_notification_outbox",
            ["organization_id", "profile_id", "status"],
        )

    reading_cols = _columns("lifesaver_health_readings")
    if "lifesaver_health_readings" in _names():
        if "device_alias" not in reading_cols:
            op.add_column(
                "lifesaver_health_readings",
                sa.Column("device_alias", sa.String(64), nullable=True),
            )
        if "ingestion_status" not in reading_cols:
            op.add_column(
                "lifesaver_health_readings",
                sa.Column(
                    "ingestion_status",
                    sa.String(32),
                    nullable=False,
                    server_default="accepted",
                ),
            )


def downgrade() -> None:
    """Remove Phase 2 objects only. Phase 1 lifesaver_* tables remain."""
    names = _names()
    if "lifesaver_notification_outbox" in names:
        op.drop_table("lifesaver_notification_outbox")
    if "lifesaver_transport_requests" in names:
        op.drop_table("lifesaver_transport_requests")

    if "lifesaver_health_readings" in names:
        cols = _columns("lifesaver_health_readings")
        with op.batch_alter_table("lifesaver_health_readings") as batch:
            if "ingestion_status" in cols:
                batch.drop_column("ingestion_status")
            if "device_alias" in cols:
                batch.drop_column("device_alias")
