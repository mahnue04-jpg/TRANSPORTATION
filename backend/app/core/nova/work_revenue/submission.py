"""Approval-gated application submission orchestration.

This module is the canonical last-mile gate for Nova Work applications.
It does not claim an external submission unless a provider-specific live
adapter returns a confirmed receipt. Providers without a verified adapter
fall back to a narrow HUMAN_ACTION_REQUIRED handoff while preserving the
owner's approval.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue import service
from app.core.nova.work_revenue.models import NovaWorkMaterial


@dataclass(frozen=True)
class SubmissionPolicy:
    provider_id: str
    tier: str
    submission_mode: str
    allowlisted: bool
    live_adapter_implemented: bool
    login_required: bool
    captcha_possible: bool
    identity_required: bool
    signature_required: bool
    terms_permit_automation: bool


def _provider_id(source: str | None, source_type: str | None, source_url: str | None) -> str:
    source_token = str(source or "").strip().lower()
    type_token = str(source_type or "").strip().lower()
    host = ""
    if source_url:
        try:
            host = (urlparse(source_url).hostname or "").lower()
        except ValueError:
            host = ""
    if "sam.gov" in host or source_token in {"sam.gov", "sam_gov"}:
        return "sam_gov"
    if "remotive" in host or source_token == "remotive":
        return "remotive"
    if "remoteok" in host or source_token in {"remoteok", "remote_ok"}:
        return "remoteok"
    if type_token == "approved_api":
        return source_token or "approved_api"
    if type_token in {"career_page", "freelance_marketplace", "rfp"}:
        return type_token
    return source_token or type_token or "unknown"


def policy_for_opportunity(opportunity: Any) -> SubmissionPolicy:
    provider = _provider_id(
        getattr(opportunity, "source", None),
        getattr(opportunity, "source_type", None),
        getattr(opportunity, "source_url", None),
    )
    # Current production providers are discovery-only. Keep them explicit so
    # an unknown source can never become automatable by accident.
    known_handoff = {"sam_gov", "remotive", "remoteok", "career_page", "freelance_marketplace", "rfp"}
    if provider in known_handoff:
        return SubmissionPolicy(
            provider_id=provider,
            tier="C",
            submission_mode="handoff",
            allowlisted=True,
            live_adapter_implemented=False,
            login_required=provider != "remotive",
            captcha_possible=provider in {"career_page", "freelance_marketplace"},
            identity_required=provider in {"sam_gov", "freelance_marketplace"},
            signature_required=provider == "sam_gov",
            terms_permit_automation=False,
        )
    return SubmissionPolicy(
        provider_id=provider,
        tier="C",
        submission_mode="blocked",
        allowlisted=False,
        live_adapter_implemented=False,
        login_required=True,
        captcha_possible=True,
        identity_required=True,
        signature_required=False,
        terms_permit_automation=False,
    )


def _materials_changed_after_approval(
    db: Session,
    *,
    application_id: str,
    organization_id: str,
    decided_at: Any,
) -> bool:
    if decided_at is None:
        return True
    rows = (
        db.query(NovaWorkMaterial)
        .filter(
            NovaWorkMaterial.application_id == application_id,
            NovaWorkMaterial.organization_id == organization_id,
        )
        .all()
    )
    for row in rows:
        updated = getattr(row, "updated_at", None)
        if updated is not None and updated > decided_at:
            return True
    return False


def submit_or_handoff(
    db: Session,
    application_id: str,
    *,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    application = service.get_application(
        db,
        application_id,
        organization_id=organization_id,
        user=user,
    )
    opportunity = service.get_opportunity(
        db,
        application.opportunity_id,
        organization_id=organization_id,
        user=user,
    )

    if application.externally_submitted:
        raise service.NovaWorkError("Application is already externally submitted", status_code=409)
    if application.approval_state != "APPROVED" or not application.approved_for_future_submission:
        raise service.NovaWorkError("Owner approval is required before submission", status_code=409)
    if _materials_changed_after_approval(
        db,
        application_id=application.application_id,
        organization_id=organization_id,
        decided_at=getattr(application, "decided_at", None),
    ):
        raise service.NovaWorkError(
            "Application materials changed after owner approval; return to owner review before submission",
            status_code=409,
        )

    policy = policy_for_opportunity(opportunity)
    target = getattr(opportunity, "source_url", None)
    if not target:
        return {
            "status": "HUMAN_ACTION_REQUIRED",
            "application_id": application.application_id,
            "opportunity_id": opportunity.opportunity_id,
            "provider_id": policy.provider_id,
            "tier": policy.tier,
            "submission_mode": "handoff",
            "application_url": None,
            "externally_submitted": False,
            "approval_consumed": False,
            "external_action_taken": False,
            "reason": "No external application URL is available. Owner/operator must provide the exact submission target.",
            "financial_execution": False,
            "contract_acceptance": False,
        }

    if not policy.allowlisted or policy.submission_mode == "blocked":
        return {
            "status": "HUMAN_ACTION_REQUIRED",
            "application_id": application.application_id,
            "opportunity_id": opportunity.opportunity_id,
            "provider_id": policy.provider_id,
            "tier": policy.tier,
            "submission_mode": "handoff",
            "application_url": target,
            "externally_submitted": False,
            "approval_consumed": False,
            "external_action_taken": False,
            "reason": "Provider is not allowlisted for automated submission. Open the source page and complete the external step manually.",
            "financial_execution": False,
            "contract_acceptance": False,
        }

    # Until a provider-specific adapter is implemented and verified, preserve
    # approval and hand off only the minimum external step. Do not mark the
    # application submitted and do not consume approval.
    if not policy.live_adapter_implemented:
        reasons = []
        if policy.login_required:
            reasons.append("login may be required")
        if policy.captcha_possible:
            reasons.append("CAPTCHA may be required")
        if policy.identity_required:
            reasons.append("identity verification may be required")
        if policy.signature_required:
            reasons.append("signature/certification may be required")
        detail = "; ".join(reasons) if reasons else "provider has no verified submit API"
        return {
            "status": "HUMAN_ACTION_REQUIRED",
            "application_id": application.application_id,
            "opportunity_id": opportunity.opportunity_id,
            "provider_id": policy.provider_id,
            "tier": policy.tier,
            "submission_mode": "handoff",
            "application_url": target,
            "externally_submitted": False,
            "approval_consumed": False,
            "external_action_taken": False,
            "reason": f"No verified direct-submit adapter is enabled for this provider ({detail}).",
            "financial_execution": False,
            "contract_acceptance": False,
        }

    # Defense in depth. Reaching here without a concrete adapter is a coding
    # error; fail closed rather than pretending to submit.
    raise service.NovaWorkError(
        "Provider claims live submission support but no concrete adapter executed",
        status_code=409,
    )

def _approved_email_body(
    db: Session,
    *,
    application_id: str,
    organization_id: str,
) -> str:
    """Build a sendable body from owner-approved materials only."""
    rows = (
        db.query(NovaWorkMaterial)
        .filter(
            NovaWorkMaterial.application_id == application_id,
            NovaWorkMaterial.organization_id == organization_id,
        )
        .order_by(NovaWorkMaterial.created_at.asc())
        .all()
    )
    by_kind = {str(row.kind or ""): row for row in rows}
    chosen = by_kind.get("cover_letter") or by_kind.get("proposal") or by_kind.get("capability_statement")
    if chosen is None:
        raise service.NovaWorkError("No approved application message material is available", status_code=409)
    body = str(chosen.body or "").strip()
    if "OWNER INPUT REQUIRED" in body.upper():
        raise service.NovaWorkError(
            "Application package still contains OWNER INPUT REQUIRED markers; resolve them before sending",
            status_code=409,
        )
    # Materials are intentionally drafted with internal-only labels. Once the
    # owner has approved the unchanged package, strip only the leading draft
    # banner so the outbound message does not falsely claim it is still internal.
    lines = body.splitlines()
    while lines and (
        lines[0].strip().upper().startswith("DRAFT")
        or "OWNER MUST APPROVE" in lines[0].strip().upper()
    ):
        lines.pop(0)
    cleaned = "\n".join(lines).strip()
    if not cleaned:
        raise service.NovaWorkError("Approved application message is empty", status_code=409)
    return cleaned


_EMAIL_RE = re.compile(r"(?i)(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])")
_APPLY_CONTEXT_RE = re.compile(
    r"(?i)\b(apply|application|resume|résumé|proposal|cv|send|email)\b"
)


def _explicit_application_emails(opportunity: Any) -> list[str]:
    """Return only emails explicitly presented in application/submission context."""
    source_url = str(getattr(opportunity, "source_url", None) or "").strip()
    candidates: list[str] = []
    if source_url.lower().startswith("mailto:"):
        address = source_url[7:].split("?", 1)[0].strip()
        if address and "@" in address:
            candidates.append(address)

    text = "\n".join(
        str(value or "")
        for value in (
            getattr(opportunity, "description", None),
            getattr(opportunity, "requirements", None),
        )
    )
    for match in _EMAIL_RE.finditer(text):
        start = max(0, match.start() - 120)
        end = min(len(text), match.end() + 120)
        context = text[start:end]
        if _APPLY_CONTEXT_RE.search(context):
            candidates.append(match.group(1))

    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = item.strip().lower()
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(item.strip())
    return out


def submit_via_confirmed_email(
    db: Session,
    application_id: str,
    *,
    to_email: str,
    organization_id: str,
    user: UserContext,
) -> dict[str, Any]:
    """Send one owner-approved application email through Nova Communications.

    This is not autonomous bulk outreach. The owner must approve the application,
    provide/verify the exact application email from the listing, attest that the
    listing accepts email applications, and explicitly confirm this send.
    """
    application = service.get_application(
        db,
        application_id,
        organization_id=organization_id,
        user=user,
    )
    opportunity = service.get_opportunity(
        db,
        application.opportunity_id,
        organization_id=organization_id,
        user=user,
    )
    if application.approval_state != "APPROVED" or not application.approved_for_future_submission:
        raise service.NovaWorkError("Owner approval is required before email submission", status_code=409)
    if application.externally_submitted or application.manual_submission_recorded:
        raise service.NovaWorkError("Application has already been recorded as submitted", status_code=409)
    if _materials_changed_after_approval(
        db,
        application_id=application.application_id,
        organization_id=organization_id,
        decided_at=getattr(application, "decided_at", None),
    ):
        raise service.NovaWorkError(
            "Application materials changed after owner approval; return to owner review before sending",
            status_code=409,
        )

    explicit_emails = _explicit_application_emails(opportunity)
    recipient = str(to_email or "").strip()
    if recipient:
        if "@" not in recipient or recipient.startswith("@") or recipient.endswith("@"):
            raise service.NovaWorkError("A valid application email address is required", status_code=422)
        if recipient.lower() not in {item.lower() for item in explicit_emails}:
            raise service.NovaWorkError(
                "The supplied email is not explicitly identified as an application/submission email in the saved listing.",
                status_code=409,
            )
    else:
        if len(explicit_emails) != 1:
            raise service.NovaWorkError(
                "Nova could not verify exactly one email application address from the saved listing. Use the approved provider handoff instead.",
                status_code=409,
            )
        recipient = explicit_emails[0]

    body = _approved_email_body(
        db,
        application_id=application.application_id,
        organization_id=organization_id,
    )
    subject = f"Application / Proposal — {opportunity.opportunity_title} — AMICOR"

    # Reuse the existing owner-confirmed Nova Communications transport. It
    # requires NOVA_COMMUNICATIONS_ALLOW_SEND=1 and a connected email provider.
    from app.core.nova.communications import service as communications_service
    from app.core.nova.communications.schemas import NovaCommsSendRequest

    try:
        sent = communications_service.send_confirmed(
            db,
            NovaCommsSendRequest(
                to=[recipient],
                subject=subject,
                body=body,
                confirm_send=True,
                organization_id=organization_id,
            ),
            organization_id=organization_id,
            user=user,
        )
    except Exception as exc:
        if isinstance(exc, service.NovaWorkError):
            raise
        detail = str(exc)
        raise service.NovaWorkError(
            f"Application email was not sent: {detail}",
            status_code=int(getattr(exc, "status_code", 502) or 502),
        ) from exc

    provider = str((sent or {}).get("provider") or "email")
    recorded = service.record_confirmed_external_submission(
        db,
        application.application_id,
        organization_id=organization_id,
        user=user,
        provider=f"email:{provider}",
        receipt=f"Recipient {recipient}; provider reported status=sent",
    )
    return {
        "status": "SUBMITTED",
        "submission_mode": "owner_confirmed_email",
        "application_id": recorded.application_id,
        "opportunity_id": recorded.opportunity_id,
        "provider_id": provider,
        "recipient": recipient,
        "externally_submitted": True,
        "external_action_taken": True,
        "owner_confirmed": True,
        "financial_execution": False,
        "contract_acceptance": False,
    }

