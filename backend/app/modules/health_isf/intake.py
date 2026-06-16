"""Ride intake automation helpers for enterprise dispatch preparation."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from app.helpers import now

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")


def sanitize_text(value: str | None, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = _CONTROL_RE.sub("", str(value))
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if max_len is not None:
        cleaned = cleaned[:max_len]
    return cleaned or None


def normalize_priority_tag(tag: str | None) -> str:
    value = (sanitize_text(tag, max_len=32) or "normal").lower()
    if value in {"emergency", "urgent", "high", "normal", "low"}:
        return value
    return "normal"


def calculate_duration_minutes(distance_miles: float) -> int:
    # Conservative enterprise assumption for mixed urban medical transport.
    mph = 25.0
    computed = int(round((max(distance_miles, 0.1) / mph) * 60.0))
    return max(computed, 1)


def calculate_priority_score(
    *,
    priority_tag: str,
    service_type: str,
    appointment_time: datetime | None,
    distance_miles: float,
    is_emergency: bool,
) -> float:
    score = 50.0
    tag = normalize_priority_tag(priority_tag)
    if tag == "emergency":
        score += 45.0
    elif tag in {"urgent", "high"}:
        score += 25.0
    elif tag == "low":
        score -= 12.0

    if is_emergency:
        score += 35.0

    service = (sanitize_text(service_type, max_len=128) or "").lower()
    if "dialysis" in service:
        score += 8.0
    if "oncology" in service or "critical" in service:
        score += 10.0

    if appointment_time is not None:
        delta_minutes = int((appointment_time - now()).total_seconds() / 60)
        if delta_minutes <= 30:
            score += 20.0
        elif delta_minutes <= 90:
            score += 10.0

    if distance_miles >= 20:
        score += 6.0
    elif distance_miles <= 3:
        score -= 2.0

    return max(0.0, min(100.0, round(score, 2)))


def build_ai_dispatch_context(
    *,
    organization_id: str,
    service_type: str,
    priority_tag: str,
    priority_score: float,
    estimated_distance_miles: float,
    estimated_duration_minutes: int,
    appointment_time: datetime | None,
    recurring_trip_pattern: dict[str, Any] | None,
    is_emergency: bool,
) -> dict[str, Any]:
    return {
        "version": "v1",
        "organization_id": organization_id,
        "routing_profile": "health_isf_dispatch",
        "service_type": sanitize_text(service_type, max_len=128),
        "priority_tag": normalize_priority_tag(priority_tag),
        "priority_score": priority_score,
        "estimated_distance_miles": estimated_distance_miles,
        "estimated_duration_minutes": estimated_duration_minutes,
        "appointment_time": appointment_time.isoformat() if appointment_time else None,
        "recurring_trip_pattern": recurring_trip_pattern or None,
        "is_emergency": is_emergency,
    }


def build_intake_fingerprint(
    *,
    organization_id: str,
    passenger_name: str,
    passenger_phone: str,
    pickup_address: str,
    dropoff_address: str,
    service_type: str,
    provider_id: str,
    appointment_time: datetime | None,
) -> str:
    basis = {
        "organization_id": organization_id,
        "passenger_name": sanitize_text(passenger_name, max_len=256),
        "passenger_phone": sanitize_text(passenger_phone, max_len=20),
        "pickup_address": sanitize_text(pickup_address, max_len=512),
        "dropoff_address": sanitize_text(dropoff_address, max_len=512),
        "service_type": sanitize_text(service_type, max_len=128),
        "provider_id": provider_id,
        "appointment_time": appointment_time.isoformat() if appointment_time else None,
    }
    payload = json.dumps(basis, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
