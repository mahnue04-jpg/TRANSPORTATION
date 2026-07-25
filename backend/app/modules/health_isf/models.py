"""
Database models for Health ISF (Integrated Services for Health) module.
MVP scope: ride requests, drivers, providers, dispatch tracking, trip status, payout placeholder.
"""
import logging
from datetime import datetime
from enum import Enum
from sqlalchemy import (
    DateTime, Enum as SQLEnum, Float, ForeignKey,
    Integer, String, Text, Boolean, Index, UniqueConstraint, inspect, text
)
from sqlalchemy import TypeDecorator, String as SAString
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.helpers import now, uuid4


# ── Helpers ───────────────────────────────────────────────────────────────────

class _CaseInsensitiveStatus(TypeDecorator):
    """Column type that normalizes enum status strings to lowercase on read/write.

    Accepts uppercase values (e.g. 'AVAILABLE') stored by legacy seed data and
    returns the lowercase str so ``str(Enum)`` comparisons keep working.
    """
    impl = SAString(32)
    cache_ok = True

    def __init__(self, enum_class, *args, **kwargs):
        self._enum_class = enum_class
        super().__init__(*args, **kwargs)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, self._enum_class):
            return value.value
        return str(value).lower()

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        try:
            return self._enum_class(value.lower())
        except ValueError:
            return value.lower()


# ── Enums ─────────────────────────────────────────────────────────────────────

class RideStatus(str, Enum):
    """Ride statuses (legacy-compatible + live execution lifecycle projections)."""
    REQUESTED = "requested"
    QUEUED = "queued"
    ASSIGNED = "assigned"
    DRIVER_EN_ROUTE = "driver_en_route"
    ARRIVED = "arrived"
    RIDER_ONBOARD = "rider_onboard"
    IN_PROGRESS = "in_progress"
    ARRIVED_DESTINATION = "arrived_destination"
    FAILED = "failed"
    ESCALATED = "escalated"

    # Legacy compatibility states used by existing routes/UI.
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DriverStatus(str, Enum):
    """Operational driver statuses."""
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    EN_ROUTE_PICKUP = "en_route_pickup"
    WAITING_AT_PICKUP = "waiting_at_pickup"
    IN_TRANSIT = "in_transit"
    COMPLETED = "completed"
    UNAVAILABLE = "unavailable"
    BUSY = "busy"
    OFFLINE = "offline"


class CustomerRequestStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DISPATCHABLE = "dispatchable"
    BROADCASTED = "broadcasted"
    ACCEPTED = "accepted"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class DispatchAssignmentState(str, Enum):
    """Dispatch assignment lifecycle states for auto-assignment offers."""
    QUEUED = "queued"
    SEARCHING = "searching"
    AWAITING_APPROVAL = "awaiting_approval"
    OFFERED = "offered"
    REJECTED = "rejected"
    EXPIRED = "expired"
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    EN_ROUTE_PICKUP = "en_route_pickup"
    PICKUP_COMPLETE = "pickup_complete"
    ARRIVED_DESTINATION = "arrived_destination"
    DROPOFF_COMPLETE = "dropoff_complete"
    REASSIGNMENT_PENDING = "reassignment_pending"


class TripStatus(str, Enum):
    """MVP trip/delivery statuses."""
    CREATED = "created"
    DISPATCHED = "dispatched"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class EventType(str, Enum):
    """Real-time event types for dispatcher operations."""
    RIDE_CREATED = "ride_created"
    RIDE_STATUS_CHANGED = "ride_status_changed"
    DRIVER_STATUS_CHANGED = "driver_status_changed"
    RIDE_ASSIGNED = "ride_assigned"
    RIDE_UNASSIGNED = "ride_unassigned"
    ASSIGNMENT_REJECTED = "assignment_rejected"
    PICKUP_COMPLETED = "pickup_completed"
    RIDE_COMPLETED = "ride_completed"
    RIDE_CANCELLED = "ride_cancelled"
    DRIVER_AVAILABILITY_CHANGED = "driver_availability_changed"
    DISPATCH_CHANGED = "dispatch_changed"
    PROVIDER_UPDATED = "provider_updated"
    DRIVER_ACTIVE_RIDE_STATE = "driver_active_ride_state"
    RIDE_LIFECYCLE_SYNC = "ride_lifecycle_sync"


class ActivityAction(str, Enum):
    """Dispatcher activity log actions."""
    RIDE_CREATED = "ride_created"
    RIDE_ASSIGNED = "ride_assigned"
    RIDE_CANCELLED = "ride_cancelled"
    DRIVER_STATUS_CHANGED = "driver_status_changed"
    ASSIGNMENT_REJECTED = "assignment_rejected"
    PICKUP_COMPLETED = "pickup_completed"
    RIDE_COMPLETED = "ride_completed"
    RIDE_ESCALATED = "ride_escalated"
    RIDE_REASSIGNED = "ride_reassigned"
    RIDE_REPLAYED = "ride_replayed"
    RIDE_WORKFLOW_RETRIED = "ride_workflow_retried"


class WorkflowExecutionStatus(str, Enum):
    """Workflow execution lifecycle states."""
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    REPLAYED = "replayed"


