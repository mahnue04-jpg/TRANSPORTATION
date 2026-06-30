"""
Pydantic schemas for Health ISF API requests/responses.
MVP scope: simple validated schemas, no advanced validation.
"""
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Optional, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from app.modules.health_isf.models import RideStatus
from app.modules.health_isf.service_categories import serialize_service_category


PHONE_RE = re.compile(r"^\+?[0-9()\-\s]{7,20}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def _sanitize_text(value: str | None, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = CONTROL_RE.sub("", str(value)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if max_len is not None:
        cleaned = cleaned[:max_len]
    return cleaned or None


# ── Provider Schemas ──────────────────────────────────────────────────────────

class ProviderBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    address: str = Field(..., min_length=1, max_length=512)
    phone: str = Field(..., min_length=1, max_length=20)
    service_type: str = Field(..., min_length=1, max_length=128)


class ProviderCreate(ProviderBase):
    pass


class ProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    address: Optional[str] = Field(None, min_length=1, max_length=512)
    phone: Optional[str] = Field(None, min_length=1, max_length=20)
    service_type: Optional[str] = Field(None, min_length=1, max_length=128)
    is_active: Optional[bool] = None


class ProviderResponse(ProviderBase):
    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Driver Schemas ────────────────────────────────────────────────────────────

class DriverBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=256)
    phone: str = Field(..., min_length=1, max_length=20)
    vehicle_type: str = Field(..., min_length=1, max_length=128)
    vehicle_plate: str = Field(..., min_length=1, max_length=50)


class DriverCreate(DriverBase):
    pass


class DriverUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=256)
    phone: Optional[str] = Field(None, min_length=1, max_length=20)
    status: Optional[str] = Field(None, min_length=1, max_length=32)
    is_active: Optional[bool] = None
    rating: Optional[float] = Field(None, ge=0.0, le=5.0)


class DriverStatusUpdateRequest(BaseModel):
    status: str = Field(..., min_length=1, max_length=32)


class DriverRideActionRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    note: Optional[str] = Field(None, max_length=1024)


class DriverContactRiderRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    channel: str = Field("sms", min_length=1, max_length=16)
    message: Optional[str] = Field(None, max_length=512)


class DriverContactRiderResponse(BaseModel):
    ok: bool = True
    channel: str
    provider: Optional[str] = None
    reference: Optional[str] = None
    dial_target: Optional[str] = None
    message: Optional[str] = None


class DriverResponse(DriverBase):
    id: str
    status: str
    is_active: bool
    total_trips: int
    rating: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VehicleCreate(BaseModel):
    vehicle_type: str = Field(..., min_length=1, max_length=128)
    vehicle_plate: str = Field(..., min_length=1, max_length=50)
    capacity: int = Field(4, ge=1, le=32)


class VehicleResponse(BaseModel):
    id: str
    organization_id: str
    vehicle_type: str
    vehicle_plate: str
    capacity: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DriverApplicationCreateRequest(BaseModel):
    applicant_name: str = Field(..., min_length=1, max_length=256)
    applicant_phone: str = Field(..., min_length=1, max_length=20)
    applicant_email: Optional[str] = Field(None, max_length=256)
    license_number: Optional[str] = Field(None, max_length=64)
    insurance_policy_number: Optional[str] = Field(None, max_length=64)
    vehicle_make: Optional[str] = Field(None, max_length=128)
    vehicle_model: Optional[str] = Field(None, max_length=128)
    vehicle_year: Optional[int] = Field(None, ge=1980, le=2100)
    vehicle_plate: Optional[str] = Field(None, max_length=50)
    vehicle_color: Optional[str] = Field(None, max_length=64)
    availability_summary: Optional[str] = Field(None, max_length=256)
    availability: Optional[dict[str, Any]] = None
    preferred_service_categories: Optional[list[str]] = None
    background_check_authorized: bool = False
    license_document_ref: Optional[str] = Field(None, max_length=256)
    insurance_document_ref: Optional[str] = Field(None, max_length=256)
    registration_document_ref: Optional[str] = Field(None, max_length=256)
    notes: Optional[str] = Field(None, max_length=2000)


class DriverApplicationStatusUpdateRequest(BaseModel):
    onboarding_status: Literal["applied", "pending_review", "approved", "active", "suspended"]
    review_notes: Optional[str] = Field(None, max_length=2000)


class DriverApplicationResponse(BaseModel):
    id: str
    organization_id: str
    applicant_name: str
    applicant_phone: str
    applicant_email: Optional[str] = None
    license_number: Optional[str] = None
    insurance_policy_number: Optional[str] = None
    vehicle_make: Optional[str] = None
    vehicle_model: Optional[str] = None
    vehicle_year: Optional[int] = None
    vehicle_plate: Optional[str] = None
    vehicle_color: Optional[str] = None
    availability_summary: Optional[str] = None
    availability: Optional[dict[str, Any]] = None
    preferred_service_categories: list[str] = Field(default_factory=list)
    background_check_authorized: bool = False
    license_document_ref: Optional[str] = None
    insurance_document_ref: Optional[str] = None
    registration_document_ref: Optional[str] = None
    onboarding_status: str
    review_notes: Optional[str] = None
    reviewed_by_user_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class RecurringRideTemplateResponse(BaseModel):
    template_id: str
    rider_name: str
    service_type: str
    category: str
    pickup_address: str
    dropoff_address: str
    preferred_pickup_time: Optional[str] = None
    recurrence: dict[str, Any] = Field(default_factory=dict)
    preferred_driver_id: Optional[str] = None
    preferred_driver_name: Optional[str] = None
    next_scheduled_at: Optional[str] = None
    last_status: str


