"""Draft application materials from verified facts only. Untrusted opportunity text is quoted, never trusted."""
from __future__ import annotations

import re
from typing import Any

from app.core.nova.work_revenue.capability_registry import list_capabilities
from app.core.nova.work_revenue.verified_profile import (
    OWNER_INPUT_REQUIRED,
    UNKNOWN,
    profile_snapshot,
)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
MAX_UNTRUSTED = 2500


def sanitize_untrusted(text: str | None) -> str:
    cleaned = _CONTROL_RE.sub("", str(text or "")).strip()
    if len(cleaned) > MAX_UNTRUSTED:
        cleaned = cleaned[:MAX_UNTRUSTED] + "…"
    return cleaned


def _quote_untrusted(label: str, value: str | None) -> str:
    body = sanitize_untrusted(value) or UNKNOWN
    return f"{label}: [UNTRUSTED SOURCE TEXT]\n{body}"


def _unknown_lines() -> str:
    return "\n".join(
        [
            f"Degrees: {OWNER_INPUT_REQUIRED}",
            f"Licenses: {OWNER_INPUT_REQUIRED}",
            f"Certifications: {OWNER_INPUT_REQUIRED}",
            f"Employment history: {OWNER_INPUT_REQUIRED}",
            f"References: {OWNER_INPUT_REQUIRED}",
            f"Years of experience: {OWNER_INPUT_REQUIRED}",
            f"Client history: {OWNER_INPUT_REQUIRED}",
            f"Revenue: {OWNER_INPUT_REQUIRED}",
        ]
    )


def _party_block(applicant_party: str) -> str:
    profile = profile_snapshot(applicant_party=applicant_party)
    party = profile["applicant_party"]
    return (
        f"Proposed contracting party: {party['label']}\n"
        f"Legal confirmation: {party['status']}\n"
        f"{party['notes']}\n"
        f"{profile['verified']['nova_identity']}"
    )


def _capability_lines() -> str:
    lines = []
    for item in list_capabilities():
        if item["availability"] in {"AVAILABLE", "AVAILABLE_WITH_OWNER_REVIEW"}:
            lines.append(f"- {item['label']} ({item['availability']}): {item['evidence']}")
    return "\n".join(lines)


def _forbidden_claims() -> str:
    return (
        "This draft does not claim degrees, licenses, certifications, employment history, "
        "references, years of experience, client results, or revenue. "
        f"Missing facts are marked {OWNER_INPUT_REQUIRED}."
    )


def generate_drafts(opportunity: dict[str, Any], *, applicant_party: str = "AMICOR") -> list[dict[str, str]]:
    title = sanitize_untrusted(opportunity.get("opportunity_title")) or UNKNOWN
    company = sanitize_untrusted(opportunity.get("company_name")) or UNKNOWN
    untrusted_desc = _quote_untrusted("Opportunity description", opportunity.get("description"))
    party = _party_block(applicant_party)
    caps = _capability_lines()
    unknown = _unknown_lines()
    forbidden = _forbidden_claims()
    identity = profile_snapshot(applicant_party=applicant_party)["verified"]["nova_identity"]

    drafts = [
        {
            "kind": "capability_statement",
            "title": "AMICOR capability statement (DRAFT)",
            "body": (
                f"DRAFT — not approved for external use.\n\n{party}\n\n"
                f"Products present in this system: "
                f"{', '.join(profile_snapshot()['verified']['products_in_repository'])}.\n\n"
                f"Authorized support kinds:\n{caps}\n\n{unknown}\n\n{forbidden}"
            ),
        },
        {
            "kind": "resume",
            "title": f"Resume draft for {title}",
            "body": (
                f"DRAFT resume. {identity}\n\n"
                f"Applicant party: {applicant_party}\n"
                f"{OWNER_INPUT_REQUIRED} for legal name, contact details, and any human work history.\n\n"
                f"Objective: Support authorized digital work related to {title} at {company}, "
                f"with owner review of all external communications.\n\n"
                f"{unknown}\n\n"
                f"Do not list fabricated employers, degrees, or dates.\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "cover_letter",
            "title": f"Cover letter draft for {title}",
            "body": (
                f"DRAFT cover letter — owner must approve before any future submission.\n\n"
                f"{party}\n\n"
                f"Regarding: {title} at {company}.\n\n"
                f"Nova can prepare drafts for authorized digital tasks (email, documents, "
                f"summaries, CRM organization) under owner authorization. Nova is not a human "
                f"applicant and will not pretend to be one.\n\n"
                f"{OWNER_INPUT_REQUIRED}: owner-specific motivation, availability, and rate.\n\n"
                f"{forbidden}\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "proposal",
            "title": f"Proposal outline for {title}",
            "body": (
                f"DRAFT proposal outline.\n\n{party}\n\n"
                f"Scope (from untrusted posting; owner must confirm):\n{untrusted_desc}\n\n"
                f"Proposed Nova-assisted work: drafting, organization, and summarization with "
                f"human review. Pricing: {OWNER_INPUT_REQUIRED}. Timeline: {OWNER_INPUT_REQUIRED}.\n\n"
                f"{forbidden}"
            ),
        },
        {
            "kind": "application_responses",
            "title": "Application response drafts",
            "body": (
                f"DRAFT application responses.\n\n"
                f"Q: Are you a human employee of the client?\n"
                f"A: No. Nova is an AI system/tool under AMICOR/owner authorization.\n\n"
                f"Q: Years of experience?\nA: {OWNER_INPUT_REQUIRED}\n\n"
                f"Q: Licenses and certifications?\nA: {OWNER_INPUT_REQUIRED} — none are stored as verified.\n\n"
                f"Q: Client references?\nA: {OWNER_INPUT_REQUIRED}\n\n"
                f"{untrusted_desc}"
            ),
        },
        {
            "kind": "work_sample_outline",
            "title": "Work-sample outline (DRAFT)",
            "body": (
                f"DRAFT work-sample outline for {title}.\n\n"
                f"1. Restate the requested work using only the untrusted posting, labeled as such.\n"
                f"2. Map tasks to authorized Nova capabilities (drafting, organization, summarization).\n"
                f"3. Mark human-required steps {OWNER_INPUT_REQUIRED}.\n"
                f"4. Do not invent prior client deliverables.\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "follow_up_message",
            "title": "Follow-up message (DRAFT)",
            "body": (
                f"DRAFT follow-up. Nothing was sent.\n\n"
                f"Subject: {OWNER_INPUT_REQUIRED} — follow-up regarding {title}\n\n"
                f"Thank you for considering {OWNER_INPUT_REQUIRED} for {title}. "
                f"We can share owner-approved materials on request. Nova did not submit an application.\n\n"
                f"{identity}"
            ),
        },
    ]
    for item in drafts:
        item["status"] = "DRAFT"
        item["owner_input_required"] = OWNER_INPUT_REQUIRED in item["body"]
    return drafts
