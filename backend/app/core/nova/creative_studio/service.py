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


def _repair_guided_demo_copy(text: str) -> str:
    """Repair legacy generated copy that accidentally spoke the UI label 'website guided demo'."""
    value = str(text or "").strip()
    if "website guided demo" not in value.lower():
        return value
    return (
        "Meet AMICOR Nova, your AI operations workspace for everyday business work. "
        "Busywork piles up fast for small business owners, and it steals focus from the work that matters. "
        "Nova helps organize requests, follow-ups, documents, and next steps, with drafts you can review first. "
        "Owner control stays with you while Nova prepares the work. "
        "Visit getamicor.com to explore AMICOR Nova."
    )


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
        from app.core.nova.creative_studio.studio_checkout import checkout_readiness, public_pricing

        readiness = checkout_readiness()
        return {
            **creative_guardrails(),
            "providers": provider_statuses(),
            "project_types": list(PROJECT_TYPES),
            "platforms": list(PLATFORMS),
            "durations": list(DURATIONS),
            "image_aspects": list(IMAGE_ASPECTS),
            "studio_test_feature": {
                "walking_commercial_ready": True,
                "pricing": public_pricing(),
                "checkout": readiness,
                "live_billing": bool(readiness.get("live_checkout_available")),
                "durable_orders": True,
                "webhook_configured": bool(readiness.get("stripe_webhook_configured")),
                "paid_providers_default_off": True,
                "publish_default_off": True,
                "approved_60s_commercial_unchanged": True,
            },
        }

    def _studio_db(self):
        return getattr(self.store, "db", None)

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
        provider_unavailable = provider_state.status != "AVAILABLE"

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
            if reusable is None:
                # Prefer any scene-matched generated artwork before paying again.
                reusable = next((asset for asset in reversed(self.store.list_assets(project_id, owner_id))
                    if asset.kind == "image" and asset.status == "GENERATED" and asset.url
                    and (_resolve_creative_media_url(asset.url) is not None
                         and _resolve_creative_media_url(asset.url).is_file())
                    and int((asset.metadata or {}).get("scene_index") or -1) == int(scene_index)), None)
            if reusable is not None:
                image_result = {"url": reusable.url}
            elif provider_unavailable:
                image_result = {
                    "url": None,
                    "provider": {
                        "status": provider_state.status,
                        "message": (
                            provider_state.message
                            + " Generate scene artwork first, or enable a funded provider after owner budget confirmation."
                        ),
                    },
                }
            else:
                image_result = self.request_image_generation(
                    owner_id, project_id, aspect_ratio=aspect_ratio, prompt=prompt_text,
                )
            source_image_url = str(image_result.get("url") or "").strip() or None
            if not source_image_url:
                message = str(
                    (image_result.get("provider") or {}).get("message")
                    or f"Nova could not create source art for scene {scene_index}."
                )
                # Missing credentials are CONFIG_REQUIRED, not a failed render.
                # ERROR is reserved for a live provider that actually attempted work.
                if provider_unavailable:
                    blocked_status = provider_state.status or CONFIG_REQUIRED
                    result = {
                        "status": blocked_status,
                        "message": message,
                        "url": None,
                        "asset_generated": False,
                        "provider": video_provider().provider_id,
                    }
                    asset = self._save_text_asset(
                        owner_id=owner_id,
                        project_id=project_id,
                        kind="video",
                        title="Scene video provider unavailable",
                        content=prompt_text,
                        status="PROVIDER_CONFIG_REQUIRED" if blocked_status == CONFIG_REQUIRED else blocked_status,
                        metadata={"provider_result": result, "brief": {"scene_index": scene_index}},
                        url=None,
                    )
                    self._finish_job(
                        job,
                        status=blocked_status,
                        message=message,
                        asset_ids=[asset.id],
                        provider=video_provider().provider_id,
                    )
                    return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": None}
                asset = self._save_text_asset(
                    owner_id=owner_id,
                    project_id=project_id,
                    kind="video",
                    title=f"Scene {scene_index} AI motion result",
                    content=prompt_text,
                    status="ERROR",
                    metadata={"provider_result": {"status": "ERROR", "message": message, "brief": {"scene_index": scene_index}, "asset_generated": False}},
                    url=None,
                )
                self._finish_job(job, status="ERROR", message=message, asset_ids=[asset.id], provider=video_provider().provider_id)
                return {
                    "job": job.as_dict(),
                    "asset": asset.as_dict(),
                    "provider": {"status": "ERROR", "message": message, "asset_generated": False},
                    "url": None,
                }

        # When live video providers are gated/unfunded, create deliberate local
        # motion instead of leaving the project stuck or falling back to a still slideshow.
        if provider_unavailable and source_image_url and not resume_task_id and project.project_type != "short_drama":
            try:
                fallback = self._build_local_scene_motion(
                    source_image_url=source_image_url,
                    platform=project.platform,
                    duration_seconds=max(3, min(int(getattr(scene, "duration_seconds", 5) or 5), 8)),
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
                "scene_index": scene_index,
                "scene_heading": scene.heading,
                "prompt_text": prompt_text,
                "prompt_image_url": source_image_url,
                "local_motion_reason": provider_state.status,
            }
            fallback["provider_gate"] = provider_state.message
            result = fallback
            generated_url = str(result.get("url") or "").strip() or None if result.get("asset_generated") else None
            status = result.get("status") or CONFIG_REQUIRED
            metadata = {
                "provider_result": {k: v for k, v in result.items() if k != "url"},
                "scene_index": scene_index,
                "generation_mode": "local_image_motion_fallback",
                "commercial_slideshow": False,
            }
            asset = self._save_text_asset(
                owner_id=owner_id,
                project_id=project_id,
                kind="video",
                title=f"Scene {scene_index} local motion",
                content=prompt_text,
                status="GENERATED" if generated_url else status,
                metadata=metadata,
                url=generated_url,
            )
            self._finish_job(
                job,
                status="GENERATED" if generated_url else status,
                message=str(result.get("message") or provider_state.message),
                asset_ids=[asset.id],
                provider="nova_ffmpeg_fallback",
            )
            return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": generated_url}

        if provider_unavailable:
            result = {
                "status": provider_state.status,
                "message": provider_state.message,
                "url": None,
                "asset_generated": False,
            }
            asset = self._save_text_asset(
                owner_id=owner_id,
                project_id=project_id,
                kind="video",
                title="Scene video provider unavailable",
                content=prompt_text,
                status="PROVIDER_CONFIG_REQUIRED" if provider_state.status == CONFIG_REQUIRED else provider_state.status,
                metadata={"provider_result": result, "brief": {"scene_index": scene_index}},
                url=None,
            )
            self._finish_job(job, status=provider_state.status, message=provider_state.message, asset_ids=[asset.id])
            return {"job": job.as_dict(), "asset": asset.as_dict(), "provider": result, "url": None}

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
                or "needs credits" in runway_message.lower()
                or "fal account needs credits" in runway_message.lower()
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
        text = _repair_guided_demo_copy(text)
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
        if audio is not None and "website guided demo" in str(audio.content or "").lower():
            audio = None
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
                        "-movflags", "+faststart", "-shortest", str(temp_root / "muxed.mp4"),
                    ]
                    muxed_path = temp_root / "muxed.mp4"
                    mux_run = run_encoder(mux_cmd, timeout=120, required_headroom=96 * 1024 * 1024)
                    if mux_run.returncode != 0 or not muxed_path.is_file() or muxed_path.stat().st_size < 1024:
                        detail = (mux_run.stderr or mux_run.stdout or "")[-1800:]
                        raise RuntimeError("audio mux failed: " + detail)

                    polished = self._polish_final_promo_mp4(
                        muxed_path,
                        output_path=output_path,
                        audio_asset=audio,
                        scenes=scenes,
                        vertical=vertical,
                        width=width,
                        height=height,
                    )
                    captions_burned = bool(polished.get("captions_burned_in"))
                    subtitle_url = polished.get("subtitle_url")
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
                    "captions_burned_in": captions_burned,
                    "subtitle_url": subtitle_url,
                    "cta_fade": "getamicor.com",
                    "commercial_slideshow": False,
                    "commercial_ready_candidate": True,
                    "publish_ready": False,
                    "owner_review_required": True,
                },
                url=public_url,
            )
            self._finish_job(
                job,
                status="GENERATED",
                message=(
                    "Final AMICOR Nova promo assembled after low-memory scene normalization."
                    if normalized_scene_clips
                    else "Final AMICOR Nova promo assembled with motion clips, English voice, captions, and CTA fade."
                ),
                asset_ids=[asset.id],
                provider="nova_ffmpeg_copy",
            )
            return {"job": job.as_dict(), "asset": asset.as_dict(), "url": public_url}

        # Issue #344: never accept six static stills as the commercial deliverable.
        # Convert each storyboard image into local Ken Burns motion, then assemble.
        motion_paths: list[Path] = []
        output_dir_tmp, public_prefix_tmp = _creative_media_root_and_prefix()
        output_dir_tmp.mkdir(parents=True, exist_ok=True)
        for offset, image_path in enumerate(image_paths):
            staged = output_dir_tmp / f"nova-still-source-{new_id('scene').split('_', 1)[-1]}{image_path.suffix or '.png'}"
            staged.write_bytes(image_path.read_bytes())
            staged_url = public_prefix_tmp + "/" + staged.name
            motion = self._build_local_scene_motion(
                source_image_url=staged_url,
                platform=project.platform,
                duration_seconds=max(
                    3,
                    min(int(getattr(scenes[offset], "duration_seconds", scene_duration) or scene_duration), 8),
                ),
            )
            motion_url = str(motion.get("url") or "").strip()
            motion_path = _resolve_creative_media_url(motion_url)
            if not motion.get("asset_generated") or motion_path is None or not motion_path.is_file():
                raise CreativeStudioError(
                    "LOCAL_MOTION_REQUIRED",
                    f"Nova refused a static slideshow for scene {offset + 1}. Local motion could not be created: "
                    + str(motion.get("message") or "unknown error"),
                    http_status=422,
                )
            motion_paths.append(motion_path)

        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"nova-final-{new_id('promo').split('_', 1)[-1]}.mp4"
        job = self._start_job(owner_id, project_id, "short_video_assembly")

        try:
            with tempfile.TemporaryDirectory(prefix="nova-final-") as temp_dir:
                temp_root = Path(temp_dir)
                concat_file = temp_root / "clips.txt"
                concat_file.write_text(
                    "\n".join("file '" + str(path).replace("'", "'\\''") + "'" for path in motion_paths) + "\n",
                    encoding="utf-8",
                )
                joined_path = temp_root / "joined.mp4"
                join_run = run_encoder(
                    [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat_file), "-c", "copy", str(joined_path)],
                    timeout=120,
                    required_headroom=96 * 1024 * 1024,
                )
                if join_run.returncode != 0 or not joined_path.is_file():
                    detail = (join_run.stderr or join_run.stdout or "")[-1800:]
                    raise RuntimeError("local motion join failed: " + detail)

                muxed_path = temp_root / "muxed.mp4"
                mux_run = run_encoder(
                    [
                        ffmpeg, "-y", "-i", str(joined_path), "-i", str(audio_path),
                        "-map", "0:v:0", "-map", "1:a:0",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "128k",
                        "-movflags", "+faststart", "-shortest", str(muxed_path),
                    ],
                    timeout=120,
                    required_headroom=96 * 1024 * 1024,
                )
                if mux_run.returncode != 0 or not muxed_path.is_file() or muxed_path.stat().st_size < 1024:
                    detail = (mux_run.stderr or mux_run.stdout or "")[-1800:]
                    raise RuntimeError("local motion audio mux failed: " + detail)

                polished = self._polish_final_promo_mp4(
                    muxed_path,
                    output_path=output_path,
                    audio_asset=audio,
                    scenes=scenes,
                    vertical=vertical,
                    width=width,
                    height=height,
                )
        except Exception as exc:
            self._finish_job(job, status="ERROR", message=str(exc), asset_ids=[], provider="nova_ffmpeg_local_motion")
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
            content="Final promo rendered from local scene motion with Nova voice narration, captions, and getamicor.com CTA fade.",
            status="GENERATED",
            metadata={
                "final_promo": True,
                "render_mode": "local_motion_not_slideshow",
                "scene_count": len(scenes),
                "voice_asset_id": audio.id,
                "brand_overlay": "optional_owner_review",
                "captions_burned_in": bool(polished.get("captions_burned_in")),
                "subtitle_url": polished.get("subtitle_url"),
                "cta_fade": "getamicor.com",
                "commercial_slideshow": False,
                "commercial_ready_candidate": True,
                "publish_ready": False,
                "owner_review_required": True,
                "generation_mode": "local_image_motion_fallback",
            },
            url=public_url,
        )
        self._finish_job(
            job,
            status="GENERATED",
            message="Final AMICOR Nova promo rendered from local motion clips (not a still slideshow).",
            asset_ids=[asset.id],
            provider="nova_ffmpeg_local_motion",
        )
        return {"job": job.as_dict(), "asset": asset.as_dict(), "url": public_url}


    def _polish_final_promo_mp4(
        self,
        muxed_path: Path,
        *,
        output_path: Path,
        audio_asset: CreativeAsset,
        scenes: list[CreativeScene],
        vertical: bool,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        """Burn English captions + getamicor.com CTA fade onto the assembled MP4 when memory allows."""
        from app.core.nova.creative_studio.presenter_media import (
            burn_captions_and_cta_fade,
            even_spaced_cues,
        )

        provider_result = (audio_asset.metadata or {}).get("provider_result") or {}
        cues = provider_result.get("caption_cues")
        script = " ".join(
            str(scene.voiceover_text or scene.subtitle_text or "").strip()
            for scene in scenes
            if str(scene.voiceover_text or scene.subtitle_text or "").strip()
        )
        if not script:
            script = str(audio_asset.content or "").strip()
        if not cues:
            # Approximate duration from scene plan when whisper cues are unavailable.
            approx = sum(float(getattr(scene, "duration_seconds", 5) or 5) for scene in scenes) or 30.0
            cues = even_spaced_cues(script or "Visit getamicor.com", approx)

        try:
            polished, srt = burn_captions_and_cta_fade(
                muxed_path,
                cues,
                width=width if vertical else max(width, 720),
                height=height if vertical else max(height, 720),
                cta_text="getamicor.com",
                fade_seconds=2.5,
            )
            output_path.write_bytes(polished.read_bytes())
            srt_dest = output_path.with_suffix(".srt")
            srt_dest.write_text(srt.read_text(encoding="utf-8"), encoding="utf-8")
            public_prefix = _creative_media_root_and_prefix()[1]
            return {
                "captions_burned_in": True,
                "subtitle_url": public_prefix + "/" + srt_dest.name,
            }
        except Exception as exc:
            # Preserve the muxed MP4 rather than failing the whole commercial when
            # caption burn-in is blocked by memory; attach an SRT sidecar when possible.
            output_path.write_bytes(muxed_path.read_bytes())
            subtitle_url = None
            try:
                from app.core.nova.creative_studio.presenter_media import srt_text
                srt_dest = output_path.with_suffix(".srt")
                srt_dest.write_text(srt_text(cues), encoding="utf-8")
                subtitle_url = _creative_media_root_and_prefix()[1] + "/" + srt_dest.name
            except Exception:
                subtitle_url = None
            return {
                "captions_burned_in": False,
                "captions_sidecar_ready": bool(subtitle_url),
                "subtitle_url": subtitle_url,
                "caption_render_error": str(exc),
            }

    def preflight_quote(self, owner_id: str, project_id: str) -> dict[str, Any]:
        from app.core.nova.creative_studio.preflight import quote_project_render

        project = self._project_or_404(owner_id, project_id)
        scenes = self.store.list_scenes(project_id, owner_id)
        scene_count = len(scenes) or (6 if int(project.duration_target or 30) == 30 else 4)
        quote = quote_project_render(
            scene_count=scene_count,
            include_voice=True,
            include_images=True,
            include_presenter_lipsync=True,
            include_cloud_captions=True,
            duration_target=int(project.duration_target or 30),
        )
        meta = dict(project.metadata or {})
        confirmation = meta.get("budget_confirmation") or {}
        quote["project_id"] = project_id
        quote["owner_budget_confirmed"] = bool(confirmation.get("confirmed"))
        quote["confirmation"] = confirmation or None
        return quote

    def confirm_render_budget(
        self,
        owner_id: str,
        project_id: str,
        *,
        confirmed: bool,
        acknowledged_estimate_usd: float | None = None,
        note: str = "",
    ) -> dict[str, Any]:
        project = self._project_or_404(owner_id, project_id)
        quote = self.preflight_quote(owner_id, project_id)
        # Acknowledging the quote is separate from authorizing provider execution.
        meta = dict(project.metadata or {})
        meta["budget_confirmation"] = {
            "confirmed": bool(confirmed),
            "acknowledged_estimate_usd": acknowledged_estimate_usd,
            "quote_estimated_total_usd": quote.get("estimated_total_usd"),
            "note": str(note or "")[:500],
            "confirmed_at": _now() if confirmed else None,
        }
        project.metadata = meta
        project.updated_at = _now()
        self.store.save_project(project)
        return {"project_id": project_id, "budget_confirmation": meta["budget_confirmation"], "quote": quote}

    def require_budget_confirmation_for_paid(self, owner_id: str, project_id: str) -> None:
        from app.core.nova.creative_studio.flags import (
            image_provider_live_enabled,
            talking_presenter_provider_live_enabled,
            video_provider_live_enabled,
            voice_provider_live_enabled,
        )

        if not any(
            [
                image_provider_live_enabled(),
                voice_provider_live_enabled(),
                video_provider_live_enabled(),
                talking_presenter_provider_live_enabled(),
            ]
        ):
            return
        project = self._project_or_404(owner_id, project_id)
        confirmation = (project.metadata or {}).get("budget_confirmation") or {}
        if confirmation.get("confirmed") is True:
            quote = self.preflight_quote(owner_id, project_id)
            if quote.get("paid_render_allowed") is not True:
                raise CreativeStudioError(
                    "PROVIDER_FUNDING_UNVERIFIED",
                    "Budget approval is recorded, but provider funding/readiness "
                    "cannot be verified. No paid render was started.",
                    http_status=422,
                )
            return
        raise CreativeStudioError(
            "BUDGET_CONFIRMATION_REQUIRED",
            "Owner budget confirmation is required before paid Creative Studio provider renders. "
            "Run preflight, review the estimate, then confirm. No automatic purchases.",
            http_status=422,
        )

    def persist_browser_final_promo(
        self,
        owner_id: str,
        project_id: str,
        *,
        data: bytes,
        filename: str = "amicor-nova-final-promo.webm",
        content_type: str = "video/webm",
    ) -> dict[str, Any]:
        self._project_or_404(owner_id, project_id)
        if not data:
            raise CreativeStudioError("EMPTY_UPLOAD", "The browser final promo file was empty.", http_status=422)
        if len(data) > 150 * 1024 * 1024:
            raise CreativeStudioError("UPLOAD_TOO_LARGE", "The browser final promo is larger than 150 MB.", http_status=422)

        suffix = Path(filename or "").suffix.lower()
        if suffix not in {".webm", ".mp4"}:
            suffix = ".mp4" if str(content_type or "").lower() == "video/mp4" else ".webm"

        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"nova-browser-final-{new_id('promo').split('_', 1)[-1]}{suffix}"
        output_path.write_bytes(data)

        asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title="Final AMICOR Nova promo",
            content="Final promo assembled safely in the owner's browser from generated Creative Studio assets.",
            status="GENERATED",
            metadata={
                "final_promo": True,
                "render_mode": "browser_safe_upload",
                "publish_ready": False,
                "owner_review_required": True,
                "commercial_ready_candidate": suffix == ".mp4",
                "commercial_slideshow": "slideshow" in str(filename or "").lower(),
                "content_type": content_type,
                "file_size_bytes": len(data),
                "acceptance_note": (
                    "Browser WebM uploads are review helpers only. Commercial acceptance requires a motion MP4 "
                    "with English voice continuity, captions, and getamicor.com CTA — not a still slideshow."
                ),
            },
            url=public_prefix + "/" + output_path.name,
        )
        job = self._start_job(owner_id, project_id, "short_video_assembly")
        self._finish_job(
            job,
            status="GENERATED",
            message="Browser-safe final AMICOR Nova promo saved successfully.",
            asset_ids=[asset.id],
            provider="nova_browser_mediarecorder",
        )
        return {"asset": asset.as_dict(), "url": asset.url, "status": "GENERATED"}


    def click_destinations(self, platform: str, *, verify: bool = False) -> dict[str, Any]:
        from app.core.nova.creative_studio.click_destinations import replacement_pack, verify_click_destination

        pack = replacement_pack(platform)
        if verify:
            probed = verify_click_destination(pack["website_field_url"])
            pack.update(
                {
                    "http_status": probed["http_status"],
                    "final_url": probed["final_url"],
                    "redirect_chain": probed["chain"],
                    "classification": probed["classification"],
                    "verified": probed["verified"],
                }
            )
        pack["publish"] = False
        return pack

    def _project_voice_license(self, owner_id: str, project_id: str) -> str | None:
        project = self._project_or_404(owner_id, project_id)
        acceptance = (project.metadata or {}).get("voice_license_acceptance") or {}
        if acceptance.get("accepted") is True:
            return "GREEN"
        return None

    def accept_voice_license(
        self,
        owner_id: str,
        project_id: str,
        *,
        accepted: bool = True,
        note: str = "",
    ) -> dict[str, Any]:
        """Owner accepts the Studio neural voice source for this commercial (AMBER → GREEN)."""
        project = self._project_or_404(owner_id, project_id)
        meta = dict(project.metadata or {})
        meta["voice_license_acceptance"] = {
            "accepted": bool(accepted),
            "note": str(note or "")[:500],
            "accepted_at": _now() if accepted else None,
            "engine": "edge-tts",
            "statement": (
                "Owner accepts the free Microsoft Edge neural TTS voice used by AMICOR Studio "
                "for this project's commercial narration. No paid provider credits were purchased."
            ),
        }
        project.metadata = meta
        project.updated_at = _now()
        self.store.save_project(project)
        return {
            "project_id": project_id,
            "license_status": "GREEN" if accepted else "AMBER",
            "voice_license_acceptance": meta["voice_license_acceptance"],
        }

    def _resolve_genova_presenter_image(self, owner_id: str, project_id: str) -> Path | None:
        """Prefer project Genova full-body stills; fall back to known media-root plates."""
        preferred_names = (
            "nova-c4edd02f88a04f7081a79a18fd98a935.png",
            "nova-18f6ccddce0249f7a77e696c808fdf89.png",
        )
        assets = [
            asset
            for asset in self.store.list_assets(project_id, owner_id)
            if asset.kind == "image"
            and asset.url
            and str(asset.status or "").upper() == "GENERATED"
        ]

        def _is_genova(asset: CreativeAsset) -> bool:
            content = str(asset.content or "").lower()
            return (
                "genova presenter v2" in content
                or (
                    ("black woman" in content or "african american woman" in content)
                    and "presenter" in content
                )
            )

        scored: list[tuple[int, Path]] = []
        for asset in assets:
            path = _resolve_creative_media_url(asset.url)
            if path is None or not path.is_file():
                continue
            name = path.name.lower()
            score = 0
            if name in preferred_names:
                score += 100
            if _is_genova(asset):
                score += 50
            if name.startswith("nova-") and name.endswith(".png"):
                score += 5
            if score:
                scored.append((score, path))
        if scored:
            scored.sort(key=lambda item: item[0], reverse=True)
            return scored[0][1]

        root, _prefix = _creative_media_root_and_prefix()
        for name in preferred_names:
            candidate = root / name
            if candidate.is_file():
                return candidate
        return None

    @serialized_media
    def render_walking_presenter_proof(
        self,
        owner_id: str,
        project_id: str,
        *,
        script: str | None = None,
        voice: str | None = None,
    ) -> dict[str, Any]:
        """Issue #351 milestone: 5–6s full-body walking presenter with speech, lip motion, captions.

        No fal/Kling/D-ID/OpenAI calls and no credit purchases.
        """
        from app.core.nova.creative_studio.walking_presenter import (
            DEFAULT_SCRIPT,
            DEFAULT_VOICE,
            WalkingPresenterError,
            render_walking_presenter,
        )

        self._project_or_404(owner_id, project_id)
        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        token = new_id("walk").split("_", 1)[-1]
        output_path = output_dir / f"nova-walk-presenter-{token}.mp4"
        presenter_image = self._resolve_genova_presenter_image(owner_id, project_id)
        job = self._start_job(owner_id, project_id, "walking_presenter_proof")
        try:
            rendered = render_walking_presenter(
                output_mp4=output_path,
                script=script or DEFAULT_SCRIPT,
                voice=voice or DEFAULT_VOICE,
                license_status=self._project_voice_license(owner_id, project_id),
                presenter_image=presenter_image,
            )
        except WalkingPresenterError as exc:
            self._finish_job(
                job,
                status="ERROR",
                message=exc.message,
                asset_ids=[],
                provider="nova_walking_presenter",
            )
            raise CreativeStudioError(exc.code, exc.message, http_status=422) from exc
        except Exception as exc:
            self._finish_job(
                job,
                status="ERROR",
                message=str(exc)[:500],
                asset_ids=[],
                provider="nova_walking_presenter",
            )
            raise CreativeStudioError("WALKING_PRESENTER_FAILED", str(exc)[:500], http_status=422) from exc

        if not (rendered.get("validation") or {}).get("ok"):
            self._finish_job(
                job,
                status="ERROR",
                message="Walking presenter failed automated H.264/AAC duration validation.",
                asset_ids=[],
                provider="nova_walking_presenter",
            )
            raise CreativeStudioError(
                "WALKING_PRESENTER_VALIDATION_FAILED",
                "Rendered file did not pass 5–6s H.264/AAC validation.",
                http_status=422,
            )

        public_url = public_prefix + "/" + output_path.name
        audio_url = public_prefix + "/" + output_path.with_suffix(".wav").name
        subtitle_url = public_prefix + "/" + output_path.with_suffix(".srt").name
        audio_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="audio",
            title="Walking presenter narration",
            content=rendered.get("script") or "",
            status="GENERATED",
            metadata={
                "provider_result": rendered.get("narration") or {},
                "paid_provider_charges": False,
                "lip_sync": True,
                "natural_female_voice": True,
            },
            url=audio_url,
        )
        video_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="presenter_video",
            title="5s full-body walking presenter proof",
            content=rendered.get("script") or "",
            status="GENERATED",
            metadata={
                **{key: value for key, value in rendered.items() if key not in {"subtitle_path", "audio_path"}},
                "subtitle_url": subtitle_url,
                "body_lipsync": True,
                "captions_burned_in": True,
                "quality_state": "OWNER_REVIEW_READY",
                "publish_ready": False,
                "external_publishing": False,
            },
            url=public_url,
        )
        visual_mode = str(rendered.get("visual_mode") or "illustrated_fallback")
        self._finish_job(
            job,
            status="GENERATED",
            message=(
                f"Walking presenter proof ready at {rendered['duration_seconds']}s with "
                f"{visual_mode}, natural female narration, phoneme lip motion, and word-aligned captions. "
                "No paid provider was charged."
            ),
            asset_ids=[video_asset.id, audio_asset.id],
            provider="nova_walking_presenter",
        )
        return {
            "job": job.as_dict(),
            "asset": video_asset.as_dict(),
            "audio": audio_asset.as_dict(),
            "url": public_url,
            "download_url": f"/api/nova/creative/projects/{project_id}/assets/{video_asset.id}/file",
            "audio_download_url": f"/api/nova/creative/projects/{project_id}/assets/{audio_asset.id}/file",
            "poll_url": f"/api/nova/creative/projects/{project_id}/jobs/{job.id}",
            "lip_sync": True,
            "render_mode": "local_walking_presenter_lipsync",
            "milestone": "5s_walking_presenter",
            "visual_mode": visual_mode,
            "illustrated_fallback": rendered.get("illustrated_fallback"),
            "genova_photoreal_plate": rendered.get("genova_photoreal_plate"),
            "true_ai_motion_synthesis": False,
            "paid_motion_blocker": rendered.get("paid_motion_blocker"),
            "validation": rendered.get("validation"),
            "license_status": (rendered.get("narration") or {}).get("license_status") or "AMBER",
            "paid_provider_charges": False,
            "publish_ready": False,
            "owner_review_required": True,
        }

    @serialized_media
    def render_walking_commercial_30s(self, owner_id: str, project_id: str) -> dict[str, Any]:
        """30s H.264/AAC walking talking commercial for mobile download. No paid provider spend."""
        from app.core.nova.creative_studio.click_destinations import replacement_pack
        from app.core.nova.creative_studio.walking_presenter import (
            WalkingPresenterError,
            render_walking_commercial_30s,
        )

        project = self._project_or_404(owner_id, project_id)
        scenes = self.store.list_scenes(project_id, owner_id)
        if not scenes:
            raise CreativeStudioError("STORYBOARD_REQUIRED", "Generate the storyboard first.", http_status=422)
        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        token = new_id("promo30").split("_", 1)[-1]
        output_path = output_dir / f"nova-walk-commercial-30s-{token}.mp4"
        presenter_image = self._resolve_genova_presenter_image(owner_id, project_id)
        job = self._start_job(owner_id, project_id, "walking_commercial_30s")
        try:
            rendered = render_walking_commercial_30s(
                output_mp4=output_path,
                scenes=[scene.as_dict() for scene in scenes],
                license_status=self._project_voice_license(owner_id, project_id),
                presenter_image=presenter_image,
            )
        except WalkingPresenterError as exc:
            self._finish_job(job, status="ERROR", message=exc.message, asset_ids=[], provider="nova_walking_commercial")
            raise CreativeStudioError(exc.code, exc.message, http_status=422) from exc
        except Exception as exc:
            self._finish_job(job, status="ERROR", message=str(exc)[:500], asset_ids=[], provider="nova_walking_commercial")
            raise CreativeStudioError("WALKING_COMMERCIAL_FAILED", str(exc)[:500], http_status=422) from exc

        if not (rendered.get("validation") or {}).get("ok"):
            self._finish_job(
                job,
                status="ERROR",
                message="30s walking commercial failed H.264/AAC duration validation.",
                asset_ids=[],
                provider="nova_walking_commercial",
            )
            raise CreativeStudioError(
                "WALKING_COMMERCIAL_VALIDATION_FAILED",
                "Rendered file did not pass 30s H.264/AAC validation.",
                http_status=422,
            )

        click = replacement_pack(project.platform)
        public_url = public_prefix + "/" + output_path.name
        audio_url = public_prefix + "/" + output_path.with_suffix(".wav").name
        subtitle_url = public_prefix + "/" + output_path.with_suffix(".srt").name
        audio_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="audio",
            title="30s walking commercial narration",
            content=rendered.get("script") or "",
            status="GENERATED",
            metadata={
                "provider_result": rendered.get("narration") or {},
                "paid_provider_charges": False,
                "lip_sync": True,
                "natural_female_voice": True,
            },
            url=audio_url,
        )
        video_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title="30s AMICOR walking talking commercial",
            content=rendered.get("script") or "",
            status="GENERATED",
            metadata={
                "final_promo": True,
                **{key: value for key, value in rendered.items() if key not in {"subtitle_path", "audio_path"}},
                "subtitle_url": subtitle_url,
                "click_destination": click,
                "body_lipsync": True,
                "external_publishing": False,
                "quality_state": "OWNER_REVIEW_READY",
            },
            url=public_url,
        )
        visual_mode = str(rendered.get("visual_mode") or "illustrated_fallback")
        self._finish_job(
            job,
            status="GENERATED",
            message=(
                f"30s walking talking commercial ready at {rendered['duration_seconds']}s "
                f"({visual_mode}). Downloadable H.264/AAC with speech, phoneme lip motion, and captions. "
                "No paid provider was charged. Owner review still required before public ads."
            ),
            asset_ids=[video_asset.id, audio_asset.id],
            provider="nova_walking_commercial",
        )
        return {
            "job": job.as_dict(),
            "asset": video_asset.as_dict(),
            "audio": audio_asset.as_dict(),
            "url": public_url,
            "download_url": f"/api/nova/creative/projects/{project_id}/assets/{video_asset.id}/file",
            "audio_download_url": f"/api/nova/creative/projects/{project_id}/assets/{audio_asset.id}/file",
            "poll_url": f"/api/nova/creative/projects/{project_id}/jobs/{job.id}",
            "lip_sync": True,
            "render_mode": "local_walking_commercial_30s",
            "milestone": "30s_walking_commercial",
            "visual_mode": visual_mode,
            "illustrated_fallback": rendered.get("illustrated_fallback"),
            "genova_photoreal_plate": rendered.get("genova_photoreal_plate"),
            "true_ai_motion_synthesis": False,
            "paid_motion_blocker": rendered.get("paid_motion_blocker"),
            "validation": rendered.get("validation"),
            "license_status": rendered.get("license_status") or "AMBER",
            "paid_provider_charges": False,
            "mobile_download_ready": True,
            "publish_ready": False,
            "owner_review_required": True,
        }

    def complete_studio_test_checkout(self, owner_id: str, project_id: str, order_id: str) -> dict[str, Any]:
        from app.core.nova.creative_studio.studio_checkout import complete_test_checkout

        self._project_or_404(owner_id, project_id)
        try:
            order = complete_test_checkout(order_id, owner_id=owner_id, db=self._studio_db())
        except KeyError as exc:
            raise CreativeStudioError("NOT_FOUND", "Checkout order not found", http_status=404) from exc
        except ValueError as exc:
            raise CreativeStudioError("CHECKOUT_BLOCKED", str(exc), http_status=422) from exc
        if order.get("project_id") != project_id:
            raise CreativeStudioError("NOT_FOUND", "Checkout order not found", http_status=404)
        return {
            "order": order,
            "receipt": order.get("receipt"),
            "job_status": order.get("job_status"),
            "fulfillment": order.get("fulfillment"),
        }

    def studio_pricing(self) -> dict[str, Any]:
        from app.core.nova.creative_studio.studio_checkout import public_pricing

        return public_pricing()

    def start_studio_checkout(
        self,
        owner_id: str,
        project_id: str,
        *,
        customer_email: str | None = None,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        from app.core.nova.creative_studio.studio_checkout import create_studio_checkout_order

        quote = self.preflight_quote(owner_id, project_id)
        try:
            started = create_studio_checkout_order(
                owner_id=owner_id,
                project_id=project_id,
                customer_email=customer_email,
                success_url=success_url,
                cancel_url=cancel_url,
                estimated_render_cost_usd=float(quote.get("estimated_total_usd") or 0),
                db=self._studio_db(),
            )
        except ValueError as exc:
            raise CreativeStudioError("CHECKOUT_BLOCKED", str(exc), http_status=422) from exc
        except RuntimeError as exc:
            raise CreativeStudioError("CHECKOUT_UNAVAILABLE", str(exc), http_status=503) from exc
        order = started["order"]
        self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="export",
            title="AMICOR Studio checkout order",
            content=(
                f"Order {order['id']} · ${order['customer_price_usd']:.2f} · "
                f"{order['scope']} · status {order['status']}"
            ),
            status="GENERATED",
            metadata={
                "order": order,
                "checkout": started.get("checkout"),
                "quote_estimated_total_usd": quote.get("estimated_total_usd"),
            },
            url=None,
        )
        return {
            **started,
            "quote": {
                "estimated_total_usd": quote.get("estimated_total_usd"),
                "purchasing_enabled": False,
                "auto_top_up": False,
                "paid_render_allowed": quote.get("paid_render_allowed"),
            },
        }

    def list_studio_checkout_orders(self, owner_id: str, project_id: str) -> dict[str, Any]:
        from app.core.nova.creative_studio.studio_checkout import list_studio_orders

        self._project_or_404(owner_id, project_id)
        orders = list_studio_orders(owner_id=owner_id, project_id=project_id, db=self._studio_db())
        return {"project_id": project_id, "orders": orders, "pricing": self.studio_pricing()}

    def get_studio_checkout_order(self, owner_id: str, project_id: str, order_id: str) -> dict[str, Any]:
        from app.core.nova.creative_studio.studio_checkout import get_studio_order, sync_studio_order_from_stripe

        self._project_or_404(owner_id, project_id)
        db = self._studio_db()
        try:
            order = sync_studio_order_from_stripe(order_id, owner_id=owner_id, db=db)
        except KeyError as exc:
            raise CreativeStudioError("NOT_FOUND", "Checkout order not found", http_status=404) from exc
        except Exception:
            order = get_studio_order(order_id, owner_id=owner_id, db=db)
            if order is None:
                raise CreativeStudioError("NOT_FOUND", "Checkout order not found", http_status=404)
        if order.get("project_id") != project_id:
            raise CreativeStudioError("NOT_FOUND", "Checkout order not found", http_status=404)
        return {
            "order": order,
            "receipt": order.get("receipt"),
            "job_status": order.get("job_status"),
            "fulfillment": order.get("fulfillment"),
        }

    def render_offline_commercial(self, owner_id: str, project_id: str) -> dict[str, Any]:
        """30s-style montage from the saved storyboard. Does not call image, voice, or video providers."""
        from app.core.nova.creative_studio.click_destinations import replacement_pack
        from app.core.nova.creative_studio.offline_commercial import OfflineCommercialError, render_offline_montage

        project = self._project_or_404(owner_id, project_id)
        scenes = self.store.list_scenes(project_id, owner_id)
        if not scenes:
            raise CreativeStudioError("STORYBOARD_REQUIRED", "Generate the storyboard first.", http_status=422)
        vertical = str(project.platform or "").strip().lower() in {"tiktok", "instagram", "youtube shorts"}
        output_dir, public_prefix = _creative_media_root_and_prefix()
        output_dir.mkdir(parents=True, exist_ok=True)
        token = new_id("promo").split("_", 1)[-1]
        output_path = output_dir / f"nova-offline-{token}.mp4"
        audio_path = output_dir / f"nova-offline-{token}.wav"
        job = self._start_job(owner_id, project_id, "offline_commercial")
        try:
            rendered = render_offline_montage(
                [scene.as_dict() for scene in scenes],
                output_mp4=output_path,
                audio_wav=audio_path,
                vertical=vertical,
            )
        except OfflineCommercialError as exc:
            self._finish_job(job, status="ERROR", message=exc.message, asset_ids=[], provider="nova_offline_montage")
            raise CreativeStudioError(exc.code, exc.message, http_status=422) from exc
        except Exception as exc:
            self._finish_job(job, status="ERROR", message=str(exc), asset_ids=[], provider="nova_offline_montage")
            raise CreativeStudioError("OFFLINE_MONTAGE_FAILED", str(exc)[:500], http_status=422) from exc

        click = replacement_pack(project.platform)
        public_url = public_prefix + "/" + output_path.name
        audio_url = public_prefix + "/" + audio_path.name
        subtitle_url = public_prefix + "/" + output_path.with_suffix(".srt").name
        audio_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="audio",
            title="Offline narration",
            content="Local espeak narration of the reviewed storyboard. Not a paid presenter voice.",
            status="GENERATED",
            metadata={
                "provider_result": rendered["narration"],
                "paid_provider_charges": False,
                "lip_sync": False,
            },
            url=audio_url,
        )
        video_asset = self._save_text_asset(
            owner_id=owner_id,
            project_id=project_id,
            kind="video",
            title="Offline 30s AMICOR Nova montage",
            content=(
                "Local title-card montage with narration and burned captions. "
                "Not a lip-synced presenter. Not approved for public posting."
            ),
            status="GENERATED",
            metadata={
                "final_promo": True,
                **{key: value for key, value in rendered.items() if key != "subtitle_path"},
                "subtitle_url": subtitle_url,
                "click_destination": click,
                "external_publishing": False,
            },
            url=public_url,
        )
        self._finish_job(
            job,
            status="GENERATED",
            message=(
                f"Offline montage rendered at {rendered['duration_seconds']}s. "
                "No paid provider was called. Lip-sync and public posting stay off."
            ),
            asset_ids=[video_asset.id, audio_asset.id],
            provider="nova_offline_montage",
        )
        narration = rendered.get("narration") or {}
        return {
            "job": job.as_dict(),
            "asset": video_asset.as_dict(),
            "audio": audio_asset.as_dict(),
            "url": public_url,
            "download_url": f"/api/nova/creative/projects/{project_id}/assets/{video_asset.id}/file",
            "audio_download_url": f"/api/nova/creative/projects/{project_id}/assets/{audio_asset.id}/file",
            "poll_url": f"/api/nova/creative/projects/{project_id}/jobs/{job.id}",
            "click_destination": click,
            "lip_sync": False,
            "render_mode": "offline_montage_not_lipsync",
            "license_status": narration.get("license_status") or "AMBER",
            "commercial_use": narration.get("commercial_use") or "",
            "paid_provider_charges": False,
            "paid_render_allowed": False,
            "readiness_note": "License stays AMBER until the owner accepts the local narration license. Publishing is held.",
        }

    def get_generation_job(self, owner_id: str, project_id: str, job_id: str) -> dict[str, Any]:
        """Read one saved job. Polling this route does not start a provider."""
        self._project_or_404(owner_id, project_id)
        job = next((row for row in self.store.list_jobs(project_id, owner_id) if row.id == job_id), None)
        if job is None:
            raise CreativeStudioError("NOT_FOUND", "Job not found", http_status=404)
        lip_sync = None
        paid = None
        if job.provider == "nova_offline_montage":
            lip_sync = False
            paid = False
        elif job.provider in {"nova_walking_presenter", "nova_walking_commercial"}:
            lip_sync = True
            paid = False
        return {
            "job": job.as_dict(),
            "ready": job.status in {"GENERATED", "ERROR"},
            "lip_sync": lip_sync,
            "paid_provider_charges": paid,
        }

    def open_asset_file(self, owner_id: str, project_id: str, asset_id: str) -> tuple[Path, str, str]:
        """Owner-scoped file for playback download. Another account gets not found."""
        from app.core.nova.creative_studio.providers import _creative_media_root_and_prefix, _resolve_creative_media_url

        self._project_or_404(owner_id, project_id)
        asset = next((row for row in self.store.list_assets(project_id, owner_id) if row.id == asset_id), None)
        if asset is None:
            raise CreativeStudioError("NOT_FOUND", "Asset not found", http_status=404)
        path = _resolve_creative_media_url(asset.url)
        root, _prefix = _creative_media_root_and_prefix()
        if path is None or not path.is_file():
            raise CreativeStudioError("MEDIA_UNAVAILABLE", "This asset has no downloadable file.", http_status=404)
        resolved = path.resolve()
        root_resolved = root.resolve()
        if resolved != root_resolved and root_resolved not in resolved.parents:
            raise CreativeStudioError("MEDIA_UNAVAILABLE", "Asset file is outside the studio media directory.", http_status=404)
        media_types = {".mp4": "video/mp4", ".wav": "audio/wav", ".srt": "text/plain; charset=utf-8"}
        media_type = media_types.get(resolved.suffix.lower(), "application/octet-stream")
        return resolved, media_type, resolved.name

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