class WorkflowIncidentStatus(str, Enum):
    """Workflow incident lifecycle states."""
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class WorkflowEscalationStatus(str, Enum):
    """Workflow escalation lifecycle states."""
    QUEUED = "queued"
    ROUTED = "routed"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AutomationPolicyScope(str, Enum):
    """Automation policy scope values."""
    TENANT = "tenant"
    ORGANIZATION = "organization"
    WORKFLOW = "workflow"


# ── Models ────────────────────────────────────────────────────────────────────

class HealthISFProvider(Base):
    """Healthcare provider (clinic, facility)."""
    __tablename__ = "health_isf_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    address: Mapped[str] = mapped_column(String(512), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    service_type: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g., "clinic", "facility"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="providers")

    rides: Mapped[list["HealthISFRide"]] = relationship(
        back_populates="provider", cascade="all, delete-orphan"
    )


class HealthISFOrganization(Base):
    """Organization/tenant owning Health ISF entities."""
    __tablename__ = "health_isf_organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    providers: Mapped[list["HealthISFProvider"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    drivers: Mapped[list["HealthISFDriver"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    rides: Mapped[list["HealthISFRide"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    vehicles: Mapped[list["HealthISFVehicle"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    automation_policies: Mapped[list["HealthISFAutomationPolicy"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    workflow_executions: Mapped[list["HealthISFWorkflowExecution"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    workflow_incidents: Mapped[list["HealthISFWorkflowIncident"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    workflow_escalations: Mapped[list["HealthISFWorkflowEscalation"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    workflow_audit_logs: Mapped[list["HealthISFWorkflowAuditLog"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class HealthISFVehicle(Base):
    """Vehicle inventory for dispatch."""
    __tablename__ = "health_isf_vehicles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vehicle_type: Mapped[str] = mapped_column(String(128), nullable=False)
    vehicle_plate: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    capacity: Mapped[int] = mapped_column(Integer, default=4)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="vehicles")
    driver: Mapped["HealthISFDriver | None"] = relationship(back_populates="vehicle", uselist=False)
    rides: Mapped[list["HealthISFRide"]] = relationship(back_populates="vehicle")


class HealthISFDriver(Base):
    """Transportation provider/driver."""
    __tablename__ = "health_isf_drivers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_vehicles.id", ondelete="SET NULL"),
        nullable=True, unique=True, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g., "sedan", "van"
    vehicle_plate: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(
        _CaseInsensitiveStatus(DriverStatus),
        default=DriverStatus.OFFLINE,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    total_trips: Mapped[int] = mapped_column(Integer, default=0)
    rating: Mapped[float] = mapped_column(Float, default=5.0)
    auth_state: Mapped[str] = mapped_column(String(32), nullable=False, default="inactive", index=True)
    availability_state: Mapped[str] = mapped_column(String(32), nullable=False, default="offline", index=True)
    is_online: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)  # For optimistic locking
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="drivers")
    vehicle: Mapped["HealthISFVehicle | None"] = relationship(back_populates="driver")

    rides: Mapped[list["HealthISFRide"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan"
    )
    trips: Mapped[list["HealthISFTrip"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan"
    )
    payouts: Mapped[list["HealthISFPayout"]] = relationship(
        back_populates="driver", cascade="all, delete-orphan"
    )


class HealthISFRide(Base):
    """Ride request from patient/user."""
    __tablename__ = "health_isf_rides"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_providers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    vehicle_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_vehicles.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    assigned_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    last_status_changed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    passenger_name: Mapped[str] = mapped_column(String(256), nullable=False)
    passenger_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    pickup_address: Mapped[str] = mapped_column(String(512), nullable=False)
    dropoff_address: Mapped[str] = mapped_column(String(512), nullable=False)
    service_type: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g., "medical_transport", "dialysis"
    status: Mapped[str] = mapped_column(
        _CaseInsensitiveStatus(RideStatus), default=RideStatus.PENDING, index=True
    )
    lifecycle_state: Mapped[str] = mapped_column(String(32), default=RideStatus.REQUESTED.value, index=True)
    estimated_distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    estimated_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority_tag: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    appointment_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    recurring_trip_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    recurring_schedule_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_recurring_ride_schedules.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    recurring_instance_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ai_dispatch_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    intake_fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)  # For optimistic locking
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    enroute_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    arrived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transporting_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    round_trip_group_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    trip_leg: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    pickup_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    return_pickup_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    same_driver_preference: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dispatch_eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    call_when_ready: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scheduling_series_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="rides")
    provider: Mapped["HealthISFProvider"] = relationship(back_populates="rides")
    driver: Mapped["HealthISFDriver | None"] = relationship(back_populates="rides")
    vehicle: Mapped["HealthISFVehicle | None"] = relationship(back_populates="rides")
    trip: Mapped["HealthISFTrip | None"] = relationship(back_populates="ride", uselist=False)
    dispatch_logs: Mapped[list["HealthISFDispatchLog"]] = relationship(
        back_populates="ride", cascade="all, delete-orphan", order_by="HealthISFDispatchLog.created_at"
    )
    status_history: Mapped[list["HealthISFRideStatusHistory"]] = relationship(
        back_populates="ride", cascade="all, delete-orphan", order_by="HealthISFRideStatusHistory.created_at"
    )
    recurring_schedule: Mapped["HealthISFRecurringRideSchedule | None"] = relationship(back_populates="generated_rides")

    __table_args__ = (
        Index("idx_rides_driver_status", "driver_id", "status"),
        Index("idx_rides_provider_status", "provider_id", "status"),
        Index("idx_rides_org_status", "organization_id", "status"),
    )


