"""Structured owner/business fact requirements. No real sensitive values are stored here."""
from __future__ import annotations

from typing import Any

from app.core.nova.work_revenue.lifecycle import FACT_STATUSES, FACT_VALUE_STATUSES
from app.core.nova.work_revenue.verified_profile import OWNER_INPUT_REQUIRED, profile_snapshot

FACT_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"fact_id": "legal_business_name", "label": "Legal business name", "sensitivity": "normal"},
    {"fact_id": "dba", "label": "DBA / trade name", "sensitivity": "normal"},
    {"fact_id": "address", "label": "Business address", "sensitivity": "normal"},
    {"fact_id": "service_areas", "label": "Service areas", "sensitivity": "normal"},
    {"fact_id": "business_age", "label": "Business age", "sensitivity": "normal"},
    {"fact_id": "ownership", "label": "Ownership", "sensitivity": "normal"},
    {"fact_id": "insurance", "label": "Insurance", "sensitivity": "normal"},
    {"fact_id": "licenses", "label": "Licenses", "sensitivity": "normal"},
    {"fact_id": "certifications", "label": "Certifications", "sensitivity": "normal"},
    {"fact_id": "relevant_experience", "label": "Relevant experience", "sensitivity": "normal"},
    {"fact_id": "references", "label": "References", "sensitivity": "normal"},
    {"fact_id": "pricing", "label": "Pricing", "sensitivity": "normal"},
    {"fact_id": "rates", "label": "Rates", "sensitivity": "normal"},
    {"fact_id": "availability", "label": "Availability", "sensitivity": "normal"},
    {"fact_id": "workforce", "label": "Workforce", "sensitivity": "normal"},
    {"fact_id": "equipment", "label": "Equipment", "sensitivity": "normal"},
    {"fact_id": "technology_capability", "label": "Technology capability", "sensitivity": "normal"},
    {"fact_id": "financial_information", "label": "Financial information", "sensitivity": "sensitive"},
    {"fact_id": "w9_readiness", "label": "W-9 readiness", "sensitivity": "sensitive"},
    {"fact_id": "tax_identifiers", "label": "Tax identifiers", "sensitivity": "sensitive"},
    {"fact_id": "banking_payment_readiness", "label": "Banking / payment readiness", "sensitivity": "sensitive"},
)


SENSITIVE_FACT_IDS = {
    "financial_information",
    "w9_readiness",
    "tax_identifiers",
    "banking_payment_readiness",
}

LEGACY_TO_VALUE_STATUS = {
    "MISSING_FACT": "MISSING",
    "OWNER_PROVIDED_FACT": "OWNER_PROVIDED",
    "KNOWN_VERIFIED_FACT": "VERIFIED",
    "UNVERIFIED_FACT": "OWNER_PROVIDED",
    "NOT_APPLICABLE": "MISSING",
}


def fact_catalog(*, applicant_party: str = "AMICOR", stored: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    snapshot = profile_snapshot(applicant_party=applicant_party)
    facts = []
    stored = stored or {}
    for item in FACT_DEFINITIONS:
        status = "MISSING_FACT"
        value = OWNER_INPUT_REQUIRED
        value_status = "MISSING"
        verification_date = None
        expiration_date = None
        source_description = None
        notes = None
        if item["fact_id"] == "technology_capability":
            status = "KNOWN_VERIFIED_FACT"
            value = "Authorized digital drafting, organization, and summarization with owner review."
            value_status = "VERIFIED"
        overlay = stored.get(item["fact_id"])
        if overlay:
            value_status = str(overlay.get("value_status") or value_status)
            status = {
                "MISSING": "MISSING_FACT",
                "OWNER_PROVIDED": "OWNER_PROVIDED_FACT",
                "VERIFIED": "KNOWN_VERIFIED_FACT",
                "EXPIRED": "UNVERIFIED_FACT",
            }.get(value_status, status)
            value = overlay.get("value_display") or value
            verification_date = overlay.get("verification_date")
            expiration_date = overlay.get("expiration_date")
            source_description = overlay.get("source_description")
            notes = overlay.get("notes")
        facts.append(
            {
                **item,
                "status": status,
                "value_status": value_status,
                "value_display": value,
                "verification_date": verification_date,
                "expiration_date": expiration_date,
                "source_description": source_description,
                "notes": notes,
                "allowed_statuses": list(FACT_STATUSES),
                "allowed_value_statuses": list(FACT_VALUE_STATUSES),
            }
        )
    return {
        "applicant_party": snapshot["applicant_party"],
        "verified_identity": snapshot["verified"]["nova_identity"],
        "facts": facts,
        "policy": "Nova does not invent, collect, or store real tax, banking, or identity numbers in this catalog.",
    }
