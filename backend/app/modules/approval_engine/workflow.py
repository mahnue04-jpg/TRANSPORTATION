"""Workflow transitions, owner approval gate, and activation controls."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.audit import record_audit
from app.modules.approval_engine.ai_review import run_ai_review
from app.modules.approval_engine.models import ApprovalCase
from app.modules.approval_engine.requirements import normalize_tiers
from app.modules.approval_engine.statuses import (
    assert_transition_allowed,
    list_allowed_next_statuses,
    normalize_status,
)
from app.modules.approval_engine.walkthrough import merge_walkthrough_with_case_state
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return []


def get_case(db: Session, case_id: str) -> ApprovalCase | None:
    return db.query(ApprovalCase).filter(ApprovalCase.id == case_id).first()


def get_case_by_badge(db: Session, organization_id: str, badge: str) -> ApprovalCase | None:
    return (
        db.query(ApprovalCase)
        .filter(
            ApprovalCase.organization_id == organization_id,
            ApprovalCase.display_badge == str(badge).strip().upper(),
        )
        .first()
    )


def list_cases(
    db: Session,
    *,
    organization_id: str,
    workflow_status: str | None = None,
    limit: int = 100,
) -> list[ApprovalCase]:
    query = db.query(ApprovalCase).filter(ApprovalCase.organization_id == organization_id)
    if workflow_status:
        query = query.filter(ApprovalCase.workflow_status == normalize_status(workflow_status))
    return (
        query.order_by(ApprovalCase.updated_at.desc(), ApprovalCase.id.asc())
        .limit(max(1, min(int(limit or 100), 500)))
        .all()
    )


def create_or_sync_case_from_platform_ops(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    display_badge: str | None = None,
    requested_tiers: list[str] | None = None,
    run_review: bool = True,
) -> ApprovalCase:
    case = (
        db.query(ApprovalCase)
        .filter(
            ApprovalCase.organization_id == application.organization_id,
            ApprovalCase.platform_ops_application_id == application.id,
        )
        .first()
    )
    tiers = normalize_tiers(requested_tiers)
    if case is None:
        case = ApprovalCase(
            id=uuid4(),
            organization_id=application.organization_id,
            entity_type="driver",
            application_id=application.id,
            platform_ops_application_id=application.id,
            display_badge=(display_badge or "").strip().upper() or None,
            workflow_status="PENDING",
            requested_service_tiers_json=json.dumps(tiers),
            created_at=now(),
            updated_at=now(),
        )
        db.add(case)
        db.flush()
        record_audit(
            db,
            organization_id=application.organization_id,
            case=case,
            entity_type="driver",
            action="case_created",
            actor_type="SYSTEM",
            actor_id="approval_engine",
            previous_status=None,
            new_status="PENDING",
            reason="Approval case created from platform ops application",
        )
    else:
        if display_badge:
            case.display_badge = display_badge.strip().upper()
        case.requested_service_tiers_json = json.dumps(tiers)
        case.updated_at = now()

    if run_review:
        return run_ai_review(db, case, application=application)
    db.commit()
    db.refresh(case)
    return case


def blocking_requirements(case: ApprovalCase) -> list[Any]:
    return [
        req
        for req in (case.requirements or [])
        if req.is_blocking
        and req.timing in {"required_now", "required_before_activation"}
        and req.status
        not in {
            "COMPLETE",
            "VERIFIED",
            "CLEARED",
            "NOT_REQUIRED",
            "FUTURE",
            "CONDITIONAL_NOT_APPLICABLE",
        }
    ]


def legal_blocking_requirements(case: ApprovalCase) -> list[Any]:
    return [req for req in blocking_requirements(case) if req.is_legal_block]


def build_approval_card(case: ApprovalCase) -> dict[str, Any]:
    from app.modules.approval_engine.driver_messages import messages_for_case

    requirements = [
        {
            "key": req.requirement_key,
            "label": req.label,
            "traffic_light": req.traffic_light,
            "status": req.status,
            "external_status": getattr(req, "external_status", None),
            "timing": req.timing,
            "is_blocking": req.is_blocking,
            "is_legal_block": req.is_legal_block,
            "expiration_date": req.expiration_date.isoformat() if req.expiration_date else None,
            "evidence_ref": req.evidence_ref,
            "evidence_source": getattr(req, "evidence_source", None),
            "provider_reference_id": getattr(req, "provider_reference_id", None),
        }
        for req in sorted(case.requirements or [], key=lambda r: r.requirement_key)
    ]
    satisfied = {"COMPLETE", "VERIFIED", "CLEARED", "NOT_REQUIRED", "FUTURE", "CONDITIONAL_NOT_APPLICABLE"}
    completed = [r for r in requirements if r["status"] in satisfied]
    missing = [
        r
        for r in requirements
        if r["is_blocking"]
        and r["status"] in {"MISSING", "MISSING_CONSENT", "NOT_STARTED", "ACTION_REQUIRED", "EXPIRED", "FAILED"}
    ]
    pending_external = [
        r
        for r in requirements
        if r["status"] in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW", "PENDING_VERIFICATION"}
    ]
    legal_blockers = [r for r in requirements if r["is_legal_block"] and r["status"] not in satisfied]
    warnings = [r for r in requirements if r["traffic_light"] == "yellow"]
    blockers = [r for r in requirements if r["traffic_light"] == "red" and r["is_blocking"]]
    expiring = [
        r
        for r in requirements
        if r.get("expiration_date") and r["traffic_light"] in {"yellow", "green"}
    ]
    return {
        "case_id": case.id,
        "display_badge": case.display_badge,
        "driver_name": case.legal_name,
        "driver_id": case.health_isf_driver_id or case.entity_id,
        "application_id": case.application_id,
        "workflow_status": case.workflow_status,
        "readiness_percentage": case.readiness_percentage,
        "service_tiers_requested": _json_list(case.requested_service_tiers_json),
        "service_tiers_approved": _json_list(case.approved_service_tiers_json),
        "requirements": requirements,
        "completed_requirements": completed,
        "missing_requirements": missing,
        "pending_external_verifications": pending_external,
        "legal_compliance_blockers": legal_blockers,
        "unresolved_warnings": warnings,
        "blocking_requirements": blockers,
        "expiring_soon_items": expiring,
        "ai_recommendation": case.ai_summary,
        "ai_summary": case.ai_summary,
        "next_required_action": case.next_required_action,
        "prepared_driver_messages": messages_for_case(case),
        "ready_for_owner_decision": case.workflow_status == "READY_FOR_APPROVAL" and not blockers and not legal_blockers,
        "owner_actions_available": (
            ["APPROVE", "REJECT", "RETURN_FOR_CORRECTION"]
            if case.workflow_status == "READY_FOR_APPROVAL" and not blockers and not legal_blockers
            else ["REJECT", "RETURN_FOR_CORRECTION"]
            if case.workflow_status in {"READY_FOR_APPROVAL", "ACTION_REQUIRED", "EXTERNAL_VERIFICATION", "FLAGGED"}
            else []
        ),
        "actions": ["APPROVE", "REJECT", "RETURN_FOR_CORRECTION"],
        "base_walkthrough": merge_walkthrough_with_case_state(
            case_requirements=list(case.requirements or []),
            next_required_action=case.next_required_action,
            ai_summary=case.ai_summary,
            workflow_status=case.workflow_status,
        ),
    }


def owner_decide(
    db: Session,
    *,
    case: ApprovalCase,
    decision: str,
    actor_user_id: str,
    reason: str | None = None,
    application: PlatformDriverOnboardingApplication | None = None,
) -> ApprovalCase:
    decision_norm = str(decision or "").strip().upper()
    if case.workflow_status != "READY_FOR_APPROVAL":
        raise ValueError("Owner decision is only allowed when status is READY_FOR_APPROVAL")
    if decision_norm == "APPROVE":
        if blocking_requirements(case):
            raise ValueError("Cannot approve while blocking requirements remain incomplete")
        from app.modules.approval_engine.phase2b import p1_approval_blockers
        from app.modules.platform_ops.onboarding.service import get_application_by_id

        linked = application
        if linked is None and case.platform_ops_application_id:
            linked = get_application_by_id(db, case.platform_ops_application_id)
        extra_blockers = p1_approval_blockers(db, case, linked)
        if extra_blockers:
            raise ValueError("Cannot approve while P1 blockers remain: " + "; ".join(extra_blockers))
        previous = case.workflow_status
        assert_transition_allowed(previous, "OWNER_APPROVED")
        case.workflow_status = "OWNER_APPROVED"
        case.owner_approval_status = "APPROVED"
        case.owner_approval_timestamp = now()
        case.approval_actor_id = actor_user_id
        case.approved_service_tiers_json = case.requested_service_tiers_json
        case.updated_at = now()
        approval_id = uuid4()
        record_audit(
            db,
            organization_id=case.organization_id,
            case=case,
            entity_type="driver",
            entity_id=case.entity_id or case.health_isf_driver_id,
            actor_type="USER",
            actor_id=actor_user_id,
            previous_status=previous,
            new_status="OWNER_APPROVED",
            action="owner_approve",
            reason=reason or "Owner approved onboarding package",
            approval_id=approval_id,
        )
        # Auto-progress to APPROVED only if still no blockers.
        if not blocking_requirements(case):
            assert_transition_allowed("OWNER_APPROVED", "APPROVED")
            case.workflow_status = "APPROVED"
            record_audit(
                db,
                organization_id=case.organization_id,
                case=case,
                entity_type="driver",
                actor_type="SYSTEM",
                actor_id="approval_engine",
                previous_status="OWNER_APPROVED",
                new_status="APPROVED",
                action="auto_approved_after_owner",
                reason="No blocking requirements after owner approval",
                approval_id=approval_id,
            )
        db.commit()
        db.refresh(case)
        return case

    if decision_norm == "REJECT":
        if not reason:
            raise ValueError("Rejection requires a reason")
        previous = case.workflow_status
        assert_transition_allowed(previous, "REJECTED")
        case.workflow_status = "REJECTED"
        case.owner_approval_status = "REJECTED"
        case.approval_actor_id = actor_user_id
        case.suspension_restriction_reason = reason
        case.updated_at = now()
        record_audit(
            db,
            organization_id=case.organization_id,
            case=case,
            entity_type="driver",
            actor_type="USER",
            actor_id=actor_user_id,
            previous_status=previous,
            new_status="REJECTED",
            action="owner_reject",
            reason=reason,
        )
        db.commit()
        db.refresh(case)
        return case

    if decision_norm in {"RETURN", "RETURN_FOR_CORRECTION"}:
        previous = case.workflow_status
        assert_transition_allowed(previous, "ACTION_REQUIRED")
        case.workflow_status = "ACTION_REQUIRED"
        case.owner_approval_status = "RETURNED"
        case.approval_actor_id = actor_user_id
        case.next_required_action = reason or "Returned for correction by owner"
        case.updated_at = now()
        record_audit(
            db,
            organization_id=case.organization_id,
            case=case,
            entity_type="driver",
            actor_type="USER",
            actor_id=actor_user_id,
            previous_status=previous,
            new_status="ACTION_REQUIRED",
            action="owner_return_for_correction",
            reason=reason,
        )
        db.commit()
        db.refresh(case)
        return case

    raise ValueError("decision must be APPROVE, REJECT, or RETURN_FOR_CORRECTION")


def activate_if_eligible(
    db: Session,
    *,
    case: ApprovalCase,
    actor_user_id: str,
    health_isf_driver_id: str | None = None,
) -> ApprovalCase:
    """Move APPROVED → ACTIVE only when all activation conditions remain valid."""
    if case.workflow_status not in {"APPROVED", "OWNER_APPROVED"}:
        raise ValueError("Activation requires APPROVED (or OWNER_APPROVED with no blockers)")
    if case.workflow_status == "OWNER_APPROVED":
        if blocking_requirements(case):
            raise ValueError("Cannot activate with blocking requirements")
        assert_transition_allowed("OWNER_APPROVED", "APPROVED")
        case.workflow_status = "APPROVED"

    blockers = blocking_requirements(case)
    if blockers:
        raise ValueError(
            "Cannot activate: blocking requirements remain: "
            + ", ".join(b.requirement_key for b in blockers)
        )
    if case.payout_setup_status not in {"COMPLETE", "VERIFIED", "READY"}:
        raise ValueError("Cannot activate for paid rides until payout setup is complete")
    if case.contractor_agreement_status not in {"COMPLETE", "SIGNED", "VERIFIED"} and any(
        r.requirement_key == "contractor_agreement" and r.status != "COMPLETE"
        for r in (case.requirements or [])
    ):
        raise ValueError("Cannot activate until contractor agreement is complete")

    previous = case.workflow_status
    assert_transition_allowed(previous, "ACTIVE")
    case.workflow_status = "ACTIVE"
    case.activation_status = "ACTIVE"
    if health_isf_driver_id:
        case.health_isf_driver_id = health_isf_driver_id
        case.entity_id = health_isf_driver_id
    case.updated_at = now()
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        entity_id=case.health_isf_driver_id,
        actor_type="USER",
        actor_id=actor_user_id,
        previous_status=previous,
        new_status="ACTIVE",
        action="activate_driver",
        reason="All activation conditions satisfied",
    )
    db.commit()
    db.refresh(case)
    return case


def human_override(
    db: Session,
    *,
    case: ApprovalCase,
    to_status: str,
    actor_user_id: str,
    reason: str,
    lawful_exception_ref: str | None = None,
) -> ApprovalCase:
    """Override with role-checked caller (route enforces role). Never greens legal blockers without exception."""
    if not reason or not str(reason).strip():
        raise ValueError("Override requires a reason")
    target = normalize_status(to_status)
    previous = normalize_status(case.workflow_status)
    if target == "ACTIVE":
        legal = legal_blocking_requirements(case)
        if legal and not lawful_exception_ref:
            raise ValueError(
                "Cannot override to ACTIVE while legal blocking requirements remain without "
                "a documented lawful exception / verified set-aside reference"
            )
    assert_transition_allowed(previous, target)
    case.workflow_status = target
    case.updated_at = now()
    if target in {"SUSPENDED", "RESTRICTED"}:
        case.suspension_restriction_reason = reason
        case.activation_status = target
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        entity_id=case.entity_id or case.health_isf_driver_id,
        actor_type="USER",
        actor_id=actor_user_id,
        previous_status=previous,
        new_status=target,
        action="human_override",
        reason=reason,
        evidence_ref=lawful_exception_ref,
        metadata={"allowed_next": list_allowed_next_statuses(previous), "lawful_exception_ref": lawful_exception_ref},
    )
    db.commit()
    db.refresh(case)
    return case


def mark_requirement(
    db: Session,
    *,
    case: ApprovalCase,
    requirement_key: str,
    status: str,
    actor_user_id: str,
    evidence_ref: str | None = None,
    traffic_light: str | None = None,
    expiration_date=None,
    external_result: bool = False,
) -> ApprovalCase:
    """Record a human/external verification result. AI paths must not call this to invent results."""
    req = next((r for r in (case.requirements or []) if r.requirement_key == requirement_key), None)
    if req is None:
        raise ValueError(f"Unknown requirement: {requirement_key}")
    if req.is_legal_block and status in {"COMPLETE", "VERIFIED", "CLEARED"} and not evidence_ref and not external_result:
        raise ValueError("Legal requirement completion requires evidence_ref or external_result confirmation")
    from app.modules.approval_engine.external_verification import (
        BASE_EXTERNAL_REQUIREMENT_KEYS,
        normalize_external_status,
        traffic_for_external_status,
    )

    previous = req.status
    req.status = status
    if requirement_key in BASE_EXTERNAL_REQUIREMENT_KEYS or external_result:
        req.external_status = normalize_external_status(status)
        req.traffic_light = traffic_light or traffic_for_external_status(req.external_status)
        if evidence_ref:
            req.evidence_source = evidence_ref
        req.reviewer_source = "EXTERNAL" if external_result else "USER"
        if req.external_status == "VERIFIED":
            from datetime import date as _date

            req.verification_date = req.verification_date or _date.today()
    else:
        req.traffic_light = traffic_light or (
            "green" if status in {"COMPLETE", "VERIFIED", "CLEARED", "NOT_REQUIRED"} else req.traffic_light
        )
    req.evidence_ref = evidence_ref or req.evidence_ref
    req.verified_by = actor_user_id
    req.verified_at = now()
    if expiration_date is not None:
        req.expiration_date = expiration_date
    req.updated_at = now()

    # Mirror key case fields.
    if requirement_key == "mvr" and status in {"COMPLETE", "VERIFIED", "CLEAR"}:
        case.mvr_status = "COMPLETE"
    if requirement_key == "background_study" and status in {"COMPLETE", "CLEARED", "VERIFIED"}:
        case.background_study_status = "COMPLETE"
    if requirement_key == "fingerprint":
        case.fingerprint_status = status if status in {"NOT_REQUIRED", "PENDING", "REQUIRED", "COMPLETE", "FAILED"} else case.fingerprint_status
    if requirement_key == "vehicle_insurance" and status in {"COMPLETE", "VERIFIED"}:
        case.insurance_status = "VERIFIED"
    if requirement_key == "vehicle_registration" and status in {"COMPLETE", "VERIFIED"}:
        case.vehicle_registration_status = "VERIFIED"
    if requirement_key == "vehicle_inspection" and status in {"COMPLETE", "VERIFIED"}:
        case.inspection_status = "VERIFIED"
    if requirement_key == "drivers_license" and status in {"COMPLETE", "VERIFIED"}:
        case.license_verification_status = "VERIFIED"
    if requirement_key == "payout_setup" and status in {"COMPLETE", "VERIFIED", "READY"}:
        case.payout_setup_status = "COMPLETE"
    if requirement_key == "contractor_agreement" and status in {"COMPLETE", "SIGNED", "VERIFIED"}:
        case.contractor_agreement_status = "COMPLETE"
    if requirement_key == "w9" and status in {"COMPLETE", "VERIFIED", "SIGNED"}:
        case.w9_status = "COMPLETE"

    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        actor_type="USER" if not external_result else "EXTERNAL",
        actor_id=actor_user_id,
        action="requirement_status_updated",
        reason=f"{requirement_key}: {previous} -> {status}",
        evidence_ref=evidence_ref,
        metadata={"requirement_key": requirement_key, "status": status},
    )
    db.commit()
    db.refresh(case)
    return case
