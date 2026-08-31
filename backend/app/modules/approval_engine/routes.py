"""API routes for the Amicor AI Approval Engine."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.db.session import get_db
from app.helpers import now
from app.modules.approval_engine.assistant import handle_assistant_query
from app.modules.approval_engine.audit import list_audit_events, serialize_audit
from app.modules.approval_engine.compliance import list_expiring, monitor_case
from app.modules.approval_engine.eligibility import evaluate_driver_ride_eligibility
from app.modules.approval_engine.models import ApprovalCase
from app.modules.approval_engine.ai_review import run_ai_review
from app.modules.approval_engine.driver_001 import (
    get_driver_001_status,
    prepare_driver_001_validation,
)
from app.modules.approval_engine.external_service import (
    adapters_for_base,
    record_external_verification,
    remaining_vendor_decisions,
    submit_external_verification,
)
from app.modules.approval_engine.external_verification import (
    PROTECTED_EXTERNAL_REQUIREMENT_KEYS,
    list_adapter_capabilities,
)
from app.modules.approval_engine.phase2b import (
    build_readiness_view,
    record_agreement,
    record_insurance_review,
    record_w9_workflow,
    serialize_agreement,
    serialize_insurance,
    serialize_training,
    serialize_vehicle,
    serialize_w9,
    upsert_vehicle_record,
)
from app.modules.approval_engine.schemas import (
    ActivateRequest,
    AgreementRecordRequest,
    ApprovalCaseCreateRequest,
    ApprovalCaseResponse,
    AssistantQueryRequest,
    Driver001PrepareRequest,
    ExternalVerificationRecordRequest,
    ExternalVerificationSubmitRequest,
    HumanOverrideRequest,
    InsuranceReviewRequest,
    OwnerDecisionRequest,
    RequirementUpdateRequest,
    TrainingUpdateRequest,
    VehicleRecordRequest,
    W9WorkflowRequest,
)
from app.modules.approval_engine.walkthrough import base_walkthrough, non_base_walkthrough
from app.modules.approval_engine.workflow import (
    activate_if_eligible,
    build_approval_card,
    create_or_sync_case_from_platform_ops,
    get_case,
    get_case_by_badge,
    human_override,
    list_cases,
    mark_requirement,
    owner_decide,
)
from app.modules.health_isf.models import HealthISFRide
from app.modules.health_isf.security import enforce_tenant_scope
from app.modules.platform_ops.onboarding.service import get_application_by_id
from app.modules.platform_ops.permissions import can_approve, can_review, can_view_compliance

router = APIRouter(
    prefix="/api/approval-engine",
    tags=["approval-engine"],
    dependencies=[
        Depends(
            require_any_role(
                ROLE_ADMIN,
                ROLE_SUPER_ADMIN_SUPPORT,
                ROLE_SUPERVISOR,
                ROLE_DISPATCHER,
                ROLE_STAFF,
                ROLE_COMPLIANCE_OFFICER,
            )
        )
    ],
)


def _org(user: UserContext, organization_id: str | None) -> str:
    return enforce_tenant_scope(user, organization_id)


def _serialize_case(case: ApprovalCase, *, include_card: bool = False) -> dict[str, Any]:
    def _tiers(raw: str | None) -> list[str]:
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            return [str(x) for x in parsed] if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    payload = {
        "id": case.id,
        "organization_id": case.organization_id,
        "display_badge": case.display_badge,
        "legal_name": case.legal_name,
        "workflow_status": case.workflow_status,
        "activation_status": case.activation_status,
        "readiness_percentage": case.readiness_percentage,
        "compliance_score": case.compliance_score,
        "ai_summary": case.ai_summary,
        "next_required_action": case.next_required_action,
        "requested_service_tiers": _tiers(case.requested_service_tiers_json),
        "approved_service_tiers": _tiers(case.approved_service_tiers_json),
        "fingerprint_status": case.fingerprint_status,
        "owner_approval_status": case.owner_approval_status,
        "owner_approval_timestamp": case.owner_approval_timestamp,
        "approval_actor_id": case.approval_actor_id,
        "platform_ops_application_id": case.platform_ops_application_id,
        "health_isf_driver_id": case.health_isf_driver_id,
        "last_ai_review_at": case.last_ai_review_at,
        "requirements": [
            {
                "key": r.requirement_key,
                "label": r.label,
                "timing": r.timing,
                "status": r.status,
                "external_status": getattr(r, "external_status", None),
                "traffic_light": r.traffic_light,
                "is_blocking": r.is_blocking,
                "is_legal_block": r.is_legal_block,
                "expiration_date": r.expiration_date.isoformat() if r.expiration_date else None,
                "verification_date": r.verification_date.isoformat()
                if getattr(r, "verification_date", None)
                else None,
                "evidence_ref": r.evidence_ref,
                "evidence_source": getattr(r, "evidence_source", None),
                "provider_key": getattr(r, "provider_key", None),
                "provider_reference_id": getattr(r, "provider_reference_id", None),
                "reviewer_source": getattr(r, "reviewer_source", None),
            }
            for r in (case.requirements or [])
        ],
        "external_tasks": [
            {
                "id": t.id,
                "task_type": t.task_type,
                "requirement_key": getattr(t, "requirement_key", None),
                "title": t.title,
                "status": t.status,
                "external_status": getattr(t, "external_status", None),
                "provider_key": getattr(t, "provider_key", None),
                "provider_reference_id": getattr(t, "provider_reference_id", None),
                "evidence_source": getattr(t, "evidence_source", None),
                "instructions": t.instructions,
            }
            for t in (case.external_tasks or [])
        ],
        "training_modules": [serialize_training(m) for m in (case.training_modules or [])],
        "vehicles": [serialize_vehicle(v) for v in (case.vehicles or [])],
        "approval_card": build_approval_card(case) if include_card else None,
    }
    return payload


@router.get("/cases")
def api_list_cases(
    organization_id: str | None = Query(None),
    workflow_status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    cases = list_cases(db, organization_id=org, workflow_status=workflow_status, limit=limit)
    return [_serialize_case(case) for case in cases]


@router.post("/cases", response_model=ApprovalCaseResponse)
def api_create_case(
    payload: ApprovalCaseCreateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    org = _org(user, organization_id)
    application = get_application_by_id(db, payload.platform_ops_application_id)
    if application is None or application.organization_id != org:
        raise HTTPException(status_code=404, detail="Platform Ops application not found")
    case = create_or_sync_case_from_platform_ops(
        db,
        application=application,
        display_badge=payload.display_badge,
        requested_tiers=payload.requested_service_tiers,
        run_review=payload.run_ai_review,
    )
    return _serialize_case(case, include_card=True)


@router.get("/cases/{case_id}")
def api_get_case(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        # Allow badge lookup
        case = get_case_by_badge(db, org, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    return _serialize_case(case, include_card=True)


@router.post("/cases/{case_id}/ai-review")
def api_ai_review(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    application = None
    if case.platform_ops_application_id:
        application = get_application_by_id(db, case.platform_ops_application_id)
    case = run_ai_review(db, case, application=application)
    return _serialize_case(case, include_card=True)


@router.post("/cases/{case_id}/owner-decision")
def api_owner_decision(
    case_id: str,
    payload: OwnerDecisionRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_approve(user):
        raise HTTPException(status_code=403, detail="Owner/admin approval role required")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    try:
        case = owner_decide(
            db,
            case=case,
            decision=payload.decision,
            actor_user_id=str(user.user_id),
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_case(case, include_card=True)


@router.post("/cases/{case_id}/activate")
def api_activate(
    case_id: str,
    payload: ActivateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_approve(user):
        raise HTTPException(status_code=403, detail="Activation role required")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    try:
        case = activate_if_eligible(
            db,
            case=case,
            actor_user_id=str(user.user_id),
            health_isf_driver_id=payload.health_isf_driver_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_case(case, include_card=True)


@router.post("/cases/{case_id}/override")
def api_override(
    case_id: str,
    payload: HumanOverrideRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_approve(user):
        raise HTTPException(status_code=403, detail="Override requires approval role")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    try:
        case = human_override(
            db,
            case=case,
            to_status=payload.to_status,
            actor_user_id=str(user.user_id),
            reason=payload.reason,
            lawful_exception_ref=payload.lawful_exception_ref,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_case(case, include_card=True)


@router.patch("/cases/{case_id}/requirements/{requirement_key}")
def api_update_requirement(
    case_id: str,
    requirement_key: str,
    payload: RequirementUpdateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    try:
        case = mark_requirement(
            db,
            case=case,
            requirement_key=requirement_key,
            status=payload.status,
            actor_user_id=str(user.user_id),
            evidence_ref=payload.evidence_ref,
            traffic_light=payload.traffic_light,
            expiration_date=payload.expiration_date,
            external_result=payload.external_result,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    application = (
        get_application_by_id(db, case.platform_ops_application_id)
        if case.platform_ops_application_id
        else None
    )
    case = run_ai_review(db, case, application=application)
    return _serialize_case(case, include_card=True)


@router.patch("/cases/{case_id}/training/{module_key}")
def api_update_training(
    case_id: str,
    module_key: str,
    payload: TrainingUpdateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    module = next((m for m in (case.training_modules or []) if m.module_key == module_key), None)
    if module is None:
        raise HTTPException(status_code=404, detail="Training module not found")
    module.status = payload.status
    module.evidence_ref = payload.evidence_ref or module.evidence_ref
    module.expires_at = payload.expires_at or module.expires_at
    if payload.module_version:
        module.module_version = payload.module_version
    if payload.assigned_at is not None:
        module.assigned_at = payload.assigned_at
    if payload.status == "completed":
        module.completed_at = payload.completed_at or now()
    elif payload.completed_at is not None:
        module.completed_at = payload.completed_at
    module.updated_at = now()
    db.commit()
    application = (
        get_application_by_id(db, case.platform_ops_application_id)
        if case.platform_ops_application_id
        else None
    )
    case = run_ai_review(db, case, application=application)
    return _serialize_case(case, include_card=True)


@router.get("/cases/{case_id}/audit")
def api_case_audit(
    case_id: str,
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    events = list_audit_events(db, organization_id=org, case_id=case.id, limit=limit)
    return [serialize_audit(event) for event in events]


@router.get("/audit")
def api_search_audit(
    organization_id: str | None = Query(None),
    case_id: str | None = Query(None),
    entity_id: str | None = Query(None),
    application_id: str | None = Query(None),
    action: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    events = list_audit_events(
        db,
        organization_id=org,
        case_id=case_id,
        entity_id=entity_id,
        application_id=application_id,
        action=action,
        limit=limit,
    )
    return [serialize_audit(event) for event in events]


@router.post("/cases/{case_id}/compliance-scan")
def api_compliance_scan(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    return monitor_case(db, case)


@router.get("/expiring")
def api_expiring(
    organization_id: str | None = Query(None),
    within_days: int = Query(30, ge=1, le=365),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    return list_expiring(db, organization_id=org, within_days=within_days)


@router.get("/eligibility/driver/{driver_id}")
def api_driver_eligibility(
    driver_id: str,
    ride_id: str = Query(...),
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
    if ride is None or str(ride.organization_id) != org:
        raise HTTPException(status_code=404, detail="Ride not found")
    return evaluate_driver_ride_eligibility(
        db, organization_id=org, driver_id=driver_id, ride=ride
    )


@router.post("/assistant/query")
def api_assistant_query(
    payload: AssistantQueryRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    ride = None
    if payload.ride_id:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == payload.ride_id).first()
        if ride is None or str(ride.organization_id) != org:
            raise HTTPException(status_code=404, detail="Ride not found")
    return handle_assistant_query(db, organization_id=org, query=payload.query, ride=ride)


@router.get("/walkthrough/base")
def api_base_walkthrough(
    user: UserContext = Depends(get_current_user_context),
):
    """Ordered BASE ambulatory steps with actor classifications (static guide)."""
    _ = user
    return {
        "service_tier": "BASE_PRIVATE_AMBULATORY",
        "ordered_steps": base_walkthrough(),
        "non_base_separate_steps": non_base_walkthrough(),
        "dispatch_gate_enabled_default": False,
    }


@router.get("/cases/{case_id}/driver-messages")
def api_driver_messages(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Prepared simple driver messages — not sent externally from this endpoint."""
    from app.modules.approval_engine.driver_messages import messages_for_case

    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    return {
        "case_id": case.id,
        "delivery": "prepared_not_sent",
        "messages": messages_for_case(case),
    }


