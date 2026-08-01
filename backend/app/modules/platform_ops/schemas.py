"""Pydantic schemas for driver onboarding API."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


EmploymentType = Literal["independent_contractor", "employee"]


class DriverApplicationDraftRequest(BaseModel):
    organization_id: str
    legal_first_name: str | None = None
    legal_middle_name: str | None = None
    legal_last_name: str | None = None
    date_of_birth: date | None = None
    email: str | None = None
    mobile_phone: str | None = None
    home_address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    preferred_language: str | None = None
    drivers_license_number: str | None = None
    license_issuing_state: str | None = None
    license_expiration_date: date | None = None
    years_driving_experience: int | None = Field(default=None, ge=0, le=80)
    employment_type: EmploymentType | None = None
    availability_days: list[str] | None = None
    availability_start_time: str | None = None
    availability_end_time: str | None = None
    willing_weekends: bool | None = None
    willing_wheelchair: bool | None = None
    service_area_counties: str | None = None
    declaration_valid_license: bool = False
    declaration_mvr_authorization: bool = False
    declaration_background_authorization: bool = False
    declaration_drug_alcohol_policy: bool = False
    declaration_truthful_information: bool = False
    electronic_signature: str | None = None
    signed_date: date | None = None


class DriverApplicationSubmitRequest(BaseModel):
    confirmation: bool = True


class DriverApplicationStatusTransitionRequest(BaseModel):
    to_status: str
    reason: str | None = None
    assigned_reviewer_id: str | None = None
    confirm: bool = False


class DriverApplicationDecisionRequest(BaseModel):
    reason: str | None = None
    confirm: bool = False


class DriverApplicationAssignReviewerRequest(BaseModel):
    assigned_reviewer_id: str


class DriverApplicationInternalNoteRequest(BaseModel):
    note_text: str = Field(min_length=1, max_length=4000)


class DocumentReviewRequest(BaseModel):
    review_status: Literal["accepted", "rejected", "correction_requested"]
    review_reason: str | None = None
    expires_at: date | None = None


class DocumentStatusOnlyRequest(BaseModel):
    category: str
    status_only_value: Literal["missing", "provided", "verified", "signed"]


class DocumentMetadataResponse(BaseModel):
    id: str
    category: str
    review_status: str
    review_reason: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    expires_at: date | None = None
    status_only_value: str | None = None
    original_filename: str | None = None
    content_type: str | None = None
    byte_size: int | None = None
    storage_backend: str
    created_at: datetime
    updated_at: datetime


class ReadinessSummaryResponse(BaseModel):
    indicators: dict[str, bool]
    document_completion_percentage: float
    missing_documents: list[str]
    compliance_warnings: list[str]
    advisory_only: bool = True


class DriverApplicationListItemResponse(BaseModel):
    id: str
    organization_id: str
    status: str
    applicant_name: str | None = None
    application_date: datetime | None = None
    email: str | None = None
    mobile_phone: str | None = None
    license_expiration_date: date | None = None
    document_completion_percentage: float = 0.0
    missing_documents: list[str] = Field(default_factory=list)
    compliance_warnings: list[str] = Field(default_factory=list)
    assigned_reviewer_id: str | None = None


class DriverApplicationDetailResponse(BaseModel):
    id: str
    organization_id: str
    status: str
    status_reason: str | None = None
    legal_first_name: str | None = None
    legal_middle_name: str | None = None
    legal_last_name: str | None = None
    date_of_birth: date | None = None
    email: str | None = None
    mobile_phone: str | None = None
    home_address: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None
    preferred_language: str | None = None
    drivers_license_number_masked: str | None = None
    license_issuing_state: str | None = None
    license_expiration_date: date | None = None
    years_driving_experience: int | None = None
    employment_type: str | None = None
    availability_days: list[str] = Field(default_factory=list)
    availability_start_time: str | None = None
    availability_end_time: str | None = None
    willing_weekends: bool | None = None
    willing_wheelchair: bool | None = None
    service_area_counties: str | None = None
    declaration_valid_license: bool = False
    declaration_mvr_authorization: bool = False
    declaration_background_authorization: bool = False
    declaration_drug_alcohol_policy: bool = False
    declaration_truthful_information: bool = False
    electronic_signature: str | None = None
    signed_date: date | None = None
    assigned_reviewer_id: str | None = None
    reviewed_at: datetime | None = None
    approved_at: datetime | None = None
    activated_at: datetime | None = None
    rejected_at: datetime | None = None
    suspended_at: datetime | None = None
    rejection_reason: str | None = None
    suspension_reason: str | None = None
    activated_driver_id: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentMetadataResponse] = Field(default_factory=list)
    readiness: ReadinessSummaryResponse | None = None
    allowed_next_statuses: list[str] = Field(default_factory=list)


class DriverApplicationCreateResponse(BaseModel):
    application: DriverApplicationDetailResponse
    applicant_access_token: str


class AuditEventResponse(BaseModel):
    id: str
    event_type: str
    from_status: str | None = None
    to_status: str | None = None
    actor_user_id: str | None = None
    actor_role: str | None = None
    reason: str | None = None
    metadata_json: str | None = None
    created_at: datetime


class ActivationResponse(BaseModel):
    application_id: str
    driver_id: str
    driver_status: str
    idempotent: bool = False
    readiness: ReadinessSummaryResponse


class DocumentCategoryInfo(BaseModel):
    category: str
    label: str
    requires_upload: bool
    sensitive: bool


class ValidationErrorItem(BaseModel):
    field: str
    message: str


class ValidationErrorResponse(BaseModel):
    detail: str
    errors: list[ValidationErrorItem]
