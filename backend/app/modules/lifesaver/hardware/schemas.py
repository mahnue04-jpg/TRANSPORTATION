"""Pydantic contracts for Lifesaver hardware simulation."""
from __future__ import annotations

from pydantic import BaseModel, Field


class SimulatedDeviceCreate(BaseModel):
    device_type: str
    display_name: str | None = None
    serial_number: str | None = Field(default=None, max_length=64)


class HardwareCommand(BaseModel):
    command: str
    motion_detected: bool | None = None
    client_command_id: str | None = Field(default=None, max_length=64)
    adapter_type: str | None = Field(default=None, max_length=32)


class VideoSessionCreate(BaseModel):
    note: str | None = Field(default=None, max_length=120)
    participant_role: str | None = Field(default="user", max_length=32)


class DiscoverRequest(BaseModel):
    device_type: str
    local_ip: str | None = Field(default="127.0.0.1", max_length=64)
    hardware_model: str | None = Field(default=None, max_length=64)
    serial_number: str | None = Field(default=None, max_length=64)


class PairConfirm(BaseModel):
    confirm: bool = False
    adapter_type: str | None = Field(default="simulated", max_length=32)


class SafetyReviewAction(BaseModel):
    review_status: str = Field(..., max_length=32)


class SafetyEventAction(BaseModel):
    confirm: bool = True
