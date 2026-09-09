"""Nova Government Services. Organization/research only. No agency filing or Health writes."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.communications.schemas import NovaCommsDraftCreate, NovaCommsEventCreate
from app.core.nova.communications.service import create_draft, create_event
from app.core.nova.government.models import (
    NovaGovernmentChecklistItem,
    NovaGovernmentProgram,
    NovaGovernmentSource,
    NovaGovernmentWorkItem,
)
from app.core.nova.government.schemas import (
    FILING_STATUSES,
    GOV_CATEGORIES,
    GOV_LEVELS,
    GOV_STATUSES,
    VERIFICATION_STATES,
    NovaGovBrainOut,
    NovaGovBrainRequest,
    NovaGovChecklistCreate,
    NovaGovChecklistOut,
    NovaGovDashboardOut,
    NovaGovDraftLink,
    NovaGovProgramCreate,
    NovaGovProgramOut,
    NovaGovSearchRequest,
    NovaGovSourceCreate,
    NovaGovSourceOut,
    NovaGovWorkCreate,
    NovaGovWorkOut,
    NovaGovWorkUpdate,
)
from app.core.nova.service import NovaCoreService
from app.core.nova.workspace.models import NovaWorkspaceFile, NovaWorkspaceProject
from app.helpers import now, uuid4
from app.web_search import search_web


class NovaGovernmentError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


SECTIONS = [
    ("federal", "Federal"),
    ("state", "State"),
    ("county", "County"),
    ("city", "City / Local"),
    ("licensing", "Licensing & Permits"),
    ("taxes", "Taxes"),
    ("grants", "Grants & Funding"),
    ("certifications", "Certifications"),
    ("transportation", "Transportation / DOT"),
    ("business_registration", "Business Registration"),
    ("compliance", "Compliance"),
    ("benefits", "Benefits / Public Services"),
    ("forms", "Forms & Documents"),
]


def _new_id(prefix: str) -> str:
    return prefix + uuid4().replace("-", "")[:12].upper()


def _can_see_org_wide(user: UserContext) -> bool:
    return normalize_role(user.role) in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}


def _owner_filter(query, model, user: UserContext):
    if _can_see_org_wide(user):
        return query
    return query.filter(model.owner_user_id == user.user_id)


def work_out(row: NovaGovernmentWorkItem) -> NovaGovWorkOut:
    return NovaGovWorkOut(
        item_id=row.item_id,
        organization_id=row.organization_id,
        owner_user_id=row.owner_user_id,
        assigned_user_id=row.assigned_user_id,
        title=row.title,
        agency=row.agency,
        government_level=row.government_level,
        state=row.state,
        county=row.county,
        city=row.city,
        category=row.category,
        description=row.description,
        source_reference=row.source_reference,
        status=row.status,
        due_date=row.due_date,
        renewal_date=row.renewal_date,
        filing_status=row.filing_status,
        notes=row.notes,
        workspace_id=row.workspace_id,
        file_id=row.file_id,
        conversation_id=row.conversation_id,
        draft_id=row.draft_id,
        calendar_event_id=row.calendar_event_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_item(
    db: Session,
    item_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovernmentWorkItem:
    query = db.query(NovaGovernmentWorkItem).filter(
        NovaGovernmentWorkItem.item_id == item_id,
        NovaGovernmentWorkItem.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaGovernmentWorkItem, user)
    row = query.first()
    if row is None:
        raise NovaGovernmentError("Government work item not found", status_code=404)
    return row


def list_items(
    db: Session,
    *,
    organization_id: str,
    user: UserContext,
    status: str | None = None,
    category: str | None = None,
    government_level: str | None = None,
) -> list[NovaGovernmentWorkItem]:
    query = db.query(NovaGovernmentWorkItem).filter(
        NovaGovernmentWorkItem.organization_id == organization_id
    )
    query = _owner_filter(query, NovaGovernmentWorkItem, user)
    if status:
        query = query.filter(NovaGovernmentWorkItem.status == status)
    if category:
        query = query.filter(NovaGovernmentWorkItem.category == category)
    if government_level:
        query = query.filter(NovaGovernmentWorkItem.government_level == government_level)
    return query.order_by(NovaGovernmentWorkItem.updated_at.desc()).all()


def create_item(
    db: Session,
    payload: NovaGovWorkCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovernmentWorkItem:
    if payload.workspace_id:
        exists = (
            db.query(NovaWorkspaceProject)
            .filter(
                NovaWorkspaceProject.workspace_id == payload.workspace_id,
                NovaWorkspaceProject.organization_id == organization_id,
            )
            .first()
        )
        if exists is None:
            raise NovaGovernmentError("Associated Nova Workspace project not found", status_code=404)
    if payload.file_id:
        file_row = (
            db.query(NovaWorkspaceFile)
            .filter(
                NovaWorkspaceFile.file_id == payload.file_id,
                NovaWorkspaceFile.organization_id == organization_id,
            )
            .first()
        )
        if file_row is None:
            raise NovaGovernmentError("Associated Nova Workspace file not found", status_code=404)
    row = None
    for _ in range(5):
        row = NovaGovernmentWorkItem(
            item_id=_new_id("NG-"),
            organization_id=organization_id,
            owner_user_id=user.user_id,
            assigned_user_id=payload.assigned_user_id or user.user_id,
            title=payload.title.strip(),
            agency=(payload.agency or "").strip() or None,
            government_level=payload.government_level,
            state=payload.state,
            county=payload.county,
            city=payload.city,
            category=payload.category,
            description=payload.description,
            source_reference=payload.source_reference,
            status=payload.status,
            due_date=payload.due_date,
            renewal_date=payload.renewal_date,
            filing_status=payload.filing_status,
            notes=payload.notes,
            workspace_id=payload.workspace_id,
            file_id=payload.file_id,
            conversation_id=payload.conversation_id,
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            return row
        except IntegrityError:
            db.rollback()
            row = None
    raise NovaGovernmentError("Could not allocate a government item ID", status_code=409)


def update_item(
    db: Session,
    item_id: str,
    payload: NovaGovWorkUpdate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovernmentWorkItem:
    row = get_item(db, item_id, organization_id=organization_id, user=user)
    data = payload.model_dump(exclude_unset=True, exclude={"organization_id"})
    if "status" in data and data["status"] not in GOV_STATUSES:
        raise NovaGovernmentError("Invalid government status", status_code=422)
    if "government_level" in data and data["government_level"] not in GOV_LEVELS:
        raise NovaGovernmentError("Invalid government level", status_code=422)
    if "category" in data and data["category"] not in GOV_CATEGORIES:
        raise NovaGovernmentError("Invalid government category", status_code=422)
    if "filing_status" in data and data["filing_status"] not in FILING_STATUSES:
        raise NovaGovernmentError("Invalid filing status", status_code=422)
    for key, value in data.items():
        setattr(row, key, value)
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row


def add_checklist(
    db: Session,
    item_id: str,
    payload: NovaGovChecklistCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovernmentChecklistItem:
    get_item(db, item_id, organization_id=organization_id, user=user)
    if payload.file_id:
        file_row = (
            db.query(NovaWorkspaceFile)
            .filter(
                NovaWorkspaceFile.file_id == payload.file_id,
                NovaWorkspaceFile.organization_id == organization_id,
            )
            .first()
        )
        if file_row is None:
            raise NovaGovernmentError("Associated Nova Workspace file not found", status_code=404)
    row = NovaGovernmentChecklistItem(
        checklist_id=_new_id("NGC-"),
        item_id=item_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        label=payload.label.strip(),
        document_type=payload.document_type,
        file_id=payload.file_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_checklist(
    db: Session, item_id: str, *, organization_id: str, user: UserContext
) -> list[NovaGovernmentChecklistItem]:
    get_item(db, item_id, organization_id=organization_id, user=user)
    return (
        db.query(NovaGovernmentChecklistItem)
        .filter(
            NovaGovernmentChecklistItem.item_id == item_id,
            NovaGovernmentChecklistItem.organization_id == organization_id,
        )
        .order_by(NovaGovernmentChecklistItem.created_at.asc())
        .all()
    )


def toggle_checklist(
    db: Session,
    checklist_id: str,
    *,
    organization_id: str,
    user: UserContext,
    completed: bool,
) -> NovaGovernmentChecklistItem:
    query = db.query(NovaGovernmentChecklistItem).filter(
        NovaGovernmentChecklistItem.checklist_id == checklist_id,
        NovaGovernmentChecklistItem.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaGovernmentChecklistItem, user)
    row = query.first()
    if row is None:
        raise NovaGovernmentError("Checklist item not found", status_code=404)
    row.completed = completed
    db.commit()
    db.refresh(row)
    return row


def add_source(
    db: Session,
    item_id: str,
    payload: NovaGovSourceCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovernmentSource:
    get_item(db, item_id, organization_id=organization_id, user=user)
    if payload.verification_status not in VERIFICATION_STATES:
        raise NovaGovernmentError("Invalid verification status", status_code=422)
    row = NovaGovernmentSource(
        source_id=_new_id("NGS-"),
        item_id=item_id,
        organization_id=organization_id,
        owner_user_id=user.user_id,
        agency_name=payload.agency_name,
        page_title=payload.page_title.strip(),
        source_url=payload.source_url,
        notes=payload.notes,
        jurisdiction=payload.jurisdiction,
        verification_status=payload.verification_status,
        retrieved_at=now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_sources(
    db: Session, item_id: str, *, organization_id: str, user: UserContext
) -> list[NovaGovernmentSource]:
    get_item(db, item_id, organization_id=organization_id, user=user)
    return (
        db.query(NovaGovernmentSource)
        .filter(
            NovaGovernmentSource.item_id == item_id,
            NovaGovernmentSource.organization_id == organization_id,
        )
        .order_by(NovaGovernmentSource.created_at.desc())
        .all()
    )


def create_program(
    db: Session,
    payload: NovaGovProgramCreate,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovernmentProgram:
    row = NovaGovernmentProgram(
        program_id=_new_id("NGP-"),
        organization_id=organization_id,
        owner_user_id=user.user_id,
        program_name=payload.program_name.strip(),
        agency=payload.agency,
        eligibility=payload.eligibility,
        amount_range=payload.amount_range,
        deadline=payload.deadline,
        status=payload.status,
        requirements=payload.requirements,
        attachments_note=payload.attachments_note,
        contact_info=payload.contact_info,
        notes=payload.notes,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_programs(db: Session, *, organization_id: str, user: UserContext) -> list[NovaGovernmentProgram]:
    query = db.query(NovaGovernmentProgram).filter(NovaGovernmentProgram.organization_id == organization_id)
    query = _owner_filter(query, NovaGovernmentProgram, user)
    return query.order_by(NovaGovernmentProgram.updated_at.desc()).all()


def link_deadline_to_calendar(
    db: Session,
    item_id: str,
    *,
    organization_id: str,
    user: UserContext,
):
    row = get_item(db, item_id, organization_id=organization_id, user=user)
    if row.due_date is None:
        raise NovaGovernmentError("Work item has no due date to link", status_code=422)
    start = datetime.combine(row.due_date, datetime.min.time())
    event = create_event(
        db,
        NovaCommsEventCreate(
            title=f"Government deadline: {row.title}",
            description=f"USER-SAVED INFORMATION from Nova Government item {row.item_id}. Not an official filing.",
            start_time=start.isoformat(),
            end_time=(start + timedelta(hours=1)).isoformat(),
            location=row.source_reference,
        ),
        organization_id=organization_id,
        user=user,
    )
    row.calendar_event_id = event.id
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row


def link_draft(
    db: Session,
    item_id: str,
    payload: NovaGovDraftLink,
    *,
    organization_id: str,
    user: UserContext,
):
    row = get_item(db, item_id, organization_id=organization_id, user=user)
    draft = create_draft(
        db,
        NovaCommsDraftCreate(to=payload.to, subject=payload.subject, body=payload.body),
        organization_id=organization_id,
        user=user,
    )
    row.draft_id = draft.id
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return row, draft


def dashboard(db: Session, *, organization_id: str, user: UserContext) -> NovaGovDashboardOut:
    items = list_items(db, organization_id=organization_id, user=user)
    today = date.today()
    upcoming = [row for row in items if row.due_date and today <= row.due_date <= today + timedelta(days=45)]
    renewals = [row for row in items if row.renewal_date and today <= row.renewal_date <= today + timedelta(days=90)]
    overdue = [row for row in items if row.due_date and row.due_date < today and row.status not in {"closed", "approved"}]
    waiting = [row for row in items if row.status == "waiting_response"]
    completed = [row for row in items if row.status in {"approved", "closed"}][:12]
    sections = []
    for key, label in SECTIONS:
        count = sum(
            1
            for row in items
            if row.government_level == key or row.category == key or (key == "city" and row.government_level in {"city", "local"})
        )
        sections.append({"key": key, "label": label, "count": count})
    return NovaGovDashboardOut(
        sections=sections,
        saved_work=[work_out(row) for row in items[:20]],
        upcoming_deadlines=[work_out(row) for row in upcoming],
        renewals=[work_out(row) for row in renewals],
        overdue=[work_out(row) for row in overdue],
        waiting_response=[work_out(row) for row in waiting],
        recently_completed=[work_out(row) for row in completed],
        programs=[
            NovaGovProgramOut(
                program_id=row.program_id,
                program_name=row.program_name,
                agency=row.agency,
                eligibility=row.eligibility,
                amount_range=row.amount_range,
                deadline=row.deadline,
                status=row.status,
                requirements=row.requirements,
                attachments_note=row.attachments_note,
                contact_info=row.contact_info,
                notes=row.notes,
            )
            for row in list_programs(db, organization_id=organization_id, user=user)[:12]
        ],
    )


def search_government(
    db: Session,
    payload: NovaGovSearchRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> dict:
    filters = " ".join(
        part
        for part in [payload.government_level, payload.category, payload.state, "government official"]
        if part
    )
    query = f"{payload.query.strip()} {filters}".strip()
    web = search_web(query, max_results=4, news_mode=False)
    saved = []
    needle = payload.query.lower()
    for row in list_items(db, organization_id=organization_id, user=user):
        blob = " ".join(
            str(part or "")
            for part in (row.title, row.agency, row.description, row.notes, row.state, row.city, row.category)
        ).lower()
        if needle in blob:
            saved.append(work_out(row))
    return {
        "query": payload.query,
        "web": {
            "status": web.get("status"),
            "response": web.get("response"),
            "sources": web.get("sources") or [],
        },
        "saved_work": saved,
        "disclaimer": "Web results are research aids, not official government rulings. USER-SAVED INFORMATION is separate from AI SUGGESTION.",
    }


def refuse_filing() -> None:
    raise NovaGovernmentError(
        "Nova does not submit government filings or pay government fees in this phase. Records stay organizational only.",
        status_code=403,
    )


def _item_context(db: Session, row: NovaGovernmentWorkItem, *, organization_id: str, user: UserContext) -> str:
    checks = list_checklist(db, row.item_id, organization_id=organization_id, user=user)
    sources = list_sources(db, row.item_id, organization_id=organization_id, user=user)
    missing = [item.label for item in checks if not item.completed]
    source_line = "; ".join(
        f"{item.page_title} ({item.verification_status})" for item in sources[:6]
    ) or "none"
    return (
        f"USER-SAVED INFORMATION: {row.title}. Agency {row.agency or 'unspecified'}. "
        f"Level {row.government_level}. Jurisdiction {row.state or ''} {row.county or ''} {row.city or ''}. "
        f"Status {row.status}. Due {row.due_date}. Renewal {row.renewal_date}. "
        f"Filing status {row.filing_status} (user-saved, not a verified filing). "
        f"Missing checklist items: {', '.join(missing) or 'none'}. Sources: {source_line}."
    )


def ask_government(
    db: Session,
    payload: NovaGovBrainRequest,
    *,
    organization_id: str,
    user: UserContext,
) -> NovaGovBrainOut:
    items = list_items(db, organization_id=organization_id, user=user)
    context = f"Open government work count: {len(items)}. "
    if payload.item_id:
        row = get_item(db, payload.item_id, organization_id=organization_id, user=user)
        context += _item_context(db, row, organization_id=organization_id, user=user)
    else:
        context += "Titles: " + ", ".join(row.title for row in items[:10])
    prompts = {
        "explain_requirement": "Explain this government requirement. Label VERIFIED DATA vs USER-SAVED INFORMATION vs AI SUGGESTION. Do not present this as an official ruling.",
        "summarize_letter": "Summarize the government letter or notes. Distinguish user-saved text from AI suggestion.",
        "find_agency": "Suggest the likely responsible agency. Mark as AI SUGGESTION unless a saved official source exists.",
        "missing_documents": "List missing checklist documents from USER-SAVED INFORMATION only, then suggest extras as AI SUGGESTION.",
        "build_checklist": "Propose a filing checklist as AI SUGGESTION. Do not claim forms were filed.",
        "next_step": "Recommend the next organizational step. Do not file or pay anything.",
        "compare_levels": "Compare federal, state, and local considerations as AI SUGGESTION unless sources are marked official_source.",
        "summarize_correspondence": "Summarize linked correspondence notes. Do not send email.",
        "prepare_questions": "Prepare questions for an agency as a draft, labeled AI SUGGESTION.",
        "prepare_email": "Prepare a professional government email draft. Do not send it.",
        "identify_deadlines": "Identify upcoming USER-SAVED deadlines and renewals.",
        "summarize_open_work": "Summarize all open Nova Government work items as USER-SAVED INFORMATION.",
        "search_prior_work": "Search prior saved Nova Government and Workspace notes for related work.",
        "ask": payload.question or "Help organize this government work without filing anything.",
    }
    question = (
        "You are Mrs. Nova Brain assisting with Nova Government organization only. "
        "Never claim a filing was submitted. Never impersonate the user. "
        "Always separate VERIFIED DATA, USER-SAVED INFORMATION, and AI SUGGESTION. Government sources may be OFFICIAL SOURCE, CONFIRMED IN WRITING, or EXPIRED OR SUPERSEDED.\n\n"
        + prompts[payload.action]
        + "\n\n"
        + context
        + "\n\n"
        + (payload.question or "")
    )
    asked = NovaCoreService.ask(
        db,
        organization_id=organization_id,
        mode="founder_advisor",
        question=question[:4000],
    )
    if payload.action == "prepare_email" and payload.item_id:
        link_draft(
            db,
            payload.item_id,
            NovaGovDraftLink(
                subject="Government inquiry draft",
                body=asked.answer,
            ),
            organization_id=organization_id,
            user=user,
        )
    if payload.action == "build_checklist" and payload.item_id:
        existing = {row.label.lower() for row in list_checklist(db, payload.item_id, organization_id=organization_id, user=user)}
        for label in (
            "Articles / formation document",
            "EIN letter",
            "W-9",
            "Insurance",
            "License or permit",
            "Government correspondence",
        ):
            if label.lower() not in existing:
                add_checklist(
                    db,
                    payload.item_id,
                    NovaGovChecklistCreate(label=label, document_type=label.lower()),
                    organization_id=organization_id,
                    user=user,
                )
    return NovaGovBrainOut(
        action=payload.action,
        answer=asked.answer,
        fact_label="AI SUGGESTION unless the answer cites USER-SAVED INFORMATION or VERIFIED DATA from an OFFICIAL SOURCE or CONFIRMED IN WRITING record. EXPIRED OR SUPERSEDED sources are not current. Not an official government ruling.",
        next_actions=asked.next_actions,
        generated_at=asked.generated_at,
    )


def checklist_out(row: NovaGovernmentChecklistItem) -> NovaGovChecklistOut:
    return NovaGovChecklistOut(
        checklist_id=row.checklist_id,
        item_id=row.item_id,
        label=row.label,
        document_type=row.document_type,
        completed=row.completed,
        file_id=row.file_id,
    )


def source_out(row: NovaGovernmentSource) -> NovaGovSourceOut:
    return NovaGovSourceOut(
        source_id=row.source_id,
        item_id=row.item_id,
        agency_name=row.agency_name,
        page_title=row.page_title,
        source_url=row.source_url,
        retrieved_at=row.retrieved_at,
        notes=row.notes,
        jurisdiction=row.jurisdiction,
        verification_status=row.verification_status,
    )
