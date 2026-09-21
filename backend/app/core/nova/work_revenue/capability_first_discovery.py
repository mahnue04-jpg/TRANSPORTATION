"""Capability-first nationwide discovery planning for Nova Work.

Discovery order:
  verified capability registry
  → allowed work families
  → targeted remote/vendor/contract queries
  → source discovery (caller)
  → duty classifier / qualification guards (caller)

This module never contacts employers, submits applications, or moves money.
"""

from __future__ import annotations

import re
from typing import Any

from app.core.nova.v3.capability_catalog import CAPABILITIES as V3_CAPABILITIES
from app.core.nova.work_revenue.capability_classification import classify_opportunity_capability
from app.core.nova.work_revenue.capability_registry import list_capabilities, nova_supported_ids

# Preferred opportunity wording baked into generated queries.
_REMOTE_VENDOR_TERMS = (
    "remote",
    "contract",
    "contractor",
    "freelance",
    "independent contractor",
    "vendor",
)

# Explicitly banned generic occupation searches.
_BANNED_QUERY_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bdelivery driver\b", re.I),
    re.compile(r"\bwarehouse associate\b", re.I),
    re.compile(r"\bregistered nurse\b", re.I),
    re.compile(r"\bwarehouse jobs?\b", re.I),
    re.compile(r"\bdelivery driver jobs?\b", re.I),
    re.compile(r"\bregistered nurse jobs?\b", re.I),
    re.compile(r"\bjobs near me\b", re.I),
    re.compile(r"^\s*nurse\s*$", re.I),
    re.compile(r"^\s*truck driver\s*$", re.I),
)

_DOWNRANK_SIGNALS = re.compile(
    r"\b("
    r"w-2|w2|full-time employee|employee role|onsite|on-site|must report in person|"
    r"driver|physical labor|lifting|manual labor|shift work onsite|"
    r"licensed professional|rn required|cpa required|security clearance|"
    r"named[- ]person|talent network"
    r")\b",
    re.I,
)
_PREFERRED_SIGNALS = re.compile(
    r"\b("
    r"remote|contract|contractor|freelance|independent contractor|vendor|"
    r"consultant|project|b2b|fixed-price|hourly contract|remote services"
    r")\b",
    re.I,
)
_STATE_RESTRICT = re.compile(
    r"\b("
    r"must (?:reside|live) in|residents? only|only (?:candidates|applicants) in|"
    r"(?:alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|"
    r"florida|georgia|hawaii|idaho|illinois|indiana|iowa|kansas|kentucky|louisiana|"
    r"maine|maryland|massachusetts|michigan|minnesota|mississippi|missouri|montana|"
    r"nebraska|nevada|new hampshire|new jersey|new mexico|new york|north carolina|"
    r"north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|"
    r"south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|"
    r"wisconsin|wyoming) (?:residents?|only)"
    r")\b",
    re.I,
)

