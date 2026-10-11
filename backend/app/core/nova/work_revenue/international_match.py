"""Worldwide remote and B2B constraints for Nova Work & Revenue.

Tested languages are the Workspace languages that already have acceptance
coverage: English, Somali, Arabic, French, and Spanish. Matching them means
AI-assisted text. It never means native fluency.

Residency, citizenship, and permit or visa requirements match the country or
region the listing names. A populated profile field for a different place does
not qualify. Missing or unreadable eligibility fails closed.
"""

from __future__ import annotations

import re
from typing import Any

# Shown on tested-language matches. This is not a native-speaker claim.
AI_ASSISTED_TRANSLATION_LABEL = "AI-assisted translation"

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
    r"\b(?:\w+\s+){0,3}visas?\s+(?:is\s+|are\s+)?(?:required|mandatory)\b|"
    r"\bmust\s+(?:hold|have|possess)\s+(?:a\s+|an\s+)?(?:valid\s+|current\s+)?"
    r"(?:\w+\s+){0,4}visas?\b|"
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


# A country fact satisfies that country. It also satisfies a region it belongs
# to. A region fact does not satisfy a single country inside the region.
_MENA_COUNTRIES = frozenset({
    "AE", "SA", "QA", "KW", "BH", "OM",
    "EG", "JO", "LB", "IQ", "YE", "SY",
    "MA", "DZ", "TN", "LY", "PS",
})
_EU_COUNTRIES = frozenset({
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
    "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
    "SI", "ES", "SE",
})
_REGION_MEMBERS = {
    "MENA": _MENA_COUNTRIES,
    "EU": _EU_COUNTRIES,
}

# Longer aliases are preferred when spans overlap.
_PLACE_ALIASES: tuple[tuple[str, str], ...] = (
    ("MENA", r"middle east and north africa|middle east|\bmena\b"),
    ("EU", r"european union|\beu\b|european"),
    ("AE", r"united arab emirates|u\.a\.e\.?|abu dhabi|dubai|emirati|\buae\b"),
    ("GB", r"united kingdom|great britain|northern ireland|u\.k\.?|britain|england|scotland|wales|london|british|\buk\b"),
    ("US", r"united states of america|united states|u\.s\.a\.?|u\.s\.?|american|\busa\b|\bus\b"),
    ("KR", r"south korea|republic of korea|seoul|korean"),
    ("SA", r"saudi arabia|riyadh|saudi"),
    ("CA", r"canada|canadian|toronto"),
    ("DE", r"germany|deutschland|german"),
    ("FR", r"france|french"),
    ("IN", r"india|chennai|indian"),
    ("CN", r"china|beijing|chinese"),
    ("JP", r"japan|tokyo|japanese"),
    ("AU", r"australia|sydney|australian"),
    ("BR", r"brazil|brazilian"),
    ("PH", r"philippines|philippine|filipino"),
    ("NG", r"nigeria|nigerian"),
    ("SG", r"singapore|singaporean"),
    ("PK", r"pakistan|pakistani"),
    ("BD", r"bangladesh|bangladeshi"),
    ("VN", r"vietnam|vietnamese"),
    ("ID", r"indonesia|indonesian"),
    ("PL", r"poland|polish"),
    ("UA", r"ukraine|ukrainian"),
    ("EG", r"egypt|egyptian"),
    ("TW", r"taiwan|taiwanese"),
    ("ES", r"spain|spanish"),
    ("IT", r"italy|italian"),
    ("PT", r"portugal|portuguese"),
    ("NL", r"netherlands|dutch"),
    ("IE", r"ireland|irish"),
    ("QA", r"qatar|qatari"),
    ("KW", r"kuwait|kuwaiti"),
    ("BH", r"bahrain|bahraini"),
    ("OM", r"oman|omani"),
    ("JO", r"jordan|jordanian"),
    ("LB", r"lebanon|lebanese"),
    ("MA", r"morocco|moroccan"),
    ("MX", r"mexico|mexican"),
)

_PLACE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (code, re.compile(rf"\b(?:{pattern})\b", re.I))
    for code, pattern in _PLACE_ALIASES
)

