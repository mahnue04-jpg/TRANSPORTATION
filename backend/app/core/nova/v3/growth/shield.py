"""Nova Shield — fail-closed growth safety layer. Every action is explained."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.growth.catalog import (
    FABRICATION_TOKENS,
    FAKE_URGENCY,
    LEGAL_TOKENS,
    PROHIBITED_SENSITIVE,
    REGULATED_INDUSTRIES,
    UNAVAILABLE_FEATURES,
)
from app.core.nova.v3.growth.models import Lead

RATE_LIMIT_MAX = 4


def evaluate(
    *,
    action: str,
    lead: Lead | None,
    content: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = extra or {}
    flags = live_flags()
    reasons: list[str] = []
    state = "ALLOW_SYNTHETIC"
    text = (content or "").lower()
    if flags.get("REAL_OUTREACH_SEND") or flags.get("REAL_EMAIL_SEND") or flags.get("CLIENT_CONTACT_ENABLED"):
        return _out("BLOCK", ["Live outreach flags are off. Real contact is forbidden."], action)
    if extra.get("live"):
        return _out("BLOCK", ["Live transport requested. Phase 3 is mock only."], action)
    if lead is None:
        reasons.append("No lead bound to this action.")
        return _out("BLOCK", reasons, action)
    if lead.do_not_contact or lead.opted_out or lead.status == "DO_NOT_CONTACT":
        return _out("DO_NOT_CONTACT", ["Do-not-contact or opt-out is set. Outreach is suppressed."], action)
    if "opt-out" in [item.lower() for item in lead.consent_restrictions] or "do not contact" in [
        item.lower() for item in lead.consent_restrictions
    ]:
        return _out("DO_NOT_CONTACT", ["Consent restrictions forbid contact."], action)
    if extra.get("wrong_recipient"):
        return _out("BLOCK", ["Recipient does not match the bound lead."], action)
    if lead.invalid_contact and action in {"mock_send", "sequence_step"}:
        return _out("BLOCK", ["Invalid contact cannot be used."], action)
    if action.endswith("send") and lead.email_placeholder and "@" not in (lead.email_placeholder or ""):
        return _out("BLOCK", ["Invalid contact cannot be used."], action)
    if any(token in text for token in PROHIBITED_SENSITIVE) or any(
        token in " ".join(lead.consent_restrictions).lower() for token in PROHIBITED_SENSITIVE
    ):
        return _out("PRIVACY_REVIEW_REQUIRED", ["Prohibited sensitive targeting or data exposure."], action)
    if any(token in text for token in LEGAL_TOKENS) or extra.get("legal_commitment"):
        return _out("LEGAL_REVIEW_REQUIRED", ["Legal commitment language is not allowed without owner/legal review."], action)
    if any(token in text for token in FABRICATION_TOKENS) or extra.get("fabricated"):
        return _out("BLOCK", ["Deceptive or fabricated claim refused."], action)
    if any(token in text for token in UNAVAILABLE_FEATURES):
        return _out("BLOCK", ["Unsupported or unavailable capability claimed."], action)
    if extra.get("unauthorized_price") or extra.get("unauthorized_discount"):
        return _out("OWNER_APPROVAL_REQUIRED", ["Unauthorized pricing or discount requires owner approval."], action)
    if extra.get("captcha") or extra.get("login_required"):
        return _out("HUMAN_ACTION_REQUIRED", ["CAPTCHA or login restrictions cannot be bypassed."], action)
    if extra.get("third_party_terms"):
        return _out("HUMAN_ACTION_REQUIRED", ["Third-party terms require a human."], action)
    if lead.outreach_count >= RATE_LIMIT_MAX and action in {"mock_send", "sequence_step", "prepare_outreach"}:
        return _out("RATE_LIMIT", ["Outreach frequency limit reached for this lead."], action)
    if extra.get("duplicate_outreach"):
        return _out("RATE_LIMIT", ["Duplicate outreach to the same lead/content is blocked."], action)
    if extra.get("spam_risk") or text.count("!!!") >= 2:
        return _out("BLOCK", ["Spam-risk pattern detected."], action)
    if lead.regulated or lead.industry.lower() in REGULATED_INDUSTRIES:
        if action in {"mock_send", "prepare_outreach", "custom_quote"}:
            reasons.append("Regulated-sector outreach requires owner approval.")
            state = "OWNER_APPROVAL_REQUIRED"
    if lead.high_value and action in {"mock_send", "prepare_quote", "custom_quote"}:
        reasons.append("High-value opportunity requires owner approval.")
        state = "OWNER_APPROVAL_REQUIRED"
    if extra.get("custom_pricing") or extra.get("major_proposal") or extra.get("non_standard_promise"):
        reasons.append("Non-standard commercial term requires owner approval.")
        state = "OWNER_APPROVAL_REQUIRED"
    if extra.get("client_legal_terms"):
        return _out("LEGAL_REVIEW_REQUIRED", ["Client legal terms require review."], action)
    if not reasons:
        reasons.append("Synthetic action is allowed. No live send.")
    return _out(state, reasons, action)


def _out(state: str, reasons: list[str], action: str) -> dict[str, Any]:
    return {
        "state": state,
        "reasons": reasons,
        "explain": " ".join(reasons),
        "action": action,
        "allowed": state == "ALLOW_SYNTHETIC",
        "needs_owner": state == "OWNER_APPROVAL_REQUIRED",
        "blocked": state in {"BLOCK", "DO_NOT_CONTACT", "RATE_LIMIT"},
    }