class RecurringScheduleCreateRequest(BaseModel):
    provider_id: str = Field(..., min_length=1, max_length=36)
    passenger_name: str = Field(..., min_length=1, max_length=256)
    passenger_phone: str = Field(..., min_length=1, max_length=20)
    pickup_address: str = Field(..., min_length=1, max_length=512)
    dropoff_address: str = Field(..., min_length=1, max_length=512)
    service_type: str = Field(..., min_length=1, max_length=128)
    start_date: datetime
    end_date: Optional[datetime] = None
    frequency: Literal["daily", "weekly", "monthly", "custom"]
    interval_count: int = Field(1, ge=1, le=365)
    weekdays: list[str] = Field(default_factory=list)
    pickup_time_local: str = Field(..., min_length=4, max_length=8)
    horizon_days: int = Field(30, ge=1, le=180)


class RecurringScheduleStatusUpdateRequest(BaseModel):
    is_active: bool
    horizon_days: int = Field(30, ge=1, le=180)


class RecurringScheduleResponse(BaseModel):
    id: str
    organization_id: str
    provider_id: Optional[str] = None
    passenger_name: str
    passenger_phone: str
    pickup_address: str
    dropoff_address: str
    service_type: str
    pickup_time_local: str
    frequency: str
    interval_count: int
    weekdays: list[int] = Field(default_factory=list)
    start_date: datetime
    end_date: Optional[datetime] = None
    is_active: bool
    last_generated_at: Optional[datetime] = None
    generated_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    generated_ride_count: int = 0


class GrantProofSnapshotResponse(BaseModel):
    generated_at: str
    transportation_mvp_status: str
    onboarding_mvp_status: str
    recurring_mvp_status: str
    dashboard_mvp_status: str
    screenshot_inventory: list[dict[str, str]]
    metrics: dict[str, Any]
    sample_entities: dict[str, Any]


class CustomerRideRequestCreateRequest(BaseModel):
    pickup_address: str = Field(..., min_length=1, max_length=512)
    dropoff_address: str = Field(..., min_length=1, max_length=512)
    rider_name: str = Field(..., min_length=1, max_length=256)
    rider_phone: str = Field(..., min_length=1, max_length=20)
    scheduled_time: Optional[datetime] = None
    ride_type: Literal["healthcare", "work", "grocery", "church", "personal"] = "healthcare"
    recurring: bool = False
    recurring_pattern: Optional[dict[str, Any]] = None
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("pickup_address", "dropoff_address", "rider_name", mode="before")
    @classmethod
    def sanitize_customer_text(cls, value: Any) -> str:
        cleaned = _sanitize_text(str(value or ""))
        if not cleaned:
            raise ValueError("Field is required")
        return cleaned

    @field_validator("rider_phone")
    @classmethod
    def validate_customer_phone(cls, value: str) -> str:
        phone = _sanitize_text(value, max_len=20) or ""
        if not PHONE_RE.match(phone):
            raise ValueError("rider_phone must be a valid phone number")
        return phone

    @field_validator("notes", mode="before")
    @classmethod
    def sanitize_customer_notes(cls, value: Any) -> Optional[str]:
        return _sanitize_text(value, max_len=1000)

    @model_validator(mode="after")
    def validate_request_contract(self) -> "CustomerRideRequestCreateRequest":
        pickup = (self.pickup_address or "").strip().lower()
        dropoff = (self.dropoff_address or "").strip().lower()
        if pickup and dropoff and pickup == dropoff:
            raise ValueError("pickup_address and dropoff_address must be different")

        if self.scheduled_time is not None:
            scheduled = self.scheduled_time
            if scheduled.tzinfo is None:
                scheduled = scheduled.replace(tzinfo=datetime.now(timezone.utc).tzinfo)
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
            if scheduled < cutoff:
                raise ValueError("scheduled_time cannot be in the past")
        return self


class CustomerRideRequestStatusUpdateRequest(BaseModel):
    dispatch_status: Literal["pending", "approved", "dispatchable", "broadcasted", "accepted", "assigned", "in_progress", "completed", "cancelled"]


class CustomerRideRequestResponse(BaseModel):
    id: str
    organization_id: str
    ride_id: str
    rider_name: str
    rider_phone: str
    pickup_address: str
    dropoff_address: str
    scheduled_time: Optional[datetime] = None
    ride_type: str
    recurring: bool
    recurring_pattern: Optional[dict[str, Any]] = None
    notes: Optional[str] = None
    dispatch_status: str
    pending_at: datetime
    broadcasted_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    in_progress_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cancelled_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class CustomerRideQueueMetricsResponse(BaseModel):
    pending: int
    approved: int
    dispatchable: int
    broadcasted: int
    accepted: int
    assigned: int
    in_progress: int
    completed: int
    cancelled: int
    total: int


class DriverLoginRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)
    phone: str = Field(..., min_length=1, max_length=20)

    @field_validator("phone")
    @classmethod
    def validate_login_phone(cls, value: str) -> str:
        phone = _sanitize_text(value, max_len=20) or ""
        if not PHONE_RE.match(phone):
            raise ValueError("phone must be a valid phone number")
        return phone


