"""Read-only first-shot readiness for Nova Creative Studio.

No provider submission, account spending, new assets, or automatic publication.
The report is only a preflight: a successful provider response and manual
movement/identity review are still required before film approval.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def first_shot_readiness(
    *,
    scenes: list[Any],
    assets: list[Any],
    provider_status: Any,
    budget_confirmed: bool,
    media_resolver: Any,
) -> dict[str, Any]:
    blockers: list[str] = []
    ordered_scenes = sorted(scenes, key=lambda row: int(getattr(row, "index", 0)))
    first_scene = ordered_scenes[0] if ordered_scenes else None
    first_index = int(getattr(first_scene, "index", 0)) if first_scene is not None else None
    if first_scene is None:
        blockers.append("STORYBOARD_REQUIRED")
    elif not str(getattr(first_scene, "visual_prompt", "") or getattr(first_scene, "description", "")).strip():
        blockers.append("FIRST_SCENE_PROMPT_REQUIRED")

    status = str(getattr(provider_status, "status", "") or "").upper()
    if status != "AVAILABLE":
        blockers.append("VIDEO_PROVIDER_NOT_AVAILABLE")

    if not budget_confirmed:
        blockers.append("BUDGET_CONFIRMATION_REQUIRED")

    # Do not report a usable reference based only on saved metadata or a URL.
    # The authenticated project-scoped store supplied these assets; require the
    # specific scene association and a resolvable local file for reuse.
    source_images = []
    for asset in assets:
        meta = getattr(asset, "metadata", None) or {}
        try:
            scene_index = int(meta.get("scene_index"))
        except (ValueError, TypeError):
            continue
        if (first_index is None or scene_index != first_index
                or getattr(asset, "kind", None) != "image"
                or str(getattr(asset, "status", "")).upper() != "GENERATED"
                or not getattr(asset, "url", None)):
            continue
        path = media_resolver(asset.url)
        if path is not None and Path(path).is_file():
            source_images.append(asset)
    if not source_images:
        blockers.append("FIRST_SCENE_REFERENCE_IMAGE_REQUIRED")

    return {
        "status": "READY_TO_REQUEST" if not blockers else "BLOCKED",
        "target_seconds": 5,
        "provider_status": status or "UNKNOWN",
        "first_scene_index": first_index,
        "reference_image_asset_id": str(getattr(source_images[-1], "id", "")) if source_images else None,
        "blockers": blockers,
        "generation_submitted": False,
        "provider_charge_incurred": False,
        "note": (
            "Non-billable readiness only. Existing scene generation remains "
            "separately owner-gated and may use a provider-selected duration; "
            "real actor quality and five-second duration are not verified."
        ),
    }
