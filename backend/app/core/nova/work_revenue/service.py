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
from app.core.nova.work_revenue.flags import engine_guardrails, EXTERNAL_SUBMISSION_ENABLED
from app.core.nova.work_revenue.lifecycle import (
    LIST_MAX_LIMIT,
    OPPORTUNITY_PRIORITIES,
    category_for_action,
    normalize_task_status,
    queue_status_for,
)
from app.core.nova.work_revenue.materials import generate_drafts, missing_owner_facts, owner_input_checklist, sanitize_untrusted
from app.core.nova.work_revenue.models import (
    NovaWorkApplication,
    NovaWorkAuditEvent,
    NovaWorkDeliverable,
    NovaWorkEngagement,
    NovaWorkMaterial,
    NovaWorkOpportunity,
    NovaWorkOwnerAction,
    NovaWorkStatusHistory,
    NovaWorkTask,
)
from app.core.nova.work_revenue.urls import UnsafeSourceUrl, validate_source_url
from app.core.nova.work_revenue.providers import get_provider, list_providers, opportunity_fingerprint
from app.core.nova.work_revenue.qualifier import qualify_opportunity
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.schemas import (
    MATERIAL_KINDS,
    ENGAGEMENT_STATUSES,
    OPPORTUNITY_STATUSES,
    OWNER_ACTION_TYPES,
    REVENUE_STATUSES,
    TASK_STATUSES,
    ApplicationCreate,
    ApplicationDecision,
    ApplicationOut,
    ApplicationStatusUpdate,
    AuditEventOut,
    CapabilityOut,
    DashboardOut,
    EngagementCreate,
    MaterialOut,
    OpportunityCreate,
    OpportunityDetailOut,
    OpportunityOut,
    OpportunityUpdate,
    OwnerActionOut,
    ProviderOut,
    QualificationOut,
    StatusHistoryOut,
    TaskCreate,
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

REVENUE_PLACEHOLDER = (
    "COMING IN LATER PHASE — owner-entered estimates only. Not earned revenue. "
    "Nova does not create invoices, charges, or payouts."
)
IDENTITY_DISCLAIMER = (
    "Nova is an AI system/tool under AMICOR/owner authorization. "
    "Nova is not a human employee. External applications are not sent in Phase 1."
)


class NovaWorkError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _safe_source_url(value: str | None) -> str | None:
    try:
        return validate_source_url(value)
    except UnsafeSourceUrl as exc:
        raise NovaWorkError(str(exc)) from exc


def _validate_amount(value: float | None, *, label: str) -> float | None:
    if value is None:
        return None
    if value < 0 or value > 1_000_000_000:
        raise NovaWorkError(f"{label} must be between 0 and 1000000000")
    return value


def _validate_date_range(start: datetime | None, end: datetime | None) -> None:
    if start and end and end < start:
        raise NovaWorkError("expected_end_date cannot be before expected_start_date")


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


_OWNER_AUDIT_EVENTS = {
    "OWNER_APPROVED_APPLICATION",
    "OWNER_REJECTED_APPLICATION",
    "OWNER_APPROVED",
    "OWNER_REJECTED",
    "RECEIPT_CONFIRMED",
    "REVENUE_RECEIVED_CONFIRMED",
    "DELIVERABLE_CONFIRMED",
    "OPPORTUNITY_ARCHIVED",
    "ARCHIVED",
}


def _record_audit(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    event_type: str,
    summary: str,
    ref_id: str | None = None,
    entity_type: str | None = None,
    actor_category: str | None = None,
    previous_state: str | None = None,
    new_state: str | None = None,
) -> None:
    actor = actor_category or ("OWNER" if event_type in _OWNER_AUDIT_EVENTS else "NOVA")
    db.add(
        NovaWorkAuditEvent(
            event_id=_new_id("NWE-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            event_type=event_type,
            summary=_safe_summary(summary),
            ref_id=ref_id,
            actor_category=actor,
            entity_type=entity_type,
            previous_state=previous_state,
            new_state=new_state,
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


def opportunity_out(
    row: NovaWorkOpportunity,
    *,
    application_state: str | None = None,
    owner_action_required: bool = False,
) -> OpportunityOut:
    qual = _parse_qual(row.qualification_json) or {}
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
        qualification=qual or None,
        follow_up_at=row.follow_up_at,
        interview_at=row.interview_at,
        updated_at=row.updated_at,
        fingerprint=getattr(row, "fingerprint", None),
        owner_action_required=owner_action_required,
        application_state=application_state,
        lifecycle_outcome=(qual or {}).get("lifecycle_outcome"),
        archived=bool(getattr(row, "archived", False)),
        estimated_value=getattr(row, "estimated_value", None),
        quoted_amount=getattr(row, "quoted_amount", None),
        contract_amount=getattr(row, "contract_amount", None),
        expected_payment_frequency=getattr(row, "expected_payment_frequency", None),
        expected_start_date=getattr(row, "expected_start_date", None),
        expected_end_date=getattr(row, "expected_end_date", None),
        revenue_status=getattr(row, "revenue_status", None) or "NONE",
        invoice_required=bool(getattr(row, "invoice_required", False)),
        owner_confirmed_payment_received=bool(getattr(row, "owner_confirmed_payment_received", False)),
        invoice_value=getattr(row, "invoice_value", None),
        amount_received=getattr(row, "amount_received", None),
        expenses=getattr(row, "expenses", None),
        estimated_net=getattr(row, "estimated_net", None),
        confirmed_net=getattr(row, "confirmed_net", None),
        payment_status=getattr(row, "payment_status", None) or "NONE",
        missing_owner_facts=missing_owner_facts(_opportunity_payload(row)),
        category=getattr(row, "category", None),
        priority=getattr(row, "priority", None) or "normal",
        tags=_json_list(getattr(row, "tags_json", None)),
        blocked_reason=getattr(row, "blocked_reason", None),
        archive_reason=getattr(row, "archive_reason", None),
        qualification_reason=getattr(row, "qualification_reason", None),
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
        revision=int(getattr(row, "revision", 1) or 1),
        parent_material_id=getattr(row, "parent_material_id", None),
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
        category=getattr(row, "category", None) or category_for_action(row.action_type),
        owner_notes=getattr(row, "owner_notes", None),
        engagement_id=getattr(row, "engagement_id", None),
        ref_type=getattr(row, "ref_type", None),
        ref_id=getattr(row, "ref_id", None),
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
        opportunity_title=(
            db.query(NovaWorkOpportunity.opportunity_title)
            .filter(
                NovaWorkOpportunity.opportunity_id == row.opportunity_id,
                NovaWorkOpportunity.organization_id == row.organization_id,
            )
            .scalar()
        ),
        materials=[material_out(item) for item in materials],
        owner_actions=[owner_action_out(item) for item in actions],
        owner_notes=getattr(row, "owner_notes", None),
        decided_at=getattr(row, "decided_at", None),
        externally_ready=False,
        approved_equals_submitted=False,
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
    title = sanitize_untrusted(payload.get("opportunity_title"))[:220]
    company = sanitize_untrusted(payload.get("company_name"))[:220]
    source_url = _safe_source_url(payload.get("source_url"))
    fingerprint = opportunity_fingerprint(
        organization_id=organization_id,
        company_name=company,
        opportunity_title=title,
        source_url=source_url,
    )
    duplicate = (
        db.query(NovaWorkOpportunity)
        .filter(
            NovaWorkOpportunity.organization_id == organization_id,
            NovaWorkOpportunity.fingerprint == fingerprint,
        )
        .first()
    )
    if duplicate is not None:
        raise NovaWorkError("Duplicate opportunity already recorded for this organization", status_code=409)
    estimated = payload.get("estimated_value")
    if estimated is None:
        estimated = payload.get("compensation_amount")
    row = NovaWorkOpportunity(
        opportunity_id=_new_id("NWO-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        source=str(payload.get("source") or "manual")[:80],
        source_url=source_url,
        source_type=source_type[:40],
        company_name=company,
        opportunity_title=title,
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
        fingerprint=fingerprint,
        estimated_value=estimated,
        expected_payment_frequency=sanitize_untrusted(payload.get("expected_payment_frequency"))[:40] or None,
        revenue_status="ESTIMATED" if estimated is not None else "NONE",
        invoice_required=False,
        owner_confirmed_payment_received=False,
        archived=False,
        category=sanitize_untrusted(payload.get("category"))[:40] or None,
        priority=(
            str(payload.get("priority") or "normal").strip().lower()
            if str(payload.get("priority") or "normal").strip().lower() in OPPORTUNITY_PRIORITIES
            else "normal"
        ),
        tags_json=_dump_list(payload.get("tags") or []),
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


def list_opportunities(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    view_filter: str | None = None,
    source: str | None = None,
    priority: str | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
    owner_action_required: bool | None = None,
) -> list[NovaWorkOpportunity]:
    _ensure()
    query = _opp_query(db, organization_id, user)
    if source:
        query = query.filter(NovaWorkOpportunity.source_type == source)
    if priority:
        query = query.filter(NovaWorkOpportunity.priority == priority)
    sort_map = {
        "updated_at": NovaWorkOpportunity.updated_at,
        "discovered_at": NovaWorkOpportunity.discovered_at,
        "deadline": NovaWorkOpportunity.application_deadline,
        "estimated_value": NovaWorkOpportunity.estimated_value,
        "company_name": NovaWorkOpportunity.company_name,
        "title": NovaWorkOpportunity.opportunity_title,
        "priority": NovaWorkOpportunity.priority,
    }
    sort_col = sort_map.get(sort, NovaWorkOpportunity.updated_at)
    query = query.order_by(sort_col.asc() if order == "asc" else sort_col.desc())
    rows = query.limit(LIST_MAX_LIMIT).all()
    apps = {item.opportunity_id: item for item in list_applications(db, organization_id=organization_id, user=user)}
    actions = {
        item.opportunity_id
        for item in list_owner_actions(db, organization_id=organization_id, user=user)
        if item.opportunity_id
    }
    selected: list[NovaWorkOpportunity] = []
    for row in rows:
        app = apps.get(row.opportunity_id)
        if view_filter and not _matches_view(row, app, actions, view_filter):
            continue
        if owner_action_required is True and row.opportunity_id not in actions:
            continue
        if owner_action_required is False and row.opportunity_id in actions:
            continue
        selected.append(row)
    start = max(int(offset or 0), 0)
    cap = LIST_MAX_LIMIT if limit is None else max(1, min(int(limit), LIST_MAX_LIMIT))
    return selected[start:start + cap]


def _matches_view(
    row: NovaWorkOpportunity,
    app: NovaWorkApplication | None,
    actions: set[str],
    view_filter: str,
) -> bool:
    archived = bool(getattr(row, "archived", False))
    if view_filter in {"new", "discovered"}:
        return row.status == "DISCOVERED" and not archived
    if view_filter == "needs_review":
        return row.status in {"REVIEWING", "OWNER_REVIEW"}
    if view_filter == "qualified":
        return (
            row.qualification_outcome in {"NOVA_CAN_PERFORM", "NOVA_WITH_OWNER_REVIEW"}
            or row.status in {"QUALIFIED", "OWNER_REVIEW", "APPROVED_TO_APPLY", "APPLICATION_PREPARED"}
        )
    if view_filter == "not_qualified":
        return row.status == "NOT_QUALIFIED" or row.qualification_outcome in {"NOT_SUITABLE", "INSUFFICIENT_INFORMATION"}
    if view_filter == "owner_action":
        return row.opportunity_id in actions
    if view_filter == "missing_information":
        return row.qualification_outcome == "INSUFFICIENT_INFORMATION" or bool(missing_owner_facts(_opportunity_payload(row)))
    if view_filter == "draft_ready":
        return app is not None and app.approval_state in {"DRAFT", "READY_FOR_OWNER_REVIEW", "NEEDS_CHANGES"}
    if view_filter == "approved":
        return app is not None and app.approved_for_future_submission
    if view_filter == "submitted" or view_filter == "manually_submitted":
        return (app is not None and app.manual_submission_recorded) or row.status == "SUBMITTED"
    if view_filter == "active":
        return row.status in {"APPLICATION_PREPARED", "SUBMITTED", "FOLLOW_UP_DUE", "INTERVIEW", "OFFER"}
    if view_filter == "won":
        return row.status == "WON"
    if view_filter == "lost":
        return row.status in {"REJECTED", "CLOSED"} and row.status != "WON"
    if view_filter == "rejected":
        return row.status == "REJECTED" or (app is not None and app.approval_state == "REJECTED")
    if view_filter == "archived":
        return archived or row.status in {"CLOSED", "REJECTED"}
    if view_filter == "qualifying":
        return row.status in {"DISCOVERED", "REVIEWING"} or row.qualification_outcome == "INSUFFICIENT_INFORMATION"
    if view_filter == "blocked":
        return bool(getattr(row, "blocked_reason", None)) or row.status == "OWNER_REVIEW"
    if view_filter == "ready":
        return row.status in {"QUALIFIED", "APPROVED_TO_APPLY", "APPLICATION_PREPARED"} and row.opportunity_id not in actions
    if view_filter == "in_progress":
        return row.status in {"APPLICATION_PREPARED", "SUBMITTED", "FOLLOW_UP_DUE", "INTERVIEW", "OFFER"}
    return False


def list_opportunity_outs(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    view_filter: str | None = None,
    source: str | None = None,
    priority: str | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
    owner_action_required: bool | None = None,
) -> list[OpportunityOut]:
    rows = list_opportunities(
        db,
        organization_id=organization_id,
        user=user,
        view_filter=view_filter,
        source=source,
        priority=priority,
        sort=sort,
        order=order,
        limit=limit,
        offset=offset,
        owner_action_required=owner_action_required,
    )
    apps_map = {item.opportunity_id: item for item in list_applications(db, organization_id=organization_id, user=user)}
    action_ids = {
        item.opportunity_id
        for item in list_owner_actions(db, organization_id=organization_id, user=user)
        if item.opportunity_id
    }
    return [_enriched_out(row, apps_map, action_ids) for row in rows]


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
    if payload.archived is True:
        row.archived = True
        if payload.archive_reason is not None:
            row.archive_reason = sanitize_untrusted(payload.archive_reason) or row.archive_reason
        _record_audit(
            db,
            organization_id=row.organization_id,
            user=user,
            event_type="OPPORTUNITY_ARCHIVED",
            summary=f"Owner archived {row.opportunity_id}",
            ref_id=row.opportunity_id,
        )
        if row.status not in {"CLOSED", "REJECTED", "WON"}:
            try:
                _apply_status(db, row, "CLOSED", user, "Owner archived opportunity")
            except NovaWorkError:
                pass
    start = payload.expected_start_date if payload.expected_start_date is not None else row.expected_start_date
    end = payload.expected_end_date if payload.expected_end_date is not None else row.expected_end_date
    _validate_date_range(start, end)
    for field_name in ("estimated_value", "quoted_amount", "contract_amount", "invoice_value", "amount_received", "expenses"):
        incoming = getattr(payload, field_name, None)
        if incoming is not None:
            setattr(row, field_name, _validate_amount(incoming, label=field_name))
    if payload.expected_payment_frequency is not None:
        row.expected_payment_frequency = sanitize_untrusted(payload.expected_payment_frequency)[:40]
    if payload.expected_start_date is not None:
        row.expected_start_date = payload.expected_start_date
    if payload.expected_end_date is not None:
        row.expected_end_date = payload.expected_end_date
    previous_revenue = row.revenue_status
    if payload.revenue_status is not None:
        if payload.revenue_status not in REVENUE_STATUSES:
            raise NovaWorkError("Unknown revenue status")
        if payload.revenue_status in {"OWNER_CONFIRMED_RECEIVED", "RECEIVED"} and not (
            payload.owner_confirmed_payment_received or row.owner_confirmed_payment_received
        ):
            raise NovaWorkError("Payment received may only be marked with owner confirmation")
        row.revenue_status = payload.revenue_status
        if previous_revenue != row.revenue_status:
            _record_audit(
                db,
                organization_id=row.organization_id,
                user=user,
                event_type="REVENUE_STATUS_CHANGED",
                summary=f"Revenue status {previous_revenue} → {row.revenue_status}. Not an actual payment.",
                ref_id=row.opportunity_id,
            )
    if payload.payment_status is not None:
        if payload.payment_status in {"RECEIVED", "OWNER_CONFIRMED_RECEIVED"} and not (
            payload.owner_confirmed_payment_received or row.owner_confirmed_payment_received
        ):
            raise NovaWorkError("Payment received may only be marked with owner confirmation")
        row.payment_status = payload.payment_status
    if payload.invoice_required is not None:
        row.invoice_required = payload.invoice_required
    if payload.owner_confirmed_payment_received is True:
        row.owner_confirmed_payment_received = True
        row.revenue_status = "OWNER_CONFIRMED_RECEIVED"
        row.payment_status = "OWNER_CONFIRMED_RECEIVED"
        _record_audit(
            db,
            organization_id=row.organization_id,
            user=user,
            event_type="RECEIPT_CONFIRMED",
            summary="Owner confirmed a receipt. Nova did not collect payment.",
            ref_id=row.opportunity_id,
        )
    elif payload.owner_confirmed_payment_received is False:
        row.owner_confirmed_payment_received = False
    if payload.category is not None:
        row.category = sanitize_untrusted(payload.category)[:40] or None
    if payload.priority is not None:
        token = str(payload.priority).strip().lower()
        row.priority = token if token in OPPORTUNITY_PRIORITIES else row.priority
    if payload.tags is not None:
        row.tags_json = _dump_list(payload.tags)
    if payload.blocked_reason is not None:
        row.blocked_reason = sanitize_untrusted(payload.blocked_reason) or None
    if payload.archive_reason is not None:
        row.archive_reason = sanitize_untrusted(payload.archive_reason) or None
    gross = row.contract_amount if row.contract_amount is not None else row.quoted_amount
    if gross is None:
        gross = row.estimated_value
    expenses = row.expenses or 0
    if gross is not None:
        row.estimated_net = gross - expenses
        row.confirmed_net = (row.amount_received or 0) - expenses if row.owner_confirmed_payment_received else None
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
        "CAPTCHA": "OWNER ACTION REQUIRED: CAPTCHA. Nova will not solve or bypass it.",
        "IDENTITY_VERIFICATION": "OWNER ACTION REQUIRED: identity verification. Nova will not impersonate a person.",
        "LIVE_INTERVIEW": "OWNER ACTION REQUIRED: live interview. A human must attend.",
        "PHONE_CALL": "OWNER ACTION REQUIRED: phone call. Nova cannot place the call.",
        "LIVE_MEETING": "OWNER ACTION REQUIRED: live meeting. A human must attend.",
        "LEGAL_SIGNATURE": "OWNER ACTION REQUIRED: legal signature. Nova cannot sign.",
        "CONTRACT_ACCEPTANCE": "OWNER ACTION REQUIRED: contract acceptance. Nova will not accept contracts.",
        "BANK_INFORMATION": "OWNER ACTION REQUIRED: banking/payout setup. Do not enter bank values here.",
        "PAYOUT_SETUP": "OWNER ACTION REQUIRED: payout setup. Owner must complete this offline.",
        "TAX_INFORMATION": "OWNER ACTION REQUIRED: tax form. Do not enter tax identifiers here.",
        "SSN": "OWNER ACTION REQUIRED: government identity numbers. Do not enter them here.",
        "BACKGROUND_CHECK": "OWNER ACTION REQUIRED: background check. Owner must complete human identity steps.",
        "LICENSE_VERIFICATION": "OWNER ACTION REQUIRED: license verification. Nova has no verified license on file.",
        "PRICING_COMMITMENT": "OWNER ACTION REQUIRED: pricing commitment. Owner must set price.",
        "FINANCIAL_COMMITMENT": "OWNER ACTION REQUIRED: financial commitment. Nova will not commit funds.",
        "LEGAL_CERTIFICATION": "OWNER ACTION REQUIRED: legal certification. Owner must certify.",
        "ACCOUNT_CREATION": "OWNER ACTION REQUIRED: account creation on an external portal.",
        "PLATFORM_REQUIRES_HUMAN": "OWNER ACTION REQUIRED: the source appears to require a human on the platform.",
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
                category=category_for_action(action_type),
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
    result["qualified_at"] = now().isoformat()
    row.qualification_outcome = result["outcome"]
    row.qualification_json = json.dumps(result)
    row.qualification_reason = (result.get("reasons") or [result.get("decision") or ""])[0][:400]
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
    payload = {}
    for key in QualificationOut.model_fields:
        if key == "opportunity_id":
            continue
        if key in result:
            payload[key] = result[key]
    return QualificationOut(opportunity_id=opportunity_id, **payload)


def refuse_external_submission() -> None:
    if EXTERNAL_SUBMISSION_ENABLED:
        raise NovaWorkError("External submission flag is true but no live adapter is implemented", status_code=409)
    raise NovaWorkError(
        "External application submission is not enabled in Phase 1. "
        "APPROVED means APPROVED_FOR_FUTURE_SUBMISSION only. Nothing was sent.",
        status_code=409,
    )


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
                revision=1,
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
        entity_type="application",
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
    if application.approval_state == "APPROVED" and payload.decision == "APPROVED":
        raise NovaWorkError("Application is already approved for future submission", status_code=409)
    if application.approval_state != "READY_FOR_OWNER_REVIEW":
        raise NovaWorkError("Owner decision requires READY_FOR_OWNER_REVIEW")
    if payload.decision not in {"APPROVED", "REJECTED", "NEEDS_CHANGES"}:
        raise NovaWorkError("Invalid owner decision")
    previous = application.approval_state
    application.approval_state = payload.decision
    application.notes = sanitize_untrusted(payload.notes) or application.notes
    application.owner_notes = sanitize_untrusted(payload.notes) or getattr(application, "owner_notes", None)
    application.decided_at = now()
    application.approved_for_future_submission = payload.decision == "APPROVED"
    application.externally_submitted = False
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
        entity_type="application",
        actor_category="OWNER",
    )
    db.commit()
    db.refresh(application)
    return application


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
    if application.manual_submission_recorded:
        raise NovaWorkError("Manual submission already recorded", status_code=409)
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
        try:
            created.append(_create_opportunity_row(db, item, organization_id=organization_id, user=user))
        except NovaWorkError as exc:
            if exc.status_code == 409:
                continue
            raise
    db.commit()
    for row in created:
        db.refresh(row)
    return created


def list_applications(db: Session, *, organization_id: str, user: UserContext, limit: int | None = None) -> list[NovaWorkApplication]:
    _ensure()
    from app.core.nova.work_revenue.lifecycle import clamp_list_limit

    return (
        _app_query(db, organization_id, user)
        .order_by(NovaWorkApplication.updated_at.desc())
        .limit(clamp_list_limit(limit, default=LIST_MAX_LIMIT))
        .all()
    )


def list_owner_actions(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    open_only: bool = True,
    limit: int | None = None,
) -> list[NovaWorkOwnerAction]:
    _ensure()
    from app.core.nova.work_revenue.lifecycle import clamp_list_limit

    query = db.query(NovaWorkOwnerAction).filter(NovaWorkOwnerAction.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkOwnerAction, user)
    if open_only:
        query = query.filter(NovaWorkOwnerAction.status == "OPEN")
    return query.order_by(NovaWorkOwnerAction.created_at.desc()).limit(clamp_list_limit(limit, default=LIST_MAX_LIMIT)).all()


def list_audit(db: Session, *, organization_id: str, user: UserContext, limit: int | None = None) -> list[NovaWorkAuditEvent]:
    _ensure()
    query = db.query(NovaWorkAuditEvent).filter(NovaWorkAuditEvent.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkAuditEvent, user)
    cap = LIST_MAX_LIMIT if limit is None else max(1, min(int(limit), LIST_MAX_LIMIT))
    return query.order_by(NovaWorkAuditEvent.created_at.desc()).limit(cap).all()


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


def _application_state_label(app: NovaWorkApplication | None) -> str | None:
    if app is None:
        return None
    if app.manual_submission_recorded:
        return "submitted_externally_recorded"
    if app.approved_for_future_submission:
        return "approved_for_future_submission"
    return app.approval_state


def _enriched_out(
    row: NovaWorkOpportunity,
    apps: dict[str, NovaWorkApplication],
    action_ids: set[str],
) -> OpportunityOut:
    return opportunity_out(
        row,
        application_state=_application_state_label(apps.get(row.opportunity_id)),
        owner_action_required=row.opportunity_id in action_ids,
    )


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> DashboardOut:
    opportunities = list_opportunities(db, organization_id=organization_id, user=user)
    app_rows = list_applications(db, organization_id=organization_id, user=user)
    applications = [application_out(db, row) for row in app_rows]
    apps_map = {row.opportunity_id: row for row in app_rows}
    actions = list_owner_actions(db, organization_id=organization_id, user=user)
    action_ids = {item.opportunity_id for item in actions if item.opportunity_id}
    outs = [_enriched_out(row, apps_map, action_ids) for row in opportunities]
    inbox = [item for item in outs if item.status in {"DISCOVERED", "REVIEWING"}]
    qualified = [item for item in outs if item.status in {"QUALIFIED", "OWNER_REVIEW", "APPROVED_TO_APPLY"}]
    follow_ups = [
        _enriched_out(row, apps_map, action_ids)
        for row in opportunities
        if row.status == "FOLLOW_UP_DUE" or _due(row.follow_up_at)
    ]
    interviews = [
        _enriched_out(row, apps_map, action_ids)
        for row in opportunities
        if row.status == "INTERVIEW" or row.interview_at
    ]
    won = [item for item in outs if item.status == "WON"]
    archived = [item for item in outs if item.archived or item.status in {"CLOSED", "REJECTED"}]
    approvals = [item for item in applications if item.approval_state == "READY_FOR_OWNER_REVIEW"]
    draft_ready = [item for item in applications if item.approval_state in {"DRAFT", "READY_FOR_OWNER_REVIEW"}]
    approved = [item for item in applications if item.approved_for_future_submission]
    submitted = [item for item in outs if item.status == "SUBMITTED" or item.application_state == "submitted_externally_recorded"]
    needs_owner = [item for item in outs if item.owner_action_required or item.missing_owner_facts]
    lost = [item for item in outs if item.status in {"REJECTED", "CLOSED"}]
    active = [item for item in outs if item.status in {"APPLICATION_PREPARED", "SUBMITTED", "FOLLOW_UP_DUE", "INTERVIEW", "OFFER"}]
    missing_info = [item for item in outs if item.qualification_outcome == "INSUFFICIENT_INFORMATION"]
    pipeline = sum((item.estimated_value or 0) for item in outs if not item.owner_confirmed_payment_received)
    contracted = sum((item.contract_amount or 0) for item in outs)
    received = sum((item.amount_received or 0) for item in outs if item.owner_confirmed_payment_received)
    engagement_rows = list_engagements(db, organization_id=organization_id, user=user)
    pending_deliverables = (
        _owner_filter(
            db.query(NovaWorkDeliverable).filter(NovaWorkDeliverable.organization_id == organization_id),
            NovaWorkDeliverable,
            user,
        )
        .filter(NovaWorkDeliverable.owner_confirmed_delivered.is_(False))
        .count()
    )
    from app.core.nova.work_revenue.managed import completion_counts, owner_fact_catalog, reconciliation

    extra = completion_counts(db, organization_id=organization_id, user=user)
    recon = reconciliation(db, organization_id=organization_id, user=user)
    fact_ready = (owner_fact_catalog(db, organization_id=organization_id, user=user) or {}).get("readiness") or {}
    return DashboardOut(
        counts={
            "work_opportunities": len(opportunities),
            "opportunities_found": len(opportunities),
            "new": len([item for item in outs if item.status == "DISCOVERED"]),
            "needs_review": len([item for item in outs if item.status in {"REVIEWING", "OWNER_REVIEW"}]),
            "qualified": len(qualified),
            "not_qualified": len([item for item in outs if item.status == "NOT_QUALIFIED"]),
            "needs_owner_input": len(needs_owner),
            "missing_information": len(missing_info),
            "draft_ready": len(draft_ready),
            "approved_for_future_submission": len(approved),
            "submitted": len(submitted),
            "active_work": len(active),
            "closed": len(archived),
            "lost": len(lost),
            "applications_needing_approval": len(approvals),
            "follow_ups_due": len(follow_ups),
            "interviews": len(interviews),
            "owner_action_required": len(actions),
            "work_won": len(won),
            "active_engagements": len([item for item in engagement_rows if item["status"] in {"NOT_STARTED", "NEW", "READY", "ACTIVE"}]),
            "blocked_engagements": len([item for item in engagement_rows if item["status"] in {"BLOCKED", "OWNER_ACTION_REQUIRED"} or item.get("blockers")]),
            "tasks_due": sum(
                1
                for item in engagement_rows
                for task in item.get("tasks") or []
                if task.get("status") not in {"COMPLETE", "CANCELLED"}
            ),
            "deliverables_pending": int(pending_deliverables or 0),
            "recurring_overdue": extra["recurring_overdue"],
            "reports_awaiting_review": extra["reports_awaiting_review"],
            "invoice_support_drafts": extra["invoice_support_drafts"],
            "blocked_work": extra["blocked_work"],
            "facts_required": int(fact_ready.get("total_required_facts") or 0),
            "facts_provided": int(fact_ready.get("provided_facts") or 0),
            "facts_verified": int(fact_ready.get("verified_facts") or 0),
            "facts_missing": int(fact_ready.get("missing_facts") or 0),
            "facts_expired": int(fact_ready.get("expired_facts") or 0),
            "facts_readiness_percent": int(fact_ready.get("percentage_complete") or 0),
        },
        opportunity_inbox=inbox,
        qualified_work=qualified,
        applications=applications,
        owner_approvals=approvals,
        follow_ups=follow_ups,
        interviews=interviews,
        won_work=won,
        owner_actions=[owner_action_out(item) for item in actions],
        rejected_or_archived=archived,
        opportunity_list=outs,
        engagements=engagement_rows,
        revenue_summary={
            "estimated_pipeline": pipeline,
            "quoted_pipeline": sum((item.quoted_amount or 0) for item in outs),
            "contracted_value": contracted,
            "owner_confirmed_received": received,
            "awaiting_invoice": recon.get("awaiting_invoice") or 0,
            "manually_recorded_invoice": recon.get("manually_recorded_invoice") or 0,
            "awaiting_owner_payment_confirmation": recon.get("awaiting_owner_payment_confirmation") or 0,
            "disclaimer": "Estimated pipeline is not received revenue. Nova does not collect payment. ESTIMATED != CONTRACTED. CONTRACTED != INVOICED. INVOICED != RECEIVED.",
        },
        guardrails=engine_guardrails(),
        revenue_placeholder=REVENUE_PLACEHOLDER,
        identity_disclaimer=IDENTITY_DISCLAIMER,
    )


def today_cards(counts: dict[str, int]) -> list[dict[str, Any]]:
    specs = (
        ("work_opportunities", "WORK OPPORTUNITIES"),
        ("qualified", "QUALIFIED"),
        ("needs_owner_input", "NEEDS OWNER INPUT"),
        ("draft_ready", "DRAFT READY"),
        ("approved_for_future_submission", "APPROVED FOR FUTURE SUBMISSION"),
        ("submitted", "SUBMITTED"),
        ("closed", "CLOSED"),
        ("applications_needing_approval", "APPLICATIONS NEEDING APPROVAL"),
        ("follow_ups_due", "FOLLOW-UPS DUE"),
        ("interviews", "INTERVIEWS"),
        ("owner_action_required", "OWNER ACTION REQUIRED"),
        ("work_won", "WORK WON"),
        ("tasks_due", "TASKS DUE"),
        ("active_engagements", "ACTIVE WORK"),
        ("recurring_overdue", "RECURRING OVERDUE"),
        ("reports_awaiting_review", "REPORTS AWAITING REVIEW"),
        ("invoice_support_drafts", "INVOICE-SUPPORT DRAFTS"),
        ("blocked_work", "BLOCKED WORK"),
    )
    return [
        {"key": key, "label": label, "count": int(counts.get(key) or 0), "href": "/nova/work"}
        for key, label in specs
    ]


def _today_source_counts(opportunities: list[OpportunityOut]) -> dict[str, int]:
    counts = {"manual": 0, "simulated": 0, "other": 0}
    for item in opportunities:
        kind = str(item.source_type or item.source or "manual").strip().lower()
        if kind == "simulated":
            counts["simulated"] += 1
        elif kind == "manual":
            counts["manual"] += 1
        else:
            counts["other"] += 1
    return counts


def _today_approval_states(applications: list[ApplicationOut]) -> dict[str, int]:
    counts = {"draft": 0, "ready_for_review": 0, "approved": 0, "submitted": 0}
    for item in applications:
        if item.manual_submission_recorded:
            counts["submitted"] += 1
        elif item.approved_for_future_submission or item.approval_state == "APPROVED":
            counts["approved"] += 1
        elif item.approval_state == "READY_FOR_OWNER_REVIEW":
            counts["ready_for_review"] += 1
        elif item.approval_state == "DRAFT":
            counts["draft"] += 1
    return counts


def _today_active_tasks(engagements: list[dict[str, Any]]) -> int:
    total = 0
    for item in engagements:
        if item.get("status") not in {"NOT_STARTED", "ACTIVE"}:
            continue
        for task in item.get("tasks") or []:
            if task.get("status") != "COMPLETE":
                total += 1
    return total


def today_summary(db: Session, *, organization_id: str, user: UserContext) -> TodaySummaryOut:
    dash = dashboard(db, organization_id=organization_id, user=user)
    guards = dash.guardrails or engine_guardrails()
    revenue = dict(dash.revenue_summary or {})
    pending_deliverables = (
        _owner_filter(
            db.query(NovaWorkDeliverable).filter(NovaWorkDeliverable.organization_id == organization_id),
            NovaWorkDeliverable,
            user,
        )
        .filter(NovaWorkDeliverable.owner_confirmed_delivered.is_(False))
        .count()
    )
    return TodaySummaryOut(
        work_opportunities=dash.counts["work_opportunities"],
        applications_needing_approval=dash.counts["applications_needing_approval"],
        follow_ups_due=dash.counts["follow_ups_due"],
        interviews=dash.counts["interviews"],
        owner_action_required=dash.counts["owner_action_required"],
        work_won=dash.counts["work_won"],
        qualified=dash.counts["qualified"],
        needs_owner_input=dash.counts["needs_owner_input"],
        draft_ready=dash.counts["draft_ready"],
        approved_for_future_submission=dash.counts["approved_for_future_submission"],
        submitted=dash.counts["submitted"],
        closed=dash.counts["closed"],
        cards=today_cards(dash.counts),
        source_counts=_today_source_counts(dash.opportunity_list),
        approval_states=_today_approval_states(dash.applications),
        active_engagements=int(dash.counts.get("active_engagements") or 0),
        active_tasks=_today_active_tasks(dash.engagements),
        revenue_summary=revenue,
        guardrails=guards,
        opportunity_mode="manual_simulated_only",
        live_discovery_enabled=bool(guards.get("LIVE_DISCOVERY_ENABLED")),
        external_submission_enabled=bool(guards.get("EXTERNAL_SUBMISSION_ENABLED")),
        financial_actions_enabled=bool(guards.get("FINANCIAL_ACTIONS_ENABLED")),
        revenue_disclaimer=str(revenue.get("disclaimer") or dash.revenue_placeholder or REVENUE_PLACEHOLDER),
        tasks_due=int(dash.counts.get("tasks_due") or 0),
        deliverables_pending=int(pending_deliverables or 0),
        quoted_pipeline=float(revenue.get("quoted_pipeline") or 0),
        contracted_revenue=float(revenue.get("contracted_value") or 0),
        recurring_overdue=int(dash.counts.get("recurring_overdue") or 0),
        reports_awaiting_review=int(dash.counts.get("reports_awaiting_review") or 0),
        invoice_support_drafts=int(dash.counts.get("invoice_support_drafts") or 0),
        blocked_work=int(dash.counts.get("blocked_work") or 0),
        owner_confirmed_received=float(revenue.get("owner_confirmed_received") or 0),
    )


def opportunity_detail(
    db: Session,
    opportunity_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> OpportunityDetailOut:
    tracked = tracker(db, opportunity_id, organization_id=organization_id, user=user)
    qual = tracked.opportunity.qualification or {}
    engagement = next(
        (
            item
            for item in list_engagements(db, organization_id=organization_id, user=user)
            if item.get("opportunity_id") == opportunity_id
        ),
        None,
    )
    return OpportunityDetailOut(
        tracker=tracked,
        missing_owner_facts=tracked.opportunity.missing_owner_facts,
        owner_input_checklist=owner_input_checklist(_opportunity_payload(
            get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
        )),
        work_split=qual.get("work_split") or {},
        engagement=engagement,
        source_url_display=tracked.opportunity.source_url,
        source_url_fetched=False,
        revenue_disclaimer=REVENUE_PLACEHOLDER,
        guardrails=engine_guardrails(),
    )


def _engagement_out(row: NovaWorkEngagement, tasks: list[NovaWorkTask] | None = None) -> dict[str, Any]:
    return {
        "engagement_id": row.engagement_id,
        "opportunity_id": row.opportunity_id,
        "client_name": row.client_name,
        "service": row.service,
        "frequency": row.frequency,
        "status": row.status,
        "queue_status": queue_status_for(row.status),
        "expected_payment": row.expected_payment,
        "payment_status": row.payment_status,
        "start_date": row.start_date.isoformat() if row.start_date else None,
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "notes": row.notes,
        "title": getattr(row, "title", None) or row.service,
        "service_type": getattr(row, "service_type", None),
        "agreed_value": getattr(row, "agreed_value", None),
        "estimated_revenue": getattr(row, "estimated_revenue", None) or row.expected_payment,
        "quoted_revenue": getattr(row, "quoted_revenue", None),
        "contracted_revenue": getattr(row, "contracted_revenue", None),
        "received_revenue": getattr(row, "received_revenue", None),
        "risks": getattr(row, "risks", None),
        "blockers": getattr(row, "blockers", None),
        "priority": getattr(row, "priority", None) or "normal",
        "source": getattr(row, "source", None),
        "due_date": row.due_date.isoformat() if getattr(row, "due_date", None) else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "organization_id": row.organization_id,
        "owner_user_id": row.owner_user_id,
        "tasks": [
            {
                "task_id": item.task_id,
                "title": item.title,
                "description": getattr(item, "description", None),
                "responsible_party": item.responsible_party,
                "classification": item.classification,
                "status": item.status,
                "priority": item.priority,
                "required_owner_input": item.required_owner_input,
                "deliverable": item.deliverable,
                "review_required": item.review_required,
                "depends_on_task_id": getattr(item, "depends_on_task_id", None),
                "blocked_reason": getattr(item, "blocked_reason", None),
                "completed_at": item.completed_at.isoformat() if getattr(item, "completed_at", None) else None,
                "owner_notes": getattr(item, "owner_notes", None),
                "due_date": item.due_date.isoformat() if item.due_date else None,
            }
            for item in (tasks or [])
        ],
    }


def list_engagements(db: Session, *, organization_id: str, user: UserContext) -> list[dict[str, Any]]:
    _ensure()
    query = db.query(NovaWorkEngagement).filter(NovaWorkEngagement.organization_id == organization_id)
    query = _owner_filter(query, NovaWorkEngagement, user)
    rows = query.order_by(NovaWorkEngagement.updated_at.desc()).limit(200).all()
    task_rows = (
        _owner_filter(
            db.query(NovaWorkTask).filter(NovaWorkTask.organization_id == organization_id),
            NovaWorkTask,
            user,
        )
        .all()
    )
    by_eng: dict[str, list[NovaWorkTask]] = {}
    for task in task_rows:
        by_eng.setdefault(task.engagement_id, []).append(task)
    return [_engagement_out(row, by_eng.get(row.engagement_id, [])) for row in rows]


def create_engagement(
    db: Session,
    payload: EngagementCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    _ensure()
    _validate_amount(payload.expected_payment, label="expected_payment")
    _validate_date_range(payload.start_date, payload.end_date)
    if payload.opportunity_id:
        get_opportunity(db, payload.opportunity_id, organization_id=organization_id, user=user)
        duplicate = (
            db.query(NovaWorkEngagement)
            .filter(
                NovaWorkEngagement.organization_id == organization_id,
                NovaWorkEngagement.opportunity_id == payload.opportunity_id,
            )
            .first()
        )
        if duplicate is not None:
            raise NovaWorkError("An internal engagement already exists for this opportunity", status_code=409)
    row = NovaWorkEngagement(
        engagement_id=_new_id("NWG-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        opportunity_id=payload.opportunity_id,
        client_name=sanitize_untrusted(payload.client_name)[:220],
        service=sanitize_untrusted(payload.service)[:220],
        frequency=sanitize_untrusted(payload.frequency)[:40] or "one_time",
        status="NOT_STARTED",
        expected_payment=payload.expected_payment,
        payment_status="NONE",
        start_date=payload.start_date,
        end_date=payload.end_date,
        notes=sanitize_untrusted(payload.notes) or None,
        title=sanitize_untrusted(payload.title)[:220] or None,
        service_type=sanitize_untrusted(payload.service_type)[:80] or None,
        agreed_value=_validate_amount(payload.agreed_value, label="agreed_value"),
        estimated_revenue=payload.expected_payment,
        contracted_revenue=_validate_amount(payload.agreed_value, label="agreed_value"),
        risks=sanitize_untrusted(payload.risks) or None,
        blockers=sanitize_untrusted(payload.blockers) or None,
        priority=sanitize_untrusted(payload.priority)[:16] or "normal",
        source=sanitize_untrusted(payload.source)[:80] or None,
        due_date=payload.due_date,
    )
    db.add(row)
    db.flush()
    starter_tasks = [
        ("Prepare internal work outline", "NOVA", "NOVA"),
        ("Owner review of work plan", "OWNER", "HUMAN"),
    ]
    if str(payload.frequency or "").lower() in {"weekly", "monthly"}:
        starter_tasks.append((f"Prepare {payload.frequency} internal report draft", "NOVA", "NOVA"))
    created_tasks: list[NovaWorkTask] = []
    for title, party, classification in starter_tasks:
        task = NovaWorkTask(
            task_id=_new_id("NWT-"),
            engagement_id=row.engagement_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            opportunity_id=payload.opportunity_id,
            title=title,
            responsible_party=party,
            classification=classification,
            status="NOT_STARTED",
            priority="normal",
            review_required=True,
            description="Generated internally from the engagement. No external action.",
        )
        db.add(task)
        created_tasks.append(task)
        _record_audit(
            db,
            organization_id=organization_id,
            user=user,
            event_type="TASK_CREATED",
            summary=f"Internal task created: {title}",
            ref_id=task.task_id,
            entity_type="task",
        )
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="ENGAGEMENT_CREATED",
        summary=f"Internal engagement created for {row.client_name}. Not a signed contract.",
        ref_id=row.engagement_id,
    )
    db.commit()
    db.refresh(row)
    return _engagement_out(row, created_tasks)


def get_engagement(db: Session, engagement_id: str, *, organization_id: str, user: UserContext) -> dict[str, Any]:
    _ensure()
    query = db.query(NovaWorkEngagement).filter(
        NovaWorkEngagement.organization_id == organization_id,
        NovaWorkEngagement.engagement_id == engagement_id,
    )
    row = _owner_filter(query, NovaWorkEngagement, user).first()
    if row is None:
        raise NovaWorkError("Engagement not found", status_code=404)
    tasks = (
        db.query(NovaWorkTask)
        .filter(
            NovaWorkTask.organization_id == organization_id,
            NovaWorkTask.engagement_id == engagement_id,
        )
        .all()
    )
    return _engagement_out(row, tasks)


def create_task(
    db: Session,
    engagement_id: str,
    payload: TaskCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    engagement = get_engagement(db, engagement_id, organization_id=organization_id, user=user)
    status = normalize_task_status(payload.status)
    if status not in TASK_STATUSES:
        raise NovaWorkError("Unknown task status")
    if payload.depends_on_task_id:
        parent = (
            db.query(NovaWorkTask)
            .filter(
                NovaWorkTask.organization_id == organization_id,
                NovaWorkTask.task_id == payload.depends_on_task_id,
                NovaWorkTask.engagement_id == engagement_id,
            )
            .first()
        )
        if parent is None:
            raise NovaWorkError("Task dependency not found on this engagement", status_code=404)
    row = NovaWorkTask(
        task_id=_new_id("NWT-"),
        engagement_id=engagement_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        opportunity_id=engagement.get("opportunity_id"),
        title=sanitize_untrusted(payload.title)[:220],
        responsible_party=payload.responsible_party,
        classification=payload.classification,
        status=status,
        priority=sanitize_untrusted(payload.priority)[:16] or "normal",
        due_date=payload.due_date,
        required_owner_input=sanitize_untrusted(payload.required_owner_input) or None,
        deliverable=sanitize_untrusted(payload.deliverable)[:220] or None,
        review_required=payload.review_required,
        description=sanitize_untrusted(payload.description) or None,
        depends_on_task_id=payload.depends_on_task_id,
        blocked_reason=sanitize_untrusted(payload.blocked_reason) or None,
    )
    db.add(row)
    _record_audit(
        db,
        organization_id=organization_id,
        user=user,
        event_type="TASK_CREATED",
        summary=f"Internal task created: {row.title}",
        ref_id=row.task_id,
        entity_type="task",
    )
    db.commit()
    return get_engagement(db, engagement_id, organization_id=organization_id, user=user)


def capabilities() -> list[CapabilityOut]:
    return [CapabilityOut(**item) for item in list_capabilities()]


def providers() -> list[ProviderOut]:
    return [ProviderOut(**item) for item in list_providers()]


def verified_profile(applicant_party: str = "AMICOR") -> dict[str, Any]:
    return profile_snapshot(applicant_party=applicant_party)


def registry() -> dict[str, Any]:
    return registry_snapshot()