_CLIENT_LOCATION_PREFIX = re.compile(
    r"\b(?:compan(?:y|ies)|clients?|customers?|employers?|firms?|"
    r"organi[sz]ations?|headquarters|\bhq\b)\b"
    r"(?:\s+[a-z]+){0,6}?\s+"
    r"(?:based|located|headquartered|residing|in|from)\s+"
    r"(?:(?:in|from|the|a|an)\s+)*$",
    re.I,
)
_CLIENT_ADJECTIVE_SUFFIX = re.compile(
    r"^\s+(?:compan(?:y|ies)|clients?|customers?|employers?|firms?)\b",
    re.I,
)
_RESIDENCY_TOPIC = re.compile(
    r"\b(?:"
    r"must\s+(?:reside|live|be\s+based|be\s+located|be\s+resident)\b|"
    r"residents?\s+only|"
    r"only\s+(?:candidates|applicants)\s+(?:in|from|within)\b|"
    r"residenc(?:y|e)\b(?!\s+(?:permits?|visas?)\b)|"
    r"must\s+be\s+(?:a\s+|an\s+)?resident\b|"
    r"(?:based|located|residing|living)\s+in\b|"
    r"(?:mena|middle\s+east)\s+residency"
    r")\b",
    re.I,
)
_EXPLICIT_RESIDENCY = re.compile(
    r"\b(?:"
    r"must\s+(?:reside|live|be\s+based|be\s+located|be\s+resident)\b|"
    r"residents?\s+only|"
    r"only\s+(?:candidates|applicants)\s+(?:in|from|within)\b|"
    r"residenc(?:y|e)\s+(?:is\s+|are\s+)?(?:required|mandatory)\b|"
    r"must\s+be\s+(?:a\s+|an\s+)?resident\b|"
    r"(?:mena|middle\s+east)\s+residency"
    r")\b",
    re.I,
)
_PERMIT_KINDS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("visa", re.compile(r"\bvisas?\b", re.I)),
    ("residence", re.compile(r"\b(?:residence|residency)\s+permits?\b", re.I)),
    ("business", re.compile(r"\b(?:business|operating|government)\s+permits?\b", re.I)),
    (
        "work",
        re.compile(
            r"\b(?:work\s+permits?|work\s+authorization|right\s+to\s+work|authorized\s+to\s+work)\b",
            re.I,
        ),
    ),
)
_RESIDENCY_FACT_KEYS = (
    "residency",
    "residencies",
    "residence",
    "residences",
    "country_of_residence",
)
_CITIZENSHIP_FACT_KEYS = ("citizenship", "citizenships")
_PERMIT_FACT_KEYS: tuple[tuple[str, str | None], ...] = (
    ("work_permits", "work"),
    ("work_permit", "work"),
    ("work_authorizations", "work_authorization"),
    ("work_authorization", "work_authorization"),
    ("visas", "visa"),
    ("visa", "visa"),
    ("permits", None),
    ("permit", None),
    ("authorizations", None),
)


def is_client_location_span(text: str, start: int, end: int) -> bool:
    """True when a place names the client or company, not the worker."""
    prefix = text[max(0, start - 80):start]
    suffix = text[end:end + 32]
    if _CLIENT_LOCATION_PREFIX.search(prefix):
        return True
    return bool(_CLIENT_ADJECTIVE_SUFFIX.match(suffix))


def _places_in(text: str, *, drop_client: bool) -> list[str]:
    spans: list[tuple[int, int, str]] = []
    for code, pattern in _PLACE_PATTERNS:
        for match in pattern.finditer(text or ""):
            if drop_client and is_client_location_span(text, match.start(), match.end()):
                continue
            spans.append((match.start(), match.end(), code))
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    found: list[str] = []
    occupied_end = -1
    for start, end, code in spans:
        if start < occupied_end:
            continue
        occupied_end = end
        if code not in found:
            found.append(code)
    return found


def _place_groups(places: list[str], sentence: str) -> list[frozenset[str]]:
    if not places:
        return [frozenset()]
    if re.search(r"\bor\b|/", sentence, re.I) or not re.search(r"\band\b", sentence, re.I):
        return [frozenset(places)]
    if len(places) > 1:
        return [frozenset([place]) for place in places]
    return [frozenset(places)]


def _permit_kind(sentence: str) -> str | None:
    for kind, pattern in _PERMIT_KINDS:
        if pattern.search(sentence):
            return kind
    return None


