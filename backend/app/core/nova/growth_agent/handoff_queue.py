"""Human handoff queue — tenant-scoped escalation for the receptionist pilot."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.errors import CrossTenantError, GrowthAgentError
from app.core.nova.growth_agent.models import GaHandoffRequest
from app.core.nova.growth_agent.redact import redact_mapping


def _utcnow() -> datetime:
    return datetime.utcnow()


def _row_dict(row: GaHandoffRequest) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "contact_id": row.contact_id,
        "conversation_id": row.conversation_id,
        "appointment_id": row.appointment_id,
        "channel": row.channel,
        "reason": row.reason,
        "status": row.status,
        "priority": row.priority,
        "summary": row.summary,
        "payload_redacted_json": dict(row.payload_redacted_json or {}),
        "acknowledged_by": row.acknowledged_by,
        "acknowledged_at": row.acknowledged_at.isoformat() + "Z" if row.acknowledged_at else None,
        "resolved_at": row.resolved_at.isoformat() + "Z" if row.resolved_at else None,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "updated_at": row.updated_at.isoformat() + "Z" if row.updated_at else None,
    }


def _get_handoff(db: Session, *, org_id: str, handoff_id: str) -> GaHandoffRequest:
    row = (
        db.query(GaHandoffRequest)
        .filter_by(id=handoff_id, organization_id=org_id)
        .one_or_none()
    )
    if row is not None:
        return row
    other = db.query(GaHandoffRequest).filter_by(id=handoff_id).one_or_none()
    if other is not None and other.organization_id != org_id:
        raise CrossTenantError()
    raise GrowthAgentError("NOT_FOUND", "Handoff not found", http_status=404)


def create_handoff(
    db: Session,
    *,
    org_id: str,
    reason: str,
    summary: str,
    channel: str = "voice",
    contact_id: str | None = None,
    conversation_id: str | None = None,
    appointment_id: str | None = None,
    priority: str = "normal",
) -> dict[str, Any]:
    payload_source = {
        "reason": reason,
        "summary": summary,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "appointment_id": appointment_id,
    }
    row = GaHandoffRequest(
        id=str(uuid4()),
        organization_id=org_id,
        contact_id=contact_id,
        conversation_id=conversation_id,
        appointment_id=appointment_id,
        channel=channel,
        reason=reason,
        summary=summary,
        status="open",
        priority=priority,
        payload_redacted_json=redact_mapping(payload_source),
    )
    db.add(row)
    db.flush()
    return _row_dict(row)


def list_handoffs(
    db: Session,
    org_id: str,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    lim = max(1, min(int(limit), 200))
    q = db.query(GaHandoffRequest).filter_by(organization_id=org_id)
    if status:
        q = q.filter(GaHandoffRequest.status == status)
    rows = q.order_by(GaHandoffRequest.created_at.desc()).limit(lim).all()
    return [_row_dict(r) for r in rows]


def acknowledge_handoff(
    db: Session,
    org_id: str,
    handoff_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    row = _get_handoff(db, org_id=org_id, handoff_id=handoff_id)
    if row.status == "resolved":
        raise GrowthAgentError("INVALID_STATE", "Handoff already resolved", http_status=409)
    if row.status == "cancelled":
        raise GrowthAgentError("INVALID_STATE", "Handoff cancelled", http_status=409)
    row.status = "acknowledged"
    row.acknowledged_by = actor_user_id
    row.acknowledged_at = _utcnow()
    db.flush()
    return _row_dict(row)


def resolve_handoff(
    db: Session,
    org_id: str,
    handoff_id: str,
    actor_user_id: str,
) -> dict[str, Any]:
    row = _get_handoff(db, org_id=org_id, handoff_id=handoff_id)
    if row.status == "resolved":
        return {**_row_dict(row), "idempotent": True}
    if row.status == "cancelled":
        raise GrowthAgentError("INVALID_STATE", "Handoff cancelled", http_status=409)
    if row.status == "open":
        row.acknowledged_by = row.acknowledged_by or actor_user_id
        row.acknowledged_at = row.acknowledged_at or _utcnow()
    row.status = "resolved"
    row.resolved_at = _utcnow()
    db.flush()
    return _row_dict(row)