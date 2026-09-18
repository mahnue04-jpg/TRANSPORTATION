"""Outreach drafts and message quality gate. Mock send only. No fabricated facts."""
from __future__ import annotations

from typing import Any

from app.core.nova.v3.errors import V3Error
from app.core.nova.v3.flags import live_flags
from app.core.nova.v3.growth.catalog import (
    APPROVED_SERVICES,
    BRAND_NAMES,
    FABRICATION_TOKENS,
    FAKE_URGENCY,
    LEGAL_TOKENS,
)
from app.core.nova.v3.growth.models import Lead, OUTREACH_KINDS


def draft(lead: Lead, kind: str, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = extra or {}
    if kind not in OUTREACH_KINDS:
        raise V3Error("INVALID_OUTREACH_KIND", "unknown outreach kind", http_status=400)
    if live_flags().get("REAL_OUTREACH_SEND") or live_flags().get("REAL_EMAIL_SEND"):
        raise V3Error("LIVE_DISABLED", "real outreach is off")
    facts = _facts(lead)
    opener = (
        f"Hello {lead.contact_name or 'there'}, this is an internal AMICOR draft for "
        f"{lead.organization_name or 'your organization'}."
    )
    need = lead.business_need or "[OWNER INPUT REQUIRED: business need]"
    product = _product_name(lead.product_fit)
    bodies = {
        "introduction_email": (
            f"{opener} We noticed a possible fit with {product} around {need}. "
            "This is not a live email. Reply handling stays inside the owner lab. "
            "If useful, the owner can approve a demo conversation. "
            "If you do not want contact, say stop and we will mark do-not-contact."
        ),
        "follow_up_email": (
            f"{opener} Following up only on facts already recorded: {need} / {product}. "
            "No new claims. Owner review still required before any real send."
        ),
        "demo_invitation": (
            f"{opener} We can prepare a synthetic demo request for {product}. "
            "Timezone and owner availability still need confirmation. Not a calendar write."
        ),
        "trial_invitation": (
            f"{opener} A seven-day trial applies only if the approved catalog lists trial_days for {product}. "
            "Nova will not invent trial terms."
        ),
        "reactivation_message": (
            f"{opener} Checking whether {need} is still relevant. No fabricated urgency."
        ),
        "proposal_follow_up": (
            f"{opener} A proposal draft can use only approved catalog terms for {product}."
        ),
        "no_response_follow_up": (
            f"{opener} One more internal follow-up on {need}. If silent, the sequence can stop."
        ),
        "post_demo_follow_up": (
            f"{opener} After a demo, next steps stay owner-approved. No contract language."
        ),
        "value_reminder": (
            f"{opener} Reminder of recorded need ({need}) and product ({product}). No extra promises."
        ),
        "final_follow_up": (
            f"{opener} Final internal follow-up. We will not keep messaging if you prefer no contact."
        ),
    }
    body = bodies[kind]
    if extra.get("inject"):
        body += " " + str(extra["inject"])
    quality = evaluate_quality(lead, body, kind)
    return {"kind": kind, "body": body, "facts_used": facts, "quality": quality, "live": False}


def evaluate_quality(lead: Lead, body: str, kind: str) -> dict[str, Any]:
    text = body.lower()
    flags: list[str] = []
    if any(token in text for token in FABRICATION_TOKENS):
        flags.append("fabricated_relationship_or_claim")
    if any(token in text for token in FAKE_URGENCY):
        flags.append("fake_urgency")
    if any(token in text for token in LEGAL_TOKENS):
        flags.append("legal_commitment")
    if "stripe" in text or "sk_live" in text:
        flags.append("payment_claim")
    brand_ok = any(name.lower() in text for name in ("amicor", "nova", "delivery", "health"))
    if not brand_ok:
        flags.append("brand_missing")
    product_ok = lead.product_fit.lower() in text or _product_name(lead.product_fit).lower() in text
    if lead.product_fit and not product_ok:
        flags.append("wrong_product")
    if lead.organization_name and lead.organization_name.lower() not in text:
        flags.append("wrong_recipient_context")
    if "not a live" not in text and "internal" not in text and "draft" not in text:
        flags.append("missing_internal_label")
    if kind.endswith("email") and "do-not-contact" not in text and "stop" not in text:
        flags.append("opt_out_missing")
    if "call" not in text and "demo" not in text and "owner" not in text and "reply" not in text:
        flags.append("weak_cta")
    catalog = [row["name"].lower() for row in APPROVED_SERVICES.values()]
    invented_price = "$" in body and not any(str(int(row["price"])) in body for row in APPROVED_SERVICES.values() if row.get("price"))
    if invented_price and "$" in body:
        flags.append("misleading_pricing")
    passed = not any(
        item in flags
        for item in (
            "fabricated_relationship_or_claim",
            "fake_urgency",
            "legal_commitment",
            "payment_claim",
            "misleading_pricing",
        )
    )
    return {
        "passed": passed,
        "flags": flags,
        "factual_accuracy": "fabricated_relationship_or_claim" not in flags,
        "approved_naming": any(name.lower().split()[0] in text for name in BRAND_NAMES),
        "correct_product": "wrong_product" not in flags,
        "no_unsupported_claims": passed,
        "professional_tone": "!!!" not in body,
        "clear_cta": "weak_cta" not in flags,
        "correct_contact": "wrong_recipient_context" not in flags,
        "opt_out_handling": "opt_out_missing" not in flags,
        "owner_review_required": True,
        "catalog_names": catalog[:3],
    }


def require_quality(result: dict[str, Any]) -> dict[str, Any]:
    if not result.get("passed"):
        raise V3Error("MESSAGE_QUALITY_FAILED", "outreach failed quality gate", http_status=409)
    return result


def _product_name(product: str) -> str:
    mapping = {"delivery": "AMICOR Delivery", "nova": "AMICOR Nova", "health": "AMICOR Health"}
    return mapping.get((product or "").lower(), "AMICOR")


def _facts(lead: Lead) -> dict[str, Any]:
    return {
        "organization_name": lead.organization_name,
        "contact_name": lead.contact_name,
        "industry": lead.industry,
        "business_need": lead.business_need,
        "product_fit": lead.product_fit,
        "geography": lead.geography,
        "missing": [key for key, value in {
            "need": lead.business_need,
            "email": lead.email_placeholder,
            "value": lead.estimated_value,
        }.items() if not value],
    }
