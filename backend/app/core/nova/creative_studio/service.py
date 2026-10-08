"""Creative Studio application service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import time
from typing import Any

from app.core.nova.creative_studio.export import export_project_package, presenter_publish_ready
from app.core.nova.creative_studio.drama import ShortDramaMixin
from app.core.nova.creative_studio.media_runtime import memory_budget, run_encoder, serialized_media
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


class CreativeStudioService(ShortDramaMixin):
    def __init__(self, store: CreativeStudioStore | DbCreativeStudioStore | None = None):
        self.store = store or get_store()

    def _build_local_scene_motion(
        self,
        *,
        source_image_url: str,
        platform: str,
        duration_seconds: int = 5,
    ) -> dict[str, Any]:
        try:
            source_path = _resolve_creative_media_url(source_image_url)
            if source_path is None or not source_path.is_file():
                return {
                    "status": "ERROR",
                    "message": "Nova local motion fallback could not load the generated source image.",
                    "url": None,
                    "asset_generated": False,
                    "provider": "nova_ffmpeg_fallback",
                }

            try:
                import imageio_ffmpeg
                ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception as exc:
                return {
                    "status": "ERROR",
                    "message": f"Nova local motion fallback media engine is unavailable: {exc}",
                    "url": None,
                    "asset_generated": False,
                    "provider": "nova_ffmpeg_fallback",
                }

            vertical = str(platform or "").strip().lower() in {"tiktok", "instagram", "youtube shorts"}
            width, height = (720, 1280) if vertical else (1280, 720)
            duration = max(2, min(int(duration_seconds or 5), 10))
            output_dir, public_prefix = _creative_media_root_and_prefix()
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"nova-local-motion-{new_id('scene').split('_', 1)[-1]}.mp4"

            # Use a conservative Ken Burns style zoom that is broadly supported
            # by bundled FFmpeg builds on Render.
            frames = duration * 25
            filter_expr = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},"
                f"zoompan=z='1+0.04*on/{max(frames - 1, 1)}':"
                f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d={frames}:s={width}x{height}:fps=25,"
                "format=yuv420p"
            )
            cmd = [
                ffmpeg, "-y", "-threads", "1", "-filter_threads", "1",
                "-loop", "1",
                "-i", str(source_path),
                "-vf", filter_expr,
                "-frames:v", str(frames),
                "-an",
                "-c:v", "libx264",
                "-threads", "1",
                "-preset", "veryfast", "-tune", "zerolatency", "-x264-params", "ref=1",
                "-crf", "23",
                "-movflags", "+faststart",
                str(output_path),
            ]
            run = run_encoder(cmd, timeout=120)
            if run.returncode != 0 or not output_path.is_file():
                detail = (run.stderr or run.stdout or "").strip().splitlines()
                tail = detail[-1] if detail else "unknown FFmpeg error"
                return {
                    "status": "ERROR",
                    "message": f"Nova local motion fallback could not create the scene video: {tail[:300]}",
                    "url": None,
                    "asset_generated": False,
                    "provider": "nova_ffmpeg_fallback",
                }

            return {
                "status": "GENERATED",
                "message": "Runway credits were unavailable, so Nova created this scene with the local motion fallback.",
                "url": public_prefix + "/" + output_path.name,
                "asset_generated": True,
                "provider": "nova_ffmpeg_fallback",
                "generation_mode": "local_image_motion_fallback",
                "duration_seconds": duration,
                "ratio": f"{width}:{height}",
            }
        except Exception as exc:
            return {
                "status": "ERROR",
                "message": f"Nova local motion fallback failed safely: {type(exc).__name__}: {exc}",
                "url": None,
                "asset_generated": False,
                "provider": "nova_ffmpeg_fallback",
            }


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
            if duration not in DURATIONS and project_type in {"short_video", "short_drama", "promo_video", "explainer"}:
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

    def update_project(self, owner_id: str, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        row = self._project_or_404(owner_id, project_id)
        updates = dict(payload or {})

        if "project_type" in updates and updates["project_type"] is not None:
            project_type = str(updates["project_type"]).strip()
            if project_type not in PROJECT_TYPES:
                raise CreativeStudioError("UNSUPPORTED_PROJECT_TYPE", f"Unsupported project_type: {project_type}")
            row.project_type = project_type

        if "platform" in updates and updates["platform"] is not None:
            platform = str(updates["platform"]).strip()
            if platform not in PLATFORMS:
                raise CreativeStudioError("INVALID_INPUT", f"Unsupported platform: {platform}")
            row.platform = platform

        if "duration_target" in updates and updates["duration_target"] is not None:
            try:
                duration = int(updates["duration_target"])
            except (TypeError, ValueError) as exc:
                raise CreativeStudioError("INVALID_INPUT", "duration_target must be an integer") from exc
            if duration not in DURATIONS and row.project_type in {"short_video", "short_drama", "promo_video", "explainer"}:
                raise CreativeStudioError("INVALID_INPUT", f"duration_target must be one of {DURATIONS}")
            row.duration_target = duration

        for field in ("title", "objective", "audience", "tone", "brand_profile_id"):
            if field in updates and updates[field] is not None:
                value = updates[field]
                setattr(row, field, str(value).strip() if isinstance(value, str) else value)

        production_keys = {
            "presenter_mode",
            "motion_style",
            "framing",
            "output_preset",
            "voice",
            "image_aspect",
            "captions",
        }
        metadata = dict(row.metadata or {})
        production = dict(metadata.get("production_settings") or {})
        for key in production_keys:
            if key in updates and updates[key] is not None:
                production[key] = updates[key]
        if production:
            metadata["production_settings"] = production
        row.metadata = metadata
        row.updated_at = _now()
        saved = self.store.save_project(row)
        return {
            "status": "UPDATED",
            "message": "Creative Studio project settings updated.",
            "project": saved.as_dict(),
        }

    def attach_brand_to_project(self, owner_id: str, project_id: str, brand_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        brand = self.store.get_brand(brand_id, owner_id)
        if brand is None:
            raise CreativeStudioError("NOT_FOUND", "Brand profile not found", http_status=404)
        project.brand_profile_id = brand.id
        project.updated_at = _now()
        saved = self.store.save_project(project)
        return {
            "status": "UPDATED",
            "message": "Brand profile attached to active project.",
            "project": saved.as_dict(),
            "brand": brand.as_dict(),
        }

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
        if project.project_type == "short_drama":
            raise CreativeStudioError("USE_DRAMA_PLANNER", "Use the Short drama cast and dialogue planner for this project.", http_status=422)
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
        if project.project_type == "short_drama":
            return self.generate_drama_caption(owner_id, project_id)
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
        if project.project_type == "short_drama":
            raise CreativeStudioError("USE_DRAMA_PLANNER", "Use the Short drama cast and dialogue planner for this project.", http_status=422)
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

    @serialized_media
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


    def reset_project_media(self, owner_id: str, project_id: str) -> dict[str, Any]:
        self._project_or_404(owner_id, project_id)
        removable_kinds = {"image_prompt", "image", "video", "audio", "presenter_video"}
        rows = self.store.delete_assets_by_kinds(project_id, owner_id, removable_kinds)

        removed_files = 0
        for asset in rows:
            if not asset.url:
                continue
            path = _resolve_creative_media_url(asset.url)
            if path is None or not path.is_file():
                continue
            try:
                path.unlink()
                removed_files += 1
            except OSError:
                pass

        return {
            "project_id": project_id,
            "status": "MEDIA_RESET",
            "deleted_asset_records": len(rows),
            "deleted_media_files": removed_files,
            "preserved": ["script", "voiceover", "subtitle", "caption", "hashtags", "storyboard"],
        }

    def clear_legacy_preview_videos(self, owner_id: str, project_id: str) -> dict[str, Any]:
        self._project_or_404(owner_id, project_id)
        assets = self.store.list_assets(project_id, owner_id)
        remove_ids: set[str] = set()

        for asset in assets:
            if asset.kind not in {"presenter_video", "video"}:
                continue
            meta = asset.metadata or {}
            provider = meta.get("provider_result") or {}
            presenter_mode = str(meta.get("presenter_mode") or "").strip().lower()
            quality_state = str(meta.get("quality_state") or "").strip().upper()
            duration = provider.get("duration_seconds")
            try:
                duration_seconds = float(duration) if duration is not None else None
            except (TypeError, ValueError):
                duration_seconds = None

            is_old_headshot = asset.kind == "presenter_video" and presenter_mode in {"", "head", "headshot"}
            is_preview_only = quality_state in {"PREVIEW_ONLY", "DEMO_READY_WITH_PROVIDER_WATERMARK"}
            is_short_generated_clip = duration_seconds is not None and duration_seconds <= 8.5
            is_failed_or_processing = str(asset.status or "").upper() in {"ERROR", "FAILED", "PROCESSING"}

            if is_old_headshot or is_preview_only or is_short_generated_clip or is_failed_or_processing:
                remove_ids.add(asset.id)

        rows = self.store.delete_assets_by_ids(project_id, owner_id, remove_ids)
        removed_files = 0
        for asset in rows:
            if not asset.url:
                continue
            path = _resolve_creative_media_url(asset.url)
            if path is None or not path.is_file():
                continue
            try:
                path.unlink()
                removed_files += 1
            except OSError:
                pass

        return {
            "project_id": project_id,
            "status": "LEGACY_PREVIEWS_CLEANED",
            "deleted_asset_records": len(rows),
            "deleted_media_files": removed_files,
        }

    @serialized_media
    def request_video_generation(self, owner_id: str, project_id: str, *, job: GenerationJob | None = None) -> dict[str, Any]:
        background = job is not None
        project = self._project_or_404(owner_id, project_id)
        self.store.delete_failed_video_assets(project_id, owner_id)
        job = job or self._start_job(owner_id, project_id, "video")
        brief = self._brief_for(owner_id, project)
        scenes = self.store.list_scenes(project_id, owner_id)

        if not scenes:
            raise CreativeStudioError(
                "STORYBOARD_REQUIRED",
                "Generate the storyboard before generating scene videos.",
                http_status=422,
            )

        provider_state = video_provider().status()
        if provider_state.status != "AVAILABLE":
            result = {"status": provider_state.status, "message": provider_state.message, "url": None, "asset_generated": False}
            asset = self._save_text_asset(
                owner_id=owner_id, project_id=project_id, kind="video",
                title="Scene video provider unavailable", content="",
                status="PROVIDER_CONFIG_REQUIRED" if provider_state.status == CONFIG_REQUIRED else provider_state.status,
                metadata={"provider_result": result}, url=None,
            )
            self._finish_job(job, status=provider_state.status, message=provider_state.message, asset_ids=[asset.id])
            return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": None}

        # Resume an unfinished provider task before advancing to the next scene.
        resume_task_id = None
        resume_asset = None
        scene_index = None
        for candidate in reversed(self.store.list_assets(project_id, owner_id)):
            if candidate.kind != "video":
                continue
            provider_result = (candidate.metadata or {}).get("provider_result") or {}
            if (
                str(provider_result.get("status") or "").upper() == "PROCESSING"
                and provider_result.get("task_id")
            ):
                pending_provider = provider_result.get("provider")
                active_provider = video_provider().provider_id
                legacy_foreign = not pending_provider and active_provider == "fal_kling_video" and not str(provider_result["task_id"]).startswith("fal-kling25:")
                if legacy_foreign or (pending_provider and pending_provider != active_provider):
                    message = "An unfinished motion job belongs to another provider. Restore that provider to finish it before switching."
                    self._finish_job(job, status="ERROR", message=message, asset_ids=[candidate.id])
                    return {"job": job.as_dict(), "asset": candidate.as_dict(), "provider": {"status": "ERROR", "message": message}, "url": None}
                resume_task_id = str(provider_result["task_id"])
                resume_asset = candidate
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
            # Reuse valid source artwork on retries; don't pay for the same image
            # again after a downstream timeout or provider failure.
            reusable = next((asset for asset in reversed(self.store.list_assets(project_id, owner_id))
                if asset.kind == "image" and asset.status == "GENERATED"
                and asset.content == prompt_text and asset.url
                and (_resolve_creative_media_url(asset.url) is not None
                     and _resolve_creative_media_url(asset.url).is_file())), None)
            image_result = {"url": reusable.url} if reusable else self.request_image_generation(
                owner_id, project_id, aspect_ratio=aspect_ratio, prompt=prompt_text,
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

        try:
            result = video_provider().generate(
                brief={
                    "project_id": project_id,
                    "title": project.title,
                    "objective": project.objective,
                    "platform": project.platform,
                    "prompt_text": prompt_text,
                    "prompt_image_url": source_image_url,
                    "resume_task_id": resume_task_id,
                    "persist_task_before_poll": background,
                    "scene_index": scene_index,
                    "scene_heading": scene.heading,
                }
            )
        except Exception as exc:
            result = {
                "status": "ERROR",
                "message": f"Video provider failed safely: {type(exc).__name__}: {exc}",
                "url": None,
                "asset_generated": False,
                "provider": video_provider().provider_id,
            }

        runway_message = str(result.get("message") or "")
        credit_exhausted = (
            str(result.get("status") or "").upper() == "ERROR"
            and (
                "not have enough credits" in runway_message.lower()
                or "insufficient credits" in runway_message.lower()
                or "credit balance" in runway_message.lower()
            )
        )
        if credit_exhausted and source_image_url and not resume_task_id and project.project_type != "short_drama":
            try:
                fallback = self._build_local_scene_motion(
                    source_image_url=source_image_url,
                    platform=project.platform,
                    duration_seconds=5,
                )
            except Exception as exc:
                fallback = {
                    "status": "ERROR",
                    "message": f"Nova local motion fallback failed safely: {type(exc).__name__}: {exc}",
                    "url": None,
                    "asset_generated": False,
                    "provider": "nova_ffmpeg_fallback",
                }
            fallback["brief"] = {
                "project_id": project_id,
                "title": project.title,
                "objective": project.objective,
                "platform": project.platform,
                "prompt_text": prompt_text,
                "prompt_image_url": source_image_url,
                "resume_task_id": None,
                "scene_index": scene_index,
                "scene_heading": scene.heading,
            }
            fallback["runway_error"] = runway_message
            result = fallback

        status = result.get("status") or CONFIG_REQUIRED
        generated_url = str(result.get("url") or "").strip() or None if result.get("asset_generated") else None
        metadata = {
            "provider_result": {k: v for k, v in result.items() if k != "url"},
            "scene_index": scene_index,
            "scene_heading": scene.heading,
        }
        if resume_asset is not None:
            # Replace the pending marker so a completed task cannot be resumed
            # forever and polling doesn't create duplicate video rows.
            resume_asset.status = "PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status
            resume_asset.metadata = metadata
            resume_asset.url = generated_url
            asset = self.store.save_asset(resume_asset)
        else:
            asset = self._save_text_asset(
                owner_id=owner_id, project_id=project_id, kind="video",
                title=f"Scene {scene_index} AI motion result", content=prompt_text,
                status="PROVIDER_CONFIG_REQUIRED" if status == CONFIG_REQUIRED else status,
                metadata=metadata, url=generated_url,
            )
        self._finish_job(
            job,
            status="RUNNING" if background and status == "PROCESSING" else status,
            message=str(result.get("message") or status),
            asset_ids=[asset.id],
            provider=str(result.get("provider") or video_provider().provider_id),
        )
        return {
            "job": job.as_dict(),
            "asset": asset.as_dict(),
            "provider": result,
            "url": generated_url,
            "scene_index": scene_index,
            "scene_count": len(scenes),
        }

    def request_voice_generation(self, owner_id: str, project_id: str, *, script: str | None = None, voice: str | None = None, presenter: bool = False) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        if project.project_type == "short_drama":
            return self.generate_drama_voices(owner_id, project_id)
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
        voice_args = {"script": text or "No voiceover script available."}
        if voice:
            voice_args['voice'] = voice
        if presenter:
            voice_args['presenter'] = True
        result = voice_provider().generate(**voice_args)
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

    @serialized_media
    def assemble_final_promo(self, owner_id: str, project_id: str) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        if project.project_type == "short_drama":
            return self.assemble_drama(owner_id, project_id)
        scenes = self.store.list_scenes(project_id, owner_id)
        if not scenes:
            raise CreativeStudioError("STORYBOARD_REQUIRED", "Generate the storyboard first.", http_status=422)

        backend_root = Path(__file__).resolve().parents[4]
        vertical = str(project.platform or "").strip().lower() in {"tiktok", "instagram", "youtube shorts"}
        width, height = (720, 1280) if vertical else (1280, 720)
        fps = 25
        scene_duration = 5

        all_assets = self.store.list_assets(project_id, owner_id)

        # A publish-ready talking presenter is already a complete narrated promo.
        # Re-encoding that MP4 on the small web service only burns memory and can
        # fail before FFmpeg starts. Promote the provider-delivered file directly
        # to the final-promo asset instead. Timed captions may travel as a sidecar
        # when burn-in was skipped for memory safety.
        def _captions_ready(metadata: dict[str, Any]) -> bool:
            return bool(
                metadata.get("captions_burned_in") is True
                or metadata.get("subtitle_url")
                or metadata.get("captions_sidecar_ready")
            )

        def _presenter_demo_eligible(item: CreativeAsset) -> bool:
            metadata = item.metadata or {}
            if presenter_publish_ready(metadata) or bool(metadata.get("demo_ready")):
                return True

            # A 30-second demo must reuse a presenter MP4 that already has
            # captions. Re-encoding that file on the 512 MiB service is what
            # runs out of memory. Preview and watermarked files stay eligible
            # for playback, but presenter_publish_ready() keeps them unpublished.
            presenter_mode = str(metadata.get("presenter_mode") or "").strip().lower()
            if presenter_mode in {"head", "half_body", "full_body"} and _captions_ready(metadata):
                return True

            # Backward compatibility for D-ID presenters created before the
            # disclosure-watermark demo policy shipped. Those rows can already
            # contain the correct head-presenter video and timed captions, but
            # their stored quality_state remains PREVIEW_ONLY. Recognize that
            # existing media in place rather than spending another provider credit.
            provider_result = metadata.get("provider_result") or {}
            provider_id = str(
                provider_result.get("provider")
                or metadata.get("provider")
                or ""
            ).strip().lower()
            return bool(
                provider_id in {"d-id", "did"}
                and presenter_mode == "head"
                and _captions_ready(metadata)
            )

        presenter = next(
            (
                item for item in reversed(all_assets)
                if item.kind == "presenter_video"
                and str(item.status or "").upper() == "GENERATED"
                and item.url
                and _presenter_demo_eligible(item)
            ),
            None,
        )
        if presenter is not None:
            presenter_path = _resolve_creative_media_url(presenter.url)
            if presenter_path is not None and presenter_path.is_file():
                presenter_meta = presenter.metadata or {}
                provider_result = presenter_meta.get("provider_result") or {}
                provider_id = str(
                    provider_result.get("provider") or presenter_meta.get("provider") or ""
                ).strip().lower()
                presenter_mode = str(presenter_meta.get("presenter_mode") or "").strip().lower()
                clean_publish = presenter_publish_ready(presenter_meta)
                legacy_demo_ready = bool(
                    not clean_publish
                    and not presenter_meta.get("demo_ready")
                    and provider_id in {"d-id", "did"}
                    and presenter_mode == "head"
                    and _captions_ready(presenter_meta)
                )
                watermarked = bool(
                    not clean_publish
                    and (
                        legacy_demo_ready
                        or presenter_meta.get("provider_watermark_preserved") is True
                        or str(presenter_meta.get("quality_state") or "").upper() == "PREVIEW_ONLY"
                        or provider_result.get("watermark_free") is False
                    )
                )
                if clean_publish:
                    render_mode = "publish_ready_presenter_passthrough"
                    promo_message = "Final AMICOR Nova promo promoted from the publish-ready Genova presenter without re-encoding."
                elif legacy_demo_ready:
                    render_mode = "legacy_did_demo_passthrough"
                    promo_message = "Final AMICOR Nova promo promoted from the existing D-ID demo presenter without re-encoding."
                else:
                    render_mode = "presenter_mp4_passthrough"
                    promo_message = "Final AMICOR Nova promo reused the existing presenter video without re-encoding."
                asset = self._save_text_asset(
                    owner_id=owner_id,
                    project_id=project_id,
                    kind="video",
                    title="Final AMICOR Nova promo",
                    content=presenter.content or "Final promo using the existing Genova presenter.",
                    status="GENERATED",
                    metadata={
                        "final_promo": True,
                        "render_mode": render_mode,
                        "presenter_asset_id": presenter.id,
                        "voice_asset_id": presenter_meta.get("voice_asset_id"),
                        "subtitle_url": presenter_meta.get("subtitle_url"),
                        "captions_burned_in": presenter_meta.get("captions_burned_in") is True,
                        "publish_ready": clean_publish,
                        "demo_ready": not clean_publish,
                        "provider_watermark_preserved": watermarked,
                        "quality_state": "PUBLISH_READY" if clean_publish else "PREVIEW_ONLY",
                        "brand_overlay": "preserved_from_presenter_asset",
                    },
                    url=presenter.url,
                )
                job = self._start_job(owner_id, project_id, "short_video_assembly")
                self._finish_job(
                    job,
                    status="GENERATED",
                    message=promo_message,
                    asset_ids=[asset.id],
                    provider="nova_presenter_passthrough",
                )
                return {"job": job.as_dict(), "asset": asset.as_dict(), "url": presenter.url}

        try:
            import imageio_ffmpeg
            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            raise CreativeStudioError(
                "FFMPEG_UNAVAILABLE",
                "Nova paused video rendering: the media engine is unavailable, and no finished presenter video could be reused. "
                + str(exc),
                http_status=422,
            ) from exc

        # Prefer the already-generated scene motion clips for final assembly.
        # Re-rendering every storyboard still is unnecessary work on the 512 MiB
        # web service and was the operation blocked by the memory guard.
        scene_clip_paths: list[Path] = []
        for scene in scenes:
            scene_clip: Path | None = None
            for candidate in reversed(all_assets):
                if candidate.kind != "video" or str(candidate.status or "").upper() != "GENERATED" or not candidate.url:
                    continue
                metadata = candidate.metadata or {}
                provider_result = metadata.get("provider_result") or {}
                brief_meta = provider_result.get("brief") or {}
                try:
                    candidate_scene_index = int(metadata.get("scene_index") or brief_meta.get("scene_index"))
                except (TypeError, ValueError):
                    continue
                if candidate_scene_index != int(scene.index):
                    continue
                candidate_path = _resolve_creative_media_url(candidate.url)
                if candidate_path is not None and candidate_path.is_file():
                    scene_clip = candidate_path
                    break
            if scene_clip is None:
                scene_clip_paths = []
                break
            scene_clip_paths.append(scene_clip)

        image_paths: list[Path] = []
        if not scene_clip_paths:
            for scene in scenes:
                prompt_text = str(scene.visual_prompt or scene.description or "").strip()
                if not prompt_text:
                    prompt_text = " ".join(
                        part for part in [project.title, project.objective, project.tone] if part
                    ).strip()
    
                image_path: Path | None = None
                for candidate in reversed(all_assets):
                    if (
                        candidate.kind == "image"
                        and str(candidate.status or "").upper() == "GENERATED"
                        and candidate.url
                        and str(candidate.content or "").strip() == prompt_text
                    ):
                        candidate_path = _resolve_creative_media_url(candidate.url)
                        if candidate_path is not None and candidate_path.is_file():
                            image_path = candidate_path
                            break
    
                if image_path is None:
                    image_result = self.request_image_generation(
                        owner_id,
                        project_id,
                        aspect_ratio="9:16" if vertical else "16:9",
                        prompt=prompt_text,
                    )
                    image_url = str(image_result.get("url") or "").strip()
                    image_path = _resolve_creative_media_url(image_url)
                    if not image_url or image_path is None or not image_path.is_file():
                        raise CreativeStudioError(
                            "SCENE_IMAGE_FAILED",
                            f"Nova could not create usable artwork for scene {scene.index}.",
                            http_status=422,
                        )
                    all_assets = self.store.list_assets(project_id, owner_id)
                image_paths.append(image_path)
    
        all_assets = self.store.list_assets(project_id, owner_id)
        audio: CreativeAsset | None = None
        for candidate in reversed(all_assets):
            if candidate.kind != "audio" or str(candidate.status or "").upper() != "GENERATED" or not candidate.url:
                continue
            candidate_path = _resolve_creative_media_url(candidate.url)
            if candidate_path is None or candidate_path.is_file():
                audio = candidate
                break
        if audio is None:
            voice_result = self.request_voice_generation(owner_id, project_id)
            audio_url = str(voice_result.get("url") or "").strip()
            if not audio_url:
                raise CreativeStudioError(
                    "VOICE_GENERATION_FAILED",
                    str((voice_result.get("provider") or {}).get("message") or "Nova could not generate voice narration."),
                    http_status=422,
                )
            all_assets = self.store.list_assets(project_id, owner_id)
            audio = next(
                (
                    item for item in reversed(all_assets)
                    if item.kind == "audio"
                    and str(item.status or "").upper() == "GENERATED"
                    and item.url == audio_url
                ),
                None,
            )

        if audio is None or not audio.url:
            raise CreativeStudioError("VOICE_REQUIRED", "Nova could not locate the generated voice narration.", http_status=422)
        audio_path = _resolve_creative_media_url(audio.url)
        if audio_path is None or not audio_path.is_file():
            raise CreativeStudioError("MEDIA_MISSING", "Generated voice media is unavailable.", http_status=422)

        if scene_clip_paths and len(scene_clip_paths) == len(scenes):
            output_dir, public_prefix = _creative_media_root_and_prefix()
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"nova-final-{new_id('promo').split('_', 1)[-1]}.mp4"
            job = self._start_job(owner_id, project_id, "short_video_assembly")
            normalized_scene_clips = False
            try:
                with tempfile.TemporaryDirectory(prefix="nova-final-copy-") as temp_dir:
                    temp_root = Path(temp_dir)

                    def _write_concat_file(paths: list[Path], target: Path) -> None:
                        target.write_text(
                            "\n".join("file '" + str(path).replace("'", "'\\''") + "'" for path in paths) + "\n",
                            encoding="utf-8",
                        )

                    concat_file = temp_root / "clips.txt"
                    _write_concat_file(scene_clip_paths, concat_file)
                    joined_path = temp_root / "joined.mp4"
                    join_cmd = [
                        ffmpeg, "-y", "-f", "concat", "-safe", "0",
                        "-i", str(concat_file), "-c", "copy", str(joined_path),
                    ]
                    join_run = run_encoder(join_cmd, timeout=90, required_headroom=96 * 1024 * 1024)

                    # Provider-generated clips can differ in codec profile, dimensions,
                    # frame rate, or time base. A concat-copy failure is therefore not
                    # necessarily a memory failure. Let the failed encoder release its
                    # cgroup pages before retrying, then normalize one clip at a time
                    # using a deliberately lightweight preview profile.
                    if join_run.returncode != 0 or not joined_path.is_file() or joined_path.stat().st_size < 1024:
                        normalized_scene_clips = True
                        normalized_paths: list[Path] = []

                        recovery_deadline = time.monotonic() + 10.0
                        while time.monotonic() < recovery_deadline:
                            budget = memory_budget()
                            if budget is None or budget[1] - budget[0] >= 160 * 1024 * 1024:
                                break
                            time.sleep(0.25)

                        normalize_width, normalize_height = ((540, 960) if vertical else (960, 540))
                        normalize_fps = 20
                        vf = (
                            f"scale={normalize_width}:{normalize_height}:force_original_aspect_ratio=decrease:"
                            f"flags=fast_bilinear,"
                            f"pad={normalize_width}:{normalize_height}:(ow-iw)/2:(oh-ih)/2,"
                            f"fps={normalize_fps},format=yuv420p"
                        )
                        for offset, source_path in enumerate(scene_clip_paths):
                            normalized_path = temp_root / f"normalized-{offset + 1}.mp4"
                            normalize_cmd = [
                                ffmpeg, "-y", "-threads", "1", "-filter_threads", "1",
                                "-i", str(source_path),
                                "-vf", vf,
                                "-an",
                                "-c:v", "libx264",
                                "-threads", "1",
                                "-preset", "ultrafast",
                                "-tune", "zerolatency",
                                "-x264-params", "ref=1:bframes=0:rc-lookahead=0:sync-lookahead=0",
                                "-crf", "25",
                                "-pix_fmt", "yuv420p",
                                "-movflags", "+faststart",
                                str(normalized_path),
                            ]
                            normalize_run = run_encoder(
                                normalize_cmd,
                                timeout=120,
                                required_headroom=128 * 1024 * 1024,
                            )
                            if (
                                normalize_run.returncode != 0
                                or not normalized_path.is_file()
                                or normalized_path.stat().st_size < 1024
                            ):
                                detail = (normalize_run.stderr or normalize_run.stdout or "")[-1800:]
                                raise RuntimeError(
                                    f"scene {offset + 1} normalization failed: {detail}"
                                )
                            normalized_paths.append(normalized_path)

                        concat_file = temp_root / "normalized-clips.txt"
                        _write_concat_file(normalized_paths, concat_file)
                        joined_path = temp_root / "joined-normalized.mp4"
                        normalized_join_cmd = [
                            ffmpeg, "-y", "-f", "concat", "-safe", "0",
                            "-i", str(concat_file), "-c", "copy", str(joined_path),
                        ]
                        normalized_join_run = run_encoder(
                            normalized_join_cmd,
                            timeout=90,
                            required_headroom=96 * 1024 * 1024,
                        )
                        if (
                            normalized_join_run.returncode != 0
                            or not joined_path.is_file()
                            or joined_path.stat().st_size < 1024
                        ):
                            detail = (
                                normalized_join_run.stderr or normalized_join_run.stdout or ""
                            )[-1800:]
                            raise RuntimeError("normalized scene join failed: " + detail)

                    mux_cmd = [
                        ffmpeg, "-y", "-i", str(joined_path), "-i", str(audio_path),
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart", "-shortest", str(output_path),
                    ]
                    mux_run = run_encoder(mux_cmd, timeout=120, required_headroom=96 * 1024 * 1024)
                    if mux_run.returncode != 0 or not output_path.is_file() or output_path.stat().st_size < 1024:
                        detail = (mux_run.stderr or mux_run.stdout or "")[-1800:]
                        raise RuntimeError("audio mux failed: " + detail)
            except Exception as exc:
                self._finish_job(job, status="ERROR", message=str(exc), asset_ids=[], provider="nova_ffmpeg_copy")
                raise CreativeStudioError(
                    "FINAL_ASSEMBLY_FAILED",
                    f"Nova final promo assembly failed: {str(exc)[-1200:]}",
                    http_status=422,
                ) from exc

            public_url = public_prefix + "/" + output_path.name
            asset = self._save_text_asset(
                owner_id=owner_id,
                project_id=project_id,
                kind="video",
                title="Final AMICOR Nova promo",
                content="Final promo assembled from existing generated scene clips with Nova voice narration.",
                status="GENERATED",
                metadata={
                    "final_promo": True,
                    "render_mode": (
                        "scene_clip_normalize_then_concat"
                        if normalized_scene_clips
                        else "scene_clip_concat_copy"
                    ),
                    "scene_count": len(scenes),
                    "voice_asset_id": audio.id,
                    "brand_overlay": "preserved_from_scene_assets",
                },
                url=public_url,
            )
            self._finish_job(
                job,
                status="GENERATED",
                message=(
                    "Final AMICOR Nova promo assembled after low-memory scene normalization."
                    if normalized_scene_clips
                    else "Final AMICOR Nova promo assembled in low-memory mode."
                ),
                asset_ids=[asset.id],
                provider="nova_ffmpeg_copy",
            )
            return {"job": job.as_dict(), "asset": asset.as_dict(), "url": public_url}

        logo_path = backend_root / "static" / "branding" / "amicor-logo-full.png"
        if not logo_path.is_file():
            raise CreativeStudioError("LOGO_MISSING", "Official AMICOR logo asset is unavailable.", http_status=422)

        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"nova-final-{new_id('promo').split('_', 1)[-1]}.mp4"
        job = self._start_job(owner_id, project_id, "short_video_assembly")

        try:
            with tempfile.TemporaryDirectory(prefix="nova-final-") as temp_dir:
                temp_root = Path(temp_dir)
                segment_paths: list[Path] = []

                for offset, image_path in enumerate(image_paths):
                    segment_path = temp_root / f"scene-{offset + 1}.mp4"
                    vf = (
                        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                        f"fps={fps},format=yuv420p"
                    )
                    segment_cmd = [
                        ffmpeg, "-y", "-threads", "1", "-filter_threads", "1",
                        "-loop", "1",
                        "-framerate", str(fps),
                        "-i", str(image_path),
                        "-t", str(scene_duration),
                        "-vf", vf,
                        "-an",
                        "-c:v", "libx264",
                        "-threads", "1",
                        "-preset", "veryfast", "-tune", "zerolatency", "-x264-params", "ref=1",
                        "-crf", "22",
                        "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart",
                        str(segment_path),
                    ]
                    segment_run = run_encoder(segment_cmd, timeout=120)
                    if segment_run.returncode != 0 or not segment_path.is_file() or segment_path.stat().st_size < 1024:
                        detail = (segment_run.stderr or segment_run.stdout or "")[-1800:]
                        raise RuntimeError(f"scene {offset + 1} render failed: {detail}")
                    segment_paths.append(segment_path)

                concat_file = temp_root / "clips.txt"
                concat_file.write_text(
                    "\n".join("file '" + str(path).replace("'", "'\\''") + "'" for path in segment_paths) + "\n",
                    encoding="utf-8",
                )
                joined_path = temp_root / "joined.mp4"
                join_cmd = [
                    ffmpeg, "-y",
                    "-f", "concat", "-safe", "0",
                    "-i", str(concat_file),
                    "-c", "copy",
                    str(joined_path),
                ]
                join_run = run_encoder(join_cmd, timeout=120)
                if join_run.returncode != 0 or not joined_path.is_file():
                    detail = (join_run.stderr or join_run.stdout or "")[-1800:]
                    raise RuntimeError("scene join failed: " + detail)

                final_cmd = [
                    ffmpeg, "-y", "-threads", "1", "-filter_complex_threads", "1",
                    "-i", str(joined_path),
                    "-i", str(audio_path),
                    "-i", str(logo_path),
                    "-filter_complex",
                    "[2:v]scale=170:-1[logo];[0:v][logo]overlay=24:24:repeatlast=1[v]",
                    "-map", "[v]",
                    "-map", "1:a:0",
                    "-c:v", "libx264",
                    "-threads", "1",
                    "-preset", "veryfast", "-tune", "zerolatency", "-x264-params", "ref=1",
                    "-crf", "21",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "160k",
                    "-movflags", "+faststart",
                    "-shortest",
                    str(output_path),
                ]
                final_run = run_encoder(final_cmd, timeout=180)
                if final_run.returncode != 0 or not output_path.is_file() or output_path.stat().st_size < 1024:
                    detail = (final_run.stderr or final_run.stdout or "")[-2200:]
                    raise RuntimeError("final render failed: " + detail)
        except Exception as exc:
            self._finish_job(job, status="ERROR", message=str(exc), asset_ids=[], provider="nova_ffmpeg_compat")
            raise CreativeStudioError(
                "FINAL_ASSEMBLY_FAILED",
                f"Nova final promo render failed: {str(exc)[-1200:]}",
                http_status=422,
            ) from exc

        public_url = public_prefix + "/" + output_path.name
        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title="Final AMICOR Nova promo",
            content="Final promo rendered from storyboard artwork with Nova voice narration and official AMICOR branding.",
            status="GENERATED",
            metadata={
                "final_promo": True,
                "render_mode": "ffmpeg_compat_stills",
                "scene_count": len(scenes),
                "voice_asset_id": audio.id,
                "brand_overlay": "official_amicor_logo",
            },
            url=public_url,
        )
        self._finish_job(
            job,
            status="GENERATED",
            message="Final AMICOR Nova promo rendered successfully.",
            asset_ids=[asset.id],
            provider="nova_ffmpeg_compat",
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
