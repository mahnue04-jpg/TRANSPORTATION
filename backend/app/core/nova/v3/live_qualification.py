"""Live opportunity risk/fit qualification for Nova Work & Revenue.

Applied after Remotive (or other) discovery and before prepare-for-approval.
Never submits applications, contacts employers, pays fees, or creates accounts.
"""
from __future__ import annotations

import re
from typing import Any

OUTCOME_QUALIFIED = "QUALIFIED"
OUTCOME_NEEDS_OWNER_REVIEW = "NEEDS_OWNER_REVIEW"
OUTCOME_NOT_QUALIFIED = "NOT_QUALIFIED"

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"

AI_ALLOWED = "allowed"
AI_PROHIBITED = "prohibited"
AI_UNCLEAR = "unclear"

FEE_YES = "yes"
FEE_NO = "no"
FEE_UNCLEAR = "unclear"

WORK_B2B = "B2B"
WORK_FREELANCE = "freelance"
WORK_CONTRACTOR = "contractor"
WORK_EMPLOYEE = "employee"
WORK_UNKNOWN = "unknown"

_CAPABILITY_TOKENS = (
    "research",
    "data analysis",
    "analysis",
    "reporting",
    "report",
    "administrative",
    "admin",
    "customer support",
    "content",
    "documentation",
    "proposal",
    "workflow",
    "automation",
    "writing",
    "writer",
    "crm",
    "summary",
    "operations",
    "virtual assistant",
    "office assistant",
)

_EMPLOYEE_TOKENS = (
    "full-time",
    "full time",
    "w-2",
    "w2",
    "employee only",
    "staff position",
    "join our team",
    "benefits package",
    "401k",
    "401(k)",
    "permanent employee",
    "salary employee",
    "hired as an employee",
)

_CONTRACT_TOKENS = (
    "freelance",
    "contractor",
    "independent contractor",
    "1099",
    "project-based",
    "project based",
    "vendor",
    "b2b",
    "business-to-business",
    "consulting",
    "contract role",
    "contract work",
    "statement of work",
    "sow",
)

_FEE_TOKENS = (
    "membership fee",
    "paid membership",
    "membership required",
    "join fee",
    "upfront fee",
    "pay to apply",
    "application fee",
    "pay to access",
    "subscription required",
    "premium membership",
    "become a member",
    "annual dues",
    "registration fee",
    "pay before",
    "payment required to",
)

_AI_PROHIBITED_TOKENS = (
    "no ai",
    "no artificial intelligence",
    "ai-generated content is not",
    "ai generated content is not",
    "chatgpt not allowed",
    "ai assistance is prohibited",
    "ai-assisted work is not allowed",
    "do not use ai",
    "ai writing tools are prohibited",
    "no generative ai",
)

_AI_ALLOWED_TOKENS = (
    "ai-assisted welcome",
    "ai tools allowed",
    "ai assistance permitted",
    "may use ai",
    "ai-assisted work allowed",
    "chatgpt allowed",
)

_CREDENTIAL_TOKENS = (
    "active license required",
    "nursing license",
    "rn license",
    "cdl required",
    "bar admission",
    "cpa required",
    "security clearance",
    "medical license",
    "pe license",
    "licensed attorney",
)

_DEGREE_TOKENS = (
    "phd required",
    "md required",
    "must have a bachelor",
    "bachelor's degree required",
    "master's degree required",
    "degree required",
)

_REGULATED_TOKENS = (
    "patient care",
    "prescribe medication",
    "legal advice",
    "court appearance",
    "handle controlled substances",
)

_SCAM_TOKENS = (
    "send wire",
    "western union",
    "gift card payment",
    "crypto only payment",
    "pay us first",
    "guaranteed income with no work",
)

_LEGIT_SOURCES = ("remotive", "remotive.com")

_GEO_HARD_TOKENS = (
    "must be located in",
    "must reside in",
    "local candidates only",
    "on-site only",
    "in-office only",
)


