"""Deterministic content generation contracts for Creative Studio V1.

Produces natural social-media copy without paste-repeating the full topic.
No live media providers; text planning / script / storyboard only.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.nova.creative_studio.models import DURATIONS

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "get",
        "gets",
        "help",
        "helps",
        "how",
        "in",
        "into",
        "is",
        "of",
        "on",
        "or",
        "our",
        "the",
        "to",
        "up",
        "with",
        "your",
        "you",
        "that",
        "this",
        "done",
        "work",
        "could",
        "can",
        "make",
        "makes",
        "using",
        "use",
        "about",
    }
)

_WEAK_HASHTAGS = frozenset(
    {
        "how",
        "helps",
        "help",
        "small",
        "get",
        "done",
        "with",
        "and",
        "the",
        "for",
        "from",
        "that",
        "this",
        "your",
        "you",
        "work",
        "time",
        "save",
        "business",
        "owners",
        "owner",
    }
)

_SHORT_FORM = frozenset({"TikTok", "Instagram", "YouTube Shorts", "Facebook"})
_PRO_FORM = frozenset({"LinkedIn", "YouTube"})

_BRAND_TOKENS = (
    ("amicor nova", "AMICOR Nova"),
    ("amicor", "AMICOR"),
    ("nova", "Nova"),
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+", str(text or ""))


def _preserve_brands(text: str) -> str:
    """Preserve AMICOR / Nova / AI capitalization without awkward .title()."""
    out = str(text or "").strip()
    if not out:
        return out
    # Normalize AI as a standalone word.
    out = re.sub(r"\bAi\b", "AI", out)
    out = re.sub(r"\bai\b", "AI", out)
    out = re.sub(r"\bA\.I\.\b", "AI", out)
    # Brand phrases (longest first).
    for raw, fixed in _BRAND_TOKENS:
        out = re.sub(re.escape(raw), fixed, out, flags=re.IGNORECASE)
    return out


def _audience_phrase(audience: str) -> str:
    aud = str(audience or "").strip()
    if not aud:
        return "your team"
    low = aud.lower()
    if low.startswith(("small business", "business owner", "operator", "founder")):
        return "your small business" if "business" in low else f"your {low}"
    if low.endswith("s"):
        return low
    return f"{low}s" if " " not in low else low


def _benefit_seed(topic: str) -> str:
    """Pull a short benefit phrase from a long topic without pasting the whole sentence."""
    topic = str(topic or "").strip()
    low = topic.lower()
    # Common "How X helps Y do Z" shape.
    m = re.search(
        r"helps?\s+.+?\s+(save time|get work done|automate|stay in control|move faster|[^.?!]+)",
        low,
        re.I,
    )
    if "save time" in low and ("work" in low or "ai" in low):
        return "handle busywork and save time"
    if "automate" in low:
        return "automate repetitive work"
    if "inventory" in low:
        return "keep inventory reconciled"
    if m:
        frag = m.group(1).strip()
        frag = re.sub(r"\s+with\s+ai\b", "", frag, flags=re.I).strip()
        if frag and frag not in {"with", "ai"}:
            return frag
    # Meaningful content words only.
    words = [w for w in _tokens(topic) if w.lower() not in _STOPWORDS and len(w) > 2]
    if not words:
        return "get more done with less friction"
    # Prefer later benefit-ish words.
    pick = words[-3:] if len(words) >= 3 else words
    return " ".join(pick).lower()


def _subject_brand(topic: str, brand_name: str) -> str:
    low = topic.lower()
    if "amicor nova" in low:
        return "AMICOR Nova"
    if "amicor" in low:
        return "AMICOR"
    if "nova" in low and brand_name:
        return _preserve_brands(brand_name)
    return _preserve_brands(brand_name) or "AMICOR Nova"


def _is_short_form(platform: str) -> bool:
    return platform in _SHORT_FORM or platform in {"X"}


def _is_pro_form(platform: str) -> bool:
    return platform in _PRO_FORM


def _natural_hook(*, topic: str, audience: str, platform: str, brand_name: str) -> str:
    aud = _audience_phrase(audience)
    benefit = _benefit_seed(topic)
    brand = _subject_brand(topic, brand_name)
    if _is_short_form(platform):
        return _preserve_brands(
            f"What if {aud} had an AI assistant that could help {benefit}?"
        )
    if _is_pro_form(platform):
        return _preserve_brands(
            f"{brand} helps {audience or 'operators'} {benefit} — without giving up control."
        )
    return _preserve_brands(f"Ready for {aud} to {benefit} with {brand}?")


def _natural_title(*, topic: str, audience: str, platform: str, brand_name: str, duration: int) -> str:
    brand = _subject_brand(topic, brand_name)
    benefit = _benefit_seed(topic)
    if "small business" in (audience or "").lower() or "small business" in topic.lower():
        core = f"Meet {brand}: AI Help for Small Business"
    elif _is_pro_form(platform):
        core = f"{brand}: Practical AI for {audience or 'operators'}"
    else:
        core = f"{brand} — AI that helps you {benefit}"
    # Duration is metadata for planning; keep titles clean for social use.
    _ = duration
    return _preserve_brands(core)


def _hashtags(topic: str, platform: str, brand_name: str) -> list[str]:
    tags: list[str] = []
    brand = _subject_brand(topic, brand_name)
    if "AMICOR" in brand.upper():
        tags.append("#AMICORNova" if "Nova" in brand else "#AMICOR")
    else:
        tags.append("#" + re.sub(r"[^A-Za-z0-9]", "", brand)[:24])

    low = topic.lower()
    if "small business" in low or "small business" in (platform or "").lower():
        tags.extend(["#SmallBusinessAI", "#SmallBusinessTools", "#AIForBusiness"])
    if "ai" in low or "nova" in low:
        tags.extend(["#AIAutomation", "#BusinessProductivity"])
    if "inventory" in low:
        tags.append("#InventoryManagement")
    if "automat" in low:
        tags.append("#WorkflowAutomation")

    # Meaningful topic tokens only (skip weak filler).
    for w in _tokens(topic):
        key = w.lower()
        if key in _WEAK_HASHTAGS or key in _STOPWORDS or len(key) < 4:
            continue
        if key in {"amicor", "nova"}:
            continue
        if key == "ai":
            tags.append("#AI")
            continue
        camel = w[:1].upper() + w[1:]
        tags.append("#" + camel)

    if platform and platform not in {"generic", "X"}:
        plat = re.sub(r"[^A-Za-z0-9]", "", platform)
        if plat:
            tags.append("#" + plat)

    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        key = tag.lower()
        if key in seen or key in {f"#{w}" for w in _WEAK_HASHTAGS}:
            continue
        seen.add(key)
        out.append(tag)
    # Guarantee a few useful defaults if topic was sparse.
    for fallback in ("#AMICORNova", "#AIForBusiness", "#BusinessProductivity"):
        if fallback.lower() not in seen and len(out) < 8:
            seen.add(fallback.lower())
            out.append(fallback)
    return out[:10]


def _short_script(
    *,
    hook: str,
    brand: str,
    audience: str,
    benefit: str,
    cta: str,
    platform: str,
    duration: int,
) -> str:
    aud = audience or "operators"
    if _is_short_form(platform) or duration <= 30:
        lines = [
            hook,
            f"Most {aud} lose hours to busywork that never ends.",
            f"{brand} helps you {benefit} while you stay in control.",
            "Drafts, planning, and next steps — without handing over the keys.",
            cta,
        ]
    else:
        lines = [
            hook,
            f"Teams like {aud} still spend too much energy on repeatable tasks.",
            f"{brand} is built to help you {benefit} with owner-approved workflows.",
            "You review what matters. Nova prepares the rest.",
            cta,
        ]
    return "\n".join(_preserve_brands(line) for line in lines)


def _voiceover_for_duration(
    *,
    hook: str,
    brand: str,
    benefit: str,
    cta: str,
    duration: int,
    audience: str,
) -> str:
    """Spoken copy sized roughly for the target length (no topic dump)."""
    aud = _audience_phrase(audience)
    if duration <= 15:
        text = f"{hook} {brand} helps {aud} {benefit}. {cta}"
    elif duration >= 60:
        text = (
            f"{hook} "
            f"Too much of the day disappears into busywork. "
            f"{brand} helps {aud} {benefit}, with clear drafts you can review. "
            f"Keep ownership. Move faster. {cta}"
        )
    else:
        text = (
            f"{hook} "
            f"{brand} helps {aud} {benefit} without giving up control. "
            f"{cta}"
        )
    return _preserve_brands(text)


def _word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z0-9']+", text or ""))


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
    cta = _preserve_brands(str(cta or "Learn more with AMICOR Nova.").strip())
    duration = int(duration_target or 30)
    if duration not in DURATIONS:
        duration = 30

    brand = _subject_brand(topic, brand_name)
    benefit = _benefit_seed(topic)
    hook = _natural_hook(topic=topic, audience=audience, platform=platform, brand_name=brand_name)
    title = _natural_title(
        topic=topic, audience=audience, platform=platform, brand_name=brand_name, duration=duration
    )
    short_script = _short_script(
        hook=hook,
        brand=brand,
        audience=audience,
        benefit=benefit,
        cta=cta,
        platform=platform,
        duration=duration,
    )
    tagline_bit = f" {brand_tagline.strip()}" if brand_tagline else ""
    if _is_pro_form(platform):
        long_caption = _preserve_brands(
            f"{hook}\n\n"
            f"{brand} supports {audience} with practical AI assistance focused on {benefit}. "
            f"Stay owner-controlled while you move on {objective}.{tagline_bit}\n\n{cta}"
        )
    else:
        long_caption = _preserve_brands(
            f"{hook}\n\n"
            f"{brand} helps {audience} {benefit} — drafts and planning help without noisy hype."
            f"{tagline_bit}\n\n{cta}"
        )
    short_caption = _preserve_brands(f"{brand}: AI help to {benefit}. {cta}")
    voiceover = _voiceover_for_duration(
        hook=hook,
        brand=brand,
        benefit=benefit,
        cta=cta,
        duration=duration,
        audience=audience,
    )
    # Subtitles track spoken script cleanly — no labels/metadata.
    subtitle = voiceover
    image_prompt = (
        f"Clean modern social creative for {platform}, brand '{brand}', "
        f"audience '{audience}', tone '{tone}', benefit '{benefit}', "
        f"no third-party logos, no deceptive claims, high readability, marketing still."
    )
    shot_list = [
        "Cold open: face or bold text with the spoken hook",
        "Problem beat: busywork / friction visual",
        "Benefit beat: simple product or workflow visual",
        "End card: brand mark + clear CTA",
    ]
    return {
        "hook": hook,
        "title": title,
        "short_script": short_script,
        "long_caption": long_caption,
        "short_caption": short_caption,
        "hashtags": _hashtags(topic, platform, brand_name),
        "cta": cta,
        "shot_list": shot_list,
        "image_prompt": image_prompt,
        "voiceover_script": voiceover,
        "subtitle_caption_text": subtitle,
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
    brand = _subject_brand(topic, brand_name)
    benefit = _benefit_seed(topic)
    aud = audience or "operators"
    style = str(style or "modern").strip()
    tone = str(tone or "clear").strip()
    cta = _preserve_brands(str(cta or pack["cta"]).strip())

    if duration == 15:
        weights = [3.0, 7.0, 5.0]
        headings = ["Hook", "Value", "CTA"]
    elif duration == 60:
        weights = [8.0, 14.0, 14.0, 14.0, 10.0]
        headings = ["Hook", "Problem", "Solution", "Proof", "CTA"]
    else:
        weights = [5.0, 10.0, 10.0, 5.0]
        headings = ["Hook", "Problem", "Solution", "CTA"]

    vo_by_heading = {
        "Hook": pack["hook"],
        "Problem": f"Busywork piles up fast for {aud} — and it steals focus from real work.",
        "Solution": f"{brand} helps you {benefit} with drafts you can review first.",
        "Proof": "Owner controls stay with you. Nova prepares the next step.",
        "Value": f"{brand} helps you {benefit} without handing over the keys.",
        "CTA": cta,
    }
    desc_by_heading = {
        "Hook": f"Open on a tight talking-head or bold on-screen text delivering the hook. Style: {style}.",
        "Problem": f"Show cluttered inbox / task pile / clock pressure for {aud}. Tone: {tone}.",
        "Solution": f"Cut to a clean product/workflow moment that shows {brand} assisting — not replacing — the owner.",
        "Proof": "Quick overlay: owner review checkmark, then calm desk or dashboard shot.",
        "Value": f"Show a clear before/after energy shift without deceptive claims — lighter workload vibe.",
        "CTA": f"End card with {brand} wordmark and spoken CTA on screen.",
    }
    visual_by_heading = {
        "Hook": f"Vertical {platform} cold open, readable hook text, {tone} lighting, no logos of other brands.",
        "Problem": f"Vertical scene of everyday busywork friction for {aud}; naturalistic; {style}.",
        "Solution": f"Vertical demo-style shot implying AI assist for {benefit}; clean UI blur OK; brand-safe.",
        "Proof": "Vertical B-roll of owner reviewing a draft on laptop/phone; calm confidence.",
        "Value": f"Vertical lifestyle/ops shot showing regained focus after {benefit}.",
        "CTA": f"Vertical end card, {brand}, high-contrast CTA text.",
    }

    scenes = []
    for idx, (heading, secs) in enumerate(zip(headings, weights), start=1):
        vo = _preserve_brands(vo_by_heading.get(heading, cta))
        scenes.append(
            {
                "index": idx,
                "heading": heading,
                "description": _preserve_brands(desc_by_heading.get(heading, f"{heading} beat.")),
                "visual_prompt": _preserve_brands(visual_by_heading.get(heading, f"Scene {idx} for {platform}.")),
                "voiceover_text": vo,
                "subtitle_text": vo,
                "duration_seconds": secs,
                "transition_note": "Hard cut" if idx < len(headings) else "End card hold",
                "music_mood_note": f"{tone} underscore, low vocals, platform-safe",
            }
        )

    return {
        "full_script": "\n\n".join(
            f"{s['voiceover_text']}" for s in scenes
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
