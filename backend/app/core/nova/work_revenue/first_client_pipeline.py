"""First-client board for saved Work & Revenue opportunities.

The board is a read model plus owner bookkeeping. It does not search the
network, send an application, sign anything, or mark an application sent
unless that application was already externally submitted.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import service, submission
from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkSubmissionLedger,
)
from app.helpers import now

_PREVIEW_LIMIT = 360
_TOP_LIMIT = 10
_SECRET_RE = re.compile(r"(?i)\b(password|api[_ -]?key|secret|token)\b\s*[:=]\s*\S+")
_RANK = {
    "NOVA_CAN_PERFORM": 3,
    "NOVA_WITH_OWNER_REVIEW": 2,
    "INSUFFICIENT_INFORMATION": 1,
}
_RESPONSE_STATES = {"ACKNOWLEDGED", "DELIVERY_FAILURE"}


class FollowUpRequest(BaseModel):
    follow_up_at: datetime
    organization_id: str | None = None


class ResponseRecordRequest(BaseModel):
    outcome: str = Field(pattern="^(ACKNOWLEDGED|DELIVERY_FAILURE)$")
    note: str | None = Field(default=None, max_length=400)
    organization_id: str | None = None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_qual(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _preview(text: str | None) -> str | None:
    cleaned = _SECRET_RE.sub(r"\1=[REDACTED]", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    if len(cleaned) > _PREVIEW_LIMIT:
        return cleaned[:_PREVIEW_LIMIT] + "…"
    return cleaned


def _record_class(opportunity: NovaWorkOpportunity) -> str:
    source = f"{opportunity.source or ''} {opportunity.source_type or ''}".lower()
    if "simulat" in source or "fixture" in source or "example.invalid" in str(opportunity.source_url or ""):
        return "simulated"
    if "manual" in source or "import" in source:
        return "manual"
    return "live"


def _own_application(db: Session, application_id: str, *, organization_id: str, user: UserContext) -> NovaWorkApplication:
    service._ensure()
    row = (
        db.query(NovaWorkApplication)
        .filter(
            NovaWorkApplication.organization_id == organization_id,
            NovaWorkApplication.owner_user_id == user.user_id,
            NovaWorkApplication.application_id == application_id,
        )
        .first()
    )
    if row is None:
        raise service.NovaWorkError("Work application not found", status_code=404)
    return row


def _own_opportunity(db: Session, opportunity_id: str, *, organization_id: str, user: UserContext) -> NovaWorkOpportunity:
    row = (
        db.query(NovaWorkOpportunity)
        .filter(
            NovaWorkOpportunity.organization_id == organization_id,
            NovaWorkOpportunity.owner_user_id == user.user_id,
            NovaWorkOpportunity.opportunity_id == opportunity_id,
        )
        .first()
    )
    if row is None:
        raise service.NovaWorkError("Work opportunity not found", status_code=404)
    return row


def _ledger_rows(db: Session, *, organization_id: str, user: UserContext) -> list[NovaWorkSubmissionLedger]:
    return (
        db.query(NovaWorkSubmissionLedger)
        .filter(
            NovaWorkSubmissionLedger.organization_id == organization_id,
            NovaWorkSubmissionLedger.owner_user_id == user.user_id,
        )
        .all()
    )


def _stage(application: NovaWorkApplication | None, rows: list[NovaWorkSubmissionLedger]) -> str:
    if application is None:
        return "DISCOVERED"
    latest_response = next(
        (row for row in sorted(rows, key=lambda item: item.updated_at, reverse=True) if row.state in _RESPONSE_STATES),
        None,
    )
    if application.externally_submitted:
        if latest_response is not None:
            return latest_response.state
        return "SENT"
    if application.manual_submission_recorded:
        if latest_response is not None and latest_response.state == "ACKNOWLEDGED":
            return "ACKNOWLEDGED"
        return "MANUAL_RECORDED"
    if application.approval_state == "APPROVED" and application.approved_for_future_submission:
        if any(row.state == "BLOCKED" for row in rows):
            return "BLOCKED"
        return "APPROVED_NOT_SENT"
    if application.approval_state == "READY_FOR_OWNER_REVIEW":
        return "READY_FOR_OWNER_REVIEW"
    if application.approval_state in {"REJECTED", "NEEDS_CHANGES"}:
        return application.approval_state
    return "DRAFT"


def _next_action(
    *,
    stage: str,
    opportunity: NovaWorkOpportunity,
    blocked: NovaWorkSubmissionLedger | None,
) -> str:
    if stage == "SENT":
        return "Record the employer response, or set a follow-up time. This view does not send another message."
    if stage == "ACKNOWLEDGED":
        return "Track the employer response. Do not mark payment received until you confirm the cash yourself."
    if stage == "DELIVERY_FAILURE":
        return "The confirmed send failed. Do not treat this application as delivered. Fix the channel before any retry."
    if stage == "MANUAL_RECORDED":
        return "You recorded a manual submission. Nova did not send it. Record the employer response or set a follow-up."
    if stage == "BLOCKED" and blocked is not None and blocked.next_action:
        return blocked.next_action
    if stage == "APPROVED_NOT_SENT":
        if not opportunity.source_url:
            return "Add the exact application URL. Nova will not guess a recipient, and approval has not sent this."
        policy = submission.policy_for_opportunity(opportunity)
        return (
            f"Open the {policy.provider_id} source and submit the approved package yourself. "
            "No verified submit adapter is connected, so Nova has not sent this."
        )
    if stage == "READY_FOR_OWNER_REVIEW":
        return "Approve the draft or request changes. Approval does not send the application."
    if stage == "DRAFT":
        return "Review the draft materials and mark them ready. Nothing is sent from a draft."
    if stage == "DISCOVERED":
        return "Qualify this opportunity and prepare a draft. Nothing is sent from discovery."
    if stage == "NEEDS_CHANGES":
        return "Revise the draft and return it for review. The previous approval was not a send."
    if stage == "REJECTED":
        return "This application was rejected internally. Nova will not send it."
    return "Review the saved record. Nova has not contacted the client."


def _ledger_public(row: NovaWorkSubmissionLedger) -> dict[str, Any]:
    return {
        "ledger_id": row.ledger_id,
        "application_id": row.application_id,
        "opportunity_id": row.opportunity_id,
        "channel": row.channel,
        "state": row.state,
        "recipient": row.recipient,
        "receipt": row.receipt,
        "receipt_verified": bool(row.receipt) and row.state in {"SENT", "ACKNOWLEDGED", "DELIVERY_FAILURE"},
        "blocker_reason": row.blocker_reason,
        "next_action": row.next_action,
        "follow_up_due_at": row.follow_up_due_at.isoformat() if row.follow_up_due_at else None,
        "is_send_receipt": row.state == "SENT" and bool(row.receipt),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _card(
    opportunity: NovaWorkOpportunity,
    application: NovaWorkApplication | None,
    materials: list[NovaWorkMaterial],
    rows: list[NovaWorkSubmissionLedger],
) -> dict[str, Any]:
    qual = _parse_qual(opportunity.qualification_json)
    reasons = [str(item) for item in (qual.get("reasons") or []) if str(item).strip()]
    if opportunity.qualification_reason and opportunity.qualification_reason not in reasons:
        reasons.insert(0, opportunity.qualification_reason)
    stage = _stage(application, rows)
    blocked = next((row for row in rows if row.state == "BLOCKED"), None)
    proposal = next((item for item in materials if item.kind == "proposal"), None)
    pilot = next((item for item in materials if item.kind == "paid_pilot_options"), None)
    sent_row = next((row for row in rows if row.state == "SENT" and row.receipt), None)
    follow_up = None
    if application and application.follow_up_at:
        follow_up = application.follow_up_at
    elif opportunity.follow_up_at:
        follow_up = opportunity.follow_up_at
    actually_sent = bool(application and application.externally_submitted)
    return {
        "opportunity_id": opportunity.opportunity_id,
        "application_id": application.application_id if application else None,
        "company_name": opportunity.company_name,
        "title": opportunity.opportunity_title,
        "record_class": _record_class(opportunity),
        "source": opportunity.source,
        "source_type": opportunity.source_type,
        "source_url": opportunity.source_url,
        "discovered_at": opportunity.discovered_at.isoformat() if opportunity.discovered_at else None,
        "application_deadline": opportunity.application_deadline.isoformat() if opportunity.application_deadline else None,
        "qualification_outcome": opportunity.qualification_outcome,
        "qualification_reasons": reasons[:8],
        "capability_fit_score": qual.get("capability_fit_score"),
        "proposal_preview": _preview(proposal.body if proposal else None),
        "paid_pilot_preview": _preview(pilot.body if pilot else None),
        "stage": stage,
        "approval_state": application.approval_state if application else None,
        "actually_sent": actually_sent,
        "manual_submission_recorded": bool(application and application.manual_submission_recorded),
        "receipt": sent_row.receipt if sent_row else None,
        "receipt_verified": bool(sent_row and sent_row.receipt),
        "follow_up_at": follow_up.isoformat() if follow_up else None,
        "blocker_reason": blocked.blocker_reason if blocked else None,
        "next_action": _next_action(stage=stage, opportunity=opportunity, blocked=blocked),
        "external_action_taken": False,
    }


def build_board(db: Session, *, organization_id: str, user: UserContext) -> dict[str, Any]:
    """Return the signed-in owner's top matches and honest submission counts."""
    service._ensure()
    opportunities = (
        db.query(NovaWorkOpportunity)
        .filter(
            NovaWorkOpportunity.organization_id == organization_id,
            NovaWorkOpportunity.owner_user_id == user.user_id,
            NovaWorkOpportunity.archived.is_not(True),
        )
        .all()
    )
    applications = (
        db.query(NovaWorkApplication)
        .filter(
            NovaWorkApplication.organization_id == organization_id,
            NovaWorkApplication.owner_user_id == user.user_id,
        )
        .all()
    )
    app_by_opp = {row.opportunity_id: row for row in applications}
    app_ids = [row.application_id for row in applications]
    materials: list[NovaWorkMaterial] = []
    if app_ids:
        materials = (
            db.query(NovaWorkMaterial)
            .filter(
                NovaWorkMaterial.organization_id == organization_id,
                NovaWorkMaterial.owner_user_id == user.user_id,
                NovaWorkMaterial.application_id.in_(app_ids),
                NovaWorkMaterial.kind.in_(("proposal", "paid_pilot_options")),
            )
            .all()
        )
    materials_by_app: dict[str, list[NovaWorkMaterial]] = {}
    for item in materials:
        materials_by_app.setdefault(item.application_id, []).append(item)
    ledger_by_app: dict[str, list[NovaWorkSubmissionLedger]] = {}
    for item in _ledger_rows(db, organization_id=organization_id, user=user):
        ledger_by_app.setdefault(item.application_id, []).append(item)

    ranked: list[tuple[tuple[int, int, str], NovaWorkOpportunity]] = []
    for opportunity in opportunities:
        qual = _parse_qual(opportunity.qualification_json)
        outcome = str(opportunity.qualification_outcome or qual.get("outcome") or "")
        try:
            fit_score = int(qual.get("capability_fit_score") or 0)
        except (TypeError, ValueError):
            fit_score = 0
        ranked.append(((_RANK.get(outcome, 0), fit_score, opportunity.updated_at.isoformat()), opportunity))
    ranked.sort(key=lambda item: item[0], reverse=True)

    cards = []
    for _key, opportunity in ranked[:_TOP_LIMIT]:
        application = app_by_opp.get(opportunity.opportunity_id)
        rows = ledger_by_app.get(application.application_id, []) if application else []
        drafts = materials_by_app.get(application.application_id, []) if application else []
        cards.append(_card(opportunity, application, drafts, rows))

    sent_cards = []
    for application in applications:
        if not application.externally_submitted:
            continue
        opportunity = next((row for row in opportunities if row.opportunity_id == application.opportunity_id), None)
        if opportunity is None:
            continue
        if any(card["application_id"] == application.application_id for card in cards):
            continue
        rows = ledger_by_app.get(application.application_id, [])
        drafts = materials_by_app.get(application.application_id, [])
        sent_cards.append(_card(opportunity, application, drafts, rows))

    def _count(stage: str) -> int:
        return sum(1 for card in cards + sent_cards if card["stage"] == stage)

    current = now()
    follow_ups_due = 0
    for card in cards + sent_cards:
        if not card["follow_up_at"]:
            continue
        if card["stage"] not in {"SENT", "MANUAL_RECORDED", "ACKNOWLEDGED", "DELIVERY_FAILURE"}:
            continue
        due = datetime.fromisoformat(card["follow_up_at"])
        if _as_utc(due) <= current and card["stage"] != "ACKNOWLEDGED":
            follow_ups_due += 1

    return {
        "mode": "first_client_board",
        "demo": False,
        "live_search_claimed": False,
        "live_search_status": "not_run",
        "empty_reason": None if cards else "no_saved_opportunities",
        "top_matches": cards,
        "sent_outside_top_matches": sent_cards[:_TOP_LIMIT],
        "counts": {
            "top_matches": len(cards),
            "drafts": _count("DRAFT") + _count("READY_FOR_OWNER_REVIEW") + _count("NEEDS_CHANGES"),
            "approved_not_sent": _count("APPROVED_NOT_SENT") + _count("BLOCKED"),
            "actually_sent": sum(1 for card in cards + sent_cards if card["actually_sent"]),
            "manual_recorded": _count("MANUAL_RECORDED"),
            "blocked": _count("BLOCKED"),
            "delivery_failures": _count("DELIVERY_FAILURE"),
            "acknowledgements": _count("ACKNOWLEDGED"),
            "follow_ups_due": follow_ups_due,
        },
        "applications_sent_by_this_request": 0,
        "external_action_taken": False,
        "external_submission": False,
        "financial_execution": False,
    }


