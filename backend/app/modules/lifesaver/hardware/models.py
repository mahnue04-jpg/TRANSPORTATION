"""Lifesaver-owned hardware tables. Additive lifesaver_* names only."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.helpers import now, uuid4


class LifesaverDevice(Base):
    __tablename__ = "lifesaver_devices"
    __table_args__ = (
        UniqueConstraint("organization_id", "serial_number", name="uq_lifesaver_device_org_serial"),
        Index("ix_lifesaver_devices_org_profile", "organization_id", "profile_id"),
        Index("ix_lifesaver_devices_org_type", "organization_id", "device_type"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    software_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OFFLINE")
    adapter_name: Mapped[str] = mapped_column(String(64), nullable=False, default="simulated")
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    pairing_state: Mapped[str] = mapped_column(String(32), nullable=False, default="PAIRED")
    hardware_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pairing_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    state_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverDeviceCommand(Base):
    __tablename__ = "lifesaver_device_commands"
    __table_args__ = (Index("ix_lifesaver_dcmd_org_device", "organization_id", "device_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    actor_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    client_command_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    lifecycle_status: Mapped[str] = mapped_column(String(32), nullable=False, default="COMPLETED")
    adapter_type: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    response_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(256), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class LifesaverDeviceEvent(Base):
    __tablename__ = "lifesaver_device_events"
    __table_args__ = (Index("ix_lifesaver_devent_org_device", "organization_id", "device_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="needs_human_review")
    summary: Mapped[str] = mapped_column(String(256), nullable=False)
    emergency_services_contacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    confidence: Mapped[str | None] = mapped_column(String(16), nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEEDS_REVIEW")
    escalation_state: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifesaverVideoSession(Base):
    __tablename__ = "lifesaver_video_sessions"
    __table_args__ = (Index("ix_lifesaver_vsession_org_device", "organization_id", "device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="requested")
    session_phase: Mapped[str] = mapped_column(String(32), nullable=False, default="REQUESTED")
    participant_role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="local_simulation")
    privacy_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    media_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LifesaverDevicePairing(Base):
    __tablename__ = "lifesaver_device_pairings"
    __table_args__ = (Index("ix_lifesaver_pair_org_state", "organization_id", "pairing_state"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    device_type: Mapped[str] = mapped_column(String(32), nullable=False)
    hardware_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    serial_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    local_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pairing_state: Mapped[str] = mapped_column(String(32), nullable=False, default="DISCOVERED")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pairing_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    capabilities_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverSafetyEvent(Base):
    __tablename__ = "lifesaver_safety_events"
    __table_args__ = (Index("ix_lifesaver_safety_org_device", "organization_id", "device_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[str] = mapped_column(String(16), nullable=False, default="low")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated")
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="NEEDS_REVIEW")
    escalation_state: Mapped[str] = mapped_column(String(32), nullable=False, default="none")
    summary: Mapped[str] = mapped_column(String(256), nullable=False)
    simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    emergency_services_contacted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class LifesaverDeviceCapability(Base):
    __tablename__ = "lifesaver_device_capabilities"
    __table_args__ = (Index("ix_lifesaver_dcap_org_device", "organization_id", "device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    capability_name: Mapped[str] = mapped_column(String(64), nullable=False)
    present: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LifesaverHardwareSession(Base):
    __tablename__ = "lifesaver_hardware_sessions"
    __table_args__ = (Index("ix_lifesaver_hsession_org_device", "organization_id", "device_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uuid4)
    organization_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    profile_id: Mapped[str] = mapped_column(String(36), nullable=False)
    video_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    session_phase: Mapped[str] = mapped_column(String(32), nullable=False, default="REQUESTED")
    participant_role: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    media_stored: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


HARDWARE_MODELS = (
    LifesaverDevice,
    LifesaverDeviceCommand,
    LifesaverDeviceEvent,
    LifesaverVideoSession,
    LifesaverDevicePairing,
    LifesaverDeviceCapability,
    LifesaverSafetyEvent,
    LifesaverHardwareSession,
)

HARDWARE_COLUMN_ENSURES = {
    "lifesaver_devices": {
        "adapter_type": "VARCHAR(32) DEFAULT 'simulated'",
        "pairing_state": "VARCHAR(32) DEFAULT 'PAIRED'",
        "hardware_model": "VARCHAR(64)",
        "local_ip": "VARCHAR(64)",
        "pairing_token": "VARCHAR(64)",
    },
    "lifesaver_device_commands": {
        "client_command_id": "VARCHAR(64)",
        "lifecycle_status": "VARCHAR(32) DEFAULT 'COMPLETED'",
        "adapter_type": "VARCHAR(32) DEFAULT 'simulated'",
        "response_code": "VARCHAR(32)",
        "error_message": "VARCHAR(256)",
        "started_at": "DATETIME",
        "completed_at": "DATETIME",
    },
    "lifesaver_device_events": {
        "confidence": "VARCHAR(16)",
        "review_status": "VARCHAR(32) DEFAULT 'NEEDS_REVIEW'",
        "escalation_state": "VARCHAR(32) DEFAULT 'none'",
        "acknowledged_by": "VARCHAR(36)",
        "source": "VARCHAR(32) DEFAULT 'simulated'",
        "acknowledged_at": "DATETIME",
    },
    "lifesaver_video_sessions": {
        "session_phase": "VARCHAR(32) DEFAULT 'REQUESTED'",
        "participant_role": "VARCHAR(32) DEFAULT 'user'",
    },
}
