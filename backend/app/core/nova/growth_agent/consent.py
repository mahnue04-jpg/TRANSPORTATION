"""Consent-first helpers. Chat is not permission for promotional messaging."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.nova.growth_agent.errors import ConsentRequiredError

STOP_TOKENS = {"stop", "unsubscribe", "opt out", "opt-out", "cancel messages"}


def is_stop_message(text: str | None) -> bool:
    import re

    normalized = (text or "").strip().lower()
    if not normalized:
        return False
    if normalized in STOP_TOKENS:
        return True
    # Whole-message or clearly opt-out phrasing only — not "stop by tomorrow".
    if re.fullmatch(r"(stop|unsubscribe|cancel|opt[ -]?out)([!. ]*)", normalized):
        return True
    return bool(
        re.search(r"\b(unsubscribe|opt[ -]?out)\b", normalized)
        or re.search(r"\bstop (messaging|texts?|emails?|messages?)\b", normalized)
    )


def latest_consent_status(
    records: list[dict[str, Any]],
    *,
    channel: str,
    purpose: str,
) -> str | None:
    """Return opted_in / opted_out / None from chronologically last matching record."""
    matched = [
        r
        for r in records
        if str(r.get("channel")) == channel and str(r.get("purpose")) == purpose
    ]
    if not matched:
        return None
    matched.sort(key=lambda r: str(r.get("recorded_at") or ""))
    return str(matched[-1].get("status") or "")


def assert_can_message(
    records: list[dict[str, Any]],
    *,
    channel: str,
    purpose: str,
    do_not_contact: bool = False,
) -> None:
    if do_not_contact:
        raise ConsentRequiredError("Contact is marked do-not-contact")
    status = latest_consent_status(records, channel=channel, purpose=purpose)
    if purpose == "marketing" and status != "opted_in":
        raise ConsentRequiredError("Marketing messages require verifiable opt-in")
    if purpose == "transactional" and status == "opted_out":
        raise ConsentRequiredError("Transactional messaging suppressed after opt-out")
    if status == "opted_out":
        raise ConsentRequiredError("Channel opted out")


def consent_evidence(
    *,
    source: str,
    method: str,
    text_shown: str,
) -> dict[str, Any]:
    return {
        "collection_source": source,
        "method": method,
        "disclosure_shown": text_shown[:500],
        "recorded_at_utc": datetime.utcnow().isoformat() + "Z",
    }
