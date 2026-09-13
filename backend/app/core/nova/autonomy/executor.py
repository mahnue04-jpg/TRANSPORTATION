"""Supervised Phase 1 executor. LOW acts only after owner approval. MEDIUM records only."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.autonomy import ledger
from app.core.nova.autonomy.models import AutonomyApproveRequest, AutonomyIntentCreate, AutonomyIntentOut
from app.core.nova.autonomy.policy import (
    can_act,
    classify,
    is_blocked,
    may_execute,
    normalize_action_type,
    phase1_enabled,
)
from app.core.nova.today.schemas import RECOMMENDED_ACTIONS, NovaTodayActionCreate, NovaTodayApproveRequest
from app.helpers import uuid4


class AutonomyError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _require_enabled() -> None:
    if not phase1_enabled():
        raise AutonomyError("Autonomy Phase 1 is off.", status_code=404)


def _source_module(value: str | None, action_type: str) -> str:
    if value in {"workspace", "communications", "government", "business", "link", "autonomy"}:
        return value
    if action_type == "create_draft":
        return "communications"
    if action_type == "create_task":
        return "business"
    return "autonomy"


def _ensure_today_action(
    db: Session,
    payload: AutonomyIntentCreate,
    *,
    organization_id: str,
    user: UserContext,
    action_type: str,
):
    """Reuse an in-org logical Today row before creating.

    Logical key is organization_id + source_module + source_ref_id +
    recommended_action. Owner is omitted so standing/org-wide cards are
    not minted per viewer.

    Exception: if no in-org row exists and the item is user-specific
    (not a standing synthetic card), Phase 1 may create one owner-scoped
    V2 row. Standing cards (rec-*, link/health|delivery|freight) are
    never created unless today_action_id is supplied.
    """
    from app.core.nova.today import service as today
    from app.core.nova.today.links import is_standing_synthetic

    if payload.today_action_id:
        supplied = today.get_in_org_today_action_by_id(
            db,
            payload.today_action_id,
            organization_id=organization_id,
        )
        if supplied is None:
            raise AutonomyError("Today action not found", status_code=404)
        return today.action_out(supplied)
    if action_type in {"history", "audit_read"}:
        return None
    source_module = payload.source_module if payload.source_module != "autonomy" else "business"
    recommended = action_type if action_type in RECOMMENDED_ACTIONS else "acknowledge"
    existing = today.find_in_org_today_action(
        db,
        organization_id=organization_id,
        source_module=source_module,
        source_ref_id=payload.source_ref_id,
        recommended_action=recommended,
    )
    if existing is not None:
        return today.action_out(existing)
    if is_standing_synthetic(source_module, payload.source_ref_id):
        raise AutonomyError(
            "Phase 1 will not create standing recommendation or product-shortcut cards.",
            status_code=409,
        )
    try:
        return today.create_action(
            db,
            NovaTodayActionCreate(
                source_module=source_module,
                source_ref_id=payload.source_ref_id,
                title=payload.title or action_type,
                recommended_action=recommended,
            ),
            organization_id=organization_id,
            user=user,
        )
    except today.NovaTodayError as exc:
        if exc.status_code == 409:
            reused = today.find_in_org_today_action(
                db,
                organization_id=organization_id,
                source_module=source_module,
                source_ref_id=payload.source_ref_id,
                recommended_action=recommended,
            )
            if reused is not None:
                return today.action_out(reused)
        raise AutonomyError(str(exc), status_code=exc.status_code) from exc


def create_intent(
    db: Session,
    payload: AutonomyIntentCreate,
    *,
    organization_id: str,
    user: UserContext,
    idempotency_key: str | None = None,
) -> AutonomyIntentOut:
    _require_enabled()
    action_type = normalize_action_type(payload.action_type)
    risk = classify(action_type, confidence=payload.confidence)
    existing = ledger.latest_for_idempotency(
        db, organization_id=organization_id, idempotency_key=idempotency_key or ""
    )
    if existing:
        return AutonomyIntentOut.from_row(existing)

    today_action = None
    today_action_id = payload.today_action_id
    if may_execute(risk) and action_type not in {"history", "audit_read"}:
        today_action = _ensure_today_action(
            db, payload, organization_id=organization_id, user=user, action_type=action_type
        )
        today_action_id = today_action.action_id if today_action else None

    if is_blocked(risk):
        approval_state = "blocked"
        result = "blocked_by_policy"
    elif risk == "MEDIUM":
        approval_state = "awaiting_approval"
        result = "request_recorded"
    elif action_type in {"history", "audit_read"}:
        approval_state = "completed"
        result = "history_read"
    else:
        approval_state = "awaiting_approval"
        result = "intent_created"

    verification = "unknown"
    if risk == "MEDIUM":
        verification = "awaiting_approval"
    if is_blocked(risk):
        verification = "blocked"

    row = ledger.append(
        db,
        user=user,
        organization_id=organization_id,
        action_type=action_type,
        risk_class=risk,
        approval_state=approval_state,
        source_module=_source_module(payload.source_module, action_type),
        source_ref_id=payload.source_ref_id,
        executed=False,
        correlation_id=payload.correlation_id or uuid4(),
        idempotency_key=idempotency_key,
        today_action_id=today_action_id,
        target=f"{_source_module(payload.source_module, action_type)}:{payload.source_ref_id}",
        result=result,
        verification_result=verification,
        detail="Phase 1 intent. No external send, file, or pay.",
    )
    return AutonomyIntentOut.from_row(row)


def _verify_low(
    db: Session,
    *,
    action_type: str,
    organization_id: str,
    user: UserContext,
    today_action=None,
    recheck=None,
) -> str:
    from app.core.nova.today import service as today
    from app.core.nova.today.verify import verify_result

    if action_type == "recheck_source":
        if recheck is not None and getattr(recheck, "mutated_external", True) is False:
            return str(getattr(recheck, "verification_status", None) or "verified")
        return "unknown"
    if today_action is None:
        return "unknown"
    if action_type in {"create_draft", "create_task"}:
        row = today._get_action(db, today_action.action_id, organization_id=organization_id, user=user)
        return verify_result(db, row, organization_id=organization_id, user=user)
    if action_type == "snooze":
        return "verified" if today_action.status == "snoozed" and today_action.snoozed_until else "missing"
    if action_type == "dismiss":
        return "verified" if today_action.status == "dismissed" else "missing"
    if action_type in {"acknowledge", "open_link"}:
        return "verified" if today_action.status in {"done", "approved"} else "missing"
    if action_type in {"history", "audit_read"}:
        return "verified"
    return "unknown"


def approve_intent(
    db: Session,
    audit_id: str,
    payload: AutonomyApproveRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> AutonomyIntentOut:
    _require_enabled()
    if not can_act(user):
        raise AutonomyError("Dispatcher and staff cannot ACT in Autonomy Phase 1.", status_code=403)
    current = ledger.latest_for_audit(db, organization_id=organization_id, audit_id=audit_id)
    if current is None:
        raise AutonomyError("Autonomy intent not found.", status_code=404)

    risk = classify(current.action_type)
    if risk != current.risk_class or is_blocked(risk) or not may_execute(risk):
        row = ledger.append(
            db,
            user=user,
            organization_id=organization_id,
            action_type=current.action_type,
            risk_class=risk,
            approval_state="blocked" if is_blocked(risk) else current.approval_state,
            source_module=current.source_module,
            source_ref_id=current.source_ref_id,
            executed=False,
            audit_id=current.audit_id,
            correlation_id=current.correlation_id,
            idempotency_key=current.idempotency_key,
            today_action_id=current.today_action_id,
            target=current.target,
            result="blocked_by_policy" if is_blocked(risk) else "not_executed",
            verification_result="blocked" if is_blocked(risk) else "awaiting_approval",
            detail="Policy recheck denied execution.",
        )
        return AutonomyIntentOut.from_row(row)

    if current.action_type in {"history", "audit_read"}:
        from app.core.nova.today import service as today

        today.list_history(db, organization_id=organization_id, user=user)
        row = ledger.append(
            db,
            user=user,
            organization_id=organization_id,
            action_type=current.action_type,
            risk_class="LOW",
            approval_state="completed",
            source_module=current.source_module,
            source_ref_id=current.source_ref_id,
            executed=False,
            audit_id=current.audit_id,
            correlation_id=current.correlation_id,
            idempotency_key=current.idempotency_key,
            today_action_id=current.today_action_id,
            target=current.target,
            result="history_read",
            verification_result="verified",
        )
        return AutonomyIntentOut.from_row(row)

    from app.core.nova.today import service as today

    href = None
    mutated_external = False
    result_ref_id = current.result_ref_id
    today_out = None
    recheck = None
    try:
        if current.action_type == "snooze":
            hours = payload.hours if payload.hours is not None else 24
            today_out = today.snooze_action(
                db,
                current.today_action_id or "",
                organization_id=organization_id,
                user=user,
                hours=hours,
            )
            result = "snoozed"
        elif current.action_type == "dismiss":
            today_out = today.dismiss_action(
                db,
                current.today_action_id or "",
                organization_id=organization_id,
                user=user,
            )
            result = "dismissed"
        elif current.action_type == "recheck_source":
            recheck = today.recheck_source(
                db,
                organization_id=organization_id,
                user=user,
                action_id=current.today_action_id,
            )
            mutated_external = bool(recheck.mutated_external)
            result = "source_rechecked"
            result_ref_id = recheck.result_ref_id
            if current.today_action_id:
                today_out = today.get_action(
                    db, current.today_action_id, organization_id=organization_id, user=user
                )
        else:
            approved = today.approve_action(
                db,
                current.today_action_id or "",
                NovaTodayApproveRequest(
                    draft_to=payload.draft_to,
                    draft_subject=payload.draft_subject,
                    task_title=payload.task_title,
                ),
                organization_id=organization_id,
                user=user,
            )
            today_out = approved.action
            href = approved.href
            result_ref_id = approved.draft_id or approved.task_id or today_out.result_ref_id
            result = today_out.result_type or "completed"
    except today.NovaTodayError as exc:
        raise AutonomyError(str(exc), status_code=exc.status_code) from exc

    executed = current.action_type not in {"history", "audit_read"}
    verification = _verify_low(
        db,
        action_type=current.action_type,
        organization_id=organization_id,
        user=user,
        today_action=today_out,
        recheck=recheck,
    )
    row = ledger.append(
        db,
        user=user,
        organization_id=organization_id,
        action_type=current.action_type,
        risk_class="LOW",
        approval_state="completed",
        source_module=current.source_module,
        source_ref_id=current.source_ref_id,
        executed=executed,
        audit_id=current.audit_id,
        correlation_id=current.correlation_id,
        idempotency_key=current.idempotency_key,
        result_ref_id=result_ref_id,
        today_action_id=current.today_action_id or (today_out.action_id if today_out else None),
        target=current.target,
        result=result,
        verification_result=verification,
    )
    return AutonomyIntentOut.from_row(row, href=href, mutated_external=mutated_external)


def record_medium_request(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    action_type: str,
    source_ref_id: str,
    source_module: str = "communications",
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
) -> AutonomyIntentOut:
    _require_enabled()
    key = normalize_action_type(action_type)
    risk = classify(key)
    if risk != "MEDIUM":
        raise AutonomyError("Not a Phase 1 MEDIUM request.", status_code=422)
    existing = ledger.latest_for_idempotency(
        db, organization_id=organization_id, idempotency_key=idempotency_key or ""
    )
    if existing:
        return AutonomyIntentOut.from_row(existing)
    row = ledger.append(
        db,
        user=user,
        organization_id=organization_id,
        action_type=key,
        risk_class="MEDIUM",
        approval_state="awaiting_approval",
        source_module=source_module,
        source_ref_id=source_ref_id,
        executed=False,
        correlation_id=correlation_id or uuid4(),
        idempotency_key=idempotency_key,
        target=f"{source_module}:{source_ref_id}",
        result="request_recorded",
        verification_result="awaiting_approval",
        detail="MEDIUM request stored. External send/submit/update was not performed.",
    )
    return AutonomyIntentOut.from_row(row)


def record_today_wrapper(
    db: Session,
    *,
    user: UserContext,
    organization_id: str,
    action_type: str,
    source_module: str,
    source_ref_id: str,
    today_action_id: str | None,
    result_ref_id: str | None,
    result: str,
    verification_result: str | None,
    executed: bool,
) -> None:
    if not phase1_enabled():
        return
    risk = classify(action_type)
    ledger.append(
        db,
        user=user,
        organization_id=organization_id,
        action_type=normalize_action_type(action_type),
        risk_class=risk,
        approval_state="completed" if executed else "awaiting_approval",
        source_module=source_module,
        source_ref_id=source_ref_id,
        executed=executed and may_execute(risk),
        today_action_id=today_action_id,
        result_ref_id=result_ref_id,
        target=f"{source_module}:{source_ref_id}",
        result=result,
        verification_result=verification_result,
    )


def get_intent(db: Session, audit_id: str, *, organization_id: str) -> AutonomyIntentOut:
    _require_enabled()
    row = ledger.latest_for_audit(db, organization_id=organization_id, audit_id=audit_id)
    if row is None:
        raise AutonomyError("Autonomy intent not found.", status_code=404)
    return AutonomyIntentOut.from_row(row)
