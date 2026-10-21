"""Sandbox subscriber FAQ tickets. Nothing is sent and billing stays off.

Revision ID: 20261018_casting_faq
Revises: 20261015_casting_journey

Safe plan, dev and disposable databases only:

- Production and prod environment names return without DDL.
- If the casting organization or platform user table is absent, upgrade returns.
- Downgrade drops only ``nova_casting_faq_tickets``.
- Rows cannot store a real delivery flag, credential, or billing collection.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261018_casting_faq"
down_revision = "20261015_casting_journey"
branch_labels = None
depends_on = None

_TABLE = "nova_casting_faq_tickets"
_PARENTS = ("platform_users", "nova_casting_organizations")


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
    if any(name not in present for name in _PARENTS) or _TABLE in present:
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(48), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("nova_casting_organizations.id"), nullable=False),
        sa.Column("asker_id", sa.String(36), sa.ForeignKey("platform_users.id"), nullable=False),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("topic", sa.String(40), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("human_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("external_delivery", sa.String(8), nullable=False, server_default="false"),
        sa.Column("credentials_stored", sa.String(8), nullable=False, server_default="false"),
        sa.Column("billing_collected", sa.String(8), nullable=False, server_default="false"),
        sa.Column("acknowledged_by", sa.String(36), nullable=False, server_default=""),
        sa.Column("acknowledged_at", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.CheckConstraint(
            "status IN ('answered', 'waiting_for_person', 'acknowledged')",
            name="ck_nova_casting_faq_status",
        ),
        sa.CheckConstraint("external_delivery = 'false'", name="ck_nova_casting_faq_delivery"),
        sa.CheckConstraint("credentials_stored = 'false'", name="ck_nova_casting_faq_credentials"),
        sa.CheckConstraint("billing_collected = 'false'", name="ck_nova_casting_faq_billing"),
        sa.CheckConstraint("length(question) > 0 AND length(question) <= 500", name="ck_nova_casting_faq_question"),
    )
    op.create_index("ix_nova_casting_faq_org", _TABLE, ["organization_id", "created_at"])


def downgrade():
    if _production_schema_locked():
        return
    bind = op.get_bind()
    if _TABLE not in _names(bind):
        return
    op.drop_index("ix_nova_casting_faq_org", table_name=_TABLE)
    op.drop_table(_TABLE)
