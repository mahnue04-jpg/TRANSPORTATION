"""Structured owner/business fact requirements. No real sensitive values are stored here."""
from __future__ import annotations

from typing import Any

from app.core.nova.work_revenue.lifecycle import FACT_STATUSES
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


def fact_catalog(*, applicant_party: str = "AMICOR") -> dict[str, Any]:
    snapshot = profile_snapshot(applicant_party=applicant_party)
    facts = []
    for item in FACT_DEFINITIONS:
        status = "MISSING_FACT"
        value = OWNER_INPUT_REQUIRED
        if item["fact_id"] == "technology_capability":
            status = "KNOWN_VERIFIED_FACT"
            value = "Authorized digital drafting, organization, and summarization with owner review."
        facts.append(
            {
                **item,
                "status": status,
                "value_display": value,
                "allowed_statuses": list(FACT_STATUSES),
            }
        )
    return {
        "applicant_party": snapshot["applicant_party"],
        "verified_identity": snapshot["verified"]["nova_identity"],
        "facts": facts,
        "policy": "Nova does not invent, collect, or store real tax, banking, or identity numbers in this catalog.",
    }
