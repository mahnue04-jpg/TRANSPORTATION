"""SQLAlchemy persistence for Nova Creative Studio.

Isolated from Health, Delivery, Freight, Stripe, Work Revenue, and secrets.
Never store provider credentials or secrets in these tables.
"""

from __future__ import annotations

from sqlalchemy import Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class NovaCreativeBrand(Base):
    __tablename__ = "nova_creative_brands"
    __table_args__ = (Index("ix_nova_creative_brand_owner", "owner_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    business_name: Mapped[str] = mapped_column(String(200), nullable=False)
    logo_reference: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    tagline: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    target_audience: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    preferred_cta: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    brand_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prohibited_claims_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    preferred_platforms_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCreativeBrief(Base):
    __tablename__ = "nova_creative_briefs"
    __table_args__ = (Index("ix_nova_creative_brief_owner_project", "owner_id", "project_id"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    project_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    topic: Mapped[str] = mapped_column(String(300), nullable=False)
    audience: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    objective: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    cta: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    style: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    key_points_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    duration_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    platform: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCreativeProject(Base):
    __tablename__ = "nova_creative_projects"
    __table_args__ = (Index("ix_nova_creative_project_owner", "owner_id", "updated_at"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    project_type: Mapped[str] = mapped_column(String(40), nullable=False)
    platform: Mapped[str] = mapped_column(String(40), nullable=False, default="generic")
    objective: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    audience: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tone: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    duration_target: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    brand_profile_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    brief_id: Mapped[str | None] = mapped_column(String(48), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCreativeAsset(Base):
    __tablename__ = "nova_creative_assets"
    __table_args__ = (Index("ix_nova_creative_asset_owner_project", "owner_id", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(48), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(220), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="GENERATED")
    mime_type: Mapped[str] = mapped_column(String(80), nullable=False, default="text/plain")
    url: Mapped[str | None] = mapped_column(String(800), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCreativeScene(Base):
    __tablename__ = "nova_creative_scenes"
    __table_args__ = (Index("ix_nova_creative_scene_owner_project", "owner_id", "project_id", "scene_index"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(48), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scene_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visual_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voiceover_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subtitle_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    transition_note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    music_mood_note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="GENERATED")
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class NovaCreativeJob(Base):
    __tablename__ = "nova_creative_jobs"
    __table_args__ = (Index("ix_nova_creative_job_owner_project", "owner_id", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(48), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(48), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    result_asset_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    updated_at: Mapped[str] = mapped_column(String(64), nullable=False)