class DriverLoginResponse(BaseModel):
    driver_id: str
    organization_id: str
    session_token: str
    session_state: str
    auth_state: str
    availability_state: str
    is_online: bool
    issued_at: datetime
    expires_at: datetime


class DriverLogoutRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)
    session_token: str = Field(..., min_length=8, max_length=512)


class DriverAvailabilityRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)
    availability_state: Literal["available", "unavailable", "on_trip", "offline"]
    session_token: Optional[str] = Field(None, min_length=8, max_length=512)


class DriverHeartbeatRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)
    session_token: str = Field(..., min_length=8, max_length=512)


class DriverRuntimeStatusResponse(BaseModel):
    driver_id: str
    organization_id: str
    auth_state: str
    availability_state: str
    is_online: bool
    last_seen_at: Optional[datetime] = None
    active_session: bool
    active_ride_id: Optional[str] = None


class DriverSessionValidationResponse(BaseModel):
    driver_id: str
    organization_id: str
    session_valid: bool
    session_state: str
    expires_at: Optional[datetime] = None


class DriverActivePoolMetricsResponse(BaseModel):
    total_active: int
    online: int
    available: int
    assigned: int
    on_trip: int
    unavailable: int
    offline: int


class DispatchAutoAssignRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    offer_timeout_seconds: int = Field(90, ge=10, le=600)


class DispatchReassignRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    offer_timeout_seconds: int = Field(90, ge=10, le=600)
    reason: Optional[str] = Field(None, max_length=128)


class DispatchOfferDecisionRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=512)


class DispatchOfferResponse(BaseModel):
    id: Optional[str] = None
    offer_id: str
    organization_id: str
    ride_id: str
    driver_id: Optional[str] = None
    assignment_state: str
    attempt_index: int
    score: Optional[float] = None
    score_breakdown: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int
    queued_at: Optional[datetime] = None
    search_started_at: Optional[datetime] = None
    offered_at: Optional[datetime] = None
    offer_expires_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    en_route_pickup_at: Optional[datetime] = None
    pickup_complete_at: Optional[datetime] = None
    dropoff_complete_at: Optional[datetime] = None
    reassignment_pending_at: Optional[datetime] = None
    reassignment_started_at: Optional[datetime] = None
    reassignment_completed_at: Optional[datetime] = None
    reassignment_attempt_count: int = 0
    reassignment_reason: Optional[str] = None
    reassignment_chain_id: Optional[str] = None
    rejected_at: Optional[datetime] = None
    expired_at: Optional[datetime] = None
    closed_reason: Optional[str] = None


class DispatchAutoAssignResponse(BaseModel):
    ride_id: str
    assignment_state: str
    selected_driver_id: Optional[str] = None
    selected_score: Optional[float] = None
    offer: Optional[DispatchOfferResponse] = None
    candidate_count: int
    candidate_scores: list[dict[str, Any]] = Field(default_factory=list)


class DispatchRecommendationGenerateRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)


class DispatchRecommendationApproveRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    driver_id: Optional[str] = Field(None, min_length=1, max_length=36)
    offer_timeout_seconds: int = Field(90, ge=10, le=600)


class DispatchRecommendationResponse(BaseModel):
    ride_id: str
    assignment_state: str
    recommended_driver_id: Optional[str] = None
    recommended_score: Optional[float] = None
    dispatcher_message: Optional[str] = None
    offer: Optional[DispatchOfferResponse] = None


class DispatchQueueItemResponse(BaseModel):
    ride_id: str
    passenger_name: str
    requested_at: datetime
    ride_status: str
    assignment_state: str
    dispatcher_message: Optional[str] = None
    attempt_index: int
    offered_driver_id: Optional[str] = None
    recommended_driver_id: Optional[str] = None
    recommended_driver_name: Optional[str] = None
    recommendation: Optional[str] = None
    offer_expires_at: Optional[datetime] = None
    score: Optional[float] = None
    queued_at: Optional[datetime] = None
    search_started_at: Optional[datetime] = None
    offered_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    reassignment_pending_at: Optional[datetime] = None
    reassignment_started_at: Optional[datetime] = None
    reassignment_completed_at: Optional[datetime] = None
    reassignment_attempt_count: int = 0
    reassignment_reason: Optional[str] = None
    reassignment_chain_id: Optional[str] = None


class DispatchActiveAssignmentItemResponse(BaseModel):
    offer_id: str
    ride_id: str
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    assignment_state: str
    attempt_index: int
    offered_at: Optional[datetime] = None
    offer_expires_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    en_route_pickup_at: Optional[datetime] = None
    pickup_complete_at: Optional[datetime] = None
    dropoff_complete_at: Optional[datetime] = None
    reassignment_pending_at: Optional[datetime] = None
    reassignment_started_at: Optional[datetime] = None
    reassignment_completed_at: Optional[datetime] = None
    reassignment_attempt_count: int = 0
    reassignment_reason: Optional[str] = None
    reassignment_chain_id: Optional[str] = None
    score: Optional[float] = None
    passenger_name: str
    ride_status: str
    ownership_locked: bool = False
    ownership_locked_by_user_id: Optional[str] = None
    ownership_locked_at: Optional[datetime] = None
    ownership_lock_expires_at: Optional[datetime] = None
    ownership_is_current_user: Optional[bool] = None


