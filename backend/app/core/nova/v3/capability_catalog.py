"""AMICOR Nova capability catalog and capability matching.

This module teaches Nova what kinds of paid digital work it can actually perform
as an AI-assisted business service. It is descriptive only: it never submits,
contacts clients, accepts contracts, moves money, or bypasses owner approval.
"""
from __future__ import annotations

import re
from typing import Any

CAPABILITIES: dict[str, dict[str, Any]] = {
    "business_research": {
        "label": "Business research & analysis",
        "keywords": (
            "market research", "competitor research", "company research", "vendor research",
            "lead research", "business research", "research brief", "research report",
            "industry research", "competitive analysis", "web research", "desk research",
        ),
        "deliverables": (
            "research brief", "source list", "comparison table", "market summary",
            "competitor matrix", "lead list",
        ),
        "search_queries": (
            "B2B market research contractor",
            "business research freelance project",
            "vendor research consulting project",
            "competitive analysis contract",
        ),
    },
    "administrative_operations": {
        "label": "Administrative operations",
        "keywords": (
            "administrative support", "administrative operations", "virtual assistant",
            "calendar management", "inbox organization", "task tracking", "meeting notes",
            "meeting summary", "follow-up tracking", "document organization", "sop",
            "standard operating procedure", "operations support",
        ),
        "deliverables": (
            "organized task tracker", "meeting summary", "follow-up plan",
            "document system", "SOP", "administrative workflow",
        ),
        "search_queries": (
            "B2B administrative operations contractor",
            "remote administrative workflow project",
            "virtual operations support contract",
        ),
    },
    "data_spreadsheet": {
        "label": "Data & spreadsheet work",
        "keywords": (
            "data cleaning", "spreadsheet", "excel", "google sheets", "csv", "data analysis",
            "dashboard", "reporting", "data entry automation", "data transformation",
            "data categorization", "reconciliation spreadsheet", "pivot table",
        ),
        "deliverables": (
            "clean dataset", "spreadsheet model", "dashboard", "analysis report",
            "reconciliation workbook", "structured CSV",
        ),
        "search_queries": (
            "spreadsheet automation contract",
            "data cleaning freelance project",
            "Excel reporting contractor",
            "Google Sheets automation project",
        ),
    },
    "ai_workflow_automation": {
        "label": "AI workflow automation",
        "keywords": (
            "workflow automation", "ai automation", "business automation", "zapier", "make.com",
            "make automation", "n8n", "api integration", "google apps script",
            "google workspace automation", "crm automation", "email automation",
            "document automation", "ai agent", "agent workflow", "process automation",
        ),
        "deliverables": (
            "workflow map", "automation", "integration", "agent workflow",
            "test evidence", "implementation documentation",
        ),
        "search_queries": (
            "AI workflow automation contractor",
            "Zapier automation project",
            "Make.com automation contractor",
            "n8n workflow project",
            "Google Workspace automation consultant",
            "AI agent workflow contract",
        ),
    },
    "bookkeeping_support": {
        "label": "Bookkeeping support",
        "keywords": (
            "bookkeeping support", "transaction categorization", "expense categorization",
            "receipt organization", "reconciliation preparation", "expense report",
            "financial spreadsheet", "invoice tracking", "accounts receivable tracking",
            "accounts payable tracking",
        ),
        "deliverables": (
            "categorized transactions", "receipt index", "reconciliation support file",
            "expense report", "invoice tracker", "financial summary",
        ),
        "search_queries": (
            "bookkeeping support contractor no CPA required",
            "expense categorization freelance project",
            "invoice tracking contract project",
        ),
    },
    "content_documentation": {
        "label": "Content & documentation",
        "keywords": (
            "business writing", "technical writing", "documentation", "knowledge base",
            "faq", "website copy", "proposal writing", "report writing", "research brief",
            "content operations", "content editing", "sop writing",
        ),
        "deliverables": (
            "business document", "knowledge-base article", "FAQ", "website copy",
            "proposal draft", "report", "SOP",
        ),
        "search_queries": (
            "business documentation contract",
            "technical documentation freelance project",
            "SOP writing contractor",
            "content operations contract",
        ),
    },
    "web_software": {
        "label": "Web & software implementation",
        "keywords": (
            "landing page", "website development", "web development", "frontend",
            "backend integration", "api integration", "web form", "bug fix", "debugging",
            "software testing", "qa automation", "small web app", "internal tool",
            "website maintenance",
        ),
        "deliverables": (
            "website", "landing page", "web form", "API integration", "bug fix",
            "test report", "small application", "technical documentation",
        ),
        "search_queries": (
            "small web development contract project",
            "API integration freelance project",
            "website automation contractor",
            "software testing contract project",
        ),
    },
    "customer_support_operations": {
        "label": "Customer-support operations",
        "keywords": (
            "customer support operations", "support workflow", "ticket classification",
            "ticket triage", "support knowledge base", "customer issue summary",
            "response templates", "help desk automation", "support automation",
        ),
        "deliverables": (
            "ticket taxonomy", "response templates", "support workflow",
            "knowledge base", "issue summary report",
        ),
        "search_queries": (
            "customer support automation contractor",
            "help desk workflow project",
            "support knowledge base contract",
        ),
    },
    "proposal_rfp": {
        "label": "Proposal & RFP support",
        "keywords": (
            "rfp", "request for proposal", "proposal support", "proposal preparation",
            "compliance matrix", "bid response", "scope of work", "statement of work",
            "proposal research",
        ),
        "deliverables": (
            "proposal draft", "compliance matrix", "RFP summary", "scope draft",
            "submission package for owner review",
        ),
        "search_queries": (
            "RFP proposal support contractor",
            "proposal preparation freelance project",
            "bid response support contract",
        ),
    },
    "document_intelligence": {
        "label": "Document intelligence",
        "keywords": (
            "document extraction", "pdf extraction", "document processing", "ocr review",
            "contract comparison", "form extraction", "document summarization",
            "document classification", "file organization", "document analysis",
        ),
        "deliverables": (
            "structured extracted data", "document summary", "comparison table",
            "document index", "classified file set",
        ),
        "search_queries": (
            "document processing automation contract",
            "PDF data extraction freelance project",
            "document analysis contractor",
        ),
    },
}

