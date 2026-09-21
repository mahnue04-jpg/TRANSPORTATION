"""Work & Revenue Engine request/response schemas. Opportunity text is untrusted input."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.core.nova.work_revenue.urls import UnsafeSourceUrl, validate_source_url


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
    "NOT_SUPPORTED",
    "PROHIBITED",
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
    "statement_of_work",
    "bid_response",
    "questionnaire_response",
    "clarification_questions",
    "interview_prep",
    "owner_action_checklist",
    "owner_input_checklist",
    "client_discovery_questions",
    "work_plan",
    "weekly_report_template",
    "invoice_support_summary",
    "quote_response",
    "client_introduction",
    "project_summary",
    "executive_summary",
    "qualifications_narrative",
    "experience_narrative",
    "pricing_placeholder",
    "scope_of_work",
)

OWNER_ACTION_TYPES = (
    "CAPTCHA",
    "IDENTITY_VERIFICATION",
    "LIVE_INTERVIEW",
    "PHONE_CALL",
    "LIVE_MEETING",
    "LEGAL_SIGNATURE",
    "CONTRACT_ACCEPTANCE",
    "BANK_INFORMATION",
    "PAYOUT_SETUP",
    "TAX_INFORMATION",
    "SSN",
    "BACKGROUND_CHECK",
    "LICENSE_VERIFICATION",
    "PRICING_COMMITMENT",
    "FINANCIAL_COMMITMENT",
    "LEGAL_CERTIFICATION",
    "ACCOUNT_CREATION",
    "PLATFORM_REQUIRES_HUMAN",
    "VERIFY_BUSINESS_FACT",
    "REVIEW_DRAFT",
    "PROVIDE_MISSING_INFORMATION",
    "APPROVE_MANUAL_SUBMISSION",
    "CONFIRM_DELIVERABLE",
    "CONFIRM_CONTRACT",
    "CONFIRM_PAYMENT_RECEIVED",
    "REVIEW_WEEKLY_REPORT",
    "RESOLVE_BLOCKER",
)

REVENUE_STATUSES = (
    "NONE",
    "ESTIMATED",
    "NOT_QUOTED",
    "QUOTE_PREPARED",
    "QUOTED",
    "CONTRACT_PENDING",
    "CONTRACTED",
    "INVOICE_REQUIRED",
    "INVOICE_PREPARED",
    "INVOICE_SENT_MANUALLY",
    "PAYMENT_PENDING",
    "PARTIALLY_RECEIVED",
    "OWNER_CONFIRMED_RECEIVED",
    "RECEIVED",
    "REFUNDED",
    "CANCELLED",
)

PAYMENT_STATUSES = (
    "NONE",
    "PENDING",
    "PARTIALLY_RECEIVED",
    "OWNER_CONFIRMED_RECEIVED",
    "RECEIVED",
    "REFUNDED",
    "CANCELLED",
)

VIEW_FILTERS = (
    "new",
    "needs_review",
    "qualified",
    "not_qualified",
    "owner_action",
    "missing_information",
    "draft_ready",
    "approved",
    "submitted",
    "manually_submitted",
    "active",
    "won",
    "lost",
    "rejected",
    "archived",
    "qualifying",
    "blocked",
    "ready",
    "in_progress",
)

ENGAGEMENT_STATUSES = (
    "NOT_STARTED",
    "NEW",
    "READY",
    "ACTIVE",
    "WAITING_ON_OWNER",
    "OWNER_ACTION_REQUIRED",
    "WAITING_ON_CLIENT",
    "BLOCKED",
    "DELIVERABLE_READY",
    "PAUSED",
    "COMPLETE",
    "CANCELLED",
    "ARCHIVED",
)

TASK_STATUSES = (
    "NOT_STARTED",
    "READY",
    "BLOCKED",
    "IN_PROGRESS",
    "OWNER_REVIEW",
    "COMPLETE",
    "CANCELLED",
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
    "ENGAGEMENT_CREATED",
    "TASK_CREATED",
    "REVENUE_STATUS_CHANGED",
    "RECEIPT_CONFIRMED",
    "OPPORTUNITY_ARCHIVED",
    "OWNER_ACTION_CREATED",
    "DRAFT_CREATED",
    "DRAFT_REVISED",
    "OWNER_APPROVED",
    "OWNER_REJECTED",
    "TASK_COMPLETED",
    "DELIVERABLE_CREATED",
    "DELIVERABLE_CONFIRMED",
    "REVENUE_ESTIMATED",
    "REVENUE_CONTRACTED",
    "PAYMENT_STATUS_CHANGED",
    "REVENUE_RECEIVED_CONFIRMED",
    "ARCHIVED",
    "RECURRING_CREATED",
    "RECURRING_GENERATED",
    "RECURRING_COMPLETED",
    "REPORT_CREATED",
    "REPORT_APPROVED",
    "INVOICE_SUPPORT_CREATED",
    "INVOICE_SUPPORT_APPROVED",
    "FACT_UPDATED",
    "DISCLOSURE_ACKNOWLEDGED",
    "QUEUE_STATUS_CHANGED",
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
    compensation_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)
    compensation_period: str | None = Field(default=None, max_length=40)
    currency: str | None = Field(default=None, max_length=12)
    requirements: str | None = None
    skills_required: list[str] = Field(default_factory=list)
    credentials_required: list[str] = Field(default_factory=list)
    physical_presence_required: Literal["true", "false", "unknown"] = "unknown"
    application_deadline: datetime | None = None
    notes: str | None = Field(default=None, max_length=4000)
    estimated_value: float | None = Field(default=None, ge=0, le=1_000_000_000)
    expected_payment_frequency: str | None = Field(default=None, max_length=40)
    category: str | None = Field(default=None, max_length=40)
    priority: str = "normal"
    tags: list[str] = Field(default_factory=list)

    @field_validator("source_url")
    @classmethod
    def reject_unsafe_source_url(cls, value: str | None) -> str | None:
        if not value:
            return value
        try:
            return validate_source_url(value)
        except UnsafeSourceUrl as exc:
            raise ValueError(str(exc)) from exc


class OpportunityUpdate(BaseModel):
    organization_id: str | None = None
    status: str | None = None
    notes: str | None = Field(default=None, max_length=4000)
    follow_up_at: datetime | None = None
    interview_at: datetime | None = None
    archived: bool | None = None
    estimated_value: float | None = Field(default=None, ge=0, le=1_000_000_000)
    quoted_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)
    contract_amount: float | None = Field(default=None, ge=0, le=1_000_000_000)
    expected_payment_frequency: str | None = None
    expected_start_date: datetime | None = None
    expected_end_date: datetime | None = None
    revenue_status: str | None = None
    invoice_required: bool | None = None
    owner_confirmed_payment_received: bool | None = None
    invoice_value: float | None = None
    amount_received: float | None = None
    expenses: float | None = None
    payment_status: str | None = None
    category: str | None = Field(default=None, max_length=40)
    priority: str | None = None
    tags: list[str] | None = None
    blocked_reason: str | None = None
    archive_reason: str | None = None


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
    updated_at: datetime | None = None
    fingerprint: str | None = None
    owner_action_required: bool = False
    application_state: str | None = None
    lifecycle_outcome: str | None = None
    archived: bool = False
    estimated_value: float | None = None
    quoted_amount: float | None = None
    contract_amount: float | None = None
    expected_payment_frequency: str | None = None
    expected_start_date: datetime | None = None
    expected_end_date: datetime | None = None
    revenue_status: str = "NONE"
    invoice_required: bool = False
    owner_confirmed_payment_received: bool = False
    invoice_value: float | None = None
    amount_received: float | None = None
    expenses: float | None = None
    estimated_net: float | None = None
    confirmed_net: float | None = None
    payment_status: str = "NONE"
    missing_owner_facts: list[str] = Field(default_factory=list)
    category: str | None = None
    priority: str = "normal"
    tags: list[str] = Field(default_factory=list)
    blocked_reason: str | None = None
    archive_reason: str | None = None
    qualification_reason: str | None = None


class QualificationOut(BaseModel):
    opportunity_id: str
    outcome: str
    lifecycle_outcome: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
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
    work_split: dict[str, list[str]] = Field(default_factory=dict)
    employee_status_required: bool = False
    equipment_required: bool = False
    sensitive_data_required: bool = False
    payment_structure: str | None = None
    client_name: str | None = None
    work_summary: str | None = None
    decision: str | None = None
    evaluations: dict[str, str] = Field(default_factory=dict)
    qualified_at: datetime | None = None


class ApplicationCreate(BaseModel):
    organization_id: str | None = None
    opportunity_id: str
    applicant_party: Literal["AMICOR", "OWNER_PERSONAL"] = "AMICOR"
    notes: str | None = None


class ApplicationDecision(BaseModel):
    organization_id: str | None = None
    decision: Literal["APPROVED", "REJECTED", "NEEDS_CHANGES", "CHANGES_REQUESTED"]
    notes: str | None = None

    @field_validator("decision")
    @classmethod
    def normalize_decision(cls, value: str) -> str:
        if value == "CHANGES_REQUESTED":
            return "NEEDS_CHANGES"
        return value


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
    revision: int = 1
    parent_material_id: str | None = None


class OwnerActionOut(BaseModel):
    action_id: str
    opportunity_id: str | None
    application_id: str | None
    action_type: str
    display_label: str
    explanation: str
    status: str
    category: str | None = None
    owner_notes: str | None = None
    engagement_id: str | None = None
    ref_type: str | None = None
    ref_id: str | None = None


class AuditEventOut(BaseModel):
    event_id: str
    event_type: str
    summary: str
    ref_id: str | None
    created_at: datetime
    actor_category: str = "NOVA"
    entity_type: str | None = None
    previous_state: str | None = None
    new_state: str | None = None


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
    opportunity_title: str | None = None
    materials: list[MaterialOut] = Field(default_factory=list)
    owner_actions: list[OwnerActionOut] = Field(default_factory=list)
    owner_notes: str | None = None
    decided_at: datetime | None = None
    externally_ready: bool = False
    approved_equals_submitted: bool = False


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
    description: str = ""
    nova_can_perform: str = "NO"
    human_review_required: str = "YES"
    owner_approval_required: str = "YES"
    external_action_required: str = "NO"
    physical_presence_required: str = "NO"
    license_credential_required: str = "NO"
    sensitive_data: str = "NO"
    readiness_level: str = "UNSUPPORTED"
    examples: list[str] = Field(default_factory=list)
    unsupported_conditions: list[str] = Field(default_factory=list)


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
    rejected_or_archived: list[OpportunityOut] = Field(default_factory=list)
    opportunity_list: list[OpportunityOut] = Field(default_factory=list)
    engagements: list[dict[str, Any]] = Field(default_factory=list)
    revenue_summary: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, bool] = Field(default_factory=dict)
    revenue_placeholder: str
    identity_disclaimer: str


class TodaySummaryOut(BaseModel):
    work_opportunities: int
    applications_needing_approval: int
    follow_ups_due: int
    interviews: int
    owner_action_required: int
    work_won: int
    qualified: int = 0
    needs_owner_input: int = 0
    draft_ready: int = 0
    approved_for_future_submission: int = 0
    submitted: int = 0
    closed: int = 0
    href: str = "/nova/work"
    cards: list[dict[str, Any]] = Field(default_factory=list)
    source_counts: dict[str, int] = Field(default_factory=dict)
    approval_states: dict[str, int] = Field(default_factory=dict)
    active_engagements: int = 0
    active_tasks: int = 0
    revenue_summary: dict[str, Any] = Field(default_factory=dict)
    guardrails: dict[str, bool] = Field(default_factory=dict)
    opportunity_mode: str = "manual_simulated_only"
    live_discovery_enabled: bool = False
    external_submission_enabled: bool = False
    financial_actions_enabled: bool = False
    discovery_diagnostics: dict[str, Any] = Field(default_factory=dict)
    revenue_disclaimer: str = "Estimated pipeline is not received revenue. Nova does not collect payment."
    tasks_due: int = 0
    deliverables_pending: int = 0
    quoted_pipeline: float = 0
    contracted_revenue: float = 0
    recurring_overdue: int = 0
    reports_awaiting_review: int = 0
    invoice_support_drafts: int = 0
    blocked_work: int = 0
    owner_confirmed_received: float = 0


class ProviderOut(BaseModel):
    provider_id: str
    label: str
    phase1_enabled: bool
    notes: str
    capabilities: dict[str, bool] = Field(default_factory=dict)


class OpportunityDetailOut(BaseModel):
    tracker: TrackerOut
    missing_owner_facts: list[str]
    owner_input_checklist: list[dict[str, str]] = Field(default_factory=list)
    work_split: dict[str, list[str]] = Field(default_factory=dict)
    engagement: dict[str, Any] | None = None
    source_url_display: str | None
    source_url_fetched: bool = False
    revenue_disclaimer: str
    guardrails: dict[str, bool] = Field(default_factory=dict)


class EngagementCreate(BaseModel):
    organization_id: str | None = None
    opportunity_id: str | None = None
    client_name: str = Field(min_length=1, max_length=220)
    service: str = Field(min_length=1, max_length=220)
    frequency: str = "one_time"
    expected_payment: float | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    notes: str | None = None
    title: str | None = Field(default=None, max_length=220)
    service_type: str | None = Field(default=None, max_length=80)
    agreed_value: float | None = Field(default=None, ge=0, le=1_000_000_000)
    risks: str | None = None
    blockers: str | None = None
    priority: str = "normal"
    source: str | None = Field(default=None, max_length=80)
    due_date: datetime | None = None


class EngagementUpdate(BaseModel):
    organization_id: str | None = None
    status: str | None = None
    priority: str | None = None
    blockers: str | None = None
    notes: str | None = None
    due_date: datetime | None = None


class TaskCreate(BaseModel):
    organization_id: str | None = None
    title: str = Field(min_length=1, max_length=220)
    responsible_party: Literal["NOVA", "OWNER", "HUMAN"] = "NOVA"
    classification: Literal["NOVA", "HUMAN"] = "NOVA"
    status: str = "NOT_STARTED"
    priority: str = "normal"
    due_date: datetime | None = None
    required_owner_input: str | None = None
    deliverable: str | None = None
    review_required: bool = True
    description: str | None = None
    depends_on_task_id: str | None = None
    blocked_reason: str | None = None


class TaskUpdate(BaseModel):
    organization_id: str | None = None
    status: str | None = None
    blocked_reason: str | None = None
    owner_notes: str | None = None
    depends_on_task_id: str | None = None


class DeliverableCreate(BaseModel):
    organization_id: str | None = None
    engagement_id: str
    deliverable_type: str = "OTHER"
    description: str = Field(min_length=1, max_length=4000)
    due_date: datetime | None = None
    notes: str | None = None


class RevenueEntryCreate(BaseModel):
    organization_id: str | None = None
    engagement_id: str | None = None
    opportunity_id: str | None = None
    stage: str = "ESTIMATED"
    amount: float = Field(ge=0, le=1_000_000_000)
    currency: str = Field(default="USD", max_length=12)
    expected_payment_date: datetime | None = None
    invoice_reference: str | None = Field(default=None, max_length=120)
    owner_confirmed: bool = False
    reconciliation_notes: str | None = None


class DeliverableOut(BaseModel):
    deliverable_id: str
    engagement_id: str
    opportunity_id: str | None = None
    deliverable_type: str
    description: str
    due_date: datetime | None = None
    draft_status: str
    review_status: str
    owner_approved: bool
    delivery_status: str
    owner_confirmed_delivered: bool
    completed_at: datetime | None = None
    notes: str | None = None


class DeliverableUpdate(BaseModel):
    organization_id: str | None = None
    draft_status: str | None = None
    review_status: str | None = None
    owner_approved: bool | None = None
    notes: str | None = None


class DeliverableConfirm(BaseModel):
    organization_id: str | None = None
    owner_confirmed_delivered: bool = True
    notes: str | None = None


class OwnerCompletionRequest(BaseModel):
    organization_id: str | None = None
    owner_notes: str | None = Field(default=None, max_length=2000)


class OwnerInvoicePrepRequest(BaseModel):
    organization_id: str | None = None
    quantity: float = Field(gt=0, le=1_000_000_000)
    rate: float = Field(gt=0, le=1_000_000_000)
    currency: str = Field(default="USD", max_length=12)
    invoice_required: bool = True
    record_estimated_revenue: bool = True
    owner_notes: str | None = Field(default=None, max_length=2000)


class VoidInvoiceSupportRequest(BaseModel):
    organization_id: str | None = None
    confirm_void: Literal[True]
    owner_notes: str | None = Field(default=None, max_length=2000)


class RevenueEntryOut(BaseModel):
    entry_id: str
    engagement_id: str | None = None
    opportunity_id: str | None = None
    stage: str
    amount: float
    currency: str
    expected_payment_date: datetime | None = None
    invoice_reference: str | None = None
    received_date: datetime | None = None
    owner_confirmed: bool
    reconciliation_notes: str | None = None
    display_stage: str | None = None
    remaining_amount: float = 0
    party: str = "AMICOR"
    authoritative: bool = True
    amount_role: str = "amicor_ledger"
    processor_confirmed: bool = False


class RevenueConfirm(BaseModel):
    organization_id: str | None = None
    owner_confirmed: bool = False
    received_date: datetime | None = None
    reconciliation_notes: str | None = None
    amount: float | None = Field(default=None, ge=0, le=1_000_000_000)


class MaterialRevise(BaseModel):
    organization_id: str | None = None
    body: str = Field(min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=220)


class OwnerActionUpdate(BaseModel):
    organization_id: str | None = None
    owner_notes: str | None = None
    status: str | None = None


class AnalyticsOut(BaseModel):
    period: str
    new_opportunities: int = 0
    qualified_opportunities: int = 0
    owner_actions_pending: int = 0
    active_engagements: int = 0
    blocked_engagements: int = 0
    tasks_due: int = 0
    completed_work: int = 0
    estimated_pipeline: float = 0
    quoted_pipeline: float = 0
    contracted_revenue: float = 0
    invoiced_revenue: float = 0
    received_revenue: float = 0
    disclaimer: str = (
        "ESTIMATED != CONTRACTED. CONTRACTED != INVOICED. INVOICED != RECEIVED. "
        "Nova does not collect payment."
    )
    guardrails: dict[str, bool] = Field(default_factory=dict)


class RecurringSeriesCreate(BaseModel):
    organization_id: str | None = None
    engagement_id: str
    title: str = Field(min_length=1, max_length=220)
    frequency: str = "weekly"
    template_id: str | None = Field(default=None, max_length=80)
    next_work_date: datetime | None = None
    notes: str | None = None


class RecurringComplete(BaseModel):
    organization_id: str | None = None
    notes: str | None = None


class WeeklyReportCreate(BaseModel):
    organization_id: str | None = None
    engagement_id: str | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None


class WeeklyReportDecision(BaseModel):
    organization_id: str | None = None
    owner_notes: str | None = None


class InvoiceSupportCreate(BaseModel):
    organization_id: str | None = None
    engagement_id: str
    client_name: str | None = Field(default=None, max_length=220)
    work_period_start: datetime | None = None
    work_period_end: datetime | None = None
    deliverable_ids: list[str] = Field(default_factory=list)
    quantity: float = Field(default=1, ge=0, le=1_000_000_000)
    rate: float = Field(default=0, ge=0, le=1_000_000_000)
    adjustment_notes: str | None = None
    invoice_required: bool = True
    owner_notes: str | None = None


class InvoiceSupportDecision(BaseModel):
    organization_id: str | None = None
    owner_notes: str | None = None


class BusinessFactUpdate(BaseModel):
    organization_id: str | None = None
    value_status: str = "PROVIDED"
    value_display: str | None = Field(default=None, max_length=400)
    verification_date: datetime | None = None
    expiration_date: datetime | None = None
    source_description: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=2000)
    confirm_overwrite: bool = False


class DisclosurePolicyCreate(BaseModel):
    organization_id: str | None = None
    opportunity_id: str | None = None
    engagement_id: str | None = None
    ai_assistance_used: bool = True
    subcontractor_allowed: bool = False
    disclosure_required: bool = True
    owner_acknowledgment_required: bool = True
    notes: str | None = None


class DisclosureAcknowledge(BaseModel):
    organization_id: str | None = None
    owner_acknowledged: bool = True
    notes: str | None = None


class PlatformPolicyCreate(BaseModel):
    organization_id: str | None = None
    opportunity_id: str | None = None
    source_label: str = Field(default="unknown", max_length=120)
    login_required: bool = True
    captcha_required: bool = True
    human_submission_only: bool = True
    terms_restrict_automation: bool = True
    external_automation_unknown: bool = True
    manual_review_required: bool = True
    notes: str | None = None


class OwnerActionCreate(BaseModel):
    organization_id: str | None = None
    action_type: str
    category: str | None = None
    explanation: str = Field(min_length=1, max_length=4000)
    opportunity_id: str | None = None
    application_id: str | None = None
    engagement_id: str | None = None
    ref_type: str | None = None
    ref_id: str | None = None

