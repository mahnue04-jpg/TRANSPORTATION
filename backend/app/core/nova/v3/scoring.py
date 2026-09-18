"""V3 capability scoring with explainability. Never fabricates qualifications."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.adapters import RawOpportunity
from app.core.nova.v3.models import PHYSICAL_TOKENS, PROHIBITED_TOKENS


DIGITAL_TOKENS = ("report", "research", "crm", "draft", "summary", "administrative", "writing", "document")


def explain_opportunity(raw: RawOpportunity) -> dict[str, Any]:
    text = f"{raw.title} {raw.description} {' '.join(raw.required_qualifications)}".lower()
    reasons: list[str] = []
    skill_fit = "unknown"
    human_only = False
    prohibited = False
    missing = []
    if not raw.title.strip() or not raw.description.strip():
        missing.append("title_or_description")
        reasons.append("Missing information: title or description is blank.")
    if any(token in text for token in PROHIBITED_TOKENS):
        prohibited = True
        reasons.append("Prohibited content detected. Nova will not perform this work.")
    physical = raw.remote_status == "onsite" or any(token in text for token in PHYSICAL_TOKENS)
    if physical:
        human_only = True
        reasons.append("Human-only physical or on-site work. Nova cannot perform it.")
    digital = any(token in text for token in DIGITAL_TOKENS)
    if digital:
        skill_fit = "digital_admin_research"
        reasons.append("Skill fit: remote digital work Nova can draft internally.")
    credentials_needed = bool(raw.login_required or raw.captcha_required or raw.human_verification_required)
    if credentials_needed:
        reasons.append("Third-party login/CAPTCHA/identity restrictions require HUMAN_ACTION_REQUIRED.")
    if raw.compensation_amount is None:
        missing.append("compensation")
        reasons.append("Expected compensation is unknown.")
    if prohibited:
        classification, score = "PROHIBITED", 0.0
    elif human_only:
        classification, score = "HUMAN_ONLY", 0.05
    elif credentials_needed:
        classification, score = "EXTERNAL_CREDENTIALS_REQUIRED", 0.2
    elif missing and not digital:
        classification, score = "INSUFFICIENT_INFORMATION", 0.0
    elif digital and raw.remote_status == "remote":
        classification, score = "NOVA_CAN_PERFORM", 0.86
    elif digital:
        classification, score = "NOVA_CAN_ASSIST", 0.55
    else:
        classification, score = "INSUFFICIENT_INFORMATION", 0.1
        reasons.append("Not enough evidence of a digital deliverable Nova can own.")
    return {
        "classification": classification,
        "score": score,
        "skill_fit": skill_fit,
        "deliverable_type": "digital_draft" if digital else "unknown",
        "deadline_fit": "unspecified",
        "geography": raw.geography,
        "remote_status": raw.remote_status,
        "required_credentials": credentials_needed,
        "prohibited_human_only": human_only,
        "third_party_restrictions": raw.terms_restrictions,
        "expected_owner_effort": "review_and_approve" if classification == "NOVA_CAN_PERFORM" else "high_or_human",
        "required_tools": ["owner_review"] + (["external_login"] if credentials_needed else []),
        "missing_information": missing,
        "reasons": reasons,
        "why": " ".join(reasons) or "Insufficient evidence.",
    }
