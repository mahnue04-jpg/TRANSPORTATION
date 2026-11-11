"""Non-billable Creative Studio preflight quotes and budget confirmation.

Never submits paid provider jobs. Never purchases credits. Balance is either
owner-reported via env or returned as cannot_verify — no secret values are exposed.
"""

from __future__ import annotations

import os
import math
from typing import Any

from app.core.nova.creative_studio.flags import (
    image_provider_configured,
    image_provider_live_enabled,
    selected_video_provider,
    talking_presenter_provider_configured,
    talking_presenter_provider_live_enabled,
    video_provider_configured,
    video_provider_live_enabled,
    voice_provider_configured,
    voice_provider_live_enabled,
)

# Rough planning estimates only — not invoices and not provider quotes.
_EST_IMAGE_USD = 0.04
_EST_VOICE_USD = 0.03
_EST_SCENE_MOTION_USD = 0.28  # ~5s Kling-class image-to-video planning estimate
_EST_LIPSYNC_USD = 0.05
_EST_CAPTION_CLOUD_USD = 0.04


def _env_float(name: str) -> float | None:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
        return value if math.isfinite(value) else None
    except ValueError:
        return None


def accessible_balance_status() -> dict[str, Any]:
    """Report balance without calling paid generation APIs or disclosing keys."""
    reported = _env_float("NOVA_CREATIVE_OWNER_REPORTED_FAL_BALANCE_USD")
    if reported is None:
        return {
            "status": "cannot_verify",
            "currency": "USD",
            "amount": None,
            "message": (
                "Nova cannot verify the live fal credit balance from this environment. "
                "Review the available balance before approving paid work; Nova never tops up automatically."
            ),
        }
    return {
        "status": "owner_reported",
        "currency": "USD",
        "amount": reported,
        "message": (
            "Using owner-reported fal balance only. Nova does not auto-top-up or purchase credits."
            if reported >= 0
            else "Owner-reported fal balance is negative. Paid fal renders stay blocked until funds are approved."
        ),
    }


def provider_readiness_matrix() -> dict[str, Any]:
    selected = selected_video_provider()
    return {
        "image": {
            "configured": image_provider_configured(),
            "live_enabled": image_provider_live_enabled(),
        },
        "voice": {
            "configured": voice_provider_configured(),
            "live_enabled": voice_provider_live_enabled(),
        },
        "video": {
            "provider": selected,
            "configured": video_provider_configured(),
            "live_enabled": video_provider_live_enabled(),
        },
        "talking_presenter": {
            "configured": talking_presenter_provider_configured(),
            "live_enabled": talking_presenter_provider_live_enabled(),
        },
        "fal_key_present": bool(str(os.getenv("FAL_KEY") or "").strip()),
        "runway_key_present": bool(
            str(os.getenv("RUNWAYML_API_SECRET") or os.getenv("NOVA_CREATIVE_VIDEO_API_KEY") or "").strip()
        ),
        "did_key_present": bool(str(os.getenv("DID_API_KEY") or "").strip()),
        "openai_key_present": bool(str(os.getenv("OPENAI_API_KEY") or "").strip()),
    }


def quote_project_render(
    *,
    scene_count: int,
    include_voice: bool = True,
    include_images: bool = True,
    include_presenter_lipsync: bool = True,
    include_cloud_captions: bool = True,
    duration_target: int = 30,
) -> dict[str, Any]:
    scenes = max(0, int(scene_count or 0))
    line_items: list[dict[str, Any]] = []
    total = 0.0

    if include_images and scenes:
        cost = round(scenes * _EST_IMAGE_USD, 4)
        total += cost
        line_items.append(
            {
                "id": "scene_source_images",
                "label": f"Source images × {scenes}",
                "estimated_usd": cost,
                "billable_if_live": True,
            }
        )
    if scenes:
        cost = round(scenes * _EST_SCENE_MOTION_USD, 4)
        total += cost
        line_items.append(
            {
                "id": "scene_motion",
                "label": f"Scene motion (~5s) × {scenes}",
                "estimated_usd": cost,
                "billable_if_live": True,
            }
        )
    if include_voice:
        total += _EST_VOICE_USD
        line_items.append(
            {
                "id": "english_voice",
                "label": "English female voice narration",
                "estimated_usd": _EST_VOICE_USD,
                "billable_if_live": True,
            }
        )
    if include_presenter_lipsync:
        total += _EST_LIPSYNC_USD
        line_items.append(
            {
                "id": "lipsync",
                "label": "Presenter lip-sync pass",
                "estimated_usd": _EST_LIPSYNC_USD,
                "billable_if_live": True,
            }
        )
    if include_cloud_captions:
        total += _EST_CAPTION_CLOUD_USD
        line_items.append(
            {
                "id": "captions",
                "label": "Timed / burned-in captions",
                "estimated_usd": _EST_CAPTION_CLOUD_USD,
                "billable_if_live": True,
            }
        )

    balance = accessible_balance_status()
    readiness = provider_readiness_matrix()
    any_live = any(
        [
            readiness["image"]["live_enabled"],
            readiness["voice"]["live_enabled"],
            readiness["video"]["live_enabled"],
            readiness["talking_presenter"]["live_enabled"],
        ]
    )
    paid_blocked = bool(
        any_live
        and (
            balance.get("status") == "cannot_verify"
            or (isinstance(balance.get("amount"), (int, float)) and float(balance["amount"]) < 0)
        )
    )

    return {
        "quote_kind": "nova_creative_studio_preflight",
        "duration_target": int(duration_target or 30),
        "scene_count": scenes,
        "currency": "USD",
        "estimated_total_usd": round(total, 4),
        "line_items": line_items,
        "balance": balance,
        "providers": readiness,
        "paid_render_allowed": False if paid_blocked else bool(any_live),
        "requires_owner_budget_confirmation": True,
        "auto_retry_ambiguous_provider_jobs": False,
        "auto_top_up": False,
        "purchasing_enabled": False,
        "notes": [
            "Estimates are planning-only and may differ from provider invoices.",
            "Local Ken Burns / FFmpeg motion fallback does not call paid video providers.",
            "No spontaneous top-ups. No purchasing from Nova.",
            "Slideshow-of-stills exports are never commercial-acceptance.",
        ],
    }

