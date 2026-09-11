"""Pydantic payloads for the isolated Lifesaver API."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=128)
    profile_role: str | None = Field(default=None, max_length=32)
    timezone: str | None = Field(default=None, max_length=64)


class ConsentUpdate(BaseModel):
    consent_type: str = Field(..., max_length=64)
    granted: bool


class AccessibilityUpdate(BaseModel):
    large_text: bool | None = None
    high_contrast: bool | None = None
    reduce_motion: bool | None = None
    screen_reader_hints: bool | None = None


class MedicationCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    instructions: str | None = Field(default=None, max_length=512)
    schedule_times: list[str] = Field(default_factory=list)


class AppointmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    location: str | None = Field(default=None, max_length=256)
    starts_at: datetime
    notes: str | None = Field(default=None, max_length=512)


class WellnessCreate(BaseModel):
    mood: str = Field(..., min_length=1, max_length=32)
    energy: str = Field(..., min_length=1, max_length=32)
    notes: str | None = Field(default=None, max_length=512)
    notify_caregivers: bool = False


class JournalCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class ReadingCreate(BaseModel):
    reading_type: str = Field(..., max_length=32)
    value_primary: float
    value_secondary: float | None = None
    source: str = "user_entered"
    note: str | None = Field(default=None, max_length=256)


class TransportUpdate(BaseModel):
    status: str = Field(..., max_length=32)
    confirm: bool = False


class SosStart(BaseModel):
    note: str | None = Field(default=None, max_length=256)


class SosConfirm(BaseModel):
    confirm: bool
    understood_not_emergency: bool


class CircleInvite(BaseModel):
    caregiver_email: str = Field(..., min_length=3, max_length=320)
    permissions: list[str] = Field(default_factory=list)


class CirclePermissionsUpdate(BaseModel):
    permissions: list[str]


class TaskCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    assigned_caregiver_id: str | None = Field(default=None, max_length=36)
    due_at: datetime | None = None
    member_profile_id: str | None = Field(default=None, max_length=36)


class HandoffCreate(BaseModel):
    member_profile_id: str | None = Field(default=None, max_length=36)
    from_caregiver_id: str = Field(..., max_length=36)
    to_caregiver_id: str = Field(..., max_length=36)
    note: str | None = Field(default=None, max_length=256)


class AiConverse(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: str | None = Field(default=None, max_length=36)


class TransportRequestCreate(BaseModel):
    appointment_id: str | None = Field(default=None, max_length=36)
    pickup_at: datetime | None = None
    pickup_label: str = Field(..., min_length=1, max_length=160)
    destination_label: str = Field(..., min_length=1, max_length=160)
    accessibility_needs: str | None = Field(default=None, max_length=256)
    mobility_note: str | None = Field(default=None, max_length=256)
    companion_needed: bool = False


class TransportConfirm(BaseModel):
    confirm: bool


class NotificationQueue(BaseModel):
    notification_type: str = Field(..., max_length=64)
    channel: str = Field(default="email", max_length=16)
    title: str = Field(..., min_length=1, max_length=160)
    reason: str | None = Field(default=None, max_length=256)
    recipient_profile_id: str | None = Field(default=None, max_length=36)
    recipient_role: str = Field(default="caregiver", max_length=32)
    journal_body: str | None = Field(default=None, max_length=4000)
    reading_value: str | None = Field(default=None, max_length=64)


class SimulatedDeviceCreate(BaseModel):
    reading_type: str = Field(..., max_length=32)
    value_primary: float
    value_secondary: float | None = None
    recorded_at: datetime | None = None
    device_alias: str | None = Field(default=None, max_length=64)
    source: str = "simulated_device"
