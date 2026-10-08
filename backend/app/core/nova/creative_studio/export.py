"""Export Creative Studio project packages (JSON / Markdown). No publishing."""

from __future__ import annotations

import json
from typing import Any


def export_project_package(payload: dict[str, Any], *, fmt: str = "json") -> dict[str, Any]:
    fmt_norm = str(fmt or "json").strip().lower()
    if fmt_norm not in {"json", "markdown", "md", "text"}:
        raise ValueError("Unsupported export format")

    project = payload.get("project") or {}
    assets = payload.get("assets") or []
    scenes = payload.get("scenes") or []
    brand = payload.get("brand") or {}
    brief = payload.get("brief") or {}

    final_video = _latest_asset(
        assets,
        "video",
        predicate=lambda a: bool((a.get("metadata") or {}).get("final_promo")),
    )
    presenter_video = _latest_asset(assets, "presenter_video")
    image_asset = _latest_asset(assets, "image")
    audio_asset = _latest_asset(assets, "audio")

    presenter_meta = (presenter_video or {}).get("metadata") or {}
    presenter_is_publish_ready = presenter_publish_ready(presenter_meta)
    final_video_ready = bool(final_video and final_video.get("url"))
    production_ready = bool(final_video_ready and (not presenter_video or presenter_is_publish_ready))

    package = {
        "export_kind": "nova_creative_studio_project_package",
        "external_publishing": False,
        "external_submission": False,
        "financial_execution": False,
        "project": project,
        "brief": brief,
        "brand": brand,
        "script": _first_content(assets, "script"),
        "captions": _first_content(assets, "caption"),
        "hashtags": _first_content(assets, "hashtags"),
        "storyboard": _first_content(assets, "storyboard"),
        "scenes": scenes,
        "prompts": [a for a in assets if a.get("kind") == "image_prompt"],
        "voiceover_copy": _first_content(assets, "voiceover"),
        "social_media_package": {
            "production_ready": production_ready,
            "platform": project.get("platform"),
            "final_video": _asset_ref(final_video),
            "presenter_video": _asset_ref(presenter_video),
            "thumbnail_or_artwork": _asset_ref(image_asset),
            "voice_audio": _asset_ref(audio_asset),
            "caption_copy": _first_content(assets, "caption"),
            "hashtags": _first_content(assets, "hashtags"),
            "cta": brief.get("cta") or brand.get("preferred_cta") or "",
            "quality_notes": [
                "Final publishing remains owner-controlled.",
                "Presenter video must be marked publish_ready when one is included.",
                "Provider watermarks are never removed by Nova.",
            ],
        },
        "delivery_checklist": {
            "video_ready": final_video_ready,
            "presenter_ready": bool(not presenter_video or presenter_is_publish_ready),
            "caption_ready": bool(_first_content(assets, "caption")),
            "thumbnail_ready": bool(image_asset and image_asset.get("url")),
            "voice_ready": bool(audio_asset and audio_asset.get("url")),
            "brand_present": bool(brand),
        },
        "metadata": {
            "asset_count": len(assets),
            "scene_count": len(scenes),
            "status_note": "Package may include real provider media, but external publishing remains OFF until owner action.",
        },
    }

    if fmt_norm == "json":
        body = json.dumps(package, indent=2, ensure_ascii=True)
        mime = "application/json"
    else:
        body = _to_markdown(package)
        mime = "text/markdown"

    return {
        "format": "json" if fmt_norm == "json" else "markdown",
        "mime_type": mime,
        "content": body,
        "package": package,
        "status": "GENERATED",
        "url": None,
    }



def presenter_publish_ready(metadata: dict[str, Any] | None) -> bool:
    """PREVIEW_ONLY and watermarked provider output are never publish-ready."""
    meta = metadata or {}
    if meta.get("publish_ready") is not True:
        return False
    if str(meta.get("quality_state") or "").strip().upper() == "PREVIEW_ONLY":
        return False
    if meta.get("provider_watermark_preserved") is True:
        return False
    provider_result = meta.get("provider_result") or {}
    if not isinstance(provider_result, dict):
        provider_result = {}
    if provider_result.get("watermark_free") is False:
        return False
    if str(provider_result.get("quality_state") or "").strip().upper() == "PREVIEW_ONLY":
        return False
    return True


def _latest_asset(
    assets: list[dict[str, Any]],
    kind: str,
    *,
    predicate=None,
) -> dict[str, Any] | None:
    matches = [a for a in assets if a.get("kind") == kind]
    if predicate is not None:
        matches = [a for a in matches if predicate(a)]
    for asset in reversed(matches):
        if str(asset.get("status") or "").upper() == "GENERATED":
            return asset
    return matches[-1] if matches else None


def _asset_ref(asset: dict[str, Any] | None) -> dict[str, Any] | None:
    if not asset:
        return None
    metadata = asset.get("metadata") or {}
    return {
        "id": asset.get("id"),
        "title": asset.get("title"),
        "kind": asset.get("kind"),
        "status": asset.get("status"),
        "url": asset.get("url"),
        "quality_state": metadata.get("quality_state"),
        "publish_ready": presenter_publish_ready(metadata),
        "subtitle_url": metadata.get("subtitle_url"),
    }

def _first_content(assets: list[dict[str, Any]], kind: str) -> str:
    for asset in assets:
        if asset.get("kind") == kind:
            return str(asset.get("content") or "")
    return ""


def _to_markdown(package: dict[str, Any]) -> str:
    project = package.get("project") or {}
    lines = [
        f"# {project.get('title') or 'Creative Project'}",
        "",
        f"- Type: {project.get('project_type')}",
        f"- Platform: {project.get('platform')}",
        f"- Status: {project.get('status')}",
        "",
        "## Script",
        package.get("script") or "_none_",
        "",
        "## Captions",
        package.get("captions") or "_none_",
        "",
        "## Hashtags",
        package.get("hashtags") or "_none_",
        "",
        "## Storyboard",
        package.get("storyboard") or "_none_",
        "",
        "## Voiceover",
        package.get("voiceover_copy") or "_none_",
        "",
        "## Production package",
        f"- Production ready: {(package.get('social_media_package') or {}).get('production_ready')}",
        f"- Final video: {((package.get('social_media_package') or {}).get('final_video') or {}).get('url') or '_none_'}",
        f"- Presenter video: {((package.get('social_media_package') or {}).get('presenter_video') or {}).get('url') or '_none_'}",
        f"- Thumbnail/artwork: {((package.get('social_media_package') or {}).get('thumbnail_or_artwork') or {}).get('url') or '_none_'}",
        f"- Voice audio: {((package.get('social_media_package') or {}).get('voice_audio') or {}).get('url') or '_none_'}",
        f"- CTA: {(package.get('social_media_package') or {}).get('cta') or '_none_'}",
        "",
        "## Scenes",
    ]
    for scene in package.get("scenes") or []:
        lines.append(
            f"### {scene.get('index')}. {scene.get('heading')} ({scene.get('duration_seconds')}s)"
        )
        lines.append(scene.get("description") or "")
        lines.append(f"VO: {scene.get('voiceover_text') or ''}")
        lines.append(f"Visual: {scene.get('visual_prompt') or ''}")
        lines.append("")
    lines.append("## Safety")
    lines.append("External publishing: OFF. This export is for owner download only.")
    return "\n".join(lines)
