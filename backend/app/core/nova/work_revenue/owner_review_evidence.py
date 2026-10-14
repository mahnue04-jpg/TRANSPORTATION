"""Development-only owner-review evidence for saved fictional opportunities.

The export is read-only. It does not qualify, approve, submit, contact a
client, or spend money. Production runtimes refuse it. Rows are limited to
the authenticated user's organization and user id, and to simulated records
whose source URL, when present, stays on a reserved example host.
"""
from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.config import is_production_runtime, runtime_environment
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkStatusHistory,
)
from app.core.nova.work_revenue.service import SENSITIVE_RE, is_canonical_simulated_opportunity
from app.core.nova.work_revenue.urls import UnsafeSourceUrl, validate_source_url

EXPORT_COLUMNS = (
    "export_scope",
    "opportunity_id",
    "company_name",
    "opportunity_title",
    "source_url",
    "qualification_outcome",
    "qualification_reason",
    "application_id",
    "proposal_status",
    "application_status",
    "approved_for_future_submission",
    "externally_submitted",
    "approval_history",
    "discovered_at",
    "created_at",
    "updated_at",
    "qualified_at",
    "application_created_at",
    "decided_at",
    "saved_notes",
)

_EXPORT_SCOPE = "development_fictional"
_FICTIONAL_HOSTS = frozenset({"example.invalid", "example.com", "example.org"})
_APPROVAL_AUDIT_TYPES = frozenset({
    "OPPORTUNITY_CREATED",
    "OPPORTUNITY_QUALIFIED",
    "APPLICATION_DRAFT_CREATED",
    "APPLICATION_READY_FOR_REVIEW",
    "OWNER_APPROVED_APPLICATION",
    "OWNER_REJECTED_APPLICATION",
    "APPLICATION_STATUS_CHANGED",
})
_FORMULA_LEAD = frozenset("=+-@\t\r")
_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(
    r"(?<!\w)(?:\+\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]\d{3}[\s.\-]\d{4}(?!\d)"
)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SECRET_ASSIGN_RE = re.compile(
    r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|bearer)\b\s*[:=]\s*\S+"
)
_URL_USERINFO_RE = re.compile(r"(?i)(https?://)[^/\s@]+@")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:token|key|secret|password|api_key|access_token)=)[^&\s]+"
)
_MAX_ROWS = 200
_MAX_HISTORY = 30


class OwnerReviewEvidenceError(Exception):
    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


def assert_development_export_allowed() -> None:
    if is_production_runtime():
        raise OwnerReviewEvidenceError("Owner-review evidence export is development-only.")


def csv_safe(value: object) -> str:
    """Prefix spreadsheet formula leads so a cell cannot execute when opened."""
    text = "" if value is None else str(value)
    text = text.replace("\x00", "")
    if not text:
        return ""
    if text[0] in _FORMULA_LEAD or text.lstrip(" \t")[:1] in "=+-@":
        return "'" + text
    return text


def redact_text(value: object) -> str:
    text = sanitize_untrusted(None if value is None else str(value))
    if not text:
        return ""
    text = _SECRET_ASSIGN_RE.sub("[redacted]", text)
    text = SENSITIVE_RE.sub("[redacted]", text)
    text = _EMAIL_RE.sub("[redacted-email]", text)
    text = _PHONE_RE.sub("[redacted-phone]", text)
    text = _SSN_RE.sub("[redacted-ssn]", text)
    text = _URL_USERINFO_RE.sub(r"\1", text)
    text = _QUERY_SECRET_RE.sub(r"\1[redacted]", text)
    return text


def fictional_source_url(value: str | None) -> bool:
    if not value:
        return True
    try:
        cleaned = validate_source_url(value)
    except UnsafeSourceUrl:
        return False
    if not cleaned:
        return True
    host = (urlparse(cleaned).hostname or "").lower().rstrip(".")
    return host in _FICTIONAL_HOSTS


