"""Conservative opportunity qualification. Untrusted source text. No deceptive scores."""
from __future__ import annotations

import re
from typing import Any

from app.core.nova.work_revenue.capability_registry import nova_supported_ids
from app.core.nova.work_revenue.verified_profile import has_verified_credential

OWNER_INPUT_REQUIRED = "[OWNER INPUT REQUIRED]"

_PHYSICAL_RE = re.compile(
    r"\b(on[- ]site|in[- ]person|warehouse|forklift|heavy lifting|stand for|retail store|"
    r"food service|construction|electrician|plumber|cna|home health aide|warehouse associate)\b",
    re.I,
)
_DRIVING_RE = re.compile(
    r"\b(cdl|commercial driver|delivery driver|drive a|driving required|valid driver.?s license|"
    r"operate (a |the )?vehicle)\b",
    re.I,
)
_LICENSE_RE = re.compile(
    r"\b(rn\b|registered nurse|lpn|licensed practical|md\b|physician|attorney|esquire|"
    r"bar admission|cpa\b|nursing license|medical license|professional license|licensed)\b",
    re.I,
)
_REGULATED_RE = re.compile(
    r"\b(diagnos|prescrib|legal advice|audit opinion|clinical judgment|malpractice|"
    r"practice of law|practice of medicine)\b",
    re.I,
)
_IDENTITY_RE = re.compile(
    r"\b(identity verification|id\.me|idme|kyc|i-9|background check|social security|"
    r"\bssn\b|government id)\b",
    re.I,
)
_INTERVIEW_RE = re.compile(r"\b(interview|phone screen|video interview|live interview)\b", re.I)
_PHONE_RE = re.compile(r"\b(phone call|telephone|call the hiring|must call)\b", re.I)
_MEETING_RE = re.compile(r"\b(live meeting|zoom interview|teams meeting|in-person meeting)\b", re.I)
_CAPTCHA_RE = re.compile(r"\b(captcha|are you a robot)\b", re.I)
_BANK_RE = re.compile(r"\b(bank account|direct deposit|routing number|payout setup)\b", re.I)
_TAX_RE = re.compile(r"\b(w-9|w9|ein required|tax id|tax form)\b", re.I)
_CONTRACT_RE = re.compile(r"\b(clickwrap|accept (the )?contract|e-sign|electronic signature)\b", re.I)
_PRICING_RE = re.compile(r"\b(set your rate|bid required|name your price)\b", re.I)
_ACCOUNT_RE = re.compile(r"\b(create an account|sign up on the portal|register an account)\b", re.I)
_PORTFOLIO_RE = re.compile(r"\b(portfolio|work sample required|attach a sample)\b", re.I)
_CLEARANCE_RE = re.compile(r"\b(security clearance|government clearance|secret clearance)\b", re.I)
_SUPPORT_RE = re.compile(r"\b(live customer support|answer phones|call center)\b", re.I)

_DIGITAL_SKILL_MAP = {
    "email": "EMAIL_DRAFTING",
    "writing": "DOCUMENT_PREPARATION",
    "research": "RESEARCH",
    "reporting": "REPORTING",
    "admin": "ADMINISTRATIVE_SUPPORT",
    "administrative": "ADMINISTRATIVE_SUPPORT",
    "crm": "CRM_DATA_ORGANIZATION",
    "data entry": "CRM_DATA_ORGANIZATION",
    "summar": "DATA_SUMMARIZATION",
    "proposal": "PROPOSAL_DRAFTING",
    "marketing": "MARKETING_DRAFTING",
    "calendar": "CALENDAR_PREPARATION",
    "schedul": "SCHEDULING_SUPPORT",
    "follow-up": "CUSTOMER_FOLLOWUP_DRAFTING",
    "follow up": "CUSTOMER_FOLLOWUP_DRAFTING",
    "presentation": "PRESENTATION_DRAFTING",
    "lead": "LEAD_TRACKING",
}


def _blob(opportunity: dict[str, Any]) -> str:
    parts = [
        opportunity.get("opportunity_title") or "",
        opportunity.get("description") or "",
        opportunity.get("requirements") or "",
        opportunity.get("location") or "",
        " ".join(opportunity.get("skills_required") or []),
        " ".join(opportunity.get("credentials_required") or []),
    ]
    return "\n".join(str(part) for part in parts)


def _flag(pattern: re.Pattern[str], text: str) -> bool:
    return bool(pattern.search(text or ""))