SEARCH_FAMILIES: dict[str, dict[str, Any]] = {
    "administrative_operations": {
        "label": "Administrative operations",
        "capability_ids": ("administrative_operations", "ADMINISTRATIVE_SUPPORT", "SCHEDULING_SUPPORT", "CRM_DATA_ORGANIZATION"),
        "queries": (
            "remote administrative support contractor",
            "virtual administrative assistant contractor",
            "operations support contractor remote",
            "document preparation contractor remote",
            "project administration remote contractor",
            "scheduling support independent contractor",
            "data entry contractor remote",
            "CRM cleanup freelance project",
            "workflow documentation contractor remote",
            "business operations support remote contractor",
        ),
    },
    "bookkeeping_support": {
        "label": "Bookkeeping / financial admin support",
        "capability_ids": ("bookkeeping_support",),
        "queries": (
            "bookkeeping support contractor remote no CPA",
            "bookkeeping cleanup remote contractor",
            "transaction categorization freelance project",
            "expense organization remote contractor",
            "invoice preparation administrative support contractor",
            "accounts receivable administrative support remote",
            "accounts payable administrative support remote",
            "reconciliation support remote contractor",
            "financial spreadsheet preparation freelance",
            "financial reporting support contractor remote",
        ),
        "block_terms": ("CPA required", "audit opinion", "tax signing", "licensed financial advice"),
    },
    "data_spreadsheet": {
        "label": "Data / spreadsheets / reporting",
        "capability_ids": ("data_spreadsheet", "REPORTING", "CRM_DATA_ORGANIZATION"),
        "queries": (
            "Excel contractor remote",
            "spreadsheet cleanup freelance project",
            "spreadsheet analysis remote contractor",
            "CSV cleanup freelance project",
            "data cleanup remote contractor",
            "data organization independent contractor",
            "data validation remote contractor",
            "reporting contractor remote",
            "dashboard report preparation freelance",
            "inventory data analysis remote contractor",
        ),
    },
    "research_analysis": {
        "label": "Research / analysis",
        "capability_ids": ("business_research", "RESEARCH"),
        "queries": (
            "internet research contractor remote",
            "business research freelance project",
            "market research assistant remote contractor",
            "competitor research freelance project",
            "supplier research remote contractor",
            "lead research freelance project",
            "information gathering remote contractor",
            "data research freelance project",
            "research report preparation remote contractor",
        ),
    },
    "document_writing": {
        "label": "Document / writing support",
        "capability_ids": ("content_documentation", "proposal_rfp", "document_intelligence", "DOCUMENT_PREPARATION", "PROPOSAL_DRAFTING"),
        "queries": (
            "business document preparation remote contractor",
            "report preparation freelance project",
            "proposal drafting remote contractor",
            "RFP support freelance project",
            "RFP proposal support contractor remote",
            "SOP creation remote contractor",
            "process documentation freelance project",
            "document formatting remote contractor",
            "presentation content freelance project",
            "business correspondence drafting remote",
            "content operations remote contractor",
        ),
    },
    "customer_support_operations": {
        "label": "Customer support / back office",
        "capability_ids": ("customer_support_operations", "CUSTOMER_FOLLOWUP_DRAFTING", "EMAIL_DRAFTING"),
        "queries": (
            "email support contractor remote",
            "chat support contractor remote",
            "customer support operations remote contractor",
            "ticket triage remote contractor",
            "FAQ support freelance project",
            "CRM organization remote contractor",
            "customer data cleanup freelance",
            "response drafting remote contractor",
        ),
        "owner_review_if": ("phone", "live phone", "named specialist", "AI policy unclear"),
    },
    "web_software": {
        "label": "Web / software / digital support",
        "capability_ids": ("web_software", "ai_workflow_automation"),
        "queries": (
            "website updates remote contractor",
            "HTML CSS fixes freelance project",
            "QA testing support remote contractor",
            "technical documentation freelance project",
            "website administration remote contractor",
            "data transformation freelance project",
            "workflow automation remote contractor",
            "API integration support freelance project",
            "software documentation remote contractor",
        ),
        "verified_only": True,
    },
    "logistics_digital": {
        "label": "Logistics / warehouse digital support",
        "capability_ids": ("data_spreadsheet", "business_research", "administrative_operations", "REPORTING"),
        "queries": (
            "remote inventory analyst contractor",
            "inventory reconciliation remote contractor",
            "warehouse reporting contractor remote",
            "logistics data support freelance project",
            "shipment tracking administration remote",
            "inventory data cleanup remote contractor",
            "logistics research freelance project",
            "warehouse documentation remote contractor",
            "route analysis remote contractor",
            "dispatch administrative support remote contractor",
        ),
        "never_generate": ("warehouse associate", "warehouse jobs"),
    },
    "transportation_digital": {
        "label": "Transportation / delivery digital support",
        "capability_ids": ("data_spreadsheet", "administrative_operations", "business_research", "REPORTING"),
        "queries": (
            "dispatch support contractor remote",
            "route planning support remote contractor",
            "transportation reporting freelance project",
            "shipment tracking remote contractor",
            "logistics administration remote contractor",
            "delivery data analysis remote contractor",
            "delivery documentation remote contractor",
            "fleet spreadsheet reporting remote contractor",
        ),
        "never_generate": ("delivery driver", "delivery driver jobs"),
    },
    "healthcare_non_clinical": {
        "label": "Healthcare non-clinical support",
        "capability_ids": ("administrative_operations", "data_spreadsheet", "content_documentation", "document_intelligence"),
        "queries": (
            "healthcare administrative support remote contractor",
            "healthcare data cleanup freelance project",
            "records organization remote contractor",
            "medical document formatting remote contractor",
            "non-clinical scheduling support remote",
            "healthcare reporting support remote contractor",
            "healthcare operations research freelance",
        ),
        "never_generate": ("registered nurse", "registered nurse jobs", "clinical practitioner"),
        "block_terms": ("diagnosis", "treatment", "patient care", "medication administration", "clinical judgment"),
    },
    "ai_automation": {
        "label": "AI / automation contract work",
        "capability_ids": ("ai_workflow_automation", "document_intelligence", "content_documentation"),
        "queries": (
            "AI operations contractor remote",
            "AI workflow automation contractor remote",
            "AI workflow support freelance project",
            "AI research support remote contractor",
            "automation contractor remote",
            "prompt document workflow support freelance",
            "AI content operations remote contractor",
            "AI data quality freelance project",
            "AI evaluation contractor remote vendor allowed",
        ),
        "respect_ai_policy": True,
    },
}