_HUMAN_ONLY_PATTERNS = (
    "must personally perform",
    "human evaluator",
    "human rater",
    "in-person",
    "on-site",
    "onsite",
    "phone calls required all day",
    "cold calling required",
    "field work",
)

_REGULATED_PATTERNS = (
    "legal advice",
    "medical diagnosis",
    "prescribe",
    "cpa required",
    "licensed attorney",
    "nursing license",
    "security clearance",
)

# Single generic tokens that must never qualify a capability alone.
_WEAK_KEYWORD_TOKENS = frozenset(
    {
        "sop",
        "admin",
        "support",
        "operations",
        "report",
        "reporting",
        "faq",
        "csv",
    }
)

# Titles/role families that are specialist ICs and must not ride weak admin/support matches.
_SPECIALIST_TITLE_RE = re.compile(
    r"\b("
    r"product designer|ux designer|ui designer|graphic designer|visual designer|"
    r"software engineer|software developer|full[-\s]?stack|frontend engineer|backend engineer|"
    r"devops|site reliability|sre\b|shopify developer|mobile developer|ios developer|"
    r"android developer|machine learning engineer|ml engineer|ai engineer|ai architect|"
    r"data scientist|staff engineer|principal engineer|engineering manager"
    r")\b",
    re.I,
)

# Capabilities that are compatible with software/web implementation titles.
_ENGINEERING_CAPABILITIES = frozenset({"web_software", "ai_workflow_automation"})


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower()).strip()


def _is_strong_keyword(keyword: str) -> bool:
    """Multi-word or concrete capability phrases count as strong evidence."""
    token = str(keyword or "").strip().lower()
    if not token or token in _WEAK_KEYWORD_TOKENS:
        return False
    if " " in token:
        return True
    # Longer single tokens are usually concrete tools/deliverables.
    return len(token) >= 10


def _title_conflicts_with_capability(title: str, capability_id: str) -> bool:
    """Reject weak cross-family matches (e.g. Product Designer → administrative_operations)."""
    title_l = _normalize(title)
    if not title_l or not _SPECIALIST_TITLE_RE.search(title_l):
        return False
    if capability_id in _ENGINEERING_CAPABILITIES:
        # Design titles still conflict with implementation capabilities.
        if re.search(r"\b(product designer|ux designer|ui designer|graphic designer|visual designer)\b", title_l):
            return True
        return False
    return True


