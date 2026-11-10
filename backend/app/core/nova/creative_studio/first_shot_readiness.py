"""Read-only readiness contract for the first real Creative Studio video shot.

No paid provider calls or asset changes. This module deliberately does not
infer that a video is ready merely because a provider API key is present.
"""
from __future__ import annotations

from typing import Any


def first_shot_readiness(
    *,
    scenes: list[Any],
    assets: list[Any],
    provider_status: Any,
    budget_confirmed: bool,
) -> dict[str, Any]:
    blockers: list[str] = []
    if not scenes:
        blockers.append("STORYBOARD_REQUIRED")

    status = str(getattr(provider_status, "status", "")).upper()
    if status != "AVAILABLE":
        blockers.append("VIDEO_PROVIDER_NOT_AVAILABLE")

    if not budget_confirmed:
        blockers.append("BUDGET_CONFIRMATION_REQUIRED")

    # The first storyboard scene must have reusable, source-traced image
    # artwork. The preview must not quietly use an unrelated project's image.
    first_index = int(getattr(scenes[0], "index", 0)) if scenes else None
    source_images = [
        asset for asset in assets
        if getattr(asset, "kind", None) == "image"
        and str(getattr(asset, "status", "")).upper() == "GENERATED"
        and bool(getattr(asset, "url", None))
        and (getattr(asset, "metadata", None) or {}).get("scene_index") == first_index
    ]
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
            "This is a non-billable readiness check, not proof of successful "
            "animation or a commitment to a fixed provider duration."
        ),
    }