def qualify_opportunity(opportunity: dict[str, Any]) -> dict[str, Any]:
    text = _blob(opportunity)
    missing: list[str] = []
    reasons: list[str] = []
    nova_tasks: list[str] = []
    owner_tasks: list[str] = ["Owner approval before any external application"]
    human_tasks: list[str] = []
    owner_actions: list[str] = []
    owner_participation: list[str] = ["Review and approve any application materials"]
    other_human: list[str] = []

    description = (opportunity.get("description") or "").strip()
    if not description:
        missing.append("description")
    requirements = (opportunity.get("requirements") or "").strip()
    if not requirements and not (opportunity.get("skills_required") or []):
        missing.append("requirements_or_skills")

    compensation_understandable = bool(
        opportunity.get("compensation_type")
        or opportunity.get("compensation_amount") is not None
        or (opportunity.get("compensation_period") or "").strip()
    )
    if not compensation_understandable:
        missing.append("compensation")

    physical_field = str(opportunity.get("physical_presence_required") or "unknown").lower()
    physical_from_text = _flag(_PHYSICAL_RE, text)
    if physical_field == "true" or physical_from_text:
        physical = "true"
    elif physical_field == "false" and not physical_from_text:
        physical = "false"
    else:
        physical = "unknown"
        if physical_field == "unknown":
            missing.append("physical_presence_required")

    driving = _flag(_DRIVING_RE, text)
    licenses = _flag(_LICENSE_RE, text) or bool(opportunity.get("credentials_required"))
    regulated = _flag(_REGULATED_RE, text)
    identity = _flag(_IDENTITY_RE, text)
    interview = _flag(_INTERVIEW_RE, text)
    captcha = _flag(_CAPTCHA_RE, text)

    credentials = [str(item).strip() for item in (opportunity.get("credentials_required") or []) if str(item).strip()]
    unverified_credentials = [item for item in credentials if not has_verified_credential(item)]
    if credentials and unverified_credentials:
        missing.append("verified_credentials")
        reasons.append("Required credentials are not present in the verified profile.")

    if driving:
        human_tasks.append("Driving / vehicle operation")
        other_human.append("A licensed human driver")
        owner_actions.append("LICENSE_VERIFICATION")
        reasons.append("requires driving")
    if physical == "true":
        human_tasks.append("Physical / on-site presence")
        other_human.append("A human who can be physically present")
        reasons.append("requires physical presence")
    if licenses or regulated:
        human_tasks.append("Licensed or regulated professional work")
        other_human.append("A separately qualified licensed human")
        owner_actions.append("LICENSE_VERIFICATION")
        reasons.append("requires professional license")
    if identity:
        owner_tasks.append("Complete identity verification in person")
        owner_participation.append("Identity verification")
        owner_actions.append("IDENTITY_VERIFICATION")
        reasons.append("requires identity verification")
        if _flag(re.compile(r"\bssn\b|social security", re.I), text):
            owner_actions.append("SSN")
        if _flag(re.compile(r"background check", re.I), text):
            owner_actions.append("BACKGROUND_CHECK")
            reasons.append("requires background check")
    if interview:
        owner_tasks.append("Attend any live interview")
        owner_participation.append("Live interview")
        owner_actions.append("LIVE_INTERVIEW")
        human_tasks.append("Human interview")
        reasons.append("requires live interview")
    if captcha:
        owner_tasks.append("Solve any CAPTCHA or human-check")
        owner_actions.append("CAPTCHA")
        reasons.append("requires CAPTCHA")
    if _flag(_PHONE_RE, text):
        owner_actions.append("PHONE_CALL")
        owner_participation.append("Phone call")
        human_tasks.append("Phone call")
        reasons.append("requires phone calls")
    if _flag(_MEETING_RE, text):
        owner_actions.append("LIVE_MEETING")
        owner_participation.append("Live meeting")
        reasons.append("requires live meeting")
    if _flag(_ACCOUNT_RE, text):
        owner_actions.append("ACCOUNT_CREATION")
        owner_participation.append("External portal account")
        reasons.append("requires external portal account")
    if _flag(_PORTFOLIO_RE, text):
        missing.append("portfolio_or_work_sample")
        reasons.append("requires portfolio")
    if _flag(_CLEARANCE_RE, text):
        owner_actions.append("IDENTITY_VERIFICATION")
        reasons.append("requires government clearance")
        other_human.append("A human eligible for the required clearance")
    if _flag(_SUPPORT_RE, text):
        human_tasks.append("Live customer support")
        reasons.append("requires live customer support")
    if _flag(_BANK_RE, text):
        owner_actions.append("BANK_INFORMATION")
        owner_actions.append("PAYOUT_SETUP")
        owner_participation.append("Bank information")
        reasons.append("requires banking/payment setup")
    if _flag(_TAX_RE, text):
        owner_actions.append("TAX_INFORMATION")
        owner_participation.append("Tax information")
        reasons.append("requires tax form")
    if _flag(_CONTRACT_RE, text):
        owner_actions.append("CONTRACT_ACCEPTANCE")
        owner_actions.append("LEGAL_SIGNATURE")
        owner_participation.append("Legal signature / contract acceptance")
        reasons.append("requires manual signature")
    if _flag(_PRICING_RE, text):
        owner_actions.append("PRICING_COMMITMENT")
        owner_participation.append("Pricing commitment")
        reasons.append("requires owner approval of pricing")

    skills = [str(item).lower() for item in (opportunity.get("skills_required") or [])]
    skill_blob = " ".join(skills) + " " + text.lower()
    matched_caps: list[str] = []
    for needle, cap_id in _DIGITAL_SKILL_MAP.items():
        if needle in skill_blob and cap_id in nova_supported_ids():
            matched_caps.append(cap_id)
            nova_tasks.append(cap_id.replace("_", " ").title())
    nova_tasks = list(dict.fromkeys(nova_tasks))
    matched_caps = list(dict.fromkeys(matched_caps))

    if not description:
        outcome = "INSUFFICIENT_INFORMATION"
        nova_share = "unknown"
        reasons.append("Description is missing, so qualification is uncertain.")
    elif driving or regulated or (licenses and physical == "true"):
        outcome = "NOT_SUITABLE"
        nova_share = "none"
    elif physical == "true" or licenses:
        outcome = "HUMAN_REQUIRED"
        nova_share = "partial" if matched_caps else "none"
        if matched_caps:
            reasons.append("Some digital tasks may be assisted by Nova, but a qualified human must perform the role.")
    elif physical == "unknown" or (credentials and unverified_credentials) or (
        not compensation_understandable and not matched_caps
    ):
        outcome = "INSUFFICIENT_INFORMATION"
        nova_share = "unknown"
        reasons.append("Important requirements are missing or unverified; prefer INSUFFICIENT_INFORMATION.")
    elif matched_caps:
        outcome = "NOVA_WITH_OWNER_REVIEW"
        nova_share = "majority" if len(matched_caps) >= 2 else "partial"
        reasons.append("Matched authorized digital capabilities. Owner review is required before any external use.")
        if identity or interview or owner_actions:
            nova_share = "partial"
        if not identity and not interview and not owner_actions and physical == "false" and not credentials:
            outcome = "NOVA_CAN_PERFORM"
            nova_share = "majority" if nova_tasks else "partial"
            reasons.append("Matched digital capabilities with no physical, license, or identity gates.")
            owner_tasks = ["Owner approval is still required before any external application"]
    else:
        if physical == "false" and not licenses and not driving:
            outcome = "INSUFFICIENT_INFORMATION"
            nova_share = "unknown"
            reasons.append("Skills do not clearly map to authorized Nova capabilities.")
        else:
            outcome = "INSUFFICIENT_INFORMATION"
            nova_share = "unknown"
            reasons.append("Unable to confirm Nova can perform this work without guessing.")

    unique_actions = list(dict.fromkeys(owner_actions))
    unique_reasons = list(dict.fromkeys(reasons)) or ["Qualification completed without a deceptive numeric score."]
    if unique_actions:
        unique_reasons.append("requires owner approval")
    if driving or regulated:
        lifecycle = "PROHIBITED"
    elif outcome == "NOT_SUITABLE":
        lifecycle = "NOT_SUPPORTED"
    elif outcome == "HUMAN_REQUIRED" and unique_actions:
        lifecycle = "OWNER_ACTION_REQUIRED"
    elif outcome == "HUMAN_REQUIRED":
        lifecycle = "NOT_SUPPORTED"
    elif outcome == "NOVA_WITH_OWNER_REVIEW":
        lifecycle = "OWNER_ACTION_REQUIRED" if unique_actions else "NOVA_CAN_PREPARE_OWNER_REVIEW"
    elif outcome == "NOVA_CAN_PERFORM":
        lifecycle = "NOVA_CAN_PERFORM"
    else:
        lifecycle = "INSUFFICIENT_INFORMATION"
    return {
        "outcome": outcome,
        "lifecycle_outcome": lifecycle,
        "reason_codes": unique_reasons,
        "nova_task_share": nova_share,
        "owner_participation": list(dict.fromkeys(owner_participation)),
        "other_human_required": list(dict.fromkeys(other_human)),
        "physical_presence_required": physical,
        "credentials_required": credentials,
        "licenses_required": bool(licenses),
        "driving_required": bool(driving),
        "regulated_professional_judgment_required": bool(regulated),
        "identity_verification_required": bool(identity),
        "human_interview_required": bool(interview),
        "compensation_understandable": compensation_understandable,
        "missing_information": missing,
        "nova_tasks": nova_tasks,
        "owner_tasks": list(dict.fromkeys(owner_tasks)),
        "human_tasks": list(dict.fromkeys(human_tasks)),
        "reasons": unique_reasons,
        "owner_actions": unique_actions,
        "deceptive_score_used": False,
        "matched_capabilities": matched_caps,
    }
