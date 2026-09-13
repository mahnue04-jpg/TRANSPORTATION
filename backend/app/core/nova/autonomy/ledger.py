"""Append-only Autonomy Phase 1 ledger. No secrets, tokens, or message bodies."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.autonomy.models import AutonomyIntentOut, NovaAutonomyLedger
from app.core.nova.autonomy.schema_ensure import ensure_autonomy_schema as _ensure_autonomy_schema
from app.helpers import now, uuid4


def ensure_autonomy_schema(engine) -> None:
    _ensure_autonomy_schema(engine)


def _audit_id() -> str:
    return "NAL-" + uuid4().replace("-", "")[:12].upper()


def append(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    action_type: str,
    risk_class: str,
    approval_state: str,
    source_module: str,
    source_ref_id: str,
    executed: bool = False,
    audit_id: str | None = None,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    result_ref_id: str | None = None,
    target: str | None = None,
    today_action_id: str | None = None,
    result: str = "recorded",
    verification_result: str | None = None,
    detail: str | None = None,
    workflow_id: str | None = None,
    step_id: str | None = None,
    target_module: str | None = None,
    approver_user_id: str | None = None,
    attempt_number: int | None = None,
) -> NovaAutonomyLedger:
    row = NovaAutonomyLedger(
        audit_id=audit_id or _audit_id(),
        correlation_id=correlation_id or uuid4(),
        idempotency_key=(idempotency_key or "").strip() or None,
        actor_user_id=user.user_id,
        actor_role=user.role,
        organization_id=organization_id,
        action_type=action_type,
        source_module=source_module,
        source_ref_id=source_ref_id,
        result_ref_id=result_ref_id,
        target=target,
        risk_class=risk_class,
        approval_state=approval_state,
        executed=executed,
        today_action_id=today_action_id,
        result=result[:240],
        verification_result=verification_result,
        detail=(detail or "")[:400] or None,
        created_at=now(),
        workflow_id=workflow_id,
        step_id=step_id,
        target_module=target_module,
        approver_user_id=approver_user_id,
        attempt_number=attempt_number,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_for_idempotency(
    db: Session, *, organization_id: str, idempotency_key: str
) -> NovaAutonomyLedger | None:
    key = (idempotency_key or "").strip()
    if not key:
        return None
    return (
        db.query(NovaAutonomyLedger)
        .filter(
            NovaAutonomyLedger.organization_id == organization_id,
            NovaAutonomyLedger.idempotency_key == key,
        )
        .order_by(NovaAutonomyLedger.created_at.desc())
        .first()
    )


def latest_for_audit(db: Session, *, organization_id: str, audit_id: str) -> NovaAutonomyLedger | None:
    return (
        db.query(NovaAutonomyLedger)
        .filter(
            NovaAutonomyLedger.organization_id == organization_id,
            NovaAutonomyLedger.audit_id == audit_id,
        )
        .order_by(NovaAutonomyLedger.created_at.desc())
        .first()
    )


def list_ledger(
    db: Session, *, organization_id: str, limit: int = 50
) -> list[AutonomyIntentOut]:
    rows = (
        db.query(NovaAutonomyLedger)
        .filter(NovaAutonomyLedger.organization_id == organization_id)
        .order_by(NovaAutonomyLedger.created_at.desc())
        .limit(max(1, min(limit, 100)))
        .all()
    )
    return [AutonomyIntentOut.from_row(row) for row in rows]
