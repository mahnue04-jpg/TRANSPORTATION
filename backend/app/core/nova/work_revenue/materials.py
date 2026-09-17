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
        {
            "kind": "statement_of_work",
            "title": f"Statement of work outline for {title}",
            "body": (
                f"DRAFT statement of work. Not a signed contract.\n\n{party}\n\n"
                f"Period of performance: {OWNER_INPUT_REQUIRED}\n"
                f"Deliverables: {OWNER_INPUT_REQUIRED}\n"
                f"Pricing: {OWNER_INPUT_REQUIRED}\n"
                f"Nova will not accept this SOW. Owner signature is required later.\n\n"
                f"{forbidden}\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "bid_response",
            "title": f"Bid response draft for {title}",
            "body": (
                f"DRAFT bid response. No price is committed.\n\n"
                f"Bid amount: {OWNER_INPUT_REQUIRED}\n"
                f"Availability: {OWNER_INPUT_REQUIRED}\n"
                f"{identity}\n\n{forbidden}\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "questionnaire_response",
            "title": "Questionnaire response draft",
            "body": (
                f"DRAFT questionnaire responses.\n\n"
                f"Legal business name: {OWNER_INPUT_REQUIRED}\n"
                f"Owner/contact: {OWNER_INPUT_REQUIRED}\n"
                f"Insurance: {OWNER_INPUT_REQUIRED}\n"
                f"Government registrations: {OWNER_INPUT_REQUIRED}\n"
                f"References: {OWNER_INPUT_REQUIRED}\n\n{forbidden}"
            ),
        },
        {
            "kind": "clarification_questions",
            "title": "Clarification questions (DRAFT)",
            "body": (
                f"DRAFT questions for the owner to send later if appropriate. Nothing was sent.\n\n"
                f"Unknown facts remain {OWNER_INPUT_REQUIRED}.\n"
                f"1. Confirm whether physical presence is required.\n"
                f"2. Confirm whether a professional license is required.\n"
                f"3. Confirm compensation and contract party.\n"
                f"4. Confirm whether identity verification or CAPTCHA will be required.\n\n"
                f"{untrusted_desc}"
            ),
        },
        {
            "kind": "interview_prep",
            "title": "Interview preparation notes (DRAFT)",
            "body": (
                f"DRAFT interview notes. Nova cannot attend a live interview.\n\n"
                f"Identity disclosure: {identity}\n"
                f"Talking points from verified capabilities only:\n{caps}\n\n"
                f"Prior clients, revenue, and availability: {OWNER_INPUT_REQUIRED}.\n"
                f"Do not invent prior clients or revenue.\n"
                f"Owner must attend any live interview.\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "owner_action_checklist",
            "title": "Owner action checklist",
            "body": (
                f"OWNER ACTION CHECKLIST for {title} at {company}.\n\n"
                f"- Confirm legal contracting party: {OWNER_INPUT_REQUIRED}\n"
                f"- Confirm contact details: {OWNER_INPUT_REQUIRED}\n"
                f"- Confirm certifications if requested: {OWNER_INPUT_REQUIRED}\n"
                f"- Complete CAPTCHA / identity / signature steps in person if required\n"
                f"- Do not authorize Nova to submit, sign, or send banking/tax data\n"
            ),
        },
        {
            "kind": "owner_input_checklist",
            "title": "Owner input checklist",
            "body": (
                f"DRAFT — OWNER REVIEW REQUIRED. {identity}\n\n"
                f"COMPANY EXPERIENCE REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"PRICING REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"REFERENCE REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"LICENSE INFORMATION REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"INSURANCE INFORMATION REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"AVAILABILITY REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"DEADLINE CONFIRMATION REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"OWNER SIGNATURE REQUIRED: {OWNER_INPUT_REQUIRED}\n"
                f"Do not invent any of these facts.\n"
            ),
        },
        {
            "kind": "client_discovery_questions",
            "title": "Client discovery questions (DRAFT)",
            "body": (
                f"DRAFT — OWNER REVIEW REQUIRED. Nothing was sent to {company}.\n\n"
                f"1. What outcome does the client actually need? {OWNER_INPUT_REQUIRED}\n"
                f"2. What is in-scope versus out-of-scope? {OWNER_INPUT_REQUIRED}\n"
                f"3. What is the expected start date? {OWNER_INPUT_REQUIRED}\n"
                f"4. What is the payment structure? {OWNER_INPUT_REQUIRED}\n\n"
                f"{untrusted_desc}"
            ),
        },
        {
            "kind": "work_plan",
            "title": f"Internal work plan for {title}",
            "body": (
                f"DRAFT — OWNER REVIEW REQUIRED. Internal tracking only. Not a contract.\n\n{party}\n\n"
                f"Nova tasks: draft, organize, and summarize with owner review.\n"
                f"Owner tasks: approve, confirm facts, sign, and any live human steps.\n"
                f"Unsupported: physical presence, licensed practice, payments, external send.\n"
                f"Status of this plan: NOT STARTED until the owner creates an internal engagement.\n\n"
                f"{forbidden}"
            ),
        },
        {
            "kind": "weekly_report_template",
            "title": "Weekly client report template (DRAFT)",
            "body": (
                f"DRAFT — OWNER REVIEW REQUIRED. Do not send this to a client yet.\n\n"
                f"Client: {company}\nPeriod: {OWNER_INPUT_REQUIRED}\n"
                f"Work completed: {OWNER_INPUT_REQUIRED}\n"
                f"Blockers: {OWNER_INPUT_REQUIRED}\n"
                f"Next week: {OWNER_INPUT_REQUIRED}\n"
                f"Nova did not contact the client.\n\n{forbidden}"
            ),
        },
        {
            "kind": "invoice_support_summary",
            "title": "Invoice support summary (DRAFT)",
            "body": (
                f"DRAFT — OWNER REVIEW REQUIRED. This is not an invoice and was not sent.\n\n"
                f"Amount: {OWNER_INPUT_REQUIRED}\n"
                f"Period: {OWNER_INPUT_REQUIRED}\n"
                f"Owner-confirmed received: no unless the owner later confirms it.\n"
                f"Nova will not create a Stripe invoice, charge, or payout.\n\n{forbidden}"
            ),
        },
        {
            "kind": "quote_response",
            "title": f"Quote response placeholder for {title}",
            "body": (
                f"DRAFT quote response. Pricing is {OWNER_INPUT_REQUIRED}. "
                f"Nova will not agree to a rate.\n\n{party}\n\n{forbidden}\n\n{untrusted_desc}"
            ),
        },
        {
            "kind": "client_introduction",
            "title": "Client introduction (DRAFT — not sent)",
            "body": (
                f"DRAFT introduction. Nothing was sent.\n\n{identity}\n\n"
                f"Recipient: {OWNER_INPUT_REQUIRED}\nRegarding: {title} at {company}.\n"
                f"{forbidden}"
            ),
        },
        {
            "kind": "project_summary",
            "title": f"Project summary draft for {title}",
            "body": (
                f"DRAFT project summary from untrusted source text only.\n\n{untrusted_desc}\n\n"
                f"Verified capabilities:\n{caps}\n\n{unknown}"
            ),
        },
        {
            "kind": "executive_summary",
            "title": f"Executive summary draft for {title}",
            "body": (
                f"DRAFT executive summary. Do not treat this as a bid.\n\n{party}\n"
                f"Opportunity: {title} / {company}.\nPricing: {OWNER_INPUT_REQUIRED}.\n"
                f"Experience: {OWNER_INPUT_REQUIRED}.\n\n{forbidden}"
            ),
        },
        {
            "kind": "qualifications_narrative",
            "title": "Qualifications narrative (DRAFT)",
            "body": (
                f"DRAFT qualifications narrative.\n\n{identity}\n{caps}\n\n{unknown}\n\n"
                f"Do not invent certifications or licenses.\n{forbidden}"
            ),
        },
        {
            "kind": "experience_narrative",
            "title": "Experience narrative (DRAFT)",
            "body": (
                f"DRAFT experience narrative.\n\nPrior clients: {OWNER_INPUT_REQUIRED}.\n"
                f"Years of experience: {OWNER_INPUT_REQUIRED}.\n"
                f"Do not invent employment history.\n\n{forbidden}"
            ),
        },
        {
            "kind": "pricing_placeholder",
            "title": "Pricing placeholder (DRAFT)",
            "body": (
                f"DRAFT pricing placeholder. No price is offered.\n\n"
                f"Rate: {OWNER_INPUT_REQUIRED}\n"
                f"Nova cannot agree to pricing.\n\n{forbidden}"
            ),
        },
        {
            "kind": "scope_of_work",
            "title": f"Scope of work draft for {title}",
            "body": (
                f"DRAFT scope of work. Not a contract.\n\n{untrusted_desc}\n\n"
                f"Nova-assisted tasks require owner review. Owner signature: {OWNER_INPUT_REQUIRED}.\n"
                f"{forbidden}"
            ),
        },
    ]
    for item in drafts:
        item["status"] = "DRAFT"
        item["owner_input_required"] = OWNER_INPUT_REQUIRED in item["body"]
    return drafts


def missing_owner_facts(opportunity: dict[str, Any]) -> list[str]:
    facts = [
        "legal_business_name",
        "owner_contact_info",
        "verified_experience",
    ]
    text = " ".join(
        [
            str(opportunity.get("description") or ""),
            str(opportunity.get("requirements") or ""),
            " ".join(opportunity.get("credentials_required") or []),
        ]
    ).lower()
    if opportunity.get("credentials_required") or "certif" in text or "license" in text:
        facts.append("required_certification")
    if "portfolio" in text or "work sample" in text:
        facts.append("portfolio_or_work_sample")
    if "attach" in text or "upload" in text:
        facts.append("requested_attachment")
    if "insur" in text:
        facts.append("insurance_information")
    if "reference" in text:
        facts.append("reference")
    if "pric" in text or "rate" in text or "bid" in text:
        facts.append("pricing")
    if "availab" in text:
        facts.append("availability")
    if "deadline" in text or "due date" in text:
        facts.append("deadline_confirmation")
    if "sign" in text or "contract" in text:
        facts.append("owner_signature")
    return list(dict.fromkeys(facts))


def owner_input_checklist(opportunity: dict[str, Any]) -> list[dict[str, str]]:
    labels = {
        "legal_business_name": "COMPANY LEGAL NAME REQUIRED",
        "owner_contact_info": "OWNER CONTACT REQUIRED",
        "verified_experience": "COMPANY EXPERIENCE REQUIRED",
        "required_certification": "LICENSE INFORMATION REQUIRED",
        "portfolio_or_work_sample": "WORK SAMPLE REQUIRED",
        "requested_attachment": "REQUESTED ATTACHMENT REQUIRED",
        "insurance_information": "INSURANCE INFORMATION REQUIRED",
        "reference": "REFERENCE REQUIRED",
        "pricing": "PRICING REQUIRED",
        "availability": "AVAILABILITY REQUIRED",
        "deadline_confirmation": "DEADLINE CONFIRMATION REQUIRED",
        "owner_signature": "OWNER SIGNATURE REQUIRED",
    }
    return [
        {"code": code, "label": labels.get(code, code.replace("_", " ").upper() + " REQUIRED"), "marker": OWNER_INPUT_REQUIRED}
        for code in missing_owner_facts(opportunity)
    ]
