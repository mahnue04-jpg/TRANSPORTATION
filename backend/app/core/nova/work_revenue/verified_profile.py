"""Verified applicant facts only. Missing credentials are UNKNOWN / OWNER INPUT REQUIRED."""
from __future__ import annotations

from typing import Any

OWNER_INPUT_REQUIRED = "[OWNER INPUT REQUIRED]"
UNKNOWN = "UNKNOWN"

# Only facts this engine is allowed to treat as known. Do not invent degrees, licenses,
# years of experience, client lists, revenue, or legal registrations beyond this set.
VERIFIED_FACTS: dict[str, Any] = {
    "nova_identity": (
        "Nova is an AI system/tool operating under AMICOR/owner authorization. "
        "Nova is not a human employee and must not be represented as one."
    ),
    "contracting_parties": [
        {
            "id": "AMICOR",
            "label": "AMICOR / Amicor Health, LLC",
            "status": OWNER_INPUT_REQUIRED,
            "notes": "Confirm the legal contracting entity for each opportunity before applying.",
        },
        {
            "id": "OWNER_PERSONAL",
            "label": "Owner personally",
            "status": OWNER_INPUT_REQUIRED,
            "notes": "Use only where legally and operationally appropriate. Owner must confirm.",
        },
    ],
    "products_in_repository": [
        "AMICOR Nova",
        "AMICOR Health",
        "AMICOR Delivery",
        "AMICOR Freight",
    ],
    "authorized_work_kinds": [
        "Email and follow-up drafting with owner review",
        "Document, proposal, and report drafting with owner review",
        "Lead, customer, and task organization inside Nova",
        "Summarization of owner-provided or local operational text",
    ],
}

UNKNOWN_FIELDS: tuple[str, ...] = (
    "degrees",
    "licenses",
    "certifications",
    "employment_history",
    "references",
    "professional_credentials",
    "years_of_experience",
    "client_history",
    "revenue",
    "legal_status_details",
    "ein",
    "personal_contact_details",
    "owner_resume_history",
)


def unknown_map() -> dict[str, str]:
    return {field: UNKNOWN for field in UNKNOWN_FIELDS}


def profile_snapshot(*, applicant_party: str = "AMICOR") -> dict[str, Any]:
    parties = {item["id"]: item for item in VERIFIED_FACTS["contracting_parties"]}
    party = parties.get(applicant_party, parties["AMICOR"])
    return {
        "verified": dict(VERIFIED_FACTS),
        "applicant_party": party,
        "unknown": unknown_map(),
        "placeholder": OWNER_INPUT_REQUIRED,
        "fabrication_policy": "Never invent missing credentials, clients, revenue, or experience.",
    }


def has_verified_credential(name: str) -> bool:
    token = (name or "").strip().lower()
    if not token:
        return False
    return False
