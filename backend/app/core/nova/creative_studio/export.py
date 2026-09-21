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
        "metadata": {
            "asset_count": len(assets),
            "scene_count": len(scenes),
            "status_note": "Planning/generated text only unless a real provider completed media.",
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
