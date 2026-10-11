"""Worldwide remote and B2B constraints for Nova Work & Revenue.

Tested languages are the Workspace languages that already have acceptance
coverage: English, Somali, Arabic, French, and Spanish. Matching them means
AI-assisted text. It never means native fluency.
"""

from __future__ import annotations

import re
from typing import Any

# Keep this aligned with Nova Workspace answer languages that have tests.
# Somali speech remains experimental and is not a fluency claim.
TESTED_WORK_LANGUAGES: dict[str, str] = {
    "en": "English",
    "so": "Somali",
    "ar": "Arabic",
    "fr": "French",
    "es": "Spanish",
}

_LANGUAGE_ORDER: tuple[tuple[str, str], ...] = (
    ("en", r"english"),
    ("so", r"somali|af-soomaali|af soomaali"),
    ("ar", r"arabic"),
    ("fr", r"french|fran[cç]ais"),
    ("es", r"spanish|espa[nñ]ol"),
    ("pt", r"portuguese|portugu[eê]s"),
    ("zh", r"mandarin|chinese"),
    ("de", r"german|deutsch"),
    ("hi", r"hindi"),
    ("ja", r"japanese"),
    ("it", r"italian"),
    ("ru", r"russian"),
    ("el", r"greek"),
    ("ko", r"korean"),
    ("tr", r"turkish"),
)

_LANGUAGE_NAMES = "|".join(pattern for _, pattern in _LANGUAGE_ORDER)
_LANGUAGE_TOKEN = re.compile(rf"\b({_LANGUAGE_NAMES})\b", re.I)
_LANGUAGE_BEFORE = re.compile(
    r"(?:fluent|fluency|proficient|native|speaking|speaker|written|writing|speak|write|read)\s+(?:in\s+)?(?:the\s+)?$",
    re.I,
)
_LANGUAGE_AFTER = re.compile(
    r"^(?:[- ]speaking\b|(?:\s+\w+){0,3}\s+(?:fluency|fluent|speaker|speaking|communication|emails?|writing|written|required|mandatory)\b)",
    re.I,
)
_LANGUAGE_IN = re.compile(
    r"(?:emails?|communication|correspondence|writing|support)\s+in\s+$",
    re.I,
)

_NATIVE_FLUENCY = re.compile(
    r"\b("
    r"near[- ]native|native[- ]level|native fluency|native speaker|mother tongue|first language|"
    r"native (?:english|somali|arabic|french|spanish|portuguese|mandarin|chinese|german|hindi|"
    r"japanese|italian|russian|greek|korean|turkish)|"
    r"(?:english|somali|arabic|french|spanish|portuguese|mandarin|chinese|german|hindi|"
    r"japanese|italian|russian|greek|korean|turkish) native"
    r")\b",
    re.I,
)
_RESIDENCY = re.compile(
    r"\b("
    r"must\s+(?:reside|live|be\s+based|be\s+located|be\s+resident)\b|"
    r"residents?\s+only|"
    r"only\s+(?:candidates|applicants)\s+(?:in|from|within)\b|"
    r"residency\s+(?:required|mandatory)|"
    r"must\s+be\s+(?:a\s+|an\s+)?resident\b|"
    r"(?:mena|middle\s+east)\s+residency"
    r")\b",
    re.I,
)
_CITIZENSHIP = re.compile(
    r"\b("
    r"citizenship\s+(?:required|mandatory)|"
    r"must\s+be\s+(?:a\s+|an\s+)?citizen\b|"
    r"(?:u\.?s\.?|us|american|eu|european)\s+citizenship|"
    r"citizens?\s+only"
    r")\b",
    re.I,
)
_PERMIT = re.compile(
    r"(?:"
    r"\b(?:work|residence|residency|business|operating|government)\s+permits?\b"
    r"(?:\s+\w+){0,6}\s+(?:is\s+|are\s+)?(?:required|mandatory)\b|"
    r"\bmust\s+(?:hold|have|possess)\s+(?:a\s+|an\s+)?(?:valid\s+|current\s+)?"
    r"(?:\w+\s+){0,4}permits?\b|"
    r"\bvisa\s+(?:is\s+)?(?:required|mandatory)\b|"
    r"\bmust\s+(?:hold|have|possess)\s+(?:a\s+)?(?:valid\s+)?visa\b|"
    r"\bwork\s+authorization\s+(?:is\s+)?(?:required|mandatory)\b|"
    r"\bmust\s+be\s+authorized\s+to\s+work\b|"
    r"\bright\s+to\s+work\s+(?:is\s+)?(?:required|mandatory)\b|"
    r"\bmust\s+have\s+(?:the\s+)?(?:legal\s+)?right\s+to\s+work\b"
    r")",
    re.I,
)
def _listing_text(job: dict[str, Any]) -> str:
    return " ".join(
        str(job.get(key) or "")
        for key in (
            "title",
            "opportunity_title",
            "description",
            "requirements",
            "skills",
            "skills_required",
            "credentials",
            "credentials_required",
        )
    )


