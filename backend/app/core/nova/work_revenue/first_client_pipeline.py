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
_SEND_KEY_PREFIX = "send:"
_FIXTURE_HOSTS = {"example.com", "example.org", "example.invalid"}
_REJECTED_OUTCOMES = {"NOT_QUALIFIED", "NOT_SUITABLE", "PROHIBITED", "NOT_SUPPORTED"}


class SubmissionTransport:
    """In-process submission transport. The default never opens a socket."""

    permitted_channel: dict[str, Any] | None = None

    def deliver(self, message: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": "BLOCKED",
            "receipt": None,
            "reason": "No authenticated permitted channel is connected.",
            "network_used": False,
        }


_submission_transport: SubmissionTransport = SubmissionTransport()


def set_submission_transport(transport: SubmissionTransport | None) -> None:
    """Install a test double. Production keeps the default, which cannot send."""
    global _submission_transport
    _submission_transport = transport or SubmissionTransport()


def permitted_submission_channel() -> dict[str, Any] | None:
    channel = getattr(_submission_transport, "permitted_channel", None)
    if not isinstance(channel, dict):
        return None
    if channel.get("permitted") is not True or not str(channel.get("channel_id") or "").strip():
        return None
    return channel


class SubmissionAttemptRequest(BaseModel):
    """Consent is required before a local mock receipt can be stored.

    The default is no consent. This request never authorizes a network send.
    """

    mock_receipt_consent: bool = False
    organization_id: str | None = None


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


def _send_receipt(rows: list[NovaWorkSubmissionLedger]) -> NovaWorkSubmissionLedger | None:
    return next((row for row in rows if row.state == "SENT" and row.receipt), None)


def _stage(application: NovaWorkApplication | None, rows: list[NovaWorkSubmissionLedger]) -> str:
    if application is None:
        return "DISCOVERED"
    ordered = sorted(rows, key=lambda item: item.updated_at or item.created_at, reverse=True)
    latest = ordered[0] if ordered else None
    sent = _send_receipt(rows)
    if application.externally_submitted:
        if sent is None:
            return "BLOCKED"
        if latest is not None and latest.state in _RESPONSE_STATES and latest.updated_at >= sent.updated_at:
            return latest.state
        return "SENT"
    if any(row.state == "MOCK_RECEIPT" and row.receipt for row in rows):
        return "MOCK_RECEIPT"
    if latest is not None and latest.state == "DELIVERY_FAILURE":
        return "DELIVERY_FAILURE"
    if latest is not None and latest.state == "BLOCKED" and application.approval_state == "APPROVED":
        return "BLOCKED"
    if application.manual_submission_recorded:
        if latest is not None and latest.state == "ACKNOWLEDGED":
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
    if stage == "MOCK_RECEIPT":
        return "Mock receipt stored. This is not an application send. Nothing was delivered and no fee was charged."
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
        "mock_only": row.state == "MOCK_RECEIPT" and bool(row.receipt),
        "blocker_reason": row.blocker_reason,
        "next_action": row.next_action,
        "follow_up_due_at": row.follow_up_due_at.isoformat() if row.follow_up_due_at else None,
        "is_send_receipt": row.state == "SENT" and bool(row.receipt),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _provenance(opportunity: NovaWorkOpportunity, qual: dict[str, Any]) -> tuple[str | None, str | None, bool]:
    """Return fetch stamp, where it came from, and whether the URL plus stamp exist."""
    fetched = str(qual.get("fetched_at") or "").strip()
    discovered = opportunity.discovered_at.isoformat() if opportunity.discovered_at else ""
    stamp = fetched or discovered
    basis = "fetched_at" if fetched else ("discovered_at" if discovered else None)
    url = str(opportunity.source_url or "").strip()
    complete = bool(url.startswith("http") and stamp)
    return (stamp or None), basis, complete


