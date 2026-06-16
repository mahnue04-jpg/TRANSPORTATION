from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DRIVER_SUPPORT,
    ROLE_MEDICAL_COORDINATOR,
    ROLE_SUPERVISOR,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.compliance_evidence_service import ComplianceEvidenceService
from app.core.nova.compliance_service import ComplianceService
from app.core.nova.operations_orchestration_service import OperationsOrchestrationService
from app.core.nova.router import _resolve_org
from app.db.models import (
    OperationsConstraintEvaluation,
    OperationsConstraintViolation,
    OperationsPolicyScoreSnapshot,
)
from app.db.session import get_db


require_compliance_read = require_any_role(
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SUPERVISOR,
    ROLE_DRIVER_SUPPORT,
    ROLE_MEDICAL_COORDINATOR,
)

require_profile_update = require_any_role(
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DRIVER_SUPPORT,
    ROLE_SUPERVISOR,
)

require_document_review = require_any_role(
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
)

require_supervisor_approval = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPERVISOR,
)

require_orchestration_read = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPERVISOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DRIVER_SUPPORT,
    ROLE_MEDICAL_COORDINATOR,
)

require_orchestration_mutation = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPERVISOR,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DRIVER_SUPPORT,
)

router = APIRouter(prefix="/api/ops/compliance", tags=["ops-compliance"])
orchestration_router = APIRouter(prefix="/api/ops/orchestration", tags=["ops-orchestration"])
federation_router = APIRouter(prefix="/api/ops/federation", tags=["ops-federation"])
replay_router = APIRouter(prefix="/api/ops/replay", tags=["ops-replay"])
predictive_router = APIRouter(prefix="/api/ops/predictive", tags=["ops-predictive"])
governance_router = APIRouter(prefix="/api/ops/governance", tags=["ops-governance"])


class ComplianceProfileUpsertRequest(BaseModel):
    driver_id: str
    onboarding_status: str | None = None
    compliance_status: str | None = None
    approval_status: str | None = None
    background_check_status: str | None = None
    background_check_reference: str | None = None
    license_number: str | None = None
    license_expiration: str | None = None
    insurance_provider: str | None = None
    insurance_expiration: str | None = None
    vehicle_registration_expiration: str | None = None
    vehicle_inspection_expiration: str | None = None
    medical_transport_certified: bool | None = None
    training_completed: bool | None = None
    notes: str | None = None


class ComplianceDocumentMetadataRequest(BaseModel):
    driver_id: str
    document_id: str | None = None
    type: str
    expiration_date: str | None = None


class ComplianceEvidenceAppendRequest(BaseModel):
    driver_id: str
    document_id: str
    mime_type: str | None = None
    storage_provider: str | None = None
    retention_class: str | None = None
    encryption_status: str | None = None
    immutable_reference_id: str | None = None
    replaces_document_id: str | None = None
    lineage_root_id: str | None = None
    content_seed: str | None = None


class ComplianceSignedAccessRequest(BaseModel):
    document_id: str
    access_reason: str
    ttl_minutes: int | None = 15


class ComplianceSignedAccessReadRequest(BaseModel):
    signed_access_id: str
    access_reason: str


class ComplianceSignedAccessRevokeRequest(BaseModel):
    signed_access_id: str


class ComplianceExportRequest(BaseModel):
    driver_id: str | None = None
    export_scope: str | None = None
    retention_class: str | None = None


class ComplianceHandoffRequest(BaseModel):
    driver_id: str
    stage: str
    assigned_supervisor_id: str | None = None
    countersign_supervisor_id: str | None = None
    escalation_notes: str
    review_reassignment_from: str | None = None


class ComplianceRetentionRequest(BaseModel):
    document_id: str
    retention_class: str
    action_type: str | None = None
    legal_hold: bool | None = False
    release_reason: str | None = None


class CompliancePolicyPackRequest(BaseModel):
    jurisdiction: str
    transport_type: str | None = None
    medical_transport_class: str | None = None


class OrchestrationTaskCreateRequest(BaseModel):
    title: str
    description: str
    category: str | None = None
    priority: str | None = None
    target_driver_id: str | None = None


class OrchestrationTaskAssignRequest(BaseModel):
    task_id: str
    assigned_to: str
    assigned_to_role: str
    reason: str


class OrchestrationTaskAcknowledgeRequest(BaseModel):
    task_id: str
    note: str
    acknowledgement_type: str | None = None


