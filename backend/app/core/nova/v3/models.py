"""Normalized V3 entities. In-memory Phase 1. No production schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


SOURCE_KINDS = (
    "job_board",
    "freelance_marketplace",
    "government_contracting",
    "grants_rfp",
    "business_lead",
    "email_import",
    "manual",
    "api",
)

CLASSIFICATIONS = (
    "NOVA_CAN_PERFORM",
    "NOVA_CAN_ASSIST",
    "HUMAN_ONLY",
    "PROHIBITED",
    "INSUFFICIENT_INFORMATION",
    "EXTERNAL_CREDENTIALS_REQUIRED",
)

LIFECYCLE = (
    "LEAD",
    "QUALIFIED",
    "APPLICATION_PREPARED",
    "OWNER_REVIEW",
    "SUBMITTED",
    "INTERVIEW",
    "WON",
    "ACTIVE",
    "DELIVERABLE_READY",
    "OWNER_APPROVAL",
    "DELIVERED",
    "INVOICED",
    "PARTIALLY_PAID",
    "PAID",
    "CLOSED",
    "CANCELLED",
    "ARCHIVED",
    "REJECTED",
)

WORK_TYPES = (
    "research_report",
    "document_preparation",
    "business_summary",
    "lead_list_organization",
    "crm_cleanup_plan",
    "proposal_preparation",
    "market_research",
    "customer_follow_up_draft",
    "administrative_reporting",
)

FROZEN = frozenset({"ARCHIVED", "CLOSED", "CANCELLED"})
PHYSICAL_TOKENS = (
    "cdl",
    "forklift",
    "lift 50",
    "on-site driving",
    "in-person only",
    "physical labor",
    "warehouse picker",
    "nurse on site",
)
PROHIBITED_TOKENS = (
    "bypass captcha",
    "weaponize",
    "undiagnosed medical treatment",
    "real money movement",
)


@dataclass
class Opportunity:
    opportunity_id: str
    organization_id: str
    owner_user_id: str
    source_kind: str
    provider_id: str
    provider_identifier: str
    title: str
    company_name: str
    description: str
    source_url: str | None
    source_evidence: str
    fetched_at: datetime
    expires_at: datetime | None
    compensation_amount: float | None
    compensation_type: str
    currency: str
    required_qualifications: list[str]
    geography: str
    remote_status: str
    terms_restrictions: str
    login_required: bool
    captcha_required: bool
    human_verification_required: bool
    rate_limited: bool
    fingerprint: str
    provenance: dict[str, Any]
    classification: str
    score: float
    status: str = "LEAD"
    duplicate_of: str | None = None
    owner_review_required: bool = True
    score_explanation: dict[str, Any] = field(default_factory=dict)
    workflow_state: str = "DISCOVERED"


@dataclass
class Client:
    client_id: str
    organization_id: str
    owner_user_id: str
    name: str
    status: str = "LEAD"


@dataclass
class Engagement:
    engagement_id: str
    organization_id: str
    owner_user_id: str
    client_id: str
    opportunity_id: str | None
    title: str
    status: str = "ACTIVE"
    expected_amount: float = 0.0
    received_amount: float = 0.0
    remaining_amount: float = 0.0
    workflow_state: str = "ACTIVE"


@dataclass
class Proposal:
    proposal_id: str
    organization_id: str
    owner_user_id: str
    opportunity_id: str
    body: str
    status: str = "APPLICATION_PREPARED"
    externally_submitted: bool = False
    mock_submitted: bool = False


@dataclass
class Approval:
    approval_id: str
    organization_id: str
    owner_user_id: str
    action: str
    target_id: str
    payload_fingerprint: str
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    consumed_at: datetime | None = None
    idempotency_key: str | None = None
    approval_type: str = "generic"


@dataclass
class WorkItem:
    work_item_id: str
    organization_id: str
    owner_user_id: str
    engagement_id: str
    work_type: str
    source_inputs: dict[str, Any]
    task_plan: list[str]
    execution_record: dict[str, Any] = field(default_factory=dict)
    quality_checks: list[str] = field(default_factory=list)
    evidence_links: list[str] = field(default_factory=list)
    deliverable: str = ""
    owner_review_status: str = "PENDING"
    delivery_status: str = "INTERNAL_ONLY"
    status: str = "PLANNED"
    quality_report: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    message_id: str
    organization_id: str
    owner_user_id: str
    channel: str
    body: str
    status: str
    sent_externally: bool = False


@dataclass
class Invoice:
    invoice_id: str
    organization_id: str
    owner_user_id: str
    engagement_id: str
    amount: float
    kind: str
    status: str
    due_at: datetime | None
    delivered_mock: bool = False
    stripe_invoice_created: bool = False


@dataclass
class PaymentEvent:
    event_id: str
    organization_id: str
    owner_user_id: str
    invoice_id: str | None
    amount: float
    event_type: str
    occurred_at: datetime
    applied_to_ledger: bool = False
    synthetic: bool = True
    late: bool = False
    duplicate: bool = False
    processor: str = "synthetic"
    stale: bool = False
    reversed: bool = False
    unknown_invoice: bool = False
    out_of_order: bool = False
    processor_mismatch: bool = False


@dataclass
class Correction:
    correction_id: str
    organization_id: str
    owner_user_id: str
    engagement_id: str
    original_amount: float
    corrected_amount: float
    reason: str
    idempotency_key: str


@dataclass
class CredentialMeta:
    credential_id: str
    organization_id: str
    owner_user_id: str
    provider: str
    credential_type: str
    authorization_scope: str
    expires_at: datetime | None
    refresh_capable: bool
    owner_approved: bool
    connection_status: str
    revoked: bool
    secret_present: bool = False
    token_stored: bool = False


@dataclass
class ScheduledJob:
    job_id: str
    organization_id: str
    owner_user_id: str
    kind: str
    period_key: str
    timezone_name: str
    status: str
    run_count: int = 0
    retry_count: int = 0
    last_error: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    attempts: int = 0
    max_attempts: int = 3
    next_run_at: datetime | None = None
    dead_letter: bool = False
    run_history: list[dict[str, Any]] = field(default_factory=list)
    frequency: str = "daily"
    ref_id: str | None = None
    paused_reason: str | None = None
