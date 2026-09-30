"""Creative Studio application service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
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
    _creative_media_root_and_prefix,
    _resolve_creative_media_url,
)
from app.core.nova.creative_studio.safety import BLOCK, screen_creative_text
from app.core.nova.creative_studio.store import CreativeStudioStore, DbCreativeStudioStore, get_db_store, get_store


class CreativeStudioError(Exception):
    def __init__(self, code: str, message: str, *, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CreativeStudioService:
    def __init__(self, store: CreativeStudioStore | DbCreativeStudioStore | None = None):
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

        def asset_payload(asset: CreativeAsset) -> dict[str, Any]:
            payload = asset.as_dict()
            if asset.url and asset.kind in {"image", "video", "audio"}:
                local_path = _resolve_creative_media_url(asset.url)
                if local_path is not None:
                    payload["media_available"] = local_path.is_file()
                else:
                    payload["media_available"] = str(asset.url).startswith(("http://", "https://"))
            else:
                payload["media_available"] = None
            return payload

        return {
            "project": row.as_dict(),
            "assets": [asset_payload(a) for a in self.store.list_assets(project_id, owner_id)],
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
        self.store.delete_scenes(project_id, owner_id)
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
        generated_url = str(result.get("url") or "").strip() or None if result.get("asset_generated") else None
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="image",
            title="Image generation result",
            content=prompt or "",
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={"provider_result": {k: v for k, v in result.items() if k != "url"}, "aspect_ratio": aspect_ratio},
            url=generated_url,
        )
        self._finish_job(
            job,
            status=status,
            message=str(result.get("message") or status),
            asset_ids=[asset.id],
            provider=image_provider().provider_id,
        )
        return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": generated_url}

    def clear_failed_video_assets(self, owner_id: str, project_id: str) -> dict[str, Any]:
        self._project_or_404(owner_id, project_id)
        deleted = self.store.delete_failed_video_assets(project_id, owner_id)
        return {"project_id": project_id, "deleted": deleted, "status": "CLEANED"}

    def request_video_generation(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        self.store.delete_failed_video_assets(project_id, owner_id)
        job = self._start_job(owner_id, project_id, "video")
        brief = self._brief_for(owner_id, project)
        scenes = self.store.list_scenes(project_id, owner_id)

        if not scenes:
            raise CreativeStudioError(
                "STORYBOARD_REQUIRED",
                "Generate the storyboard before generating scene videos.",
                http_status=422,
            )

        # Resume an unfinished Runway task before advancing to the next scene.
        resume_task_id = None
        scene_index = None
        for candidate in reversed(self.store.list_assets(project_id, owner_id)):
            if candidate.kind != "video":
                continue
            provider_result = (candidate.metadata or {}).get("provider_result") or {}
            if (
                str(provider_result.get("status") or "").upper() == "PROCESSING"
                and provider_result.get("task_id")
            ):
                resume_task_id = str(provider_result["task_id"])
                brief_meta = provider_result.get("brief") or {}
                try:
                    scene_index = int(brief_meta.get("scene_index"))
                except (TypeError, ValueError):
                    scene_index = None
                break

        completed_scene_indexes: set[int] = set()
        for candidate in self.store.list_assets(project_id, owner_id):
            if candidate.kind != "video" or str(candidate.status or "").upper() != "GENERATED":
                continue
            if not candidate.url:
                continue
            candidate_path = _resolve_creative_media_url(candidate.url)
            if candidate_path is not None and not candidate_path.is_file():
                continue
            provider_result = (candidate.metadata or {}).get("provider_result") or {}
            brief_meta = provider_result.get("brief") or {}
            try:
                completed_scene_indexes.add(int(brief_meta.get("scene_index")))
            except (TypeError, ValueError):
                continue

        if scene_index is None:
            remaining = [scene.index for scene in scenes if int(scene.index) not in completed_scene_indexes]
            if not remaining:
                self._finish_job(
                    job,
                    status="GENERATED",
                    message="All storyboard scenes already have AI motion clips.",
                    asset_ids=[],
                    provider=video_provider().provider_id,
                )
                return {
                    "job": job.as_dict(),
                    "provider": {
                        "status": "GENERATED",
                        "message": "All storyboard scenes already have AI motion clips.",
                        "all_scenes_generated": True,
                        "completed_scene_indexes": sorted(completed_scene_indexes),
                    },
                    "asset": None,
                    "url": None,
                }
            scene_index = int(remaining[0])

        scene = next((row for row in scenes if int(row.index) == int(scene_index)), scenes[0])
        prompt_text = str(scene.visual_prompt or scene.description or "").strip()
        if not prompt_text:
            prompt_text = " ".join(
                part for part in [
                    project.title,
                    project.objective,
                    (brief.topic if brief else ""),
                    (brief.style if brief else ""),
                    project.tone,
                ] if part
            )

        source_image_url = None
        if not resume_task_id:
            aspect_ratio = "9:16" if str(project.platform or "").strip().lower() in {
                "tiktok", "instagram", "youtube shorts"
            } else "16:9"
            image_result = self.request_image_generation(
                owner_id,
                project_id,
                aspect_ratio=aspect_ratio,
                prompt=prompt_text,
            )
            source_image_url = str(image_result.get("url") or "").strip() or None
            if not source_image_url:
                message = str(
                    (image_result.get("provider") or {}).get("message")
                    or f"Nova could not create source art for scene {scene_index}."
                )
                asset = self._save_text_asset(
                    owner_id=owner_id,
                    project_id=project_id,
                    kind="video",
                    title=f"Scene {scene_index} AI motion result",
                    content=prompt_text,
                    status="ERROR",
                    metadata={"provider_result": {"status": "ERROR", "message": message, "brief": {"scene_index": scene_index}}},
                    url=None,
                )
                self._finish_job(job, status="ERROR", message=message, asset_ids=[asset.id], provider=video_provider().provider_id)
                return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": {"status": "ERROR", "message": message}, "url": None}

        result = video_provider().generate(
            brief={
                "project_id": project_id,
                "title": project.title,
                "objective": project.objective,
                "platform": project.platform,
                "prompt_text": prompt_text,
                "prompt_image_url": source_image_url,
                "resume_task_id": resume_task_id,
                "scene_index": scene_index,
                "scene_heading": scene.heading,
            }
        )
        status = result.get("status") or CONFIG_REQUIRED
        generated_url = str(result.get("url") or "").strip() or None if result.get("asset_generated") else None
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title=f"Scene {scene_index} AI motion result",
            content=prompt_text,
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={
                "provider_result": {k: v for k, v in result.items() if k != "url"},
                "scene_index": scene_index,
                "scene_heading": scene.heading,
            },
            url=generated_url,
        )
        self._finish_job(
            job,
            status=status,
            message=str(result.get("message") or status),
            asset_ids=[asset.id],
            provider=video_provider().provider_id,
        )
        return {
            "job": job.as_dict(),
            "asset": asset.as_dict(),
            "provider": result,
            "url": generated_url,
            "scene_index": scene_index,
            "scene_count": len(scenes),
        }

    def request_voice_generation(self, owner_id: str, project_id: str, *, script: str | None = None) -> dict[str, Any]:
        self._project_or_404(owner_id, project_id)
        job = self._start_job(owner_id, project_id, "voice")
        text = script or ""
        if not text:
            assets = self.store.list_assets(project_id, owner_id)
            # For short/promo video, narrate the full storyboard script first.
            for asset in reversed(assets):
                if asset.kind == "script" and asset.title == "Short video full script":
                    text = asset.content
                    break
            if not text:
                for asset in reversed(assets):
                    if asset.kind == "voiceover":
                        text = asset.content
                        break
        result = voice_provider().generate(script=text or "No voiceover script available.")
        status = result.get("status") or CONFIG_REQUIRED
        generated_url = str(result.get("url") or "").strip() or None if result.get("asset_generated") else None
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="audio",
            title="Voice generation result",
            content=text or "",
            status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
            metadata={"provider_result": {k: v for k, v in result.items() if k != "url"}},
            url=generated_url,
        )
        self._finish_job(job, status=status, message=str(result.get("message") or status), asset_ids=[asset.id], provider=voice_provider().provider_id)
        return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": generated_url}

    def assemble_final_promo(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        scenes = self.store.list_scenes(project_id, owner_id)
        if not scenes:
            raise CreativeStudioError("STORYBOARD_REQUIRED", "Generate the storyboard first.", http_status=422)

        assets = self.store.list_assets(project_id, owner_id)
        video_by_scene: dict[int, CreativeAsset] = {}
        for asset in assets:
            if asset.kind != "video" or str(asset.status or "").upper() != "GENERATED" or not asset.url:
                continue
            local_path = _resolve_creative_media_url(asset.url)
            if local_path is not None and not local_path.is_file():
                continue
            idx = (asset.metadata or {}).get("scene_index")
            if idx is None:
                provider_result = (asset.metadata or {}).get("provider_result") or {}
                idx = ((provider_result.get("brief") or {}).get("scene_index"))
            try:
                scene_idx = int(idx)
            except (TypeError, ValueError):
                continue
            video_by_scene[scene_idx] = asset

        expected = [int(scene.index) for scene in scenes]
        missing = [idx for idx in expected if idx not in video_by_scene]
        if missing:
            raise CreativeStudioError(
                "SCENES_INCOMPLETE",
                "Generate all storyboard scene videos first. Missing scene(s): " + ", ".join(str(x) for x in missing),
                http_status=422,
            )

        audio = None
        for asset in reversed(assets):
            if asset.kind != "audio" or str(asset.status or "").upper() != "GENERATED" or not asset.url:
                continue
            local_path = _resolve_creative_media_url(asset.url)
            if local_path is not None and not local_path.is_file():
                continue
            audio = asset
            break
        if audio is None:
            raise CreativeStudioError("VOICE_REQUIRED", "Generate the voice narration first.", http_status=422)

        backend_root = Path(__file__).resolve().parents[4]

        def local_media(url: str) -> Path:
            path = _resolve_creative_media_url(url)
            if path is None or not path.is_file():
                raise CreativeStudioError(
                    "MEDIA_MISSING",
                    "A generated media file is missing. Regenerate the missing scene or voice after persistent media storage is enabled.",
                    http_status=422,
                )
            return path

        clip_paths = [local_media(video_by_scene[idx].url or "") for idx in expected]
        audio_path = local_media(audio.url or "")
        logo_path = backend_root / "static" / "branding" / "amicor-logo-full.png"
        if not logo_path.is_file():
            raise CreativeStudioError("LOGO_MISSING", "Official AMICOR logo asset is unavailable.", http_status=500)

        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise CreativeStudioError("FFMPEG_UNAVAILABLE", "Final promo media engine is unavailable.", http_status=500) from exc

        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"nova-final-{new_id('promo').split('_', 1)[1]}.mp4"

        job = self._start_job(owner_id, project_id, "short_video_assembly")
        try:
            with tempfile.TemporaryDirectory(prefix="nova-promo-") as temp_dir:
                temp_root = Path(temp_dir)
                concat_file = temp_root / "clips.txt"
                concat_file.write_text(
                    "\n".join("file '" + str(path).replace("'", "'\\''") + "'" for path in clip_paths) + "\n",
                    encoding="utf-8",
                )
                joined = temp_root / "joined.mp4"

                join_cmd = [
                    ffmpeg, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy",
                    str(joined),
                ]
                joined_run = subprocess.run(join_cmd, capture_output=True, text=True, timeout=180)
                if joined_run.returncode != 0:
                    raise RuntimeError("clip join failed: " + joined_run.stderr[-1200:])

                final_cmd = [
                    ffmpeg, "-y",
                    "-i", str(joined),
                    "-i", str(audio_path),
                    "-i", str(logo_path),
                    "-filter_complex",
                    "[2:v]scale=180:-1[logo];[0:v][logo]overlay=24:24[v]",
                    "-map", "[v]",
                    "-map", "1:a:0",
                    "-c:v", "libx264",
                    "-preset", "veryfast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-b:a", "160k",
                    "-movflags", "+faststart",
                    "-shortest",
                    str(output_path),
                ]
                final_run = subprocess.run(final_cmd, capture_output=True, text=True, timeout=240)
                if final_run.returncode != 0 or not output_path.is_file():
                    raise RuntimeError("final mux failed: " + final_run.stderr[-1200:])
        except Exception as exc:
            self._finish_job(job, status="ERROR", message=str(exc), asset_ids=[], provider="nova_ffmpeg")
            raise CreativeStudioError("FINAL_ASSEMBLY_FAILED", "Nova could not assemble the final promo video.", http_status=500) from exc

        public_url = public_prefix + "/" + output_path.name
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title="Final AMICOR Nova promo",
            content="Final assembled promo from storyboard scene clips with full voice narration and AMICOR logo overlay.",
            status="GENERATED",
            metadata={
                "final_promo": True,
                "scene_indexes": expected,
                "voice_asset_id": audio.id,
                "brand_overlay": "official_amicor_logo",
            },
            url=public_url,
        )
        self._finish_job(
            job,
            status="GENERATED",
            message="Final AMICOR Nova promo assembled successfully.",
            asset_ids=[asset.id],
            provider="nova_ffmpeg",
        )
        return {"job": job.as_dict(), "asset": asset.as_dict(), "url": public_url}


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


def get_service(db=None) -> CreativeStudioService:
    """Return Creative Studio service.

    Production/router path should pass a SQLAlchemy Session so records persist.
    Unit tests may inject an in-memory CreativeStudioStore directly.
    """
    if db is not None:
        return CreativeStudioService(get_db_store(db))
    return CreativeStudioService()
