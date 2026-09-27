"""Nova Government Services. Organization/research only. No agency filing or Health writes."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import html
import json
import re
from urllib.parse import urlparse

import requests
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


def _require_workspace_project(
    db: Session,
    workspace_id: str | None,
    *,
    organization_id: str,
    user: UserContext,
) -> None:
    if not workspace_id:
        return
    query = db.query(NovaWorkspaceProject).filter(
        NovaWorkspaceProject.workspace_id == workspace_id,
        NovaWorkspaceProject.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaWorkspaceProject, user)
    if query.first() is None:
        raise NovaGovernmentError("Associated Nova Workspace project not found", status_code=404)


def _require_workspace_file(
    db: Session,
    file_id: str | None,
    *,
    organization_id: str,
    user: UserContext,
) -> None:
    if not file_id:
        return
    query = db.query(NovaWorkspaceFile).filter(
        NovaWorkspaceFile.file_id == file_id,
        NovaWorkspaceFile.organization_id == organization_id,
    )
    query = _owner_filter(query, NovaWorkspaceFile, user)
    if query.first() is None:
        raise NovaGovernmentError("Associated Nova Workspace file not found", status_code=404)


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
    _require_workspace_project(
        db,
        payload.workspace_id,
        organization_id=organization_id,
        user=user,
    )
    _require_workspace_file(
        db,
        payload.file_id,
        organization_id=organization_id,
        user=user,
    )
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
    _require_workspace_project(
        db,
        data.get("workspace_id"),
        organization_id=organization_id,
        user=user,
    )
    _require_workspace_file(
        db,
        data.get("file_id"),
        organization_id=organization_id,
        user=user,
    )
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
    _require_workspace_file(
        db,
        payload.file_id,
        organization_id=organization_id,
        user=user,
    )
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
    query = f'{payload.query.strip()} {filters} official government site:.gov'.strip()
    normalized_query = payload.query.lower().replace("/", " ").replace("-", " ")
    query_terms = {
        term for term in normalized_query.split()
        if len(term) >= 4 and term not in {"government", "official", "requirements"}
    }
    intent_groups = {
        "licensing": {"license", "licenses", "licensing", "permit", "permits"},
        "registration": {"registration", "register", "registered", "formation"},
        "tax": {"tax", "taxes", "taxation"},
        "grant": {"grant", "grants", "funding"},
        "certification": {"certification", "certifications", "certified"},
        "transportation": {"transportation", "transport", "dot", "carrier"},
    }
    required_intent_terms: set[str] = set()
    for group_terms in intent_groups.values():
        if any(term in normalized_query for term in group_terms):
            required_intent_terms.update(group_terms)
    if payload.category:
        category_key = payload.category.lower()
        for group_name, group_terms in intent_groups.items():
            if group_name in category_key or category_key in group_name:
                required_intent_terms.update(group_terms)

    web = search_web(
        query,
        max_results=10,
        news_mode=False,
        require_domains=["gov"],
        require_terms=sorted(required_intent_terms),
    )

    def rank_sources(sources: list[dict]) -> list[dict]:
        scored_sources = []
        for source in sources:
            url = str(source.get("url") or "").lower()
            if not (".gov/" in url or url.endswith(".gov")):
                continue
            haystack = " ".join(
                str(source.get(key) or "").lower() for key in ("title", "url", "snippet")
            )
            matched_terms = {term for term in query_terms if term in haystack}
            if required_intent_terms and not any(term in haystack for term in required_intent_terms):
                continue
            relevance = len(matched_terms)
            if relevance >= 2 or (relevance >= 1 and required_intent_terms):
                scored_sources.append((relevance, source))
        scored_sources.sort(key=lambda pair: pair[0], reverse=True)
        return [source for _, source in scored_sources[:4]]

    web["sources"] = rank_sources(web.get("sources") or [])

    if not web["sources"] and required_intent_terms:
        location_terms = [
            term for term in normalized_query.split()
            if len(term) >= 4
            and term not in {"business", "government", "official", "requirements"}
            and term not in required_intent_terms
        ]
        intent_terms = sorted(required_intent_terms)
        fallback_query = " ".join(
            location_terms[:3]
            + ["business"]
            + intent_terms[:4]
            + ["official", "government", "site:.gov"]
        ).strip()
        fallback_web = search_web(
            fallback_query,
            max_results=12,
            news_mode=False,
            require_domains=["gov"],
            require_terms=sorted(required_intent_terms),
        )
        fallback_sources = rank_sources(fallback_web.get("sources") or [])
        if fallback_sources:
            web["sources"] = fallback_sources
            web["status"] = fallback_web.get("status") or web.get("status")

    # Conservative official-source recovery for known government portals.
    # These are discovery links only; their presence never proves that a
    # particular license, permit, fee, document, or deadline applies.
    if not web["sources"] and required_intent_terms.intersection(intent_groups["licensing"]):
        is_minnesota = (
            "minnesota" in normalized_query
            or str(payload.state or "").strip().lower() in {"mn", "minnesota"}
        )
        if is_minnesota:
            official_candidates = [
                {
                    "title": "Business Licenses and Permits",
                    "url": "https://mn.gov/deed/business/starting-business/legal-regulatory/",
                    "label": "mn.gov",
                    "snippet": "Minnesota DEED official guidance for identifying business licenses and permits.",
                },
                {
                    "title": "Minnesota eLicense",
                    "url": "https://mn.gov/elicense/",
                    "label": "mn.gov",
                    "snippet": "Official Minnesota licensing portal for licenses, permits, registrations, and certifications.",
                },
            ]
            recovered = rank_sources(official_candidates)
            if recovered:
                web["sources"] = recovered
                web["status"] = "partial"
    # Provider summaries can include fallback/Wikipedia prose even when the final
    # links are official. Build the displayed summary only from accepted .gov hits.
    if web["sources"]:
        web["response"] = "Official government results matching your search are listed below."
    else:
        web["response"] = "No relevant official .gov result matched this search. Try the agency name, license/permit type, and state or city."
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


LEGACY_AUTO_CHECKLIST_LABELS = {
    "Articles / formation document",
    "EIN letter",
    "W-9",
    "Insurance",
    "License or permit",
    "Government correspondence",
}


def _verified_sources(
    db: Session,
    item_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> list[NovaGovernmentSource]:
    return [
        source
        for source in list_sources(db, item_id, organization_id=organization_id, user=user)
        if source.verification_status in {"official_source", "confirmed_in_writing"}
    ]


def _purge_legacy_generated_checklist(
    db: Session,
    item_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> int:
    checks = list_checklist(db, item_id, organization_id=organization_id, user=user)
    if not checks:
        return 0
    labels = {row.label for row in checks}
    if labels != LEGACY_AUTO_CHECKLIST_LABELS:
        return 0
    if any(row.completed or row.file_id for row in checks):
        return 0
    if _verified_sources(db, item_id, organization_id=organization_id, user=user):
        return 0
    deleted = (
        db.query(NovaGovernmentChecklistItem)
        .filter(
            NovaGovernmentChecklistItem.item_id == item_id,
            NovaGovernmentChecklistItem.organization_id == organization_id,
            NovaGovernmentChecklistItem.label.in_(LEGACY_AUTO_CHECKLIST_LABELS),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


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

    # Ask Nova is conversational. Do not bury a simple personal/session question
    # inside government workflow boilerplate.
    raw_question = (payload.question or "").strip()
    lowered_question = raw_question.lower()
    if payload.action == "ask" and lowered_question in {
        "what is my name", "what's my name", "whats my name", "who am i", "who am i?"
    }:
        known_names = {
            "mahnue04@gmail.com": "Saye Monibah",
        }
        email = str(getattr(user, "email", "") or "").strip().lower()
        display_name = known_names.get(email, "")
        answer = f"Your name is {display_name}." if display_name else "I do not have your name verified in this signed-in session yet."
        return NovaGovBrainOut(
            action=payload.action,
            answer=answer,
            fact_label="SIGNED-IN SESSION INFORMATION",
            next_actions=[],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    item_required_actions = {
        "explain_requirement",
        "summarize_letter",
        "find_agency",
        "missing_documents",
        "build_checklist",
        "next_step",
        "compare_levels",
        "prepare_email",
        "identify_deadlines",
    }
    if payload.action in item_required_actions and not payload.item_id:
        labels = {
            "explain_requirement": "Explain requirement",
            "summarize_letter": "Summarize letter",
            "find_agency": "Find agency",
            "missing_documents": "Missing documents",
            "build_checklist": "Build checklist",
            "next_step": "Next step",
            "compare_levels": "Compare levels",
            "prepare_email": "Draft inquiry",
            "identify_deadlines": "Identify deadlines",
        }
        return NovaGovBrainOut(
            action=payload.action,
            answer=f"{labels[payload.action]} needs a saved government work item. Open a saved item first, then run this tool so Nova uses that item's real notes, checklist, and sources.",
            fact_label="USER ACTION REQUIRED",
            next_actions=["Open a saved government work item."],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    if payload.action == "summarize_open_work":
        open_items = [row for row in items if row.status not in {"closed", "approved"}]
        lines = [
            f"- {row.title} — level {row.government_level}; category {row.category}; status {row.status}; agency {row.agency or 'not saved'}; due {row.due_date or 'none'}; renewal {row.renewal_date or 'none'}."
            for row in open_items[:20]
        ]
        answer = (
            f"USER-SAVED INFORMATION: {len(open_items)} saved open Government work item(s) found."
            + ("\n" + "\n".join(lines) if lines else "")
        )
        return NovaGovBrainOut(
            action=payload.action,
            answer=answer,
            fact_label="USER-SAVED INFORMATION. Not an official government ruling.",
            next_actions=[],
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    if payload.item_id:
        row = get_item(db, payload.item_id, organization_id=organization_id, user=user)
        _purge_legacy_generated_checklist(
            db,
            row.item_id,
            organization_id=organization_id,
            user=user,
        )
        sources = list_sources(db, row.item_id, organization_id=organization_id, user=user)
        verified = [
            source for source in sources
            if source.verification_status in {"official_source", "confirmed_in_writing"}
        ]
        verified_agencies = [source.agency_name for source in verified if source.agency_name]
        saved_checks = list_checklist(db, row.item_id, organization_id=organization_id, user=user)
        open_saved_checks = [check.label for check in saved_checks if not check.completed]
        verified_source_summary = "; ".join(
            f"{source.page_title} ({source.verification_status})"
            + (f" — {source.source_url}" if source.source_url else "")
            for source in verified[:6]
        )

        if payload.action == "explain_requirement" and verified:
            answer = (
                f"VERIFIED DATA: saved evidence includes {verified_source_summary}. "
                f"USER-SAVED INFORMATION: '{row.title}' remains a research item with status {row.status}. "
                "The saved source verifies where the research came from, but source metadata alone does not prove that a specific license, permit, document, fee, or deadline applies to this business. "
                "Capture the applicable requirement from the official page or confirmed correspondence before treating it as required."
            )
            return NovaGovBrainOut(
                action=payload.action,
                answer=answer,
                fact_label="VERIFIED SOURCE SAVED + APPLICABILITY VERIFICATION REQUIRED. Not an official government ruling.",
                next_actions=["Review the saved official source and record the specific applicable requirement."],
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        if payload.action == "explain_requirement" and not verified:
            answer = (
                f"USER-SAVED INFORMATION: '{row.title}' is a saved Government research item, not yet a verified legal requirement. "
                "VERIFIED DATA: no official or confirmed source is saved for this item. "
                "Next step: search the applicable official government source and save it before treating any license, permit, document, fee, or deadline as required."
            )
            return NovaGovBrainOut(action=payload.action, answer=answer, fact_label="USER-SAVED INFORMATION + VERIFICATION REQUIRED. Not an official government ruling.", next_actions=["Verify the requirement from an official government source."], generated_at=datetime.now(timezone.utc).isoformat())

        if payload.action == "find_agency":
            if verified_agencies:
                answer = "VERIFIED DATA from saved evidence: responsible agency/agencies: " + ", ".join(dict.fromkeys(verified_agencies)) + "."
                label = "VERIFIED DATA from saved OFFICIAL SOURCE or CONFIRMED IN WRITING evidence."
            else:
                answer = "No responsible agency is verified for this work item yet. Search official government sources for the specific activity, then save the source and agency before treating an agency as responsible."
                label = "VERIFICATION REQUIRED. No verified agency saved."
            return NovaGovBrainOut(action=payload.action, answer=answer, fact_label=label, next_actions=["Search and save an official government source."], generated_at=datetime.now(timezone.utc).isoformat())

        if payload.action in {"missing_documents", "build_checklist"}:
            if open_saved_checks:
                answer = (
                    "USER-SAVED INFORMATION: the currently saved incomplete checklist item(s) are: "
                    + ", ".join(open_saved_checks)
                    + ". "
                    + (
                        "A verified source is saved, but Nova has not stored source-derived document requirements. "
                        if verified
                        else "No verified source-derived document requirements are saved. "
                    )
                    + "Nova will not add generic documents, forms, identification, fees, zoning items, insurance, or tax registrations as government requirements without evidence that specifically supports them."
                )
                label = "USER-SAVED CHECKLIST + VERIFICATION REQUIRED. No additional requirement inferred."
            else:
                answer = (
                    "No source-derived required-document checklist is saved for this work item. "
                    + (
                        f"VERIFIED DATA: saved evidence includes {verified_source_summary}. "
                        if verified
                        else "VERIFIED DATA: no official or confirmed source is saved. "
                    )
                    + "Nova will not create a filing checklist from generic assumptions. Record only requirements explicitly supported by the official source or confirmed correspondence."
                )
                label = "VERIFICATION REQUIRED. No verified document requirements saved."
            return NovaGovBrainOut(
                action=payload.action,
                answer=answer,
                fact_label=label,
                next_actions=["Review the saved official evidence and record only explicitly supported checklist items."],
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        if payload.action == "next_step" and verified:
            answer = (
                f"VERIFIED DATA: saved evidence includes {verified_source_summary}. "
                "Next organizational step: review that official evidence and record the specific regulated activity, responsible agency, required documents, fees, and deadlines only where the source explicitly establishes them. "
                "Do not create a filing checklist or submission timeline from the page title or source status alone."
            )
            return NovaGovBrainOut(
                action=payload.action,
                answer=answer,
                fact_label="VERIFIED SOURCE SAVED + APPLICABILITY VERIFICATION REQUIRED. Not an official government ruling.",
                next_actions=["Extract and save the specific applicable requirement from the official evidence."],
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

        if payload.action == "next_step" and not verified:
            answer = (
                "Next step: verify whether this Government requirement actually applies. "
                "Use an official government source to identify the regulated activity, responsible agency, required documents, fees, and any deadlines. "
                "Do not prepare a filing checklist or submission timeline until that evidence is saved."
            )
            return NovaGovBrainOut(action=payload.action, answer=answer, fact_label="AI SUGGESTION based on missing verification. Not an official government ruling.", next_actions=["Verify the requirement from an official source."], generated_at=datetime.now(timezone.utc).isoformat())

        if payload.action == "compare_levels":
            answer = (
                f"USER-SAVED INFORMATION: this item is currently classified as {row.government_level}.\n"
                "Federal: no federal requirement verified.\n"
                "State: no additional state requirement verified beyond the saved research classification.\n"
                "County: no county requirement verified.\n"
                "City / Local: no city or local requirement verified.\n"
                "Verify each level only where the specific business activity and location make that level relevant."
            )
            return NovaGovBrainOut(action=payload.action, answer=answer, fact_label="USER-SAVED INFORMATION + VERIFICATION REQUIRED. Not an official government ruling.", next_actions=["Verify applicable jurisdictions from official sources."], generated_at=datetime.now(timezone.utc).isoformat())

        if payload.action == "identify_deadlines":
            answer = (
                f"USER-SAVED INFORMATION: due date {row.due_date or 'none recorded'}; renewal date {row.renewal_date or 'none recorded'}. "
                "No other deadline is verified from saved official or confirmed evidence."
            )
            return NovaGovBrainOut(action=payload.action, answer=answer, fact_label="USER-SAVED INFORMATION. No deadline inferred or invented.", next_actions=[] if (row.due_date or row.renewal_date) else ["Verify deadlines from an official source if this requirement applies."], generated_at=datetime.now(timezone.utc).isoformat())

        if payload.action == "summarize_letter":
            letter_sources = [
                source for source in sources
                if source.verification_status in {"confirmed_in_writing", "user_provided"}
                and any(token in (source.page_title or "").lower() for token in ("letter", "correspond", "notice", "email"))
            ]
            if not letter_sources and not row.file_id:
                return NovaGovBrainOut(
                    action=payload.action,
                    answer="No government letter or correspondence is saved to this work item to summarize. Add the letter/document or a confirmed correspondence source first.",
                    fact_label="USER ACTION REQUIRED. No letter evidence saved.",
                    next_actions=["Attach or save the government letter/correspondence."],
                    generated_at=datetime.now(timezone.utc).isoformat(),
                )

        if payload.action == "prepare_email":
            evidence_note = (
                f"I found an official source titled '{verified[0].page_title}', but I am seeking confirmation of how it applies to our specific activity. "
                if verified
                else ""
            )
            body = (
                f"Subject: Request for guidance regarding {row.title}\n\n"
                "Hello,\n\n"
                f"I am researching whether our activity is subject to the requirement described as '{row.title}'. "
                + evidence_note
                + "Please confirm whether a license, permit, registration, or other requirement applies; which agency is responsible; "
                "what documents and fees, if any, are required; and whether any filing, renewal, or response deadlines apply.\n\n"
                "Thank you."
            )
            link_draft(db, row.item_id, NovaGovDraftLink(subject=f"Inquiry regarding {row.title}", body=body), organization_id=organization_id, user=user)
            return NovaGovBrainOut(
                action=payload.action,
                answer=body,
                fact_label="AI SUGGESTION — DRAFT ONLY. No requirements assumed and nothing sent.",
                next_actions=["Review and customize the draft before any manual send."],
                generated_at=datetime.now(timezone.utc).isoformat(),
            )

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