class HealthISFDriverSession(Base):
    """Driver runtime session tokens for authenticated operational access."""
    __tablename__ = "health_isf_driver_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    driver_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    session_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    session_state: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("idx_driver_sessions_org_driver", "organization_id", "driver_id"),
        Index("idx_driver_sessions_state_expiry", "session_state", "expires_at"),
    )


class HealthISFRecurringRideSchedule(Base):
    """Dispatcher-managed recurring schedule that generates future rides."""
    __tablename__ = "health_isf_recurring_ride_schedules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_providers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    passenger_name: Mapped[str] = mapped_column(String(256), nullable=False)
    passenger_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    pickup_address: Mapped[str] = mapped_column(String(512), nullable=False)
    dropoff_address: Mapped[str] = mapped_column(String(512), nullable=False)
    service_type: Mapped[str] = mapped_column(String(128), nullable=False)
    pickup_time_local: Mapped[str] = mapped_column(String(8), nullable=False)
    frequency: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    interval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    weekday_mask_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    last_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    generated_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    organization: Mapped["HealthISFOrganization"] = relationship()
    provider: Mapped["HealthISFProvider | None"] = relationship()
    generated_rides: Mapped[list["HealthISFRide"]] = relationship(back_populates="recurring_schedule")


class HealthISFCustomerRideRequest(Base):
    """Customer request queue state for the operational dispatch lifecycle."""
    __tablename__ = "health_isf_customer_ride_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    submitted_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    rider_name: Mapped[str] = mapped_column(String(256), nullable=False)
    rider_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    pickup_address: Mapped[str] = mapped_column(String(512), nullable=False)
    dropoff_address: Mapped[str] = mapped_column(String(512), nullable=False)
    scheduled_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    ride_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    recurring_pattern_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    trip_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    scheduling_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    linked_ride_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    dispatch_status: Mapped[str] = mapped_column(String(32), nullable=False, default=CustomerRequestStatus.PENDING.value, index=True)
    pending_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)
    broadcasted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    in_progress_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    ride: Mapped["HealthISFRide"] = relationship()

    __table_args__ = (
        Index("idx_customer_requests_org_status", "organization_id", "dispatch_status"),
        Index("idx_customer_requests_org_created", "organization_id", "created_at"),
    )


class HealthISFDispatchAssignment(Base):
    """Dispatch assignment attempts with offer timeout and scoring traceability."""
    __tablename__ = "health_isf_dispatch_assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    assignment_state: Mapped[str] = mapped_column(String(32), nullable=False, default=DispatchAssignmentState.QUEUED.value, index=True)
    attempt_index: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=90)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    search_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    en_route_pickup_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pickup_complete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dropoff_complete_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reassignment_pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reassignment_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reassignment_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reassignment_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reassignment_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reassignment_chain_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("idx_dispatch_assign_org_ride", "organization_id", "ride_id"),
        Index("idx_dispatch_assign_org_state", "organization_id", "assignment_state"),
        Index("idx_dispatch_assign_ride_attempt", "ride_id", "attempt_index"),
        Index("idx_dispatch_assign_offer_expiry", "assignment_state", "offer_expires_at"),
    )


class HealthISFDispatchLog(Base):
    """Dispatch audit log entries for ride lifecycle operations."""
    __tablename__ = "health_isf_dispatch_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    assignment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_dispatch_assignments.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    lifecycle_state: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    transition_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    transition_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    emitted_event_name: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    emitted_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    websocket_delivery_target: Mapped[str | None] = mapped_column(String(256), nullable=True)
    assignment_transition_source: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acted_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    ride: Mapped["HealthISFRide"] = relationship(back_populates="dispatch_logs")


class HealthISFRideStatusHistory(Base):
    """Status transition history for rides."""
    __tablename__ = "health_isf_ride_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    changed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

    ride: Mapped["HealthISFRide"] = relationship(back_populates="status_history")


class HealthISFTrip(Base):
    """Trip/delivery execution tracking."""
    __tablename__ = "health_isf_trips"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True
    )
    driver_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        SQLEnum(TripStatus), default=TripStatus.CREATED, index=True
    )
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    distance_miles: Mapped[float | None] = mapped_column(Float, nullable=True)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    ride: Mapped["HealthISFRide"] = relationship(back_populates="trip")
    driver: Mapped["HealthISFDriver"] = relationship(back_populates="trips")


class HealthISFPayout(Base):
    """Driver payout tracking (MVP: placeholder, no real payments yet)."""
    __tablename__ = "health_isf_payouts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    driver_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="RESTRICT"),
        nullable=False, index=True
    )
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)  # pending, processed, failed
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    driver: Mapped["HealthISFDriver"] = relationship(back_populates="payouts")