def _supported_capability_keys() -> set[str]:
    keys = set(nova_supported_ids())
    keys.update(V3_CAPABILITIES.keys())
    # availability filter from work_revenue registry
    for row in list_capabilities():
        if row.get("availability") in {"AVAILABLE", "AVAILABLE_WITH_OWNER_REVIEW"}:
            keys.add(str(row.get("capability_id")))
    return keys


def is_banned_query(query: str) -> bool:
    text = str(query or "").strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in _BANNED_QUERY_PATTERNS)


def _family_supported(family: dict[str, Any], supported: set[str]) -> bool:
    ids = family.get("capability_ids") or ()
    if family.get("verified_only"):
        return any(item in supported for item in ids)
    return any(item in supported for item in ids) or True


def generate_capability_first_queries(
    *,
    families: list[str] | None = None,
    include_nationwide_remote: bool = True,
) -> list[dict[str, Any]]:
    """Build targeted discovery queries from verified capabilities and families."""
    supported = _supported_capability_keys()
    selected = families or list(SEARCH_FAMILIES.keys())
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for family_id in selected:
        family = SEARCH_FAMILIES.get(family_id)
        if not family:
            continue
        if not _family_supported(family, supported):
            continue
        matched_caps = [cid for cid in family["capability_ids"] if cid in supported]
        for query in family["queries"]:
            q = str(query).strip()
            if not q or is_banned_query(q):
                continue
            key = q.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "query": q,
                    "search_family": family_id,
                    "search_family_label": family["label"],
                    "capability_registry_matches": matched_caps,
                    "why_searched": (
                        f"Capability-first nationwide remote/digital search for {family['label']} "
                        "using verified Nova capabilities."
                    ),
                    "geography": "United States remote nationwide" if include_nationwide_remote else "remote",
                    "preferred_signals": list(_REMOTE_VENDOR_TERMS),
                }
            )
    return rows


def capability_first_search_queries(*, families: list[str] | None = None) -> list[str]:
    return [row["query"] for row in generate_capability_first_queries(families=families)]


def search_family_catalog() -> list[dict[str, Any]]:
    supported = _supported_capability_keys()
    rows: list[dict[str, Any]] = []
    for family_id, family in SEARCH_FAMILIES.items():
        rows.append(
            {
                "family_id": family_id,
                "label": family["label"],
                "capability_ids": list(family["capability_ids"]),
                "supported": _family_supported(family, supported),
                "query_count": len(
                    [q for q in family["queries"] if not is_banned_query(q)]
                ),
                "sample_queries": [q for q in family["queries"] if not is_banned_query(q)][:3],
                "never_generate": list(family.get("never_generate") or ()),
            }
        )
    return rows