class OrchestrationTaskEscalateRequest(BaseModel):
    task_id: str
    escalation_level: str
    routed_to: str
    routed_to_role: str
    reason: str


class OrchestrationTaskHandoffRequest(BaseModel):
    task_id: str
    stage: str
    from_user_id: str | None = None
    from_role: str | None = None
    to_user_id: str
    to_role: str
    note: str


class OrchestrationNotificationAppendRequest(BaseModel):
    task_id: str
    notification_type: str
    message: str
    notification_scope: str | None = None
    metadata: dict[str, Any] | None = None


class OrchestrationResolutionRequest(BaseModel):
    task_id: str
    reason: str


class OrchestrationResolutionApprovalRequest(BaseModel):
    task_id: str
    reason: str


class OrchestrationResolutionRejectRequest(BaseModel):
    task_id: str
    reason: str


class FederationRegisterRegionRequest(BaseModel):
    region_code: str
    region_name: str
    region_id: str | None = None
    memberships: list[dict[str, Any]] | None = None


class FederationCrossRegionHandoffRequest(BaseModel):
    task_id: str
    source_region_id: str
    target_region_id: str
    reason: str


class ReplaySessionCreateRequest(BaseModel):
    session_name: str
    after_sequence: int | None = 0
    limit: int | None = 120
    scenario_id: str | None = None


class ReplayScenarioCreateRequest(BaseModel):
    scenario_name: str
    hypothesis: str
    scenario_type: str | None = None
    baseline_window: str | None = None


class ReplayBranchGenerateRequest(BaseModel):
    replay_session_id: str
    branch_name: str
    branch_type: str | None = None
    scenario_id: str | None = None


class PredictiveGovernanceRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    prediction_scope: str | None = "governance"


class PredictiveConstraintRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    constraint_domain: str | None = "operational_constraints"


class PredictiveCapacityRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    capacity_scope: str | None = "capacity_pressure"


class PredictiveRiskRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    risk_domain: str | None = "governance_risk"


class PredictiveAnomalyRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    anomaly_scope: str | None = "operational_anomaly"


class GovernanceProvenanceRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    decision_scope: str | None = "governance_decision"


class GovernanceExplanationRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    explanation_scope: str | None = "governance_explanation"


class GovernanceReasoningRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    reasoning_scope: str | None = "advisory_reasoning"


class GovernanceMemoryRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    memory_window: str | None = "long_horizon"
    trend_window: str | None = "long_horizon"


class GovernancePolicyRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None
    policy_scope: str | None = "governance_policy_constraints"


class GovernanceRationaleChainRequest(BaseModel):
    replay_session_id: str | None = None
    decision_id: str | None = None


class GovernanceRiskRequest(BaseModel):
    replay_session_id: str | None = None
    scenario_id: str | None = None


class ComplianceDocumentVerificationRequest(BaseModel):
    document_id: str
    verification_status: str
    reason: str


class ComplianceWorkflowActionRequest(BaseModel):
    driver_id: str
    action: str
    reason: str