class HealthISFDriverApplication(Base):
    """Independent contractor driver onboarding applications."""
    __tablename__ = "health_isf_driver_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    applicant_name: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    applicant_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    applicant_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    license_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    insurance_policy_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_make: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    vehicle_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vehicle_plate: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(String(64), nullable=True)
    availability_summary: Mapped[str | None] = mapped_column(String(256), nullable=True)
    availability_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    preferred_service_categories: Mapped[str | None] = mapped_column(Text, nullable=True)
    background_check_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    license_document_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    insurance_document_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    registration_document_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    onboarding_status: Mapped[str] = mapped_column(String(32), nullable=False, default="applied", index=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("idx_driver_app_org_status_created", "organization_id", "onboarding_status", "created_at"),
    )


class HealthISFDriverLocationPing(Base):
    """High-frequency GPS and heartbeat ingestion for live transportation operations."""
    __tablename__ = "health_isf_driver_location_pings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    driver_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    heading: Mapped[float | None] = mapped_column(Float, nullable=True)
    speed_kph: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_meters: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="mobile")
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    __table_args__ = (
        Index("idx_driver_location_org_driver_created", "organization_id", "driver_id", "created_at"),
        Index("idx_driver_location_org_ride_created", "organization_id", "ride_id", "created_at"),
    )


class HealthISFRideRoutePlan(Base):
    """Persisted route/ETA abstractions that survive reconnects and restarts."""
    __tablename__ = "health_isf_ride_route_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    map_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")
    route_reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    origin_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    origin_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    destination_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    destination_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_distance_miles: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    traffic_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    deviation_threshold_meters: Mapped[float] = mapped_column(Float, nullable=False, default=250.0)
    path_points_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("idx_route_plan_org_ride", "organization_id", "ride_id"),
    )


class HealthISFPaymentTransaction(Base):
    """Payment transaction ledger with optional Stripe intent references."""
    __tablename__ = "health_isf_payment_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    provider_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_providers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    gateway: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    gateway_payment_intent_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requires_capture", index=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="usd")
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    tip_amount_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    surcharge_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    processing_fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    settlement_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    invoice_reference: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    failure_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("idx_payment_tx_org_ride", "organization_id", "ride_id"),
        Index("idx_payment_tx_org_status", "organization_id", "status"),
    )


class HealthISFSettlementLedger(Base):
    """Provider and driver settlement rows for each paid ride transaction."""
    __tablename__ = "health_isf_settlement_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    payment_transaction_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_payment_transactions.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    participant_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    participant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    gross_amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    net_amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    __table_args__ = (
        Index("idx_settlement_org_payment", "organization_id", "payment_transaction_id"),
        Index("idx_settlement_org_participant", "organization_id", "participant_type", "participant_id"),
    )


# ── Real-Time Models ─────────────────────────────────────────────────────────

class RealTimeEvent(Base):
    """Real-time event log for dispatcher synchronization."""
    __tablename__ = "health_isf_realtime_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(SQLEnum(EventType), nullable=False, index=True)
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    payload: Mapped[str] = mapped_column(Text, nullable=False)  # JSON payload with event data
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    __table_args__ = (
        Index("idx_events_org_timestamp", "organization_id", "created_at"),
        Index("idx_events_ride_type", "ride_id", "event_type"),
        Index("idx_events_driver_type", "driver_id", "event_type"),
    )


class DispatcherActivityLog(Base):
    """Activity feed log for dispatcher board operations."""
    __tablename__ = "health_isf_dispatcher_activity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    action: Mapped[str] = mapped_column(SQLEnum(ActivityAction), nullable=False, index=True)
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    description: Mapped[str] = mapped_column(String(512), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON with additional details
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    __table_args__ = (
        Index("idx_activity_org_timestamp", "organization_id", "created_at"),
        Index("idx_activity_ride", "ride_id", "created_at"),
        Index("idx_activity_driver", "driver_id", "created_at"),
    )


class RideAssignmentLock(Base):
    """Optimistic locking for concurrent ride assignments."""
    __tablename__ = "health_isf_assignment_locks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    locked_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_locks_expires_at", "expires_at"),
    )


class DispatchEventRetry(Base):
    """Retry queue for failed dispatch events."""
    __tablename__ = "health_isf_dispatch_event_retries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True, index=True)
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    __table_args__ = (
        Index("idx_dispatch_retries_org_status", "organization_id", "status"),
        Index("idx_dispatch_retries_due", "status", "next_retry_at"),
    )


class DispatchDeadLetterEvent(Base):
    """Dead-letter queue for events exhausted after retries."""
    __tablename__ = "health_isf_dispatch_dead_letters"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    retry_event_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_dispatch_event_retries.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class DispatchIdempotencyKey(Base):
    """Idempotency key records for dispatch event handling."""
    __tablename__ = "health_isf_dispatch_idempotency"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    scope: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)


