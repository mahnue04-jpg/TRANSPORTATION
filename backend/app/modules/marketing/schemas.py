"""Pydantic schemas for isolated marketing lead capture."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

LEAD_TYPES = frozenset({"provider_interest", "contact", "driver_interest"})
ORG_TYPES = frozenset(
    {
        "hospital",
        "clinic",
        "behavioral_health",
        "assisted_living",
        "skilled_nursing",
        "dialysis",
        "county_community",
        "other",
    }
)
CONTACT_METHODS = frozenset({"email", "phone", "either"})
MONTHLY_RIDE_BANDS = frozenset(
    {"1-25", "26-75", "76-200", "200+", "unsure", ""}
)


class MarketingLeadCreate(BaseModel):
    lead_type: Literal["provider_interest", "contact", "driver_interest"]
    organization_name: str | None = Field(default=None, max_length=256)
    contact_name: str = Field(min_length=2, max_length=128)
    work_email: str = Field(min_length=5, max_length=320)
    phone: str | None = Field(default=None, max_length=64)
    organization_type: str | None = Field(default=None, max_length=64)
    estimated_monthly_rides: str | None = Field(default=None, max_length=64)
    service_area: str | None = Field(default=None, max_length=256)
    transportation_needs: str | None = Field(default=None, max_length=4000)
    preferred_contact_method: str | None = Field(default=None, max_length=32)
    subject: str | None = Field(default=None, max_length=64)
    message: str | None = Field(default=None, max_length=4000)
    consent: bool = False
    source_path: str | None = Field(default=None, max_length=256)
    lead_source: str | None = Field(default=None, max_length=128)
    # Honeypot — must remain empty. Bots that fill it are rejected silently.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("contact_name", "organization_name", "service_area", "work_email", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("work_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = (value or "").strip().lower()
        if not _EMAIL_RE.match(email):
            raise ValueError("Enter a valid email address")
        return email

    @field_validator("organization_type")
    @classmethod
    def validate_org_type(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if value not in ORG_TYPES:
            raise ValueError("Unsupported organization type")
        return value

    @field_validator("preferred_contact_method")
    @classmethod
    def validate_contact_method(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        if value not in CONTACT_METHODS:
            raise ValueError("Unsupported preferred contact method")
        return value

    @field_validator("estimated_monthly_rides")
    @classmethod
    def validate_monthly_rides(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if value not in MONTHLY_RIDE_BANDS:
            raise ValueError("Unsupported estimated monthly rides value")
        return value or None
