"""Sandbox invitations, mock transport attempts, and unreleased upload metadata.

Revision ID: 20261015_casting_journey
Revises: 20261014_casting_pilot

Safe plan, dev and disposable databases only:

- Production and prod environment names return without DDL.
- If the pilot parent tables are absent, upgrade returns. It does not create
  them and it does not enable public intake or public media.
- Message delivery stays on the earlier constraint ``delivery_state = 'not_sent'``.
  This revision does not add a sent state.
- Mock media rows store scan metadata only. They have no byte column and
  ``public_url`` is constrained to empty.
- Downgrade drops only the four journey tables.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261015_casting_journey"
down_revision = "20261014_casting_pilot"
branch_labels = None
depends_on = None

_TABLES = (
    "nova_casting_mock_media",
    "nova_casting_mock_attempts",
    "nova_casting_journey_audit",
    "nova_casting_invites",
)
_PARENTS = (
    "platform_users",
    "nova_casting_organizations",
    "nova_casting_campaigns",
    "nova_casting_roles",
    "nova_casting_intakes",
    "nova_casting_pilot_messages",
)


def _production_schema_locked() -> bool:
    import os
    for name in ("AMICOR_ENVIRONMENT", "ENVIRONMENT", "APP_ENV"):
        if os.getenv(name, "").strip().lower() in {"production", "prod"}:
            return True
    return False


def _names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    present = _names(bind)
    if any(name not in present for name in _PARENTS):
        return
    if "nova_casting_invites" not in present:
        op.create_table(
            "nova_casting_invites",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
            sa.Column("tenant_id", sa.String(36), nullable=False),
            sa.Column("campaign_id", sa.String(48), sa.ForeignKey("nova_casting_campaigns.id"), nullable=False),
            sa.Column("role_id", sa.String(48), sa.ForeignKey("nova_casting_roles.id"), nullable=False),
            sa.Column("token", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column("applicant_id", sa.String(36), nullable=False, server_default=""),
            sa.Column("application_id", sa.String(48), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("redeemed_at", sa.String(64), nullable=False, server_default=""),
            sa.CheckConstraint(
                "status IN ('open', 'redeemed', 'expired', 'revoked')",
                name="ck_nova_casting_invite_status",
            ),
            sa.UniqueConstraint("token", name="uq_nova_casting_invite_token"),
        )
        op.create_index("ix_nova_casting_invite_org", "nova_casting_invites", ["organization_id", "campaign_id"])
    if "nova_casting_mock_attempts" not in present:
        op.create_table(
            "nova_casting_mock_attempts",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("message_id", sa.String(48), sa.ForeignKey("nova_casting_pilot_messages.id"), nullable=False),
            sa.Column("attempt_number", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.String(16), nullable=False),
            sa.Column("mock_receipt", sa.String(32), nullable=False, server_default=""),
            sa.Column("failure_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("provider", sa.String(32), nullable=False, server_default="disposable-mock"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.CheckConstraint(
                "outcome IN ('mock_accepted', 'mock_failed', 'suppressed', 'opted_out')",
                name="ck_nova_casting_mock_attempt_outcome",
            ),
            sa.CheckConstraint("provider = 'disposable-mock'", name="ck_nova_casting_mock_attempt_provider"),
            sa.CheckConstraint("attempt_number >= 1", name="ck_nova_casting_mock_attempt_number"),
        )
        op.create_index(
            "ix_nova_casting_mock_attempt_message",
            "nova_casting_mock_attempts",
            ["organization_id", "message_id"],
        )
    if "nova_casting_mock_media" not in present:
        op.create_table(
            "nova_casting_mock_media",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
            sa.Column("application_id", sa.String(48), sa.ForeignKey("nova_casting_intakes.id"), nullable=False),
            sa.Column("applicant_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
            sa.Column("mime_type", sa.String(64), nullable=False),
            sa.Column("byte_size", sa.Integer(), nullable=False),
            sa.Column("scan_status", sa.String(16), nullable=False),
            sa.Column("scan_reason", sa.String(120), nullable=False, server_default=""),
            sa.Column("public_url", sa.String(8), nullable=False, server_default=""),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.CheckConstraint("scan_status IN ('CLEAN', 'REJECTED')", name="ck_nova_casting_mock_media_status"),
            sa.CheckConstraint("public_url = ''", name="ck_nova_casting_mock_media_url"),
            sa.CheckConstraint("byte_size >= 0", name="ck_nova_casting_mock_media_size"),
        )
        op.create_index(
            "ix_nova_casting_mock_media_application",
            "nova_casting_mock_media",
            ["organization_id", "application_id"],
        )
    if "nova_casting_journey_audit" not in present:
        op.create_table(
            "nova_casting_journey_audit",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("actor_id", sa.String(36), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("object_id", sa.String(48), nullable=False),
            sa.Column("occurred_at", sa.String(64), nullable=False),
            sa.CheckConstraint(
                "action IN ('invite.issued', 'invite.redeemed', 'invite.expired', "
                "'mock.dispatched', 'upload.mock_recorded')",
                name="ck_nova_casting_journey_audit_action",
            ),
        )
        op.create_index(
            "ix_nova_casting_journey_audit_org",
            "nova_casting_journey_audit",
            ["organization_id", "occurred_at"],
        )


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    present = _names(bind)
    for name in _TABLES:
        if name in present:
            op.drop_table(name)
