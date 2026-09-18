"""Supervised owner-action queue. Approval is never execution."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.adapters import AdapterRequest, get_adapter
from app.core.nova.work_revenue.adapters.contracts import KIND_TO_CAPABILITY
from app.core.nova.work_revenue.config import is_capability_enabled
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.models import NovaWorkLiveActionAudit, NovaWorkSupervisedAction
from app.core.nova.work_revenue.safety import evaluate_live_action
from app.core.nova.work_revenue.service import (
    NovaWorkError,
    _ensure,
    _new_id,
    _owner_filter,
    _record_audit,
    _safe_summary,
)
from app.helpers import now

SUPERVISED_STATUSES = (
    "DRAFT",
    "READY_FOR_REVIEW",
    "OWNER_APPROVED",
    "QUEUED",
    "EXECUTED",
    "FAILED",
    "CANCELED",
)

ACTION_TYPES = {
    "REVIEW_OPPORTUNITY": "LIVE_DISCOVERY",
    "APPROVE_QUALIFICATION": "LIVE_DISCOVERY",
    "APPROVE_APPLICATION": "EXTERNAL_SUBMISSION",
    "APPROVE_EXTERNAL_SUBMISSION": "EXTERNAL_SUBMISSION",
    "APPROVE_CLIENT_CONTACT": "CLIENT_CONTACT",
    "APPROVE_REPORT_SEND": "REPORT_SEND",
    "APPROVE_INVOICE_SEND": "INVOICE_SEND",
    "APPROVE_CALENDAR_ACTION": "CALENDAR_ACTIONS",
    "APPROVE_PAYMENT_ACTION": "FINANCIAL_EXECUTION",
}

CAPABILITY_TO_KIND = {value: key for key, value in KIND_TO_CAPABILITY.items()}

TRANSITIONS = {
    "DRAFT": {"READY_FOR_REVIEW", "CANCELED"},
    "READY_FOR_REVIEW": {"OWNER_APPROVED", "DRAFT", "CANCELED"},
    "OWNER_APPROVED": {"QUEUED", "CANCELED", "FAILED"},
    "QUEUED": {"FAILED", "CANCELED"},
    "EXECUTED": set(),
    "FAILED": {"CANCELED"},
    "CANCELED": set(),
}

DEFAULT_TZ = "America/Chicago"
_TAG_RE = re.compile(r"<[^>]+>")


def _plain(value: str | None, limit: int) -> str:
    return _TAG_RE.sub("", sanitize_untrusted(value or ""))[:limit].strip()


def _query(db: Session, organization_id: str, user: UserContext):
    return _owner_filter(
        db.query(NovaWorkSupervisedAction).filter(NovaWorkSupervisedAction.organization_id == organization_id),
        NovaWorkSupervisedAction,
        user,
    )


def _validate_timezone(value: str | None) -> str:
    token = (value or DEFAULT_TZ).strip() or DEFAULT_TZ
    try:
        ZoneInfo(token)
    except ZoneInfoNotFoundError as exc:
        raise NovaWorkError("timezone must be an explicit IANA name") from exc
    return token


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc).isoformat()
    return value.astimezone(timezone.utc).isoformat()


def record_live_audit(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    action_type: str,
    outcome: str,
    reason: str,
    external_target: str | None = None,
    idempotency_key: str | None = None,
    supervised_action_id: str | None = None,
    conditions: dict[str, Any] | None = None,
) -> NovaWorkLiveActionAudit:
    row = NovaWorkLiveActionAudit(
        audit_id=_new_id("NWL-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        action_type=str(action_type or "")[:48],
        outcome=("allowed" if str(outcome).lower() == "allowed" else "blocked"),
        reason=_safe_summary(reason)[:400],
        external_target=sanitize_untrusted(external_target or "")[:220] or None,
        idempotency_key=(idempotency_key or "")[:120] or None,
        supervised_action_id=supervised_action_id,
        conditions_json=json.dumps(conditions or {}, separators=(",", ":")),
    )
    db.add(row)
    return row


def action_out(row: NovaWorkSupervisedAction) -> dict[str, Any]:
    return {
        "supervised_action_id": row.supervised_action_id,
        "action_type": row.action_type,
        "capability": row.capability,
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "ref_type": row.ref_type,
        "ref_id": row.ref_id,
        "idempotency_key": row.idempotency_key,
        "timezone": row.timezone,
        "owner_approved": bool(row.owner_approved),
        "approved_at": _iso(row.approved_at),
        "queued_at": _iso(row.queued_at),
        "executed_at": _iso(row.executed_at),
        "canceled_at": _iso(row.canceled_at),
        "blocked_reason": row.blocked_reason,
        "failure_reason": row.failure_reason,
        "approval_equals_execution": False,
        "live_execution": False,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def get_action(
    db: Session, supervised_action_id: str, *, organization_id: str, user: UserContext
) -> NovaWorkSupervisedAction:
    _ensure()
    row = _query(db, organization_id, user).filter(
        NovaWorkSupervisedAction.supervised_action_id == supervised_action_id
    ).first()
    if row is None:
        raise NovaWorkError("Supervised action not found", status_code=404)
    return row


def create_action(
    db: Session,
    payload: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    action_type = str(payload.get("action_type") or "").strip().upper()
    if action_type not in ACTION_TYPES:
        raise NovaWorkError("Unknown supervised action type")
    timezone_name = _validate_timezone(payload.get("timezone"))
    idempotency_key = sanitize_untrusted(str(payload.get("idempotency_key") or "")).strip()
    if not idempotency_key or len(idempotency_key) > 120:
        raise NovaWorkError("idempotency_key is required")
    title = _plain(str(payload.get("title") or action_type.replace("_", " ").title()), 220)
    summary = _plain(str(payload.get("summary") or "Owner-controlled action. Approval is not execution."), 2000)
    row = NovaWorkSupervisedAction(
        supervised_action_id=_new_id("NWS-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        action_type=action_type,
        status="DRAFT",
        capability=ACTION_TYPES[action_type],
        title=title or action_type,
        summary=summary or "Owner-controlled action.",
        ref_type=sanitize_untrusted(str(payload.get("ref_type") or ""))[:32] or None,
        ref_id=sanitize_untrusted(str(payload.get("ref_id") or ""))[:32] or None,
        idempotency_key=idempotency_key,
        timezone=timezone_name,
        payload_json=json.dumps(
            {key: payload.get(key) for key in ("ref_type", "ref_id") if payload.get(key)},
            separators=(",", ":"),
        ),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise NovaWorkError("Duplicate supervised action idempotency key", status_code=409) from exc
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="SUPERVISED_ACTION_CREATED",
        summary=f"Draft supervised action {row.supervised_action_id}. Approval is not execution.",
        ref_id=row.supervised_action_id,
        entity_type="supervised_action",
        actor_category="OWNER",
        new_state="DRAFT",
    )
    db.commit()
    db.refresh(row)
    return action_out(row)


def _apply(
    db: Session,
    row: NovaWorkSupervisedAction,
    target: str,
    *,
    organization_id: str,
    user: UserContext,
    notes: str | None = None,
) -> NovaWorkSupervisedAction:
    allowed = TRANSITIONS.get(row.status, set())
    if target not in allowed:
        raise NovaWorkError(f"Cannot transition supervised action from {row.status} to {target}")
    previous = row.status
    row.status = target
    row.updated_at = now()
    if notes is not None:
        row.owner_notes = sanitize_untrusted(notes) or None
    if target == "OWNER_APPROVED":
        row.owner_approved = True
        row.approved_at = now()
        row.blocked_reason = None
    if target == "QUEUED":
        row.queued_at = now()
    if target == "CANCELED":
        row.canceled_at = now()
        row.owner_approved = False
    if target == "FAILED":
        row.failure_reason = row.failure_reason or "Live execution is disabled."
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="SUPERVISED_ACTION_TRANSITION",
        summary=f"Supervised action {previous} → {target}. APPROVED != EXECUTED.",
        ref_id=row.supervised_action_id,
        entity_type="supervised_action",
        actor_category="OWNER",
        previous_state=previous,
        new_state=target,
    )
    return row


def submit_for_review(
    db: Session, supervised_action_id: str, *, organization_id: str, user: UserContext
) -> dict[str, Any]:
    row = get_action(db, supervised_action_id, organization_id=organization_id, user=user)
    _apply(db, row, "READY_FOR_REVIEW", organization_id=organization_id, user=user)
    db.commit()
    db.refresh(row)
    return action_out(row)


def approve_action(
    db: Session, supervised_action_id: str, *, organization_id: str, user: UserContext, notes: str | None = None
) -> dict[str, Any]:
    row = get_action(db, supervised_action_id, organization_id=organization_id, user=user)
    _apply(db, row, "OWNER_APPROVED", organization_id=organization_id, user=user, notes=notes)
    db.commit()
    db.refresh(row)
    return action_out(row)


def queue_action(
    db: Session, supervised_action_id: str, *, organization_id: str, user: UserContext
) -> dict[str, Any]:
    row = get_action(db, supervised_action_id, organization_id=organization_id, user=user)
    if not row.owner_approved:
        raise NovaWorkError("Execution cannot be queued without owner approval")
    _apply(db, row, "QUEUED", organization_id=organization_id, user=user)
    db.commit()
    db.refresh(row)
    return action_out(row)


def cancel_action(
    db: Session, supervised_action_id: str, *, organization_id: str, user: UserContext, notes: str | None = None
) -> dict[str, Any]:
    row = get_action(db, supervised_action_id, organization_id=organization_id, user=user)
    _apply(db, row, "CANCELED", organization_id=organization_id, user=user, notes=notes)
    db.commit()
    db.refresh(row)
    return action_out(row)


def execute_action(
    db: Session, supervised_action_id: str, *, organization_id: str, user: UserContext
) -> dict[str, Any]:
    row = get_action(db, supervised_action_id, organization_id=organization_id, user=user)
    if row.status == "EXECUTED":
        raise NovaWorkError("Duplicate execution is blocked", status_code=409)
    if row.status == "CANCELED":
        raise NovaWorkError("Revoked approval stops queued execution", status_code=409)
    if row.status not in {"OWNER_APPROVED", "QUEUED"}:
        raise NovaWorkError("Execution cannot happen without approval and queueing")
    if not row.owner_approved:
        raise NovaWorkError("Execution cannot happen without approval")
    kind = CAPABILITY_TO_KIND.get(row.capability, "external_submission")
    adapter = get_adapter(kind, dry_run=True)
    request = AdapterRequest(
        organization_id=organization_id,
        owner_user_id=user.user_id,
        action_type=row.action_type,
        idempotency_key=row.idempotency_key,
        owner_approved=bool(row.owner_approved),
        dry_run=True,
        timezone=row.timezone,
        external_target=row.ref_id,
    )
    decision = evaluate_live_action(
        row.capability,
        tenant_authorized=True,
        owner_approved=bool(row.owner_approved),
        adapter_implemented=False,
        required_facts_available=False,
        terms_policy_satisfied=False,
        not_duplicated=True,
        dry_run=True,
    )
    adapter_result = adapter.execute(request)
    record_live_audit(
        db,
        organization_id=organization_id,
        user=user,
        action_type=row.capability,
        outcome="blocked",
        reason=decision.reason,
        external_target=row.ref_id,
        idempotency_key=row.idempotency_key,
        supervised_action_id=row.supervised_action_id,
        conditions=decision.conditions,
    )
    row.status = "FAILED"
    row.failure_reason = decision.reason
    row.blocked_reason = decision.reason
    row.updated_at = now()
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="SUPERVISED_ACTION_EXECUTION_BLOCKED",
        summary="Live execution blocked. Approval is not execution. Nothing was sent.",
        ref_id=row.supervised_action_id,
        entity_type="supervised_action",
        actor_category="NOVA",
        previous_state="QUEUED" if row.queued_at else "OWNER_APPROVED",
        new_state="FAILED",
    )
    db.commit()
    db.refresh(row)
    payload = action_out(row)
    payload["safety"] = decision.as_dict()
    payload["adapter"] = adapter_result.as_dict()
    payload["capability_enabled"] = is_capability_enabled(row.capability)
    return payload


def list_actions(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    _ensure()
    query = _query(db, organization_id, user)
    token = (status or "").strip().upper()
    if token and token != "ALL":
        query = query.filter(NovaWorkSupervisedAction.status == token)
    rows = query.order_by(NovaWorkSupervisedAction.updated_at.desc()).limit(max(1, min(int(limit or 100), 200))).all()
    return [action_out(row) for row in rows]


def queue_board(db: Session, *, organization_id: str, user: UserContext) -> dict[str, Any]:
    rows = list_actions(db, organization_id=organization_id, user=user, status="ALL", limit=200)
    groups = {
        "pending_owner_approval": [row for row in rows if row["status"] in {"DRAFT", "READY_FOR_REVIEW"}],
        "approved_waiting": [row for row in rows if row["status"] in {"OWNER_APPROVED", "QUEUED"}],
        "blocked": [row for row in rows if row["status"] == "FAILED" or row.get("blocked_reason")],
        "completed": [row for row in rows if row["status"] == "EXECUTED"],
        "failed": [row for row in rows if row["status"] == "FAILED"],
        "canceled": [row for row in rows if row["status"] == "CANCELED"],
    }
    return {
        "approval_equals_execution": False,
        "live_execution": False,
        "counts": {key: len(value) for key, value in groups.items()},
        **groups,
    }


def live_audit_out(row: NovaWorkLiveActionAudit) -> dict[str, Any]:
    try:
        conditions = json.loads(row.conditions_json or "{}")
    except json.JSONDecodeError:
        conditions = {}
    return {
        "audit_id": row.audit_id,
        "action_type": row.action_type,
        "outcome": row.outcome,
        "reason": row.reason,
        "owner_user_id": row.owner_user_id,
        "organization_id": row.organization_id,
        "timestamp": _iso(row.created_at),
        "external_target": row.external_target,
        "idempotency_key": row.idempotency_key,
        "supervised_action_id": row.supervised_action_id,
        "conditions": conditions,
        "secrets_exposed": False,
    }


def list_live_audits(
    db: Session, *, organization_id: str, user: UserContext, limit: int = 100
) -> list[dict[str, Any]]:
    _ensure()
    rows = (
        _owner_filter(
            db.query(NovaWorkLiveActionAudit).filter(NovaWorkLiveActionAudit.organization_id == organization_id),
            NovaWorkLiveActionAudit,
            user,
        )
        .order_by(NovaWorkLiveActionAudit.created_at.desc())
        .limit(max(1, min(int(limit or 100), 200)))
        .all()
    )
    return [live_audit_out(row) for row in rows]