class HealthISFRideExecutionAction(Base):
    """Append-only execution actions for audit-safe ride lifecycle operations."""
    __tablename__ = "health_isf_ride_execution_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    from_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_state: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    action_status: Mapped[str] = mapped_column(String(16), nullable=False, default="success", index=True)
    replay_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    # Event sequencing metadata
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, default=lambda: str(uuid4()), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    monotonic_ts: Mapped[float] = mapped_column(Float, nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    __table_args__ = (
        Index("idx_ride_exec_actions_org_ride", "organization_id", "ride_id"),
        Index("idx_ride_exec_actions_replay", "organization_id", "replay_key"),
        Index("idx_ride_exec_actions_event_id", "organization_id", "event_id"),
        Index("idx_ride_exec_actions_seq", "organization_id", "ride_id", "sequence_number"),
    )


class OperationalAlertLog(Base):
    """Persisted operational alerts for reliability review."""
    __tablename__ = "health_isf_operational_alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    alert_state: Mapped[str] = mapped_column(String(24), nullable=False, default="open", index=True)
    incident_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    escalation_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_roles_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    notification_channels_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalation_chain_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    message: Mapped[str] = mapped_column(String(512), nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    acknowledged_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    __table_args__ = (
        Index("idx_alerts_org_created", "organization_id", "created_at"),
        Index("idx_alerts_org_state", "organization_id", "alert_state"),
        Index("idx_alerts_org_incident", "organization_id", "incident_key"),
    )


class HealthISFAutomationPolicy(Base):
    """Tenant-scoped automation policy configuration."""
    __tablename__ = "health_isf_automation_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default=AutomationPolicyScope.TENANT.value, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    auto_reassign_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    auto_escalation_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    allow_replay: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    max_retry_attempts: Mapped[int] = mapped_column(Integer, default=3)
    stuck_ride_minutes: Mapped[int] = mapped_column(Integer, default=45)
    delayed_pickup_minutes: Mapped[int] = mapped_column(Integer, default=20)
    escalation_minutes: Mapped[int] = mapped_column(Integer, default=30)
    policy_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="automation_policies")


class HealthISFWorkflowExecution(Base):
    """Workflow execution history for recovery and escalation workflows."""
    __tablename__ = "health_isf_workflow_executions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workflow_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkflowExecutionStatus.QUEUED.value, index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    policy_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_automation_policies.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    input_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="workflow_executions")
    policy: Mapped["HealthISFAutomationPolicy | None"] = relationship()
    incidents: Mapped[list["HealthISFWorkflowIncident"]] = relationship(
        back_populates="workflow_execution", cascade="all, delete-orphan"
    )
    escalations: Mapped[list["HealthISFWorkflowEscalation"]] = relationship(
        back_populates="workflow_execution", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_workflow_exec_org_updated", "organization_id", "updated_at"),
        Index("idx_workflow_exec_org_status", "organization_id", "status"),
    )


class HealthISFWorkflowIncident(Base):
    """Operational incident generated by workflow automation."""
    __tablename__ = "health_isf_workflow_incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workflow_execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_workflow_executions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_drivers.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    incident_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkflowIncidentStatus.OPEN.value, index=True)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="workflow_incidents")
    workflow_execution: Mapped["HealthISFWorkflowExecution | None"] = relationship(back_populates="incidents")
    escalations: Mapped[list["HealthISFWorkflowEscalation"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_workflow_incident_org_status", "organization_id", "status"),
        Index("idx_workflow_incident_org_created", "organization_id", "created_at"),
    )


class HealthISFWorkflowEscalation(Base):
    """Escalation record for unresolved workflow incidents."""
    __tablename__ = "health_isf_workflow_escalations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workflow_execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_workflow_executions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_workflow_incidents.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    escalation_level: Mapped[int] = mapped_column(Integer, default=1, index=True)
    target_queue: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_role: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkflowEscalationStatus.QUEUED.value, index=True)
    summary: Mapped[str] = mapped_column(String(512), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="workflow_escalations")
    workflow_execution: Mapped["HealthISFWorkflowExecution | None"] = relationship(back_populates="escalations")
    incident: Mapped["HealthISFWorkflowIncident"] = relationship(back_populates="escalations")

    __table_args__ = (
        Index("idx_workflow_escalation_org_status", "organization_id", "status"),
        Index("idx_workflow_escalation_org_created", "organization_id", "created_at"),
    )


class HealthISFWorkflowAuditLog(Base):
    """Audit trail for workflow automation and recovery actions."""
    __tablename__ = "health_isf_workflow_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    workflow_execution_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_workflow_executions.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    incident_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_workflow_incidents.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    escalation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_workflow_escalations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    organization: Mapped["HealthISFOrganization"] = relationship(back_populates="workflow_audit_logs")

    __table_args__ = (
        Index("idx_workflow_audit_org_created", "organization_id", "created_at"),
    )


class SecurityAuditAction(Base):
    """Enterprise audit record for sensitive/privileged actions."""
    __tablename__ = "health_isf_security_audit_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    ride_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    __table_args__ = (
        Index("idx_sec_audit_org_created", "organization_id", "created_at"),
    )


class SecuritySuspiciousActivity(Base):
    """Tracks suspicious activity signals (invalid token, boundary violation, brute-force hooks)."""
    __tablename__ = "health_isf_security_suspicious_activity"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    activity_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


