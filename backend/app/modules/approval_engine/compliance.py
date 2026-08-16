"""Post-activation compliance / expiration monitoring."""
from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.audit import record_audit
from app.modules.approval_engine.models import ApprovalCase, ApprovalExternalTask
from app.modules.approval_engine.statuses import assert_transition_allowed, normalize_status


THRESHOLD_DAYS = (
    (60, "informational"),
    (30, "warning"),
    (14, "urgent"),
    (7, "critical"),
)


def classify_expiration(expiration: date | None, *, today: date | None = None) -> dict[str, Any] | None:
    if expiration is None:
        return None
    day = today or date.today()
    days_left = (expiration - day).days
    if days_left < 0:
        return {"level": "expired", "days_left": days_left}
    for threshold, level in THRESHOLD_DAYS:
        if days_left <= threshold:
            # Keep the most severe matching threshold (smallest window).
            continue
    # Pick tightest threshold that still covers days_left.
    level = "informational"
    for threshold, name in reversed(THRESHOLD_DAYS):
        if days_left <= threshold:
            level = name
            break
    if days_left > 60:
        return {"level": "ok", "days_left": days_left}
    return {"level": level, "days_left": days_left}


def _open_reverification_task(db: Session, case: ApprovalCase, requirement_key: str, label: str) -> None:
    existing = next(
        (
            t
            for t in (case.external_tasks or [])
            if getattr(t, "requirement_key", None) == requirement_key
            and t.status in {"OPEN", "IN_PROGRESS", "NEEDS_ATTENTION"}
        ),
        None,
    )
    if existing is not None:
        existing.external_status = "EXPIRED"
        existing.status = "NEEDS_ATTENTION"
        existing.instructions = (
            f"Re-verification required: {label} expired. "
            "AI detected expiration; an authoritative external/manual result is required."
        )
        existing.updated_at = now()
        return
    task = ApprovalExternalTask(
        id=uuid4(),
        case_id=case.id,
        organization_id=case.organization_id,
        task_type=f"{requirement_key}_reverification",
        requirement_key=requirement_key,
        title=f"Re-verify expired: {label}",
        instructions=(
            f"Mandatory credential expired ({requirement_key}). "
            "Submit/record a fresh external or manual verification with evidence. "
            "AI must not invent the renewed result."
        ),
        status="NEEDS_ATTENTION",
        external_status="EXPIRED",
        audit_history_json=json.dumps(
            [{"at": now().isoformat(), "status": "EXPIRED", "action": "reverification_opened"}]
        ),
        created_at=now(),
        updated_at=now(),
    )
    db.add(task)


def monitor_case(db: Session, case: ApprovalCase, *, commit: bool = True) -> dict[str, Any]:
    today = date.today()
    alerts: list[dict[str, Any]] = []
    expired_mandatory: list[str] = []
    reverification_opened: list[str] = []

    for req in case.requirements or []:
        info = classify_expiration(req.expiration_date, today=today)
        if not info:
            continue
        if info["level"] == "ok":
            continue
        alerts.append(
            {
                "requirement_key": req.requirement_key,
                "label": req.label,
                "expiration_date": req.expiration_date.isoformat() if req.expiration_date else None,
                "level": info["level"],
                "days_left": info["days_left"],
                "is_blocking": req.is_blocking,
            }
        )
        if info["level"] == "expired" and req.is_blocking and req.timing in {
            "required_now",
            "required_before_activation",
        }:
            expired_mandatory.append(req.requirement_key)
            req.traffic_light = "red"
            req.status = "EXPIRED"
            req.external_status = "EXPIRED"
            req.updated_at = now()
            _open_reverification_task(db, case, req.requirement_key, req.label or req.requirement_key)
            reverification_opened.append(req.requirement_key)

    action = None
    previous = normalize_status(case.workflow_status)
    if expired_mandatory and previous == "ACTIVE":
        target = "RESTRICTED"
        assert_transition_allowed(previous, target)
        case.workflow_status = target
        case.activation_status = "RESTRICTED"
        case.suspension_restriction_reason = (
            "Mandatory qualification expired: " + ", ".join(expired_mandatory)
        )
        case.next_required_action = (
            "Re-verify expired mandatory credentials: " + ", ".join(expired_mandatory)
        )
        case.updated_at = now()
        action = "auto_restrict_expired_mandatory"
        record_audit(
            db,
            organization_id=case.organization_id,
            case=case,
            entity_type="driver",
            entity_id=case.health_isf_driver_id or case.entity_id,
            actor_type="AI",
            actor_id="compliance_monitor",
            previous_status=previous,
            new_status=target,
            action=action,
            reason=case.suspension_restriction_reason,
            metadata={
                "expired_mandatory": expired_mandatory,
                "reverification_opened": reverification_opened,
                "alerts": alerts,
            },
        )
    elif alerts:
        record_audit(
            db,
            organization_id=case.organization_id,
            case=case,
            entity_type="driver",
            entity_id=case.health_isf_driver_id or case.entity_id,
            actor_type="AI",
            actor_id="compliance_monitor",
            previous_status=previous,
            new_status=case.workflow_status,
            action="compliance_expiration_scan",
            reason=f"{len(alerts)} expiration alert(s)",
            metadata={"alerts": alerts, "reverification_opened": reverification_opened},
        )

    if commit:
        db.commit()
        db.refresh(case)

    return {
        "case_id": case.id,
        "workflow_status": case.workflow_status,
        "alerts": alerts,
        "expired_mandatory": expired_mandatory,
        "reverification_opened": reverification_opened,
        "action": action,
        "next_scan_hint": (today + timedelta(days=1)).isoformat(),
    }


def list_expiring(
    db: Session,
    *,
    organization_id: str,
    within_days: int = 30,
) -> list[dict[str, Any]]:
    today = date.today()
    horizon = today + timedelta(days=max(0, int(within_days)))
    rows: list[dict[str, Any]] = []
    cases = (
        db.query(ApprovalCase)
        .filter(ApprovalCase.organization_id == organization_id)
        .all()
    )
    for case in cases:
        for req in case.requirements or []:
            if not req.expiration_date:
                continue
            if today <= req.expiration_date <= horizon or req.expiration_date < today:
                info = classify_expiration(req.expiration_date, today=today) or {}
                rows.append(
                    {
                        "case_id": case.id,
                        "display_badge": case.display_badge,
                        "driver_name": case.legal_name,
                        "requirement_key": req.requirement_key,
                        "label": req.label,
                        "expiration_date": req.expiration_date.isoformat(),
                        "level": info.get("level"),
                        "days_left": info.get("days_left"),
                        "workflow_status": case.workflow_status,
                    }
                )
    rows.sort(key=lambda item: (item.get("days_left") is None, item.get("days_left") or 0))
    return rows
