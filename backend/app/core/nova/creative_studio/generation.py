"""Deterministic content generation contracts for Creative Studio V1."""

from __future__ import annotations

import re
from typing import Any

from app.core.nova.creative_studio.models import DURATIONS


def _slug_words(text: str, limit: int = 8) -> list[str]:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())
    return words[:limit] or ["amicor", "nova"]


def _hashtags(topic: str, platform: str) -> list[str]:
    words = _slug_words(topic, 5)
    tags = [f"#{w}" for w in words]
    tags.extend(["#AMICOR", "#NovaCreative"])
    if platform and platform != "generic":
        tags.append("#" + re.sub(r"[^A-Za-z0-9]", "", platform))
    # de-dupe preserve order
    seen = set()
    out = []
    for tag in tags:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    return out[:12]


def generate_content_pack(
    *,
    topic: str,
    audience: str,
    objective: str,
    tone: str,
    platform: str,
    cta: str,
    duration_target: int | None = None,
    brand_name: str = "AMICOR",
    brand_tagline: str = "",
) -> dict[str, Any]:
    topic = str(topic or "").strip()
    audience = str(audience or "general audience").strip()
    objective = str(objective or "awareness").strip()
    tone = str(tone or "clear and professional").strip()
    platform = str(platform or "generic").strip()
    cta = str(cta or "Learn more with AMICOR Nova.").strip()
    duration = int(duration_target or 30)
    if duration not in DURATIONS:
        duration = 30

    hook = f"What if {topic} could be simpler for {audience}?"
    title = f"{topic.strip().title()}: a {duration}s {platform} cut"
    short_script = (
        f"Hook: {hook}\n"
        f"Point: {brand_name} helps {audience} with {topic}.\n"
        f"Proof angle: practical, owner-controlled AI assistance.\n"
        f"CTA: {cta}"
    )
    long_caption = (
        f"{hook}\n\n"
        f"{brand_name} is building tools so {audience} can move faster on {topic}. "
        f"Tone: {tone}. Objective: {objective}."
        + (f" {brand_tagline}" if brand_tagline else "")
        + f"\n\n{cta}"
    )
    short_caption = f"{hook} {cta}"
    voiceover = (
        f"{hook} Here is a practical look at {topic} for {audience}. "
        f"{brand_name} keeps the owner in control. {cta}"
    )
    image_prompt = (
        f"Clean modern social creative for {platform}, topic '{topic}', audience '{audience}', "
        f"tone '{tone}', brand '{brand_name}', no logos of third parties, no deceptive claims, "
        f"high readability, marketing still."
    )
    shot_list = [
        "Cold open text card with hook",
        "Product/context visual or abstract motion",
        "Benefit callout overlay",
        "Owner/brand end card with CTA",
    ]
    return {
        "hook": hook,
        "title": title,
        "short_script": short_script,
        "long_caption": long_caption,
        "short_caption": short_caption,
        "hashtags": _hashtags(topic, platform),
        "cta": cta,
        "shot_list": shot_list,
        "image_prompt": image_prompt,
        "voiceover_script": voiceover,
        "subtitle_caption_text": voiceover,
        "duration_target": duration,
        "platform": platform,
        "status_label": "GENERATED",
        "media_generated": False,
    }


def assemble_short_video(
    *,
    topic: str,
    audience: str,
    platform: str,
    duration_target: int,
    style: str,
    tone: str,
    cta: str,
    brand_name: str = "AMICOR",
) -> dict[str, Any]:
    duration = int(duration_target)
    if duration not in DURATIONS:
        raise ValueError(f"Unsupported duration_target; allowed: {DURATIONS}")
    pack = generate_content_pack(
        topic=topic,
        audience=audience,
        objective="engagement",
        tone=tone,
        platform=platform,
        cta=cta,
        duration_target=duration,
        brand_name=brand_name,
    )
    # Scene split by duration.
    if duration == 15:
        weights = [3.0, 7.0, 5.0]
        headings = ["Hook", "Value", "CTA"]
    elif duration == 60:
        weights = [8.0, 14.0, 14.0, 14.0, 10.0]
        headings = ["Hook", "Problem", "Solution", "Proof", "CTA"]
    else:
        weights = [5.0, 10.0, 10.0, 5.0]
        headings = ["Hook", "Problem", "Solution", "CTA"]

    scenes = []
    for idx, (heading, secs) in enumerate(zip(headings, weights), start=1):
        scenes.append(
            {
                "index": idx,
                "heading": heading,
                "description": f"{heading} beat for {topic} aimed at {audience}. Style: {style}.",
                "visual_prompt": (
                    f"Scene {idx} ({heading}) for {platform} short video about {topic}; "
                    f"tone {tone}; style {style}; vertical-friendly composition."
                ),
                "voiceover_text": {
                    "Hook": pack["hook"],
                    "Problem": f"Many {audience} still struggle with {topic}.",
                    "Solution": f"{brand_name} outlines a clearer path on {topic}.",
                    "Proof": f"Keep controls with the owner while Nova drafts the work.",
                    "Value": f"{brand_name} helps {audience} move on {topic} without losing control.",
                    "CTA": cta,
                }.get(heading, f"{heading}: {topic}"),
                "subtitle_text": "",
                "duration_seconds": secs,
                "transition_note": "Hard cut" if idx < len(headings) else "End card hold",
                "music_mood_note": f"{tone} underscore, low vocals, platform-safe",
            }
        )
        scenes[-1]["subtitle_text"] = scenes[-1]["voiceover_text"]

    return {
        "full_script": "\n\n".join(
            f"[{s['heading']} · {s['duration_seconds']}s]\n{s['voiceover_text']}" for s in scenes
        ),
        "scenes": scenes,
        "music_mood_note": f"{tone} pacing for {platform}",
        "transition_note": "Prefer hard cuts; soft dissolve only on end card.",
        "final_cta": cta,
        "recommended_duration": duration,
        "captions": pack["short_caption"],
        "hashtags": pack["hashtags"],
        "status_label": "GENERATED",
        "media_generated": False,
        "video_provider_status": "CONFIG_REQUIRED",
    }