_SCHEMA_LOGGER = logging.getLogger(__name__)


def _schema_datetime_sql(dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return "TIMESTAMP WITH TIME ZONE"
    return "DATETIME"


def _schema_add_column_if_missing(
    conn,
    inspector,
    table_name: str,
    column_name: str,
    column_type_sql: str,
) -> None:
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    try:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type_sql}"))
    except Exception:
        _SCHEMA_LOGGER.exception(
            "health_isf_schema_add_column_failed table=%s column=%s type=%s",
            table_name,
            column_name,
            column_type_sql,
        )


def ensure_health_isf_schema() -> None:
    """Apply lightweight additive schema upgrades for older Health ISF databases."""
    from app.db.session import engine

    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        inspector = inspect(conn)
        table_names = set(inspector.get_table_names())
        if not table_names:
            return

        if "health_isf_rides" in table_names:
            ride_columns = {column["name"] for column in inspector.get_columns("health_isf_rides")}
            if "version" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN version INTEGER NOT NULL DEFAULT 0"))
            if "priority_score" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN priority_score FLOAT"))
            if "priority_tag" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN priority_tag VARCHAR(32)"))
            if "is_emergency" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN is_emergency BOOLEAN NOT NULL DEFAULT 0"))
            if "appointment_time" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN appointment_time DATETIME"))
            if "recurring_trip_pattern" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN recurring_trip_pattern TEXT"))
            if "recurring_schedule_id" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN recurring_schedule_id VARCHAR(36)"))
            if "recurring_instance_date" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN recurring_instance_date DATETIME"))
            if "ai_dispatch_context" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN ai_dispatch_context TEXT"))
            if "intake_fingerprint" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN intake_fingerprint VARCHAR(128)"))
            if "lifecycle_state" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN lifecycle_state VARCHAR(32) DEFAULT 'requested'"))
            if "assigned_at" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN assigned_at DATETIME"))
            if "enroute_at" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN enroute_at DATETIME"))
            if "arrived_at" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN arrived_at DATETIME"))
            if "picked_up_at" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN picked_up_at DATETIME"))
            if "transporting_at" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN transporting_at DATETIME"))
            if "round_trip_group_id" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN round_trip_group_id VARCHAR(36)"))
            if "trip_leg" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN trip_leg VARCHAR(16)"))
            if "pickup_time" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN pickup_time DATETIME"))
            if "return_pickup_type" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN return_pickup_type VARCHAR(32)"))
            if "same_driver_preference" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN same_driver_preference BOOLEAN NOT NULL DEFAULT 0"))
            if "dispatch_eligible_at" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN dispatch_eligible_at DATETIME"))
            if "call_when_ready" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN call_when_ready BOOLEAN NOT NULL DEFAULT 0"))
            if "scheduling_series_id" not in ride_columns:
                conn.execute(text("ALTER TABLE health_isf_rides ADD COLUMN scheduling_series_id VARCHAR(36)"))
            conn.execute(text("UPDATE health_isf_rides SET lifecycle_state='queued' WHERE lifecycle_state IS NULL OR lifecycle_state=''"))
            conn.execute(text("UPDATE health_isf_rides SET lifecycle_state='queued' WHERE status='pending'"))
            conn.execute(text("UPDATE health_isf_rides SET lifecycle_state='assigned' WHERE status='accepted'"))
            conn.execute(text("UPDATE health_isf_rides SET lifecycle_state='in_progress' WHERE status='in_transit'"))
            conn.execute(text("UPDATE health_isf_rides SET lifecycle_state='completed' WHERE status='completed'"))
            conn.execute(text("UPDATE health_isf_rides SET lifecycle_state='cancelled' WHERE status='cancelled'"))
            conn.execute(text("UPDATE health_isf_rides SET assigned_at = COALESCE(assigned_at, accepted_at, updated_at) WHERE lifecycle_state='assigned'"))
            conn.execute(text("UPDATE health_isf_rides SET enroute_at = COALESCE(enroute_at, updated_at) WHERE lifecycle_state='driver_en_route'"))
            conn.execute(text("UPDATE health_isf_rides SET arrived_at = COALESCE(arrived_at, updated_at) WHERE lifecycle_state='arrived'"))
            conn.execute(text("UPDATE health_isf_rides SET picked_up_at = COALESCE(picked_up_at, updated_at) WHERE lifecycle_state='rider_onboard'"))
            conn.execute(text("UPDATE health_isf_rides SET transporting_at = COALESCE(transporting_at, updated_at) WHERE lifecycle_state='in_progress'"))

        if "health_isf_customer_ride_requests" in table_names:
            req_columns = {column["name"] for column in inspector.get_columns("health_isf_customer_ride_requests")}
            if "trip_type" not in req_columns:
                conn.execute(text("ALTER TABLE health_isf_customer_ride_requests ADD COLUMN trip_type VARCHAR(32)"))
            if "scheduling_metadata_json" not in req_columns:
                conn.execute(text("ALTER TABLE health_isf_customer_ride_requests ADD COLUMN scheduling_metadata_json TEXT"))
            if "linked_ride_ids_json" not in req_columns:
                conn.execute(text("ALTER TABLE health_isf_customer_ride_requests ADD COLUMN linked_ride_ids_json TEXT"))

        if "health_isf_recurring_ride_schedules" not in table_names:
            Base.metadata.tables["health_isf_recurring_ride_schedules"].create(bind=conn)
        if "health_isf_drivers" in table_names:
            driver_columns = {column["name"] for column in inspector.get_columns("health_isf_drivers")}
            if "version" not in driver_columns:
                conn.execute(text("ALTER TABLE health_isf_drivers ADD COLUMN version INTEGER NOT NULL DEFAULT 0"))
            if "auth_state" not in driver_columns:
                conn.execute(text("ALTER TABLE health_isf_drivers ADD COLUMN auth_state VARCHAR(32) NOT NULL DEFAULT 'inactive'"))
            if "availability_state" not in driver_columns:
                conn.execute(text("ALTER TABLE health_isf_drivers ADD COLUMN availability_state VARCHAR(32) NOT NULL DEFAULT 'offline'"))
            if "is_online" not in driver_columns:
                conn.execute(text("ALTER TABLE health_isf_drivers ADD COLUMN is_online BOOLEAN NOT NULL DEFAULT 0"))
            if "last_seen_at" not in driver_columns:
                conn.execute(text("ALTER TABLE health_isf_drivers ADD COLUMN last_seen_at DATETIME"))
            conn.execute(
                text(
                    "UPDATE health_isf_drivers "
                    "SET status = lower(status) "
                    "WHERE status IS NOT NULL AND status <> lower(status)"
                )
            )

        if "health_isf_ride_execution_actions" not in table_names:
            Base.metadata.tables["health_isf_ride_execution_actions"].create(bind=conn)
        else:
            ride_exec_columns = {column["name"] for column in inspector.get_columns("health_isf_ride_execution_actions")}
            if "event_id" not in ride_exec_columns:
                conn.execute(text("ALTER TABLE health_isf_ride_execution_actions ADD COLUMN event_id VARCHAR(64) NOT NULL DEFAULT ''"))
            if "sequence_number" not in ride_exec_columns:
                conn.execute(text("ALTER TABLE health_isf_ride_execution_actions ADD COLUMN sequence_number INTEGER"))
            if "monotonic_ts" not in ride_exec_columns:
                conn.execute(text("ALTER TABLE health_isf_ride_execution_actions ADD COLUMN monotonic_ts FLOAT"))
            if "source" not in ride_exec_columns:
                conn.execute(text("ALTER TABLE health_isf_ride_execution_actions ADD COLUMN source VARCHAR(64)"))
                # Optionally, backfill event_id with UUIDs for existing rows if needed
                # import uuid
                # for row in conn.execute(text("SELECT id FROM health_isf_ride_execution_actions WHERE event_id = '' OR event_id IS NULL")):
                #     conn.execute(text("UPDATE health_isf_ride_execution_actions SET event_id = :eid WHERE id = :id"), {"eid": str(uuid.uuid4()), "id": row["id"]})

        if "health_isf_driver_sessions" not in table_names:
            try:
                Base.metadata.tables["health_isf_driver_sessions"].create(bind=conn)
            except Exception:
                _SCHEMA_LOGGER.exception("health_isf_driver_sessions_create_failed")

        if "health_isf_dispatch_assignments" not in table_names:
            try:
                Base.metadata.tables["health_isf_dispatch_assignments"].create(bind=conn)
            except Exception:
                _SCHEMA_LOGGER.exception("health_isf_dispatch_assignments_create_failed")
        elif "health_isf_dispatch_assignments" in table_names:
            datetime_sql = _schema_datetime_sql(conn.dialect.name)
            dispatch_assignment_column_types = {
                "score": "FLOAT",
                "score_breakdown_json": "TEXT",
                "timeout_seconds": "INTEGER NOT NULL DEFAULT 90",
                "queued_at": datetime_sql,
                "search_started_at": datetime_sql,
                "offered_at": datetime_sql,
                "offer_expires_at": datetime_sql,
                "assigned_at": datetime_sql,
                "accepted_at": datetime_sql,
                "en_route_pickup_at": datetime_sql,
                "pickup_complete_at": datetime_sql,
                "dropoff_complete_at": datetime_sql,
                "reassignment_pending_at": datetime_sql,
                "reassignment_started_at": datetime_sql,
                "reassignment_completed_at": datetime_sql,
                "reassignment_attempt_count": "INTEGER NOT NULL DEFAULT 0",
                "reassignment_reason": "VARCHAR(128)",
                "reassignment_chain_id": "VARCHAR(64)",
                "rejected_at": datetime_sql,
                "expired_at": datetime_sql,
                "closed_reason": "VARCHAR(128)",
                "metadata_json": "TEXT",
            }
            for column_name, column_type in dispatch_assignment_column_types.items():
                _schema_add_column_if_missing(
                    conn,
                    inspector,
                    "health_isf_dispatch_assignments",
                    column_name,
                    column_type,
                )

        if "health_isf_dispatch_logs" in table_names:
            dispatch_log_columns = {column["name"] for column in inspector.get_columns("health_isf_dispatch_logs")}
            if "request_id" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN request_id VARCHAR(128)"))
            if "assignment_id" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN assignment_id VARCHAR(36)"))
            if "lifecycle_state" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN lifecycle_state VARCHAR(64)"))
            if "transition_reason" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN transition_reason VARCHAR(256)"))
            if "transition_timestamp" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN transition_timestamp DATETIME"))
            if "emitted_event_name" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN emitted_event_name VARCHAR(128)"))
            if "emitted_timestamp" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN emitted_timestamp DATETIME"))
            if "websocket_delivery_target" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN websocket_delivery_target VARCHAR(256)"))
            if "assignment_transition_source" not in dispatch_log_columns:
                conn.execute(text("ALTER TABLE health_isf_dispatch_logs ADD COLUMN assignment_transition_source VARCHAR(128)"))

        if "health_isf_operational_alerts" in table_names:
            alert_columns = {column["name"] for column in inspector.get_columns("health_isf_operational_alerts")}
            if "alert_state" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN alert_state VARCHAR(24) NOT NULL DEFAULT 'open'"))
            if "incident_key" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN incident_key VARCHAR(128)"))
            if "escalation_level" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN escalation_level INTEGER NOT NULL DEFAULT 0"))
            if "target_roles_json" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN target_roles_json TEXT"))
            if "notification_channels_json" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN notification_channels_json TEXT"))
            if "escalation_chain_json" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN escalation_chain_json TEXT"))
            if "occurrence_count" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN occurrence_count INTEGER NOT NULL DEFAULT 1"))
            if "last_seen_at" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN last_seen_at DATETIME"))
            if "acknowledged_by_user_id" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN acknowledged_by_user_id VARCHAR(36)"))
            if "acknowledged_at" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN acknowledged_at DATETIME"))
            if "escalated_at" not in alert_columns:
                conn.execute(text("ALTER TABLE health_isf_operational_alerts ADD COLUMN escalated_at DATETIME"))

        # Idempotency: one document type per completed ride.
        if "health_isf_trip_documents" in table_names:
            try:
                conn.execute(
                    text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_trip_docs_ride_type "
                        "ON health_isf_trip_documents (ride_id, document_type)"
                    )
                )
            except Exception:
                pass