def _load_facts(facts: Any | None) -> dict[str, Any]:
    if facts is not None:
        return dict(facts)
    from app.core.nova.work_revenue.verified_profile import VERIFIED_FACTS

    return VERIFIED_FACTS


def _fact_values(raw: Any) -> list[Any]:
    if raw is None or isinstance(raw, bool):
        return []
    if isinstance(raw, (list, tuple, set)):
        values: list[Any] = []
        for item in raw:
            values.extend(_fact_values(item))
        return values
    if isinstance(raw, (int, float)):
        return []
    return [raw]


def _records_from_value(raw: Any, default_kind: str | None) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for value in _fact_values(raw):
        kind = default_kind
        place_text = value
        if isinstance(value, dict):
            place_text = value.get("country") or value.get("region") or value.get("place") or ""
            named = str(value.get("kind") or value.get("type") or "").strip().lower().replace("-", "_")
            if named in {"work", "work_permit"}:
                kind = "work"
            elif named in {"work_authorization", "authorization", "right_to_work"}:
                kind = "work_authorization"
            elif named in {"visa", "visas"}:
                kind = "visa"
            elif named in {"residence", "residence_permit", "residency_permit"}:
                kind = "residence"
            elif named in {"business", "business_permit", "operating"}:
                kind = "business"
            elif named in {"residency", "residence_country", "country_of_residence"}:
                kind = "residency"
            elif named in {"citizenship", "citizen"}:
                kind = "citizenship"
            elif named:
                kind = None
        if not kind or not isinstance(place_text, str):
            continue
        for code in _places_in(place_text, drop_client=False):
            records.append((code, kind))
    return records


def _verified_records(facts: dict[str, Any], family: str) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    if family == "residency":
        keys: tuple[tuple[str, str | None], ...] = tuple((key, "residency") for key in _RESIDENCY_FACT_KEYS)
    elif family == "citizenship":
        keys = tuple((key, "citizenship") for key in _CITIZENSHIP_FACT_KEYS)
    else:
        keys = _PERMIT_FACT_KEYS
    for key, kind in keys:
        if key in facts:
            records.extend(_records_from_value(facts.get(key), kind))
    return records


def _place_covers(verified_place: str, required_place: str) -> bool:
    if verified_place == required_place:
        return True
    members = _REGION_MEMBERS.get(required_place)
    return bool(members and verified_place in members)


def _kind_covers(verified_kind: str, required_kind: str) -> bool:
    if verified_kind == required_kind:
        return True
    work_kinds = {"work", "work_authorization"}
    return verified_kind in work_kinds and required_kind in work_kinds


def _need_met(alternatives: frozenset[tuple[str, str]], verified: list[tuple[str, str]]) -> bool:
    if not alternatives:
        return False
    return any(
        _kind_covers(verified_kind, required_kind) and _place_covers(verified_place, required_place)
        for verified_place, verified_kind in verified
        for required_place, required_kind in alternatives
    )


def _eligibility_sentence_optional(sentence: str) -> bool:
    """Preference is not a requirement unless the same sentence is mandatory."""
    if re.search(r"\b(?:must|required|mandatory)\b", sentence, re.I):
        return False
    return bool(re.search(
        r"\b(?:prefer(?:red|ence)?|optional|nice to have|a plus)\b",
        sentence,
        re.I,
    ))


def _residency_needs(text: str) -> list[frozenset[tuple[str, str]] | None]:
    """Place sets the worker must satisfy. None means the place cannot be read."""
    needs: list[frozenset[tuple[str, str]] | None] = []
    for sentence in re.split(r"[.;\n]", text or ""):
        if not sentence.strip() or _eligibility_sentence_optional(sentence):
            continue
        if not _claim_stands(_RESIDENCY_TOPIC, sentence):
            continue
        places = _places_in(sentence, drop_client=True)
        if not places:
            if _EXPLICIT_RESIDENCY.search(sentence):
                needs.append(None)
            continue
        for group in _place_groups(places, sentence):
            needs.append(frozenset((place, "residency") for place in group) if group else None)
    return needs


def _citizenship_needs(text: str) -> list[frozenset[tuple[str, str]] | None]:
    needs: list[frozenset[tuple[str, str]] | None] = []
    for sentence in re.split(r"[.;\n]", text or ""):
        if not sentence.strip() or _eligibility_sentence_optional(sentence):
            continue
        if not _claim_stands(_CITIZENSHIP, sentence):
            continue
        places = _places_in(sentence, drop_client=True)
        if not places:
            needs.append(None)
            continue
        for group in _place_groups(places, sentence):
            needs.append(frozenset((place, "citizenship") for place in group) if group else None)
    return needs


