"""Creative Studio application service."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.nova.creative_studio.export import export_project_package
from app.core.nova.creative_studio.flags import creative_guardrails
from app.core.nova.creative_studio.generation import assemble_short_video, generate_content_pack
from app.core.nova.creative_studio.models import (
    DURATIONS,
    PLATFORMS,
    PROJECT_TYPES,
    BrandProfile,
    ContentBrief,
    CreativeAsset,
    CreativeProject,
    CreativeScene,
    GenerationJob,
    new_id,
)
from app.core.nova.creative_studio.providers import (
    CONFIG_REQUIRED,
    IMAGE_ASPECTS,
    image_provider,
    provider_statuses,
    video_provider,
    voice_provider,
)
from app.core.nova.creative_studio.safety import BLOCK, screen_creative_text
from app.core.nova.creative_studio.store import CreativeStudioStore, get_store


class CreativeStudioError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreativeStudioService:
    def __init__(self, store: CreativeStudioStore | None = None):
        self.store = store or get_store()

    def guardrails(self) -> dict[str, Any]:
        return {
            **creative_guardrails(),
            "providers": provider_statuses(),
            "project_types": list(PROJECT_TYPES),
            "platforms": list(PLATFORMS),
            "durations": list(DURATIONS),
            "image_aspects": list(IMAGE_ASPECTS),
        }

    def create_project(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        title = str(payload.get("title") or "").strip()
        project_type = str(payload.get("project_type") or "").strip()
        platform = str(payload.get("platform") or "generic").strip()
        if not title:
            raise CreativeStudioError("INVALID_INPUT", "title is required")
        if project_type not in PROJECT_TYPES:
            raise CreativeStudioError("UNSUPPORTED_PROJECT_TYPE", f"Unsupported project_type: {project_type}")
        if platform not in PLATFORMS:
            raise CreativeStudioError("INVALID_INPUT", f"Unsupported platform: {platform}")
        duration = payload.get("duration_target")
        if duration is not None:
            try:
                duration = int(duration)
            except (TypeError, ValueError) as exc:
                raise CreativeStudioError("INVALID_INPUT", "duration_target must be an integer") from exc
            if duration not in DURATIONS and project_type in {"short_video", "promo_video", "explainer"}:
                raise CreativeStudioError("INVALID_INPUT", f"duration_target must be one of {DURATIONS}")
        safety = screen_creative_text(title, payload.get("objective"), payload.get("audience"), payload.get("tone"))
        if safety["decision"] == BLOCK:
            raise CreativeStudioError("SAFETY_BLOCK", safety["message"], http_status=422)
        row = CreativeProject(
            id=new_id("cproj"),
            owner_id=owner_id,
            title=title,
            project_type=project_type,
            platform=platform,
            objective=str(payload.get("objective") or "").strip(),
            audience=str(payload.get("audience") or "").strip(),
            tone=str(payload.get("tone") or "").strip(),
            duration_target=duration,
            status="draft",
            brand_profile_id=payload.get("brand_profile_id"),
            metadata={"safety": safety},
        )
        self.store.save_project(row)
        return row.as_dict()

    def list_projects(self, owner_id: str) -> list[dict[str, Any]]:
        return [p.as_dict() for p in self.store.list_projects(owner_id)]

    def get_project(self, owner_id: str, project_id: str) -> dict[str, Any]:
        row = self.store.get_project(project_id, owner_id)
        if row is None:
            raise CreativeStudioError("NOT_FOUND", "Project not found", http_status=404)
        return {
            "project": row.as_dict(),
            "assets": [a.as_dict() for a in self.store.list_assets(project_id, owner_id)],
            "scenes": [s.as_dict() for s in self.store.list_scenes(project_id, owner_id)],
            "jobs": [j.as_dict() for j in self.store.list_jobs(project_id, owner_id)],
            "brief": (
                self.store.get_brief(row.brief_id, owner_id).as_dict()
                if row.brief_id and self.store.get_brief(row.brief_id, owner_id)
                else None
            ),
            "brand": (
                self.store.get_brand(row.brand_profile_id, owner_id).as_dict()
                if row.brand_profile_id and self.store.get_brand(row.brand_profile_id, owner_id)
                else None
            ),
        }

    def create_brand(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("business_name") or "").strip()
        if not name:
            raise CreativeStudioError("INVALID_INPUT", "business_name is required")
        # Reject secret-like fields
        blob = " ".join(str(payload.get(k) or "") for k in payload)
        if any(tok in blob.lower() for tok in ("api_key", "password", "secret", "ssn", "ein", "routing")):
            raise CreativeStudioError("INVALID_INPUT", "Brand profile cannot store secrets or credentials", http_status=422)
        row = BrandProfile(
            id=new_id("cbrand"),
            owner_id=owner_id,
            business_name=name,
            logo_reference=str(payload.get("logo_reference") or "").strip(),
            tagline=str(payload.get("tagline") or "").strip(),
            tone=str(payload.get("tone") or "").strip(),
            target_audience=str(payload.get("target_audience") or "").strip(),
            preferred_cta=str(payload.get("preferred_cta") or "").strip(),
            brand_description=str(payload.get("brand_description") or "").strip(),
            prohibited_claims=list(payload.get("prohibited_claims") or []),
            preferred_platforms=list(payload.get("preferred_platforms") or []),
        )
        self.store.save_brand(row)
        return row.as_dict()

    def list_brands(self, owner_id: str) -> list[dict[str, Any]]:
        return [b.as_dict() for b in self.store.list_brands(owner_id)]

    def create_brief(self, owner_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        topic = str(payload.get("topic") or "").strip()
        if not topic:
            raise CreativeStudioError("INVALID_INPUT", "topic is required")
        project_id = payload.get("project_id")
        if project_id and self.store.get_project(str(project_id), owner_id) is None:
            raise CreativeStudioError("NOT_FOUND", "Project not found", http_status=404)
        safety = screen_creative_text(topic, payload.get("audience"), payload.get("cta"), payload.get("objective"))
        if safety["decision"] == BLOCK:
            raise CreativeStudioError("SAFETY_BLOCK", safety["message"], http_status=422)
        row = ContentBrief(
            id=new_id("cbrief"),
            owner_id=owner_id,
            project_id=str(project_id) if project_id else None,
            topic=topic,
            audience=str(payload.get("audience") or "").strip(),
            objective=str(payload.get("objective") or "").strip(),
            tone=str(payload.get("tone") or "").strip(),
            cta=str(payload.get("cta") or "").strip(),
            style=str(payload.get("style") or "").strip(),
            key_points=list(payload.get("key_points") or []),
            duration_target=payload.get("duration_target"),
            platform=str(payload.get("platform") or "generic").strip(),
        )
        self.store.save_brief(row)
        if row.project_id:
            project = self.store.get_project(row.project_id, owner_id)
            if project:
                project.brief_id = row.id
                project.updated_at = _now()
                self.store.save_project(project)
        return {**row.as_dict(), "safety": safety}

    def _project_or_404(self, owner_id: str, project_id: str) -> CreativeProject:
        row = self.store.get_project(project_id, owner_id)
        if row is None:
            raise CreativeStudioError("NOT_FOUND", "Project not found", http_status=404)
        return row

    def _brand_for(self, owner_id: str, project: CreativeProject) -> BrandProfile | None:
        if not project.brand_profile_id:
            return None
        return self.store.get_brand(project.brand_profile_id, owner_id)

    def _brief_for(self, owner_id: str, project: CreativeProject) -> ContentBrief | None:
        if not project.brief_id:
            return None
        return self.store.get_brief(project.brief_id, owner_id)

    def _start_job(self, owner_id: str, project_id: str, kind: str) -> GenerationJob:
        job = GenerationJob(
            id=new_id("cjob"),
            project_id=project_id,
            owner_id=owner_id,
            kind=kind,
            status="RUNNING",
        )
        return self.store.save_job(job)

    def _finish_job(self, job: GenerationJob, *, status: str, message: str, asset_ids: list[str], provider: str | None = None) -> GenerationJob:
        job.status = status
        job.message = message
        job.result_asset_ids = asset_ids
        job.provider = provider
        job.updated_at = _now()
        return self.store.save_job(job)

    def _save_text_asset(
        self,
        *,
        owner_id: str,
        project_id: str,
        kind: str,
        title: str,
        content: str,
        status: str = "GENERATED",
        metadata: dict[str, Any] | None = None,
        url: str | None = None,
    ) -> CreativeAsset:
        asset = CreativeAsset(
            id=new_id("casset"),
            project_id=project_id,
            owner_id=owner_id,
            kind=kind,
            title=title,
            content=content,
            status=status,
            url=url,
            metadata=metadata or {},
        )
        return self.store.save_asset(asset)

    def generate_script(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        brief = self._brief_for(owner_id, project)
        brand = self._brand_for(owner_id, project)
        topic = (brief.topic if brief else project.title)
        safety = screen_creative_text(topic, project.objective, project.audience)
        if safety["decision"] == BLOCK:
            raise CreativeStudioError("SAFETY_BLOCK", safety["message"], http_status=422)
        job = self._start_job(owner_id, project_id, "script")
        pack = generate_content_pack(
            topic=topic,
            audience=(brief.audience if brief and brief.audience else project.audience),
            objective=(brief.objective if brief and brief.objective else project.objective),
            tone=(brief.tone if brief and brief.tone else project.tone) or (brand.tone if brand else "clear"),
            platform=project.platform,
            cta=(brief.cta if brief and brief.cta else (brand.preferred_cta if brand else "Learn more.")),
            duration_target=project.duration_target,
            brand_name=brand.business_name if brand else "AMICOR",
            brand_tagline=brand.tagline if brand else "",
        )
        assets = [
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind="script", title="Short script", content=pack["short_script"], metadata={"hook": pack["hook"], "title": pack["title"]}),
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind="voiceover", title="Voiceover script", content=pack["voiceover_script"]),
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind="subtitle", title="Subtitle text", content=pack["subtitle_caption_text"]),
        ]
        project.status = "scripted"
        project.updated_at = _now()
        self.store.save_project(project)
        self._finish_job(job, status="GENERATED", message="Script package generated (text only).", asset_ids=[a.id for a in assets])
        return {"job": job.as_dict(), "pack": pack, "assets": [a.as_dict() for a in assets], "safety": safety}

    def generate_caption(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        brief = self._brief_for(owner_id, project)
        brand = self._brand_for(owner_id, project)
        topic = (brief.topic if brief else project.title)
        job = self._start_job(owner_id, project_id, "caption")
        pack = generate_content_pack(
            topic=topic,
            audience=project.audience or (brief.audience if brief else ""),
            objective=project.objective or (brief.objective if brief else ""),
            tone=project.tone or (brand.tone if brand else "clear"),
            platform=project.platform,
            cta=(brief.cta if brief and brief.cta else (brand.preferred_cta if brand else "Learn more.")),
            duration_target=project.duration_target,
            brand_name=brand.business_name if brand else "AMICOR",
            brand_tagline=brand.tagline if brand else "",
        )
        assets = [
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind="caption", title="Long caption", content=pack["long_caption"]),
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind="caption", title="Short caption", content=pack["short_caption"], metadata={"variant": "short"}),
            self._save_text_asset(owner_id=owner_id, project_id=project_id, kind="hashtags", title="Hashtags", content=" ".join(pack["hashtags"])),
        ]
        self._finish_job(job, status="GENERATED", message="Captions and hashtags generated.", asset_ids=[a.id for a in assets])
        return {"job": job.as_dict(), "pack": pack, "assets": [a.as_dict() for a in assets]}

    def generate_storyboard(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        brief = self._brief_for(owner_id, project)
        brand = self._brand_for(owner_id, project)
        duration = int(project.duration_target or 30)
        if duration not in DURATIONS:
            duration = 30
        job = self._start_job(owner_id, project_id, "storyboard")
        assembly = assemble_short_video(
            topic=(brief.topic if brief else project.title),
            audience=project.audience or (brief.audience if brief else "general audience"),
            platform=project.platform,
            duration_target=duration,
            style=(brief.style if brief and brief.style else "clean social"),
            tone=project.tone or (brand.tone if brand else "clear"),
            cta=(brief.cta if brief and brief.cta else (brand.preferred_cta if brand else "Learn more.")),
            brand_name=brand.business_name if brand else "AMICOR",
        )
        # Replace scenes
        existing = self.store.list_scenes(project_id, owner_id)
        for scene in existing:
            self.store.scenes.pop(scene.id, None)
        saved_scenes = []
        for raw in assembly["scenes"]:
            scene = CreativeScene(
                id=new_id("cscene"),
                project_id=project_id,
                owner_id=owner_id,
                index=int(raw["index"]),
                heading=raw["heading"],
                description=raw["description"],
                visual_prompt=raw["visual_prompt"],
                voiceover_text=raw["voiceover_text"],
                subtitle_text=raw["subtitle_text"],
                duration_seconds=float(raw["duration_seconds"]),
                transition_note=raw.get("transition_note") or "",
                music_mood_note=raw.get("music_mood_note") or "",
            )
            saved_scenes.append(self.store.save_scene(scene))
        storyboard_text = "\n\n".join(
            f"{s.index}. {s.heading} ({s.duration_seconds}s)\n{s.description}\nVisual: {s.visual_prompt}"
            for s in saved_scenes
        )
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="storyboard",
            title="Storyboard",
            content=storyboard_text,
            metadata={"full_script": assembly["full_script"], "final_cta": assembly["final_cta"]},
        )
        script_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="script",
            title="Short video full script",
            content=assembly["full_script"],
        )
        project.status = "storyboarded"
        project.updated_at = _now()
        self.store.save_project(project)
        self._finish_job(
            job,
            status="GENERATED",
            message="Storyboard and scenes generated. No video file produced.",
            asset_ids=[asset.id, script_asset.id],
        )
        return {
            "job": job.as_dict(),
            "assembly": assembly,
            "scenes": [s.as_dict() for s in saved_scenes],
            "assets": [asset.as_dict(), script_asset.as_dict()],
        }

    def generate_image_prompt(self, owner_id: str, project_id: str, *, aspect_ratio: str = "1:1") -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        if aspect_ratio not in IMAGE_ASPECTS:
            raise CreativeStudioError("INVALID_INPUT", f"aspect_ratio must be one of {IMAGE_ASPECTS}")
        brief = self._brief_for(owner_id, project)
        brand = self._brand_for(owner_id, project)
        job = self._start_job(owner_id, project_id, "image_prompt")
        pack = generate_content_pack(
            topic=(brief.topic if brief else project.title),
            audience=project.audience,
            objective=project.objective,
            tone=project.tone or (brand.tone if brand else "clear"),
            platform=project.platform,
            cta=(brief.cta if brief and brief.cta else "Learn more."),
            brand_name=brand.business_name if brand else "AMICOR",
        )
        prompt = f"{pack['image_prompt']} Aspect ratio {aspect_ratio}."
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="image_prompt",
            title=f"Image prompt ({aspect_ratio})",
            content=prompt,
            status="GENERATED",
            metadata={"aspect_ratio": aspect_ratio, "media_generated": False},
            url=None,
        )
        self._finish_job(job, status="GENERATED", message="Image prompt generated. No image file produced.", asset_ids=[asset.id])
        return {"job": job.as_dict(), "asset": asset.as_dict(), "aspect_ratio": aspect_ratio, "url": None}

    def request_image_generation(self, owner_id: str, project_id: str, *, aspect_ratio: str = "1:1", prompt: str | None = None) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        if aspect_ratio not in IMAGE_ASPECTS:
            raise CreativeStudioError("INVALID_INPUT", f"aspect_ratio must be one of {IMAGE_ASPECTS}")
        job = self._start_job(owner_id, project_id, "image")
        if not prompt:
            generated = self.generate_image_prompt(owner_id, project_id, aspect_ratio=aspect_ratio)
            prompt = generated["asset"]["content"]
        result = image_provider().generate(prompt=prompt, aspect_ratio=aspect_ratio)
        status = result.get("status") or CONFIG_REQUIRED
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="image",
            title="Image generation result",
            content=prompt or "",
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={"provider_result": {k: v for k, v in result.items() if k != "url"}, "aspect_ratio": aspect_ratio},
            url=None,  # never invent
        )
        self._finish_job(
            job,
            status=status,
            message=str(result.get("message") or status),
            asset_ids=[asset.id],
            provider=image_provider().provider_id,
        )
        return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": None}

    def request_video_generation(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        job = self._start_job(owner_id, project_id, "video")
        result = video_provider().generate(brief={"project_id": project_id, "title": project.title})
        status = result.get("status") or CONFIG_REQUIRED
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title="Video generation status",
            content="Video file not produced.",
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={"provider_result": result},
            url=None,
        )
        self._finish_job(job, status=status, message=str(result.get("message") or status), asset_ids=[asset.id], provider=video_provider().provider_id)
        return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": None}

    def request_voice_generation(self, owner_id: str, project_id: str, *, script: str | None = None) -> dict[str, Any]:
        self._project_or_404(owner_id, project_id)
        job = self._start_job(owner_id, project_id, "voice")
        text = script or ""
        if not text:
            for asset in self.store.list_assets(project_id, owner_id):
                if asset.kind == "voiceover":
                    text = asset.content
                    break
        result = voice_provider().generate(script=text or "No voiceover script available.")
        status = result.get("status") or CONFIG_REQUIRED
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="audio",
            title="Voice generation status",
            content=text or "",
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={"provider_result": result},
            url=None,
        )
        self._finish_job(job, status=status, message=str(result.get("message") or status), asset_ids=[asset.id], provider=voice_provider().provider_id)
        return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": None}

    def export_project(self, owner_id: str, project_id: str, *, fmt: str = "json") -> dict[str, Any]:
        detail = self.get_project(owner_id, project_id)
        job = self._start_job(owner_id, project_id, "export")
        exported = export_project_package(detail, fmt=fmt)
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="export",
            title=f"Export ({exported['format']})",
            content=exported["content"],
            status="GENERATED",
            metadata={"mime_type": exported["mime_type"]},
            url=None,
        )
        self._finish_job(job, status="GENERATED", message="Export package ready for download.", asset_ids=[asset.id])
        return {"job": job.as_dict(), "export": exported, "asset": asset.as_dict()}


def get_service() -> CreativeStudioService:
    return CreativeStudioService()
