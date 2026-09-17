"""Nova Work & Revenue Engine. Local paid-work foundation. No Stripe, no external apply, no Lifesaver."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.work_revenue.capability_registry import list_capabilities, registry_snapshot
from app.core.nova.work_revenue.materials import generate_drafts, sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkOwnerAction,
    NovaWorkStatusHistory,
)
from app.core.nova.work_revenue.providers import get_provider, list_providers
from app.core.nova.work_revenue.qualifier import qualify_opportunity
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.schemas import (
    MATERIAL_KINDS,
    OPPORTUNITY_STATUSES,
    OWNER_ACTION_TYPES,
    ApplicationCreate,
    ApplicationDecision,
    ApplicationOut,
    ApplicationStatusUpdate,
    AuditEventOut,
    CapabilityOut,
    DashboardOut,
    MaterialOut,
    OpportunityCreate,
    OpportunityOut,
    OpportunityUpdate,
    OwnerActionOut,
    ProviderOut,
    QualificationOut,
    StatusHistoryOut,
    TodaySummaryOut,
    TrackerOut,
)
from app.core.nova.work_revenue.verified_profile import OWNER_INPUT_REQUIRED, profile_snapshot
from app.helpers import now, uuid4

SENSITIVE_RE = re.compile(
    r"(ssn|social security|password|secret|api[_-]?key|routing number|account number)",
    re.I,
)

STATUS_TRANSITIONS: dict[str, set[str]] = {
    "DISCOVERED": {"REVIEWING", "QUALIFIED", "NOT_QUALIFIED", "OWNER_REVIEW", "CLOSED"},
    "REVIEWING": {"QUALIFIED", "NOT_QUALIFIED", "OWNER_REVIEW", "DISCOVERED", "CLOSED"},
    "QUALIFIED": {"OWNER_REVIEW", "APPROVED_TO_APPLY", "APPLICATION_PREPARED", "NOT_QUALIFIED", "CLOSED"},
    "NOT_QUALIFIED": {"REVIEWING", "CLOSED"},
    "OWNER_REVIEW": {"APPROVED_TO_APPLY", "APPLICATION_PREPARED", "NOT_QUALIFIED", "QUALIFIED", "CLOSED"},
    "APPROVED_TO_APPLY": {"APPLICATION_PREPARED", "CLOSED", "OWNER_REVIEW"},
    "APPLICATION_PREPARED": {"SUBMITTED", "OWNER_REVIEW", "CLOSED"},
    "SUBMITTED": {"FOLLOW_UP_DUE", "INTERVIEW", "REJECTED", "OFFER", "CLOSED"},
    "FOLLOW_UP_DUE": {"INTERVIEW", "OFFER", "REJECTED", "CLOSED", "SUBMITTED"},
    "INTERVIEW": {"OFFER", "FOLLOW_UP_DUE", "REJECTED", "CLOSED"},
    "OFFER": {"WON", "REJECTED", "CLOSED"},
    "WON": {"CLOSED"},
    "REJECTED": {"CLOSED"},
    "CLOSED": set(),
}

OUTCOME_TO_STATUS = {
    "NOVA_CAN_PERFORM": "QUALIFIED",
    "NOVA_WITH_OWNER_REVIEW": "OWNER_REVIEW",
    "HUMAN_REQUIRED": "OWNER_REVIEW",
    "NOT_SUITABLE": "NOT_QUALIFIED",
    "INSUFFICIENT_INFORMATION": "REVIEWING",
}

REVENUE_PLACEHOLDER = "COMING IN LATER PHASE — revenue is not tracked and must not be fabricated."
IDENTITY_DISCLAIMER = (
    "Nova is an AI system/tool under AMICOR/owner authorization. "
    "Nova is not a human employee. External applications are not sent in Phase 1."
)


class NovaWorkError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _new_id(prefix: str) -> str:
    return prefix + uuid4().replace("-", "")[:12].upper()


def _can_see_org_wide(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


def _owner_filter(query, model, user: UserContext):
    if _can_see_org_wide(user):
        return query
    return query.filter(model.owner_user_id == user.user_id)


def _ensure() -> None:
    ensure_work_revenue_schema()


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    if isinstance(data, list):
        return [str(item) for item in data]
    return [str(data)]


def _dump_list(items: list[str] | None) -> str:
    return json.dumps(list(items or []))


def _safe_summary(text: str) -> str:
    cleaned = sanitize_untrusted(text)[:380]
    if SENSITIVE_RE.search(cleaned):
        return "Event recorded. Sensitive identity or secret values were omitted."
    return cleaned


def _parse_qual(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _record_audit(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    event_type: str,
    summary: str,
    ref_id: str | None = None,
) -> None:
    db.add(
        NovaWorkAuditEvent(
            event_id=_new_id("NWE-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            event_type=event_type,
            summary=_safe_summary(summary),
            ref_id=ref_id,
        )
    )


def _record_history(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    ref_type: str,
    ref_id: str,
    from_status: str | None,
    to_status: str,
    note: str | None = None,
) -> None:
    db.add(
        NovaWorkStatusHistory(
            history_id=_new_id("NWH-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            ref_type=ref_type,
            ref_id=ref_id,
            from_status=from_status,
            to_status=to_status,
            note=_safe_summary(note or to_status)[:400],
        )
    )


def _opp_query(db: Session, organization_id: str, user: UserContext):
    query = db.query(NovaWorkOpportunity).filter(NovaWorkOpportunity.organization_id == organization_id)
    return _owner_filter(query, NovaWorkOpportunity, user)


def _app_query(db: Session, organization_id: str, user: UserContext):
    query = db.query(NovaWorkApplication).filter(NovaWorkApplication.organization_id == organization_id)
    return _owner_filter(query, NovaWorkApplication, user)


def get_opportunity(db: Session, opportunity_id: str, *, organization_id: str, user: UserContext) -> NovaWorkOpportunity:
    _ensure()
    row = _opp_query(db, organization_id, user).filter(NovaWorkOpportunity.opportunity_id == opportunity_id).first()
    if row is None:
        raise NovaWorkError("Work opportunity not found", status_code=404)
    return row


def get_application(db: Session, application_id: str, *, organization_id: str, user: UserContext) -> NovaWorkApplication:
    _ensure()
    row = _app_query(db, organization_id, user).filter(NovaWorkApplication.application_id == application_id).first()
    if row is None:
        raise NovaWorkError("Work application not found", status_code=404)
    return row


def opportunity_out(row: NovaWorkOpportunity) -> OpportunityOut:
    return OpportunityOut(
        opportunity_id=row.opportunity_id,
        organization_id=row.organization_id,
        source=row.source,
        source_url=row.source_url,
        source_type=row.source_type,
        company_name=row.company_name,
        opportunity_title=row.opportunity_title,
        description=row.description,
        location=row.location,
        remote_status=row.remote_status,
        engagement_type=row.engagement_type,
        compensation_type=row.compensation_type,
        compensation_amount=row.compensation_amount,
        compensation_period=row.compensation_period,
        currency=row.currency,
        requirements=row.requirements,
        skills_required=_json_list(row.skills_required),
        credentials_required=_json_list(row.credentials_required),
        physical_presence_required=row.physical_presence_required,
        application_deadline=row.application_deadline,
        discovered_at=row.discovered_at,
        status=row.status,
        notes=row.notes,
        qualification_outcome=row.qualification_outcome,
        qualification=_parse_qual(row.qualification_json),
        follow_up_at=row.follow_up_at,
        interview_at=row.interview_at,
    )


def material_out(row: NovaWorkMaterial) -> MaterialOut:
    return MaterialOut(
        material_id=row.material_id,
        application_id=row.application_id,
        kind=row.kind,
        title=row.title,
        body=row.body,
        status=row.status,
        owner_input_required=row.owner_input_required,
    )


def owner_action_out(row: NovaWorkOwnerAction) -> OwnerActionOut:
    return OwnerActionOut(
        action_id=row.action_id,
        opportunity_id=row.opportunity_id,
        application_id=row.application_id,
        action_type=row.action_type,
        display_label=row.display_label,
        explanation=row.explanation,
        status=row.status,
    )


def application_out(db: Session, row: NovaWorkApplication) -> ApplicationOut:
    materials = (
        db.query(NovaWorkMaterial)
        .filter(
            NovaWorkMaterial.application_id == row.application_id,
            NovaWorkMaterial.organization_id == row.organization_id,
        )
        .order_by(NovaWorkMaterial.created_at.asc())
        .all()
    )
    actions = (
        db.query(NovaWorkOwnerAction)
        .filter(
            NovaWorkOwnerAction.application_id == row.application_id,
            NovaWorkOwnerAction.organization_id == row.organization_id,
        )
        .order_by(NovaWorkOwnerAction.created_at.asc())
        .all()
    )
    return ApplicationOut(
        application_id=row.application_id,
        opportunity_id=row.opportunity_id,
        organization_id=row.organization_id,
        applicant_party=row.applicant_party,
        approval_state=row.approval_state,
        approved_for_future_submission=row.approved_for_future_submission,
        externally_submitted=row.externally_submitted,
        manual_submission_recorded=row.manual_submission_recorded,
        follow_up_at=row.follow_up_at,
        interview_at=row.interview_at,
        notes=row.notes,
        materials=[material_out(item) for item in materials],
        owner_actions=[owner_action_out(item) for item in actions],
    )


def _opportunity_payload(row: NovaWorkOpportunity) -> dict[str, Any]:
    return {
        "opportunity_title": row.opportunity_title,
        "description": row.description,
        "requirements": row.requirements,
        "location": row.location,
        "skills_required": _json_list(row.skills_required),
        "credentials_required": _json_list(row.credentials_required),
        "physical_presence_required": row.physical_presence_required,
        "compensation_type": row.compensation_type,
        "compensation_amount": row.compensation_amount,
        "compensation_period": row.compensation_period,
        "company_name": row.company_name,
    }


def _create_opportunity_row(
    db: Session,
    payload: dict[str, Any],
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkOpportunity:
    physical = str(payload.get("physical_presence_required") or "unknown").lower()
    if physical not in {"true", "false", "unknown"}:
        physical = "unknown"
    source_type = str(payload.get("source_type") or "manual")
    row = NovaWorkOpportunity(
        opportunity_id=_new_id("NWO-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        source=str(payload.get("source") or "manual")[:80],
        source_url=sanitize_untrusted(payload.get("source_url")) or None,
        source_type=source_type[:40],
        company_name=sanitize_untrusted(payload.get("company_name"))[:220],
        opportunity_title=sanitize_untrusted(payload.get("opportunity_title"))[:220],
        description=sanitize_untrusted(payload.get("description")) or None,
        location=sanitize_untrusted(payload.get("location"))[:220] or None,
        remote_status=sanitize_untrusted(payload.get("remote_status"))[:40] or None,
        engagement_type=sanitize_untrusted(payload.get("engagement_type"))[:40] or None,
        compensation_type=sanitize_untrusted(payload.get("compensation_type"))[:40] or None,
        compensation_amount=payload.get("compensation_amount"),
        compensation_period=sanitize_untrusted(payload.get("compensation_period"))[:40] or None,
        currency=sanitize_untrusted(payload.get("currency"))[:12] or None,
        requirements=sanitize_untrusted(payload.get("requirements")) or None,
        skills_required=_dump_list(payload.get("skills_required") or []),
        credentials_required=_dump_list(payload.get("credentials_required") or []),
        physical_presence_required=physical,
        application_deadline=payload.get("application_deadline"),
        notes=sanitize_untrusted(payload.get("notes")) or None,
        status="DISCOVERED",
        discovered_at=now(),
    )
    db.add(row)
    db.flush()
    _record_history(
        db,
        organization_id=organization_id,
        user=user,
        ref_type="opportunity",
        ref_id=row.opportunity_id,
        from_status=None,
        to_status="DISCOVERED",
    )
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="OPPORTUNITY_CREATED",
        summary=f"Opportunity recorded: {row.opportunity_title}",
        ref_id=row.opportunity_id,
    )
    return row


def create_opportunity(
    db: Session,
    payload: OpportunityCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkOpportunity:
    _ensure()
    data = payload.model_dump()
    data["source"] = "manual"
    data["source_type"] = data.get("source_type") or "manual"
    row = _create_opportunity_row(db, data, organization_id=organization_id, user=user)
    db.commit()
    db.refresh(row)
    return row


def list_opportunities(db: Session, *, organization_id: str, user: UserContext) -> list[NovaWorkOpportunity]:
    _ensure()
    return (
        _opp_query(db, organization_id, user)
        .order_by(NovaWorkOpportunity.updated_at.desc())
        .all()
    )


def _apply_status(db: Session, row: NovaWorkOpportunity, new_status: str, user: UserContext, note: str | None = None) -> None:
    if new_status not in OPPORTUNITY_STATUSES:
        raise NovaWorkError("Unknown opportunity status")
    if new_status == row.status:
        return
    allowed = STATUS_TRANSITIONS.get(row.status, set())
    if new_status not in allowed:
        raise NovaWorkError(f"Cannot transition from {row.status} to {new_status}")
    previous = row.status
    row.status = new_status
    row.updated_at = now()
    _record_history(
        db,
        organization_id=row.organization_id,
        user=user,
        ref_type="opportunity",
        ref_id=row.opportunity_id,
        from_status=previous,
        to_status=new_status,
        note=note,
    )
    _record_audit(
        db,
        organization_id=row.organization_id,
        user=user,
        event_type="APPLICATION_STATUS_CHANGED",
        summary=f"Opportunity {row.opportunity_id} moved {previous} → {new_status}",
        ref_id=row.opportunity_id,
    )


def update_opportunity(
    db: Session,
    opportunity_id: str,
    payload: OpportunityUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkOpportunity:
    row = get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
    if payload.status:
        _apply_status(db, row, payload.status, user, payload.notes)
    if payload.notes is not None:
        row.notes = sanitize_untrusted(payload.notes)
    if payload.follow_up_at is not None:
        row.follow_up_at = payload.follow_up_at
    if payload.interview_at is not None:
        row.interview_at = payload.interview_at
        if payload.status is None and row.status in {"SUBMITTED", "FOLLOW_UP_DUE", "APPLICATION_PREPARED"}:
            _apply_status(db, row, "INTERVIEW", user, "Interview date recorded")
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row


def _upsert_owner_actions(
    db: Session,
    row: NovaWorkOpportunity,
    user: UserContext,
    action_types: list[str],
    *,
    application_id: str | None = None,
) -> None:
    existing = {
        item.action_type
        for item in db.query(NovaWorkOwnerAction)
        .filter(
            NovaWorkOwnerAction.organization_id == row.organization_id,
            NovaWorkOwnerAction.opportunity_id == row.opportunity_id,
            NovaWorkOwnerAction.status == "OPEN",
        )
        .all()
    }
    explanations = {
        "CAPTCHA": "A CAPTCHA or robot-check is indicated. Nova will not solve or bypass it.",
        "IDENTITY_VERIFICATION": "Identity verification must be completed by the owner. Nova will not impersonate a person.",
        "LIVE_INTERVIEW": "A live interview is indicated. A human must attend.",
        "LEGAL_SIGNATURE": "A legal signature is required. Nova cannot sign.",
        "CONTRACT_ACCEPTANCE": "Contract acceptance requires the owner. Nova will not accept contracts.",
        "BANK_INFORMATION": "Bank information is requested. Owner must handle this offline. Values are not stored here.",
        "TAX_INFORMATION": "Tax information is requested. Owner must handle this offline. Values are not stored here.",
        "SSN": "Government identity numbers are requested. Do not enter them here. Owner action only.",
        "BACKGROUND_CHECK": "A background check is indicated. Owner must complete any human identity steps.",
        "LICENSE_VERIFICATION": "A professional or driving license appears required. Nova has no verified license on file.",
        "PRICING_COMMITMENT": "A pricing or bid commitment is indicated. Owner must set price.",
        "FINANCIAL_COMMITMENT": "A financial commitment is indicated. Nova will not commit funds.",
        "LEGAL_CERTIFICATION": "A legal certification is indicated. Owner must certify.",
        "PLATFORM_REQUIRES_HUMAN": "The source appears to require a human on the platform.",
    }
    for action_type in action_types:
        if action_type not in OWNER_ACTION_TYPES or action_type in existing:
            continue
        db.add(
            NovaWorkOwnerAction(
                action_id=_new_id("NWAO-"),
                organization_id=row.organization_id,
                owner_user_id=user.user_id,
                opportunity_id=row.opportunity_id,
                application_id=application_id,
                action_type=action_type,
                display_label="OWNER ACTION REQUIRED",
                explanation=explanations.get(action_type, "Owner action is required. Nova will not bypass this control."),
                status="OPEN",
            )
        )
        safe_type = (
            "IDENTITY_STEP"
            if action_type in {"SSN", "BANK_INFORMATION", "TAX_INFORMATION"}
            else action_type
        )
        _record_audit(
            db,
            organization_id=row.organization_id,
            user=user,
            event_type="OWNER_ACTION_REQUIRED",
            summary=f"OWNER ACTION REQUIRED: {safe_type}",
            ref_id=row.opportunity_id,
        )


def qualify(
    db: Session,
    opportunity_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> tuple[NovaWorkOpportunity, dict[str, Any]]:
    row = get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
    result = qualify_opportunity(_opportunity_payload(row))
    row.qualification_outcome = result["outcome"]
    row.qualification_json = json.dumps(result)
    row.updated_at = now()
    target = OUTCOME_TO_STATUS.get(result["outcome"], "REVIEWING")
    if row.status in {"DISCOVERED", "REVIEWING", "QUALIFIED", "NOT_QUALIFIED", "OWNER_REVIEW"}:
        if row.status != target:
            try:
                _apply_status(db, row, target, user, f"Qualified as {result['outcome']}")
            except NovaWorkError:
                if row.status == "DISCOVERED" and target != "DISCOVERED":
                    _apply_status(db, row, "REVIEWING", user, "Qualification in progress")
                    if target != "REVIEWING":
                        _apply_status(db, row, target, user, f"Qualified as {result['outcome']}")
    _upsert_owner_actions(db, row, user, result.get("owner_actions") or [])
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="OPPORTUNITY_QUALIFIED",
        summary=f"Qualified {row.opportunity_id} as {result['outcome']}",
        ref_id=row.opportunity_id,
    )
    db.commit()
    db.refresh(row)
    return row, result


def qualification_out(opportunity_id: str, result: dict[str, Any]) -> QualificationOut:
    return QualificationOut(opportunity_id=opportunity_id, **{k: result[k] for k in QualificationOut.model_fields if k != "opportunity_id"})


def create_application(
    db: Session,
    payload: ApplicationCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkApplication:
    row = get_opportunity(db, payload.opportunity_id, organization_id=organization_id, user=user)
    if row.status in {"NOT_QUALIFIED", "CLOSED", "REJECTED"}:
        raise NovaWorkError("Cannot prepare an application for a closed or not-qualified opportunity")
    existing = (
        _app_query(db, organization_id, user)
        .filter(NovaWorkApplication.opportunity_id == row.opportunity_id)
        .first()
    )
    if existing is not None:
        raise NovaWorkError("An application workspace already exists for this opportunity", status_code=409)
    application = NovaWorkApplication(
        application_id=_new_id("NWA-"),
        opportunity_id=row.opportunity_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        applicant_party=payload.applicant_party,
        approval_state="DRAFT",
        notes=sanitize_untrusted(payload.notes) or None,
    )
    db.add(application)
    db.flush()
    drafts = generate_drafts(_opportunity_payload(row), applicant_party=payload.applicant_party)
    for draft in drafts:
        if draft["kind"] not in MATERIAL_KINDS:
            continue
        db.add(
            NovaWorkMaterial(
                material_id=_new_id("NWM-"),
                application_id=application.application_id,
                organization_id=organization_id,
                owner_user_id=user.user_id,
                kind=draft["kind"],
                title=draft["title"][:220],
                body=draft["body"],
                status="DRAFT",
                owner_input_required=bool(draft.get("owner_input_required")),
            )
        )
    if row.status in {"QUALIFIED", "OWNER_REVIEW", "APPROVED_TO_APPLY"}:
        _apply_status(db, row, "APPLICATION_PREPARED", user, "Application workspace created")
    elif row.status in {"DISCOVERED", "REVIEWING"}:
        _apply_status(db, row, "REVIEWING", user, "Application workspace created before qualification")
    _record_history(
        db,
        organization_id=organization_id,
        user=user,
        ref_type="application",
        ref_id=application.application_id,
        from_status=None,
        to_status="DRAFT",
    )
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="APPLICATION_DRAFT_CREATED",
        summary=f"Draft materials created for {row.opportunity_title}",
        ref_id=application.application_id,
    )
    db.commit()
    db.refresh(application)
    return application


def mark_ready_for_review(
    db: Session,
    application_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkApplication:
    application = get_application(db, application_id, organization_id=organization_id, user=user)
    if application.approval_state not in {"DRAFT", "NEEDS_CHANGES"}:
        raise NovaWorkError("Only DRAFT or NEEDS_CHANGES applications can be sent for owner review")
    previous = application.approval_state
    application.approval_state = "READY_FOR_OWNER_REVIEW"
    application.updated_at = now()
    _record_history(
        db,
        organization_id=organization_id,
        user=user,
        ref_type="application",
        ref_id=application.application_id,
        from_status=previous,
        to_status="READY_FOR_OWNER_REVIEW",
    )
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="APPLICATION_READY_FOR_REVIEW",
        summary="Application marked READY_FOR_OWNER_REVIEW",
        ref_id=application.application_id,
    )
    db.commit()
    db.refresh(application)
    return application


def decide_application(
    db: Session,
    application_id: str,
    payload: ApplicationDecision,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkApplication:
    application = get_application(db, application_id, organization_id=organization_id, user=user)
    if application.approval_state != "READY_FOR_OWNER_REVIEW":
        raise NovaWorkError("Owner decision requires READY_FOR_OWNER_REVIEW")
    if payload.decision not in {"APPROVED", "REJECTED", "NEEDS_CHANGES"}:
        raise NovaWorkError("Invalid owner decision")
    previous = application.approval_state
    application.approval_state = payload.decision
    application.notes = sanitize_untrusted(payload.notes) or application.notes
    application.approved_for_future_submission = payload.decision == "APPROVED"
    application.updated_at = now()
    if payload.decision == "APPROVED":
        opportunity = get_opportunity(db, application.opportunity_id, organization_id=organization_id, user=user)
        if opportunity.status in {"APPLICATION_PREPARED", "OWNER_REVIEW", "QUALIFIED"}:
            try:
                if opportunity.status != "APPROVED_TO_APPLY":
                    if opportunity.status == "APPLICATION_PREPARED":
                        pass
                    if opportunity.status in {"QUALIFIED", "OWNER_REVIEW"}:
                        _apply_status(db, opportunity, "APPROVED_TO_APPLY", user, "Owner approved for future submission")
                    elif opportunity.status == "APPLICATION_PREPARED":
                        # APPROVED_TO_APPLY is a prior state; keep APPLICATION_PREPARED after drafts exist.
                        pass
            except NovaWorkError:
                pass
        event_type = "OWNER_APPROVED_APPLICATION"
        summary = "Owner approved application for FUTURE submission only. Nothing was sent externally."
    elif payload.decision == "REJECTED":
        event_type = "OWNER_REJECTED_APPLICATION"
        summary = "Owner rejected the application draft."
        opportunity = get_opportunity(db, application.opportunity_id, organization_id=organization_id, user=user)
        if opportunity.status not in {"CLOSED", "REJECTED", "WON"}:
            try:
                _apply_status(db, opportunity, "CLOSED", user, "Owner rejected application")
            except NovaWorkError:
                pass
    else:
        event_type = "APPLICATION_STATUS_CHANGED"
        summary = "Owner requested changes. Materials remain DRAFT."
        application.approved_for_future_submission = False
    _record_history(
        db,
        organization_id=organization_id,
        user=user,
        ref_type="application",
        ref_id=application.application_id,
        from_status=previous,
        to_status=payload.decision,
    )
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type=event_type,
        summary=summary,
        ref_id=application.application_id,
    )
    db.commit()
    db.refresh(application)
    return application


def refuse_external_submission() -> None:
    raise NovaWorkError(
        "External application submission is not enabled in Phase 1. "
        "APPROVED means APPROVED_FOR_FUTURE_SUBMISSION only. Nothing was sent.",
        status_code=409,
    )


def record_manual_submission(
    db: Session,
    application_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkApplication:
    application = get_application(db, application_id, organization_id=organization_id, user=user)
    if application.approval_state != "APPROVED" or not application.approved_for_future_submission:
        raise NovaWorkError("Manual submission may be recorded only after owner APPROVED", status_code=409)
    if application.externally_submitted:
        raise NovaWorkError("Phase 1 does not send external applications", status_code=409)
    application.manual_submission_recorded = True
    application.updated_at = now()
    opportunity = get_opportunity(db, application.opportunity_id, organization_id=organization_id, user=user)
    if opportunity.status == "APPLICATION_PREPARED":
        _apply_status(db, opportunity, "SUBMITTED", user, "Owner recorded a manual submission. Nova did not send it.")
    elif opportunity.status == "APPROVED_TO_APPLY":
        _apply_status(db, opportunity, "APPLICATION_PREPARED", user, "Materials were already prepared")
        _apply_status(db, opportunity, "SUBMITTED", user, "Owner recorded a manual submission. Nova did not send it.")
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="APPLICATION_STATUS_CHANGED",
        summary="Manual submission recorded by owner. Nova did not contact the source.",
        ref_id=application.application_id,
    )
    db.commit()
    db.refresh(application)
    return application


def update_application_status(
    db: Session,
    application_id: str,
    payload: ApplicationStatusUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaWorkOpportunity:
    application = get_application(db, application_id, organization_id=organization_id, user=user)
    opportunity = get_opportunity(db, application.opportunity_id, organization_id=organization_id, user=user)
    _apply_status(db, opportunity, payload.status, user, payload.notes)
    if payload.follow_up_at is not None:
        application.follow_up_at = payload.follow_up_at
        opportunity.follow_up_at = payload.follow_up_at
    if payload.interview_at is not None:
        application.interview_at = payload.interview_at
        opportunity.interview_at = payload.interview_at
    if payload.notes is not None:
        application.notes = sanitize_untrusted(payload.notes)
    application.updated_at = now()
    opportunity.updated_at = now()
    db.commit()
    db.refresh(opportunity)
    return opportunity


def ingest_simulated(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    fixture_ids: list[str] | None = None,
) -> list[NovaWorkOpportunity]:
    _ensure()
    testing = os.getenv("TESTING", "").lower() == "true"
    runtime = os.getenv("RUNTIME_ENVIRONMENT", os.getenv("APP_ENV", "development")).lower()
    if not testing and runtime in {"production", "prod"}:
        raise NovaWorkError("Simulated opportunities are not allowed in production", status_code=403)
    provider = get_provider("simulated")
    created: list[NovaWorkOpportunity] = []
    for item in provider.ingest({"fixture_ids": fixture_ids} if fixture_ids else None):
        created.append(_create_opportunity_row(db, item, organization_id=organization_id, user=user))
    db.commit()
    for row in created:
        db.refresh(row)
    return created


def list_applications(db: Session, *, organization_id: str, user: UserContext) -> list[NovaWorkApplication]:
    _ensure()
    return _app_query(db, organization_id, user).order_by(NovaWorkApplication.updated_at.desc()).all()


def list_owner_actions(db: Session, *, organization_id: str, user: UserContext, open_only: bool = True) -> list[NovaWorkOwnerAction]:
    _ensure()
    query = db.query(NovaWorkOwnerAction).filter(NovaWorkOwnerAction.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkOwnerAction, user)
    if open_only:
        query = query.filter(NovaWorkOwnerAction.status == "OPEN")
    return query.order_by(NovaWorkOwnerAction.created_at.desc()).all()


def list_audit(db: Session, *, organization_id: str, user: UserContext) -> list[NovaWorkAuditEvent]:
    _ensure()
    query = db.query(NovaWorkAuditEvent).filter(NovaWorkAuditEvent.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkAuditEvent, user)
    return query.order_by(NovaWorkAuditEvent.created_at.desc()).limit(200).all()


def tracker(db: Session, opportunity_id: str, *, organization_id: str, user: UserContext) -> TrackerOut:
    opportunity = get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
    application_row = (
        _app_query(db, organization_id, user)
        .filter(NovaWorkApplication.opportunity_id == opportunity_id)
        .first()
    )
    application = application_out(db, application_row) if application_row else None
    actions = (
        db.query(NovaWorkOwnerAction)
        .filter(
            NovaWorkOwnerAction.organization_id == organization_id,
            NovaWorkOwnerAction.opportunity_id == opportunity_id,
        )
        .all()
    )
    history_rows = (
        db.query(NovaWorkStatusHistory)
        .filter(
            NovaWorkStatusHistory.organization_id == organization_id,
            NovaWorkStatusHistory.ref_id.in_(
                [opportunity_id] + ([application_row.application_id] if application_row else [])
            ),
        )
        .order_by(NovaWorkStatusHistory.created_at.asc())
        .all()
    )
    return TrackerOut(
        opportunity=opportunity_out(opportunity),
        application=application,
        approval_state=application.approval_state if application else None,
        application_status=opportunity.status,
        follow_up_at=opportunity.follow_up_at,
        interview_at=opportunity.interview_at,
        owner_actions=[owner_action_out(item) for item in actions],
        notes=opportunity.notes,
        status_history=[
            StatusHistoryOut(
                history_id=item.history_id,
                ref_type=item.ref_type,
                ref_id=item.ref_id,
                from_status=item.from_status,
                to_status=item.to_status,
                note=item.note,
                created_at=item.created_at,
            )
            for item in history_rows
        ],
    )


def _due(value: datetime | None) -> bool:
    if value is None:
        return False
    current = now()
    if value.tzinfo is None and current.tzinfo is not None:
        value = value.replace(tzinfo=current.tzinfo)
    return value <= current


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> DashboardOut:
    opportunities = list_opportunities(db, organization_id=organization_id, user=user)
    applications = [application_out(db, row) for row in list_applications(db, organization_id=organization_id, user=user)]
    actions = list_owner_actions(db, organization_id=organization_id, user=user)
    inbox = [opportunity_out(row) for row in opportunities if row.status in {"DISCOVERED", "REVIEWING"}]
    qualified = [opportunity_out(row) for row in opportunities if row.status in {"QUALIFIED", "OWNER_REVIEW", "APPROVED_TO_APPLY"}]
    follow_ups = [opportunity_out(row) for row in opportunities if row.status == "FOLLOW_UP_DUE" or _due(row.follow_up_at)]
    interviews = [opportunity_out(row) for row in opportunities if row.status == "INTERVIEW" or row.interview_at]
    won = [opportunity_out(row) for row in opportunities if row.status == "WON"]
    approvals = [item for item in applications if item.approval_state == "READY_FOR_OWNER_REVIEW"]
    return DashboardOut(
        counts={
            "work_opportunities": len(opportunities),
            "applications_needing_approval": len(approvals),
            "follow_ups_due": len(follow_ups),
            "interviews": len(interviews),
            "owner_action_required": len(actions),
            "work_won": len(won),
        },
        opportunity_inbox=inbox,
        qualified_work=qualified,
        applications=applications,
        owner_approvals=approvals,
        follow_ups=follow_ups,
        interviews=interviews,
        won_work=won,
        owner_actions=[owner_action_out(item) for item in actions],
        revenue_placeholder=REVENUE_PLACEHOLDER,
        identity_disclaimer=IDENTITY_DISCLAIMER,
    )


def today_summary(db: Session, *, organization_id: str, user: UserContext) -> TodaySummaryOut:
    dash = dashboard(db, organization_id=organization_id, user=user)
    return TodaySummaryOut(
        work_opportunities=dash.counts["work_opportunities"],
        applications_needing_approval=dash.counts["applications_needing_approval"],
        follow_ups_due=dash.counts["follow_ups_due"],
        interviews=dash.counts["interviews"],
        owner_action_required=dash.counts["owner_action_required"],
        work_won=dash.counts["work_won"],
    )


def capabilities() -> list[CapabilityOut]:
    return [CapabilityOut(**item) for item in list_capabilities()]


def providers() -> list[ProviderOut]:
    return [ProviderOut(**item) for item in list_providers()]


def verified_profile(applicant_party: str = "AMICOR") -> dict[str, Any]:
    return profile_snapshot(applicant_party=applicant_party)


def registry() -> dict[str, Any]:
    return registry_snapshot()