def _rejected_outcome(opportunity: NovaWorkOpportunity, qual: dict[str, Any]) -> bool:
    outcome = str(
        opportunity.qualification_outcome
        or qual.get("outcome")
        or qual.get("qualification_status")
        or ""
    )
    return outcome in _REJECTED_OUTCOMES


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
    source_reasons = []
    for item in list(qual.get("source_eligibility_reasons") or []) + list(qual.get("eligibility_explanations") or []):
        text = str(item).strip()
        if text and text not in source_reasons:
            source_reasons.append(text)
        if len(source_reasons) >= 8:
            break
    stage = _stage(application, rows)
    blocked = next((row for row in rows if row.state == "BLOCKED"), None)
    proposal = next((item for item in materials if item.kind == "proposal"), None)
    pilot = next((item for item in materials if item.kind == "paid_pilot_options"), None)
    sent_row = next((row for row in rows if row.state == "SENT" and row.receipt), None)
    mock_row = next((row for row in rows if row.state == "MOCK_RECEIPT" and row.receipt), None)
    follow_up = None
    if application and application.follow_up_at:
        follow_up = application.follow_up_at
    elif opportunity.follow_up_at:
        follow_up = opportunity.follow_up_at
    actually_sent = bool(application and application.externally_submitted)
    fetched_at, provenance_basis, provenance_complete = _provenance(opportunity, qual)
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
        "source_eligibility_reasons": source_reasons,
        "eligibility_decision": str(qual.get("eligibility_decision") or "") or None,
        "source_provider_id": str(qual.get("source_provider_id") or qual.get("provenance_provider") or "") or None,
        "capability_fit_score": qual.get("capability_fit_score"),
        "proposal_preview": _preview(proposal.body if proposal else None),
        "paid_pilot_preview": _preview(pilot.body if pilot else None),
        "stage": stage,
        "approval_state": application.approval_state if application else None,
        "actually_sent": actually_sent,
        "sent_vs_draft": "sent" if actually_sent else "draft",
        "provenance_fetched_at": fetched_at,
        "provenance_basis": provenance_basis,
        "provenance_complete": provenance_complete,
        "manual_submission_recorded": bool(application and application.manual_submission_recorded),
        "receipt": sent_row.receipt if sent_row else (mock_row.receipt if mock_row else None),
        "receipt_verified": bool(sent_row and sent_row.receipt),
        "mock_only": bool(mock_row) and not actually_sent,
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

    eligible: list[NovaWorkOpportunity] = []
    incomplete: list[NovaWorkOpportunity] = []
    rejected_count = 0
    for _key, opportunity in ranked:
        qual = _parse_qual(opportunity.qualification_json)
        if _rejected_outcome(opportunity, qual):
            rejected_count += 1
            continue
        _stamp, _basis, complete = _provenance(opportunity, qual)
        if complete:
            eligible.append(opportunity)
        else:
            incomplete.append(opportunity)

    def _cards_for(rows_in: list[NovaWorkOpportunity]) -> list[dict[str, Any]]:
        built = []
        for opportunity in rows_in:
            application = app_by_opp.get(opportunity.opportunity_id)
            rows = ledger_by_app.get(application.application_id, []) if application else []
            drafts = materials_by_app.get(application.application_id, []) if application else []
            built.append(_card(opportunity, application, drafts, rows))
        return built

    cards = _cards_for(eligible[:_TOP_LIMIT])
    incomplete_cards = _cards_for(incomplete[:_TOP_LIMIT])

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
        "empty_reason": None if cards else (
            "no_complete_matches" if rejected_count or incomplete_cards else "no_saved_opportunities"
        ),
        "top_matches": cards,
        "incomplete_provenance": incomplete_cards,
        "sent_outside_top_matches": sent_cards[:_TOP_LIMIT],
        "counts": {
            "top_matches": len(cards),
            "incomplete_provenance": len(incomplete_cards),
            "rejected": rejected_count,
            "drafts": _count("DRAFT") + _count("READY_FOR_OWNER_REVIEW") + _count("NEEDS_CHANGES"),
            "approved_not_sent": _count("APPROVED_NOT_SENT") + _count("BLOCKED"),
            "actually_sent": sum(1 for card in cards + sent_cards if card["actually_sent"]),
            "mock_receipts": _count("MOCK_RECEIPT"),
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
    if existing is not None and existing.state == "SENT" and existing.receipt and state != "SENT":
        # A stored send receipt is not replaced by a later blocked or failed attempt.
        return existing
    if existing is not None and existing.state == "MOCK_RECEIPT" and existing.receipt and state != "SENT":
        # A stored mock receipt is not a send and is not replaced by a later attempt.
        return existing
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


def _send_ledger(db: Session, *, organization_id: str, user: UserContext, application_id: str) -> NovaWorkSubmissionLedger | None:
    return (
        db.query(NovaWorkSubmissionLedger)
        .filter(
            NovaWorkSubmissionLedger.organization_id == organization_id,
            NovaWorkSubmissionLedger.owner_user_id == user.user_id,
            NovaWorkSubmissionLedger.idempotency_key == f"{_SEND_KEY_PREFIX}{application_id}",
        )
        .first()
    )


def _materials_need_owner_input(db: Session, *, organization_id: str, user: UserContext, application_id: str) -> bool:
    rows = (
        db.query(NovaWorkMaterial)
        .filter(
            NovaWorkMaterial.organization_id == organization_id,
            NovaWorkMaterial.owner_user_id == user.user_id,
            NovaWorkMaterial.application_id == application_id,
        )
        .all()
    )
    return any("OWNER INPUT REQUIRED" in str(row.body or "").upper() for row in rows)


def _attempt_payload(
    row: NovaWorkSubmissionLedger,
    *,
    application: NovaWorkApplication,
    sent_now: int,
    application_url: str | None,
    provider_id: str | None,
) -> dict[str, Any]:
    return {
        "ledger": _ledger_public(row),
        "handoff": {
            "status": row.state,
            "externally_submitted": bool(application.externally_submitted) and row.state == "SENT" and bool(row.receipt),
            "external_action_taken": False,
            "application_url": application_url,
            "provider_id": provider_id,
            "reason": row.blocker_reason or row.next_action,
        },
        "application_externally_submitted": bool(application.externally_submitted),
        "applications_sent_by_this_request": sent_now,
        "mock_only": row.state == "MOCK_RECEIPT" and bool(row.receipt),
        "financial_execution": False,
    }


def record_submission_attempt(
    db: Session,
    application_id: str,
    *,
    organization_id: str,
    user: UserContext,
    mock_receipt_consent: bool = False,
) -> dict[str, Any]:
    """Store a consented local mock receipt, or leave the attempt blocked.

    This route does not mark an application sent. A mock receipt is not a
    delivery, and the transport is not called without explicit consent.
    The default transport never touches the network.
    """
    application = _own_application(db, application_id, organization_id=organization_id, user=user)
    existing = _send_ledger(
        db,
        organization_id=organization_id,
        user=user,
        application_id=application.application_id,
    )
    if existing is not None and existing.state == "MOCK_RECEIPT" and existing.receipt:
        if application.externally_submitted:
            application.externally_submitted = False
            db.commit()
            db.refresh(application)
        return _attempt_payload(
            existing,
            application=application,
            sent_now=0,
            application_url=None,
            provider_id=existing.channel,
        )
    if existing is not None and existing.state == "SENT" and existing.receipt:
        if not application.externally_submitted:
            application.externally_submitted = True
            db.commit()
            db.refresh(application)
        return _attempt_payload(
            existing,
            application=application,
            sent_now=0,
            application_url=None,
            provider_id=existing.channel,
        )

    handoff = submission.submit_or_handoff(
        db,
        application.application_id,
        organization_id=organization_id,
        user=user,
    )
    db.refresh(application)
    if application.externally_submitted and not (existing and existing.receipt):
        application.externally_submitted = False
        db.flush()

    opportunity = _own_opportunity(
        db,
        application.opportunity_id,
        organization_id=organization_id,
        user=user,
    )
    provider_id = str(handoff.get("provider_id") or "handoff")
    application_url = handoff.get("application_url") or opportunity.source_url
    channel = permitted_submission_channel()
    state = "BLOCKED"
    receipt = None
    if channel is None:
        reason = "No authenticated permitted channel is connected."
        next_action = (
            "Owner step: connect one authenticated permitted submission channel for this provider, "
            "or open the source URL and submit the approved package yourself. Nothing was sent."
        )
    elif _materials_need_owner_input(
        db,
        organization_id=organization_id,
        user=user,
        application_id=application.application_id,
    ):
        reason = "The approved draft still contains OWNER INPUT REQUIRED."
        next_action = (
            "Owner step: replace each OWNER INPUT REQUIRED marker in the approved draft, "
            "then retry this single application. Nothing was sent."
        )
    elif not mock_receipt_consent:
        reason = "Owner consent is required before a mock receipt can be stored."
        next_action = (
            "Owner step: check the mock-receipt consent box to store a local receipt. "
            "That receipt is not an application send, and no fee is charged."
        )
    else:
        delivered = _submission_transport.deliver(
            {
                "application_id": application.application_id,
                "channel_id": channel.get("channel_id"),
                "source_url": application_url,
                "sandbox": True,
                "billable": False,
            }
        )
        receipt_value = str(delivered.get("receipt") or "").strip()
        reported_sent = delivered.get("state") == "SENT"
        # network_used means the transport left this process. This board does
        # not record that as a send. A blank receipt is not a receipt either.
        if delivered.get("network_used") or (reported_sent and not receipt_value):
            state = "BLOCKED"
            reason = "The transport did not return a local non-network receipt, so this attempt was not marked sent."
            next_action = (
                "Owner step: confirm the permitted channel can return a local receipt without using the network, "
                "then retry this single application. Nothing was sent."
            )
        elif reported_sent and receipt_value:
            state = "MOCK_RECEIPT"
            receipt = receipt_value[:1000]
            reason = None
            next_action = (
                "Mock receipt stored. This is not an application send. "
                "Nothing was delivered and no fee was charged."
            )
            application.externally_submitted = False
        elif delivered.get("state") == "DELIVERY_FAILURE":
            state = "DELIVERY_FAILURE"
            reason = str(delivered.get("reason") or "The permitted channel rejected the message.")
            next_action = "The confirmed channel failed. Do not treat this application as delivered. Fix the channel before any retry."
            application.externally_submitted = False
        else:
            state = "BLOCKED"
            reason = str(delivered.get("reason") or "The permitted channel did not accept the application.")
            next_action = (
                "Owner step: connect one authenticated permitted submission channel for this provider, "
                "or open the source URL and submit the approved package yourself. Nothing was sent."
            )
            application.externally_submitted = False

    row = _save_ledger(
        db,
        organization_id=organization_id,
        user=user,
        application=application,
        state=state,
        channel=str((channel or {}).get("channel_id") or provider_id)[:80],
        idempotency_key=f"{_SEND_KEY_PREFIX}{application.application_id}",
        recipient=(str(channel.get("recipient") or "")[:220] or None) if channel else None,
        receipt=receipt,
        blocker_reason=(reason or "")[:1000] or None,
        next_action=next_action[:1000],
    )
    application.externally_submitted = bool(row.state == "SENT" and row.receipt)
    recorded_state = row.state
    if recorded_state == "MOCK_RECEIPT" and row.receipt:
        event_type = "MOCK_RECEIPT_STORED"
        summary = "Mock receipt stored. Nothing was sent."
    elif recorded_state == "SENT" and row.receipt:
        event_type = "SUBMISSION_SENT"
        summary = "Submission receipt stored for one application."
    else:
        event_type = "SUBMISSION_BLOCKED"
        summary = "Submission attempt was not marked sent."
    service._record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type=event_type,
        summary=summary,
        ref_id=application.application_id,
        entity_type="application",
        actor_category="NOVA",
        new_state=recorded_state,
        reason=reason,
        source="first_client_pipeline",
    )
    db.commit()
    db.refresh(row)
    db.refresh(application)
    return _attempt_payload(
        row,
        application=application,
        sent_now=1 if state == "SENT" else 0,
        application_url=application_url,
        provider_id=provider_id,
    )


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
    sent = _send_ledger(
        db,
        organization_id=organization_id,
        user=user,
        application_id=application.application_id,
    )
    if sent is None or sent.state != "SENT" or not sent.receipt or not application.externally_submitted:
        raise service.NovaWorkError(
            "Follow-up can be scheduled only after a submission receipt. This application has no send receipt.",
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
    sent = _send_ledger(
        db,
        organization_id=organization_id,
        user=user,
        application_id=application.application_id,
    )
    if sent is None or sent.state != "SENT" or not sent.receipt or not application.externally_submitted:
        raise service.NovaWorkError(
            "An employer response can be recorded only after a submission receipt. This application has no send receipt.",
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


def _verified_live_match(record: dict[str, Any]) -> bool:
    """True only for a qualified live record with a real source URL and fetch time.

    Fixture, simulated, and example hosts never qualify as verified leads.
    """
    from urllib.parse import urlparse

    if str(record.get("record_class") or "").lower() in {"fixture", "simulated", "manual"}:
        return False
    if record.get("simulated") or record.get("fixture"):
        return False
    url = str(record.get("source_url") or "")
    if not url.startswith("https://"):
        return False
    host = (urlparse(url).hostname or "").lower()
    if host in _FIXTURE_HOSTS or host.endswith(".invalid") or host.endswith(".example"):
        return False
    qual = record.get("live_qualification") if isinstance(record.get("live_qualification"), dict) else {}
    status = str(qual.get("qualification_status") or record.get("qualification_status") or "")
    if status != "QUALIFIED":
        return False
    if not str(record.get("fetched_at") or "").strip():
        return False
    blockers = {str(item) for item in (qual.get("blockers") or [])}
    if blockers.intersection({
        "upfront_fee_required",
        "upfront_fee_or_paid_membership",
        "upwork_paid_connects",
        "certification_or_license_required",
        "unverified_experience_required",
        "physical_licensed_or_onsite_role",
    }):
        return False
    return True


def draft_targeted_proposals(records: list[dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Draft at most three proposals for verified live matches. Fixtures draft nothing."""
    from app.core.nova.work_revenue.materials import generate_drafts

    cap = max(0, min(3, int(limit)))
    drafted: list[dict[str, Any]] = []
    for record in records:
        if len(drafted) >= cap:
            break
        if not _verified_live_match(record):
            continue
        materials = generate_drafts(
            {
                "opportunity_title": record.get("title") or record.get("opportunity_title"),
                "company_name": record.get("company_name"),
                "description": record.get("description"),
                "source_url": record.get("source_url"),
                "fetched_at": record.get("fetched_at"),
                "search_family": record.get("search_family"),
            }
        )
        proposal = next((item for item in materials if item.get("kind") == "proposal"), None)
        pilot = next((item for item in materials if item.get("kind") == "paid_pilot_options"), None)
        cost_scope = next((item for item in materials if item.get("kind") == "cost_scope_check"), None)
        if proposal is None or pilot is None or cost_scope is None:
            continue
        body = str(proposal.get("body") or "").rstrip() + "\n\nThis draft was not sent."
        drafted.append(
            {
                "record_class": "live",
                "fixture": False,
                "source_url": record.get("source_url"),
                "fetched_at": record.get("fetched_at"),
                "title": record.get("title") or record.get("opportunity_title"),
                "company_name": record.get("company_name"),
                "proposal": body,
                "paid_pilot_options": pilot.get("body"),
                "cost_scope_check": cost_scope.get("body"),
                "sent": False,
                "external_action_taken": False,
            }
        )
    return drafted
