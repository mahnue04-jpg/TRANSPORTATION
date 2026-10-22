"""Language guards for Work & Revenue and the Operations Agent.

A rollout language can be named. It cannot become a translated proposal,
a translated legal clause, or a translated client approval.
"""

from __future__ import annotations

import re

from app.core.nova.language.catalog import APPROVAL, NOTICES, ROLLOUT, SUPPORTED, VERIFIED_SCREEN
from app.core.nova.work_revenue.international_match import (
    _preferred_language_codes,
    mandatory_language_groups,
    untested_language_required,
)

_LEGAL = re.compile(
    r"governing law|liabilit|indemnif|terms and conditions|non-disclosure|\bnda\b|"
    r"jurisdiction|warrant(?:y|ies)|force majeure",
    re.I,
)
_APPROVAL = re.compile(
    r"client approval|approved by the client|authorization to submit|owner approval|"
    r"\bi approve\b|please approve",
    re.I,
)
_PRESERVED = "Original language is preserved."


def normalize_language(code: str) -> str:
    cleaned = str(code or "").strip().lower()
    return cleaned if cleaned in SUPPORTED else ""


def detect_source_language(text: str) -> str:
    """Script of the source text. Latin text stays English rather than a guess."""
    sample = text or ""
    if re.search(r"[\u3040-\u30ff]", sample):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", sample):
        return "ko"
    if re.search(r"[\u0370-\u03ff]", sample):
        return "el"
    if re.search(r"[\u0400-\u04ff]", sample):
        return "ru"
    if re.search(r"[äöüÄÖÜß]", sample):
        return "de"
    return "en" if sample.strip() else "unspecified"


def opportunity_language_plan(text: str) -> dict:
    """What discovery may say about a listing. Untested requirements still fail closed."""
    groups = mandatory_language_groups(text or "")
    required: list[str] = []
    unverified_alternatives: list[str] = []
    for group in groups:
        tested = [code for code in group if code in VERIFIED_SCREEN]
        for code in sorted(group):
            if code not in required:
                required.append(code)
            if code in ROLLOUT and tested and code not in unverified_alternatives:
                unverified_alternatives.append(code)
    preferred: list[str] = []
    for sentence in re.split(r"[.;\n]", text or ""):
        for code in _preferred_language_codes(sentence):
            if code not in preferred and code not in required:
                preferred.append(code)
    unverified_required = [code for code in required if code in ROLLOUT and code not in unverified_alternatives]
    blocked = untested_language_required(text or "")
    return {
        "required_languages": required,
        "preferred_languages": preferred,
        "preferred_unverified": [code for code in preferred if code in ROLLOUT],
        "rollout_languages": list(ROLLOUT),
        "unverified_required": unverified_required,
        "unverified_alternatives": unverified_alternatives,
        "fail_closed": blocked,
        "translation_applied": False,
        "original_language_preserved": True,
        "business_delivery_operational": not blocked,
        "operational": not blocked,
    }


def guard_proposal(listing_text: str, draft: str, requested_language: str = "") -> dict:
    """Keep the listing text and refuse a translated client proposal."""
    source = detect_source_language(listing_text)
    requested = normalize_language(requested_language)
    unknown = bool(str(requested_language or "").strip()) and requested == ""
    if not requested:
        requested = source if source in SUPPORTED else "en"
    refused = requested in ROLLOUT or unknown
    note = (
        f" {_PRESERVED}"
        " Unsupported translation was not applied."
        " Legal terms were not translated."
        " Client approval text was not translated."
    )
    body = draft or ""
    if _PRESERVED not in body:
        body = f"{body}{note}"
    verified = requested in VERIFIED_SCREEN
    return {
        "body": body,
        "source_text": listing_text,
        "source_language": source,
        "proposal_language": source,
        "requested_language": requested,
        "translation_applied": False,
        "legal_terms_present": bool(_LEGAL.search(listing_text or "") or _LEGAL.search(draft or "")),
        "legal_terms_translated": False,
        "client_approval_present": bool(_APPROVAL.search(listing_text or "") or _APPROVAL.search(draft or "")),
        "client_approval_translated": False,
        "unsupported_translation_refused": refused,
        "business_delivery_operational": verified and not refused,
        "screen_catalog_verified": verified,
        "operational": verified and not refused,
    }


def assess_operations_task(text: str, requested_language: str) -> dict:
    """Return the task in its original language. Do not emit a translation."""
    source = detect_source_language(text)
    requested = normalize_language(requested_language)
    known = requested in SUPPORTED
    if not known:
        requested = str(requested_language or "").strip().lower()
    rollout = requested in ROLLOUT
    copy_code = requested if requested in APPROVAL else "en"
    return {
        "input_text": text,
        "output_text": text,
        "source_language": source,
        "requested_language": requested,
        "output_language": source,
        "translation_applied": False,
        "legal_terms_present": bool(_LEGAL.search(text or "")),
        "legal_terms_translated": False,
        "client_approval_present": bool(_APPROVAL.search(text or "")),
        "client_approval_translated": False,
        "unsupported_translation_refused": rollout or not known,
        "business_delivery_operational": known and not rollout,
        "screen_catalog_verified": requested in VERIFIED_SCREEN,
        "operational": known and not rollout,
        "approval_copy": APPROVAL[copy_code],
        "notice": NOTICES.get(requested, ""),
    }