class DriverRouteProgressRequest(BaseModel):
    target_state: Literal[
        "assigned",
        "en_route_pickup",
        "arrived_pickup",
        "rider_loaded",
        "trip_in_progress",
        "arrived_destination",
        "completed",
    ]
    ride_id: Optional[str] = Field(None, min_length=1, max_length=36)


class DriverLiveWorkspaceResponse(BaseModel):
    driver_id: str
    organization_id: str
    safety_status: str
    reconnect_safe: bool
    active_assignment: Optional[DispatchActiveAssignmentItemResponse] = None
    active_ride: Optional["RideResponse"] = None
    assignment_countdown_seconds: Optional[int] = None
    eta_minutes: Optional[int] = None
    timeline_states: list[str] = Field(default_factory=list)


class RiderEventFeedItem(BaseModel):
    event_name: str
    timestamp: datetime
    ride_id: str
    driver_id: Optional[str] = None
    message: str


class RiderLiveTrackingResponse(BaseModel):
    organization_id: str
    rider_phone: str
    active_ride: Optional["RideResponse"] = None
    timeline: list[RiderEventFeedItem] = Field(default_factory=list)
    eta_minutes: Optional[int] = None


class AdminLiveOperationsRideItem(BaseModel):
    ride_id: str
    passenger_name: str
    ride_status: str
    assignment_state: str
    driver_id: Optional[str] = None
    driver_name: Optional[str] = None
    provider_id: Optional[str] = None
    requested_at: Optional[datetime] = None
    offer_expires_at: Optional[datetime] = None
    stale_assignment: bool = False


class AdminDispatchAlertItem(BaseModel):
    severity: Literal["info", "warn", "high", "critical"] = "warn"
    alert_type: str
    ride_id: Optional[str] = None
    driver_id: Optional[str] = None
    message: str
    created_at: datetime


class AdminLiveOperationsResponse(BaseModel):
    organization_id: str
    generated_at: datetime
    active_rides: list[AdminLiveOperationsRideItem] = Field(default_factory=list)
    awaiting_assignment: list[AdminLiveOperationsRideItem] = Field(default_factory=list)
    stale_assignments: list[AdminLiveOperationsRideItem] = Field(default_factory=list)
    driver_availability_board: dict[str, int] = Field(default_factory=dict)
    provider_coordination_alerts: list[AdminDispatchAlertItem] = Field(default_factory=list)
    websocket_monitor: dict[str, Any] = Field(default_factory=dict)
    dispatch_event_counters: dict[str, int] = Field(default_factory=dict)


class AdminDispatchAlertsResponse(BaseModel):
    organization_id: str
    generated_at: datetime
    alerts: list[AdminDispatchAlertItem] = Field(default_factory=list)
    counters: dict[str, int] = Field(default_factory=dict)


class AdminReassignDriverRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    driver_id: str = Field(..., min_length=1, max_length=36)
    reason: Optional[str] = Field(None, max_length=256)


class AdminForceExpireAssignmentRequest(BaseModel):
    offer_id: str = Field(..., min_length=1, max_length=36)
    reason: Optional[str] = Field(None, max_length=256)


class AdminDispatchInterventionResponse(BaseModel):
    organization_id: str
    ride: Optional["RideResponse"] = None
    offer: Optional[DispatchOfferResponse] = None
    message: str


# ── Ride Schemas ──────────────────────────────────────────────────────────────

class RideBase(BaseModel):
    passenger_name: str = Field(..., min_length=1, max_length=256)
    passenger_phone: str = Field(..., min_length=1, max_length=20)
    pickup_address: str = Field(..., min_length=1, max_length=512)
    dropoff_address: str = Field(..., min_length=1, max_length=512)
    service_type: str = Field(..., min_length=1, max_length=128)
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("passenger_name", "pickup_address", "dropoff_address", "service_type", mode="before")
    @classmethod
    def sanitize_required_text(cls, value: Any) -> str:
        cleaned = _sanitize_text(str(value or ""))
        if not cleaned:
            raise ValueError("Field is required")
        return cleaned

    @field_validator("service_type", mode="after")
    @classmethod
    def normalize_service_category(cls, value: str) -> str:
        return serialize_service_category(value)

    @field_validator("notes", mode="before")
    @classmethod
    def sanitize_notes(cls, value: Any) -> Optional[str]:
        return _sanitize_text(value, max_len=1000)

    @field_validator("passenger_phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        phone = _sanitize_text(value, max_len=20) or ""
        if not PHONE_RE.match(phone):
            raise ValueError("Passenger phone must be a valid phone number")
        return phone

    @model_validator(mode="after")
    def validate_addresses(self):
        if (self.pickup_address or "").lower() == (self.dropoff_address or "").lower():
            raise ValueError("Pickup and dropoff addresses must be different")
        return self


class RideCreate(RideBase):
    provider_id: str = Field(..., min_length=1, max_length=36)
    estimated_distance_miles: float = Field(1.0, gt=0)
    estimated_duration_minutes: Optional[int] = Field(None, gt=0)
    priority_tag: Literal["normal", "high", "urgent", "emergency", "low"] = "normal"
    is_emergency: bool = False
    appointment_time: Optional[datetime] = None
    recurring_trip_pattern: Optional[Any] = None
    ai_dispatch_context: Optional[Any] = None

    @field_validator("provider_id", mode="before")
    @classmethod
    def validate_provider(cls, value: Any) -> str:
        provider_id = _sanitize_text(str(value or ""), max_len=36)
        if not provider_id:
            raise ValueError("provider_id is required")
        return provider_id

    @field_validator("priority_tag", mode="before")
    @classmethod
    def normalize_priority_tag(cls, value: Any) -> str:
        tag = (_sanitize_text(str(value or "normal"), max_len=32) or "normal").lower()
        if tag == "urgent":
            return "urgent"
        if tag in {"normal", "high", "emergency", "low"}:
            return tag
        return "normal"

    @field_validator("recurring_trip_pattern")
    @classmethod
    def validate_recurring_trip_pattern(cls, value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if value is None:
            return None
        frequency = str(value.get("frequency", "")).lower()
        if frequency and frequency not in {"daily", "weekly", "monthly", "custom"}:
            raise ValueError("recurring_trip_pattern.frequency is invalid")
        return value


class RideStatusUpdateRequest(BaseModel):
    status: RideStatus


class RideAssignDriverRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)


class RideAssignVehicleRequest(BaseModel):
    vehicle_id: str = Field(..., min_length=1, max_length=36)


class DispatcherCustomerRequestAssignDriverRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)


