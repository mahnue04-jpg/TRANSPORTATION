"""Additive Growth campaign review table; draft, not authorized for deployment.

Alembic must not stamp this revision without applying its schema. Deploying or
running migrations against an existing environment requires a separate owner
approval and backup review. No runtime route creates or modifies this schema.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20261118_nova_ga_campaign_review"
down_revision = "20261112_nova_ga_retention"
branch_labels = None
depends_on = None


def _verify_existing_table(inspector) -> None:
    """Fail closed instead of stamping a partially provisioned campaign table."""
    table = "nova_ga_campaign_asset_reviews"
    expected = {
        "id": 36, "organization_id": 36, "owner_user_id": 36,
        "campaign_id": 128, "studio_project_id": 128, "asset_id": 128,
        "status": 32, "created_at": 48, "updated_at": 48,
    }
    actual = {col["name"]: col for col in inspector.get_columns(table)}
    if set(actual) != set(expected):
        raise RuntimeError("Campaign review table schema is incomplete")
    for name, length in expected.items():
        column = actual[name]
        if column.get("nullable") or not isinstance(column["type"], sa.String):
            raise RuntimeError("Campaign review column schema mismatch")
        if column["type"].length != length:
            raise RuntimeError("Campaign review column length mismatch")
    pk = inspector.get_pk_constraint(table)
    if pk.get("constrained_columns") != ["id"]:
        raise RuntimeError("Campaign review primary key is missing")
    uniques = inspector.get_unique_constraints(table)
    if not any(
        constraint.get("name") == "uq_nova_ga_campaign_org_ref"
        and constraint.get("column_names") == ["organization_id", "campaign_id"]
        for constraint in uniques
    ):
        raise RuntimeError("Campaign review unique constraint is missing")
    indexes = inspector.get_indexes(table)
    if not any(
        index.get("name") == "ix_nova_ga_campaign_owner"
        and index.get("column_names") ==
        ["organization_id", "owner_user_id", "created_at"]
        and not index.get("unique")
        for index in indexes
    ):
        raise RuntimeError("Campaign review owner index is missing")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "nova_ga_campaign_asset_reviews" in inspector.get_table_names():
        _verify_existing_table(inspector)
        return
    op.create_table(
        "nova_ga_campaign_asset_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("owner_user_id", sa.String(36), nullable=False),
        sa.Column("campaign_id", sa.String(128), nullable=False),
        sa.Column("studio_project_id", sa.String(128), nullable=False),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(48), nullable=False),
        sa.Column("updated_at", sa.String(48), nullable=False),
        sa.UniqueConstraint("organization_id", "campaign_id",
                            name="uq_nova_ga_campaign_org_ref"),
    )
    op.create_index(
        "ix_nova_ga_campaign_owner", "nova_ga_campaign_asset_reviews",
        ["organization_id", "owner_user_id", "created_at"],
    )


def downgrade() -> None:
    # Deliberately no destructive downgrade. Any removal would require a
    # separate backup+owner-approved deletion change.
    return