def _permit_needs(text: str) -> list[frozenset[tuple[str, str]] | None]:
    needs: list[frozenset[tuple[str, str]] | None] = []
    for sentence in re.split(r"[.;\n]", text or ""):
        if not sentence.strip() or _eligibility_sentence_optional(sentence):
            continue
        if not _claim_stands(_PERMIT, sentence):
            continue
        kind = _permit_kind(sentence)
        places = _places_in(sentence, drop_client=True)
        if not kind or not places:
            needs.append(None)
            continue
        for group in _place_groups(places, sentence):
            if not group:
                needs.append(None)
                continue
            needs.append(frozenset((place, kind) for place in group))
    return needs


def _dimension(
    needs: list[frozenset[tuple[str, str]] | None],
    verified: list[tuple[str, str]],
    *,
    plain_place: bool,
) -> dict[str, Any]:
    if not needs:
        return {"required": False, "met": True, "unverifiable": False, "alternatives": []}
    alternatives: list[list[str]] = []
    unverifiable = False
    met = True
    for need in needs:
        if not need:
            unverifiable = True
            met = False
            alternatives.append([])
            continue
        rendered: list[str] = []
        for place, kind in sorted(need):
            rendered.append(place if plain_place else f"{place}:{kind}")
        alternatives.append(rendered)
        if not _need_met(need, verified):
            met = False
    return {
        "required": True,
        "met": met,
        "unverifiable": unverifiable,
        "alternatives": alternatives,
    }


def assess_country_eligibility(text: str, facts: Any | None = None) -> dict[str, Any]:
    """Country and region checks for residency, citizenship, and permits.

    A truthy profile field is not enough. The verified place has to cover the
    required country or region, and an unreadable requirement fails closed.
    """
    loaded = _load_facts(facts)
    return {
        "residency": _dimension(
            _residency_needs(text),
            _verified_records(loaded, "residency"),
            plain_place=True,
        ),
        "citizenship": _dimension(
            _citizenship_needs(text),
            _verified_records(loaded, "citizenship"),
            plain_place=True,
        ),
        "permit": _dimension(
            _permit_needs(text),
            _verified_records(loaded, "permit"),
            plain_place=False,
        ),
    }


def verified_residency_meets_listing(job: dict[str, Any], facts: Any | None = None) -> bool:
    """True when every stated worker-location requirement is verified."""
    residency = assess_country_eligibility(_listing_text(job), facts)["residency"]
    return bool(residency["required"] and residency["met"] and not residency["unverifiable"])


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


_PLACE_DISPLAY = {
    "MENA": "MENA",
    "EU": "European Union",
    "AE": "United Arab Emirates",
    "GB": "United Kingdom",
    "US": "United States",
    "KR": "South Korea",
    "SA": "Saudi Arabia",
    "CA": "Canada",
    "DE": "Germany",
    "FR": "France",
    "IN": "India",
    "CN": "China",
    "JP": "Japan",
    "AU": "Australia",
    "BR": "Brazil",
    "PH": "Philippines",
    "NG": "Nigeria",
    "SG": "Singapore",
    "PK": "Pakistan",
    "BD": "Bangladesh",
    "VN": "Vietnam",
    "ID": "Indonesia",
    "PL": "Poland",
    "UA": "Ukraine",
    "EG": "Egypt",
    "TW": "Taiwan",
    "ES": "Spain",
    "IT": "Italy",
    "PT": "Portugal",
    "NL": "Netherlands",
    "IE": "Ireland",
    "QA": "Qatar",
    "KW": "Kuwait",
    "BH": "Bahrain",
    "OM": "Oman",
    "JO": "Jordan",
    "LB": "Lebanon",
    "MA": "Morocco",
    "MX": "Mexico",
}
_LANGUAGE_DISPLAY = {
    "en": "English",
    "so": "Somali",
    "ar": "Arabic",
    "fr": "French",
    "es": "Spanish",
    "pt": "Portuguese",
    "zh": "Chinese",
    "de": "German",
    "hi": "Hindi",
    "ja": "Japanese",
    "it": "Italian",
    "ru": "Russian",
    "el": "Greek",
    "ko": "Korean",
    "tr": "Turkish",
}
_PERMIT_DISPLAY = {
    "work": "work permit",
    "work_authorization": "work authorization",
    "visa": "visa",
    "residence": "residence permit",
    "business": "business permit",
}
_BLOCKER_KIND = {
    "residency_required": "residency",
    "citizenship_required": "citizenship",
    "permit_required": "permit",
    "untested_language_required": "language",
    "native_fluency_required": "native_fluency",
}
_NATIVE_EXPLANATION = (
    "Mandatory native fluency. AI-assisted translation does not satisfy native fluency, "
    "and no fluency is claimed."
)