class DispatcherCustomerRequestAutoDispatchRequest(BaseModel):
    offer_timeout_seconds: int = Field(90, ge=10, le=600)


class DispatcherCustomerRequestReassignRequest(BaseModel):
    offer_timeout_seconds: int = Field(90, ge=10, le=600)
    reason: Optional[str] = Field(None, max_length=256)


class DispatcherCustomerRequestReasonRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=512)


class RideResponse(RideBase):
    id: str
    organization_id: str
    provider_id: Optional[str]
    driver_id: Optional[str]
    vehicle_id: Optional[str]
    status: str
    lifecycle_state: Optional[str] = None
    estimated_distance_miles: Optional[float]
    estimated_duration_minutes: Optional[int]
    priority_score: Optional[float]
    priority_tag: Optional[str]
    is_emergency: bool
    appointment_time: Optional[datetime]
    recurring_trip_pattern: Optional[Any] = None
    recurring_schedule_id: Optional[str] = None
    recurring_instance_date: Optional[datetime] = None
    ai_dispatch_context: Optional[Any] = None
    requested_at: datetime
    assigned_at: Optional[datetime]
    enroute_at: Optional[datetime]
    arrived_at: Optional[datetime]
    picked_up_at: Optional[datetime]
    transporting_at: Optional[datetime]
    accepted_at: Optional[datetime]
    completed_at: Optional[datetime]

    class Config:
        from_attributes = True


class DispatcherCustomerRequestActionResponse(BaseModel):
    request: CustomerRideRequestResponse
    ride: Optional[RideResponse] = None
    offer: Optional[DispatchOfferResponse] = None
    message: str


class RideArrivalStatusResponse(BaseModel):
    ride_id: str
    organization_id: str
    lifecycle_state: str
    arrived: bool
    arrived_at: Optional[datetime] = None
    evidence_event_id: Optional[str] = None
    evidence_source: Optional[str] = None
    evidence_captured_at: Optional[datetime] = None
    driver_id: Optional[str] = None


class RidePickupStatusResponse(BaseModel):
    ride_id: str
    organization_id: str
    lifecycle_state: str
    picked_up: bool
    in_progress: bool
    picked_up_at: Optional[datetime] = None
    evidence_event_id: Optional[str] = None
    evidence_source: Optional[str] = None
    evidence_captured_at: Optional[datetime] = None
    driver_id: Optional[str] = None


class RideCompletionHandoffResponse(BaseModel):
    ride_id: str
    organization_id: str
    lifecycle_state: str
    completed: bool
    completion_artifact_id: Optional[str] = None
    completion_artifact_source: Optional[str] = None
    completion_artifact_created_at: Optional[datetime] = None
    trip_id: Optional[str] = None
    payout_id: Optional[str] = None
    provider_queue_ready: bool
    billing_queue_ready: bool


class RideHistoryEventResponse(BaseModel):
    id: str
    ride_id: str
    from_status: Optional[str]
    to_status: str
    note: Optional[str]
    changed_by_user_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Trip Schemas ──────────────────────────────────────────────────────────────

class TripResponse(BaseModel):
    id: str
    ride_id: str
    driver_id: str
    status: str
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    distance_miles: Optional[float]
    duration_minutes: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Payout Schemas ────────────────────────────────────────────────────────────

class PayoutResponse(BaseModel):
    id: str
    driver_id: str
    trip_id: Optional[str]
    amount_usd: float
    status: str
    description: Optional[str]
    created_at: datetime
    processed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Dashboard Schemas ─────────────────────────────────────────────────────────

class DashboardMetrics(BaseModel):
    total_rides: int
    total_rides_today: int
    pending_rides: int
    assigned_rides: int
    active_rides: int
    completed_rides: int
    cancelled_rides: int
    total_drivers: int
    available_drivers: int
    busy_drivers: int
    offline_drivers: int
    total_providers: int
    total_trips_completed: int
    avg_driver_rating: float
    average_ride_duration_minutes: float
    cancellation_count: int
    pending_payouts_usd: float
    total_payouts_usd: float
    timestamp: datetime