def capability_matches(text: str, *, title: str | None = None) -> list[dict[str, Any]]:
    """Return matched capability families with multi-signal evidence and score.

    A single weak token (sop/support/report/admin/operations) never qualifies a family.
    Prefer multi-word duty phrases and multiple corroborating signals.
    """
    blob = _normalize(text)
    title_l = _normalize(title or "")
    matches: list[dict[str, Any]] = []
    for key, spec in CAPABILITIES.items():
        hits = sorted({kw for kw in spec["keywords"] if kw in blob})
        if not hits:
            continue
        strong_hits = [h for h in hits if _is_strong_keyword(h)]
        weak_hits = [h for h in hits if h not in strong_hits]
        # Require at least one strong signal; weak-only matches are discarded.
        if not strong_hits:
            continue
        # Prefer corroboration: strong multi-word OR strong + another signal.
        multi_word_strong = [h for h in strong_hits if " " in h]
        if not multi_word_strong and len(strong_hits) + len(weak_hits) < 2:
            continue
        if title_l and _title_conflicts_with_capability(title_l, key):
            continue
        score = min(100, 50 + 12 * len(strong_hits) + 4 * len(weak_hits))
        if multi_word_strong:
            score = min(100, score + 8)
        matches.append(
            {
                "capability_id": key,
                "label": spec["label"],
                "score": score,
                "matched_terms": hits,
                "strong_matched_terms": strong_hits,
                "deliverables": list(spec["deliverables"]),
            }
        )
    matches.sort(key=lambda row: (int(row["score"]), row["label"]), reverse=True)
    return matches


def capability_fit(text: str, *, title: str | None = None) -> dict[str, Any]:
    """Classify whether Nova has a concrete service capability for the listing."""
    blob = _normalize(text)
    human_only = [p for p in _HUMAN_ONLY_PATTERNS if p in blob]
    regulated = [p for p in _REGULATED_PATTERNS if p in blob]
    matches = capability_matches(blob, title=title)

    if human_only:
        return {
            "fit": False,
            "score": 0,
            "capabilities": matches,
            "blockers": ["human_only_work"],
            "reason": "Work requires a human to personally perform the task.",
        }
    if regulated:
        return {
            "fit": False,
            "score": 0,
            "capabilities": matches,
            "blockers": ["regulated_or_credentialed_work"],
            "reason": "Work requires regulated or credentialed professional activity.",
        }
    if title and _SPECIALIST_TITLE_RE.search(_normalize(title)) and not matches:
        return {
            "fit": False,
            "score": 0,
            "capabilities": [],
            "blockers": ["title_role_family_mismatch"],
            "reason": "Title/role family is a specialist IC role outside matched Nova service capabilities.",
        }
    if not matches:
        return {
            "fit": False,
            "score": 20,
            "capabilities": [],
            "blockers": [],
            "reason": "No concrete Nova service capability matched the requested deliverables.",
        }

    top = matches[0]
    return {
        "fit": True,
        "score": int(top["score"]),
        "capabilities": matches,
        "blockers": [],
        "reason": f"Matched Nova capability: {top['label']}.",
    }


def capability_search_queries() -> list[str]:
    """Return deduplicated capability-first search phrases for discovery."""
    from app.core.nova.work_revenue.capability_first_discovery import capability_first_search_queries

    # Prefer capability-first nationwide remote/digital queries. Fall back to catalog
    # phrases only if the planner returns nothing (should not happen in normal use).
    planned = capability_first_search_queries()
    if planned:
        return planned
    seen: set[str] = set()
    queries: list[str] = []
    for spec in CAPABILITIES.values():
        for query in spec["search_queries"]:
            q = str(query).strip()
            if q and q.lower() not in seen:
                seen.add(q.lower())
                queries.append(q)
    return queries


def capability_catalog() -> list[dict[str, Any]]:
    """Public read-only catalog for owner UI/API use."""
    rows: list[dict[str, Any]] = []
    for key, spec in CAPABILITIES.items():
        rows.append(
            {
                "capability_id": key,
                "label": spec["label"],
                "deliverables": list(spec["deliverables"]),
                "search_queries": list(spec["search_queries"]),
            }
        )
    return rows