def _blob(job: dict[str, Any]) -> str:
    parts = [
        job.get("title"),
        job.get("company_name"),
        job.get("description"),
        job.get("compensation_text"),
        job.get("job_type"),
        job.get("geography"),
        job.get("source_attribution"),
        job.get("source_url"),
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _has_any(text: str, tokens: tuple[str, ...]) -> bool:
    return any(token in text for token in tokens)


def _detect_work_type(text: str, job_type: str | None) -> str:
    jt = str(job_type or "").lower()
    if _has_any(text, _EMPLOYEE_TOKENS) or "full_time" in jt or jt in {"full-time", "permanent"}:
        return WORK_EMPLOYEE
    if "b2b" in text or "vendor" in text or "statement of work" in text:
        return WORK_B2B
    if "freelance" in text or "freelance" in jt:
        return WORK_FREELANCE
    if _has_any(text, _CONTRACT_TOKENS) or "contract" in jt:
        return WORK_CONTRACTOR
    return WORK_UNKNOWN


def _detect_fee(text: str) -> str:
    negated = (
        "no membership fee",
        "no upfront fee",
        "no application fee",
        "no join fee",
        "without membership",
        "no paid membership",
        "membership not required",
        "no fee required",
        "no fees",
        "free to join",
    )
    if any(token in text for token in negated):
        # Still flag if an affirmative fee phrase appears outside negation context.
        affirmative = (
            "paid membership required",
            "membership required",
            "pay to apply",
            "pay to access",
            "application fee required",
            "subscription required",
            "annual dues",
            "registration fee required",
        )
        if any(token in text for token in affirmative):
            return FEE_YES
        return FEE_NO
    if _has_any(text, _FEE_TOKENS):
        return FEE_YES
    if "membership" in text and ("pay" in text or "fee" in text or "dues" in text):
        # Avoid "no fee" / "without fee" already handled above.
        if "no fee" in text or "without fee" in text:
            return FEE_NO
        return FEE_YES
    return FEE_NO


def _ai_mentioned(text: str) -> bool:
    return any(
        token in text
        for token in (
            "chatgpt",
            "generative ai",
            "ai-assisted",
            "ai assisted",
            "ai-generated",
            "ai generated",
            "artificial intelligence",
            " ai ",
            "ai tools",
            "ai writing",
        )
    )


def _detect_ai_policy(text: str) -> tuple[str, bool]:
    """Return (policy, policy_is_ambiguous_mention).

    Silence (AI never mentioned) is treated as display-unclear but not an
    automatic owner-review blocker when every other QUALIFIED criterion passes.
    Ambiguous AI mentions force NEEDS_OWNER_REVIEW.
    """
    if _has_any(text, _AI_PROHIBITED_TOKENS):
        return AI_PROHIBITED, False
    if _has_any(text, _AI_ALLOWED_TOKENS):
        return AI_ALLOWED, False
    if _ai_mentioned(text):
        return AI_UNCLEAR, True
    return AI_UNCLEAR, False


def _compensation_present(job: dict[str, Any], text: str) -> bool:
    comp = str(job.get("compensation_text") or "").strip()
    if comp and comp.lower() not in {"n/a", "na", "none", "tbd", "negotiable only"}:
        return True
    if re.search(r"\$\s?\d", text):
        return True
    if re.search(r"\b\d+(\.\d+)?\s?(usd|eur|gbp|/hr|per hour|per month|per project)\b", text):
        return True
    return False


def _source_legitimate(job: dict[str, Any]) -> bool:
    provider = str(job.get("provider_id") or "").lower()
    attribution = str(job.get("source_attribution") or "").lower()
    url = str(job.get("source_url") or "").lower()
    if provider in _LEGIT_SOURCES or attribution in {"remotive"}:
        return True
    if "remotive.com" in url:
        return True
    if url.startswith("https://") and job.get("company_name") and job.get("title"):
        return True
    return False


def _capability_fit(text: str) -> bool:
    return _has_any(text, _CAPABILITY_TOKENS)


def qualify_live_job(job: dict[str, Any]) -> dict[str, Any]:
    """Return structured qualification for one live-discovered job."""
    text = _blob(job)
    reasons: list[str] = []
    blockers: list[str] = []
    review_reasons: list[str] = []

    work_type = _detect_work_type(text, job.get("job_type"))
    fee_required = _detect_fee(text)
    ai_policy, ai_ambiguous = _detect_ai_policy(text)
    compensation_ok = _compensation_present(job, text)
    source_ok = _source_legitimate(job)
    capability_ok = _capability_fit(text)
    credentials_hard = _has_any(text, _CREDENTIAL_TOKENS)
    degree_hard = _has_any(text, _DEGREE_TOKENS)
    regulated = _has_any(text, _REGULATED_TOKENS)
    scam = _has_any(text, _SCAM_TOKENS)
    geo_hard = _has_any(text, _GEO_HARD_TOKENS)
    individual_identity = any(
        token in text
        for token in (
            "individual applicants only",
            "must apply as an individual",
            "personal ssn required",
            "no agencies",
            "no companies",
        )
    )
    outside_capability = (not capability_ok) and work_type in {WORK_EMPLOYEE, WORK_UNKNOWN} and not _has_any(
        text, ("software engineer", "nurse", "truck driver", "attorney", "physician")
    )
    clearly_outside = any(
        token in text
        for token in (
            "must be on-site surgeon",
            "commercial truck driving",
            "in-person nursing",
            "licensed electrician on site",
        )
    )

    if work_type == WORK_EMPLOYEE:
        blockers.append("employee_w2_staff_role")
        reasons.append("Listing appears to be W-2/employee/staff employment, not AMICOR vendor/contract work.")
    if fee_required == FEE_YES:
        blockers.append("upfront_fee_or_paid_membership")
        reasons.append("Upfront fee, paid membership, or payment-to-access is required.")
    if ai_policy == AI_PROHIBITED:
        blockers.append("ai_assisted_work_prohibited")
        reasons.append("AI-assisted/AI-generated work is explicitly prohibited.")
    if credentials_hard:
        blockers.append("licensing_or_certification_required")
        reasons.append("Listing requires a license/certification AMICOR/Nova does not hold.")
    if regulated:
        blockers.append("sensitive_regulated_work")
        reasons.append("Listing involves sensitive/regulated work outside Nova's safe scope.")
    if scam:
        blockers.append("scam_or_risk_signals")
        reasons.append("Suspicious payment or scam-like signals detected.")
    if not source_ok:
        blockers.append("source_legitimacy_low")
        reasons.append("Source legitimacy is weak or incomplete.")
    if clearly_outside or (outside_capability and work_type == WORK_EMPLOYEE and not capability_ok):
        blockers.append("outside_amicor_nova_capabilities")
        reasons.append("Deliverables are outside AMICOR/Nova remote digital capability.")
    if not compensation_ok and (fee_required == FEE_YES or work_type == WORK_EMPLOYEE or not source_ok or scam):
        blockers.append("missing_compensation_high_risk")
        reasons.append("Compensation is missing and the listing otherwise looks low-confidence/high-risk.")

    if ai_ambiguous:
        review_reasons.append("AI-assisted work policy is unclear and needs owner review.")
    if work_type == WORK_UNKNOWN:
        review_reasons.append("Contractor/vendor/employee status is ambiguous.")
    if not compensation_ok and not blockers:
        review_reasons.append("Compensation needs manual confirmation.")
    if individual_identity:
        review_reasons.append("Listing may prefer individual applicants over AMICOR as a business vendor.")
    if geo_hard:
        review_reasons.append("Geographic restriction needs owner verification.")
    if degree_hard and not credentials_hard:
        review_reasons.append("Degree/credential wording needs owner verification.")
    if not capability_ok and not blockers:
        review_reasons.append("Capability fit is uncertain for AMICOR/Nova deliverables.")
    if work_type in {WORK_FREELANCE, WORK_CONTRACTOR, WORK_B2B} and not blockers and source_ok:
        reasons.append(f"Appears to be {work_type} paid work Nova can evaluate.")

    if blockers:
        outcome = OUTCOME_NOT_QUALIFIED
        risk = RISK_HIGH
        owner_review_reason = "; ".join(reasons[:4])
    elif review_reasons:
        outcome = OUTCOME_NEEDS_OWNER_REVIEW
        risk = RISK_MEDIUM
        owner_review_reason = "; ".join(review_reasons[:4])
        reasons.extend(review_reasons)
    else:
        # QUALIFIED path: no fees, legitimate, contract/freelance/B2B, clear scope/comp, no AI conflict
        if work_type not in {WORK_B2B, WORK_FREELANCE, WORK_CONTRACTOR}:
            outcome = OUTCOME_NEEDS_OWNER_REVIEW
            risk = RISK_MEDIUM
            owner_review_reason = "Work type is not clearly B2B/freelance/contractor."
            reasons.append(owner_review_reason)
        elif not compensation_ok:
            outcome = OUTCOME_NEEDS_OWNER_REVIEW
            risk = RISK_MEDIUM
            owner_review_reason = "Compensation is not clear enough for automatic qualification."
            reasons.append(owner_review_reason)
        elif not capability_ok:
            outcome = OUTCOME_NEEDS_OWNER_REVIEW
            risk = RISK_MEDIUM
            owner_review_reason = "Deliverable fit needs owner confirmation."
            reasons.append(owner_review_reason)
        else:
            outcome = OUTCOME_QUALIFIED
            risk = RISK_LOW
            owner_review_reason = "No automatic disqualifiers; ready for owner approval gate."
            reasons.append(
                "No upfront fee/membership; legitimate source; paid contract-style work; no known AI-use conflict."
            )

    fit_score = 50
    if outcome == OUTCOME_QUALIFIED:
        fit_score = 82
    elif outcome == OUTCOME_NEEDS_OWNER_REVIEW:
        fit_score = 55
    else:
        fit_score = 18
    if work_type == WORK_B2B:
        fit_score += 8
    if work_type in {WORK_FREELANCE, WORK_CONTRACTOR}:
        fit_score += 5
    if work_type == WORK_EMPLOYEE:
        fit_score -= 25
    if fee_required == FEE_YES:
        fit_score -= 30
    if ai_policy == AI_PROHIBITED:
        fit_score -= 20
    if compensation_ok:
        fit_score += 6
    if capability_ok:
        fit_score += 8
    fit_score = max(0, min(100, fit_score))

    compensation_summary = str(job.get("compensation_text") or "").strip() or (
        "Compensation not stated" if not compensation_ok else "Compensation inferred from listing text"
    )

    return {
        "qualification_status": outcome,
        "qualification_outcome": outcome,
        "risk_level": risk,
        "fit_score": fit_score,
        "fit_summary": "; ".join(reasons[:3]) or owner_review_reason,
        "compensation_summary": compensation_summary,
        "work_type": work_type,
        "ai_policy": ai_policy,
        "fee_required": fee_required,
        "owner_review_reason": owner_review_reason,
        "source_url": job.get("source_url"),
        "source_legitimate": source_ok,
        "capability_fit": capability_ok,
        "compensation_present": compensation_ok,
        "blockers": blockers,
        "review_flags": review_reasons,
        "reasons": reasons,
        "auto_prepare_allowed": outcome == OUTCOME_QUALIFIED,
        "external_submission": False,
        "financial_execution": False,
    }


def apply_qualification(job: dict[str, Any]) -> dict[str, Any]:
    row = dict(job)
    qual = qualify_live_job(row)
    row["live_qualification"] = qual
    row["qualification_status"] = qual["qualification_status"]
    row["qualification_outcome"] = qual["qualification_outcome"]
    row["risk_level"] = qual["risk_level"]
    row["fit_score"] = qual["fit_score"]
    row["fit_summary"] = qual["fit_summary"]
    row["compensation_summary"] = qual["compensation_summary"]
    row["work_type"] = qual["work_type"]
    row["ai_policy"] = qual["ai_policy"]
    row["fee_required"] = qual["fee_required"]
    row["owner_review_reason"] = qual["owner_review_reason"]
    return row


def qualification_rank_bonus(qual: dict[str, Any]) -> int:
    """Deterministic ranking adjustment after relevance scoring."""
    bonus = 0
    work_type = qual.get("work_type")
    if work_type == WORK_B2B:
        bonus += 40
    elif work_type in {WORK_FREELANCE, WORK_CONTRACTOR}:
        bonus += 28
    elif work_type == WORK_EMPLOYEE:
        bonus -= 40
    if qual.get("fee_required") == FEE_YES:
        bonus -= 50
    if qual.get("qualification_status") == OUTCOME_QUALIFIED:
        bonus += 35
    elif qual.get("qualification_status") == OUTCOME_NEEDS_OWNER_REVIEW:
        bonus += 5
    else:
        bonus -= 45
    if qual.get("ai_policy") == AI_PROHIBITED:
        bonus -= 25
    elif qual.get("ai_policy") == AI_UNCLEAR:
        bonus -= 5
    if qual.get("compensation_present"):
        bonus += 10
    if qual.get("capability_fit"):
        bonus += 12
    return bonus


def qualify_and_rank_live_jobs(query: str, jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.core.nova.v3.live_discovery import rank_live_jobs

    ranked = rank_live_jobs(query, jobs)
    enriched: list[dict[str, Any]] = []
    for job in ranked:
        row = apply_qualification(job)
        base = int(row.get("relevance_score") or 0)
        qual = row["live_qualification"]
        row["relevance_score"] = base + qualification_rank_bonus(qual)
        row["ranking_components"] = {
            "base_relevance": base,
            "qualification_bonus": qualification_rank_bonus(qual),
            "qualification_status": qual["qualification_status"],
        }
        enriched.append(row)
    return sorted(
        enriched,
        key=lambda item: (
            int(item.get("relevance_score") or 0),
            int((item.get("live_qualification") or {}).get("fit_score") or 0),
            str(item.get("publication_date") or ""),
        ),
        reverse=True,
    )


def partition_by_qualification(jobs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets = {
        OUTCOME_QUALIFIED: [],
        OUTCOME_NEEDS_OWNER_REVIEW: [],
        OUTCOME_NOT_QUALIFIED: [],
    }
    for job in jobs:
        status = str(job.get("qualification_status") or OUTCOME_NEEDS_OWNER_REVIEW)
        if status not in buckets:
            buckets[OUTCOME_NEEDS_OWNER_REVIEW].append(job)
        else:
            buckets[status].append(job)
    return buckets
