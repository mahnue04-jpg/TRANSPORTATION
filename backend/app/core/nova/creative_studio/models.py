"""Creative Studio domain models (in-memory / dict-serialized)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

PROJECT_TYPES = (
    "social_post",
    "social_image",
    "short_video",
    "ad_creative",
    "promo_video",
    "explainer",
    "presentation_asset",
)

PLATFORMS = (
    "TikTok",
    "Instagram",
    "Facebook",
    "YouTube Shorts",
    "YouTube",
    "LinkedIn",
    "X",
    "generic",
)

DURATIONS = (15, 30, 60)

ASSET_KINDS = (
    "script",
    "caption",
    "hashtags",
    "image_prompt",
    "storyboard",
    "scene",
    "voiceover",
    "subtitle",
    "export",
    "image",
    "video",
    "audio",
)

ASSET_STATUS = (
    "PLANNING_ONLY",
    "GENERATED",
    "PROVIDER_CONFIG_REQUIRED",
    "FAILED",
)

JOB_KINDS = (
    "script",
    "caption",
    "storyboard",
    "image_prompt",
    "image",
    "video",
    "voice",
    "short_video_assembly",
    "export",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass
class BrandProfile:
    id: str
    owner_id: str
    business_name: str
    logo_reference: str = ""
    tagline: str = ""
    tone: str = ""
    target_audience: str = ""
    preferred_cta: str = ""
    brand_description: str = ""
    prohibited_claims: list[str] = field(default_factory=list)
    preferred_platforms: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ContentBrief:
    id: str
    owner_id: str
    project_id: str | None
    topic: str
    audience: str = ""
    objective: str = ""
    tone: str = ""
    cta: str = ""
    style: str = ""
    key_points: list[str] = field(default_factory=list)
    duration_target: int | None = None
    platform: str = "generic"
    created_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CreativeScene:
    id: str
    project_id: str
    owner_id: str
    index: int
    heading: str
    description: str
    visual_prompt: str
    voiceover_text: str
    subtitle_text: str
    duration_seconds: float
    transition_note: str = ""
    music_mood_note: str = ""
    status: str = "GENERATED"
    created_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CreativeAsset:
    id: str
    project_id: str
    owner_id: str
    kind: str
    title: str
    content: str
    status: str = "GENERATED"
    mime_type: str = "text/plain"
    url: str | None = None  # Never invent media URLs
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationJob:
    id: str
    project_id: str
    owner_id: str
    kind: str
    status: str
    message: str = ""
    result_asset_ids: list[str] = field(default_factory=list)
    provider: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CreativeProject:
    id: str
    owner_id: str
    title: str
    project_type: str
    platform: str
    objective: str = ""
    audience: str = ""
    tone: str = ""
    duration_target: int | None = None
    status: str = "draft"
    brand_profile_id: str | None = None
    brief_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