def _place_name(code: str) -> str:
    return _PLACE_DISPLAY.get(code, code)


def _join_or(parts: list[str]) -> str:
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]} or {parts[1]}"
    return ", ".join(parts[:-1]) + f", or {parts[-1]}"


def _rule(
    kind: str,
    *,
    mandatory: bool,
    decision: str,
    subjects: list[str],
    text: str,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "mandatory": mandatory,
        "decision": decision,
        "subjects": subjects,
        "text": text,
    }


def _unreadable_rule(kind: str, heading: str) -> dict[str, Any]:
    if kind == "permit":
        detail = "the required country or permit type could not be read"
    else:
        detail = "the required country or region could not be read"
    return _rule(
        kind,
        mandatory=True,
        decision="fail_closed",
        subjects=[],
        text=f"Mandatory {heading}: {detail}, so this fails closed.",
    )


def _mandatory_place_rules(text: str, facts: Any | None) -> list[dict[str, Any]]:
    loaded = _load_facts(facts)
    rules: list[dict[str, Any]] = []
    families = (
        ("residency", _residency_needs, "residency", "residency"),
        ("citizenship", _citizenship_needs, "citizenship", "citizenship"),
        ("permit", _permit_needs, "permit", "permit"),
    )
    for kind, needs_fn, verified_family, heading in families:
        verified = _verified_records(loaded, verified_family)
        for need in needs_fn(text):
            if not need:
                rules.append(_unreadable_rule(kind, heading))
                continue
            kinds = {item_kind for _, item_kind in need}
            if kind == "permit" and len(kinds) == 1:
                heading_text = _PERMIT_DISPLAY.get(next(iter(kinds)), "permit")
                subjects = [_place_name(place) for place, _item_kind in sorted(need)]
            elif kind == "permit":
                heading_text = "permit"
                subjects = [
                    f"{_place_name(place)} {_PERMIT_DISPLAY.get(item_kind, item_kind)}"
                    for place, item_kind in sorted(need)
                ]
            else:
                heading_text = heading
                subjects = [_place_name(place) for place, _item_kind in sorted(need)]
            shown = _join_or(subjects)
            if _need_met(need, verified):
                rules.append(_rule(
                    kind,
                    mandatory=True,
                    decision="met",
                    subjects=subjects,
                    text=(
                        f"Mandatory {heading_text}: {shown}. "
                        "The verified profile meets this requirement."
                    ),
                ))
            else:
                rules.append(_rule(
                    kind,
                    mandatory=True,
                    decision="fail_closed",
                    subjects=subjects,
                    text=(
                        f"Mandatory {heading_text}: {shown}. "
                        "The verified profile does not meet this requirement, so this fails closed."
                    ),
                ))
    return rules


def _preferred_language_codes(sentence: str) -> list[str]:
    """Languages named as a preference, including 'Spanish preferred'."""
    found = list(_codes_in(sentence))
    for match in _LANGUAGE_TOKEN.finditer(sentence or ""):
        code = _language_code(match.group(1))
        if not code or code in found:
            continue
        prefix = sentence[max(0, match.start() - 24):match.start()]
        suffix = sentence[match.end():match.end() + 24]
        if re.search(r"\b(?:preferred|optional)\s+$", prefix, re.I) or re.search(
            r"^\s+(?:preferred|optional)\b",
            suffix,
            re.I,
        ):
            found.append(code)
    return found