class DispatchLogResponse(BaseModel):
    id: str
    ride_id: str
    driver_id: Optional[str]
    action: str
    note: Optional[str]
    request_id: Optional[str] = None
    assignment_id: Optional[str] = None
    lifecycle_state: Optional[str] = None
    transition_reason: Optional[str] = None
    transition_timestamp: Optional[datetime] = None
    emitted_event_name: Optional[str] = None
    emitted_timestamp: Optional[datetime] = None
    websocket_delivery_target: Optional[str] = None
    assignment_transition_source: Optional[str] = None
    acted_by_user_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class StatusResponse(BaseModel):
    status: str = "healthy"
    module: str = "health_isf"
    message: str = "Health ISF MVP module is running"
    timestamp: datetime


# ── Real-Time Event Schemas ──────────────────────────────────────────────────

class RealTimeEventPayload(BaseModel):
    """Base payload for real-time events."""
    event_type: str
    ride_id: Optional[str] = None
    driver_id: Optional[str] = None
    timestamp: datetime
    actor_user_id: Optional[str] = None
    details: Optional[dict] = None


class RideStatusChangedEvent(RealTimeEventPayload):
    """Event emitted when ride status changes."""
    from_status: Optional[str] = None
    to_status: str
    event_type: str = "ride_status_changed"


class DriverStatusChangedEvent(RealTimeEventPayload):
    """Event emitted when driver status changes."""
    from_status: Optional[str] = None
    to_status: str
    event_type: str = "driver_status_changed"


class RideAssignedEvent(RealTimeEventPayload):
    """Event emitted when ride is assigned to a driver."""
    driver_name: Optional[str] = None
    event_type: str = "ride_assigned"


class AssignmentRejectedEvent(RealTimeEventPayload):
    """Event emitted when driver rejects a ride assignment."""
    reason: Optional[str] = None
    event_type: str = "assignment_rejected"


class RideCompletedEvent(RealTimeEventPayload):
    """Event emitted when ride is completed."""
    distance_miles: Optional[float] = None
    duration_minutes: Optional[int] = None
    event_type: str = "ride_completed"


class DispatcherActivityResponse(BaseModel):
    """Dispatcher activity feed entry."""
    id: str
    organization_id: str
    action: str
    ride_id: Optional[str]
    driver_id: Optional[str]
    description: str
    details: Optional[dict] = None
    actor_user_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True
        json_encoders = {
            dict: lambda v: v or {}
        }


class ActivityFeedResponse(BaseModel):
    """Activity feed with pagination."""
    activities: list[DispatcherActivityResponse]
    total: int
    skip: int
    limit: int


class WebSocketMessage(BaseModel):
    """WebSocket message format."""
    type: str  # 'event', 'subscribe', 'unsubscribe', 'ping', 'pong'
    event_type: Optional[str] = None
    payload: Optional[dict] = None
    subscription_type: Optional[str] = None  # 'dispatcher_board', 'driver_dashboard', 'ride_updates'


class ConcurrentAssignmentError(BaseModel):
    """Error response for concurrent assignment conflict."""
    detail: str
    error_code: str = "CONCURRENT_ASSIGNMENT"
    ride_id: str
    current_version: int
    required_version: int


class OperationalAlertResponse(BaseModel):
    type: str
    severity: str
    message: str
    details: dict
    timestamp: str


class OperationalMetricsResponse(BaseModel):
    active_rides: int
    average_assignment_time_seconds: float
    pickup_delay_seconds: float
    completion_duration_seconds: float
    driver_utilization_percent: float
    dispatch_throughput_per_minute: int
    websocket_connection_count: int
    failed_event_count: int
    unassigned_rides: int
    registry: dict


class OperationalHealthResponse(BaseModel):
    status: str
    database: dict
    websocket: dict
    event_queue: dict
    api_latency: dict
    query_optimization: dict
    dependencies: dict
    timestamp: str


class OperationalDashboardResponse(BaseModel):
    organization_id: Optional[str] = None
    active_rides: list[RideResponse] = Field(default_factory=list)
    pending_rides: list[RideResponse] = Field(default_factory=list)
    available_drivers: list[DriverResponse] = Field(default_factory=list)
    dispatch_load: float = Field(default=0.0, ge=0.0)
    operational_alerts: list[dict[str, Any]] = Field(default_factory=list)
    live_metrics_panel: dict
    ride_throughput_chart: list[dict]
    driver_utilization_chart: list[dict]
    dispatch_latency_tracking: dict
    operational_error_tracking: dict
    timestamp: str


class RoutePlanRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    origin_latitude: float = Field(..., ge=-90.0, le=90.0)
    origin_longitude: float = Field(..., ge=-180.0, le=180.0)
    destination_latitude: float = Field(..., ge=-90.0, le=90.0)
    destination_longitude: float = Field(..., ge=-180.0, le=180.0)
    map_provider: str = Field(default="synthetic", min_length=1, max_length=32)
    traffic_mode: Literal["light", "normal", "heavy"] = "normal"
    deviation_threshold_meters: float = Field(default=250.0, ge=50.0, le=5000.0)


class DriverLocationIngestRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)
    ride_id: Optional[str] = Field(None, min_length=1, max_length=36)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    heading: Optional[float] = Field(None, ge=0.0, le=360.0)
    speed_kph: Optional[float] = Field(None, ge=0.0, le=300.0)
    accuracy_meters: Optional[float] = Field(None, ge=0.0, le=10000.0)
    device_id: Optional[str] = Field(None, max_length=128)
    source: str = Field(default="mobile", min_length=1, max_length=32)


class MobileReconnectRequest(BaseModel):
    driver_id: str = Field(..., min_length=1, max_length=36)
    last_ping_id: Optional[str] = Field(None, min_length=1, max_length=36)