def _claim_stands(pattern: re.Pattern[str], text: str) -> bool:
    """True when a requirement is stated and not negated or marked preferred."""
    for match in pattern.finditer(text or ""):
        prefix = re.split(r"[.;\n]", text[:match.start()])[-1]
        suffix = re.split(r"[.;\n]", text[match.end():])[0]
        if re.search(r"\bnot\s+(?:required|mandatory)\b", match.group(), re.I):
            continue
        if re.search(r"\b(?:no|not|without|non-|never)(?:\s+(?:a|an|any|the))?\s*$", prefix, re.I):
            continue
        if re.search(r"^\s*(?:is |are )?(?:not required|not mandatory)\b", suffix, re.I):
            continue
        if re.search(r"\b(?:must|required|mandatory|requires?)\b", match.group(), re.I) or re.search(
            r"^\s*(?:(?:is|are)\s+)?(?:required|mandatory)\b", suffix, re.I
        ):
            return True
        if re.search(r"^\s*(?:is |are )?(?:optional|preferred|a plus|nice to have)\b", suffix, re.I):
            continue
        if re.search(r"\b(?:preferred|optional|nice to have|a plus)\s*[:\-–—]?\s*$", prefix, re.I):
            continue
        return True
    return False


def _profile_meets(kind: str) -> bool:
    """Whether verified facts already satisfy a hard constraint.

    Native fluency stays unmet. AI translation must not be recorded as native.
    """
    if kind == "native_fluency":
        return False
    from app.core.nova.work_revenue.verified_profile import VERIFIED_FACTS

    if kind == "residency":
        return bool(VERIFIED_FACTS.get("residency"))
    if kind == "citizenship":
        return bool(VERIFIED_FACTS.get("citizenship"))
    if kind == "permit":
        return bool(VERIFIED_FACTS.get("work_permits"))
    return False


def _language_code(name: str) -> str | None:
    token = str(name or "").lower()
    for code, pattern in _LANGUAGE_ORDER:
        if re.fullmatch(pattern, token, re.I):
            return code
    return None


def _language_is_used(text: str, start: int, end: int) -> bool:
    prefix = text[max(0, start - 48):start]
    suffix = text[end:end + 48]
    return bool(
        _LANGUAGE_BEFORE.search(prefix)
        or _LANGUAGE_AFTER.search(suffix)
        or _LANGUAGE_IN.search(prefix)
    )


def _codes_in(text: str) -> list[str]:
    found: list[str] = []
    for match in _LANGUAGE_TOKEN.finditer(text or ""):
        if not _language_is_used(text, match.start(), match.end()):
            continue
        code = _language_code(match.group(1))
        if code and code not in found:
            found.append(code)
    return found


def _sentence_optional(sentence: str) -> bool:
    if re.search(r"\b(?:not required|not mandatory)\b", sentence, re.I):
        if not re.search(r"\bmust\b", sentence, re.I):
            return True
    if re.search(r"\b(?:must|required|mandatory)\b", sentence, re.I):
        return False
    return bool(re.search(r"\b(?:preferred|optional|nice to have|a plus)\b", sentence, re.I))


def mandatory_language_groups(text: str) -> list[set[str]]:
    """Language sets the work requires. Members of one set are alternatives."""
    groups: list[set[str]] = []
    for sentence in re.split(r"[.;\n]", text or ""):
        if not sentence.strip() or _sentence_optional(sentence):
            continue
        if not _codes_in(sentence):
            continue
        if re.search(r"\bor\b|/", sentence, re.I):
            codes = set(_codes_in(sentence))
            if codes:
                groups.append(codes)
            continue
        for code in _codes_in(sentence):
            groups.append({code})
    return groups


def _tested_codes(groups: list[set[str]]) -> list[str]:
    used: list[str] = []
    for group in groups:
        for code in _codes_in_order(group):
            if code in TESTED_WORK_LANGUAGES and code not in used:
                used.append(code)
    order = list(TESTED_WORK_LANGUAGES)
    return sorted(used, key=order.index)


def _codes_in_order(codes: set[str]) -> list[str]:
    order = [code for code, _ in _LANGUAGE_ORDER if code in codes]
    return order


def untested_language_required(text: str) -> bool:
    """True when every alternative in a mandatory group is untested."""
    for group in mandatory_language_groups(text):
        if not any(code in TESTED_WORK_LANGUAGES for code in group):
            return True
    return False


def international_blockers(job: dict[str, Any]) -> list[str]:
    """Hard blocks for constraints the verified profile does not meet."""
    text = _listing_text(job)
    reasons: list[str] = []
    if _claim_stands(_NATIVE_FLUENCY, text) and not _profile_meets("native_fluency"):
        reasons.append("native_fluency_required")
    if _claim_stands(_RESIDENCY, text) and not _profile_meets("residency"):
        reasons.append("residency_required")
    if _claim_stands(_CITIZENSHIP, text) and not _profile_meets("citizenship"):
        reasons.append("citizenship_required")
    if _claim_stands(_PERMIT, text) and not _profile_meets("permit"):
        reasons.append("permit_required")
    if untested_language_required(text):
        reasons.append("untested_language_required")
    return reasons


def assess_international_match(job: dict[str, Any]) -> dict[str, Any]:
    """Language label for a listing. AI assistance is never called native fluency."""
    text = _listing_text(job)
    groups = mandatory_language_groups(text)
    tested = _tested_codes(groups)
    blockers = international_blockers(job)
    if "native_fluency_required" in blockers:
        support = "not_native_fluency"
    elif "untested_language_required" in blockers:
        support = "untested_language"
    elif tested:
        support = "ai_assisted_translation"
    else:
        support = "not_required"
    return {
        "tested_language_codes": tested,
        "tested_languages": [
            {"code": code, "name": TESTED_WORK_LANGUAGES[code], "support": "ai_assisted_translation"}
            for code in tested
        ],
        "language_support": support,
        "native_fluency_claimed": False,
        "ai_translation_is_native_fluency": False,
        "blockers": blockers,
    }
