"""Structured owner/business fact catalog. Nova never invents or stores secrets."""
from __future__ import annotations

import re
from typing import Any

from app.core.nova.work_revenue.lifecycle import FACT_STATUSES, FACT_VALUE_STATUSES
from app.core.nova.work_revenue.materials import sanitize_untrusted
from app.core.nova.work_revenue.urls import UnsafeSourceUrl, validate_source_url
from app.core.nova.work_revenue.verified_profile import OWNER_INPUT_REQUIRED, profile_snapshot

FACT_SOURCE_OWNER = "OWNER"

PROVIDED_STATUSES = {"PROVIDED", "OWNER_PROVIDED"}
COUNTED_PROVIDED_STATUSES = {"PROVIDED", "OWNER_PROVIDED", "VERIFIED"}

FACT_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {"fact_id": "legal_business_name", "label": "Legal business name", "category": "identity", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "dba", "label": "DBA / trade name", "category": "identity", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "address", "label": "Business address", "category": "identity", "value_kind": "address", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "business_email", "label": "Business email", "category": "identity", "value_kind": "email", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "business_phone", "label": "Business phone", "category": "identity", "value_kind": "phone", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "authorized_signer", "label": "Authorized signer", "category": "identity", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "ownership", "label": "Ownership / contracting party", "category": "identity", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "service_areas", "label": "Service areas", "category": "operations", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "industries_served", "label": "Industries served", "category": "operations", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "business_age", "label": "Business age", "category": "identity", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "insurance", "label": "Insurance status / readiness", "category": "compliance", "value_kind": "status", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": True},
    {"fact_id": "licenses", "label": "License status / readiness", "category": "compliance", "value_kind": "status", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": True},
    {"fact_id": "certifications", "label": "Certifications", "category": "capability", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "relevant_experience", "label": "Relevant experience", "category": "capability", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "references", "label": "References", "category": "capability", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "pricing", "label": "Pricing", "category": "commercial", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "rates", "label": "Rates", "category": "commercial", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "availability", "label": "Availability", "category": "operations", "value_kind": "text", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": False},
    {"fact_id": "workforce", "label": "Workforce", "category": "operations", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "equipment", "label": "Equipment", "category": "operations", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "technology_capability", "label": "Technology capability", "category": "capability", "value_kind": "text", "sensitivity": "normal", "required_before_live": False, "allow_not_applicable": False, "system_verified": True},
    {"fact_id": "ai_use_disclosure_decision", "label": "AI-use disclosure decision", "category": "disclosure", "value_kind": "decision", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": True},
    {"fact_id": "subcontractor_disclosure_decision", "label": "Subcontractor disclosure decision", "category": "disclosure", "value_kind": "decision", "sensitivity": "normal", "required_before_live": True, "allow_not_applicable": True},
    {"fact_id": "w9_readiness", "label": "W-9 readiness", "category": "financial_readiness", "value_kind": "flag", "sensitivity": "sensitive", "required_before_live": True, "allow_not_applicable": True},
    {"fact_id": "financial_information", "label": "Financial information readiness", "category": "financial_readiness", "value_kind": "flag", "sensitivity": "sensitive", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "tax_identifiers", "label": "Tax information readiness", "category": "financial_readiness", "value_kind": "flag", "sensitivity": "sensitive", "required_before_live": False, "allow_not_applicable": True},
    {"fact_id": "banking_payment_readiness", "label": "Banking / payment readiness", "category": "financial_readiness", "value_kind": "flag", "sensitivity": "sensitive", "required_before_live": False, "allow_not_applicable": True},
)

SENSITIVE_FACT_IDS = {item["fact_id"] for item in FACT_DEFINITIONS if item["sensitivity"] == "sensitive"}
REQUIRED_BEFORE_LIVE_IDS = {item["fact_id"] for item in FACT_DEFINITIONS if item["required_before_live"]}
FACT_DEFINITION_MAP = {item["fact_id"]: item for item in FACT_DEFINITIONS}

SENSITIVE_READY_VALUES = {
    "MISSING",
    "OWNER_SAYS_READY",
    "OWNER_SAYS_NOT_READY",
    "NOT_APPLICABLE",
    "VERIFIED",
    "w9_ready",
    "tax_information_ready",
    "banking_ready",
    "insurance_verified",
    "license_verified",
    OWNER_INPUT_REQUIRED,
    "[OWNER INPUT REQUIRED]",
}

STATUS_READY_VALUES = {
    "OWNER_SAYS_READY",
    "OWNER_SAYS_NOT_READY",
    "NOT_APPLICABLE",
    "VERIFIED",
    "insurance_verified",
    "license_verified",
}

AI_DISCLOSURE_VALUES = {
    "AI_ASSISTANCE_USED_DISCLOSE",
    "AI_ASSISTANCE_USED_OWNER_WILL_DECIDE_PER_PLATFORM",
    "NO_AI_ASSISTANCE_CLAIMED",
    "NOT_APPLICABLE",
}

SUBCONTRACTOR_DISCLOSURE_VALUES = {
    "SUBCONTRACTOR_ASSISTANCE_ALLOWED",
    "SUBCONTRACTOR_ASSISTANCE_NOT_ALLOWED",
    "OWNER_WILL_DECIDE_PER_ENGAGEMENT",
    "NOT_APPLICABLE",
}

SECRET_RE = re.compile(
    r"(password|passwd|api[_-]?key|secret|social security|ein\b|tax id|"
    r"routing number|account number|credit card|card number|"
    r"\b\d{3}-\d{2}-\d{4}\b|\b\d{2}-\d{7}\b|"
    r"bearer\s+[a-z0-9._\-]{8,})",
    re.I,
)
_SECRET_MARKERS = (
    "sk_" + "live",
    "sk_" + "test",
    "pk_" + "live",
    "pk_" + "test",
    "wh" + "sec_",
    "rk_" + "live",
)
LONG_DIGIT_RE = re.compile(r"\b\d{8,}\b")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_RE = re.compile(r"^\+?[0-9][0-9\s().\-]{6,19}$")
UNSAFE_MARKUP_RE = re.compile(r"(<\s*script|javascript:|data:text/html|onerror\s*=|onload\s*=)", re.I)
URL_HINT_RE = re.compile(r"(https?://|javascript:|data:|file:|vbscript:)", re.I)
MAX_FACT_VALUE = 400
MAX_FACT_NOTES = 2000

LEGACY_TO_VALUE_STATUS = {
    "MISSING_FACT": "MISSING",
    "OWNER_PROVIDED_FACT": "PROVIDED",
    "KNOWN_VERIFIED_FACT": "VERIFIED",
    "UNVERIFIED_FACT": "PROVIDED",
    "NOT_APPLICABLE": "NOT_APPLICABLE",
    "OWNER_PROVIDED": "PROVIDED",
    "PROVIDED": "PROVIDED",
}


class OwnerFactError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def normalize_fact_status(value: str | None) -> str:
    token = str(value or "MISSING").strip().upper()
    if token == "OWNER_PROVIDED":
        return "PROVIDED"
    if token not in {"MISSING", "PROVIDED", "VERIFIED", "EXPIRED", "NOT_APPLICABLE"}:
        raise OwnerFactError("Unknown fact value status")
    return token


def definition_for(fact_key: str) -> dict[str, Any] | None:
    return FACT_DEFINITION_MAP.get(str(fact_key or "").strip())


def _legacy_status(value_status: str) -> str:
    return {
        "MISSING": "MISSING_FACT",
        "PROVIDED": "OWNER_PROVIDED_FACT",
        "OWNER_PROVIDED": "OWNER_PROVIDED_FACT",
        "VERIFIED": "KNOWN_VERIFIED_FACT",
        "EXPIRED": "UNVERIFIED_FACT",
        "NOT_APPLICABLE": "NOT_APPLICABLE",
    }.get(value_status, "MISSING_FACT")


def _looks_like_secret(value: str) -> bool:
    text = value or ""
    if SECRET_RE.search(text):
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in _SECRET_MARKERS)


def validate_fact_value(
    fact_key: str,
    *,
    value_status: str,
    value_display: str | None,
    notes: str | None = None,
) -> str:
    definition = definition_for(fact_key)
    if definition is None:
        raise OwnerFactError("Unknown business fact key", status_code=404)
    status = normalize_fact_status(value_status)
    if status == "NOT_APPLICABLE" and not definition.get("allow_not_applicable"):
        raise OwnerFactError("This fact cannot be marked not applicable")
    raw = sanitize_untrusted(value_display)
    note_text = sanitize_untrusted(notes)
    if len(raw) > MAX_FACT_VALUE:
        raise OwnerFactError("Fact value exceeds the 400-character limit")
    if len(note_text) > MAX_FACT_NOTES:
        raise OwnerFactError("Fact notes exceed the 2000-character limit")
    blob = f"{raw}\n{note_text}"
    if UNSAFE_MARKUP_RE.search(blob):
        raise OwnerFactError("HTML, scripts, and event handlers are not allowed in owner facts")
    if _looks_like_secret(blob):
        raise OwnerFactError("Business facts cannot store secrets, tax identifiers, or banking credentials")
    if URL_HINT_RE.search(blob):
        matches = re.findall(r"(?:https?|javascript|data|file|vbscript):[^\s<>\"']+", blob, flags=re.I)
        if not matches:
            raise OwnerFactError("Unsafe URL text is not allowed in owner facts")
        for item in matches:
            try:
                validate_source_url(item)
            except UnsafeSourceUrl as exc:
                raise OwnerFactError("Unsafe URL text is not allowed in owner facts") from exc
    if status in {"MISSING"}:
        return OWNER_INPUT_REQUIRED
    if status == "NOT_APPLICABLE":
        return "NOT_APPLICABLE"
    kind = definition["value_kind"]
    if kind == "flag":
        token = raw.strip()
        if token not in SENSITIVE_READY_VALUES:
            raise OwnerFactError("Sensitive facts accept readiness flags only. Do not store numbers or credentials.")
        return token
    if kind == "decision":
        allowed = AI_DISCLOSURE_VALUES if fact_key == "ai_use_disclosure_decision" else SUBCONTRACTOR_DISCLOSURE_VALUES
        token = raw.strip().upper()
        if token not in allowed:
            raise OwnerFactError("Choose a supported disclosure decision. Do not enter a policy document or secret.")
        return token
    if kind == "status":
        token = raw.strip()
        if token in STATUS_READY_VALUES or token in SENSITIVE_READY_VALUES:
            return token
        if LONG_DIGIT_RE.search(token):
            raise OwnerFactError("Insurance and license facts accept readiness status only. Do not store policy or license numbers.")
        if len(token) < 3:
            raise OwnerFactError("Enter a readiness status or a short non-secret description")
        return token[:MAX_FACT_VALUE]
    if kind == "email":
        token = raw.strip()
        if not EMAIL_RE.match(token):
            raise OwnerFactError("Business email is malformed")
        return token.lower()
    if kind == "phone":
        token = re.sub(r"\s+", " ", raw.strip())
        digits = re.sub(r"\D", "", token)
        if not PHONE_RE.match(token) or not (7 <= len(digits) <= 15):
            raise OwnerFactError("Business phone is malformed")
        return token
    if not raw or raw == OWNER_INPUT_REQUIRED:
        raise OwnerFactError("A non-sensitive value is required when the fact is provided or verified")
    if definition["sensitivity"] == "sensitive":
        raise OwnerFactError("Sensitive facts accept readiness flags only. Do not store numbers or credentials.")
    if kind != "address" and LONG_DIGIT_RE.search(raw):
        raise OwnerFactError("Long number sequences look like secrets and are not stored")
    return raw[:MAX_FACT_VALUE]


def fact_readiness(facts: list[dict[str, Any]]) -> dict[str, Any]:
    required = [item for item in facts if item.get("required_before_live") and item.get("value_status") != "NOT_APPLICABLE"]
    provided = [item for item in required if item.get("value_status") in COUNTED_PROVIDED_STATUSES]
    verified = [item for item in required if item.get("value_status") == "VERIFIED"]
    missing = [item for item in required if item.get("value_status") == "MISSING"]
    expired = [item for item in required if item.get("value_status") == "EXPIRED"]
    total = len(required)
    percent = int(round((len(provided) / total) * 100)) if total else 100
    return {
        "total_required_facts": total,
        "provided_facts": len(provided),
        "verified_facts": len(verified),
        "missing_facts": len(missing),
        "expired_facts": len(expired),
        "not_applicable_facts": len([item for item in facts if item.get("value_status") == "NOT_APPLICABLE"]),
        "percentage_complete": percent,
        "missing_fact_ids": [item["fact_id"] for item in missing],
        "expired_fact_ids": [item["fact_id"] for item in expired],
        "externally_ready": False,
        "live_discovery_enabled": False,
        "external_submission_enabled": False,
        "financial_actions_enabled": False,
        "client_contact_enabled": False,
        "approval_executed": False,
        "source": FACT_SOURCE_OWNER,
        "disclaimer": "Fact readiness is internal only. It does not submit applications, contact clients, accept contracts, create invoices, or enable Stripe.",
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
        source = FACT_SOURCE_OWNER
        if item["fact_id"] == "technology_capability":
            status = "KNOWN_VERIFIED_FACT"
            value = "Authorized digital drafting, organization, and summarization with owner review."
            value_status = "VERIFIED"
            source = "SYSTEM"
        overlay = stored.get(item["fact_id"])
        if overlay:
            try:
                value_status = normalize_fact_status(overlay.get("value_status") or value_status)
            except OwnerFactError:
                value_status = "MISSING"
            status = _legacy_status(value_status)
            value = overlay.get("value_display") or value
            verification_date = overlay.get("verification_date")
            expiration_date = overlay.get("expiration_date")
            source_description = overlay.get("source_description")
            notes = overlay.get("notes")
            source = overlay.get("source") or FACT_SOURCE_OWNER
        facts.append(
            {
                "fact_id": item["fact_id"],
                "key": item["fact_id"],
                "label": item["label"],
                "display_label": item["label"],
                "category": item["category"],
                "value_kind": item["value_kind"],
                "sensitivity": item["sensitivity"],
                "required_before_live": bool(item["required_before_live"]),
                "allow_not_applicable": bool(item["allow_not_applicable"]),
                "status": status,
                "value_status": value_status,
                "value_display": value,
                "verification_date": verification_date,
                "expiration_date": expiration_date,
                "verified_at": verification_date,
                "expires_at": expiration_date,
                "source": source,
                "source_description": source_description,
                "notes": notes,
                "allowed_statuses": list(FACT_STATUSES),
                "allowed_value_statuses": ["MISSING", "PROVIDED", "VERIFIED", "EXPIRED", "NOT_APPLICABLE"],
            }
        )
    readiness = fact_readiness(facts)
    return {
        "applicant_party": snapshot["applicant_party"],
        "verified_identity": snapshot["verified"]["nova_identity"],
        "facts": facts,
        "readiness": readiness,
        "source": FACT_SOURCE_OWNER,
        "prohibited": [
            "EIN",
            "SSN",
            "tax ID numbers",
            "bank account numbers",
            "routing numbers",
            "Stripe secret keys",
            "API keys",
            "passwords",
            "authentication secrets",
            "payment card information",
        ],
        "policy": (
            "Nova does not invent, collect, or store real tax identifiers, banking, or identity numbers in this catalog. "
            "Owner entry is not application approval, bid submission, contract acceptance, message send, or payment."
        ),
        "externally_ready": False,
        "guardrails": {
            "LIVE_DISCOVERY_ENABLED": False,
            "EXTERNAL_SUBMISSION_ENABLED": False,
            "FINANCIAL_ACTIONS_ENABLED": False,
            "AUTONOMOUS_CLIENT_CONTACT_ENABLED": False,
            "FACT_ENTRY_EQUALS_APPROVAL": False,
            "FACT_ENTRY_EQUALS_SUBMIT": False,
            "FACT_ENTRY_EQUALS_PAYMENT": False,
        },
    }
