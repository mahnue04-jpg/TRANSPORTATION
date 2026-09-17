"""Nova Work & Revenue Engine APIs. Local-only Phase 1. No Stripe and no external apply."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.work_revenue import service
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.lifecycle import LIFECYCLE_STAGES
from app.core.nova.work_revenue import ops
from app.core.nova.work_revenue import managed
from app.core.nova.work_revenue.schemas import (
    ApplicationCreate,
    ApplicationDecision,
    ApplicationOut,
    ApplicationStatusUpdate,
    AuditEventOut,
    BusinessFactUpdate,
    CapabilityOut,
    DashboardOut,
    DeliverableConfirm,
    DeliverableCreate,
    DeliverableOut,
    DeliverableUpdate,
    DisclosureAcknowledge,
    DisclosurePolicyCreate,
    EngagementCreate,
    EngagementUpdate,
    InvoiceSupportCreate,
    InvoiceSupportDecision,
    MaterialRevise,
    OpportunityCreate,
    OpportunityDetailOut,
    OpportunityOut,
    OpportunityUpdate,
    OwnerActionCreate,
    OwnerActionOut,
    OwnerActionUpdate,
    PlatformPolicyCreate,
    ProviderOut,
    QualificationOut,
    RecurringComplete,
    RecurringSeriesCreate,
    RevenueConfirm,
    RevenueEntryCreate,
    RevenueEntryOut,
    TaskCreate,
    TaskUpdate,
    TodaySummaryOut,
    TrackerOut,
    WeeklyReportCreate,
    WeeklyReportDecision,
)
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/work",
    tags=["nova-work-revenue"],
    dependencies=[Depends(require_nova_access)],
)


def _resolve_org(user: UserContext, requested: str | None) -> str:
    try:
        return NovaCoreService.resolve_organization_scope(user, requested)
    except ValueError as exc:
        message = str(exc)
        status = 403 if "Cross-tenant" in message else 400
        raise HTTPException(status_code=status, detail=message) from exc


def _raise(exc: Exception) -> None:
    if isinstance(exc, service.NovaWorkError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/dashboard", response_model=DashboardOut)
def work_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.dashboard(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/today-summary", response_model=TodaySummaryOut)
def work_today_summary(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.today_summary(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/capabilities", response_model=list[CapabilityOut])
def work_capabilities(user: UserContext = Depends(get_current_user_context)):
    return service.capabilities()


@router.get("/providers", response_model=list[ProviderOut])
def work_providers(user: UserContext = Depends(get_current_user_context)):
    return service.providers()


@router.get("/guardrails")
def work_guardrails(user: UserContext = Depends(get_current_user_context)):
    return engine_guardrails()


@router.get("/profile")
def work_profile(
    applicant_party: str = "AMICOR",
    user: UserContext = Depends(get_current_user_context),
):
    return service.verified_profile(applicant_party=applicant_party)


@router.get("/opportunities", response_model=list[OpportunityOut])
def list_opportunities(
    organization_id: str | None = None,
    view_filter: str | None = None,
    source: str | None = None,
    priority: str | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
    owner_action_required: bool | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return service.list_opportunity_outs(
        db,
        organization_id=org_id,
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


@router.post("/opportunities", response_model=OpportunityOut)
def create_opportunity(
    payload: OpportunityCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.opportunity_out(service.create_opportunity(db, payload, organization_id=org_id, user=user))
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/opportunities/{opportunity_id}", response_model=OpportunityOut)
def get_opportunity(
    opportunity_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.opportunity_out(service.get_opportunity(db, opportunity_id, organization_id=org_id, user=user))
    except service.NovaWorkError as exc:
        _raise(exc)


@router.patch("/opportunities/{opportunity_id}", response_model=OpportunityOut)
def update_opportunity(
    opportunity_id: str,
    payload: OpportunityUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.opportunity_out(
            service.update_opportunity(db, opportunity_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/opportunities/{opportunity_id}/qualify", response_model=QualificationOut)
def qualify_opportunity(
    opportunity_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        _row, result = service.qualify(db, opportunity_id, organization_id=org_id, user=user)
        return service.qualification_out(opportunity_id, result)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/opportunities/{opportunity_id}/tracker", response_model=TrackerOut)
def opportunity_tracker(
    opportunity_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.tracker(db, opportunity_id, organization_id=org_id, user=user)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/opportunities/{opportunity_id}/detail", response_model=OpportunityDetailOut)
def opportunity_detail(
    opportunity_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.opportunity_detail(db, opportunity_id, organization_id=org_id, user=user)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/ingest/simulated", response_model=list[OpportunityOut])
def ingest_simulated(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        rows = service.ingest_simulated(db, organization_id=org_id, user=user)
        return [service.opportunity_out(row) for row in rows]
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/applications", response_model=list[ApplicationOut])
def list_applications(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.application_out(db, row)
        for row in service.list_applications(db, organization_id=org_id, user=user, limit=limit)
    ]


@router.post("/applications", response_model=ApplicationOut)
def create_application(
    payload: ApplicationCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        row = service.create_application(db, payload, organization_id=org_id, user=user)
        return service.application_out(db, row)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/applications/{application_id}", response_model=ApplicationOut)
def get_application(
    application_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        row = service.get_application(db, application_id, organization_id=org_id, user=user)
        return service.application_out(db, row)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/applications/{application_id}/ready-for-review", response_model=ApplicationOut)
def ready_for_review(
    application_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        row = service.mark_ready_for_review(db, application_id, organization_id=org_id, user=user)
        return service.application_out(db, row)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/applications/{application_id}/decision", response_model=ApplicationOut)
def decide_application(
    application_id: str,
    payload: ApplicationDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        row = service.decide_application(db, application_id, payload, organization_id=org_id, user=user)
        return service.application_out(db, row)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/applications/{application_id}/submit")
def refuse_submit(
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
):
    try:
        service.refuse_external_submission()
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/applications/{application_id}/record-manual-submission", response_model=ApplicationOut)
def record_manual_submission(
    application_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        row = service.record_manual_submission(db, application_id, organization_id=org_id, user=user)
        return service.application_out(db, row)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.patch("/applications/{application_id}/status", response_model=OpportunityOut)
def update_application_status(
    application_id: str,
    payload: ApplicationStatusUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.opportunity_out(
            service.update_application_status(db, application_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/owner-actions", response_model=list[OwnerActionOut])
def list_owner_actions(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.owner_action_out(row) for row in service.list_owner_actions(db, organization_id=org_id, user=user)]


@router.get("/audit", response_model=list[AuditEventOut])
def list_audit(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        AuditEventOut(
            event_id=row.event_id,
            event_type=row.event_type,
            summary=row.summary,
            ref_id=row.ref_id,
            created_at=row.created_at,
            actor_category=getattr(row, "actor_category", None) or "NOVA",
            entity_type=getattr(row, "entity_type", None),
            previous_state=getattr(row, "previous_state", None),
            new_state=getattr(row, "new_state", None),
        )
        for row in service.list_audit(db, organization_id=org_id, user=user, limit=limit)
    ]


@router.get("/engagements")
def list_engagements(
    organization_id: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    source: str | None = None,
    client: str | None = None,
    owner_action: bool | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.list_work_queue(
            db,
            organization_id=_resolve_org(user, organization_id),
            user=user,
            status=status,
            priority=priority,
            source=source,
            client=client,
            owner_action=owner_action,
            sort=sort,
            order=order,
            limit=limit,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/engagements")
def create_engagement(
    payload: EngagementCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.create_engagement(db, payload, organization_id=org_id, user=user)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/engagements/{engagement_id}")
def get_engagement(
    engagement_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return service.get_engagement(
            db, engagement_id, organization_id=_resolve_org(user, organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/engagements/{engagement_id}/tasks")
def create_task(
    engagement_id: str,
    payload: TaskCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.create_task(db, engagement_id, payload, organization_id=org_id, user=user)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/owner-facts")
def owner_facts(
    applicant_party: str = "AMICOR",
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.owner_fact_catalog(
        db,
        organization_id=_resolve_org(user, organization_id),
        user=user,
        applicant_party=applicant_party,
    )


@router.get("/lifecycle")
def work_lifecycle(user: UserContext = Depends(get_current_user_context)):
    return {
        "stages": list(LIFECYCLE_STAGES),
        "approved_equals_submitted": False,
        "external_submission_enabled": False,
        "live_discovery_enabled": False,
        "financial_actions_enabled": False,
    }


@router.get("/recurring-templates")
def recurring_templates(user: UserContext = Depends(get_current_user_context)):
    return ops.recurring_catalog()


@router.get("/analytics")
def work_analytics(
    organization_id: str | None = None,
    period: str = "all",
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.analytics(db, organization_id=_resolve_org(user, organization_id), user=user, period=period)
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/tasks")
def list_tasks(
    organization_id: str | None = None,
    engagement_id: str | None = None,
    status: str | None = None,
    nova_capable: bool | None = None,
    limit: int | None = None,
    offset: int = 0,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return ops.list_tasks(
        db,
        organization_id=_resolve_org(user, organization_id),
        user=user,
        engagement_id=engagement_id,
        status=status,
        nova_capable=nova_capable,
        limit=limit,
        offset=offset,
    )


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: str,
    payload: TaskUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.update_task(
            db, task_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/deliverables", response_model=list[DeliverableOut])
def list_deliverables(
    organization_id: str | None = None,
    engagement_id: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return ops.list_deliverables(
        db,
        organization_id=_resolve_org(user, organization_id),
        user=user,
        engagement_id=engagement_id,
        limit=limit,
        offset=offset,
    )


@router.post("/deliverables", response_model=DeliverableOut)
def create_deliverable(
    payload: DeliverableCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.create_deliverable(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/deliverables/{deliverable_id}", response_model=DeliverableOut)
def get_deliverable(
    deliverable_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.deliverable_out(
            ops.get_deliverable(
                db, deliverable_id, organization_id=_resolve_org(user, organization_id), user=user
            )
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.patch("/deliverables/{deliverable_id}", response_model=DeliverableOut)
def update_deliverable(
    deliverable_id: str,
    payload: DeliverableUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.update_deliverable(
            db, deliverable_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/deliverables/{deliverable_id}/confirm", response_model=DeliverableOut)
def confirm_deliverable(
    deliverable_id: str,
    payload: DeliverableConfirm,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.confirm_deliverable(
            db, deliverable_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/revenue-entries", response_model=list[RevenueEntryOut])
def list_revenue_entries(
    organization_id: str | None = None,
    engagement_id: str | None = None,
    stage: str | None = None,
    limit: int | None = None,
    offset: int = 0,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return ops.list_revenue_entries(
        db,
        organization_id=_resolve_org(user, organization_id),
        user=user,
        engagement_id=engagement_id,
        stage=stage,
        limit=limit,
        offset=offset,
    )


@router.post("/revenue-entries", response_model=RevenueEntryOut)
def create_revenue_entry(
    payload: RevenueEntryCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.create_revenue_entry(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as ext:
        _raise(ext)


@router.post("/revenue-entries/{entry_id}/stage", response_model=RevenueEntryOut)
def update_revenue_stage(
    entry_id: str,
    stage: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.update_revenue_stage(
            db, entry_id, stage, organization_id=_resolve_org(user, organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/revenue-entries/{entry_id}/confirm", response_model=RevenueEntryOut)
def confirm_revenue(
    entry_id: str,
    payload: RevenueConfirm,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.confirm_revenue_received(
            db, entry_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/applications/{application_id}/materials/{material_id}/revise")
def revise_material(
    application_id: str,
    material_id: str,
    payload: MaterialRevise,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.revise_material(
            db,
            application_id,
            material_id,
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.patch("/owner-actions/{action_id}")
def update_owner_action(
    action_id: str,
    payload: OwnerActionUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return ops.update_owner_action(
            db, action_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.patch("/engagements/{engagement_id}")
def update_engagement(
    engagement_id: str,
    payload: EngagementUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.update_engagement(
            db, engagement_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/queue")
def work_queue(
    organization_id: str | None = None,
    status: str | None = None,
    priority: str | None = None,
    source: str | None = None,
    client: str | None = None,
    owner_action: bool | None = None,
    due_before: datetime | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.list_work_queue(
            db,
            organization_id=_resolve_org(user, organization_id),
            user=user,
            status=status,
            priority=priority,
            source=source,
            client=client,
            owner_action=owner_action,
            due_before=due_before,
            sort=sort,
            order=order,
            limit=limit,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/recurring")
def create_recurring(
    payload: RecurringSeriesCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.create_recurring_series(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/recurring")
def list_recurring(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.list_recurring_series(
        db, organization_id=_resolve_org(user, organization_id), user=user, limit=limit
    )


@router.post("/recurring/{series_id}/generate")
def generate_recurring(
    series_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.generate_recurring_occurrence(
            db, series_id, organization_id=_resolve_org(user, organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/recurring/{series_id}/pause")
def pause_recurring(
    series_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.set_recurring_status(
            db, series_id, "PAUSED", organization_id=_resolve_org(user, organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/recurring/{series_id}/resume")
def resume_recurring(
    series_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.set_recurring_status(
            db, series_id, "ACTIVE", organization_id=_resolve_org(user, organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/recurring/{series_id}/archive")
def archive_recurring(
    series_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.set_recurring_status(
            db, series_id, "ARCHIVED", organization_id=_resolve_org(user, organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/recurring/{series_id}/complete")
def complete_recurring(
    series_id: str,
    payload: RecurringComplete,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.complete_recurring_occurrence(
            db, series_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/reports/weekly")
def create_weekly_report(
    payload: WeeklyReportCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.generate_weekly_report(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/reports")
def list_reports(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.list_weekly_reports(
        db, organization_id=_resolve_org(user, organization_id), user=user, limit=limit
    )


@router.post("/reports/{report_id}/review")
def review_report(
    report_id: str,
    payload: WeeklyReportDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.transition_weekly_report(
            db,
            report_id,
            "READY_FOR_OWNER_REVIEW",
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/reports/{report_id}/approve")
def approve_report(
    report_id: str,
    payload: WeeklyReportDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.transition_weekly_report(
            db,
            report_id,
            "APPROVED_FOR_MANUAL_USE",
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/reports/{report_id}/archive")
def archive_report(
    report_id: str,
    payload: WeeklyReportDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.transition_weekly_report(
            db,
            report_id,
            "ARCHIVED",
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/reports/{report_id}/send")
def refuse_report_send(report_id: str, user: UserContext = Depends(get_current_user_context)):
    try:
        managed.refuse_report_send()
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/invoice-support")
def create_invoice_support(
    payload: InvoiceSupportCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.create_invoice_support(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/invoice-support")
def list_invoice_support(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.list_invoice_supports(
        db, organization_id=_resolve_org(user, organization_id), user=user, limit=limit
    )


@router.post("/invoice-support/{invoice_support_id}/review")
def review_invoice_support(
    invoice_support_id: str,
    payload: InvoiceSupportDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.transition_invoice_support(
            db,
            invoice_support_id,
            "READY_FOR_OWNER_REVIEW",
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/invoice-support/{invoice_support_id}/approve")
def approve_invoice_support(
    invoice_support_id: str,
    payload: InvoiceSupportDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.transition_invoice_support(
            db,
            invoice_support_id,
            "APPROVED",
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/invoice-support/{invoice_support_id}/archive")
def archive_invoice_support(
    invoice_support_id: str,
    payload: InvoiceSupportDecision,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.transition_invoice_support(
            db,
            invoice_support_id,
            "ARCHIVED",
            payload,
            organization_id=_resolve_org(user, payload.organization_id),
            user=user,
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/invoice-support/{invoice_support_id}/send")
def refuse_invoice_send(invoice_support_id: str, user: UserContext = Depends(get_current_user_context)):
    try:
        managed.refuse_invoice_send()
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/reconciliation")
def revenue_reconciliation(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.reconciliation(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.post("/owner-actions")
def create_owner_action(
    payload: OwnerActionCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.create_owner_action(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.put("/owner-facts/{fact_key}")
def update_owner_fact(
    fact_key: str,
    payload: BusinessFactUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.update_business_fact(
            db, fact_key, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.post("/disclosure-policies")
def create_disclosure_policy(
    payload: DisclosurePolicyCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.create_disclosure_policy(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/disclosure-policies")
def list_disclosure_policies(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.list_disclosure_policies(
        db, organization_id=_resolve_org(user, organization_id), user=user, limit=limit
    )


@router.post("/disclosure-policies/{policy_id}/acknowledge")
def acknowledge_disclosure(
    policy_id: str,
    payload: DisclosureAcknowledge,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.acknowledge_disclosure(
            db, policy_id, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/platform-policies/catalog")
def platform_policy_catalog(user: UserContext = Depends(get_current_user_context)):
    return managed.platform_policy_catalog()


@router.post("/platform-policies")
def create_platform_policy(
    payload: PlatformPolicyCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    try:
        return managed.create_platform_policy(
            db, payload, organization_id=_resolve_org(user, payload.organization_id), user=user
        )
    except service.NovaWorkError as exc:
        _raise(exc)


@router.get("/platform-policies")
def list_platform_policies(
    organization_id: str | None = None,
    limit: int | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return managed.list_platform_policies(
        db, organization_id=_resolve_org(user, organization_id), user=user, limit=limit
    )
