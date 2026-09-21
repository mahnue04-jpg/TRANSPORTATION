"""Creative Studio safety / policy screening."""

from __future__ import annotations

import re
from typing import Any

BLOCK = "BLOCK"
OWNER_REVIEW = "OWNER_REVIEW"
OK = "OK"

_BLOCK_PATTERNS = (
    (re.compile(r"\b(impersonat(?:e|ion)|pretend to be|fake (?:official|government))\b", re.I), "fraudulent_impersonation"),
    (re.compile(r"\b(deceptive endorsement|fake (?:review|testimonial)|buy fake followers)\b", re.I), "deceptive_endorsements"),
    (re.compile(r"\b(cures? cancer|guaranteed (?:cure|treatment)|miracle (?:drug|cure))\b", re.I), "false_medical_claims"),
    (re.compile(r"\b(guaranteed returns?|risk[- ]free (?:profit|investment)|get rich quick)\b", re.I), "false_financial_guarantees"),
    (re.compile(r"\b(reproduce (?:copyrighted|pirated)|download pirated|ripped movie)\b", re.I), "unlawful_copyrighted_reproduction"),
    (re.compile(r"\b(deceive viewers?|trick (?:the )?(?:audience|viewers?)|misleading edit to scam)\b", re.I), "instructions_to_deceive"),
)

_REVIEW_PATTERNS = (
    (re.compile(r"\b(vote for|political campaign|ballot|partisan)\b", re.I), "political_persuasion"),
    (re.compile(r"\b(treat(?:ment|s)?|diagnos(?:e|is)|supplement claim|clinical result)\b", re.I), "sensitive_health_claims"),
    (re.compile(r"\b(invest(?:ment)?|roi|crypto|stock tip|financial advice)\b", re.I), "financial_claims"),
    (re.compile(r"\b(testimonial|customer said|as seen on)\b", re.I), "testimonials"),
    (re.compile(r"\b(before and after|before/after|dramatic transformation)\b", re.I), "before_after_claims"),
)


def screen_creative_text(*parts: str) -> dict[str, Any]:
    blob = "\n".join(str(p or "") for p in parts)
    blockers: list[str] = []
    reviews: list[str] = []
    for pattern, code in _BLOCK_PATTERNS:
        if pattern.search(blob):
            blockers.append(code)
    for pattern, code in _REVIEW_PATTERNS:
        if pattern.search(blob):
            reviews.append(code)
    if blockers:
        return {
            "decision": BLOCK,
            "blockers": blockers,
            "owner_review_flags": reviews,
            "message": "Content blocked by Creative Studio safety policy.",
        }
    if reviews:
        return {
            "decision": OWNER_REVIEW,
            "blockers": [],
            "owner_review_flags": reviews,
            "message": "Owner review required before publishing or paid promotion.",
        }
    return {
        "decision": OK,
        "blockers": [],
        "owner_review_flags": [],
        "message": "Passed automated Creative Studio safety screen.",
    }
