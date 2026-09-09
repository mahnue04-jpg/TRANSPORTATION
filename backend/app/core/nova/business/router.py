"""Nova Business OS APIs. Operations organization only. No ledger or autonomous send."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import UserContext, get_current_user_context
from app.core.nova.business import service
from app.core.nova.business.schemas import (
    NovaBizActivityOut,
    NovaBizBrainOut,
    NovaBizBrainRequest,
    NovaBizCustomerCreate,
    NovaBizCustomerOut,
    NovaBizCustomerUpdate,
    NovaBizDashboardOut,
    NovaBizDocumentCreate,
    NovaBizDocumentOut,
    NovaBizDraftLink,
    NovaBizExpenseCreate,
    NovaBizExpenseOut,
    NovaBizMeetingCreate,
    NovaBizMeetingOut,
    NovaBizOpportunityCreate,
    NovaBizOpportunityOut,
    NovaBizOpportunityUpdate,
    NovaBizPipelineOut,
    NovaBizProfileCreate,
    NovaBizProfileOut,
    NovaBizProfileUpdate,
    NovaBizTaskCreate,
    NovaBizTaskOut,
    NovaBizTaskUpdate,
    NovaBizVendorCreate,
    NovaBizVendorOut,
)
from app.core.nova.communications.service import draft_out
from app.core.nova.router import require_nova_access
from app.core.nova.service import NovaCoreService
from app.db.session import get_db

router = APIRouter(
    prefix="/api/nova/business",
    tags=["nova-business"],
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
    if isinstance(exc, service.NovaBusinessError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise exc


@router.get("/dashboard", response_model=NovaBizDashboardOut)
def business_dashboard(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.dashboard(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/pipeline", response_model=NovaBizPipelineOut)
def business_pipeline(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return service.pipeline(db, organization_id=_resolve_org(user, organization_id), user=user)


@router.get("/profiles", response_model=list[NovaBizProfileOut])
def list_profiles(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.profile_out(row) for row in service.list_profiles(db, organization_id=org_id, user=user)]


@router.post("/profiles", response_model=NovaBizProfileOut)
def create_profile(
    payload: NovaBizProfileCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.profile_out(service.create_profile(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/profiles/{profile_id}", response_model=NovaBizProfileOut)
def get_profile(
    profile_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.profile_out(service.get_profile(db, profile_id, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.patch("/profiles/{profile_id}", response_model=NovaBizProfileOut)
def update_profile(
    profile_id: str,
    payload: NovaBizProfileUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.profile_out(
            service.update_profile(db, profile_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/customers", response_model=list[NovaBizCustomerOut])
def list_customers(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.customer_out(row) for row in service.list_customers(db, organization_id=org_id, user=user)]


@router.post("/customers", response_model=NovaBizCustomerOut)
def create_customer(
    payload: NovaBizCustomerCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.customer_out(service.create_customer(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/customers/{customer_id}", response_model=NovaBizCustomerOut)
def get_customer(
    customer_id: str,
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    try:
        return service.customer_out(service.get_customer(db, customer_id, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.patch("/customers/{customer_id}", response_model=NovaBizCustomerOut)
def update_customer(
    customer_id: str,
    payload: NovaBizCustomerUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.customer_out(
            service.update_customer(db, customer_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/opportunities", response_model=list[NovaBizOpportunityOut])
def list_opportunities(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [
        service.opportunity_out(row)
        for row in service.list_opportunities(db, organization_id=org_id, user=user)
    ]


@router.post("/opportunities", response_model=NovaBizOpportunityOut)
def create_opportunity(
    payload: NovaBizOpportunityCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.opportunity_out(
            service.create_opportunity(db, payload, organization_id=org_id, user=user)
        )
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.patch("/opportunities/{opportunity_id}", response_model=NovaBizOpportunityOut)
def update_opportunity(
    opportunity_id: str,
    payload: NovaBizOpportunityUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.opportunity_out(
            service.update_opportunity(db, opportunity_id, payload, organization_id=org_id, user=user)
        )
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/tasks", response_model=list[NovaBizTaskOut])
def list_tasks(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.task_out(row) for row in service.list_tasks(db, organization_id=org_id, user=user)]


@router.post("/tasks", response_model=NovaBizTaskOut)
def create_task(
    payload: NovaBizTaskCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.task_out(service.create_task(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.patch("/tasks/{task_id}", response_model=NovaBizTaskOut)
def update_task(
    task_id: str,
    payload: NovaBizTaskUpdate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.task_out(service.update_task(db, task_id, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/vendors", response_model=list[NovaBizVendorOut])
def list_vendors(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.vendor_out(row) for row in service.list_vendors(db, organization_id=org_id, user=user)]


@router.post("/vendors", response_model=NovaBizVendorOut)
def create_vendor(
    payload: NovaBizVendorCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.vendor_out(service.create_vendor(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/documents", response_model=list[NovaBizDocumentOut])
def list_documents(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.document_out(row) for row in service.list_documents(db, organization_id=org_id, user=user)]


@router.post("/documents", response_model=NovaBizDocumentOut)
def create_document(
    payload: NovaBizDocumentCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.document_out(service.create_document(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/expenses", response_model=list[NovaBizExpenseOut])
def list_expenses(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.expense_out(row) for row in service.list_expenses(db, organization_id=org_id, user=user)]


@router.post("/expenses", response_model=NovaBizExpenseOut)
def create_expense(
    payload: NovaBizExpenseCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.expense_out(service.create_expense(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/meetings", response_model=list[NovaBizMeetingOut])
def list_meetings(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.meeting_out(row) for row in service.list_meetings(db, organization_id=org_id, user=user)]


@router.post("/meetings", response_model=NovaBizMeetingOut)
def create_meeting(
    payload: NovaBizMeetingCreate,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.meeting_out(service.create_meeting(db, payload, organization_id=org_id, user=user))
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.get("/activity", response_model=list[NovaBizActivityOut])
def list_activity(
    organization_id: str | None = None,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, organization_id)
    return [service.activity_out(row) for row in service.list_activity(db, organization_id=org_id, user=user)]


@router.post("/draft")
def link_draft(
    payload: NovaBizDraftLink,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        draft = service.link_draft(db, payload, organization_id=org_id, user=user)
        return {"draft": draft_out(draft), "sent": False}
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.post("/ledger")
def refuse_ledger(user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_ledger()
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.post("/send")
def refuse_send(user: UserContext = Depends(get_current_user_context)):
    try:
        service.refuse_send()
    except service.NovaBusinessError as exc:
        _raise(exc)


@router.post("/ask", response_model=NovaBizBrainOut)
def ask_business(
    payload: NovaBizBrainRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org_id = _resolve_org(user, payload.organization_id)
    try:
        return service.ask_business(db, payload, organization_id=org_id, user=user)
    except service.NovaBusinessError as exc:
        _raise(exc)
