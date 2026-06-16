"""Post-routing response engine for structured business-ready replies.

This module is additive and guarded:
- It does not change routing decisions.
- It formats response text after routing based on inferred response mode.
- It falls back to the original response if formatting cannot be applied.
"""

from __future__ import annotations

import re
from typing import Any


_BUSINESS_PLAN_TERMS = (
    "business plan",
    "startup plan",
    "start a business",
    "start my business",
    "startup checklist",
)
_PROPOSAL_TERMS = ("proposal", "scope of work", "client proposal", "project proposal")
_INVOICE_TERMS = ("invoice", "invoicing", "payment terms", "billing")
_MARKETING_TERMS = ("marketing", "campaign", "positioning", "advertise", "promotion")
_RESEARCH_TERMS = ("research", "analyze", "investigate", "find out")
_SUMMARIZE_TERMS = ("summarize", "summary", "summarise", "brief")
_EMAIL_TERMS = ("email", "draft email", "compose", "subject line")
_MEETING_TERMS = ("meeting notes", "meeting minutes", "minutes", "meeting summary")


def _safe_text(value: Any) -> str:
    return str(value or "").strip()


def _sanitize_internal_labels(text: str) -> str:
    sanitized = text or ""
    sanitized = re.sub(r"\[MEMORY_CONTEXT\].*?\[/MEMORY_CONTEXT\]", "", sanitized, flags=re.IGNORECASE | re.DOTALL)
    sanitized = re.sub(r"\[(?:SYSTEM|INTERNAL|ROUTE|TOOL|PROVIDER)_[A-Z_]+\]", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b(?:short_term_memory|long_term_memory|user_id|memory_context)\b", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b(?:schema|internal labels?|provider diagnostics?)\b", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip()


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _looks_like_business_plan_prompt(text: str) -> bool:
    if _contains_any(text, _BUSINESS_PLAN_TERMS):
        return True
    return bool(
        re.search(r"\bstart\s+(?:a\s+)?(?:new\s+)?[a-z\s]{0,40}\bbusiness\b", text)
        or re.search(r"\bbusiness\s+plan\b", text)
        or re.search(r"\bstartup\b", text)
    )


def _infer_mode(message: str, tool: str, intent: str | None) -> str:
    lower = (message or "").lower()
    intent_lower = (intent or "").lower()

    if _contains_any(lower, _MEETING_TERMS):
        return "meeting_notes"

    if tool == "email" or _contains_any(lower, _EMAIL_TERMS):
        return "draft_email"

    if tool == "search" or intent_lower in ("research", "summarize"):
        if _contains_any(lower, _SUMMARIZE_TERMS) or intent_lower == "summarize":
            return "summarize"
        return "research"

    if tool == "business":
        if _contains_any(lower, _PROPOSAL_TERMS):
            return "proposal"
        if _contains_any(lower, _INVOICE_TERMS):
            return "invoice"
        if _contains_any(lower, _MARKETING_TERMS):
            return "marketing"
        if _looks_like_business_plan_prompt(lower):
            return "business_plan"

    return "general_assistant"


def _memory_profile(preferences: dict[str, Any] | None, memory_summary: str | None) -> dict[str, str]:
    prefs = preferences or {}
    profile = {
        "name": _safe_text(prefs.get("preferred_name") or prefs.get("name")),
        "industry": _safe_text(prefs.get("industry")),
        "location": _safe_text(prefs.get("location")),
        "role": _safe_text(prefs.get("role")),
        "summary": _safe_text(memory_summary),
    }
    return profile


def _is_vague_business_prompt(message: str, profile: dict[str, str]) -> bool:
    lower = (message or "").lower()
    has_industry = bool(profile.get("industry")) or bool(re.search(r"\b(trucking|transport|salon|construction|landscaping|retail|consulting|agency|food|manufacturing)\b", lower))
    has_location = bool(profile.get("location")) or bool(re.search(r"\b(in|at|from)\s+[a-z][a-z\s]{2,}\b", lower))
    has_budget = bool(re.search(r"(?:\$\s?\d[\d,]*(?:\.\d+)?)|(?:\b\d+[\d,]*\s?(?:k|m)\b)|\bbudget\b", lower))
    return not (has_industry and has_location and has_budget)


def _greeting(profile: dict[str, str]) -> str:
    name = profile.get("name") or ""
    return f"{name}, " if name else ""


def _extract_points(text: str, max_points: int = 4) -> list[str]:
    if not text:
        return []
    sentences = [s.strip(" -•\n\t") for s in re.split(r"[\n\.]+", text) if s.strip()]
    points: list[str] = []
    for sentence in sentences:
        if len(sentence) < 10:
            continue
        points.append(sentence)
        if len(points) >= max_points:
            break
    return points


def _format_business_plan(message: str, profile: dict[str, str]) -> str:
    industry_hint = profile.get("industry") or "your chosen industry"
    location_hint = profile.get("location") or "your target city/state"
    header = _greeting(profile) + "here is a practical starter business plan:"
    if _is_vague_business_prompt(message, profile):
        return "\n".join(
            [
                "## Business Plan Starter",
                header,
                "",
                "### 1) Business Idea Summary",
                f"- Build a focused offer in {industry_hint} that solves one urgent customer problem first.",
                "",
                "### 2) Target Customer",
                "- Define one primary customer profile before expanding.",
                "",
                "### 3) Services/Products",
                "- Start with 1-2 core services/products you can deliver reliably.",
                "",
                "### 4) Pricing/Revenue Model",
                "- Set a baseline package, premium package, and add-on upsell.",
                "",
                "### 5) Startup Checklist",
                "- Register entity, open business account, define offer, and create first sales script.",
                "",
                "### 6) Marketing Approach",
                "- Use one acquisition channel first (outbound, local partnerships, or social).",
                "",
                "### 7) Operations Plan",
                "- Define intake, delivery, invoicing, and weekly KPI review.",
                "",
                "### 8) Next 3 Actions",
                "- Validate demand with 10 customer conversations.",
                "- Publish one clear offer page and outreach message.",
                "- Close first pilot customer and capture testimonial.",
                "",
                "### Quick Clarifying Questions",
                "1. What industry are you targeting?",
                f"2. Which city/state are you operating in? (current: {location_hint})",
                "3. What starting budget range are you working with?",
            ]
        )

    return "\n".join(
        [
            "## Business Plan",
            header,
            "",
            "### 1) Business Idea Summary",
            f"- Position around a clear niche in {industry_hint} and solve a measurable pain point.",
            "",
            "### 2) Target Customer",
            "- Primary ICP: customers who need fast, reliable outcomes and clear pricing.",
            "",
            "### 3) Services/Products",
            "- Core offer, premium offer, and one recurring retainer/maintenance option.",
            "",
            "### 4) Pricing/Revenue Model",
            "- Use value-based pricing with minimum margin guardrails and monthly revenue targets.",
            "",
            "### 5) Startup Checklist",
            "- Entity setup, compliance, payments/invoicing flow, sales assets, and onboarding SOP.",
            "",
            "### 6) Marketing Approach",
            "- Build pipeline via referrals, outbound messaging, and proof-based social content.",
            "",
            "### 7) Operations Plan",
            "- Weekly cadence: lead tracking, fulfillment capacity, cashflow, and quality checkpoints.",
            "",
            "### 8) Next 3 Actions",
            "- Finalize offer and pricing sheet this week.",
            "- Launch first campaign with one primary channel.",
            "- Set 30-day KPI targets for leads, close rate, and revenue.",
        ]
    )


def _format_proposal(message: str, profile: dict[str, str]) -> str:
    intro = _greeting(profile) + "copy this proposal draft and replace placeholders:"
    return "\n".join(
        [
            "## Client Proposal Draft",
            intro,
            "",
            "### 1) Proposal Title",
            "- [Project Name] Proposal for [Client Name]",
            "",
            "### 2) Client Problem",
            "- [Client Name] is currently facing [specific challenge] impacting [cost, speed, or quality].",
            "",
            "### 3) Proposed Solution",
            "- We will deliver [solution] to achieve [target outcome].",
            "",
            "### 4) Scope of Work",
            "- Discovery and requirements",
            "- Implementation and delivery",
            "- QA, handoff, and support window",
            "",
            "### 5) Timeline",
            "- Week 1: Planning",
            "- Weeks 2-3: Execution",
            "- Week 4: Review and final delivery",
            "",
            "### 6) Pricing",
            "- Project Fee: [Insert Price]",
            "- Optional Add-ons: [Insert Add-ons]",
            "",
            "### 7) Next Steps",
            "- Confirm scope and timeline.",
            "- Approve proposal and sign agreement.",
            "- Schedule kickoff meeting.",
            "",
            "### 8) Professional Closing",
            "Thank you for the opportunity to support your team. We are ready to begin immediately upon approval.",
        ]
    )


def _format_invoice(profile: dict[str, str]) -> str:
    intro = _greeting(profile) + "here is a client-ready invoice package:"
    return "\n".join(
        [
            "## Invoice Draft",
            intro,
            "",
            "### 1) Invoice Summary",
            "- Invoice #: [INV-0001]",
            "- Client: [Client Name]",
            "- Service Period: [Start Date] - [End Date]",
            "",
            "### 2) Client-Ready Email",
            "Subject: Invoice [INV-0001] - [Your Company Name]",
            "Hi [Client Name],",
            "Please find your invoice for [services delivered]. Let me know if you need any additional documentation.",
            "",
            "### 3) Line Item Placeholders",
            "- [Service/Deliverable 1] - Qty [ ] - Rate [ ] - Amount [ ]",
            "- [Service/Deliverable 2] - Qty [ ] - Rate [ ] - Amount [ ]",
            "- Subtotal: [ ]",
            "- Tax (if applicable): [ ]",
            "- Total Due: [ ]",
            "",
            "### 4) Payment Terms",
            "- Payment terms: Net [15/30]",
            "- Payment method: [Bank transfer / ACH / other]",
            "",
            "### 5) Due Date",
            "- Due date: [Insert Due Date]",
            "",
            "### 6) Polite Closing",
            "Thank you for your business and timely payment.",
            "",
            "Note: This is a draft template only and does not execute payment processing.",
        ]
    )


def _format_marketing(profile: dict[str, str]) -> str:
    industry = profile.get("industry") or "your business"
    intro = _greeting(profile) + "here is a focused marketing plan:"
    return "\n".join(
        [
            "## Marketing Plan",
            intro,
            "",
            "### 1) Positioning",
            f"- Position {industry} around one clear promise: fast, reliable, and outcome-driven delivery.",
            "",
            "### 2) Target Audience",
            "- Primary: decision-makers with immediate purchase intent.",
            "- Secondary: referral partners and repeat customers.",
            "",
            "### 3) Five Marketing Ideas",
            "- Publish 3 proof-based case posts per week.",
            "- Run a limited-time offer for first-time clients.",
            "- Build referral partnerships with adjacent service providers.",
            "- Send a short weekly value email with one CTA.",
            "- Capture testimonials and turn them into ad creatives.",
            "",
            "### 4) Channels",
            "- Organic social, local SEO/profile pages, outbound email/DM, and partner referrals.",
            "",
            "### 5) Example Social Post",
            "- \"We helped [client type] achieve [result] in [timeframe]. Want the same outcome? Reply with 'PLAN' and we will send the exact framework.\"",
            "",
            "### 6) Next Campaign Step",
            "- Launch one 14-day campaign with a single offer, single audience, and single CTA.",
        ]
    )


def _format_research(message: str, raw_response: str, sources: list[dict], status: str) -> str: # type: ignore
    if not sources:
        return "\n".join(
            [
                "## Research Update",
                "I could not retrieve live research results right now.",
                "Please try again in a moment, or refine your query to a narrower topic.",
            ]
        )

    points = _extract_points(raw_response, max_points=5)
    lines = [
        "## Research Brief",
        f"Query: {message.strip()}",
        "",
        "### Key Findings",
    ]
    if points:
        for item in points:
            lines.append(f"- {item}")
    else:
        lines.append("- Results were found; key points are available in the source links below.")

    lines.extend(["", "### Sources"])
    for src in sources[:4]: # type: ignore
        title = _safe_text(src.get("title") or src.get("label") or "Source") # type: ignore
        url = _safe_text(src.get("url")) # type: ignore
        lines.append(f"- {title}: {url}")

    return "\n".join(lines)


def _format_summarize(message: str, raw_response: str, sources: list[dict], status: str) -> str: # type: ignore
    if status != "success" and not sources:
        return "\n".join(
            [
                "## Summary",
                "I could not retrieve live source material to summarize right now.",
                "Please retry shortly and I will provide a concise summary.",
            ]
        )

    points = _extract_points(raw_response, max_points=4)
    lines = ["## Summary", f"Topic: {message.strip()}", "", "### Key Points"]
    if points:
        for item in points:
            lines.append(f"- {item}")
    else:
        lines.append("- Summary generated from available context.")

    if sources:
        lines.extend(["", "### Sources"])
        for src in sources[:3]: # type: ignore
            lines.append(f"- {_safe_text(src.get('title') or 'Source')}: {_safe_text(src.get('url'))}") # type: ignore

    return "\n".join(lines)


def _format_meeting_notes(message: str, profile: dict[str, str]) -> str:
    intro = _greeting(profile) + "here is a clean meeting-notes draft:"
    return "\n".join(
        [
            "## Meeting Notes",
            intro,
            "",
            "### Meeting Objective",
            f"- {message.strip() or '[Insert objective]'}",
            "",
            "### Key Decisions",
            "- [Decision 1]",
            "- [Decision 2]",
            "",
            "### Action Items",
            "- [Owner] - [Task] - [Due Date]",
            "- [Owner] - [Task] - [Due Date]",
            "",
            "### Open Questions",
            "- [Question needing follow-up]",
            "",
            "### Next Check-in",
            "- [Date/Time and agenda focus]",
        ]
    )


def _format_draft_email(raw_response: str, profile: dict[str, str]) -> str:
    intro = _greeting(profile) + "here is your draft email:"
    return "\n".join(["## Draft Email", intro, "", raw_response.strip()])


def apply_response_engine(
    *,
    message: str,
    result: dict[str, Any],
    preferences: dict[str, Any] | None,
    memory_summary: str | None,
) -> dict[str, Any]:
    """Format routed response into a structured assistant output.

    Returns the original result unchanged on any internal failure.
    """
    try:
        tool = _safe_text(result.get("tool") or "")
        raw_response = _safe_text(result.get("response") or "")
        status = _safe_text(result.get("status") or "success").lower()
        meta = result.get("meta") or {} # type: ignore
        intent = _safe_text(meta.get("intent") if isinstance(meta, dict) else "") # type: ignore
        sources = result.get("sources") if isinstance(result.get("sources"), list) else [] # type: ignore

        profile = _memory_profile(preferences, memory_summary)
        mode = _infer_mode(message, tool, intent)

        if mode == "business_plan":
            final_text = _format_business_plan(message, profile)
        elif mode == "proposal":
            final_text = _format_proposal(message, profile)
        elif mode == "invoice":
            final_text = _format_invoice(profile)
        elif mode == "marketing":
            final_text = _format_marketing(profile)
        elif mode == "research":
            final_text = _format_research(message, raw_response, sources, status) # type: ignore
        elif mode == "summarize":
            final_text = _format_summarize(message, raw_response, sources, status) # type: ignore
        elif mode == "draft_email":
            final_text = _format_draft_email(raw_response, profile)
        elif mode == "meeting_notes":
            final_text = _format_meeting_notes(message, profile)
        else:
            final_text = raw_response

        final_text = _sanitize_internal_labels(final_text)
        updated = dict(result)
        updated["response"] = final_text or raw_response
        updated_meta = dict(meta) if isinstance(meta, dict) else {} # type: ignore
        updated_meta["response_mode"] = mode
        updated["meta"] = updated_meta
        return updated
    except Exception:
        return result
