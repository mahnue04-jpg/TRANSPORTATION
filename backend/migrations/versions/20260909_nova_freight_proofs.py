"""Nova freight proof-of-pickup and proof-of-delivery records.

Revision ID: 20260909_nova_freight_proofs
Revises: 20260909_nova_freight_lifecycle
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260909_nova_freight_proofs"
down_revision = "20260909_nova_freight_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_shipment_events" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipment_events")}
        if "proof_id" not in existing:
            op.add_column("nova_freight_shipment_events", sa.Column("proof_id", sa.String(32), nullable=True))
    if "nova_freight_proofs" not in names:
        op.create_table(
            "nova_freight_proofs",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("proof_id", sa.String(32), nullable=False),
            sa.Column("shipment_id", sa.String(32), nullable=False),
            sa.Column("organization_id", sa.String(36), nullable=False),
            sa.Column("proof_type", sa.String(32), nullable=False),
            sa.Column("document_ref", sa.String(128), nullable=False),
            sa.Column("original_filename", sa.String(255), nullable=True),
            sa.Column("content_type", sa.String(128), nullable=True),
            sa.Column("uploaded_by_user_id", sa.String(36), nullable=True),
            sa.Column("uploaded_by_carrier_id", sa.String(32), nullable=True),
            sa.Column("uploader_role", sa.String(32), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("latitude", sa.Numeric(10, 6), nullable=True),
            sa.Column("longitude", sa.Numeric(10, 6), nullable=True),
            sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("signer_name", sa.String(160), nullable=True),
            sa.Column("signer_role", sa.String(64), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_nova_freight_proofs_proof_id", "nova_freight_proofs", ["proof_id"], unique=True)
        op.create_index("ix_nova_freight_proofs_shipment_id", "nova_freight_proofs", ["shipment_id"])
        op.create_index("ix_nova_freight_proofs_org_id", "nova_freight_proofs", ["organization_id"])
        op.create_index("ix_nova_freight_proofs_doc_ref", "nova_freight_proofs", ["shipment_id", "document_ref"])
        op.create_index("ix_nova_freight_proofs_active", "nova_freight_proofs", ["shipment_id", "is_active"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = set(inspector.get_table_names())
    if "nova_freight_proofs" in names:
        op.drop_index("ix_nova_freight_proofs_active", table_name="nova_freight_proofs")
        op.drop_index("ix_nova_freight_proofs_doc_ref", table_name="nova_freight_proofs")
        op.drop_index("ix_nova_freight_proofs_org_id", table_name="nova_freight_proofs")
        op.drop_index("ix_nova_freight_proofs_shipment_id", table_name="nova_freight_proofs")
        op.drop_index("ix_nova_freight_proofs_proof_id", table_name="nova_freight_proofs")
        op.drop_table("nova_freight_proofs")
    if "nova_freight_shipment_events" in names:
        existing = {col["name"] for col in inspector.get_columns("nova_freight_shipment_events")}
        if "proof_id" in existing:
            op.drop_column("nova_freight_shipment_events", "proof_id")