@router.get("/dashboard-summary", dependencies=[Depends(require_compliance_read)])
def compliance_dashboard_summary(
    organization_id: str | None = Query(None),
    role_view: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceService.dashboard_summary(
        db,
        organization_id=org_id,
        actor=user,
        role_view=role_view,
    )
    payload["phase25"] = ComplianceEvidenceService.evidence_dashboard_extensions(
        db,
        organization_id=org_id,
        role_view=payload.get("role_view", user.role),
    )
    payload["audit_metadata"] = {
        "generated_at": payload.get("compliance_timeline", [{}])[0].get("timestamp") if payload.get("compliance_timeline") else None,
        "endpoint": "/api/ops/compliance/dashboard-summary",
        "organization_id": org_id,
        "role": user.role,
        "correlation_id": f"compliance-summary-{uuid4().hex[:12]}",
        "advisory_only": True,
        "execution_disabled": True,
        "append_only": True,
        "replay_safe": True,
        "deny_by_default": True,
    }
    return payload


@router.get("/timeline", dependencies=[Depends(require_compliance_read)])
def compliance_timeline(
    organization_id: str | None = Query(None),
    role_view: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceService.dashboard_summary(
        db,
        organization_id=org_id,
        actor=user,
        role_view=role_view,
    )
    rows = [
        row for row in payload.get("compliance_timeline", [])
        if int(row.get("sequence", 0) or 0) > after_sequence
    ]
    rows = sorted(rows, key=lambda row: int(row.get("sequence", 0) or 0))[:limit]
    next_cursor = max([int(row.get("sequence", 0) or 0) for row in rows], default=after_sequence)

    return {
        "organization_id": org_id,
        "role_scope": user.role,
        "role_view": payload.get("role_view", user.role),
        "after_sequence": after_sequence,
        "next_cursor": next_cursor,
        "events": rows,
        "ordering": "sequence_ascending",
        "append_only": True,
        "replay_safe": True,
        "governance": payload.get("governance", {}),
        "audit_metadata": {
            "endpoint": "/api/ops/compliance/timeline",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"compliance-timeline-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "append_only": True,
            "replay_safe": True,
            "deny_by_default": True,
        },
    }


@router.post("/profile/upsert", dependencies=[Depends(require_profile_update)])
def upsert_compliance_profile(
    body: ComplianceProfileUpsertRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    profile = ComplianceService.upsert_profile(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=False),
        correlation_id=f"compliance-profile-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "profile": profile,
        "advisory_only": True,
        "execution_disabled": True,
        "supervision_required": True,
    }


@router.post("/documents/upload-metadata", dependencies=[Depends(require_profile_update)])
def upload_document_metadata(
    body: ComplianceDocumentMetadataRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    document = ComplianceService.upload_document_metadata(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(),
        correlation_id=f"compliance-doc-upload-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "document": document,
        "advisory_only": True,
        "execution_disabled": True,
        "supervision_required": True,
    }


@router.post("/documents/verify", dependencies=[Depends(require_document_review)])
def verify_document(
    body: ComplianceDocumentVerificationRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    verified = ComplianceService.verify_document(
        db,
        organization_id=org_id,
        actor=user,
        document_id=body.document_id,
        verification_status=body.verification_status,
        reason=body.reason,
        correlation_id=f"compliance-doc-verify-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "document": verified,
        "advisory_only": True,
        "execution_disabled": True,
        "supervision_required": True,
    }


@router.post("/workflow/action", dependencies=[Depends(require_profile_update)])
def compliance_workflow_action(
    body: ComplianceWorkflowActionRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if str(body.action).strip().lower() in {"approved", "rejected"}:
        require_supervisor_approval(user)

    org_id = _resolve_org(user, organization_id)
    updated = ComplianceService.workflow_action(
        db,
        organization_id=org_id,
        actor=user,
        driver_id=body.driver_id,
        action=body.action,
        reason=body.reason,
        correlation_id=f"compliance-wf-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "profile": updated,
        "advisory_only": True,
        "execution_disabled": True,
        "supervision_required": True,
        "operator_approval_required": True,
    }


@router.post("/expiration-scan", dependencies=[Depends(require_profile_update)])
def compliance_expiration_scan(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    result = ComplianceService.expiration_scan(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"compliance-expiration-{uuid4().hex[:12]}",
    )
    return result


@router.post("/documents/evidence/append", dependencies=[Depends(require_profile_update)])
def append_document_evidence(
    body: ComplianceEvidenceAppendRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    evidence = ComplianceEvidenceService.append_document_evidence(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"compliance-evidence-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "evidence": evidence,
        "advisory_only": True,
        "execution_disabled": True,
        "append_only": True,
        "replay_safe": True,
    }


@router.post("/documents/signed-access/generate", dependencies=[Depends(require_profile_update)])
def generate_signed_access(
    body: ComplianceSignedAccessRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.generate_signed_access(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"compliance-signed-access-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@router.post("/documents/signed-access/retrieve", dependencies=[Depends(require_compliance_read)])
def retrieve_signed_document(
    body: ComplianceSignedAccessReadRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.retrieve_document(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(),
        correlation_id=f"compliance-retrieve-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@router.post("/documents/signed-access/revoke", dependencies=[Depends(require_profile_update)])
def revoke_signed_access(
    body: ComplianceSignedAccessRevokeRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.revoke_signed_access(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(),
        correlation_id=f"compliance-revoke-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@router.get("/documents/integrity", dependencies=[Depends(require_compliance_read)])
def verify_document_integrity(
    document_id: str = Query(...),
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.verify_integrity(
        db,
        organization_id=org_id,
        document_id=document_id,
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@router.post("/exports/generate", dependencies=[Depends(require_compliance_read)])
def generate_export_bundle(
    body: ComplianceExportRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.generate_export_bundle(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"compliance-export-{uuid4().hex[:12]}",
    )
    orchestration_bundle = OperationsOrchestrationService.export_orchestration_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"ops-export-integrated-{uuid4().hex[:12]}",
    )
    federation_bundle = OperationsOrchestrationService.export_federated_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"federation-export-integrated-{uuid4().hex[:12]}",
    )
    replay_bundle = OperationsOrchestrationService.export_replay_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"replay-export-integrated-{uuid4().hex[:12]}",
    )
    predictive_bundle = OperationsOrchestrationService.export_predictive_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=None,
        correlation_id=f"predictive-export-integrated-{uuid4().hex[:12]}",
    )
    governance_bundle = OperationsOrchestrationService.export_governance_provenance_bundle(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=None,
        correlation_id=f"governance-export-integrated-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "phase27_orchestration_evidence": orchestration_bundle,
        "phase28_federated_evidence": federation_bundle,
        "phase29_replay_evidence": replay_bundle,
        "phase30_predictive_evidence": predictive_bundle,
        "phase31_governance_provenance": governance_bundle,
        "phase32_governance_policy_evidence": governance_bundle,
        **payload,
    }


@router.post("/supervisor-handoff/transition", dependencies=[Depends(require_profile_update)])
def handoff_transition(
    body: ComplianceHandoffRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.handoff_transition(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"compliance-handoff-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@router.post("/retention/apply", dependencies=[Depends(require_profile_update)])
def apply_retention(
    body: ComplianceRetentionRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = ComplianceEvidenceService.apply_retention(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"compliance-retention-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@router.post("/policy-pack/evaluate", dependencies=[Depends(require_compliance_read)])
def evaluate_policy_pack(
    body: CompliancePolicyPackRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    policy = ComplianceEvidenceService.policy_pack(body.model_dump(exclude_none=True))
    return {
        "organization_id": org_id,
        "policy_pack": policy,
        "advisory_only": True,
        "execution_disabled": True,
        "operator_configurable": True,
    }


@orchestration_router.post("/task/create", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_task_create(
    body: OrchestrationTaskCreateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.create_task(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-create-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/assign", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_task_assign(
    body: OrchestrationTaskAssignRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.assign_task(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-assign-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/acknowledge", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_task_acknowledge(
    body: OrchestrationTaskAcknowledgeRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.acknowledge_task(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-ack-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/escalate", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_task_escalate(
    body: OrchestrationTaskEscalateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.escalate_task(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-escalate-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/handoff", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_task_handoff(
    body: OrchestrationTaskHandoffRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.handoff_task(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-handoff-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/notifications/append", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_append_notification(
    body: OrchestrationNotificationAppendRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.append_notification(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-notify-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/resolve", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_request_resolution(
    body: OrchestrationResolutionRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.request_resolution(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-resolve-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/approve-resolution", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_approve_resolution(
    body: OrchestrationResolutionApprovalRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.approve_resolution(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-approve-resolution-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.post("/task/reject-resolution", dependencies=[Depends(require_orchestration_mutation)])
def orchestration_reject_resolution(
    body: OrchestrationResolutionRejectRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.reject_resolution(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"ops-task-reject-resolution-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@orchestration_router.get("/queue", dependencies=[Depends(require_orchestration_read)])
def orchestration_queue(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_queue_snapshot(
        db,
        organization_id=org_id,
        actor=user,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/queue",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-queue-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@orchestration_router.get("/timeline", dependencies=[Depends(require_orchestration_read)])
def orchestration_timeline(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_timeline_projection(
        db,
        organization_id=org_id,
        actor=user,
        after_sequence=after_sequence,
        limit=limit,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/timeline",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-timeline-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@orchestration_router.get("/notifications", dependencies=[Depends(require_orchestration_read)])
def orchestration_notifications(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.notification_feed(
        db,
        organization_id=org_id,
        actor=user,
        limit=limit,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/notifications",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-notifications-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@orchestration_router.get("/live-stream", dependencies=[Depends(require_orchestration_read)])
def orchestration_live_stream(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_live_projection(
        db,
        organization_id=org_id,
        actor=user,
        after_sequence=after_sequence,
        limit=limit,
        correlation_id=f"ops-live-stream-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/live-stream",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-live-stream-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@orchestration_router.get("/sla", dependencies=[Depends(require_orchestration_read)])
def orchestration_sla_snapshot(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_sla_snapshot(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"ops-sla-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/sla",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-sla-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@orchestration_router.get("/queue-health", dependencies=[Depends(require_orchestration_read)])
def orchestration_queue_health(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_queue_health_metrics(
        db,
        organization_id=org_id,
        actor=user,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/queue-health",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-queue-health-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@orchestration_router.get("/export-bundle", dependencies=[Depends(require_orchestration_read)])
def orchestration_export_bundle(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_orchestration_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"ops-export-bundle-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/orchestration/export-bundle",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"ops-export-bundle-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@federation_router.post("/register-region", dependencies=[Depends(require_orchestration_mutation)])
def federation_register_region(
    body: FederationRegisterRegionRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.register_region(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"federation-register-region-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@federation_router.post("/handoff/create", dependencies=[Depends(require_orchestration_mutation)])
def federation_create_handoff(
    body: FederationCrossRegionHandoffRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.create_cross_region_handoff(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"federation-handoff-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        **payload,
    }


@federation_router.get("/queues", dependencies=[Depends(require_orchestration_read)])
def federation_queues(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_cross_region_queue_snapshot(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"federation-queues-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/federation/queues",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"federation-queues-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@federation_router.get("/regions", dependencies=[Depends(require_orchestration_read)])
def federation_regions(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.list_regions(
        db,
        organization_id=org_id,
        actor=user,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/federation/regions",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"federation-regions-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@federation_router.get("/capacity", dependencies=[Depends(require_orchestration_read)])
def federation_capacity(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_capacity_forecast(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"federation-capacity-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/federation/capacity",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"federation-capacity-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@federation_router.get("/continuity", dependencies=[Depends(require_orchestration_read)])
def federation_continuity(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_continuity_projection(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"federation-continuity-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/federation/continuity",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"federation-continuity-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@federation_router.get("/health", dependencies=[Depends(require_orchestration_read)])
def federation_health(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.build_regional_health_summary(
        db,
        organization_id=org_id,
        actor=user,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/federation/health",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"federation-health-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@federation_router.get("/export-bundle", dependencies=[Depends(require_orchestration_read)])
def federation_export_bundle(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_federated_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"federation-export-bundle-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/federation/export-bundle",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"federation-export-bundle-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.post("/session/create", dependencies=[Depends(require_orchestration_mutation)])
def replay_create_session(
    body: ReplaySessionCreateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.create_replay_session(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"replay-session-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/session/create",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-session-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.post("/scenario/create", dependencies=[Depends(require_orchestration_mutation)])
def replay_create_scenario(
    body: ReplayScenarioCreateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.create_simulation_scenario(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"replay-scenario-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/scenario/create",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-scenario-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.post("/branch/generate", dependencies=[Depends(require_orchestration_mutation)])
def replay_generate_branch(
    body: ReplayBranchGenerateRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_timeline_branch(
        db,
        organization_id=org_id,
        actor=user,
        payload=body.model_dump(exclude_none=True),
        correlation_id=f"replay-branch-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/branch/generate",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-branch-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.get("/timeline", dependencies=[Depends(require_orchestration_read)])
def replay_timeline(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.reconstruct_operational_timeline(
        db,
        organization_id=org_id,
        actor=user,
        after_sequence=after_sequence,
        limit=limit,
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/timeline",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-timeline-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.get("/projection", dependencies=[Depends(require_orchestration_read)])
def replay_projection(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=500),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_replay_projection(
        db,
        organization_id=org_id,
        actor=user,
        after_sequence=after_sequence,
        limit=limit,
        replay_session_id=replay_session_id,
        correlation_id=f"replay-projection-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/projection",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-projection-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.get("/comparison", dependencies=[Depends(require_orchestration_read)])
def replay_comparison(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.compare_forecast_outcomes(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"replay-comparison-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/comparison",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-comparison-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.get("/continuity", dependencies=[Depends(require_orchestration_read)])
def replay_continuity(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_continuity_simulation(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"replay-continuity-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/continuity",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-continuity-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.get("/evidence", dependencies=[Depends(require_orchestration_read)])
def replay_evidence(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_replay_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"replay-evidence-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/evidence",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-evidence-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@replay_router.get("/export-bundle", dependencies=[Depends(require_orchestration_read)])
def replay_export_bundle(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_replay_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"replay-export-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/replay/export-bundle",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"replay-export-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.post("/governance", dependencies=[Depends(require_orchestration_mutation)])
def predictive_governance(
    body: PredictiveGovernanceRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_governance_prediction(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        prediction_scope=str(body.prediction_scope or "governance").strip(),
        correlation_id=f"predictive-governance-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/governance",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-governance-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.post("/constraints", dependencies=[Depends(require_orchestration_mutation)])
def predictive_constraints(
    body: PredictiveConstraintRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.analyze_operational_constraints(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        constraint_domain=str(body.constraint_domain or "operational_constraints").strip(),
        correlation_id=f"predictive-constraints-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/constraints",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-constraints-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.post("/capacity", dependencies=[Depends(require_orchestration_mutation)])
def predictive_capacity(
    body: PredictiveCapacityRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_capacity_prediction(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        capacity_scope=str(body.capacity_scope or "capacity_pressure").strip(),
        correlation_id=f"predictive-capacity-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/capacity",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-capacity-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.post("/risk", dependencies=[Depends(require_orchestration_mutation)])
def predictive_risk(
    body: PredictiveRiskRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_risk_projection(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        risk_domain=str(body.risk_domain or "governance_risk").strip(),
        correlation_id=f"predictive-risk-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/risk",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-risk-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.post("/anomaly", dependencies=[Depends(require_orchestration_mutation)])
def predictive_anomaly(
    body: PredictiveAnomalyRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_anomaly_forecast(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        anomaly_scope=str(body.anomaly_scope or "operational_anomaly").strip(),
        correlation_id=f"predictive-anomaly-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/anomaly",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-anomaly-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.get("/drift", dependencies=[Depends(require_orchestration_read)])
def predictive_drift(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.detect_governance_drift(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"predictive-drift-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/drift",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-drift-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.get("/recommendations", dependencies=[Depends(require_orchestration_read)])
def predictive_recommendations(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_optimization_recommendations(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"predictive-recommendations-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/recommendations",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-recommendations-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.get("/trends", dependencies=[Depends(require_orchestration_read)])
def predictive_trends(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_governance_trend_analysis(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"predictive-trends-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/trends",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-trends-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.get("/evidence", dependencies=[Depends(require_orchestration_read)])
def predictive_evidence(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_predictive_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"predictive-evidence-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/evidence",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-evidence-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@predictive_router.get("/export-bundle", dependencies=[Depends(require_orchestration_read)])
def predictive_export_bundle(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_predictive_evidence_bundle(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"predictive-export-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/predictive/export-bundle",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"predictive-export-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.post("/provenance", dependencies=[Depends(require_orchestration_mutation)])
def governance_provenance(
    body: GovernanceProvenanceRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.build_decision_provenance(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        decision_scope=str(body.decision_scope or "governance_decision").strip(),
        correlation_id=f"governance-provenance-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/provenance",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-provenance-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.post("/explanations", dependencies=[Depends(require_orchestration_mutation)])
def governance_explanations(
    body: GovernanceExplanationRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_governance_explanation(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        explanation_scope=str(body.explanation_scope or "governance_explanation").strip(),
        correlation_id=f"governance-explanations-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/explanations",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-explanations-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.post("/reasoning", dependencies=[Depends(require_orchestration_mutation)])
def governance_reasoning(
    body: GovernanceReasoningRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.reconstruct_reasoning_chain(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        reasoning_scope=str(body.reasoning_scope or "advisory_reasoning").strip(),
        correlation_id=f"governance-reasoning-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/reasoning",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-reasoning-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.post("/memory", dependencies=[Depends(require_orchestration_mutation)])
def governance_memory(
    body: GovernanceMemoryRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    memory_payload = OperationsOrchestrationService.generate_operational_memory_snapshot(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        scenario_id=body.scenario_id,
        memory_window=str(body.memory_window or "long_horizon").strip(),
        correlation_id=f"governance-memory-{uuid4().hex[:12]}",
    )
    trend_payload = OperationsOrchestrationService.aggregate_long_horizon_trends(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        trend_window=str(body.trend_window or "long_horizon").strip(),
        correlation_id=f"governance-memory-trends-{uuid4().hex[:12]}",
    )
    context_payload = OperationsOrchestrationService.reconstruct_decision_context(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        decision_scope="governance_memory_context",
        correlation_id=f"governance-memory-context-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/memory",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-memory-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        "memory": memory_payload,
        "trends": trend_payload,
        "decision_context": context_payload,
        "advisory_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "append_only": True,
        "replay_safe": True,
    }


@governance_router.get("/ancestry", dependencies=[Depends(require_orchestration_read)])
def governance_ancestry(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_historical_governance_trace(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"governance-ancestry-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/ancestry",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-ancestry-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.get("/lineage", dependencies=[Depends(require_orchestration_read)])
def governance_lineage(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.build_recommendation_lineage(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"governance-lineage-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/lineage",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-lineage-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.get("/history", dependencies=[Depends(require_orchestration_read)])
def governance_history(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_operational_memory_snapshot(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        scenario_id=None,
        memory_window="historical_reconstruction",
        correlation_id=f"governance-history-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/history",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-history-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.get("/trends", dependencies=[Depends(require_orchestration_read)])
def governance_trends(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.aggregate_long_horizon_trends(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        trend_window="long_horizon",
        correlation_id=f"governance-trends-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/trends",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-trends-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }


@governance_router.post("/policy/matrix", dependencies=[Depends(require_orchestration_mutation)])
def governance_policy_matrix(
    body: GovernancePolicyRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.generate_policy_matrix(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        correlation_id=f"governance-policy-matrix-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.post("/framework/map", dependencies=[Depends(require_orchestration_mutation)])
def governance_framework_map(
    body: GovernancePolicyRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.map_regulatory_frameworks(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        correlation_id=f"governance-framework-map-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.post("/policy/evaluate", dependencies=[Depends(require_orchestration_mutation)])
def governance_policy_evaluate(
    body: GovernancePolicyRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.evaluate_policy_constraints(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        correlation_id=f"governance-policy-evaluate-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.post("/policy/score", dependencies=[Depends(require_orchestration_mutation)])
def governance_policy_score(
    body: GovernancePolicyRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.calculate_weighted_governance_score(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        policy_scope=str(body.policy_scope or "governance_policy_constraints").strip(),
        correlation_id=f"governance-policy-score-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.post("/rationale/build", dependencies=[Depends(require_orchestration_mutation)])
def governance_rationale_build(
    body: GovernanceRationaleChainRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.build_rationale_chain(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        decision_id=body.decision_id,
        correlation_id=f"governance-rationale-build-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.post("/risk/evaluate", dependencies=[Depends(require_orchestration_mutation)])
def governance_risk_evaluate(
    body: GovernanceRiskRequest,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.evaluate_operational_risk(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=body.replay_session_id,
        correlation_id=f"governance-risk-evaluate-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.get("/policy/history", dependencies=[Depends(require_orchestration_read)])
def governance_policy_history(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    eval_query = db.query(OperationsConstraintEvaluation).filter(OperationsConstraintEvaluation.organization_id == org_id)
    score_query = db.query(OperationsPolicyScoreSnapshot).filter(OperationsPolicyScoreSnapshot.organization_id == org_id)
    if replay_session_id is not None:
        eval_query = eval_query.filter(OperationsConstraintEvaluation.replay_session_id == replay_session_id)
        score_query = score_query.filter(OperationsPolicyScoreSnapshot.replay_session_id == replay_session_id)
    evaluations = eval_query.order_by(OperationsConstraintEvaluation.created_at.asc(), OperationsConstraintEvaluation.sequence.asc()).all()
    scores = score_query.order_by(OperationsPolicyScoreSnapshot.created_at.asc(), OperationsPolicyScoreSnapshot.sequence.asc()).all()
    return {
        "organization_id": org_id,
        "constraint_history": [
            {
                "constraint_evaluation_event_id": row.constraint_evaluation_event_id,
                "policy_id": row.policy_id,
                "framework_name": row.framework_name,
                "rule_code": row.rule_code,
                "evaluation_score": row.evaluation_score,
                "evaluation_status": row.evaluation_status,
            }
            for row in evaluations
        ],
        "score_history": [
            {
                "policy_score_event_id": row.policy_score_event_id,
                "policy_scope": row.policy_scope,
                "weighted_score": row.weighted_score,
                "score_status": row.score_status,
            }
            for row in scores
        ],
        "advisory_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "append_only": True,
        "replay_safe": True,
    }


@governance_router.get("/policy/lineage", dependencies=[Depends(require_orchestration_read)])
def governance_policy_lineage(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.trace_policy_lineage(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"governance-policy-lineage-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.get("/rationale/{decision_id}", dependencies=[Depends(require_orchestration_read)])
def governance_rationale_detail(
    decision_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.reconstruct_governance_decision(
        db,
        organization_id=org_id,
        actor=user,
        decision_id=decision_id,
        correlation_id=f"governance-rationale-detail-{uuid4().hex[:12]}",
    )
    return {"organization_id": org_id, **payload}


@governance_router.get("/frameworks", dependencies=[Depends(require_orchestration_read)])
def governance_frameworks(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    constraints = OperationsOrchestrationService._normalize_constraint_weights(
        OperationsOrchestrationService._policy_constraint_catalog()
    )
    return {
        "organization_id": org_id,
        "frameworks": OperationsOrchestrationService._collect_framework_mappings(constraints),
        "advisory_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "append_only": True,
        "replay_safe": True,
    }


@governance_router.get("/constraints", dependencies=[Depends(require_orchestration_read)])
def governance_constraints(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    return {
        "organization_id": org_id,
        "constraints": OperationsOrchestrationService._normalize_constraint_weights(
            OperationsOrchestrationService._policy_constraint_catalog()
        ),
        "advisory_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "append_only": True,
        "replay_safe": True,
    }


@governance_router.get("/violations", dependencies=[Depends(require_orchestration_read)])
def governance_violations(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    query = db.query(OperationsConstraintViolation).filter(OperationsConstraintViolation.organization_id == org_id)
    if replay_session_id is not None:
        query = query.filter(OperationsConstraintViolation.replay_session_id == replay_session_id)
    violations = query.order_by(OperationsConstraintViolation.created_at.asc(), OperationsConstraintViolation.sequence.asc()).all()
    return {
        "organization_id": org_id,
        "violations": [
            {
                "constraint_violation_event_id": row.constraint_violation_event_id,
                "policy_id": row.policy_id,
                "framework_name": row.framework_name,
                "rule_code": row.rule_code,
                "violation_level": row.violation_level,
                "severity_weight": row.severity_weight,
            }
            for row in violations
        ],
        "advisory_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "append_only": True,
        "replay_safe": True,
    }


@governance_router.get("/score/{session_id}", dependencies=[Depends(require_orchestration_read)])
def governance_score_for_session(
    session_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    row = db.query(OperationsPolicyScoreSnapshot).filter(
        OperationsPolicyScoreSnapshot.organization_id == org_id,
        OperationsPolicyScoreSnapshot.replay_session_id == session_id,
    ).order_by(OperationsPolicyScoreSnapshot.created_at.desc(), OperationsPolicyScoreSnapshot.sequence.desc()).first()
    if row is None:
        return {
            "organization_id": org_id,
            **OperationsOrchestrationService.calculate_weighted_governance_score(
                db,
                organization_id=org_id,
                actor=user,
                replay_session_id=session_id,
                policy_scope="governance_policy_constraints",
                correlation_id=f"governance-score-session-{uuid4().hex[:12]}",
            ),
        }
    return {
        "organization_id": org_id,
        "policy_score_event_id": row.policy_score_event_id,
        "policy_scope": row.policy_scope,
        "weighted_score": row.weighted_score,
        "score_status": row.score_status,
        "score_snapshot": row.score_payload_json and __import__("json").loads(row.score_payload_json),
        "advisory_only": True,
        "execution_disabled": True,
        "autonomous_execution": False,
        "append_only": True,
        "replay_safe": True,
    }


@governance_router.get("/export-bundle", dependencies=[Depends(require_orchestration_read)])
def governance_export_bundle(
    organization_id: str | None = Query(None),
    replay_session_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    payload = OperationsOrchestrationService.export_governance_provenance_bundle(
        db,
        organization_id=org_id,
        actor=user,
        replay_session_id=replay_session_id,
        correlation_id=f"governance-export-{uuid4().hex[:12]}",
    )
    return {
        "organization_id": org_id,
        "audit_metadata": {
            "endpoint": "/api/ops/governance/export-bundle",
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": f"governance-export-meta-{uuid4().hex[:12]}",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        },
        **payload,
    }