def is_fictional_saved_opportunity(row: NovaWorkOpportunity) -> bool:
    if not is_canonical_simulated_opportunity(row):
        return False
    return fictional_source_url(getattr(row, "source_url", None))


def _sort_stamp(value: datetime | None) -> datetime:
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _qualified_at(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if not isinstance(data, dict):
        return ""
    stamp = str(data.get("qualified_at") or "").strip()
    if not stamp or "@" in stamp or SENSITIVE_RE.search(stamp):
        return ""
    return stamp[:40]


def _flag(value: bool) -> str:
    return "true" if value else "false"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _history_text(
    history_rows: list[NovaWorkStatusHistory],
    audit_rows: list[NovaWorkAuditEvent],
) -> str:
    events: list[tuple[datetime, str]] = []
    for item in history_rows:
        previous = item.from_status or ""
        note = redact_text(item.note)
        events.append((
            item.created_at,
            f"{_iso(item.created_at)} history {item.ref_type} {previous}->{item.to_status} {note}".strip(),
        ))
    for item in audit_rows:
        if item.event_type not in _APPROVAL_AUDIT_TYPES:
            continue
        summary = redact_text(item.summary)
        events.append((
            item.created_at,
            f"{_iso(item.created_at)} audit {item.event_type} {summary}".strip(),
        ))
    events.sort(key=lambda pair: _sort_stamp(pair[0]))
    return _clip(" ; ".join(text for _stamp, text in events[:_MAX_HISTORY]), 2000)


def _display_source_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        cleaned = validate_source_url(value)
    except UnsafeSourceUrl:
        return "[omitted-unsafe-url]"
    return redact_text(cleaned or "")


def build_owner_review_evidence(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    assert_development_export_allowed()
    if not user.user_id:
        raise OwnerReviewEvidenceError("User authorization is required")
    if not user.organization_id or organization_id != user.organization_id:
        raise OwnerReviewEvidenceError("Cross-tenant owner-review evidence export denied")

    saved = (
        db.query(NovaWorkOpportunity)
        .filter(
            NovaWorkOpportunity.organization_id == organization_id,
            NovaWorkOpportunity.owner_user_id == user.user_id,
        )
        .order_by(NovaWorkOpportunity.created_at.asc())
        .all()
    )
    fictional = [row for row in saved if is_fictional_saved_opportunity(row)]
    omitted = len(saved) - len(fictional)
    truncated = max(0, len(fictional) - _MAX_ROWS)
    included = fictional[:_MAX_ROWS]
    opportunity_ids = [row.opportunity_id for row in included]

    applications: list[NovaWorkApplication] = []
    if opportunity_ids:
        applications = (
            db.query(NovaWorkApplication)
            .filter(
                NovaWorkApplication.organization_id == organization_id,
                NovaWorkApplication.owner_user_id == user.user_id,
                NovaWorkApplication.opportunity_id.in_(opportunity_ids),
            )
            .all()
        )
    apps_by_opportunity: dict[str, NovaWorkApplication] = {}
    for application in applications:
        current = apps_by_opportunity.get(application.opportunity_id)
        if current is None or (application.updated_at or application.created_at) >= (
            current.updated_at or current.created_at
        ):
            apps_by_opportunity[application.opportunity_id] = application
    application_ids = [item.application_id for item in apps_by_opportunity.values()]

    proposal_status: dict[str, str] = {}
    if application_ids:
        material_rows = (
            db.query(
                NovaWorkMaterial.application_id,
                NovaWorkMaterial.kind,
                NovaWorkMaterial.status,
                NovaWorkMaterial.created_at,
            )
            .filter(
                NovaWorkMaterial.organization_id == organization_id,
                NovaWorkMaterial.owner_user_id == user.user_id,
                NovaWorkMaterial.application_id.in_(application_ids),
                NovaWorkMaterial.kind == "proposal",
            )
            .order_by(NovaWorkMaterial.created_at.asc())
            .all()
        )
        for application_id, _kind, status, _created_at in material_rows:
            proposal_status[application_id] = str(status or "")

    ref_ids = opportunity_ids + application_ids
    history_by_ref: dict[str, list[NovaWorkStatusHistory]] = {ref: [] for ref in ref_ids}
    audit_by_ref: dict[str, list[NovaWorkAuditEvent]] = {ref: [] for ref in ref_ids}
    if ref_ids:
        for item in (
            db.query(NovaWorkStatusHistory)
            .filter(
                NovaWorkStatusHistory.organization_id == organization_id,
                NovaWorkStatusHistory.owner_user_id == user.user_id,
                NovaWorkStatusHistory.ref_id.in_(ref_ids),
            )
            .order_by(NovaWorkStatusHistory.created_at.asc())
            .all()
        ):
            history_by_ref.setdefault(item.ref_id, []).append(item)
        for item in (
            db.query(NovaWorkAuditEvent)
            .filter(
                NovaWorkAuditEvent.organization_id == organization_id,
                NovaWorkAuditEvent.owner_user_id == user.user_id,
                NovaWorkAuditEvent.ref_id.in_(ref_ids),
            )
            .order_by(NovaWorkAuditEvent.created_at.asc())
            .all()
        ):
            audit_by_ref.setdefault(item.ref_id, []).append(item)

    rows: list[dict[str, str]] = []
    for opportunity in included:
        application = apps_by_opportunity.get(opportunity.opportunity_id)
        application_id = application.application_id if application else ""
        history_rows = list(history_by_ref.get(opportunity.opportunity_id, []))
        audit_rows = list(audit_by_ref.get(opportunity.opportunity_id, []))
        if application_id:
            history_rows.extend(history_by_ref.get(application_id, []))
            audit_rows.extend(audit_by_ref.get(application_id, []))
        approval_history = _history_text(history_rows, audit_rows)
        if application and (application.owner_notes or application.notes):
            note_stamp = _iso(application.decided_at or application.updated_at)
            note_text = redact_text(application.owner_notes or application.notes)
            approval_history = _clip(
                f"{approval_history} ; {note_stamp} approval_note {note_text}".strip(" ;"),
                2000,
            )
        rows.append({
            "export_scope": _EXPORT_SCOPE,
            "opportunity_id": opportunity.opportunity_id,
            "company_name": _clip(redact_text(opportunity.company_name), 220),
            "opportunity_title": _clip(redact_text(opportunity.opportunity_title), 220),
            "source_url": _display_source_url(opportunity.source_url),
            "qualification_outcome": redact_text(opportunity.qualification_outcome),
            "qualification_reason": _clip(redact_text(opportunity.qualification_reason), 400),
            "application_id": application_id,
            "proposal_status": proposal_status.get(application_id, ""),
            "application_status": application.approval_state if application else "",
            "approved_for_future_submission": _flag(
                bool(application and application.approved_for_future_submission)
            ),
            "externally_submitted": _flag(bool(application and application.externally_submitted)),
            "approval_history": approval_history,
            "discovered_at": _iso(opportunity.discovered_at),
            "created_at": _iso(opportunity.created_at),
            "updated_at": _iso(opportunity.updated_at),
            "qualified_at": _qualified_at(opportunity.qualification_json),
            "application_created_at": _iso(application.created_at) if application else "",
            "decided_at": _iso(application.decided_at) if application else "",
            "saved_notes": _clip(redact_text(opportunity.notes), 400),
        })

    return {
        "development_only": True,
        "runtime_environment": runtime_environment(),
        "external_submission": False,
        "applications_submitted_by_export": False,
        "fictional_records_only": True,
        "tenant_scoped": True,
        "user_scoped": True,
        "included_count": len(rows),
        "omitted_non_fictional_count": omitted,
        "truncated_count": truncated,
        "columns": list(EXPORT_COLUMNS),
        "rows": rows,
    }


def render_evidence_csv(rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=list(EXPORT_COLUMNS),
        lineterminator="\n",
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({column: csv_safe(row.get(column, "")) for column in EXPORT_COLUMNS})
    return buffer.getvalue()