@router.get("/external-adapters")
def api_list_external_adapters(
    user: UserContext = Depends(get_current_user_context),
):
    """Configurable provider/manual adapter points — no commercial vendor selected."""
    _ = user
    return {
        "base_adapters": adapters_for_base(),
        "all_adapters": list_adapter_capabilities(),
        "remaining_vendor_decisions": remaining_vendor_decisions(),
        "note": (
            "Adapters are configuration points only. Set AMICOR_EXT_VERIFY_<KEY>_PROVIDER "
            "after business/legal review. Default mode is manual verification."
        ),
    }


@router.post("/cases/{case_id}/external/{requirement_key}/submit")
def api_submit_external_verification(
    case_id: str,
    requirement_key: str,
    payload: ExternalVerificationSubmitRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    try:
        case = submit_external_verification(
            db,
            case=case,
            requirement_key=requirement_key,
            actor_user_id=str(user.user_id),
            payload={
                "notes": payload.notes,
                "provider_reference_id": payload.provider_reference_id,
                **(payload.metadata or {}),
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_case(case, include_card=True)


@router.post("/cases/{case_id}/external/{requirement_key}/record")
def api_record_external_verification(
    case_id: str,
    requirement_key: str,
    payload: ExternalVerificationRecordRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Record an authoritative external/manual result. AI cannot call this path as actor AI."""
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    if requirement_key in PROTECTED_EXTERNAL_REQUIREMENT_KEYS and not can_view_compliance(user):
        raise HTTPException(status_code=403, detail="Compliance role required to record MVR/background/fingerprint")
    org = _org(user, organization_id)
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    try:
        case = record_external_verification(
            db,
            case=case,
            requirement_key=requirement_key,
            status=payload.status,
            actor_user_id=str(user.user_id),
            actor_type=payload.actor_type,
            evidence_source=payload.evidence_source,
            provider_reference_id=payload.provider_reference_id,
            provider_key=payload.provider_key,
            verification_date=payload.verification_date,
            expiration_date=payload.expiration_date,
            notes=payload.notes,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    application = (
        get_application_by_id(db, case.platform_ops_application_id)
        if case.platform_ops_application_id
        else None
    )
    case = run_ai_review(db, case, application=application)
    return _serialize_case(case, include_card=True)


def _case_for_org(db: Session, case_id: str, org: str) -> ApprovalCase:
    case = get_case(db, case_id)
    if case is None or case.organization_id != org:
        raise HTTPException(status_code=404, detail="Approval case not found")
    return case


def _application_for_case(db: Session, case: ApprovalCase):
    if not case.platform_ops_application_id:
        raise HTTPException(status_code=400, detail="Approval case has no Platform Ops application")
    application = get_application_by_id(db, case.platform_ops_application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@router.get("/cases/{case_id}/readiness-view")
def api_readiness_view(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = (
        get_application_by_id(db, case.platform_ops_application_id)
        if case.platform_ops_application_id
        else None
    )
    return build_readiness_view(db, case, application)


@router.post("/cases/{case_id}/insurance-review")
def api_insurance_review(
    case_id: str,
    payload: InsuranceReviewRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_view_compliance(user):
        raise HTTPException(status_code=403, detail="Compliance role required")
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = _application_for_case(db, case)
    recorded = record_insurance_review(
        db,
        case=case,
        application=application,
        actor_user_id=str(user.user_id),
        carrier=payload.carrier,
        policy_reference=payload.policy_reference,
        effective_date=payload.effective_date,
        expiration_date=payload.expiration_date,
        vehicle_association=payload.vehicle_association,
        review_status=payload.review_status,
        notes=payload.notes,
        evidence_ref=payload.evidence_ref,
    )
    case = run_ai_review(db, case, application=application)
    return {"insurance": recorded, "case": _serialize_case(case, include_card=True)}


@router.get("/cases/{case_id}/insurance-review")
def api_get_insurance_review(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = _application_for_case(db, case)
    return serialize_insurance(application)


@router.post("/cases/{case_id}/agreement")
def api_record_agreement(
    case_id: str,
    payload: AgreementRecordRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_view_compliance(user):
        raise HTTPException(status_code=403, detail="Compliance role required")
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = _application_for_case(db, case)
    recorded = record_agreement(
        db,
        case=case,
        application=application,
        actor_user_id=str(user.user_id),
        version=payload.version,
        status=payload.status,
        accepted_at=payload.accepted_at,
        evidence_document_id=payload.evidence_document_id,
        notes=payload.notes,
    )
    case = run_ai_review(db, case, application=application)
    return {"agreement": recorded, "case": _serialize_case(case, include_card=True)}


@router.get("/cases/{case_id}/agreement")
def api_get_agreement(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = _application_for_case(db, case)
    return serialize_agreement(application)


@router.post("/cases/{case_id}/w9-workflow")
def api_w9_workflow(
    case_id: str,
    payload: W9WorkflowRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_view_compliance(user):
        raise HTTPException(status_code=403, detail="Compliance role required")
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = _application_for_case(db, case)
    try:
        recorded = record_w9_workflow(
            db,
            case=case,
            application=application,
            actor_user_id=str(user.user_id),
            status=payload.status,
            external_provider=payload.external_provider,
            external_reference=payload.external_reference,
            notes=payload.notes,
            payload=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    case = run_ai_review(db, case, application=application)
    return {"w9": recorded, "case": _serialize_case(case, include_card=True)}


@router.get("/cases/{case_id}/w9-workflow")
def api_get_w9_workflow(
    case_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    application = _application_for_case(db, case)
    return serialize_w9(application)


@router.post("/cases/{case_id}/vehicle")
def api_upsert_vehicle(
    case_id: str,
    payload: VehicleRecordRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    if not can_view_compliance(user):
        raise HTTPException(status_code=403, detail="Compliance role required")
    org = _org(user, organization_id)
    case = _case_for_org(db, case_id, org)
    try:
        recorded = upsert_vehicle_record(
            db,
            case=case,
            actor_user_id=str(user.user_id),
            make=payload.make,
            model=payload.model,
            year=payload.year,
            license_plate=payload.license_plate,
            registration_expiration=payload.registration_expiration,
            inspection_status=payload.inspection_status,
            inspection_expiration=payload.inspection_expiration,
            insurance_association_ref=payload.insurance_association_ref,
            insurance_expiration=payload.insurance_expiration,
            eligibility_status=payload.eligibility_status,
            health_isf_vehicle_id=payload.health_isf_vehicle_id,
            notes=payload.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    application = (
        get_application_by_id(db, case.platform_ops_application_id)
        if case.platform_ops_application_id
        else None
    )
    case = run_ai_review(db, case, application=application)
    return {"vehicle": recorded, "case": _serialize_case(case, include_card=True)}


@router.get("/driver-001")
def api_driver_001_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    org = _org(user, organization_id)
    return get_driver_001_status(db, organization_id=org)


@router.post("/driver-001/prepare")
def api_prepare_driver_001(
    payload: Driver001PrepareRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Create/reuse a real DRV-001 Platform Ops + approval case for BASE validation.

    Does not fabricate verifications, approve, activate, or enable the dispatch gate.
    """
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    org = _org(user, organization_id)
    try:
        return prepare_driver_001_validation(
            db,
            organization_id=org,
            actor_user_id=str(user.user_id),
            legal_first_name=payload.legal_first_name,
            legal_last_name=payload.legal_last_name,
            email=payload.email,
            mobile_phone=payload.mobile_phone,
            reuse_existing=payload.reuse_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cases/{case_id}/compliance-summary")
def api_case_compliance_summary(
    case_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    from app.modules.approval_engine.compliance_summary import (
        build_compliance_summary,
        resolve_case_and_application,
    )

    case = db.query(ApprovalCase).filter(ApprovalCase.id == case_id).first()
    if case is None:
        raise HTTPException(status_code=404, detail="Approval case not found")
    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    case, application = resolve_case_and_application(db, case=case)
    return build_compliance_summary(db, application=application, case=case)


@router.get("/applications/{application_id}/compliance-summary")
def api_application_compliance_summary(
    application_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    from app.modules.approval_engine.compliance_summary import (
        build_compliance_summary,
        resolve_case_and_application,
    )
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    application = (
        db.query(PlatformDriverOnboardingApplication)
        .filter(PlatformDriverOnboardingApplication.id == application_id)
        .first()
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    case, application = resolve_case_and_application(db, application=application)
    return build_compliance_summary(db, application=application, case=case)


@router.get("/driver-001/compliance-summary")
def api_driver_001_compliance_summary(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    from app.modules.approval_engine.compliance_summary import (
        build_compliance_summary,
        resolve_case_and_application,
    )
    from app.modules.approval_engine.driver_001 import DRIVER_001_BADGE
    from app.modules.approval_engine.workflow import get_case_by_badge

    if not can_review(user):
        raise HTTPException(status_code=403, detail="Review role required")
    org = _org(user, organization_id)
    case = get_case_by_badge(db, org, DRIVER_001_BADGE)
    if case is None:
        return {
            "exists": False,
            "overall_status": "NOT_STARTED",
            "progress_percent": 0,
            "next_required_action": "Prepare Driver #001 validation record",
            "items": [],
        }
    case, application = resolve_case_and_application(db, case=case)
    summary = build_compliance_summary(db, application=application, case=case)
    summary["exists"] = True
    return summary
