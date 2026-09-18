"""Growth entities. Synthetic Phase 3. No production schema."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

LEAD_STATUSES = (
    "DISCOVERED",
    "QUALIFYING",
    "QUALIFIED",
    "DISQUALIFIED",
    "OWNER_REVIEW",
    "OUTREACH_READY",
    "CONTACTED_MOCK",
    "ENGAGED",
    "DEMO_REQUESTED",
    "DEMO_SCHEDULED",
    "PROPOSAL_READY",
    "NEGOTIATION",
    "WON",
    "LOST",
    "ON_HOLD",
    "DO_NOT_CONTACT",
    "ARCHIVED",
)

SEQUENCE_STEPS = (
    ("day_0", 0, "introduction_email"),
    ("day_3", 3, "follow_up_email"),
    ("day_7", 7, "value_reminder"),
    ("day_14", 14, "final_follow_up"),
)

OUTREACH_KINDS = (
    "introduction_email",
    "follow_up_email",
    "demo_invitation",
    "trial_invitation",
    "reactivation_message",
    "proposal_follow_up",
    "no_response_follow_up",
    "post_demo_follow_up",
    "value_reminder",
    "final_follow_up",
)

SHIELD_STATES = (
    "ALLOW_SYNTHETIC",
    "OWNER_APPROVAL_REQUIRED",
    "HUMAN_ACTION_REQUIRED",
    "BLOCK",
    "DO_NOT_CONTACT",
    "RATE_LIMIT",
    "LEGAL_REVIEW_REQUIRED",
    "PRIVACY_REVIEW_REQUIRED",
)


@dataclass
class Lead:
    lead_id: str
    organization_id: str
    owner_user_id: str
    organization_name: str
    contact_name: str
    role_title: str
    industry: str
    geography: str
    website: str | None
    email_placeholder: str | None
    phone_placeholder: str | None
    source: str
    provenance: dict[str, Any]
    source_url: str | None
    discovered_at: datetime
    business_need: str
    product_fit: str
    estimated_value: float | None
    urgency: str
    score: float
    score_explanation: dict[str, Any]
    qualification_status: str
    consent_restrictions: list[str]
    next_action: str
    follow_up_at: datetime | None
    status: str = "DISCOVERED"
    fingerprint: str = ""
    duplicate_of: str | None = None
    do_not_contact: bool = False
    opted_out: bool = False
    invalid_contact: bool = False
    owner_notes: str = ""
    nova_notes: str = ""
    last_contact_at: datetime | None = None
    conversion_reason: str | None = None
    loss_reason: str | None = None
    outreach_count: int = 0
    high_value: bool = False
    regulated: bool = False


@dataclass
class Activity:
    activity_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    kind: str
    detail: dict[str, Any]
    at: datetime


@dataclass
class OutreachMessage:
    message_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    kind: str
    body: str
    status: str
    quality: dict[str, Any]
    sent_externally: bool = False
    mock_sent: bool = False
    shield_state: str = "ALLOW_SYNTHETIC"


@dataclass
class Sequence:
    sequence_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    status: str = "ACTIVE"
    step_index: int = 0
    pause_reason: str | None = None


@dataclass
class DemoRequest:
    demo_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    requested_at: datetime
    timezone_name: str
    product: str
    demo_type: str
    status: str = "REQUESTED"
    scheduled_at: datetime | None = None
    contact_name: str = ""
    company: str = ""


@dataclass
class Quote:
    quote_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    service_id: str
    kind: str
    amount: float | None
    status: str
    body: str
    owner_action_required: bool = False
    sent_externally: bool = False


@dataclass
class Customer:
    customer_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    name: str
    product: str
    status: str = "ONBOARDING_PREPARED"
    external_account_created: bool = False
    onboarding: list[str] = field(default_factory=list)


@dataclass
class ShieldDecision:
    decision_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str | None
    action: str
    state: str
    reasons: list[str]
    explain: str
    at: datetime
    content_fingerprint: str | None = None


@dataclass
class GrowthApproval:
    approval_id: str
    organization_id: str
    owner_user_id: str
    lead_id: str
    action: str
    target_id: str
    payload_fingerprint: str
    status: str
    created_at: datetime
    expires_at: datetime | None = None
    consumed_at: datetime | None = None