def score_discovery_candidate(job: dict[str, Any], *, query: str | None = None) -> dict[str, Any]:
    """Immediate post-discovery scoring before or with qualification."""
    text = " ".join(
        str(job.get(key) or "")
        for key in ("title", "description", "job_type", "geography", "compensation_text", "remote_status")
    )
    duty = classify_opportunity_capability(
        {
            "title": job.get("title") or job.get("opportunity_title"),
            "description": job.get("description"),
            "requirements": job.get("requirements"),
            "skills_required": job.get("skills_required"),
            "credentials_required": job.get("credentials_required"),
            "engagement_type": job.get("job_type") or job.get("engagement_type"),
            "remote_status": job.get("remote_status") or "remote",
            "physical_presence_required": job.get("physical_presence_required") or "unknown",
            "ai_policy": job.get("ai_policy"),
        }
    )
    score = 55
    preferred_hits = len(_PREFERRED_SIGNALS.findall(text))
    downrank_hits = len(_DOWNRANK_SIGNALS.findall(text))
    score += min(25, preferred_hits * 4)
    score -= min(40, downrank_hits * 12)

    remote_ok = "remote" in text.lower() or str(job.get("remote_status") or "").lower() == "remote"
    if remote_ok:
        score += 8
    else:
        score -= 20

    state_restricted = bool(_STATE_RESTRICT.search(text))
    if state_restricted:
        score -= 8

    classification = duty["capability_classification"]
    if classification == "CAN_PERFORM":
        score += 20
    elif classification == "NEEDS_OWNER_REVIEW":
        score += 5
    elif classification == "INSUFFICIENT_INFORMATION":
        score = min(score, 45)
    else:
        score = min(score, 35)

    score = max(0, min(100, score))
    if classification == "INSUFFICIENT_INFORMATION":
        band = "INSUFFICIENT_INFORMATION"
    elif score >= 80:
        band = "STRONG_FIT"
    elif score >= 60:
        band = "OWNER_REVIEW"
    else:
        band = "REJECT"

    family = match_query_to_family(query or "")
    return {
        "discovery_score": score,
        "discovery_band": band,
        "capability_match": bool(duty["capability_registry_matches"]),
        "remote_eligibility": "YES" if remote_ok else "NO",
        "vendor_contract_compatibility": "YES" if preferred_hits else "UNKNOWN",
        "physical_presence_requirement": duty["required_physical_presence"],
        "license_requirement": duty["required_license_or_credential"] or "NONE",
        "AI_policy": job.get("ai_policy") or "unknown",
        "human_identity_requirement": "YES" if "named" in text.lower() or "talent network" in text.lower() else "NO",
        "fee_to_apply": "unknown",
        "compensation_signal": "YES" if job.get("compensation_text") else "UNKNOWN",
        "actual_duty_fit": classification,
        "capability_classification": classification,
        "capability_registry_matches": duty["capability_registry_matches"],
        "nova_can_do": duty["nova_can_do"],
        "nova_cannot_do": duty["nova_cannot_do"],
        "deliverables_nova_can_produce": duty["deliverables_nova_can_produce"],
        "owner_review_needed": duty["owner_review_needed"] or band == "OWNER_REVIEW",
        "state_restriction_detected": state_restricted,
        "search_family": (family or {}).get("family_id"),
        "search_family_label": (family or {}).get("label"),
        "why_searched": (family or {}).get("why_searched")
        or "Capability-first remote/digital discovery against verified Nova capabilities.",
        "title_used_for_decision": False,
        "nationwide_remote_allowed": True,
    }


def match_query_to_family(query: str) -> dict[str, Any] | None:
    q = str(query or "").strip().lower()
    if not q:
        return None
    for family_id, family in SEARCH_FAMILIES.items():
        for candidate in family["queries"]:
            if candidate.lower() == q or candidate.lower() in q or q in candidate.lower():
                return {
                    "family_id": family_id,
                    "label": family["label"],
                    "why_searched": (
                        f"Capability-first nationwide remote/digital search for {family['label']}."
                    ),
                }
    # soft keyword match
    for family_id, family in SEARCH_FAMILIES.items():
        label_bits = family["label"].lower().split()
        if any(bit in q for bit in label_bits if len(bit) > 4):
            return {
                "family_id": family_id,
                "label": family["label"],
                "why_searched": (
                    f"Capability-first nationwide remote/digital search for {family['label']}."
                ),
            }
    return None


def assert_no_banned_generated_queries(queries: list[str] | None = None) -> None:
    for query in queries or capability_first_search_queries():
        if is_banned_query(query):
            raise AssertionError(f"Banned generic query generated: {query}")
