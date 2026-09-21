"""Duty-based opportunity capability classification.

The job title is never used to decide the class. Nova reads the description,
requirements, skills, credentials, engagement type, physical-presence flag,
and AI/vendor notes.
"""

from __future__ import annotations

import re
from typing import Any

CAN_PERFORM = "CAN_PERFORM"
NEEDS_OWNER_REVIEW = "NEEDS_OWNER_REVIEW"
CANNOT_PERFORM = "CANNOT_PERFORM"
INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"

_WS = re.compile(r"\s+")

_DIGITAL: tuple[tuple[str, str, str], ...] = (
    (r"\bresearch\b", "research", "research"),
    (r"\bspreadsheet\b|\bexcel\b|\bgoogle sheets\b", "spreadsheet_analysis", "spreadsheet cleanup and analysis"),
    (r"\breport(?:ing|s)?\b|\bdata analysis\b", "reporting", "reporting"),
    (r"\bdocument preparation\b|\bprepare documents\b|\bdraft(?:ing)? documents\b", "document_preparation", "document preparation"),
    (r"\bdata organization\b|\borganiz(?:e|ing) (?:data|records|crm)\b|\bdata entry\b", "data_organization", "data organization"),
    (r"\bemail drafts?\b|\bemail drafting\b|\bdraft(?:ing)? emails?\b", "administrative_support", "administrative support"),
    (r"\bworkflow documentation\b|\bdocument(?:ing)? workflows\b|\bsops?\b", "workflow_documentation", "workflow documentation"),
    (r"\bproposal\b|\brfp\b", "proposal_drafting", "proposal and RFP drafting"),
    (r"\bcustomer[- ]support operations\b|\bsupport operations\b", "customer_support_operations", "customer-support operations"),
    (r"\bcontent operations\b|\bcontent calendar\b", "content_operations", "content operations"),
    (r"\bweb support\b|\bsoftware support\b|\bwebsite updates\b", "web_software_support", "web and software support"),
    (r"\bai-assisted analysis\b|\bai assisted analysis\b", "ai_assisted_analysis", "AI-assisted analysis"),
    (r"\bbookkeeping support\b|\bbookkeeping\b", "bookkeeping_support", "bookkeeping support"),
    (r"\bdraft(?:ing)? (?:emails|communications|follow-up)\b|\bscheduling support\b", "administrative_support", "drafting and scheduling support"),
)

_PHYSICAL = re.compile(
    r"\b("
    r"driv(?:e|ing)|operate (?:a |the )?vehicle|vehicle operation|delivery driver|"
    r"forklift|heavy lifting|\blifting\b|\bloading\b|\bpicking\b|\bpacking\b|\bstocking\b|"
    r"physical labor|in-person manual|manual work|on-site physical"
    r")\b",
    re.I,
)
_NURSING = re.compile(
    r"\b(registered nurse|\brn\b|nursing practice|patient care|clinical judgment|licensed medical)\b",
    re.I,
)
_LICENSED_PRO = re.compile(
    r"\b("
    r"attorney|legal advice|legal opinion|cpa opinion|audit opinion|"
    r"licensed accountant|clinical practice|diagnos(?:e|is)|prescribe"
    r")\b",
    re.I,
)
_W2 = re.compile(r"\b(w-2|w2|staff employment|full-time employee|employee role)\b", re.I)
_IDENTITY = re.compile(
    r"\b(specific individual|named specialist|talent network membership|phone-only)\b",
    re.I,
)
_AI_UNCLEAR = re.compile(
    r"\b(ai(?:-|\s)?use policy (?:is )?unclear|ai policy (?:is )?unclear|ai policy not stated|ai rules unclear)\b",
    re.I,
)
_AI_PROHIBITED = re.compile(r"\b(ai[- ]assisted work is not allowed|ai prohibited|do not use ai|no ai tools)\b", re.I)
_HUMAN_PARTIAL = re.compile(
    r"\b(in-person meetings required|human participation unclear|subcontractor rules unclear|phone support required|must call|phone call|call the hiring)\b",
    re.I,
)
_CONTRACT_UNCLEAR = re.compile(
    r"\b(compensation terms (?:are )?unclear|contract terms need confirmation|vendor compatibility unclear)\b",
    re.I,
)
_VAGUE_TITLE = re.compile(r"^(role not described|untitled|unknown|tbd|n/?a)$", re.I)


def _clean(value: Any) -> str:
    return _WS.sub(" ", str(value or "")).strip()


