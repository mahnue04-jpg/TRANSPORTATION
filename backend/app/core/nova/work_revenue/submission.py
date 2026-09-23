"""Approval-gated application submission orchestration.

This module is the canonical last-mile gate for Nova Work applications.
It does not claim an external submission unless a provider-specific live
adapter returns a confirmed receipt. Providers without a verified adapter
fall back to a narrow HUMAN_ACTION_REQUIRED handoff while preserving the
owner's approval.
"""
from __future__ import annotations

from dataclasses import dataclass
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
