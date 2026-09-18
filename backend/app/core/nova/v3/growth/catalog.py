"""Configurable AMICOR targeting profiles and approved commercial catalog.

Profiles are data, not architecture. New sectors can be added without code forks.
Prices that are None require OWNER_ACTION_REQUIRED. Nova does not invent pricing.
"""
from __future__ import annotations

from typing import Any

PRODUCTS = ("delivery", "nova", "health")

TARGET_PROFILES: dict[str, dict[str, Any]] = {
    "delivery_pharmacy": {
        "product": "delivery",
        "label": "Pharmacies",
        "industries": ("pharmacy", "retail pharmacy"),
        "geographies": ("local", "metro"),
        "needs": ("same-day delivery", "prescription courier", "b2b delivery"),
    },
    "delivery_clinic": {
        "product": "delivery",
        "label": "Clinics and medical offices",
        "industries": ("clinic", "medical office", "accident clinic"),
        "geographies": ("local", "metro"),
        "needs": ("specimen courier", "supply delivery"),
    },
    "delivery_auto": {
        "product": "delivery",
        "label": "Auto parts businesses",
        "industries": ("auto parts", "automotive"),
        "geographies": ("local",),
        "needs": ("parts courier", "b2b delivery"),
    },
    "delivery_legal": {
        "product": "delivery",
        "label": "Law firms",
        "industries": ("law firm", "legal"),
        "geographies": ("local",),
        "needs": ("document courier", "court filing run"),
    },
    "delivery_retail": {
        "product": "delivery",
        "label": "Retailers and local businesses",
        "industries": ("retail", "local business"),
        "geographies": ("local",),
        "needs": ("last-mile", "b2b delivery"),
    },
    "delivery_airport": {
        "product": "delivery",
        "label": "Airport baggage / courier",
        "industries": ("airport", "courier"),
        "geographies": ("airport", "metro"),
        "needs": ("baggage transfer", "time-critical courier"),
    },
    "nova_smb": {
        "product": "nova",
        "label": "Small businesses needing AI operations support",
        "industries": ("small business", "professional services"),
        "geographies": ("remote", "local"),
        "needs": ("administrative automation", "ai operations", "follow-up"),
    },
    "nova_healthcare_ops": {
        "product": "nova",
        "label": "Healthcare businesses needing admin automation",
        "industries": ("healthcare", "clinic", "pharmacy"),
        "geographies": ("local", "remote"),
        "needs": ("administrative automation", "scheduling support"),
        "regulated": True,
    },
    "nova_logistics": {
        "product": "nova",
        "label": "Transportation and logistics companies",
        "industries": ("transportation", "logistics"),
        "geographies": ("regional", "remote"),
        "needs": ("ai operations", "dispatch admin"),
    },
    "health_transport": {
        "product": "health",
        "label": "Healthcare transportation",
        "industries": ("clinic", "healthcare", "medical office"),
        "geographies": ("local", "metro"),
        "needs": ("non-emergency transport", "patient transportation"),
        "regulated": True,
    },
}

APPROVED_SERVICES: dict[str, dict[str, Any]] = {
    "delivery_local_b2b": {
        "product": "delivery",
        "name": "AMICOR Delivery local B2B",
        "price": 499.0,
        "currency": "USD",
        "billing": "recurring",
        "trial_days": 0,
        "max_discount_pct": 10,
        "approved_claims": ("local B2B delivery", "owner-controlled operations"),
    },
    "nova_ops_assist": {
        "product": "nova",
        "name": "AMICOR Nova operations assist",
        "price": 299.0,
        "currency": "USD",
        "billing": "recurring",
        "trial_days": 7,
        "max_discount_pct": 0,
        "approved_claims": ("owner-controlled operations assistant", "seven-day trial where published"),
    },
    "nova_admin_automation": {
        "product": "nova",
        "name": "AMICOR Nova administrative automation",
        "price": 199.0,
        "currency": "USD",
        "billing": "recurring",
        "trial_days": 7,
        "max_discount_pct": 0,
        "approved_claims": ("administrative draft support", "owner approval required before live actions"),
    },
    "delivery_one_time_courier": {
        "product": "delivery",
        "name": "AMICOR Delivery one-time courier",
        "price": 85.0,
        "currency": "USD",
        "billing": "one_time",
        "trial_days": 0,
        "max_discount_pct": 0,
        "approved_claims": ("one-time local courier run"),
    },
    "health_non_emergency_transport": {
        "product": "health",
        "name": "AMICOR Health non-emergency transport",
        "price": None,
        "currency": "USD",
        "billing": "custom",
        "trial_days": 0,
        "max_discount_pct": 0,
        "approved_claims": ("non-emergency transportation subject to owner confirmation"),
    },
}

APPROVED_FAQ = {
    "what is nova": "AMICOR Nova is an owner-controlled operations assistant. Live actions stay off until the owner authorizes them.",
    "what is delivery": "AMICOR Delivery is a local B2B delivery service. Coverage and pricing require owner confirmation for each market.",
    "what is health": "AMICOR Health includes owner-controlled transportation workflows. Eligibility and pricing are not invented by Nova.",
    "trial": "A seven-day trial may apply only to approved Nova catalog plans that publish trial_days.",
    "pricing": "Nova will not invent pricing. Approved catalog prices are used, otherwise OWNER_ACTION_REQUIRED.",
}

BRAND_NAMES = ("AMICOR", "AMICOR Delivery", "AMICOR Nova", "AMICOR Health")
REGULATED_INDUSTRIES = frozenset({"pharmacy", "clinic", "healthcare", "medical office", "accident clinic"})
PROHIBITED_SENSITIVE = ("ssn", "social security", "hipaa phi dump", "undocumented status", "credit card full pan")
FABRICATION_TOKENS = (
    "guaranteed results",
    "certified partner of",
    "#1 in the market",
    "10000 customers",
    "we already work with you",
    "signed contract",
    "hipaa certified by nova",
)
LEGAL_TOKENS = ("we agree to indemnify", "binding contract", "we waive liability", "this is a legally binding")
FAKE_URGENCY = ("offer expires today", "last chance pricing", "act now or lose")
UNAVAILABLE_FEATURES = ("autonomous bank transfer", "bypass captcha", "live stripe charges", "unsupervised medical advice")


def service_for_product(product: str) -> dict[str, Any] | None:
    for row in APPROVED_SERVICES.values():
        if row["product"] == product and row.get("price") is not None:
            return row
    return None


def profile_for_industry(industry: str, product: str | None = None) -> dict[str, Any] | None:
    needle = (industry or "").lower()
    for profile in TARGET_PROFILES.values():
        if product and profile["product"] != product:
            continue
        if any(needle == item or needle in item or item in needle for item in profile["industries"]):
            return profile
    return None
