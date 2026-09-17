"""Source-grounded Lifesaver summaries. Local records only. Not clinical."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Iterable

from app.modules.lifesaver.constants import AI_DISCLAIMER
from app.modules.lifesaver.observation_quality import (
    QUALITY_INVALID,
    QUALITY_MISSING,
    QUALITY_STALE,
    QUALITY_UNSUPPORTED,
    QUALITY_VALID,
    SOURCE_TYPE_MANUAL,
    SOURCE_TYPE_SIMULATED,
)

_DIAGNOSIS_CLAIM_RE = re.compile(
    r"\b(diagnosed with|this is (a )?(disease|cancer)|increasing dangerously|"
    r"dangerously\b|you have (cancer|diabetes|hypertension)|heart attack|"
    r"life.?saving)\b",
    re.IGNORECASE,
)

_OBSERVATION_QUESTION_RE = re.compile(
    r"\b(weight|glucose|blood pressure|blood-pressure|\bbp\b|spo2|"
    r"oxygen|temperature|reading|measurement|observation|health data|"
    r"last reading|my numbers|summarize my)\b",
    re.IGNORECASE,
)

_VALUE_LABEL = {
    SOURCE_TYPE_SIMULATED: "Simulated value",
    SOURCE_TYPE_MANUAL: "Manual entry",
}

_REJECTED = frozenset({
    QUALITY_INVALID,
    QUALITY_MISSING,
    QUALITY_UNSUPPORTED,
    "DUPLICATE",
    "OUT_OF_ORDER",
    QUALITY_STALE,
})


def looks_like_observation_question(message: str | None) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    return bool(_OBSERVATION_QUESTION_RE.search(text))


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_when(value: Any) -> str:
    stamped = _parse_ts(value)
    if stamped is None:
        return "an unspecified time"
    return stamped.strftime("%I:%M %p").lstrip("0")


def _kind_label(measurement_type: str) -> str:
    return (measurement_type or "reading").replace("_", " ")


def _value_phrase(record: dict[str, Any]) -> str:
    kind = _kind_label(str(record.get("measurement_type") or "reading"))
    unit = record.get("unit") or ""
    primary = record.get("value")
    secondary = record.get("value_secondary")
    if primary is None:
        body = "no numeric value"
    elif secondary is not None and str(record.get("measurement_type")) in {"blood_pressure"}:
        body = f"{primary}/{secondary} {unit}".strip()
    else:
        body = f"{primary} {unit}".strip()
    source_type = record.get("source_type") or ""
    if record.get("simulated") or source_type == SOURCE_TYPE_SIMULATED:
        prefix = "A simulated"
    elif source_type == SOURCE_TYPE_MANUAL or record.get("source") in {"user_entered", "manual_entry"}:
        prefix = "A manual"
    else:
        prefix = "A recorded"
    return f"{prefix} {kind} entry of {body} was recorded at {_format_when(record.get('captured_at'))}"


def _quality_note(record: dict[str, Any]) -> str | None:
    status = record.get("quality_status")
    if status == QUALITY_VALID and record.get("trusted"):
        if record.get("simulated"):
            return None
        return None
    if status == QUALITY_STALE:
        return "stale"
    if status in {QUALITY_INVALID, QUALITY_MISSING, QUALITY_UNSUPPORTED, "DUPLICATE", "OUT_OF_ORDER"}:
        return (status or "rejected").lower().replace("_", "-")
    return "quality-limited"


def empty_provenance(*, reason: str, missing: bool = True) -> dict[str, Any]:
    return {
        "source_record_ids": [],
        "source_measurement_types": [],
        "source_timestamps": [],
        "source_quality_statuses": [],
        "simulated_sources_present": False,
        "missing_data_flags": [reason] if missing else [],
        "rejected_record_ids": [],
        "trusted_record_count": 0,
    }


def build_provenance(trusted: list[dict[str, Any]], rejected: list[dict[str, Any]], *, missing_flags: list[str]) -> dict[str, Any]:
    records = trusted + rejected
    return {
        "source_record_ids": [row.get("provenance_id") or row.get("id") for row in trusted if row.get("provenance_id") or row.get("id")],
        "source_measurement_types": sorted({str(row.get("measurement_type")) for row in trusted if row.get("measurement_type")}),
        "source_timestamps": [row.get("captured_at") for row in trusted if row.get("captured_at")],
        "source_quality_statuses": [str(row.get("quality_status") or "") for row in records if row.get("quality_status")],
        "simulated_sources_present": any(bool(row.get("simulated")) for row in trusted),
        "missing_data_flags": missing_flags,
        "rejected_record_ids": [row.get("provenance_id") or row.get("id") for row in rejected if row.get("provenance_id") or row.get("id")],
        "trusted_record_count": len(trusted),
    }


def summarize_from_records(records: Iterable[dict[str, Any]] | None) -> dict[str, Any]:
    rows = [dict(row) for row in (records or [])]
    trusted = [row for row in rows if row.get("trusted") and row.get("quality_status") == QUALITY_VALID]
    rejected = [row for row in rows if row not in trusted]
    missing_flags: list[str] = []

    if not rows:
        missing_flags.append("no_source")
        reply = (
            "No trustworthy reading is available. I cannot provide a data-based "
            "conclusion because no stored Lifesaver observation was found. "
            + AI_DISCLAIMER
        )
        return {
            "reply": reply,
            "mode": "provenance_no_source",
            "disclaimer": AI_DISCLAIMER,
            "provenance": empty_provenance(reason="no_source"),
        }

    if not trusted:
        statuses = {str(row.get("quality_status") or "") for row in rejected}
        if statuses and statuses <= {QUALITY_STALE}:
            missing_flags.append("all_stale")
            reply = (
                "No trustworthy reading is available. Every candidate observation "
                "is marked stale and was not used as evidence. "
                + AI_DISCLAIMER
            )
            mode = "provenance_all_stale"
        elif statuses and statuses <= {QUALITY_INVALID, QUALITY_MISSING, QUALITY_UNSUPPORTED}:
            missing_flags.append("all_rejected")
            reply = (
                "No trustworthy reading is available. Every candidate observation "
                "was rejected as invalid, missing, or unsupported and was not used "
                "as evidence. "
                + AI_DISCLAIMER
            )
            mode = "provenance_all_rejected"
        else:
            missing_flags.append("no_trusted_source")
            labels = ", ".join(sorted(status.lower().replace("_", "-") for status in statuses if status)) or "quality-limited"
            reply = (
                "No trustworthy reading is available. Stored candidate observations "
                f"are quality-limited ({labels}) and were not used as trusted evidence. "
                + AI_DISCLAIMER
            )
            mode = "provenance_untrusted"
        return {
            "reply": reply,
            "mode": mode,
            "disclaimer": AI_DISCLAIMER,
            "provenance": build_provenance([], rejected, missing_flags=missing_flags),
        }

    sentences: list[str] = []
    by_type: dict[str, list[dict[str, Any]]] = {}
    for row in trusted:
        by_type.setdefault(str(row.get("measurement_type") or "reading"), []).append(row)

    for kind, group in by_type.items():
        ordered = sorted(group, key=lambda item: item.get("captured_at") or "")
        latest = ordered[-1]
        sentences.append(_value_phrase(latest) + ".")
        if latest.get("simulated"):
            sentences.append("This value is simulated and is not from a connected medical device.")
        elif (latest.get("source_type") == SOURCE_TYPE_MANUAL) or latest.get("source") in {"user_entered", "manual_entry"}:
            sentences.append("This value is a manual entry.")
        if len(ordered) == 1:
            sentences.append(
                f"No prior trustworthy {_kind_label(kind)} reading is available for comparison."
            )
        else:
            earlier = ordered[-2]
            sentences.append(
                "A later stored value is available after an earlier stored value of "
                f"{earlier.get('value')} {earlier.get('unit') or ''}".strip()
                + ". This is a stored-record comparison, not a diagnosis."
            )

    if rejected:
        notes = []
        for row in rejected:
            label = _quality_note(row)
            ident = row.get("provenance_id") or row.get("id")
            if label and ident:
                notes.append(f"{ident} ({label})")
        if notes:
            sentences.append(
                "Additional stored observations were not used as trusted evidence: "
                + "; ".join(notes[:8])
                + "."
            )
        if any(row.get("quality_status") == QUALITY_STALE for row in rejected):
            sentences.append("At least one stored observation is stale.")
        if any(row.get("quality_status") in {QUALITY_INVALID, QUALITY_MISSING, QUALITY_UNSUPPORTED} for row in rejected):
            sentences.append("At least one stored observation was rejected for quality reasons.")

    ids = [str(row.get("provenance_id") or row.get("id")) for row in trusted if row.get("provenance_id") or row.get("id")]
    if ids:
        sentences.append("Internal record IDs used: " + ", ".join(ids) + ".")
    content = " ".join(sentences)
    if _DIAGNOSIS_CLAIM_RE.search(content):
        content = (
            "A stored observation summary is available only as a non-diagnostic "
            "record listing. I cannot provide a disease conclusion from these records."
        )
    reply = content + " " + AI_DISCLAIMER

    if any(row.get("simulated") for row in trusted):
        missing_flags.append("simulated_disclosed")
    if any((row.get("source_type") == SOURCE_TYPE_MANUAL) or row.get("source") in {"user_entered", "manual_entry"} for row in trusted):
        missing_flags.append("manual_disclosed")

    return {
        "reply": reply,
        "mode": "provenance_summary",
        "disclaimer": AI_DISCLAIMER,
        "provenance": build_provenance(trusted, rejected, missing_flags=missing_flags),
    }


def refuses_diagnosis_wording(text: str | None) -> bool:
    body = (text or "").replace(AI_DISCLAIMER, "")
    return not bool(_DIAGNOSIS_CLAIM_RE.search(body))
