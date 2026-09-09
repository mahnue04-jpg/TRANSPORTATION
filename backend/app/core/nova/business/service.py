"""Nova Business OS. Operations organization only. No ledger, payroll, or autonomous send."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.business.models import (
    NovaBusinessActivity,
    NovaBusinessCustomer,
    NovaBusinessDocument,
    NovaBusinessExpense,
    NovaBusinessMeeting,
    NovaBusinessOpportunity,
    NovaBusinessProfile,
    NovaBusinessTask,
    NovaBusinessVendor,
)
from app.core.nova.business.schemas import (
    CUSTOMER_KINDS,
    CUSTOMER_STATUSES,
    ENTITY_TYPES,
    OPEN_OPP_STATUSES,
    OPP_STATUSES,
    PROFILE_STATUSES,
    RELATIONSHIP_TYPES,
    TASK_PRIORITIES,
    TASK_STATUSES,
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
from app.core.nova.communications.schemas import NovaCommsDraftCreate, NovaCommsEventCreate
from app.core.nova.communications.service import (
    create_draft,
    create_event,
    derive_contacts,
    list_messages,
)
from app.core.nova.government.service import NovaGovernmentError
from app.core.nova.government.service import get_item as get_gov_item
from app.core.nova.government.service import list_items as list_gov_items
from app.core.nova.government.service import work_out as gov_work_out
from app.core.nova.service import NovaCoreService
from app.core.nova.workspace.models import NovaWorkspaceFile, NovaWorkspaceProject
from app.helpers import now, uuid4


class NovaBusinessError(ValueError):
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


def _record_activity(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    kind: str,
    title: str,
    ref_id: str | None = None,
) -> None:
    db.add(
        NovaBusinessActivity(
            activity_id=_new_id("NBA-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            kind=kind,
            title=title,
            ref_id=ref_id,
        )
    )


def _require_workspace(db: Session, workspace_id: str | None, organization_id: str) -> None:
    if not workspace_id:
        return
    exists = (
        db.query(NovaWorkspaceProject)
        .filter(
            NovaWorkspaceProject.workspace_id == workspace_id,
            NovaWorkspaceProject.organization_id == organization_id,
        )
        .first()
    )
    if exists is None:
        raise NovaBusinessError("Associated Nova Workspace project not found", status_code=404)


def _require_file(db: Session, file_id: str | None, organization_id: str) -> None:
    if not file_id:
        return
    exists = (
        db.query(NovaWorkspaceFile)
        .filter(
            NovaWorkspaceFile.file_id == file_id,
            NovaWorkspaceFile.organization_id == organization_id,
        )
        .first()
    )
    if exists is None:
        raise NovaBusinessError("Associated Nova Workspace file not found", status_code=404)


def _require_government(db: Session, item_id: str | None, organization_id: str, user: UserContext) -> None:
    if not item_id:
        return
    try:
        get_gov_item(db, item_id, organization_id=organization_id, user=user)
    except NovaGovernmentError as exc:
        raise NovaBusinessError(str(exc), status_code=exc.status_code) from exc


def _scoped_get(db: Session, model, id_field: str, value: str, organization_id: str, user: UserContext, label: str):
    query = db.query(model).filter(getattr(model, id_field) == value, model.organization_id == organization_id)
    query = _owner_filter(query, model, user)
    row = query.first()
    if row is None:
        raise NovaBusinessError(f"{label} not found", status_code=404)
    return row


def _commit_new(db: Session, factory, *, prefix: str):
    for _ in range(5):
        row = factory(_new_id(prefix))
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
    raise NovaBusinessError("Could not allocate a Business ID", status_code=409)


def profile_out(row: NovaBusinessProfile, *, include_ein: bool = True) -> NovaBizProfileOut:
    return NovaBizProfileOut(
        profile_id=row.profile_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        business_name=row.business_name,
        legal_name=row.legal_name,
        dba=row.dba,
        entity_type=row.entity_type,
        industry=row.industry,
        ein_reference=row.ein_reference if include_ein else None,
        address=row.address,
        phone=row.phone,
        email=row.email,
        website=row.website,
        ownership_notes=row.ownership_notes,
        formation_date=row.formation_date,
        state_of_formation=row.state_of_formation,
        status=row.status,
        tags=row.tags,
        notes=row.notes,
        workspace_id=row.workspace_id,
        government_item_id=row.government_item_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def customer_out(row: NovaBusinessCustomer) -> NovaBizCustomerOut:
    return NovaBizCustomerOut(
        customer_id=row.customer_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        assigned_user_id=row.assigned_user_id,
        kind=row.kind,
        name=row.name,
        role_title=row.role_title,
        phone=row.phone,
        email=row.email,
        address=row.address,
        relationship_type=row.relationship_type,
        status=row.status,
        notes=row.notes,
        source=row.source,
        last_contact=row.last_contact,
        next_follow_up=row.next_follow_up,
        workspace_id=row.workspace_id,
        conversation_id=row.conversation_id,
        draft_id=row.draft_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def opportunity_out(row: NovaBusinessOpportunity) -> NovaBizOpportunityOut:
    return NovaBizOpportunityOut(
        opportunity_id=row.opportunity_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        assigned_user_id=row.assigned_user_id,
        title=row.title,
        customer_id=row.customer_id,
        company_name=row.company_name,
        source=row.source,
        description=row.description,
        estimated_value=row.estimated_value or 0.0,
        probability=row.probability or 0.0,
        status=row.status,
        expected_close_date=row.expected_close_date,
        next_action=row.next_action,
        next_action_date=row.next_action_date,
        notes=row.notes,
        workspace_id=row.workspace_id,
        file_id=row.file_id,
        conversation_id=row.conversation_id,
        draft_id=row.draft_id,
        calendar_event_id=row.calendar_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def task_out(row: NovaBusinessTask) -> NovaBizTaskOut:
    return NovaBizTaskOut(
        task_id=row.task_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        assigned_user_id=row.assigned_user_id,
        title=row.title,
        description=row.description,
        priority=row.priority,
        due_date=row.due_date,
        status=row.status,
        customer_id=row.customer_id,
        opportunity_id=row.opportunity_id,
        workspace_id=row.workspace_id,
        government_item_id=row.government_item_id,
        draft_id=row.draft_id,
        notes=row.notes,
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def vendor_out(row: NovaBusinessVendor) -> NovaBizVendorOut:
    return NovaBizVendorOut(
        vendor_id=row.vendor_id,
        vendor_name=row.vendor_name,
        category=row.category,
        contact_name=row.contact_name,
        email=row.email,
        phone=row.phone,
        website=row.website,
        status=row.status,
        services=row.services,
        document_id=row.document_id,
        government_item_id=row.government_item_id,
        notes=row.notes,
    )


def document_out(row: NovaBusinessDocument) -> NovaBizDocumentOut:
    return NovaBizDocumentOut(
        document_id=row.document_id,
        title=row.title,
        kind=row.kind,
        status=row.status,
        counterparty=row.counterparty,
        effective_date=row.effective_date,
        expiration_date=row.expiration_date,
        renewal_date=row.renewal_date,
        notes=row.notes,
        customer_id=row.customer_id,
        vendor_id=row.vendor_id,
        workspace_id=row.workspace_id,
        file_id=row.file_id,
        government_item_id=row.government_item_id,
    )


def expense_out(row: NovaBusinessExpense) -> NovaBizExpenseOut:
    return NovaBizExpenseOut(
        expense_id=row.expense_id,
        vendor_name=row.vendor_name,
        category=row.category,
        expense_date=row.expense_date,
        amount=row.amount or 0.0,
        description=row.description,
        file_id=row.file_id,
        workspace_id=row.workspace_id,
        notes=row.notes,
    )


def meeting_out(row: NovaBusinessMeeting) -> NovaBizMeetingOut:
    return NovaBizMeetingOut(
        meeting_id=row.meeting_id,
        title=row.title,
        start_time=row.start_time,
        end_time=row.end_time,
        notes=row.notes,
        customer_id=row.customer_id,
        opportunity_id=row.opportunity_id,
        workspace_id=row.workspace_id,
        calendar_event_id=row.calendar_event_id,
    )


def activity_out(row: NovaBusinessActivity) -> NovaBizActivityOut:
    return NovaBizActivityOut(
        activity_id=row.activity_id,
        kind=row.kind,
        title=row.title,
        ref_id=row.ref_id,
        created_at=row.created_at,
    )


def list_profiles(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessProfile]:
    query = db.query(NovaBusinessProfile).filter(NovaBusinessProfile.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessProfile, user).order_by(NovaBusinessProfile.updated_at.desc()).all()


def get_profile(db: Session, profile_id: str, *, organization_id: str, user: UserContext) -> NovaBusinessProfile:
    return _scoped_get(db, NovaBusinessProfile, "profile_id", profile_id, organization_id, user, "Business profile")


def create_profile(db: Session, payload: NovaBizProfileCreate, *, organization_id: str, user: UserContext):
    _require_workspace(db, payload.workspace_id, organization_id)
    _require_government(db, payload.government_item_id, organization_id, user)
    def factory(new_id: str) -> NovaBusinessProfile:
        return NovaBusinessProfile(
            profile_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            business_name=payload.business_name.strip(),
            legal_name=payload.legal_name,
            dba=payload.dba,
            entity_type=payload.entity_type,
            industry=payload.industry,
            ein_reference=payload.ein_reference,
            address=payload.address,
            phone=payload.phone,
            email=payload.email,
            website=payload.website,
            ownership_notes=payload.ownership_notes,
            formation_date=payload.formation_date,
            state_of_formation=payload.state_of_formation,
            status=payload.status,
            tags=payload.tags,
            notes=payload.notes,
            workspace_id=payload.workspace_id,
            government_item_id=payload.government_item_id,
        )
    row = _commit_new(db, factory, prefix="NB-")
    _record_activity(db, organization_id=organization_id, user=user, kind="profile_created", title=row.business_name, ref_id=row.profile_id)
    db.commit()
    db.refresh(row)
    return row


def update_profile(db: Session, profile_id: str, payload: NovaBizProfileUpdate, *, organization_id: str, user: UserContext):
    row = get_profile(db, profile_id, organization_id=organization_id, user=user)
    data = payload.model_dump(exclude_unset=True, exclude={"organization_id"})
    if "entity_type" in data and data["entity_type"] not in ENTITY_TYPES:
        raise NovaBusinessError("Invalid entity type", status_code=422)
    if "status" in data and data["status"] not in PROFILE_STATUSES:
        raise NovaBusinessError("Invalid profile status", status_code=422)
    _require_workspace(db, data.get("workspace_id"), organization_id)
    _require_government(db, data.get("government_item_id"), organization_id, user)
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = now()
    _record_activity(db, organization_id=organization_id, user=user, kind="profile_updated", title=row.business_name, ref_id=row.profile_id)
    db.commit()
    db.refresh(row)
    return row


def list_customers(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessCustomer]:
    query = db.query(NovaBusinessCustomer).filter(NovaBusinessCustomer.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessCustomer, user).order_by(NovaBusinessCustomer.updated_at.desc()).all()


def get_customer(db: Session, customer_id: str, *, organization_id: str, user: UserContext) -> NovaBusinessCustomer:
    return _scoped_get(db, NovaBusinessCustomer, "customer_id", customer_id, organization_id, user, "Customer")


def create_customer(db: Session, payload: NovaBizCustomerCreate, *, organization_id: str, user: UserContext):
    _require_workspace(db, payload.workspace_id, organization_id)
    def factory(new_id: str) -> NovaBusinessCustomer:
        return NovaBusinessCustomer(
            customer_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            assigned_user_id=payload.assigned_user_id or user.user_id,
            kind=payload.kind,
            name=payload.name.strip(),
            role_title=payload.role_title,
            phone=payload.phone,
            email=payload.email,
            address=payload.address,
            relationship_type=payload.relationship_type,
            status=payload.status,
            notes=payload.notes,
            source=payload.source,
            last_contact=payload.last_contact,
            next_follow_up=payload.next_follow_up,
            workspace_id=payload.workspace_id,
            conversation_id=payload.conversation_id,
        )
    row = _commit_new(db, factory, prefix="NBC-")
    _record_activity(db, organization_id=organization_id, user=user, kind="customer_created", title=row.name, ref_id=row.customer_id)
    db.commit()
    db.refresh(row)
    return row


def update_customer(db: Session, customer_id: str, payload: NovaBizCustomerUpdate, *, organization_id: str, user: UserContext):
    row = get_customer(db, customer_id, organization_id=organization_id, user=user)
    data = payload.model_dump(exclude_unset=True, exclude={"organization_id"})
    if "kind" in data and data["kind"] not in CUSTOMER_KINDS:
        raise NovaBusinessError("Invalid customer kind", status_code=422)
    if "status" in data and data["status"] not in CUSTOMER_STATUSES:
        raise NovaBusinessError("Invalid customer status", status_code=422)
    if "relationship_type" in data and data["relationship_type"] not in RELATIONSHIP_TYPES:
        raise NovaBusinessError("Invalid relationship type", status_code=422)
    _require_workspace(db, data.get("workspace_id"), organization_id)
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = now()
    _record_activity(db, organization_id=organization_id, user=user, kind="customer_updated", title=row.name, ref_id=row.customer_id)
    db.commit()
    db.refresh(row)
    return row


def list_opportunities(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessOpportunity]:
    query = db.query(NovaBusinessOpportunity).filter(NovaBusinessOpportunity.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessOpportunity, user).order_by(NovaBusinessOpportunity.updated_at.desc()).all()


def get_opportunity(db: Session, opportunity_id: str, *, organization_id: str, user: UserContext) -> NovaBusinessOpportunity:
    return _scoped_get(db, NovaBusinessOpportunity, "opportunity_id", opportunity_id, organization_id, user, "Opportunity")


def create_opportunity(db: Session, payload: NovaBizOpportunityCreate, *, organization_id: str, user: UserContext):
    if payload.customer_id:
        get_customer(db, payload.customer_id, organization_id=organization_id, user=user)
    _require_workspace(db, payload.workspace_id, organization_id)
    _require_file(db, payload.file_id, organization_id)
    def factory(new_id: str) -> NovaBusinessOpportunity:
        return NovaBusinessOpportunity(
            opportunity_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            assigned_user_id=payload.assigned_user_id or user.user_id,
            title=payload.title.strip(),
            customer_id=payload.customer_id,
            company_name=payload.company_name,
            source=payload.source,
            description=payload.description,
            estimated_value=max(0.0, payload.estimated_value),
            probability=min(100.0, max(0.0, payload.probability)),
            status=payload.status,
            expected_close_date=payload.expected_close_date,
            next_action=payload.next_action,
            next_action_date=payload.next_action_date,
            notes=payload.notes,
            workspace_id=payload.workspace_id,
            file_id=payload.file_id,
            conversation_id=payload.conversation_id,
        )
    row = _commit_new(db, factory, prefix="NBO-")
    _record_activity(db, organization_id=organization_id, user=user, kind="opportunity_created", title=row.title, ref_id=row.opportunity_id)
    db.commit()
    db.refresh(row)
    return row


def update_opportunity(db: Session, opportunity_id: str, payload: NovaBizOpportunityUpdate, *, organization_id: str, user: UserContext):
    row = get_opportunity(db, opportunity_id, organization_id=organization_id, user=user)
    data = payload.model_dump(exclude_unset=True, exclude={"organization_id"})
    if "status" in data and data["status"] not in OPP_STATUSES:
        raise NovaBusinessError("Invalid opportunity status", status_code=422)
    if data.get("customer_id"):
        get_customer(db, data["customer_id"], organization_id=organization_id, user=user)
    _require_workspace(db, data.get("workspace_id"), organization_id)
    _require_file(db, data.get("file_id"), organization_id)
    if "estimated_value" in data and data["estimated_value"] is not None:
        data["estimated_value"] = max(0.0, data["estimated_value"])
    if "probability" in data and data["probability"] is not None:
        data["probability"] = min(100.0, max(0.0, data["probability"]))
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = now()
    _record_activity(db, organization_id=organization_id, user=user, kind="opportunity_updated", title=row.title, ref_id=row.opportunity_id)
    db.commit()
    db.refresh(row)
    return row


def list_tasks(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessTask]:
    query = db.query(NovaBusinessTask).filter(NovaBusinessTask.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessTask, user).order_by(NovaBusinessTask.updated_at.desc()).all()


def get_task(db: Session, task_id: str, *, organization_id: str, user: UserContext) -> NovaBusinessTask:
    return _scoped_get(db, NovaBusinessTask, "task_id", task_id, organization_id, user, "Task")


def create_task(db: Session, payload: NovaBizTaskCreate, *, organization_id: str, user: UserContext):
    if payload.customer_id:
        get_customer(db, payload.customer_id, organization_id=organization_id, user=user)
    if payload.opportunity_id:
        get_opportunity(db, payload.opportunity_id, organization_id=organization_id, user=user)
    _require_workspace(db, payload.workspace_id, organization_id)
    _require_government(db, payload.government_item_id, organization_id, user)
    def factory(new_id: str) -> NovaBusinessTask:
        return NovaBusinessTask(
            task_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            assigned_user_id=payload.assigned_user_id or user.user_id,
            title=payload.title.strip(),
            description=payload.description,
            priority=payload.priority,
            due_date=payload.due_date,
            status=payload.status,
            customer_id=payload.customer_id,
            opportunity_id=payload.opportunity_id,
            workspace_id=payload.workspace_id,
            government_item_id=payload.government_item_id,
            notes=payload.notes,
            completed_at=now() if payload.status == "completed" else None,
        )
    row = _commit_new(db, factory, prefix="NBT-")
    kind = "task_completed" if row.status == "completed" else "task_created"
    _record_activity(db, organization_id=organization_id, user=user, kind=kind, title=row.title, ref_id=row.task_id)
    db.commit()
    db.refresh(row)
    return row


def update_task(db: Session, task_id: str, payload: NovaBizTaskUpdate, *, organization_id: str, user: UserContext):
    row = get_task(db, task_id, organization_id=organization_id, user=user)
    data = payload.model_dump(exclude_unset=True, exclude={"organization_id"})
    if "status" in data and data["status"] not in TASK_STATUSES:
        raise NovaBusinessError("Invalid task status", status_code=422)
    if "priority" in data and data["priority"] not in TASK_PRIORITIES:
        raise NovaBusinessError("Invalid task priority", status_code=422)
    _require_workspace(db, data.get("workspace_id"), organization_id)
    _require_government(db, data.get("government_item_id"), organization_id, user)
    for key, value in data.items():
        setattr(row, key, value)
    if row.status == "completed" and row.completed_at is None:
        row.completed_at = now()
        _record_activity(db, organization_id=organization_id, user=user, kind="task_completed", title=row.title, ref_id=row.task_id)
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row


def list_vendors(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessVendor]:
    query = db.query(NovaBusinessVendor).filter(NovaBusinessVendor.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessVendor, user).order_by(NovaBusinessVendor.updated_at.desc()).all()


def create_vendor(db: Session, payload: NovaBizVendorCreate, *, organization_id: str, user: UserContext):
    _require_government(db, payload.government_item_id, organization_id, user)
    def factory(new_id: str) -> NovaBusinessVendor:
        return NovaBusinessVendor(
            vendor_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            vendor_name=payload.vendor_name.strip(),
            category=payload.category,
            contact_name=payload.contact_name,
            email=payload.email,
            phone=payload.phone,
            website=payload.website,
            status=payload.status,
            services=payload.services,
            document_id=payload.document_id,
            government_item_id=payload.government_item_id,
            notes=payload.notes,
        )
    row = _commit_new(db, factory, prefix="NBV-")
    _record_activity(db, organization_id=organization_id, user=user, kind="vendor_created", title=row.vendor_name, ref_id=row.vendor_id)
    db.commit()
    db.refresh(row)
    return row


def list_documents(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessDocument]:
    query = db.query(NovaBusinessDocument).filter(NovaBusinessDocument.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessDocument, user).order_by(NovaBusinessDocument.updated_at.desc()).all()


def get_document(db: Session, document_id: str, *, organization_id: str, user: UserContext) -> NovaBusinessDocument:
    return _scoped_get(db, NovaBusinessDocument, "document_id", document_id, organization_id, user, "Document")


def create_document(db: Session, payload: NovaBizDocumentCreate, *, organization_id: str, user: UserContext):
    _require_workspace(db, payload.workspace_id, organization_id)
    _require_file(db, payload.file_id, organization_id)
    _require_government(db, payload.government_item_id, organization_id, user)
    def factory(new_id: str) -> NovaBusinessDocument:
        return NovaBusinessDocument(
            document_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            title=payload.title.strip(),
            kind=payload.kind,
            status=payload.status,
            counterparty=payload.counterparty,
            effective_date=payload.effective_date,
            expiration_date=payload.expiration_date,
            renewal_date=payload.renewal_date,
            notes=payload.notes,
            customer_id=payload.customer_id,
            vendor_id=payload.vendor_id,
            workspace_id=payload.workspace_id,
            file_id=payload.file_id,
            government_item_id=payload.government_item_id,
        )
    row = _commit_new(db, factory, prefix="NBD-")
    _record_activity(db, organization_id=organization_id, user=user, kind="document_linked", title=row.title, ref_id=row.document_id)
    db.commit()
    db.refresh(row)
    return row


def list_expenses(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessExpense]:
    query = db.query(NovaBusinessExpense).filter(NovaBusinessExpense.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessExpense, user).order_by(NovaBusinessExpense.updated_at.desc()).all()


def create_expense(db: Session, payload: NovaBizExpenseCreate, *, organization_id: str, user: UserContext):
    _require_workspace(db, payload.workspace_id, organization_id)
    _require_file(db, payload.file_id, organization_id)
    def factory(new_id: str) -> NovaBusinessExpense:
        return NovaBusinessExpense(
            expense_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            vendor_name=payload.vendor_name,
            category=payload.category,
            expense_date=payload.expense_date,
            amount=max(0.0, payload.amount),
            description=payload.description,
            file_id=payload.file_id,
            workspace_id=payload.workspace_id,
            notes=payload.notes,
        )
    row = _commit_new(db, factory, prefix="NBE-")
    _record_activity(db, organization_id=organization_id, user=user, kind="expense_recorded", title=row.description or row.vendor_name or row.expense_id, ref_id=row.expense_id)
    db.commit()
    db.refresh(row)
    return row


def list_meetings(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessMeeting]:
    query = db.query(NovaBusinessMeeting).filter(NovaBusinessMeeting.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessMeeting, user).order_by(NovaBusinessMeeting.start_time.asc()).all()


def create_meeting(db: Session, payload: NovaBizMeetingCreate, *, organization_id: str, user: UserContext):
    _require_workspace(db, payload.workspace_id, organization_id)
    start = payload.start_time
    end = payload.end_time or (datetime.fromisoformat(start.replace("Z", "+00:00")) + timedelta(hours=1)).isoformat()
    event = create_event(
        db,
        NovaCommsEventCreate(
            title=f"Business meeting: {payload.title.strip()}",
            description="USER-SAVED INFORMATION from Nova Business. Health appointments were not changed.",
            start_time=start,
            end_time=end,
        ),
        organization_id=organization_id,
        user=user,
    )
    def factory(new_id: str) -> NovaBusinessMeeting:
        return NovaBusinessMeeting(
            meeting_id=new_id,
            organization_id=organization_id,
            owner_user_id=user.user_id,
            title=payload.title.strip(),
            start_time=event.start_time,
            end_time=event.end_time,
            notes=payload.notes,
            customer_id=payload.customer_id,
            opportunity_id=payload.opportunity_id,
            workspace_id=payload.workspace_id,
            calendar_event_id=event.id,
        )
    row = _commit_new(db, factory, prefix="NBM-")
    _record_activity(db, organization_id=organization_id, user=user, kind="meeting_linked", title=row.title, ref_id=row.meeting_id)
    if payload.create_follow_up_task:
        create_task(
            db,
            NovaBizTaskCreate(
                title=f"Follow up: {row.title}",
                customer_id=payload.customer_id,
                opportunity_id=payload.opportunity_id,
                workspace_id=payload.workspace_id,
                due_date=date.today() + timedelta(days=2),
            ),
            organization_id=organization_id,
            user=user,
        )
    db.commit()
    db.refresh(row)
    return row


def list_activity(db: Session, *, organization_id: str, user: UserContext) -> list[NovaBusinessActivity]:
    query = db.query(NovaBusinessActivity).filter(NovaBusinessActivity.organization_id == organization_id)
    return _owner_filter(query, NovaBusinessActivity, user).order_by(NovaBusinessActivity.created_at.desc()).limit(40).all()


def link_draft(db: Session, payload: NovaBizDraftLink, *, organization_id: str, user: UserContext):
    draft = create_draft(
        db,
        NovaCommsDraftCreate(to=payload.to, subject=payload.subject, body=payload.body),
        organization_id=organization_id,
        user=user,
    )
    if payload.customer_id:
        customer = get_customer(db, payload.customer_id, organization_id=organization_id, user=user)
        customer.draft_id = draft.id
        customer.updated_at = now()
        _record_activity(db, organization_id=organization_id, user=user, kind="communication_linked", title=f"Draft for {customer.name}", ref_id=customer.customer_id)
    if payload.opportunity_id:
        opportunity = get_opportunity(db, payload.opportunity_id, organization_id=organization_id, user=user)
        opportunity.draft_id = draft.id
        opportunity.updated_at = now()
        _record_activity(db, organization_id=organization_id, user=user, kind="communication_linked", title=f"Draft for {opportunity.title}", ref_id=opportunity.opportunity_id)
    db.commit()
    return draft


def pipeline(db: Session, *, organization_id: str, user: UserContext) -> NovaBizPipelineOut:
    opps = list_opportunities(db, organization_id=organization_id, user=user)
    customers = list_customers(db, organization_id=organization_id, user=user)
    open_rows = [row for row in opps if row.status in OPEN_OPP_STATUSES]
    won_rows = [row for row in opps if row.status == "won"]
    lost_rows = [row for row in opps if row.status == "lost"]
    return NovaBizPipelineOut(
        open_count=len(open_rows),
        won_count=len(won_rows),
        lost_count=len(lost_rows),
        customer_count=len(customers),
        open_pipeline=round(sum(row.estimated_value or 0.0 for row in open_rows), 2),
        won_pipeline=round(sum(row.estimated_value or 0.0 for row in won_rows), 2),
        expected_revenue=round(sum((row.estimated_value or 0.0) * ((row.probability or 0.0) / 100.0) for row in open_rows), 2),
    )


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> NovaBizDashboardOut:
    today = date.today()
    profiles = list_profiles(db, organization_id=organization_id, user=user)
    customers = list_customers(db, organization_id=organization_id, user=user)
    opps = list_opportunities(db, organization_id=organization_id, user=user)
    tasks = list_tasks(db, organization_id=organization_id, user=user)
    meetings = list_meetings(db, organization_id=organization_id, user=user)
    documents = list_documents(db, organization_id=organization_id, user=user)
    expenses = list_expenses(db, organization_id=organization_id, user=user)
    vendors = list_vendors(db, organization_id=organization_id, user=user)
    activity = list_activity(db, organization_id=organization_id, user=user)
    gov_items = [gov_work_out(row) for row in list_gov_items(db, organization_id=organization_id, user=user)[:12]]
    messages = list_messages(db, organization_id=organization_id, user=user)[:8]
    contacts = derive_contacts(db, organization_id=organization_id, user=user)[:8]
    upcoming = [
        row
        for row in meetings
        if row.start_time and (row.start_time.date() if hasattr(row.start_time, "date") else today) >= today
    ][:8]
    return NovaBizDashboardOut(
        profiles=[profile_out(row, include_ein=False) for row in profiles[:8]],
        open_opportunities=[opportunity_out(row) for row in opps if row.status in OPEN_OPP_STATUSES][:12],
        active_customers=[customer_out(row) for row in customers if row.status == "active"][:12],
        follow_ups_due=[
            customer_out(row)
            for row in customers
            if row.next_follow_up and row.next_follow_up <= today + timedelta(days=7)
        ][:12],
        overdue_tasks=[
            task_out(row)
            for row in tasks
            if row.due_date and row.due_date < today and row.status not in {"completed", "cancelled"}
        ],
        upcoming_meetings=[meeting_out(row) for row in upcoming],
        documents_attention=[
            document_out(row)
            for row in documents
            if row.status in {"expiring", "expired"}
            or (row.expiration_date and today <= row.expiration_date <= today + timedelta(days=45))
            or (row.renewal_date and today <= row.renewal_date <= today + timedelta(days=45))
        ][:12],
        completed_opportunities=[opportunity_out(row) for row in opps if row.status == "won"][:12],
        pipeline=pipeline(db, organization_id=organization_id, user=user),
        expense_total=round(sum(row.amount or 0.0 for row in expenses), 2),
        government_items=[item.model_dump(mode="json") for item in gov_items],
        communications_recent=[
            {"title": row.subject, "sender": row.sender, "created_at": row.created_at.isoformat() if row.created_at else None}
            for row in messages
        ],
        communications_contacts=[
            {"name": row.name, "email": row.email, "source": "nova_communications"}
            for row in contacts
        ],
        vendors=[vendor_out(row) for row in vendors[:12]],
        recent_activity=[activity_out(row) for row in activity],
    )


def refuse_ledger() -> None:
    raise NovaBusinessError(
        "Nova Business OS does not create accounting ledgers, journal entries, payroll, or tax filings in this phase.",
        status_code=403,
    )


def refuse_send() -> None:
    raise NovaBusinessError(
        "Nova Business OS does not send external email autonomously. Save a draft in Communications instead.",
        status_code=403,
    )


def ask_business(db: Session, payload: NovaBizBrainRequest, *, organization_id: str, user: UserContext) -> NovaBizBrainOut:
    pipe = pipeline(db, organization_id=organization_id, user=user)
    dash = dashboard(db, organization_id=organization_id, user=user)
    context = (
        f"USER-SAVED INFORMATION: {len(dash.active_customers)} active customers, "
        f"{pipe.open_count} open opportunities, open pipeline {pipe.open_pipeline}, "
        f"expected revenue {pipe.expected_revenue}, overdue tasks {len(dash.overdue_tasks)}, "
        f"follow-ups {len(dash.follow_ups_due)}, expenses {dash.expense_total} (NOT accounting)."
    )
    if payload.customer_id:
        customer = get_customer(db, payload.customer_id, organization_id=organization_id, user=user)
        context += f" Customer {customer.name} status {customer.status} follow-up {customer.next_follow_up}."
    if payload.opportunity_id:
        opportunity = get_opportunity(db, payload.opportunity_id, organization_id=organization_id, user=user)
        context += f" Opportunity {opportunity.title} status {opportunity.status} value {opportunity.estimated_value}."
    if payload.document_id:
        document = get_document(db, payload.document_id, organization_id=organization_id, user=user)
        context += f" Document {document.title} kind {document.kind} expires {document.expiration_date}."
    prompts = {
        "attention_today": "What needs attention today from USER-SAVED INFORMATION only, then add AI SUGGESTION next steps.",
        "summarize_business": "Summarize this Nova Business OS snapshot. Label VERIFIED DATA vs USER-SAVED INFORMATION vs AI SUGGESTION.",
        "overdue_followups": "List overdue or due-soon follow-ups from USER-SAVED INFORMATION.",
        "top_opportunities": "Rank top open opportunities using saved values. Forecasting is not booked revenue.",
        "summarize_customer": "Summarize this customer from USER-SAVED INFORMATION.",
        "prepare_meeting": "Prepare meeting notes and questions as AI SUGGESTION.",
        "draft_followup": "Prepare a professional follow-up email draft. Do not send it.",
        "summarize_contract": "Summarize the linked contract/document notes. Not legal advice.",
        "missing_documents": "Identify missing organizational documents as AI SUGGESTION.",
        "government_requirements": "Describe linked Government Hub items as references only. Do not file anything.",
        "next_work": "Recommend the next operational step. No autonomous outreach.",
        "find_prior_work": "Search prior saved Business and Workspace notes.",
        "summarize_pipeline": "Summarize operational pipeline totals. Not an accounting ledger.",
        "summarize_expenses": "Summarize informational expenses. Label Operational Expense Tracking — NOT Accounting.",
        "operational_risks": "Identify operational risks as AI SUGGESTION from overdue tasks, expirations, and follow-ups.",
        "ask": payload.question or "Help organize this business work without accounting or sending email.",
    }
    question = (
        "You are Mrs. Nova Brain assisting with Nova Business OS only. "
        "Never book revenue, never send email, never file government forms, never create a ledger.\n\n"
        + prompts[payload.action]
        + "\n\n"
        + context
        + "\n\n"
        + (payload.question or "")
    )
    asked = NovaCoreService.ask(db, organization_id=organization_id, mode="founder_advisor", question=question[:4000])
    if payload.action == "draft_followup":
        link_draft(
            db,
            NovaBizDraftLink(
                subject="Business follow-up draft",
                body=asked.answer,
                customer_id=payload.customer_id,
                opportunity_id=payload.opportunity_id,
            ),
            organization_id=organization_id,
            user=user,
        )
    return NovaBizBrainOut(
        action=payload.action,
        answer=asked.answer,
        fact_label="AI SUGGESTION unless the answer cites USER-SAVED INFORMATION or VERIFIED DATA. Not accounting, legal advice, or an official filing.",
        next_actions=asked.next_actions,
        generated_at=asked.generated_at,
    )
