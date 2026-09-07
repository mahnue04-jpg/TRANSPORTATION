"""Driver policy acknowledgment catalog.

Legal bodies are DRAFT FOR ATTORNEY REVIEW placeholders — not final counsel-approved
language. Do not treat these texts as enforceable contracts until attorney review.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.helpers import now

POLICY_PACK_VERSION = "DRAFT-ATTORNEY-REVIEW-2026.1"
DRAFT_BANNER = "DRAFT FOR ATTORNEY REVIEW — not final legal language."

# ICA is handled by work_setup e-sign; listed here for portal completeness only.
ICA_POLICY_KEY = "independent_contractor_agreement"

REQUIRED_POLICY_KEYS: tuple[str, ...] = (
    "driver_code_of_conduct",
    "safety_policy",
    "drug_alcohol_prohibited_conduct",
    "accident_incident_reporting",
    "customer_privacy_confidentiality",
    "delivery_prohibited_items",
    "no_discrimination_harassment",
    "vehicle_insurance_maintenance",
    "platform_use_account_security",
    "suspension_deactivation_rules",
)

POLICY_CATALOG: tuple[dict[str, str], ...] = (
    {
        "key": ICA_POLICY_KEY,
        "title": "Independent Contractor Agreement",
        "summary": (
            "Defines independent-contractor status, services, compensation, taxes, "
            "and compliance expectations. Signed electronically in Work setup."
        ),
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Full Independent Contractor Agreement text is presented and signed in the "
            "Work setup step (version AMICOR-ICA-2026.1). Attorney review still required "
            "before public recruiting treats this as final."
        ),
        "satisfied_by": "work_setup_ica",
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "driver_code_of_conduct",
        "title": "Driver Code of Conduct",
        "summary": "Professional conduct expectations while representing Amicor on trips.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must treat riders, caregivers, and partners with respect; follow "
            "dispatch instructions; avoid unsafe driving; and never misuse rider information. "
            "Detailed enforceable standards require attorney review before public recruiting."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "safety_policy",
        "title": "Safety Policy",
        "summary": "Vehicle, passenger, and roadway safety expectations.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must operate a safe vehicle, use seat belts as required by law, "
            "avoid distracted driving, and report unsafe conditions promptly. "
            "Final safety policy language requires attorney and operations review."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "drug_alcohol_prohibited_conduct",
        "title": "Drug / Alcohol / Prohibited Conduct Policy",
        "summary": "Zero-tolerance expectations for impairment and prohibited conduct.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must not operate while impaired by alcohol, illegal drugs, or other "
            "substances that reduce safe driving ability. Prohibited conduct includes "
            "violence, theft, and illegal activity during platform work. "
            "Attorney review is required before this draft is published as binding policy."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "accident_incident_reporting",
        "title": "Accident / Incident Reporting Policy",
        "summary": "Immediate reporting expectations after collisions or rider incidents.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must report accidents, injuries, and significant incidents to Amicor "
            "as soon as safely possible and cooperate with required documentation. "
            "Formal reporting timelines and legal duties require attorney review."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "customer_privacy_confidentiality",
        "title": "Customer Privacy / Confidentiality",
        "summary": "Protect rider and patient information learned during trips.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must not share rider names, addresses, health-related details, or "
            "trip purpose except as needed to complete the trip or as required by law. "
            "HIPAA/privacy counsel should review before public recruiting."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "delivery_prohibited_items",
        "title": "Delivery Prohibited-Items Policy",
        "summary": "Items that must not be transported if delivery work is offered.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "If delivery assignments are offered, drivers must refuse illegal, hazardous, "
            "or otherwise prohibited items. This draft is not a complete hazmat or "
            "prohibited-items schedule — attorney and operations review required."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "no_discrimination_harassment",
        "title": "No Discrimination / Harassment Policy",
        "summary": "Equal treatment and harassment-free service expectations.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must not discriminate or harass based on protected characteristics "
            "under applicable law. Complaints may result in review and deactivation. "
            "Final policy language requires attorney review."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "vehicle_insurance_maintenance",
        "title": "Vehicle / Insurance Maintenance Responsibility",
        "summary": "Driver responsibility to keep vehicle and insurance current.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must maintain a roadworthy vehicle, current registration, and "
            "required insurance for Amicor trips, and promptly upload updated proof "
            "when documents change or expire. Coverage minimums require business review."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "platform_use_account_security",
        "title": "Platform Use / Account Security",
        "summary": "Account sharing and credential security rules.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Drivers must not share login credentials, must protect device access, and "
            "must only use Amicor tools for authorized work. Detailed terms require "
            "attorney review."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
    {
        "key": "suspension_deactivation_rules",
        "title": "Suspension / Deactivation Rules",
        "summary": "When Amicor may suspend or deactivate driver access.",
        "body": (
            f"{DRAFT_BANNER}\n\n"
            "Amicor may suspend or deactivate access for safety, compliance, documentation, "
            "or policy concerns pending review. Appeal and notice procedures require "
            "attorney review before public recruiting."
        ),
        "legal_status": "DRAFT_FOR_ATTORNEY_REVIEW",
    },
)


def policy_catalog_payload() -> dict[str, Any]:
    return {
        "pack_version": POLICY_PACK_VERSION,
        "legal_notice": DRAFT_BANNER,
        "attorney_review_required_before_public_recruiting": True,
        "policies": [dict(item) for item in POLICY_CATALOG],
        "required_acknowledgment_keys": list(REQUIRED_POLICY_KEYS),
    }


def _parse_acks(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def serialize_policy_acknowledgments(
    application: Any,
    *,
    ica_signed: bool = False,
) -> dict[str, Any]:
    stored = _parse_acks(getattr(application, "policy_acknowledgments_json", None))
    items = []
    missing = []
    for policy in POLICY_CATALOG:
        key = policy["key"]
        if key == ICA_POLICY_KEY:
            accepted = bool(ica_signed)
            record = {"accepted": accepted, "satisfied_by": "work_setup_ica"} if accepted else None
        else:
            record = stored.get(key) if isinstance(stored.get(key), dict) else None
            accepted = bool(record and record.get("accepted_at"))
        if key in REQUIRED_POLICY_KEYS and not accepted:
            missing.append(key)
        items.append(
            {
                "key": key,
                "title": policy["title"],
                "summary": policy["summary"],
                "legal_status": policy["legal_status"],
                "draft_banner": DRAFT_BANNER,
                "accepted": accepted,
                "accepted_at": (record or {}).get("accepted_at"),
                "version": (record or {}).get("version") or POLICY_PACK_VERSION,
                "required": key in REQUIRED_POLICY_KEYS or key == ICA_POLICY_KEY,
            }
        )
    return {
        "pack_version": POLICY_PACK_VERSION,
        "legal_notice": DRAFT_BANNER,
        "attorney_review_required_before_public_recruiting": True,
        "all_required_accepted": len(missing) == 0 and ica_signed,
        "missing_keys": missing if ica_signed else missing + ([ICA_POLICY_KEY] if not ica_signed else []),
        "items": items,
    }


def acknowledge_policies(
    application: Any,
    *,
    policy_keys: list[str],
    typed_name: str,
    accept_draft_notice: bool,
) -> dict[str, Any]:
    if not accept_draft_notice:
        raise ValueError("You must acknowledge that these policies are drafts for attorney review.")
    name = str(typed_name or "").strip()
    if len(name) < 2:
        raise ValueError("Typed legal name is required to acknowledge policies.")
    allowed = {item["key"] for item in POLICY_CATALOG if item["key"] != ICA_POLICY_KEY}
    keys = [str(key).strip() for key in policy_keys if str(key).strip()]
    if not keys:
        raise ValueError("Select at least one policy to acknowledge.")
    unknown = [key for key in keys if key not in allowed]
    if unknown:
        raise ValueError(f"Unknown policy keys: {', '.join(unknown)}")
    stored = _parse_acks(getattr(application, "policy_acknowledgments_json", None))
    stamp = now().isoformat()
    for key in keys:
        stored[key] = {
            "accepted_at": stamp,
            "version": POLICY_PACK_VERSION,
            "typed_name": name,
            "draft_notice_accepted": True,
        }
    application.policy_acknowledgments_json = json.dumps(stored)
    application.updated_at = now()
    return stored


def required_policies_complete(application: Any, *, ica_signed: bool) -> bool:
    summary = serialize_policy_acknowledgments(application, ica_signed=ica_signed)
    return bool(summary.get("all_required_accepted"))