# ── AI governance approvals ──────────────────────────────────────────────────

class HealthISFGovernanceApproval(Base):
    __tablename__ = "health_isf_governance_approvals"
    __table_args__ = (
        Index("idx_governance_approvals_org_created", "organization_id", "created_at"),
        Index("idx_governance_approvals_org_status", "organization_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    submitted_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    approved_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("platform_users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    action_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action_payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    approval_token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approval_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    rollback_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed", index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    tenant_scope: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    role_scope_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    audit_event_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# ── Financial engine records ─────────────────────────────────────────────────

class HealthISFTripFinancialRecord(Base):
    """Canonical financial breakdown for a completed trip."""
    __tablename__ = "health_isf_trip_financial_records"
    __table_args__ = (
        Index("idx_trip_financial_org_created", "organization_id", "created_at"),
        Index("idx_trip_financial_org_ride", "organization_id", "ride_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    trip_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ride_price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    driver_pay_usd: Mapped[float] = mapped_column(Float, nullable=False)
    platform_revenue_usd: Mapped[float] = mapped_column(Float, nullable=False)
    provider_share_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    processing_fee_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    payment_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payout_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    billing_handoff_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    is_healthcare: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    service_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    breakdown_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class HealthISFClaim(Base):
    """Healthcare reimbursement claim generated from completed trips."""
    __tablename__ = "health_isf_claims"
    __table_args__ = (
        Index("idx_claims_org_status", "organization_id", "status"),
        Index("idx_claims_org_created", "organization_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    financial_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provider_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    claim_reference: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted", index=True)
    billed_amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    service_type: Mapped[str] = mapped_column(String(128), nullable=False)
    passenger_name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class HealthISFBillingHandoff(Base):
    """Billing handoff linking trip completion to downstream billing queues."""
    __tablename__ = "health_isf_billing_handoffs"
    __table_args__ = (
        Index("idx_billing_handoff_org_ride", "organization_id", "ride_id"),
        Index("idx_billing_handoff_org_status", "organization_id", "handoff_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, unique=True, index=True,
    )
    financial_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    handoff_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ready", index=True)
    payment_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payout_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    ride_price_usd: Mapped[float] = mapped_column(Float, nullable=False)
    driver_pay_usd: Mapped[float] = mapped_column(Float, nullable=False)
    platform_revenue_usd: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class HealthISFTripDocument(Base):
    """Trip receipt / payout / billing documents generated on ride completion."""
    __tablename__ = "health_isf_trip_documents"
    __table_args__ = (
        UniqueConstraint("ride_id", "document_type", name="uq_trip_docs_ride_type"),
        Index("idx_trip_docs_org_ride", "organization_id", "ride_id"),
        Index("idx_trip_docs_org_driver", "organization_id", "driver_id"),
        Index("idx_trip_docs_org_type", "organization_id", "document_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ride_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("health_isf_rides.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    driver_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    financial_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payment_transaction_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    payout_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    reference: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="issued", index=True)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    content_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