def _joined(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return _clean(" ".join(_clean(item) for item in value))
    return _clean(value)


def _affirmed(pattern: re.Pattern[str], text: str) -> bool:
    """True when a phrase is present and not directly negated."""
    for match in pattern.finditer(text or ""):
        prefix = text[max(0, match.start() - 16):match.start()]
        if re.search(r"\b(?:no|not|without|non-)\s*$", prefix, re.I):
            continue
        return True
    return False


def duty_corpus(opportunity: dict[str, Any]) -> str:
    """Work description used for classification. Title is excluded."""
    parts = [
        opportunity.get("description"),
        opportunity.get("requirements"),
        opportunity.get("skills"),
        opportunity.get("skills_required"),
        opportunity.get("credentials"),
        opportunity.get("credentials_required"),
        opportunity.get("engagement_type"),
        opportunity.get("job_type"),
        opportunity.get("remote_status"),
        opportunity.get("ai_usage_policy"),
        opportunity.get("ai_policy"),
    ]
    return _clean(" ".join(_joined(part) for part in parts if _joined(part)))


def classify_opportunity_capability(opportunity: dict[str, Any]) -> dict[str, Any]:
    title = _clean(opportunity.get("opportunity_title") or opportunity.get("title"))
    duties = duty_corpus(opportunity)
    physical_flag = _clean(opportunity.get("physical_presence_required")).lower()
    engagement = _clean(opportunity.get("engagement_type") or opportunity.get("job_type")).lower()

    registry: list[str] = []
    nova_can: list[str] = []
    for pattern, label, phrase in _DIGITAL:
        if re.search(pattern, duties, re.I) and label not in registry:
            registry.append(label)
            nova_can.append(phrase)

    physical_hit = _affirmed(_PHYSICAL, duties) or physical_flag == "true"
    nursing_hit = _affirmed(_NURSING, duties)
    licensed_hit = _affirmed(_LICENSED_PRO, duties) or nursing_hit
    w2_hit = _affirmed(_W2, duties) or engagement in {"w2", "w-2", "employee", "full_time", "full-time"}
    identity_hit = _affirmed(_IDENTITY, duties)
    ai_unclear = bool(_AI_UNCLEAR.search(duties))
    ai_banned = _affirmed(_AI_PROHIBITED, duties)
    human_partial = bool(_HUMAN_PARTIAL.search(duties))
    contract_unclear = bool(_CONTRACT_UNCLEAR.search(duties))
    hard_block = physical_hit or nursing_hit or licensed_hit or w2_hit or identity_hit or ai_banned

    nova_cannot: list[str] = []
    human_actions: list[str] = []
    license_needed = ""
    if _affirmed(re.compile(r"\b(driv(?:e|ing)|operate (?:a |the )?vehicle|vehicle operation)\b", re.I), duties):
        nova_cannot.append("drive a vehicle or transport packages physically")
    if _affirmed(re.compile(r"\b(forklift|heavy lifting|\blifting\b|\bpicking\b|\bpacking\b|\bloading\b|\bstocking\b|physical labor)\b", re.I), duties):
        nova_cannot.append("lifting, picking, packing, loading, or stocking")
    if physical_flag == "true" and not nova_cannot:
        nova_cannot.append("in-person physical presence")
    elif physical_flag == "true":
        nova_cannot.append("in-person physical presence")
    if nursing_hit:
        nova_cannot.append("nursing practice, patient care, and clinical judgment")
        license_needed = "RN license"
    elif licensed_hit:
        nova_cannot.append("licensed professional legal, accounting, or clinical judgment")
        license_needed = "licensed professional credential"
    if w2_hit:
        nova_cannot.append("W-2 or staff employment")
    if identity_hit:
        nova_cannot.append("identity-dependent or phone-only duties")
    if ai_banned:
        nova_cannot.append("work where AI use is prohibited")

    vague = (not duties) or (len(duties) < 24 and not registry) or bool(_VAGUE_TITLE.match(title) and not registry and not hard_block)
    if not registry and not hard_block and (not duties or vague or bool(_VAGUE_TITLE.match(title))):
        classification = INSUFFICIENT_INFORMATION
        blocking = "insufficient duties/deliverables"
        review_reason = ""
        fit = 0.0
        nova_can = []
        human_actions.append("Provide the actual duties and deliverables before qualification")
    elif hard_block:
        classification = CANNOT_PERFORM
        blocking = nova_cannot[0] if nova_cannot else "outside Nova verified capability"
        review_reason = ""
        fit = 0.1
        if registry:
            nova_can = [f"{item} only if separately contracted" for item in nova_can]
        elif re.search(r"\b(?:driv|deliver)", duties, re.I):
            nova_can = ["route research, delivery documentation, dispatch/admin support if separately contracted"]
        elif re.search(r"\b(warehouse|inventory|lift|pick|pack)\b", duties, re.I):
            nova_can = ["inventory spreadsheet analysis and reporting only if separately scoped"]
        if nursing_hit:
            nova_can.append("non-clinical admin, document, and data support if separately scoped")
    elif ai_unclear or human_partial or contract_unclear:
        classification = NEEDS_OWNER_REVIEW
        blocking = ""
        review_reason = (
            "AI-use policy is unclear"
            if ai_unclear
            else "scope partly fits but includes duties or contract terms that need owner confirmation"
        )
        fit = 0.55
        human_actions.append("Owner confirms AI policy, contract type, and any human-only duties")
    elif registry:
        classification = CAN_PERFORM
        blocking = ""
        review_reason = ""
        fit = min(0.95, 0.72 + 0.04 * len(registry))
    else:
        classification = INSUFFICIENT_INFORMATION
        blocking = "insufficient duties/deliverables"
        review_reason = ""
        fit = 0.0
        human_actions.append("Provide the actual duties and deliverables before qualification")

    if re.search(r"\bdriver.?s license\b", duties, re.I) and not license_needed:
        license_needed = "driver's license"

    deliverables = [item for item in nova_can if "separately" not in item]
    return {
        "capability_classification": classification,
        "capability_fit_score": round(fit, 2),
        "nova_can_do": nova_can,
        "nova_cannot_do": nova_cannot,
        "required_human_actions": human_actions,
        "required_physical_presence": "YES" if physical_hit else "NO",
        "required_license_or_credential": license_needed,
        "deliverables_nova_can_produce": deliverables,
        "blocking_reason": blocking,
        "owner_review_reason": review_reason,
        "capability_registry_matches": registry,
        "owner_review_needed": classification == NEEDS_OWNER_REVIEW,
        "auto_prepare_allowed": classification not in {CANNOT_PERFORM, INSUFFICIENT_INFORMATION},
        "title_used_for_decision": False,
    }
