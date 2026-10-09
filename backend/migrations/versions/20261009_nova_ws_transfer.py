"""Recipient-approved Nova Workspace transfers."""
from alembic import op
import sqlalchemy as sa

revision = "20261009_nova_ws_transfer"
down_revision = "20260921_nova_creative_studio"
branch_labels = None
depends_on = None


def upgrade():
    if "nova_workspace_transfers" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table("nova_workspace_transfers",
        sa.Column("transfer_id", sa.String(32), primary_key=True),
        sa.Column("dedup_key", sa.String(64), nullable=False, unique=True),
        sa.Column("source_organization_id", sa.String(36), nullable=False),
        sa.Column("source_user_id", sa.String(36), nullable=False),
        sa.Column("sender_email", sa.String(320), nullable=False),
        sa.Column("recipient_email", sa.String(320), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_user_id", sa.String(36), nullable=True),
        sa.Column("accepted_organization_id", sa.String(36), nullable=True),
        sa.Column("destination_workspace_id", sa.String(32), nullable=True))
    op.create_index("ix_nova_workspace_transfers_recipient_email", "nova_workspace_transfers", ["recipient_email"])


def downgrade():
    op.drop_table("nova_workspace_transfers")
