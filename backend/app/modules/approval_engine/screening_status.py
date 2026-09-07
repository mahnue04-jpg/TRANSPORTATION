"""Applicant/admin screening status mapping for MVR and background checks.

Does not call vendors or invent clearance results. Maps persisted consent and
Approval Engine requirement states into a stable public status vocabulary.
"""
from __future__ import annotations

from typing import Any

SCREENING_STATUSES = (
    "not_started",
    "consent_required",
    "pending",
    "review_required",
    "cleared",
    "failed",
    "expired",
)

_CLEARED = frozenset({"COMPLETE", "VERIFIED", "CLEAR", "CLEARED"})
_FAILED = frozenset({"FAILED", "DISQUALIFIED", "REJECTED"})
_EXPIRED = frozenset({"EXPIRED"})
_PENDING = frozenset(
    {
        "PENDING",
        "PENDING_EXTERNAL",
        "PENDING_VERIFICATION",
        "SUBMITTED",
        "IN_PROGRESS",
        "ACTION_REQUIRED",
    }
)
_REVIEW = frozenset({"MANUAL_REVIEW", "REVIEW_REQUIRED", "FLAGGED"})


def normalize_screening_status(raw: str | None, *, has_consent: bool) -> str:
    value = str(raw or "").strip().upper()
    if value in _CLEARED:
        return "cleared"
    if value in _FAILED:
        return "failed"
    if value in _EXPIRED:
        return "expired"
    if value in _REVIEW:
        return "review_required"
    if value in _PENDING or value in {"REQUIRED"}:
        return "pending" if has_consent else "consent_required"
    if not has_consent:
        return "consent_required"
    if not value or value in {"NOT_STARTED", "UNKNOWN", "NOT_REQUIRED"}:
        return "not_started" if not has_consent else "pending"
    return "pending" if has_consent else "consent_required"


def _requirement_status(case: Any, key: str) -> str | None:
    if case is None:
        return None
    for row in getattr(case, "requirements", None) or []:
        if str(getattr(row, "requirement_key", "") or "") == key:
            return str(getattr(row, "status", "") or "")
    return None


def screening_summary_for_application(
    *,
    application: Any,
    case: Any = None,
) -> dict[str, Any]:
    mvr_consent = bool(
        getattr(application, "declaration_mvr_authorization", False)
        or any(
            str(getattr(doc, "category", "")) == "motor_vehicle_record_consent"
            and str(getattr(doc, "review_status", "")).lower() in {"pending", "accepted"}
            for doc in (getattr(application, "documents", None) or [])
        )
    )
    bg_consent = bool(
        getattr(application, "declaration_background_authorization", False)
        or getattr(application, "background_consent_at", None)
        or any(
            str(getattr(doc, "category", "")) == "background_check_consent"
            and str(getattr(doc, "review_status", "")).lower() in {"pending", "accepted"}
            for doc in (getattr(application, "documents", None) or [])
        )
    )
    mvr_raw = _requirement_status(case, "mvr") or getattr(case, "mvr_status", None)
    bg_raw = _requirement_status(case, "background_study") or getattr(case, "background_study_status", None)
    mvr_status = normalize_screening_status(mvr_raw, has_consent=mvr_consent)
    bg_status = normalize_screening_status(bg_raw, has_consent=bg_consent)
    blocking = [
        key
        for key, status in (("mvr", mvr_status), ("background_study", bg_status))
        if status in {"consent_required", "pending", "review_required", "failed", "expired", "not_started"}
        # background_study may be non-base; still surface status, but only hard-block when AE marks it blocking.
    ]
    # Activation hard-block: MVR always required before activation for BASE private ambulatory.
    activation_blockers = []
    if mvr_status in {"consent_required", "pending", "review_required", "failed", "expired", "not_started"}:
        activation_blockers.append(f"mvr:{mvr_status}")
    bg_req = None
    if case is not None:
        for row in getattr(case, "requirements", None) or []:
            if str(getattr(row, "requirement_key", "")) == "background_study":
                bg_req = row
                break
    if bg_req is not None and bool(getattr(bg_req, "is_blocking", False)):
        if bg_status in {"consent_required", "pending", "review_required", "failed", "expired", "not_started"}:
            activation_blockers.append(f"background_study:{bg_status}")
    return {
        "statuses_supported": list(SCREENING_STATUSES),
        "external_vendor_configured": False,
        "external_vendor_note": (
            "No live MVR/background vendor adapter is configured. "
            "Do not invent clearance. Configure a licensed provider API/account before public recruiting."
        ),
        "mvr": {
            "status": mvr_status,
            "consent_on_file": mvr_consent,
            "raw_status": mvr_raw,
        },
        "background_study": {
            "status": bg_status,
            "consent_on_file": bg_consent,
            "raw_status": bg_raw,
            "blocking_when_required": bool(getattr(bg_req, "is_blocking", False)) if bg_req else False,
        },
        "activation_blockers": activation_blockers,
        "blocks_activation": bool(activation_blockers),
    }