class PaymentIntentRequest(BaseModel):
    ride_id: str = Field(..., min_length=1, max_length=36)
    amount_usd: Optional[float] = Field(None, ge=0.0, le=100000.0)
    tip_amount_usd: float = Field(default=0.0, ge=0.0, le=20000.0)
    surcharge_usd: float = Field(default=0.0, ge=0.0, le=20000.0)
    currency: str = Field(default="usd", min_length=3, max_length=8)
    invoice_reference: Optional[str] = Field(None, max_length=128)
    capture_immediately: bool = False


class PaymentCaptureRequest(BaseModel):
    payment_id: str = Field(..., min_length=1, max_length=36)


class PaymentSettlementRequest(BaseModel):
    payment_id: str = Field(..., min_length=1, max_length=36)
    driver_ratio: float = Field(default=0.72, ge=0.0, le=1.0)
    provider_ratio: float = Field(default=0.28, ge=0.0, le=1.0)


# ── Intelligence Schemas ────────────────────────────────────────────────────

class IntelligenceThresholds(BaseModel):
    stuck_ride_minutes: int = Field(45, ge=5, le=240)
    delayed_pickup_minutes: int = Field(20, ge=5, le=240)
    cancellation_spike_count: int = Field(10, ge=1, le=500)
    low_driver_coverage_ratio: float = Field(0.5, ge=0.05, le=1.0)
    websocket_disconnect_spike_count: int = Field(20, ge=1, le=1000)
    overloaded_provider_active_rides: int = Field(5, ge=1, le=100)
    high_dispatch_latency_seconds: int = Field(120, ge=10, le=3600)
    auto_reassign_confidence_threshold: float = Field(0.7, ge=0.0, le=1.0)


class IntelligenceRecommendationItem(BaseModel):
    entity_type: str
    entity_id: str
    score: float
    confidence: float
    explanation: list[str]
    details: dict[str, Any] = Field(default_factory=dict)


class IntelligenceRecommendationResponse(BaseModel):
    organization_id: str
    ride_id: Optional[str] = None
    generated_at: str
    recommendations: list[IntelligenceRecommendationItem]
    dispatcher_recommendation_payloads: list[dict[str, Any]]
    automated_actions: list[dict[str, Any]]


class IntelligenceAnomalyResponse(BaseModel):
    organization_id: str
    generated_at: str
    anomalies: list[dict[str, Any]]
    explanations: list[str]


class IntelligenceRiskResponse(BaseModel):
    organization_id: str
    generated_at: str
    operational_health_score: float
    risk_score: float
    workload_score: float
    eta_minutes: float
    delay_risk_score: float
    provider_saturation_score: float
    dispatcher_workload_score: float
    trend_explanations: list[str]
    anomaly_explanations: list[str]
    recommendation_summaries: list[str]


class IntelligenceSummaryResponse(BaseModel):
    organization_id: str
    generated_at: str
    summary: str
    operational_health_score: float
    risk_score: float
    anomaly_count: int
    recommendation_count: int
    trend_explanations: list[str]
    anomaly_explanations: list[str]
    recommendation_summaries: list[str]
    predictive_signals: dict[str, Any]
    operational_state_awareness: Optional[dict[str, Any]] = None
    operational_context_aggregation: Optional[dict[str, Any]] = None
    operational_correlations: Optional[dict[str, Any]] = None
    operational_anomaly_surface: Optional[dict[str, Any]] = None
    backend_state_verification: Optional[dict[str, Any]] = None


class IntelligenceReanalyzeRequest(BaseModel):
    organization_id: Optional[str] = None
    ride_id: Optional[str] = None
    thresholds: Optional[IntelligenceThresholds] = None
    broadcast: bool = True


class IntelligenceReanalyzeResponse(BaseModel):
    summary: IntelligenceSummaryResponse
    anomalies: IntelligenceAnomalyResponse
    recommendations: IntelligenceRecommendationResponse
    risk: IntelligenceRiskResponse


# ── Workflow Automation Schemas ──────────────────────────────────────────────

class WorkflowRecoverRequest(BaseModel):
    organization_id: Optional[str] = None
    ride_id: Optional[str] = None
    note: Optional[str] = Field(None, max_length=1024)
    dry_run: bool = False


class WorkflowReassignRequest(BaseModel):
    organization_id: Optional[str] = None
    ride_id: str = Field(..., min_length=1, max_length=36)
    driver_id: Optional[str] = Field(None, min_length=1, max_length=36)
    suggest_only: bool = False
    approval_override: bool = False


class WorkflowReplayRequest(BaseModel):
    organization_id: Optional[str] = None
    limit: int = Field(25, ge=1, le=250)


class WorkflowEscalateRequest(BaseModel):
    organization_id: Optional[str] = None
    incident_id: Optional[str] = Field(None, min_length=1, max_length=36)
    ride_id: Optional[str] = Field(None, min_length=1, max_length=36)
    summary: Optional[str] = Field(None, max_length=512)
    severity: str = Field("high", min_length=1, max_length=16)
    target_role: str = Field("dispatcher", min_length=1, max_length=64)
    escalation_level: int = Field(1, ge=1, le=10)
    details: dict[str, Any] = Field(default_factory=dict)


