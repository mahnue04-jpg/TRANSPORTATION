from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ENTITY_TYPES = ("llc", "corp", "sole_prop", "partnership", "nonprofit", "other")
PROFILE_STATUSES = ("active", "inactive", "forming", "dissolved")
CUSTOMER_KINDS = ("individual", "company")
RELATIONSHIP_TYPES = ("customer", "prospect", "partner", "vendor_contact", "other")
CUSTOMER_STATUSES = ("active", "inactive", "prospect", "archived")
OPP_STATUSES = (
    "new",
    "contacted",
    "qualified",
    "meeting_scheduled",
    "proposal_needed",
    "proposal_sent",
    "negotiating",
    "won",
    "lost",
    "on_hold",
)
OPEN_OPP_STATUSES = (
    "new",
    "contacted",
    "qualified",
    "meeting_scheduled",
    "proposal_needed",
    "proposal_sent",
    "negotiating",
    "on_hold",
)
TASK_STATUSES = ("todo", "in_progress", "waiting", "blocked", "completed", "cancelled")
TASK_PRIORITIES = ("low", "normal", "high", "urgent")
DOC_KINDS = (
    "contract",
    "proposal",
    "agreement",
    "invoice",
    "insurance",
    "license",
    "certification",
    "vendor_agreement",
    "customer_document",
)
DOC_STATUSES = ("draft", "active", "expiring", "expired", "renewed", "cancelled")
VENDOR_STATUSES = ("active", "inactive", "prospective")


class NovaBizProfileCreate(BaseModel):
    business_name: str = Field(min_length=2, max_length=220)
    legal_name: str | None = Field(default=None, max_length=220)
    dba: str | None = Field(default=None, max_length=220)
    entity_type: Literal["llc", "corp", "sole_prop", "partnership", "nonprofit", "other"] = "llc"
    industry: str | None = Field(default=None, max_length=120)
    ein_reference: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=400)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    website: str | None = Field(default=None, max_length=400)
    ownership_notes: str | None = Field(default=None, max_length=4000)
    formation_date: date | None = None
    state_of_formation: str | None = Field(default=None, max_length=64)
    status: Literal["active", "inactive", "forming", "dissolved"] = "active"
    tags: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=8000)
    workspace_id: str | None = None
    government_item_id: str | None = None
    organization_id: str | None = None


class NovaBizProfileUpdate(BaseModel):
    business_name: str | None = Field(default=None, min_length=2, max_length=220)
    legal_name: str | None = None
    dba: str | None = None
    entity_type: str | None = None
    industry: str | None = None
    ein_reference: str | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    ownership_notes: str | None = None
    formation_date: date | None = None
    state_of_formation: str | None = None
    status: str | None = None
    tags: str | None = None
    notes: str | None = None
    workspace_id: str | None = None
    government_item_id: str | None = None
    organization_id: str | None = None


class NovaBizProfileOut(BaseModel):
    profile_id: str
    organization_id: str
    owner_user_id: str
    business_name: str
    legal_name: str | None
    dba: str | None
    entity_type: str
    industry: str | None
    ein_reference: str | None = None
    address: str | None
    phone: str | None
    email: str | None
    website: str | None
    ownership_notes: str | None
    formation_date: date | None
    state_of_formation: str | None
    status: str
    tags: str | None
    notes: str | None
    workspace_id: str | None
    government_item_id: str | None
    created_at: datetime
    updated_at: datetime


class NovaBizCustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=220)
    kind: Literal["individual", "company"] = "company"
    role_title: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=320)
    address: str | None = Field(default=None, max_length=400)
    relationship_type: Literal["customer", "prospect", "partner", "vendor_contact", "other"] = "customer"
    status: Literal["active", "inactive", "prospect", "archived"] = "active"
    notes: str | None = Field(default=None, max_length=8000)
    source: str | None = Field(default=None, max_length=160)
    assigned_user_id: str | None = None
    last_contact: date | None = None
    next_follow_up: date | None = None
    workspace_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaBizCustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=220)
    kind: str | None = None
    role_title: str | None = None
    phone: str | None = None
    email: str | None = None
    address: str | None = None
    relationship_type: str | None = None
    status: str | None = None
    notes: str | None = None
    source: str | None = None
    assigned_user_id: str | None = None
    last_contact: date | None = None
    next_follow_up: date | None = None
    workspace_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaBizCustomerOut(BaseModel):
    customer_id: str
    organization_id: str
    owner_user_id: str
    assigned_user_id: str | None
    kind: str
    name: str
    role_title: str | None
    phone: str | None
    email: str | None
    address: str | None
    relationship_type: str
    status: str
    notes: str | None
    source: str | None
    last_contact: date | None
    next_follow_up: date | None
    workspace_id: str | None
    conversation_id: str | None
    draft_id: str | None
    created_at: datetime
    updated_at: datetime


class NovaBizOpportunityCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    customer_id: str | None = None
    company_name: str | None = Field(default=None, max_length=220)
    source: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=8000)
    estimated_value: float = 0.0
    probability: float = 0.0
    status: Literal[
        "new",
        "contacted",
        "qualified",
        "meeting_scheduled",
        "proposal_needed",
        "proposal_sent",
        "negotiating",
        "won",
        "lost",
        "on_hold",
    ] = "new"
    expected_close_date: date | None = None
    assigned_user_id: str | None = None
    next_action: str | None = Field(default=None, max_length=240)
    next_action_date: date | None = None
    notes: str | None = Field(default=None, max_length=8000)
    workspace_id: str | None = None
    file_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaBizOpportunityUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    customer_id: str | None = None
    company_name: str | None = None
    source: str | None = None
    description: str | None = None
    estimated_value: float | None = None
    probability: float | None = None
    status: str | None = None
    expected_close_date: date | None = None
    assigned_user_id: str | None = None
    next_action: str | None = None
    next_action_date: date | None = None
    notes: str | None = None
    workspace_id: str | None = None
    file_id: str | None = None
    conversation_id: str | None = None
    organization_id: str | None = None


class NovaBizOpportunityOut(BaseModel):
    opportunity_id: str
    organization_id: str
    owner_user_id: str
    assigned_user_id: str | None
    title: str
    customer_id: str | None
    company_name: str | None
    source: str | None
    description: str | None
    estimated_value: float
    probability: float
    status: str
    expected_close_date: date | None
    next_action: str | None
    next_action_date: date | None
    notes: str | None
    workspace_id: str | None
    file_id: str | None
    conversation_id: str | None
    draft_id: str | None
    calendar_event_id: str | None
    created_at: datetime
    updated_at: datetime


class NovaBizTaskCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str | None = Field(default=None, max_length=8000)
    assigned_user_id: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    due_date: date | None = None
    status: Literal["todo", "in_progress", "waiting", "blocked", "completed", "cancelled"] = "todo"
    customer_id: str | None = None
    opportunity_id: str | None = None
    workspace_id: str | None = None
    government_item_id: str | None = None
    notes: str | None = Field(default=None, max_length=8000)
    organization_id: str | None = None


class NovaBizTaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    description: str | None = None
    assigned_user_id: str | None = None
    priority: str | None = None
    due_date: date | None = None
    status: str | None = None
    customer_id: str | None = None
    opportunity_id: str | None = None
    workspace_id: str | None = None
    government_item_id: str | None = None
    notes: str | None = None
    organization_id: str | None = None


class NovaBizTaskOut(BaseModel):
    task_id: str
    organization_id: str
    owner_user_id: str
    assigned_user_id: str | None
    title: str
    description: str | None
    priority: str
    due_date: date | None
    status: str
    customer_id: str | None
    opportunity_id: str | None
    workspace_id: str | None
    government_item_id: str | None
    draft_id: str | None
    notes: str | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class NovaBizVendorCreate(BaseModel):
    vendor_name: str = Field(min_length=2, max_length=220)
    category: str | None = Field(default=None, max_length=80)
    contact_name: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=400)
    status: Literal["active", "inactive", "prospective"] = "active"
    services: str | None = Field(default=None, max_length=4000)
    document_id: str | None = None
    government_item_id: str | None = None
    notes: str | None = Field(default=None, max_length=8000)
    organization_id: str | None = None


class NovaBizVendorOut(BaseModel):
    vendor_id: str
    vendor_name: str
    category: str | None
    contact_name: str | None
    email: str | None
    phone: str | None
    website: str | None
    status: str
    services: str | None
    document_id: str | None
    government_item_id: str | None
    notes: str | None


class NovaBizDocumentCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    kind: Literal[
        "contract",
        "proposal",
        "agreement",
        "invoice",
        "insurance",
        "license",
        "certification",
        "vendor_agreement",
        "customer_document",
    ] = "contract"
    status: Literal["draft", "active", "expiring", "expired", "renewed", "cancelled"] = "active"
    counterparty: str | None = Field(default=None, max_length=220)
    effective_date: date | None = None
    expiration_date: date | None = None
    renewal_date: date | None = None
    notes: str | None = Field(default=None, max_length=8000)
    customer_id: str | None = None
    vendor_id: str | None = None
    workspace_id: str | None = None
    file_id: str | None = None
    government_item_id: str | None = None
    organization_id: str | None = None


class NovaBizDocumentOut(BaseModel):
    document_id: str
    title: str
    kind: str
    status: str
    counterparty: str | None
    effective_date: date | None
    expiration_date: date | None
    renewal_date: date | None
    notes: str | None
    customer_id: str | None
    vendor_id: str | None
    workspace_id: str | None
    file_id: str | None
    government_item_id: str | None


class NovaBizExpenseCreate(BaseModel):
    vendor_name: str | None = Field(default=None, max_length=220)
    category: str | None = Field(default=None, max_length=80)
    expense_date: date | None = None
    amount: float = 0.0
    description: str | None = Field(default=None, max_length=4000)
    file_id: str | None = None
    workspace_id: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    organization_id: str | None = None


class NovaBizExpenseOut(BaseModel):
    expense_id: str
    vendor_name: str | None
    category: str | None
    expense_date: date | None
    amount: float
    description: str | None
    file_id: str | None
    workspace_id: str | None
    notes: str | None
    label: str = "Operational Expense Tracking — NOT Accounting"


class NovaBizMeetingCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    start_time: str
    end_time: str | None = None
    notes: str | None = Field(default=None, max_length=8000)
    customer_id: str | None = None
    opportunity_id: str | None = None
    workspace_id: str | None = None
    create_follow_up_task: bool = False
    organization_id: str | None = None


class NovaBizMeetingOut(BaseModel):
    meeting_id: str
    title: str
    start_time: datetime
    end_time: datetime | None
    notes: str | None
    customer_id: str | None
    opportunity_id: str | None
    workspace_id: str | None
    calendar_event_id: str | None


class NovaBizDraftLink(BaseModel):
    to: list[str] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=512)
    body: str = Field(default="", max_length=20000)
    customer_id: str | None = None
    opportunity_id: str | None = None
    organization_id: str | None = None


class NovaBizActivityOut(BaseModel):
    activity_id: str
    kind: str
    title: str
    ref_id: str | None
    created_at: datetime


class NovaBizPipelineOut(BaseModel):
    open_count: int
    won_count: int
    lost_count: int
    customer_count: int
    open_pipeline: float
    won_pipeline: float
    expected_revenue: float
    disclaimer: str = "Operational forecasting only. Not an accounting ledger and not a Stripe charge."


class NovaBizDashboardOut(BaseModel):
    profiles: list[NovaBizProfileOut]
    open_opportunities: list[NovaBizOpportunityOut]
    active_customers: list[NovaBizCustomerOut]
    follow_ups_due: list[NovaBizCustomerOut]
    overdue_tasks: list[NovaBizTaskOut]
    upcoming_meetings: list[NovaBizMeetingOut]
    documents_attention: list[NovaBizDocumentOut]
    completed_opportunities: list[NovaBizOpportunityOut]
    pipeline: NovaBizPipelineOut
    expense_total: float
    expense_label: str = "Operational Expense Tracking — NOT Accounting"
    government_items: list[dict[str, Any]]
    communications_recent: list[dict[str, Any]]
    communications_contacts: list[dict[str, Any]]
    vendors: list[NovaBizVendorOut]
    recent_activity: list[NovaBizActivityOut]


class NovaBizBrainRequest(BaseModel):
    action: Literal[
        "attention_today",
        "summarize_business",
        "overdue_followups",
        "top_opportunities",
        "summarize_customer",
        "prepare_meeting",
        "draft_followup",
        "summarize_contract",
        "missing_documents",
        "government_requirements",
        "next_work",
        "find_prior_work",
        "summarize_pipeline",
        "summarize_expenses",
        "operational_risks",
        "ask",
    ] = "ask"
    question: str | None = Field(default=None, max_length=4000)
    customer_id: str | None = None
    opportunity_id: str | None = None
    document_id: str | None = None
    organization_id: str | None = None


class NovaBizBrainOut(BaseModel):
    action: str
    answer: str
    fact_label: str
    next_actions: list[str] = Field(default_factory=list)
    generated_at: str
