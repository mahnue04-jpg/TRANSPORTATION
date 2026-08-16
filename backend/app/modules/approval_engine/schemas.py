"""API schemas for the AI Approval Engine."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ApprovalCaseCreateRequest(BaseModel):
    platform_ops_application_id: str
    display_badge: str | None = None
    requested_service_tiers: list[str] = Field(default_factory=lambda: ["BASE_PRIVATE_AMBULATORY"])
    run_ai_review: bool = True


class OwnerDecisionRequest(BaseModel):
    decision: Literal["APPROVE", "REJECT", "RETURN_FOR_CORRECTION"]
    reason: str | None = None


class HumanOverrideRequest(BaseModel):
    to_status: str
    reason: str
    lawful_exception_ref: str | None = None


class RequirementUpdateRequest(BaseModel):
    status: str
    evidence_ref: str | None = None
    traffic_light: str | None = None
    expiration_date: date | None = None
    external_result: bool = False


class ExternalVerificationSubmitRequest(BaseModel):
    notes: str | None = None
    provider_reference_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExternalVerificationRecordRequest(BaseModel):
    status: Literal[
        "NOT_STARTED",
        "ACTION_REQUIRED",
        "SUBMITTED",
        "PENDING_EXTERNAL",
        "VERIFIED",
        "CLEARED",
        "FAILED",
        "DISQUALIFIED",
        "EXPIRED",
        "MANUAL_REVIEW",
    ]
    evidence_source: str | None = None
    provider_key: str | None = None
    provider_reference_id: str | None = None
    verification_date: date | None = None
    expiration_date: date | None = None
    notes: str | None = None
    actor_type: Literal["USER", "EXTERNAL", "SYSTEM"] = "EXTERNAL"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TrainingUpdateRequest(BaseModel):
    status: Literal["assigned", "in_progress", "completed", "failed", "expired", "retraining_required"]
    evidence_ref: str | None = None
    expires_at: date | None = None
    module_version: str | None = None
    assigned_at: datetime | None = None
    completed_at: datetime | None = None


class InsuranceReviewRequest(BaseModel):
    carrier: str | None = None
    policy_reference: str | None = None
    effective_date: date | None = None
    expiration_date: date | None = None
    vehicle_association: str | None = None
    review_status: Literal["pending", "accepted", "rejected", "expired", "correction_requested"] = "pending"
    notes: str | None = None
    evidence_ref: str | None = None


class AgreementRecordRequest(BaseModel):
    version: str
    status: Literal["pending", "accepted", "signed", "returned", "expired"] = "accepted"
    accepted_at: datetime | None = None
    evidence_document_id: str | None = None
    notes: str | None = None


class W9WorkflowRequest(BaseModel):
    status: Literal["requested", "pending", "completed", "externally_verified"]
    external_provider: str | None = None
    external_reference: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VehicleRecordRequest(BaseModel):
    make: str | None = None
    model: str | None = None
    year: int | None = Field(default=None, ge=1980, le=2100)
    license_plate: str | None = None
    registration_expiration: date | None = None
    inspection_status: str | None = None
    inspection_expiration: date | None = None
    insurance_association_ref: str | None = None
    insurance_expiration: date | None = None
    eligibility_status: Literal["PENDING", "REVIEWED", "ELIGIBLE_NOT_ACTIVE", "BLOCKED", "EXPIRED"] = "PENDING"
    health_isf_vehicle_id: str | None = None
    notes: str | None = None


class ActivateRequest(BaseModel):
    health_isf_driver_id: str | None = None


class AssistantQueryRequest(BaseModel):
    query: str
    ride_id: str | None = None


class Driver001PrepareRequest(BaseModel):
    legal_first_name: str | None = None
    legal_last_name: str | None = None
    email: str | None = None
    mobile_phone: str | None = None
    reuse_existing: bool = True


class ApprovalCaseResponse(BaseModel):
    id: str
    organization_id: str
    display_badge: str | None = None
    legal_name: str | None = None
    workflow_status: str
    activation_status: str
    readiness_percentage: float
    compliance_score: float
    ai_summary: str | None = None
    next_required_action: str | None = None
    requested_service_tiers: list[str] = Field(default_factory=list)
    approved_service_tiers: list[str] = Field(default_factory=list)
    fingerprint_status: str
    owner_approval_status: str
    owner_approval_timestamp: datetime | None = None
    approval_actor_id: str | None = None
    platform_ops_application_id: str | None = None
    health_isf_driver_id: str | None = None
    last_ai_review_at: datetime | None = None
    requirements: list[dict[str, Any]] = Field(default_factory=list)
    external_tasks: list[dict[str, Any]] = Field(default_factory=list)
    training_modules: list[dict[str, Any]] = Field(default_factory=list)
    approval_card: dict[str, Any] | None = None