class AutomationPolicyResponse(BaseModel):
    id: str
    organization_id: str
    name: str
    scope: str
    is_enabled: bool
    approval_required: bool
    auto_reassign_enabled: bool
    auto_escalation_enabled: bool
    allow_replay: bool
    max_retry_attempts: int
    stuck_ride_minutes: int
    delayed_pickup_minutes: int
    escalation_minutes: int
    policy_rules: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkflowExecutionResponse(BaseModel):
    id: str
    organization_id: str
    workflow_name: str
    status: str
    trigger_type: str
    ride_id: Optional[str] = None
    driver_id: Optional[str] = None
    policy_id: Optional[str] = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    retry_count: int
    max_attempts: int
    approval_required: bool
    approved_by_user_id: Optional[str] = None
    created_by_user_id: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class WorkflowIncidentResponse(BaseModel):
    id: str
    organization_id: str
    workflow_execution_id: Optional[str] = None
    ride_id: Optional[str] = None
    driver_id: Optional[str] = None
    incident_type: str
    severity: str
    status: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    resolved_at: Optional[datetime] = None
    escalated_at: Optional[datetime] = None


class WorkflowEscalationResponse(BaseModel):
    id: str
    organization_id: str
    workflow_execution_id: Optional[str] = None
    incident_id: str
    escalation_level: int
    target_queue: str
    target_role: str
    status: str
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    acknowledged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None


class WorkflowOperationResponse(BaseModel):
    execution: WorkflowExecutionResponse
    incidents: list[WorkflowIncidentResponse]
    escalations: list[WorkflowEscalationResponse]
    recommendations: list[dict[str, Any]]
    policy: AutomationPolicyResponse
    summary: str
    broadcast_events: int
    dry_run: bool


# ── AI Dispatch Orchestration Schemas ────────────────────────────────────────

class AIDispatchVoiceCommandRequest(BaseModel):
    organization_id: Optional[str] = None
    transcript: str = Field(..., min_length=1, max_length=4000)
    ride_id: Optional[str] = Field(None, min_length=1, max_length=36)


class AIDispatchVoiceCommandResponse(BaseModel):
    organization_id: str
    generated_at: str
    transcript: str
    intent: str
    action_label: str
    extracted_entities: dict[str, Optional[str]]
    recommendation_summary: Optional[str] = None
    recommended_endpoint: str
    automation_hints: list[dict[str, Any]]


class AIDispatchIntakeAssistRequest(BaseModel):
    organization_id: Optional[str] = None
    passenger_name: str = Field(..., min_length=1, max_length=256)
    passenger_phone: Optional[str] = Field(None, min_length=1, max_length=20)
    pickup_address: str = Field(..., min_length=1, max_length=512)
    dropoff_address: str = Field(..., min_length=1, max_length=512)
    service_type: str = Field(..., min_length=1, max_length=128)
    provider_id: Optional[str] = Field(None, min_length=1, max_length=36)
    appointment_time: Optional[datetime] = None
    recurring_trip_pattern: Optional[dict[str, Any]] = None
    estimated_distance_miles: float = Field(0.0, ge=0.0, le=500.0)
    estimated_duration_minutes: Optional[int] = Field(None, ge=1, le=1440)
    priority_tag: Optional[str] = Field(None, min_length=1, max_length=32)
    is_emergency: bool = False
    notes: Optional[str] = Field(None, max_length=1000)

    @field_validator("passenger_name", "pickup_address", "dropoff_address", "service_type", mode="before")
    @classmethod
    def sanitize_intake_text(cls, value: Any) -> str:
        cleaned = _sanitize_text(str(value or ""))
        if not cleaned:
            raise ValueError("Field is required")
        return cleaned

    @field_validator("passenger_phone", "priority_tag", "notes", mode="before")
    @classmethod
    def sanitize_optional_intake_text(cls, value: Any) -> Optional[str]:
        return _sanitize_text(value)


class AIDispatchIntakeAssistResponse(BaseModel):
    organization_id: str
    generated_at: str
    urgency: str
    priority_score: float
    estimated_duration_minutes: int
    suggested_provider_ids: list[str]
    suggested_driver_ids: list[str]
    duplicate_candidates: list[dict[str, Any]]
    dispatcher_notes: list[str]
    ai_dispatch_context: dict[str, Any]


class AIDispatchNotificationResponse(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str
    created_at: str
    source: str
    ride_id: Optional[str] = None


class OperationalTimelineItemResponse(BaseModel):
    id: str
    kind: str
    timestamp: str
    title: str
    summary: str
    severity: str
    ride_id: Optional[str] = None
    driver_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AutonomousOperationsSnapshotResponse(BaseModel):
    organization_id: str
    generated_at: str
    summary: dict[str, Any]
    metrics: dict[str, Any]
    dashboard: dict[str, Any]
    analytics: dict[str, Any]
    alerts: list[dict[str, Any]]
    notifications: list[AIDispatchNotificationResponse]
    recommendations: dict[str, Any]
    timeline: list[OperationalTimelineItemResponse]
    resilience: dict[str, Any]
    assistant: dict[str, Any]
    orchestration: dict[str, Any]
    event_stream: dict[str, Any]
    memory_snapshot: dict[str, Any]
    operational_state_awareness: Optional[dict[str, Any]] = None
    operational_context_aggregation: Optional[dict[str, Any]] = None
    operational_correlations: Optional[dict[str, Any]] = None
    operational_anomaly_surface: Optional[dict[str, Any]] = None
    backend_state_verification: Optional[dict[str, Any]] = None
