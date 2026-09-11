"""Request bodies for connected-health simulation surfaces."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectedDeviceCreate(BaseModel):
    device_type: str
    manufacturer: str | None = Field(default="unspecified", max_length=80)
    model: str | None = Field(default="simulated", max_length=80)
    device_alias: str | None = Field(default="Simulated device", max_length=80)
    connection_method: str | None = Field(default="simulated", max_length=32)
    serial_last4: str | None = Field(default=None, max_length=4)
    battery_percent: int | None = Field(default=None, ge=0, le=100)
    client_request_id: str | None = Field(default=None, max_length=64)
    member_profile_id: str | None = Field(default=None, max_length=36)


class ConnectedReadingCreate(BaseModel):
    reading_kind: str
    value_primary: float | None = None
    value_secondary: float | None = None
    unit: str | None = Field(default=None, max_length=16)
    data_quality: str | None = Field(default="unknown", max_length=16)
    flag_for_review: bool = False
    member_profile_id: str | None = Field(default=None, max_length=36)


class HomeTestKitCreate(BaseModel):
    test_category: str
    manufacturer_or_lab: str | None = Field(default="unspecified", max_length=80)
    kit_id_last4: str | None = Field(default=None, max_length=4)
    expires_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=256)
    client_request_id: str | None = Field(default=None, max_length=64)
    member_profile_id: str | None = Field(default=None, max_length=36)


class KitTransition(BaseModel):
    status: str | None = None
    member_profile_id: str | None = Field(default=None, max_length=36)


class ResultDocumentCreate(BaseModel):
    source: str = "user_uploaded"
    document_reference: str = Field(default="ref-redacted", max_length=80)
    kit_id: str | None = Field(default=None, max_length=36)
    flag_for_review: bool = False
    member_profile_id: str | None = Field(default=None, max_length=36)


class ShareRequest(BaseModel):
    member_profile_id: str | None = Field(default=None, max_length=36)
