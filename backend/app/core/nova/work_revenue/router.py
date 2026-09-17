"""Nova Work & Revenue Engine APIs. Local-only Phase 1. No Stripe and no external apply."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.core.nova.work_revenue import service
from app.core.nova.work_revenue.schemas import (
    ApplicationCreate,
    ApplicationDecision,
    ApplicationOut,
    ApplicationStatusUpdate,
    AuditEventOut,
    CapabilityOut,
    DashboardOut,
    OpportunityCreate,
    OpportunityDetailOut,
    OpportunityOut,
    OpportunityUpdate,
    OwnerActionOut,
    ProviderOut,
    QualificationOut,
    TodaySummaryOut,
    TrackerOut,
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
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return service.list_opportunity_outs(
        db, organization_id=org_id, user=user, view_filter=view_filter
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
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.application_out(db, row) for row in service.list_applications(db, organization_id=org_id, user=user)]


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
        )
        for row in service.list_audit(db, organization_id=org_id, user=user)
    ]