def _save_ledger(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    application: NovaWorkApplication,
    state: str,
    channel: str,
    idempotency_key: str,
    recipient: str | None = None,
    receipt: str | None = None,
    blocker_reason: str | None = None,
    next_action: str | None = None,
) -> NovaWorkSubmissionLedger:
    existing = (
        db.query(NovaWorkSubmissionLedger)
        .filter(
            NovaWorkSubmissionLedger.organization_id == organization_id,
            NovaWorkSubmissionLedger.owner_user_id == user.user_id,
            NovaWorkSubmissionLedger.idempotency_key == idempotency_key,
        )
        .first()
    )
    if existing is not None:
        existing.state = state
        existing.channel = channel[:80]
        existing.recipient = recipient
        existing.receipt = receipt
        existing.blocker_reason = blocker_reason
        existing.next_action = next_action
        existing.updated_at = now()
        return existing
    row = NovaWorkSubmissionLedger(
        ledger_id=service._new_id("NWL-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        application_id=application.application_id,
        opportunity_id=application.opportunity_id,
        channel=channel[:80],
        state=state,
        recipient=(recipient or "")[:220] or None,
        receipt=receipt,
        blocker_reason=blocker_reason,
        next_action=next_action,
        idempotency_key=idempotency_key[:120],
    )
    db.add(row)
    return row


def record_submission_attempt(
    db: Session,
    application_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    """Record the truthful handoff. This does not send and does not invent a receipt."""
    application = _own_application(db, application_id, organization_id=organization_id, user=user)
    before_sent = bool(application.externally_submitted)
    result = submission.submit_or_handoff(
        db,
        application.application_id,
        organization_id=organization_id,
        user=user,
    )
    db.refresh(application)
    if application.externally_submitted and not before_sent:
        application.externally_submitted = False
        db.flush()
        result = {
            **dict(result),
            "status": "BLOCKED",
            "externally_submitted": False,
            "external_action_taken": False,
            "reason": "No stored receipt was found, so this attempt was not marked sent.",
        }
    if result.get("externally_submitted") is True and not before_sent:
        result = {
            **dict(result),
            "status": "BLOCKED",
            "externally_submitted": False,
            "external_action_taken": False,
            "reason": "The handoff did not store a send receipt. Approval remains unsent.",
        }
    reason = str(result.get("reason") or "No verified submit channel is connected.")
    next_action = (
        "Owner step: open the source URL and submit the approved package yourself. "
        + reason
    )
    row = _save_ledger(
        db,
        organization_id=organization_id,
        user=user,
        application=application,
        state="BLOCKED",
        channel=str(result.get("provider_id") or "handoff"),
        idempotency_key=f"blocked:{application.application_id}",
        blocker_reason=reason[:1000],
        next_action=next_action[:1000],
    )
    service._record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="SUBMISSION_BLOCKED",
        summary="Submission attempt recorded as blocked. Nothing was sent.",
        ref_id=application.application_id,
        entity_type="application",
        actor_category="NOVA",
        new_state="BLOCKED",
        reason=reason,
        source="first_client_pipeline",
    )
    db.commit()
    db.refresh(row)
    db.refresh(application)
    return {
        "ledger": _ledger_public(row),
        "handoff": {
            "status": "BLOCKED",
            "externally_submitted": False,
            "external_action_taken": False,
            "application_url": result.get("application_url"),
            "provider_id": result.get("provider_id"),
            "reason": reason,
        },
        "application_externally_submitted": bool(application.externally_submitted),
        "applications_sent_by_this_request": 0,
        "financial_execution": False,
    }


def schedule_follow_up(
    db: Session,
    application_id: str,
    payload: FollowUpRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    """Set a follow-up only after a real or owner-recorded submission. Does not send."""
    application = _own_application(db, application_id, organization_id=organization_id, user=user)
    if not application.externally_submitted and not application.manual_submission_recorded:
        raise service.NovaWorkError(
            "Follow-up can be scheduled only after a confirmed send or an owner-recorded manual submission. This application has not been sent.",
            status_code=409,
        )
    due = _as_utc(payload.follow_up_at)
    current = now()
    if due <= current:
        raise service.NovaWorkError("Follow-up time must be in the future", status_code=422)
    if due > current + timedelta(days=90):
        raise service.NovaWorkError("Follow-up time must be within 90 days", status_code=422)
    opportunity = _own_opportunity(
        db,
        application.opportunity_id,
        organization_id=organization_id,
        user=user,
    )
    application.follow_up_at = due
    opportunity.follow_up_at = due
    application.updated_at = current
    opportunity.updated_at = current
    service._record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="FOLLOW_UP_SCHEDULED",
        summary="Owner scheduled a follow-up. Nova did not send it.",
        ref_id=application.application_id,
        entity_type="application",
        actor_category="OWNER",
        new_state="FOLLOW_UP_SCHEDULED",
        reason=due.isoformat(),
        source="first_client_pipeline",
    )
    db.commit()
    db.refresh(application)
    return {
        "application_id": application.application_id,
        "follow_up_at": application.follow_up_at.isoformat() if application.follow_up_at else None,
        "externally_submitted": bool(application.externally_submitted),
        "message_sent": False,
        "external_action_taken": False,
    }


def record_response(
    db: Session,
    application_id: str,
    payload: ResponseRecordRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    """Record an employer acknowledgement or a delivery failure. Does not send."""
    application = _own_application(db, application_id, organization_id=organization_id, user=user)
    outcome = payload.outcome
    if outcome == "DELIVERY_FAILURE" and not application.externally_submitted:
        raise service.NovaWorkError(
            "Delivery failure can be recorded only after a confirmed send. This application has not been sent.",
            status_code=409,
        )
    if outcome == "ACKNOWLEDGED" and not (
        application.externally_submitted or application.manual_submission_recorded
    ):
        raise service.NovaWorkError(
            "An acknowledgement can be recorded only after a confirmed send or an owner-recorded manual submission.",
            status_code=409,
        )
    note = re.sub(r"\s+", " ", str(payload.note or "")).strip()[:400] or None
    if outcome == "ACKNOWLEDGED":
        next_action = "Employer acknowledgement recorded by the owner. Nova did not contact the client again."
    else:
        next_action = "Delivery failure recorded. This application is not treated as delivered."
    row = _save_ledger(
        db,
        organization_id=organization_id,
        user=user,
        application=application,
        state=outcome,
        channel="owner_recorded_response",
        idempotency_key=f"response:{application.application_id}:{outcome}",
        receipt=note,
        blocker_reason=note if outcome == "DELIVERY_FAILURE" else None,
        next_action=next_action,
    )
    service._record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="SUBMISSION_RESPONSE_RECORDED",
        summary=f"Owner recorded {outcome}. Nova did not send a message.",
        ref_id=application.application_id,
        entity_type="application",
        actor_category="OWNER",
        new_state=outcome,
        reason=note,
        source="first_client_pipeline",
    )
    db.commit()
    db.refresh(row)
    db.refresh(application)
    return {
        "ledger": _ledger_public(row),
        "actually_sent": bool(application.externally_submitted),
        "applications_sent_by_this_request": 0,
        "external_action_taken": False,
        "financial_execution": False,
    }
