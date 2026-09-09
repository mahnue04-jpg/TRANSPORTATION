from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

GOV_STATUSES = (
    "researching",
    "requirements_found",
    "documents_needed",
    "ready_to_file",
    "submitted",
    "waiting_response",
    "approved",
    "denied",
    "renewal_due",
    "closed",
)
GOV_LEVELS = ("federal", "state", "county", "city", "local")
GOV_CATEGORIES = (
    "licensing",
    "permits",
    "taxes",
    "grants",
    "certifications",
    "transportation",
    "business_registration",
    "compliance",
    "benefits",
    "forms",
    "other",
)
VERIFICATION_STATES = (
    "unverified",
    "user_provided",
    "official_source",
    "confirmed_in_writing",
    "expired_or_superseded",
)
FILING_STATUSES = ("not_filed", "drafted", "ready", "submitted", "paid_elsewhere", "not_applicable")


class NovaGovWorkCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    agency: str | None = Field(default=None, max_length=220)
    government_level: Literal["federal", "state", "county", "city", "local"] = "state"
    state: str | None = Field(default=None, max_length=64)
    county: str | None = Field(default=None, max_length=120)
    city: str | None = Field(default=None, max_length=120)
    category: Literal[
        "licensing",
        "permits",
        "taxes",
        "grants",
        "certifications",
        "transportation",
        "business_registration",
        "compliance",
        "benefits",
        "forms",
        "other",
    ] = "compliance"
    description: str | None = Field(default=None, max_length=8000)
    source_reference: str | None = Field(default=None, max_length=500)
    status: Literal[
        "researching",
        "requirements_found",
        "documents_needed",
        "ready_to_file",
        "submitted",
        "waiting_response",
        "approved",
        "denied",
        "renewal_due",
        "closed",
    ] = "researching"
    due_date: date | None = None
    renewal_date: date | None = None
    filing_status: Literal["not_filed", "drafted", "ready", "submitted", "paid_elsewhere", "not_applicable"] = "not_filed"
    notes: str | None = Field(default=None, max_length=8000)
    assigned_user_id: str | None = None
    workspace_id: str | None = None
    file_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaGovWorkUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    agency: str | None = None
    government_level: Literal["federal", "state", "county", "city", "local"] | None = None
    state: str | None = None
    county: str | None = None
    city: str | None = None
    category: str | None = None
    description: str | None = None
    source_reference: str | None = None
    status: str | None = None
    due_date: date | None = None
    renewal_date: date | None = None
    filing_status: str | None = None
    notes: str | None = None
    assigned_user_id: str | None = None
    workspace_id: str | None = None
    file_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaGovWorkOut(BaseModel):
    item_id: str
    organization_id: str
    owner_user_id: str
    assigned_user_id: str | None
    title: str
    agency: str | None
    government_level: str
    state: str | None
    county: str | None
    city: str | None
    category: str
    description: str | None
    source_reference: str | None
    status: str
    due_date: date | None
    renewal_date: date | None
    filing_status: str
    notes: str | None
    workspace_id: str | None
    file_id: str | None
    conversation_id: str | None
    draft_id: str | None
    calendar_event_id: str | None
    created_at: datetime
    updated_at: datetime


class NovaGovChecklistCreate(BaseModel):
    label: str = Field(min_length=2, max_length=220)
    document_type: str | None = Field(default=None, max_length=64)
    file_id: str | None = None
    organization_id: str | None = None


class NovaGovChecklistOut(BaseModel):
    checklist_id: str
    item_id: str
    label: str
    document_type: str | None
    completed: bool
    file_id: str | None


class NovaGovSourceCreate(BaseModel):
    agency_name: str | None = Field(default=None, max_length=220)
    page_title: str = Field(min_length=2, max_length=240)
    source_url: str | None = Field(default=None, max_length=700)
    notes: str | None = Field(default=None, max_length=4000)
    jurisdiction: str | None = Field(default=None, max_length=180)
    verification_status: Literal[
        "unverified",
        "user_provided",
        "official_source",
        "confirmed_in_writing",
        "expired_or_superseded",
    ] = "unverified"
    organization_id: str | None = None


class NovaGovSourceOut(BaseModel):
    source_id: str
    item_id: str
    agency_name: str | None
    page_title: str
    source_url: str | None
    retrieved_at: datetime
    notes: str | None
    jurisdiction: str | None
    verification_status: str


class NovaGovProgramCreate(BaseModel):
    program_name: str = Field(min_length=2, max_length=240)
    agency: str | None = Field(default=None, max_length=220)
    eligibility: str | None = Field(default=None, max_length=4000)
    amount_range: str | None = Field(default=None, max_length=120)
    deadline: date | None = None
    status: str = "researching"
    requirements: str | None = Field(default=None, max_length=4000)
    attachments_note: str | None = Field(default=None, max_length=2000)
    contact_info: str | None = Field(default=None, max_length=320)
    notes: str | None = Field(default=None, max_length=4000)
    organization_id: str | None = None


class NovaGovProgramOut(BaseModel):
    program_id: str
    program_name: str
    agency: str | None
    eligibility: str | None
    amount_range: str | None
    deadline: date | None
    status: str
    requirements: str | None
    attachments_note: str | None
    contact_info: str | None
    notes: str | None


class NovaGovDraftLink(BaseModel):
    to: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=20000)
    organization_id: str | None = None


class NovaGovSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=400)
    government_level: str | None = None
    category: str | None = None
    state: str | None = None
    organization_id: str | None = None


class NovaGovDashboardOut(BaseModel):
    sections: list[dict[str, Any]]
    saved_work: list[NovaGovWorkOut]
    upcoming_deadlines: list[NovaGovWorkOut]
    renewals: list[NovaGovWorkOut]
    overdue: list[NovaGovWorkOut]
    waiting_response: list[NovaGovWorkOut]
    recently_completed: list[NovaGovWorkOut]
    programs: list[NovaGovProgramOut]


class NovaGovBrainRequest(BaseModel):
    action: Literal[
        "explain_requirement",
        "summarize_letter",
        "find_agency",
        "missing_documents",
        "build_checklist",
        "next_step",
        "compare_levels",
        "summarize_correspondence",
        "prepare_questions",
        "prepare_email",
        "identify_deadlines",
        "summarize_open_work",
        "search_prior_work",
        "ask",
    ] = "ask"
    question: str | None = Field(default=None, max_length=4000)
    item_id: str | None = None
    organization_id: str | None = None


class NovaGovBrainOut(BaseModel):
    action: str
    answer: str
    fact_label: str
    next_actions: list[str] = Field(default_factory=list)
    generated_at: str
