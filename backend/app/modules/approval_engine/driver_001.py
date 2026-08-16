"""Driver #001 production-validation preparation.

Creates or reuses a real Platform Ops onboarding application + approval-engine
case with badge DRV-001, BASE ambulatory only. Never fabricates verifications,
never auto-approves, never activates, never enables the dispatch gate.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.approval_engine.audit import record_audit, serialize_audit, list_audit_events
from app.modules.approval_engine.eligibility import dispatch_gate_enabled
from app.modules.approval_engine.models import ApprovalCase, ensure_approval_engine_schema
from app.modules.approval_engine.walkthrough import merge_walkthrough_with_case_state
from app.modules.approval_engine.workflow import (
    build_approval_card,
    create_or_sync_case_from_platform_ops,
    get_case_by_badge,
)
from app.modules.approval_engine.ai_review import run_ai_review
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication
from app.modules.platform_ops.onboarding.service import (
    create_draft_application,
    get_application_by_id,
)
from app.modules.platform_ops.schemas import DriverApplicationDraftRequest

DRIVER_001_BADGE = "DRV-001"
DRIVER_001_TIERS = ["BASE_PRIVATE_AMBULATORY"]


def _serialize_case_brief(case: ApprovalCase) -> dict[str, Any]:
    return {
        "case_id": case.id,
        "display_badge": case.display_badge,
        "workflow_status": case.workflow_status,
        "activation_status": case.activation_status,
        "readiness_percentage": case.readiness_percentage,
        "fingerprint_status": case.fingerprint_status,
        "requested_service_tiers": json.loads(case.requested_service_tiers_json or "[]"),
        "approved_service_tiers": json.loads(case.approved_service_tiers_json or "[]"),
        "ai_summary": case.ai_summary,
        "next_required_action": case.next_required_action,
        "owner_approval_status": case.owner_approval_status,
        "platform_ops_application_id": case.platform_ops_application_id,
        "health_isf_driver_id": case.health_isf_driver_id,
        "last_ai_review_at": case.last_ai_review_at.isoformat() if case.last_ai_review_at else None,
    }


def prepare_driver_001_validation(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str | None = None,
    legal_first_name: str | None = None,
    legal_last_name: str | None = None,
    email: str | None = None,
    mobile_phone: str | None = None,
    reuse_existing: bool = True,
) -> dict[str, Any]:
    """Prepare a real Driver #001 onboarding record for BASE validation.

    - Uses Platform Ops draft application path (same as future drivers).
    - Forces BASE_PRIVATE_AMBULATORY only.
    - Runs AI review to detect missing items / next actions.
    - Does NOT mark any requirement complete.
    - Does NOT owner-approve.
    - Does NOT activate.
    - Does NOT enable dispatch gate.
    """
    ensure_approval_engine_schema()
    if dispatch_gate_enabled():
        # Explicitly refuse silent production gate enablement during validation prep.
        raise ValueError(
            "AMICOR_APPROVAL_ENGINE_DISPATCH_GATE is enabled. "
            "Disable it before Driver #001 production-validation preparation."
        )

    applicant_token: str | None = None
    created_new_application = False
    case = get_case_by_badge(db, organization_id, DRIVER_001_BADGE) if reuse_existing else None
    application: PlatformDriverOnboardingApplication | None = None

    if case and case.platform_ops_application_id:
        application = get_application_by_id(db, case.platform_ops_application_id)

    if application is None:
        # Optional identity seeds help operators recognize the file; driver must still complete
        # all required fields/uploads. Nothing is marked verified.
        payload = DriverApplicationDraftRequest(
            organization_id=organization_id,
            legal_first_name=legal_first_name or "Driver",
            legal_last_name=legal_last_name or "001",
            email=email,
            mobile_phone=mobile_phone,
        )
        application, applicant_token = create_draft_application(
            db,
            organization_id=organization_id,
            payload=payload,
        )
        created_new_application = True

    case = create_or_sync_case_from_platform_ops(
        db,
        application=application,
        display_badge=DRIVER_001_BADGE,
        requested_tiers=list(DRIVER_001_TIERS),
        run_review=False,
    )
    # Hard-enforce BASE-only for Driver #001 validation.
    case.display_badge = DRIVER_001_BADGE
    case.requested_service_tiers_json = json.dumps(DRIVER_001_TIERS)
    case.approved_service_tiers_json = None  # never pre-approve tiers
    case.fingerprint_status = "NOT_REQUIRED"
    case.activation_status = "NOT_ACTIVE"
    if case.workflow_status == "ACTIVE":
        raise ValueError(
            "Existing DRV-001 case is already ACTIVE. Refusing to rewrite activation state. "
            "Use a new badge or review the live case manually."
        )
    case.updated_at = now()
    db.flush()

    case = run_ai_review(
        db,
        case,
        application=application,
        actor_type="AI",
        actor_id="driver_001_validation_prep",
    )

    # Safety: prep must never leave the case approved/active.
    if case.workflow_status in {"OWNER_APPROVED", "APPROVED", "ACTIVE"}:
        raise ValueError("Driver #001 prep unexpectedly reached an approved/active state")
    if case.owner_approval_status == "APPROVED" and not case.owner_approval_timestamp:
        pass  # ignore stale labels; owner_approval_timestamp is source of truth for real approval
    if case.activation_status == "ACTIVE":
        raise ValueError("Driver #001 prep must not activate the driver")

    record_audit(
        db,
        organization_id=organization_id,
        case=case,
        entity_type="driver",
        actor_type="USER" if actor_user_id else "SYSTEM",
        actor_id=actor_user_id or "driver_001_validation_prep",
        previous_status=None,
        new_status=case.workflow_status,
        action="driver_001_validation_prepared",
        reason=(
            "Prepared real Platform Ops + approval-engine records for Driver #001 BASE "
            "ambulatory production validation. No verifications fabricated; not activated."
        ),
        metadata={
            "created_new_application": created_new_application,
            "tiers": DRIVER_001_TIERS,
            "dispatch_gate_enabled": False,
            "fabricated_verifications": False,
            "activated": False,
        },
        commit=True,
    )

    db.refresh(case)
    application = get_application_by_id(db, application.id)
    walkthrough = merge_walkthrough_with_case_state(
        case_requirements=list(case.requirements or []),
        next_required_action=case.next_required_action,
        ai_summary=case.ai_summary,
        workflow_status=case.workflow_status,
    )
    audit = [serialize_audit(e) for e in list_audit_events(db, organization_id=organization_id, case_id=case.id, limit=25)]

    return {
        "driver_badge": DRIVER_001_BADGE,
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "created_new_application": created_new_application,
        "fabricated_verifications": False,
        "owner_approved": False,
        "activated": False,
        "dispatch_gate_enabled": False,
        "safe_test_mode": {
            "required_for_local_usability": True,
            "use_real_sensitive_documents": False,
            "reason": (
                "Local/dev document storage defaults to filesystem local_dev under "
                "backend/data/onboarding_docs. It is not appropriate for real driver's "
                "licenses, insurance cards, registration, tax, banking, or other PII."
            ),
            "placeholder_guidance": {
                "legal_name": "Driver One",
                "email": "driver001.safe@example.com",
                "phone": "612-555-1001",
                "dob": "1988-06-01",
                "license_number": "TEST-MN-001",
                "vehicle": "2019 Honda Accord · plate TEST001 · VIN optional/blank",
                "uploads": (
                    "Upload blank/non-sensitive placeholder images labeled TEST ONLY "
                    "(e.g. a text screenshot). Do not upload real ID/insurance/registration."
                ),
                "w9_payout": "Check the secure-workflow boxes only; do not enter SSN or bank details.",
            },
        },
        "platform_ops_application": {
            "id": application.id if application else None,
            "status": application.status if application else None,
            "applicant_access_token": applicant_token,  # only returned on create
            "apply_path": "/platform-ops/driver-apply",
            "admin_path": "/platform-ops/driver-onboarding-admin",
        },
        "case": _serialize_case_brief(case),
        "approval_card": build_approval_card(case),
        "walkthrough": walkthrough,
        "integrations_still_required": [
            {
                "item": "MVR provider",
                "requirement_keys": ["mvr"],
                "needed_for": "BASE activation",
            },
            {
                "item": "Insurance verification channel",
                "requirement_keys": ["vehicle_insurance"],
                "needed_for": "BASE activation",
            },
            {
                "item": "Vehicle inspection authority / process",
                "requirement_keys": ["vehicle_inspection"],
                "needed_for": "BASE activation",
            },
            {
                "item": "Payout provider / bank setup",
                "requirement_keys": ["payout_setup"],
                "needed_for": "Paid activation",
            },
            {
                "item": "Training completion source (in-app and/or certificates)",
                "requirement_keys": ["base_training"],
                "needed_for": "BASE activation",
            },
            {
                "item": "Minnesota background-study system",
                "requirement_keys": ["background_study"],
                "needed_for": "STS/MHCP only — not BASE",
            },
            {
                "item": "Fingerprint vendor",
                "requirement_keys": ["fingerprint"],
                "needed_for": "STS/MHCP conditional — not BASE",
            },
            {
                "item": "MHCP/NEMT credentialing",
                "requirement_keys": ["mhcp_credentialing"],
                "needed_for": "Future tier only — not BASE",
            },
        ],
        "credentials_accounts_amicor_must_obtain": [
            "MVR service account / API credentials",
            "Insurance verification method (carrier portal, broker, or vendor)",
            "Inspection process ownership (who accepts inspection evidence)",
            "Payout rail account (Stripe Connect / bank payout provider as chosen)",
            "eRA / tax handling process for W-9 (secure handling, not plaintext sprawl)",
            "Optional later: Minnesota NETStudy / background-study access for STS",
            "Optional later: fingerprint vendor account for STS/MHCP",
        ],
        "manual_setup_required": [
            "Driver #001 completes Platform Ops application fields and uploads",
            "Admin reviews uploaded documents (accept/reject) without inventing external clears",
            "External MVR request after consent",
            "Insurance verification after upload",
            "Inspection evidence accepted under Amicor process",
            "Training modules completed and recorded",
            "Contractor agreement + W-9 status completed",
            "Payout method configured",
            "Owner/admin authenticated APPROVE only when READY_FOR_APPROVAL",
        ],
        "owner_approval_required_for": [
            "Material READY_FOR_APPROVAL decision (APPROVE / REJECT / RETURN)",
            "Activation after APPROVED only if all BASE activation conditions remain valid",
            "Any human override (reason required; legal blockers need lawful exception ref)",
        ],
        "compliance_needing_authoritative_verification": [
            "Driver license authenticity (beyond date/presence checks)",
            "MVR result",
            "Insurance validity with carrier",
            "Vehicle registration authenticity when not conclusively verified in-house",
            "Inspection acceptance criteria under Minnesota / Amicor policy",
            "Whether any BASE medical qualification is conditionally required for this driver",
        ],
        "recent_audit": audit,
        "instructions": [
            "1) Share applicant token / apply path with Driver #001 (same flow as future drivers).",
            "2) Driver completes BASE walkthrough steps in order; AI will refresh next actions.",
            "3) Admins record external verification results with evidence — never invent them.",
            "4) When AI moves the case to READY_FOR_APPROVAL, owner decides.",
            "5) Activate only after APPROVED and all mandatory BASE conditions remain valid.",
            "6) Keep STS/MHCP off unless intentionally requested later.",
            "7) Keep AMICOR_APPROVAL_ENGINE_DISPATCH_GATE disabled for this validation phase.",
        ],
    }


def get_driver_001_status(db: Session, *, organization_id: str) -> dict[str, Any]:
    ensure_approval_engine_schema()
    case = get_case_by_badge(db, organization_id, DRIVER_001_BADGE)
    if case is None:
        return {
            "driver_badge": DRIVER_001_BADGE,
            "exists": False,
            "dispatch_gate_enabled": dispatch_gate_enabled(),
            "message": "No DRV-001 case yet. Call prepare endpoint to create the real onboarding record.",
            "walkthrough": merge_walkthrough_with_case_state(
                case_requirements=[],
                next_required_action="Prepare Driver #001 validation record",
                ai_summary=None,
                workflow_status=None,
            ),
        }
    application = (
        get_application_by_id(db, case.platform_ops_application_id)
        if case.platform_ops_application_id
        else None
    )
    # Refresh AI next actions from live application state without inventing completions.
    if application is not None:
        case = run_ai_review(db, case, application=application)
    walkthrough = merge_walkthrough_with_case_state(
        case_requirements=list(case.requirements or []),
        next_required_action=case.next_required_action,
        ai_summary=case.ai_summary,
        workflow_status=case.workflow_status,
    )
    from app.modules.approval_engine.phase2b import build_readiness_view

    return {
        "driver_badge": DRIVER_001_BADGE,
        "exists": True,
        "dispatch_gate_enabled": dispatch_gate_enabled(),
        "fabricated_verifications": False,
        "case": _serialize_case_brief(case),
        "platform_ops_application": {
            "id": application.id if application else None,
            "status": application.status if application else None,
        },
        "approval_card": build_approval_card(case),
        "readiness_view": build_readiness_view(db, case, application),
        "walkthrough": walkthrough,
        "activation_blocked_reason": (
            None
            if case.workflow_status == "ACTIVE"
            else (
                case.next_required_action
                or "Driver #001 is not ACTIVE; mandatory BASE requirements and/or owner approval still outstanding."
            )
        ),
    }
