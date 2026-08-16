"""Append-only audit logging for the AI Approval Engine."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.models import ApprovalAuditEvent, ApprovalCase
from app.modules.approval_engine.statuses import ACTOR_TYPES


def record_audit(
    db: Session,
    *,
    organization_id: str,
    action: str,
    entity_type: str = "driver",
    entity_id: str | None = None,
    case: ApprovalCase | None = None,
    actor_type: str = "SYSTEM",
    actor_id: str | None = None,
    previous_status: str | None = None,
    new_status: str | None = None,
    reason: str | None = None,
    evidence_ref: str | None = None,
    approval_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> ApprovalAuditEvent:
    actor = str(actor_type or "SYSTEM").upper()
    if actor not in ACTOR_TYPES:
        actor = "SYSTEM"
    event = ApprovalAuditEvent(
        id=uuid4(),
        case_id=case.id if case else None,
        organization_id=organization_id,
        entity_type=entity_type,
        entity_id=entity_id or (case.entity_id if case else None),
        actor_type=actor,
        actor_id=actor_id,
        previous_status=previous_status,
        new_status=new_status,
        action=action,
        reason=reason,
        evidence_ref=evidence_ref,
        approval_id=approval_id,
        metadata_json=json.dumps(metadata) if metadata else None,
        created_at=now(),
    )
    db.add(event)
    if commit:
        db.commit()
        db.refresh(event)
    else:
        db.flush()
    return event


def list_audit_events(
    db: Session,
    *,
    organization_id: str,
    case_id: str | None = None,
    entity_id: str | None = None,
    application_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[ApprovalAuditEvent]:
    query = db.query(ApprovalAuditEvent).filter(
        ApprovalAuditEvent.organization_id == organization_id
    )
    if case_id:
        query = query.filter(ApprovalAuditEvent.case_id == case_id)
    if entity_id:
        query = query.filter(ApprovalAuditEvent.entity_id == entity_id)
    if application_id:
        case_ids = [
            row.id
            for row in db.query(ApprovalCase.id)
            .filter(
                ApprovalCase.organization_id == organization_id,
                ApprovalCase.application_id == application_id,
            )
            .all()
        ]
        if case_ids:
            query = query.filter(ApprovalAuditEvent.case_id.in_(case_ids))
        else:
            return []
    if action:
        query = query.filter(ApprovalAuditEvent.action == action)
    return (
        query.order_by(ApprovalAuditEvent.created_at.desc(), ApprovalAuditEvent.id.desc())
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )


def serialize_audit(event: ApprovalAuditEvent) -> dict[str, Any]:
    meta = None
    if event.metadata_json:
        try:
            meta = json.loads(event.metadata_json)
        except json.JSONDecodeError:
            meta = {"raw": event.metadata_json}
    return {
        "event_id": event.id,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "case_id": event.case_id,
        "actor_type": event.actor_type,
        "actor_id": event.actor_id,
        "timestamp": event.created_at.isoformat() if event.created_at else None,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "action": event.action,
        "reason": event.reason,
        "evidence_ref": event.evidence_ref,
        "approval_id": event.approval_id,
        "metadata": meta,
    }
