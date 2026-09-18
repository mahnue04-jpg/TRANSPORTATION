"""Synthetic Phase 3 lead fixtures. No live discovery."""
from __future__ import annotations

from typing import Any

FIXTURES: dict[str, dict[str, Any]] = {
    "A": {
        "organization_name": "River Pharmacy LLC",
        "contact_name": "Alex Rivera",
        "role_title": "Pharmacist Owner",
        "industry": "pharmacy",
        "geography": "local metro",
        "website": "https://example-pharmacy.test",
        "email_placeholder": "alex@example-pharmacy.test",
        "business_need": "same-day prescription courier",
        "product_fit": "delivery",
        "estimated_value": 800,
        "urgency": "high",
        "source": "synthetic_directory",
    },
    "B": {
        "organization_name": "North Clinic",
        "contact_name": "Jordan Lee",
        "role_title": "Clinic Manager",
        "industry": "clinic",
        "geography": "metro",
        "website": "https://example-clinic.test",
        "email_placeholder": "jordan@example-clinic.test",
        "business_need": "non-emergency patient transportation",
        "product_fit": "health",
        "estimated_value": 1200,
        "source": "synthetic_web",
    },
    "C": {
        "organization_name": "Harbor Bookkeeping",
        "contact_name": "Sam Patel",
        "role_title": "Owner",
        "industry": "professional services",
        "geography": "remote",
        "website": "https://example-smb.test",
        "email_placeholder": "sam@example-smb.test",
        "business_need": "administrative automation",
        "product_fit": "nova",
        "estimated_value": 299,
        "source": "synthetic_inbound",
    },
    "D": {
        "organization_name": "Broken Email Co",
        "contact_name": "Pat",
        "role_title": "Owner",
        "industry": "retail",
        "geography": "local",
        "email_placeholder": "not-an-email",
        "business_need": "b2b delivery",
        "product_fit": "delivery",
        "source": "synthetic_import",
    },
    "F": {
        "organization_name": "Quiet Office LLC",
        "contact_name": "Riley",
        "role_title": "Director",
        "industry": "law firm",
        "geography": "local",
        "email_placeholder": "riley@example-legal.test",
        "business_need": "document courier",
        "product_fit": "delivery",
        "consent_restrictions": ["do not contact"],
        "source": "synthetic_list",
    },
    "N": {
        "organization_name": "Summit Logistics",
        "contact_name": "Casey Nguyen",
        "role_title": "CEO",
        "industry": "logistics",
        "geography": "regional",
        "website": "https://example-logistics.test",
        "email_placeholder": "casey@example-logistics.test",
        "business_need": "ai operations",
        "product_fit": "nova",
        "estimated_value": 25000,
        "urgency": "high",
        "source": "synthetic_referral",
    },
}


def fixture(letter: str) -> dict[str, Any]:
    return dict(FIXTURES[letter])
