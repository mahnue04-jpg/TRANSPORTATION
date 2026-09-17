"""Authorized Nova capability registry. Claims only what this repository can actually support."""
from __future__ import annotations

from typing import Any

AVAILABLE = "AVAILABLE"
AVAILABLE_WITH_OWNER_REVIEW = "AVAILABLE_WITH_OWNER_REVIEW"
HUMAN_REQUIRED = "HUMAN_REQUIRED"
NOT_SUPPORTED = "NOT_SUPPORTED"
PROHIBITED = "PROHIBITED"

CAPABILITIES: tuple[dict[str, str], ...] = (
    {
        "capability_id": "EMAIL_DRAFTING",
        "label": "Email drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Nova Communications stores drafts only; send is refused.",
        "notes": "Drafts remain unsent until a later authorized send path exists.",
    },
    {
        "capability_id": "CALENDAR_PREPARATION",
        "label": "Calendar preparation",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Nova Business/Communications can store local meeting records.",
        "notes": "Does not book external calendars autonomously.",
    },
    {
        "capability_id": "CUSTOMER_FOLLOWUP_DRAFTING",
        "label": "Customer follow-up drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Communications draft creation exists; nothing is sent automatically.",
        "notes": "Owner must review before any future outreach.",
    },
    {
        "capability_id": "LEAD_TRACKING",
        "label": "Lead tracking",
        "availability": AVAILABLE,
        "evidence": "Nova Business OS tracks customers and opportunities.",
        "notes": "Operational tracking only, not booked revenue.",
    },
    {
        "capability_id": "RESEARCH",
        "label": "Research support",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Nova ask/summarize can organize owner-provided or local context.",
        "notes": "Does not scrape job boards or treat untrusted web text as fact.",
    },
    {
        "capability_id": "REPORTING",
        "label": "Reporting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Nova summarize/review-report paths exist for local text.",
        "notes": "Reports are drafts until owner review.",
    },
    {
        "capability_id": "DOCUMENT_PREPARATION",
        "label": "Document preparation",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Workspace files and this engine's draft materials.",
        "notes": "No autonomous filing or signature.",
    },
    {
        "capability_id": "SCHEDULING_SUPPORT",
        "label": "Scheduling support",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Local meeting/task records in Nova Business.",
        "notes": "Does not confirm external appointments without owner action.",
    },
    {
        "capability_id": "CRM_DATA_ORGANIZATION",
        "label": "CRM data organization",
        "availability": AVAILABLE,
        "evidence": "Nova Business customers, tasks, and notes.",
        "notes": "Tenant-scoped operational records only.",
    },
    {
        "capability_id": "MARKETING_DRAFTING",
        "label": "Marketing drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Text drafting from verified profile facts only.",
        "notes": "Will not invent client results or credentials.",
    },
    {
        "capability_id": "PROPOSAL_DRAFTING",
        "label": "Proposal drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "This Work & Revenue engine prepares proposal drafts.",
        "notes": "Drafts stay DRAFT until owner approval.",
    },
    {
        "capability_id": "PRESENTATION_DRAFTING",
        "label": "Presentation drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Work-sample/outline drafts only.",
        "notes": "No slide-deck generation claimed beyond outlines.",
    },
    {
        "capability_id": "ADMINISTRATIVE_SUPPORT",
        "label": "Administrative support",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Task, document, and follow-up organization in Nova.",
        "notes": "Owner review required for external actions.",
    },
    {
        "capability_id": "DATA_SUMMARIZATION",
        "label": "Data summarization",
        "availability": AVAILABLE,
        "evidence": "Nova summarize APIs operate on provided text.",
        "notes": "Untrusted opportunity text is labeled untrusted.",
    },
    {
        "capability_id": "PHYSICAL_LABOR",
        "label": "Physical labor",
        "availability": NOT_SUPPORTED,
        "evidence": "Nova is a software system with no physical body.",
        "notes": "On-site, warehouse, lifting, and similar work cannot be performed by Nova.",
    },
    {
        "capability_id": "DRIVING",
        "label": "Driving",
        "availability": PROHIBITED,
        "evidence": "Nova cannot operate a vehicle. AMICOR Health/Delivery driving is a separate human workflow.",
        "notes": "Do not apply Nova as a driver.",
    },
    {
        "capability_id": "LICENSED_PROFESSIONAL_PRACTICE",
        "label": "Licensed professional practice",
        "availability": PROHIBITED,
        "evidence": "No verified professional licenses are stored for Nova.",
        "notes": "Nursing, medicine, law, CPA, and similar practice are prohibited claims.",
    },
    {
        "capability_id": "AUTONOMOUS_APPLICATION_SUBMISSION",
        "label": "Autonomous application submission",
        "availability": PROHIBITED,
        "evidence": "Phase 1 explicitly disables external submission.",
        "notes": "Approved means APPROVED_FOR_FUTURE_SUBMISSION only.",
    },
    {
        "capability_id": "CAPTCHA_OR_IDENTITY_BYPASS",
        "label": "CAPTCHA or identity bypass",
        "availability": PROHIBITED,
        "evidence": "Security policy. Escalate as OWNER ACTION REQUIRED.",
        "notes": "Never attempt to bypass CAPTCHA or identity controls.",
    },
    {
        "capability_id": "FINANCIAL_TRANSACTIONS",
        "label": "Financial transactions",
        "availability": PROHIBITED,
        "evidence": "Billing and payment-processor work is owned by a separate agent and is out of scope.",
        "notes": "No invoices, bank transfers, or payment collection in this engine.",
    },
    {
        "capability_id": "QUESTIONNAIRE_DRAFTING",
        "label": "Questionnaire drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "This engine drafts questionnaire responses from verified facts only.",
        "notes": "Unknown answers are marked OWNER INPUT REQUIRED.",
    },
    {
        "capability_id": "RFP_RESPONSE_PREPARATION",
        "label": "RFP response preparation",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Bid/RFP draft materials are prepared locally and remain DRAFT.",
        "notes": "Nova will not submit an RFP response.",
    },
    {
        "capability_id": "SOW_DRAFTING",
        "label": "Statement of work drafting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "SOW outlines are drafted as internal documents only.",
        "notes": "Not a signed contract. Owner must review every term.",
    },
    {
        "capability_id": "BID_PREPARATION",
        "label": "Bid preparation",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Bid drafts never include a committed price unless the owner entered one.",
        "notes": "Pricing remains OWNER INPUT REQUIRED.",
    },
    {
        "capability_id": "MEETING_PREPARATION",
        "label": "Meeting and appointment preparation",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Interview/meeting notes can be drafted from verified capabilities.",
        "notes": "Nova cannot attend live meetings.",
    },
    {
        "capability_id": "WEEKLY_CLIENT_REPORTING",
        "label": "Weekly client reporting",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Weekly report templates are local drafts.",
        "notes": "Does not contact the client. Owner must send any report.",
    },
    {
        "capability_id": "INVOICE_PREPARATION_SUPPORT",
        "label": "Invoice preparation support",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Internal invoice-support summaries from owner-entered amounts only.",
        "notes": "Does not create, send, or collect invoices. No Stripe.",
    },
    {
        "capability_id": "REVENUE_TRACKING_SUPPORT",
        "label": "Revenue tracking support",
        "availability": AVAILABLE,
        "evidence": "Owner-entered estimates, quotes, contracts, and confirmed receipts.",
        "notes": "Estimated pipeline is never mixed with received revenue.",
    },
    {
        "capability_id": "BUSINESS_INTELLIGENCE_SUMMARIES",
        "label": "Business intelligence summaries",
        "availability": AVAILABLE_WITH_OWNER_REVIEW,
        "evidence": "Summarization of owner-provided or local operational text.",
        "notes": "Does not invent metrics, customers, or revenue.",
    },
)


