"""Work & Revenue Engine request/response schemas. Opportunity text is untrusted input."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


OPPORTUNITY_STATUSES = (
    "DISCOVERED",
    "REVIEWING",
    "QUALIFIED",
    "NOT_QUALIFIED",
    "OWNER_REVIEW",
    "APPROVED_TO_APPLY",
    "APPLICATION_PREPARED",
    "SUBMITTED",
    "FOLLOW_UP_DUE",
    "INTERVIEW",
    "OFFER",
    "WON",
    "REJECTED",
    "CLOSED",
)

QUALIFICATION_OUTCOMES = (
    "NOVA_CAN_PERFORM",
    "NOVA_WITH_OWNER_REVIEW",
    "HUMAN_REQUIRED",
    "NOT_SUITABLE",
    "INSUFFICIENT_INFORMATION",
)

APPROVAL_STATES = (
    "DRAFT",
    "READY_FOR_OWNER_REVIEW",
    "APPROVED",
    "REJECTED",
    "NEEDS_CHANGES",
)

MATERIAL_KINDS = (
    "capability_statement",
    "resume",
    "cover_letter",
    "proposal",
    "application_responses",
    "work_sample_outline",
    "follow_up_message",
)

OWNER_ACTION_TYPES = (
    "CAPTCHA",
    "IDENTITY_VERIFICATION",
    "LIVE_INTERVIEW",
    "LEGAL_SIGNATURE",
    "CONTRACT_ACCEPTANCE",
    "BANK_INFORMATION",
    "TAX_INFORMATION",
    "SSN",
    "BACKGROUND_CHECK",
    "LICENSE_VERIFICATION",
    "PRICING_COMMITMENT",
    "FINANCIAL_COMMITMENT",
    "LEGAL_CERTIFICATION",
    "PLATFORM_REQUIRES_HUMAN",
)

SOURCE_TYPES = (
    "manual",
    "simulated",
    "approved_api",
    "career_page",
    "rfp",
    "freelance_marketplace",
    "imported",
)

APPLICANT_PARTIES = ("AMICOR", "OWNER_PERSONAL")

PHYSICAL_PRESENCE_VALUES = ("true", "false", "unknown")

AUDIT_EVENT_TYPES = (
    "OPPORTUNITY_CREATED",
    "OPPORTUNITY_QUALIFIED",
    "APPLICATION_DRAFT_CREATED",
    "APPLICATION_READY_FOR_REVIEW",
    "OWNER_APPROVED_APPLICATION",
    "OWNER_REJECTED_APPLICATION",
    "OWNER_ACTION_REQUIRED",
    "APPLICATION_STATUS_CHANGED",
)


class OpportunityCreate(BaseModel):
    organization_id: str | None = None
    source: str = "manual"
    source_url: str | None = Field(default=None, max_length=800)
    source_type: str = "manual"
    company_name: str = Field(min_length=1, max_length=220)
    opportunity_title: str = Field(min_length=1, max_length=220)
    description: str | None = None
    location: str | None = Field(default=None, max_length=220)
    remote_status: str | None = Field(default=None, max_length=40)
    engagement_type: str | None = Field(default=None, max_length=40)
    compensation_type: str | None = Field(default=None, max_length=40)
    compensation_amount: float | None = None
    compensation_period: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=12)
    requirements: str | None = None
    skills_required: list[str] = Field(default_factory=list)
    credentials_required: list[str] = Field(default_factory=list)
    physical_presence_required: Literal["true", "false", "unknown"] = "unknown"
    application_deadline: datetime | None = None
    notes: str | None = None


class OpportunityUpdate(BaseModel):
    organization_id: str | None = None
    status: str | None = None
    notes: str | None = None
    follow_up_at: datetime | None = None
    interview_at: datetime | None = None


class OpportunityOut(BaseModel):
    opportunity_id: str
    organization_id: str
    source: str
    source_url: str | None
    source_type: str
    company_name: str
    opportunity_title: str
    description: str | None
    location: str | None
    remote_status: str | None
    engagement_type: str | None
    compensation_type: str | None
    compensation_amount: float | None
    compensation_period: str | None
    currency: str | None
    requirements: str | None
    skills_required: list[str]
    credentials_required: list[str]
    physical_presence_required: str
    application_deadline: datetime | None
    discovered_at: datetime
    status: str
    notes: str | None
    qualification_outcome: str | None
    qualification: dict[str, Any] | None = None
    follow_up_at: datetime | None
    interview_at: datetime | None


class QualificationOut(BaseModel):
    opportunity_id: str
    outcome: str
    nova_task_share: str
    owner_participation: list[str]
    other_human_required: list[str]
    physical_presence_required: str
    credentials_required: list[str]
    licenses_required: bool
    driving_required: bool
    regulated_professional_judgment_required: bool
    identity_verification_required: bool
    human_interview_required: bool
    compensation_understandable: bool
    missing_information: list[str]
    nova_tasks: list[str]
    owner_tasks: list[str]
    human_tasks: list[str]
    reasons: list[str]
    owner_actions: list[str]
    deceptive_score_used: bool = False


class ApplicationCreate(BaseModel):
    organization_id: str | None = None
    opportunity_id: str
    applicant_party: Literal["AMICOR", "OWNER_PERSONAL"] = "AMICOR"
    notes: str | None = None


class ApplicationDecision(BaseModel):
    organization_id: str | None = None
    decision: Literal["APPROVED", "REJECTED", "NEEDS_CHANGES"]
    notes: str | None = None


class ApplicationStatusUpdate(BaseModel):
    organization_id: str | None = None
    status: str
    follow_up_at: datetime | None = None
    interview_at: datetime | None = None
    notes: str | None = None


class MaterialOut(BaseModel):
    material_id: str
    application_id: str
    kind: str
    title: str
    body: str
    status: str
    owner_input_required: bool


class OwnerActionOut(BaseModel):
    action_id: str
    opportunity_id: str | None
    application_id: str | None
    action_type: str
    display_label: str
    explanation: str
    status: str


class AuditEventOut(BaseModel):
    event_id: str
    event_type: str
    summary: str
    ref_id: str | None
    created_at: datetime


class StatusHistoryOut(BaseModel):
    history_id: str
    ref_type: str
    ref_id: str
    from_status: str | None
    to_status: str
    note: str | None
    created_at: datetime


class ApplicationOut(BaseModel):
    application_id: str
    opportunity_id: str
    organization_id: str
    applicant_party: str
    approval_state: str
    approved_for_future_submission: bool
    externally_submitted: bool
    manual_submission_recorded: bool
    follow_up_at: datetime | None
    interview_at: datetime | None
    notes: str | None
    materials: list[MaterialOut] = Field(default_factory=list)
    owner_actions: list[OwnerActionOut] = Field(default_factory=list)


class TrackerOut(BaseModel):
    opportunity: OpportunityOut
    application: ApplicationOut | None
    approval_state: str | None
    application_status: str
    follow_up_at: datetime | None
    interview_at: datetime | None
    owner_actions: list[OwnerActionOut]
    notes: str | None
    status_history: list[StatusHistoryOut]


class CapabilityOut(BaseModel):
    capability_id: str
    label: str
    availability: str
    evidence: str
    notes: str


class DashboardOut(BaseModel):
    counts: dict[str, int]
    opportunity_inbox: list[OpportunityOut]
    qualified_work: list[OpportunityOut]
    applications: list[ApplicationOut]
    owner_approvals: list[ApplicationOut]
    follow_ups: list[OpportunityOut]
    interviews: list[OpportunityOut]
    won_work: list[OpportunityOut]
    owner_actions: list[OwnerActionOut]
    revenue_placeholder: str
    identity_disclaimer: str


class TodaySummaryOut(BaseModel):
    work_opportunities: int
    applications_needing_approval: int
    follow_ups_due: int
    interviews: int
    owner_action_required: int
    work_won: int
    href: str = "/nova/work"


class ProviderOut(BaseModel):
    provider_id: str
    label: str
    phase1_enabled: bool
    notes: str
