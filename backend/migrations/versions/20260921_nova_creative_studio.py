"""Add Nova Creative Studio persistent tables.

Revision ID: 20260921_nova_creative_studio
Revises: 20260921_nova_work_inputs
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260921_nova_creative_studio"
down_revision = "20260921_nova_work_inputs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names())

    if "nova_creative_brands" not in existing:
        op.create_table(
            "nova_creative_brands",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("business_name", sa.String(200), nullable=False),
            sa.Column("logo_reference", sa.String(500), nullable=False, server_default=""),
            sa.Column("tagline", sa.String(300), nullable=False, server_default=""),
            sa.Column("tone", sa.String(120), nullable=False, server_default=""),
            sa.Column("target_audience", sa.String(300), nullable=False, server_default=""),
            sa.Column("preferred_cta", sa.String(300), nullable=False, server_default=""),
            sa.Column("brand_description", sa.Text(), nullable=False, server_default=""),
            sa.Column("prohibited_claims_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("preferred_platforms_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_nova_creative_brand_owner",
            "nova_creative_brands",
            ["owner_id", "updated_at"],
            unique=False,
        )

    if "nova_creative_briefs" not in existing:
        op.create_table(
            "nova_creative_briefs",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("project_id", sa.String(48), nullable=True),
            sa.Column("topic", sa.String(300), nullable=False),
            sa.Column("audience", sa.String(300), nullable=False, server_default=""),
            sa.Column("objective", sa.String(300), nullable=False, server_default=""),
            sa.Column("tone", sa.String(120), nullable=False, server_default=""),
            sa.Column("cta", sa.String(300), nullable=False, server_default=""),
            sa.Column("style", sa.String(120), nullable=False, server_default=""),
            sa.Column("key_points_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("duration_target", sa.Integer(), nullable=True),
            sa.Column("platform", sa.String(40), nullable=False, server_default="generic"),
            sa.Column("created_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_nova_creative_brief_owner_project",
            "nova_creative_briefs",
            ["owner_id", "project_id"],
            unique=False,
        )

    if "nova_creative_projects" not in existing:
        op.create_table(
            "nova_creative_projects",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("project_type", sa.String(40), nullable=False),
            sa.Column("platform", sa.String(40), nullable=False, server_default="generic"),
            sa.Column("objective", sa.String(300), nullable=False, server_default=""),
            sa.Column("audience", sa.String(300), nullable=False, server_default=""),
            sa.Column("tone", sa.String(120), nullable=False, server_default=""),
            sa.Column("duration_target", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
            sa.Column("brand_profile_id", sa.String(48), nullable=True),
            sa.Column("brief_id", sa.String(48), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_nova_creative_project_owner",
            "nova_creative_projects",
            ["owner_id", "updated_at"],
            unique=False,
        )

    if "nova_creative_assets" not in existing:
        op.create_table(
            "nova_creative_assets",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("project_id", sa.String(48), nullable=False),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("title", sa.String(220), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(40), nullable=False, server_default="GENERATED"),
            sa.Column("mime_type", sa.String(80), nullable=False, server_default="text/plain"),
            sa.Column("url", sa.String(800), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_nova_creative_asset_owner_project",
            "nova_creative_assets",
            ["owner_id", "project_id", "created_at"],
            unique=False,
        )

    if "nova_creative_scenes" not in existing:
        op.create_table(
            "nova_creative_scenes",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("project_id", sa.String(48), nullable=False),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("scene_index", sa.Integer(), nullable=False),
            sa.Column("heading", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("visual_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("voiceover_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("subtitle_text", sa.Text(), nullable=False, server_default=""),
            sa.Column("duration_seconds", sa.Float(), nullable=False, server_default="0"),
            sa.Column("transition_note", sa.String(200), nullable=False, server_default=""),
            sa.Column("music_mood_note", sa.String(200), nullable=False, server_default=""),
            sa.Column("status", sa.String(40), nullable=False, server_default="GENERATED"),
            sa.Column("created_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_nova_creative_scene_owner_project",
            "nova_creative_scenes",
            ["owner_id", "project_id", "scene_index"],
            unique=False,
        )

    if "nova_creative_jobs" not in existing:
        op.create_table(
            "nova_creative_jobs",
            sa.Column("id", sa.String(48), primary_key=True),
            sa.Column("project_id", sa.String(48), nullable=False),
            sa.Column("owner_id", sa.String(36), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("message", sa.Text(), nullable=False, server_default=""),
            sa.Column("result_asset_ids_json", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("provider", sa.String(80), nullable=True),
            sa.Column("created_at", sa.String(64), nullable=False),
            sa.Column("updated_at", sa.String(64), nullable=False),
        )
        op.create_index(
            "ix_nova_creative_job_owner_project",
            "nova_creative_jobs",
            ["owner_id", "project_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    for name in (
        "nova_creative_jobs",
        "nova_creative_scenes",
        "nova_creative_assets",
        "nova_creative_projects",
        "nova_creative_briefs",
        "nova_creative_brands",
    ):
        op.drop_table(name)
