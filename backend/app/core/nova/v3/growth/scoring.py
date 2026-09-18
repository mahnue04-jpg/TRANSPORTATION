"""Explainable lead scoring. No black-box totals."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.growth.catalog import REGULATED_INDUSTRIES, profile_for_industry


def score_lead(payload: dict[str, Any]) -> dict[str, Any]:
    industry = str(payload.get("industry") or "").lower()
    need = str(payload.get("business_need") or "").lower()
    product = str(payload.get("product_fit") or "").lower()
    geography = str(payload.get("geography") or "").lower()
    role = str(payload.get("role_title") or "").lower()
    email = str(payload.get("email_placeholder") or "").strip()
    website = str(payload.get("website") or "").strip()
    value = payload.get("estimated_value")
    urgency = str(payload.get("urgency") or "unspecified").lower()
    restrictions = [str(item).lower() for item in (payload.get("consent_restrictions") or [])]
    reasons: list[str] = []
    missing: list[str] = []
    score = 0.15
    profile = profile_for_industry(industry, product or None) or profile_for_industry(industry)
    product_fit = product or (profile["product"] if profile else "unknown")
    if profile:
        score += 0.22
        reasons.append(f"Business type matches targeting profile '{profile['label']}'.")
    else:
        reasons.append("No configured targeting profile matched this industry yet.")
    if product_fit in {"delivery", "nova", "health"}:
        score += 0.12
        reasons.append(f"AMICOR service fit: {product_fit}.")
    else:
        missing.append("product_fit")
        reasons.append("AMICOR product fit is unclear.")
    if geography:
        score += 0.08
        reasons.append(f"Geographic fit noted as {geography}.")
    else:
        missing.append("geography")
    if need:
        score += 0.1
        reasons.append(f"Stated need: {need}.")
    else:
        missing.append("business_need")
        reasons.append("Expected need is missing.")
    if value is None:
        missing.append("estimated_value")
        reasons.append("Potential recurring value is unknown.")
    else:
        amount = float(value)
        if amount >= 10000:
            score += 0.18
            reasons.append("High estimated value. Owner review is recommended before outreach.")
        elif amount >= 200:
            score += 0.1
            reasons.append("Estimated value supports a standard conversation.")
    decision_maker = any(token in role for token in ("owner", "director", "manager", "pharmacist", "president", "ceo"))
    if decision_maker:
        score += 0.08
        reasons.append("Role looks like a decision-maker or operator.")
    else:
        reasons.append("Decision-maker relevance is uncertain.")
    if urgency in {"high", "urgent", "this week"}:
        score += 0.07
        reasons.append("Urgency is high.")
    contactable = bool(email and "@" in email and "." in email.split("@")[-1])
    if not contactable:
        missing.append("valid_email")
        reasons.append("Contactability is weak or the email placeholder is invalid.")
        score -= 0.2
    if website:
        score += 0.03
    if any("do not contact" in item or item == "opt-out" for item in restrictions):
        score = 0.0
        reasons.append("Consent/contact restrictions forbid outreach.")
    regulated = industry in REGULATED_INDUSTRIES or bool(profile and profile.get("regulated"))
    if regulated:
        reasons.append("Regulated-sector outreach requires owner approval.")
    owner_effort = "review_and_approve" if score >= 0.6 else "high_research"
    if not contactable:
        qualification = "DISQUALIFIED"
        next_action = "repair_or_discard_invalid_contact"
    elif any("do not contact" in item or item == "opt-out" for item in restrictions):
        qualification = "DO_NOT_CONTACT"
        next_action = "suppress_and_audit"
    elif missing and score < 0.4:
        qualification = "DISQUALIFIED"
        next_action = "collect_missing_information"
    elif regulated or (value is not None and float(value) >= 10000):
        qualification = "OWNER_REVIEW"
        next_action = "owner_review_before_outreach"
    elif score >= 0.55:
        qualification = "QUALIFIED"
        next_action = "prepare_personalized_outreach"
    else:
        qualification = "QUALIFYING"
        next_action = "research_missing_facts"
    score = max(0.0, min(round(score, 3), 0.99))
    return {
        "score": score,
        "qualification_status": qualification,
        "product_fit": product_fit,
        "why": " ".join(reasons),
        "reasons": reasons,
        "recommended_next_action": next_action,
        "business_type": industry or "unknown",
        "service_fit": product_fit,
        "geographic_fit": geography or "unknown",
        "expected_need": need or "unknown",
        "company_size_indicator": "unknown" if value is None else ("large" if float(value) >= 10000 else "smb"),
        "potential_recurring_value": value,
        "decision_maker_relevance": decision_maker,
        "urgency": urgency,
        "contactability": contactable,
        "missing_information": missing,
        "compliance_restrictions": restrictions,
        "owner_effort_required": owner_effort,
        "regulated": regulated,
        "high_value": bool(value is not None and float(value) >= 10000),
        "profile": None if profile is None else profile["label"],
    }
