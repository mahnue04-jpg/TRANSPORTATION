"""Pydantic contracts for Nova freight shipment intake."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EQUIPMENT_TYPES = (
    "van",
    "cargo_van",
    "box_truck",
    "straight_truck",
    "dry_van",
    "reefer",
    "flatbed",
    "other",
)

WEIGHT_UNITS = ("lb", "kg")

SHIPMENT_STATUSES = (
    "draft",
    "requested",
    "ready_for_dispatch",
    "offered",
    "assigned",
    "accepted",
    "en_route_to_pickup",
    "arrived_pickup",
    "picked_up",
    "in_transit",
    "arrived_delivery",
    "delivered",
    "completed",
    "cancelled",
)

PRE_DISPATCH_STATUSES = frozenset({"draft", "requested", "ready_for_dispatch"})
EquipmentType = Literal[
    "van",
    "cargo_van",
    "box_truck",
    "straight_truck",
    "dry_van",
    "reefer",
    "flatbed",
    "other",
]


def _require_text(value: str | None, field_name: str, *, min_len: int = 2) -> str:
    text = str(value or "").strip()
    if len(text) < min_len:
        raise ValueError(f"{field_name} is required")
    return text


class NovaFreightShipmentCreate(BaseModel):
    customer_name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    pickup_address: str
    pickup_city: str
    pickup_state: str
    pickup_zip: str
    pickup_contact: str | None = None
    pickup_phone: str | None = None
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None
    delivery_address: str
    delivery_city: str
    delivery_state: str
    delivery_zip: str
    delivery_contact: str | None = None
    delivery_phone: str | None = None
    delivery_window_start: datetime | None = None
    delivery_window_end: datetime | None = None
    commodity: str
    quantity: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str = "lb"
    piece_count: int | None = None
    pallet_count: int | None = None
    length_in: Decimal | None = None
    width_in: Decimal | None = None
    height_in: Decimal | None = None
    special_handling_notes: str | None = None
    hazardous: bool = False
    temperature_controlled: bool = False
    fragile: bool = False
    equipment_type: EquipmentType = "cargo_van"
    quoted_amount: Decimal | None = None
    currency: str = "USD"

    @field_validator(
        "customer_name",
        "pickup_address",
        "pickup_city",
        "pickup_state",
        "pickup_zip",
        "delivery_address",
        "delivery_city",
        "delivery_state",
        "delivery_zip",
        "commodity",
        mode="before",
    )
    @classmethod
    def _required_text(cls, value: object, info) -> str:
        return _require_text(str(value) if value is not None else "", info.field_name)

    @field_validator("contact_email", mode="before")
    @classmethod
    def _optional_email(cls, value: object) -> str | None:
        text = str(value or "").strip()
        if not text:
            return None
        if "@" not in text or "." not in text.split("@")[-1]:
            raise ValueError("contact_email must be a valid email address")
        return text.lower()

    @field_validator("weight_unit", mode="before")
    @classmethod
    def _weight_unit(cls, value: object) -> str:
        unit = str(value or "lb").strip().lower()
        if unit not in WEIGHT_UNITS:
            raise ValueError("weight_unit must be lb or kg")
        return unit

    @field_validator("quantity", "weight", "length_in", "width_in", "height_in", "quoted_amount", mode="before")
    @classmethod
    def _positive_decimal(cls, value: object, info) -> Decimal | None:
        if value in (None, ""):
            return None
        number = Decimal(str(value))
        if number <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return number

    @field_validator("piece_count", "pallet_count", mode="before")
    @classmethod
    def _non_negative_int(cls, value: object, info) -> int | None:
        if value in (None, ""):
            return None
        number = int(value)
        if number < 0:
            raise ValueError(f"{info.field_name} cannot be negative")
        return number

    @model_validator(mode="after")
    def _windows(self) -> "NovaFreightShipmentCreate":
        if self.pickup_window_start and self.pickup_window_end and self.pickup_window_end < self.pickup_window_start:
            raise ValueError("pickup_window_end must be on or after pickup_window_start")
        if self.delivery_window_start and self.delivery_window_end and self.delivery_window_end < self.delivery_window_start:
            raise ValueError("delivery_window_end must be on or after delivery_window_start")
        return self


class NovaFreightShipmentUpdate(BaseModel):
    customer_name: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    pickup_address: str | None = None
    pickup_city: str | None = None
    pickup_state: str | None = None
    pickup_zip: str | None = None
    pickup_contact: str | None = None
    pickup_phone: str | None = None
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None
    delivery_address: str | None = None
    delivery_city: str | None = None
    delivery_state: str | None = None
    delivery_zip: str | None = None
    delivery_contact: str | None = None
    delivery_phone: str | None = None
    delivery_window_start: datetime | None = None
    delivery_window_end: datetime | None = None
    commodity: str | None = None
    quantity: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str | None = None
    piece_count: int | None = None
    pallet_count: int | None = None
    length_in: Decimal | None = None
    width_in: Decimal | None = None
    height_in: Decimal | None = None
    special_handling_notes: str | None = None
    hazardous: bool | None = None
    temperature_controlled: bool | None = None
    fragile: bool | None = None
    equipment_type: EquipmentType | None = None
    quoted_amount: Decimal | None = None
    currency: str | None = None

    @field_validator(
        "customer_name",
        "pickup_address",
        "pickup_city",
        "pickup_state",
        "pickup_zip",
        "delivery_address",
        "delivery_city",
        "delivery_state",
        "delivery_zip",
        "commodity",
        mode="before",
    )
    @classmethod
    def _optional_required_text(cls, value: object, info) -> str | None:
        if value is None:
            return None
        return _require_text(str(value), info.field_name)

    @field_validator("contact_email", mode="before")
    @classmethod
    def _optional_email(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if "@" not in text or "." not in text.split("@")[-1]:
            raise ValueError("contact_email must be a valid email address")
        return text.lower()

    @field_validator("weight_unit", mode="before")
    @classmethod
    def _weight_unit(cls, value: object) -> str | None:
        if value is None:
            return None
        unit = str(value).strip().lower()
        if unit not in WEIGHT_UNITS:
            raise ValueError("weight_unit must be lb or kg")
        return unit

    @field_validator("quantity", "weight", "length_in", "width_in", "height_in", "quoted_amount", mode="before")
    @classmethod
    def _positive_decimal(cls, value: object, info) -> Decimal | None:
        if value in (None, ""):
            return None
        number = Decimal(str(value))
        if number <= 0:
            raise ValueError(f"{info.field_name} must be greater than 0")
        return number

    @field_validator("piece_count", "pallet_count", mode="before")
    @classmethod
    def _non_negative_int(cls, value: object, info) -> int | None:
        if value in (None, ""):
            return None
        number = int(value)
        if number < 0:
            raise ValueError(f"{info.field_name} cannot be negative")
        return number

    @model_validator(mode="after")
    def _windows(self) -> "NovaFreightShipmentUpdate":
        if self.pickup_window_start and self.pickup_window_end and self.pickup_window_end < self.pickup_window_start:
            raise ValueError("pickup_window_end must be on or after pickup_window_start")
        if self.delivery_window_start and self.delivery_window_end and self.delivery_window_end < self.delivery_window_start:
            raise ValueError("delivery_window_end must be on or after delivery_window_start")
        return self


class NovaFreightShipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    shipment_id: str
    organization_id: str
    shipper_user_id: str | None = None
    status: str
    customer_name: str
    contact_name: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    pickup_address: str
    pickup_city: str
    pickup_state: str
    pickup_zip: str
    pickup_contact: str | None = None
    pickup_phone: str | None = None
    pickup_window_start: datetime | None = None
    pickup_window_end: datetime | None = None
    delivery_address: str
    delivery_city: str
    delivery_state: str
    delivery_zip: str
    delivery_contact: str | None = None
    delivery_phone: str | None = None
    delivery_window_start: datetime | None = None
    delivery_window_end: datetime | None = None
    commodity: str
    quantity: Decimal | None = None
    weight: Decimal | None = None
    weight_unit: str
    piece_count: int | None = None
    pallet_count: int | None = None
    length_in: Decimal | None = None
    width_in: Decimal | None = None
    height_in: Decimal | None = None
    special_handling_notes: str | None = None
    hazardous: bool
    temperature_controlled: bool
    fragile: bool
    equipment_type: str
    quoted_amount: Decimal | None = None
    carrier_payout_amount: Decimal | None = None
    amicor_margin: Decimal | None = None
    currency: str
    proof_of_pickup_ref: str | None = None
    proof_of_delivery_ref: str | None = None
    created_at: datetime
    updated_at: datetime