def _structured(item: dict[str, str]) -> dict[str, Any]:
    availability = item["availability"]
    if availability == AVAILABLE:
        nova_can = "YES"
        human_review = "NO"
        readiness = "SUPPORTED"
    elif availability == AVAILABLE_WITH_OWNER_REVIEW:
        nova_can = "PARTIAL"
        human_review = "YES"
        readiness = "PARTIALLY_SUPPORTED"
    elif availability == HUMAN_REQUIRED:
        nova_can = "NO"
        human_review = "YES"
        readiness = "HUMAN_REQUIRED"
    elif availability == PROHIBITED:
        nova_can = "NO"
        human_review = "YES"
        readiness = "UNSUPPORTED"
    else:
        nova_can = "NO"
        human_review = "YES"
        readiness = "UNSUPPORTED"
    return {
        **item,
        "description": item.get("notes") or item["label"],
        "nova_can_perform": nova_can,
        "human_review_required": human_review,
        "owner_approval_required": "NO" if availability == AVAILABLE else "YES",
        "external_action_required": "NO",
        "physical_presence_required": "YES" if item["capability_id"] in {"PHYSICAL_LABOR", "DRIVING"} else "NO",
        "license_credential_required": "YES" if item["capability_id"] in {"LICENSED_PROFESSIONAL_PRACTICE", "DRIVING"} else "NO",
        "sensitive_data": "POSSIBLE" if item["capability_id"] in {"INVOICE_PREPARATION_SUPPORT", "REVENUE_TRACKING_SUPPORT"} else "NO",
        "readiness_level": readiness,
        "examples": [item["label"]],
        "unsupported_conditions": (
            ["Any live send, signature, payment, or impersonation"]
            if availability != PROHIBITED
            else [item["notes"]]
        ),
    }


def list_capabilities() -> list[dict[str, Any]]:
    return [_structured(item) for item in CAPABILITIES]


def capability_map() -> dict[str, dict[str, Any]]:
    return {item["capability_id"]: item for item in list_capabilities()}


def availability_for(capability_id: str) -> str:
    item = capability_map().get(capability_id)
    return item["availability"] if item else NOT_SUPPORTED


def nova_supported_ids() -> set[str]:
    return {
        item["capability_id"]
        for item in CAPABILITIES
        if item["availability"] in {AVAILABLE, AVAILABLE_WITH_OWNER_REVIEW}
    }


def registry_snapshot() -> dict[str, Any]:
    return {
        "capabilities": list_capabilities(),
        "policy": (
            "Nova is an AI system/tool under AMICOR/owner authorization. "
            "It is not a human employee and must not claim unverified credentials."
        ),
    }