def _language_rules(text: str, blockers: list[str]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    if "native_fluency_required" in blockers:
        rules.append(_rule(
            "native_fluency",
            mandatory=True,
            decision="fail_closed",
            subjects=[],
            text=_NATIVE_EXPLANATION,
        ))
    else:
        for group in mandatory_language_groups(text):
            ordered = _codes_in_order(group)
            names = [_LANGUAGE_DISPLAY.get(code, code) for code in ordered]
            shown = _join_or(names)
            tested = [code for code in ordered if code in TESTED_WORK_LANGUAGES]
            if not tested:
                rules.append(_rule(
                    "language",
                    mandatory=True,
                    decision="fail_closed",
                    subjects=names,
                    text=(
                        f"Mandatory language: {shown}. This language is not tested, "
                        "so this fails closed. No fluency is claimed."
                    ),
                ))
                continue
            tested_names = _join_or([_LANGUAGE_DISPLAY.get(code, code) for code in tested])
            if set(tested) == set(group):
                sentence = (
                    f"Mandatory language: {shown}. Labeled {AI_ASSISTED_TRANSLATION_LABEL}. "
                    "This is not native fluency."
                )
            else:
                verb = "are" if len(tested) > 1 else "is"
                sentence = (
                    f"Mandatory language: {shown}. {tested_names} {verb} covered as "
                    f"{AI_ASSISTED_TRANSLATION_LABEL}. This is not native fluency."
                )
            rules.append(_rule(
                "language",
                mandatory=True,
                decision="met",
                subjects=names,
                text=sentence,
            ))
    for sentence in re.split(r"[.;\n]", text or ""):
        if not sentence.strip() or not _sentence_optional(sentence):
            continue
        codes = _preferred_language_codes(sentence)
        if not codes:
            continue
        names = [_LANGUAGE_DISPLAY.get(code, code) for code in codes]
        rules.append(_rule(
            "language",
            mandatory=False,
            decision="preferred",
            subjects=names,
            text=f"Preferred language: {_join_or(names)}. A preference is not a blocker.",
        ))
    return rules


def _preferred_country_rules(text: str) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for sentence in re.split(r"[.;\n]", text or ""):
        if not sentence.strip() or not _eligibility_sentence_optional(sentence):
            continue
        places = [_place_name(code) for code in _places_in(sentence, drop_client=True)]
        shown = _join_or(places) if places else "a place that was not named"
        if _RESIDENCY_TOPIC.search(sentence) or re.search(r"\blocation preference\b", sentence, re.I):
            rules.append(_rule(
                "residency",
                mandatory=False,
                decision="preferred",
                subjects=places,
                text=f"Preferred residency: {shown}. A preference is not a blocker.",
            ))
        if re.search(r"\bcitizenship\b", sentence, re.I):
            rules.append(_rule(
                "citizenship",
                mandatory=False,
                decision="preferred",
                subjects=places,
                text=f"Preferred citizenship: {shown}. A preference is not a blocker.",
            ))
        permit_kind = _permit_kind(sentence)
        if permit_kind:
            label = _PERMIT_DISPLAY.get(permit_kind, "permit")
            subjects = [f"{place} {label}" for place in places] if places else [label]
            rules.append(_rule(
                "permit",
                mandatory=False,
                decision="preferred",
                subjects=subjects,
                text=f"Preferred {label}: {shown}. A preference is not a blocker.",
            ))
    return rules


def _dedupe_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for rule in rules:
        text = str(rule.get("text") or "")
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(rule)
    return unique


def build_owner_eligibility_view(
    text: str,
    facts: Any | None,
    blockers: list[str],
) -> dict[str, Any]:
    """Owner-facing sentences for the decision international_blockers already made."""
    rules = _dedupe_rules(
        _mandatory_place_rules(text, facts)
        + _language_rules(text, blockers)
        + _preferred_country_rules(text)
    )
    decision = "fail_closed" if any(rule["decision"] == "fail_closed" for rule in rules) else "clear"
    return {
        "eligibility_rules": rules,
        "eligibility_explanations": [str(rule["text"]) for rule in rules],
        "eligibility_decision": decision,
    }


def explanation_for_blocker(rules: list[dict[str, Any]], code: str) -> str:
    kind = _BLOCKER_KIND.get(code)
    if not kind:
        return ""
    texts = [
        str(rule.get("text") or "")
        for rule in rules
        if rule.get("kind") == kind and rule.get("decision") == "fail_closed" and rule.get("mandatory")
    ]
    return " ".join(text for text in texts if text)


def attach_owner_eligibility(opportunity: dict[str, Any], qual: dict[str, Any]) -> dict[str, Any]:
    """Copy the owner-facing view onto a qualification without inventing fluency."""
    view = assess_international_match(opportunity)
    merged = dict(qual)
    merged["language_support"] = view["language_support"]
    merged["language_support_label"] = view["language_support_label"]
    merged["tested_language_codes"] = list(view["tested_language_codes"])
    merged["eligibility_explanations"] = list(view["eligibility_explanations"])
    merged["eligibility_rules"] = list(view["eligibility_rules"])
    merged["eligibility_decision"] = view["eligibility_decision"]
    merged["native_fluency_claimed"] = False
    merged["native_speaker_capability"] = False
    merged["ai_translation_is_native_fluency"] = False
    if view["eligibility_decision"] != "fail_closed":
        return merged
    merged["auto_prepare_allowed"] = False
    texts = [
        str(rule["text"])
        for rule in view["eligibility_rules"]
        if rule.get("decision") == "fail_closed"
    ]
    reasons = [str(item) for item in (merged.get("reasons") or []) if str(item) not in texts]
    merged["reasons"] = texts + reasons
    merged["reason_codes"] = list(merged["reasons"])
    if texts:
        merged["owner_review_reason"] = texts[0]
        merged["blocking_reason"] = texts[0]
    if merged.get("outcome") in {"NOVA_CAN_PERFORM", "NOVA_WITH_OWNER_REVIEW"}:
        merged["outcome"] = "NOT_SUITABLE"
        merged["lifecycle_outcome"] = "NOT_SUPPORTED"
        merged["decision"] = "NOT_SUITABLE"
    evaluations = dict(merged.get("evaluations") or {})
    if any(
        rule.get("kind") in {"residency", "citizenship", "permit"} and rule.get("decision") == "fail_closed"
        for rule in view["eligibility_rules"]
    ):
        evaluations["location_eligibility"] = "NO"
        merged["evaluations"] = evaluations
    return merged


def international_blockers(job: dict[str, Any], facts: Any | None = None) -> list[str]:
    """Hard blocks for constraints the verified profile does not meet.

    Native fluency is never treated as met. Country constraints fail closed
    unless the verified place is the required country or region.
    """
    text = _listing_text(job)
    reasons: list[str] = []
    if _claim_stands(_NATIVE_FLUENCY, text):
        reasons.append("native_fluency_required")
    eligibility = assess_country_eligibility(text, facts)
    if eligibility["residency"]["required"] and not eligibility["residency"]["met"]:
        reasons.append("residency_required")
    if eligibility["citizenship"]["required"] and not eligibility["citizenship"]["met"]:
        reasons.append("citizenship_required")
    if eligibility["permit"]["required"] and not eligibility["permit"]["met"]:
        reasons.append("permit_required")
    if untested_language_required(text):
        reasons.append("untested_language_required")
    return reasons


def assess_international_match(job: dict[str, Any], facts: Any | None = None) -> dict[str, Any]:
    """Language label for a listing. AI assistance is never called native fluency."""
    text = _listing_text(job)
    groups = mandatory_language_groups(text)
    tested = _tested_codes(groups)
    blockers = international_blockers(job, facts)
    if "native_fluency_required" in blockers:
        support = "not_native_fluency"
    elif "untested_language_required" in blockers:
        support = "untested_language"
    elif tested:
        support = "ai_assisted_translation"
    else:
        support = "not_required"
    label = AI_ASSISTED_TRANSLATION_LABEL if support == "ai_assisted_translation" else ""
    view = build_owner_eligibility_view(text, facts, blockers)
    return {
        "tested_language_codes": tested,
        "tested_languages": [
            {
                "code": code,
                "name": TESTED_WORK_LANGUAGES[code],
                "support": "ai_assisted_translation",
                "label": AI_ASSISTED_TRANSLATION_LABEL,
            }
            for code in tested
        ],
        "language_support": support,
        "language_support_label": label,
        "native_fluency_claimed": False,
        "native_speaker_capability": False,
        "ai_translation_is_native_fluency": False,
        "eligibility": assess_country_eligibility(text, facts),
        "eligibility_explanations": view["eligibility_explanations"],
        "eligibility_rules": view["eligibility_rules"],
        "eligibility_decision": view["eligibility_decision"],
        "blockers": blockers,
    }
