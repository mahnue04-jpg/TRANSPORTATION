"""Observation-quality protections for simulated and manual health ingest.

Software sanity checks only. This module does not diagnose, interpret, or
claim a medical device is connected.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

from app.helpers import now
from app.modules.lifesaver.connected_health.constants import READING_KINDS
from app.modules.lifesaver.constants import (
    READING_TYPES,
    READING_UNITS,
    SOURCE_EXTERNAL_RESERVED,
    SOURCE_SIMULATED,
    SOURCE_SIMULATED_DEVICE,
    SOURCE_USER_ENTERED,
)

QUALITY_VALID = "VALID"
QUALITY_STALE = "STALE"
QUALITY_DUPLICATE = "DUPLICATE"
QUALITY_INVALID = "INVALID"
QUALITY_MISSING = "MISSING"
QUALITY_UNSUPPORTED = "UNSUPPORTED"
QUALITY_OUT_OF_ORDER = "OUT_OF_ORDER"

QUALITY_STATUSES = frozenset({
    QUALITY_VALID,
    QUALITY_STALE,
    QUALITY_DUPLICATE,
    QUALITY_INVALID,
    QUALITY_MISSING,
    QUALITY_UNSUPPORTED,
    QUALITY_OUT_OF_ORDER,
})

SOURCE_MANUAL = "manual_entry"
SOURCE_CONNECTED_SIM = "connected_simulated"

SUPPORTED_SOURCES = frozenset({
    SOURCE_USER_ENTERED,
    SOURCE_SIMULATED,
    SOURCE_SIMULATED_DEVICE,
    SOURCE_MANUAL,
    SOURCE_CONNECTED_SIM,
    "home_hub_simulated",
})

SOURCE_TYPE_MANUAL = "manual_entry"
SOURCE_TYPE_SIMULATED = "simulated"

_SOURCE_TYPES = {
    SOURCE_USER_ENTERED: SOURCE_TYPE_MANUAL,
    SOURCE_MANUAL: SOURCE_TYPE_MANUAL,
    SOURCE_SIMULATED: SOURCE_TYPE_SIMULATED,
    SOURCE_SIMULATED_DEVICE: SOURCE_TYPE_SIMULATED,
    SOURCE_CONNECTED_SIM: SOURCE_TYPE_SIMULATED,
    "home_hub_simulated": SOURCE_TYPE_SIMULATED,
}

SUPPORTED_MEASUREMENTS = frozenset(READING_TYPES | READING_KINDS)

# Software bounds only. Not clinical reference ranges.
_RANGES: dict[str, dict[str, tuple[float, float]]] = {
    "blood_pressure": {"primary": (50.0, 260.0), "secondary": (20.0, 180.0)},
    "glucose": {"primary": (20.0, 800.0)},
    "oxygen_saturation": {"primary": (50.0, 100.0)},
    "spo2": {"primary": (50.0, 100.0)},
    "temperature": {"primary": (90.0, 110.0)},
    "weight": {"primary": (20.0, 800.0)},
    "heart_rate": {"primary": (20.0, 250.0)},
    "activity": {"primary": (0.0, 200000.0)},
}
_TEMP_C_RANGE = (32.0, 43.0)

_UNIT_REQUIRED = frozenset({
    "blood_pressure",
    "glucose",
    "oxygen_saturation",
    "spo2",
    "temperature",
    "weight",
    "heart_rate",
})

STALE_SECONDS = 24 * 60 * 60
FUTURE_GRACE_SECONDS = 5 * 60

SIMULATED_SOURCES = frozenset({
    SOURCE_SIMULATED,
    SOURCE_SIMULATED_DEVICE,
    SOURCE_CONNECTED_SIM,
    "home_hub_simulated",
})


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def normalize_measurement_type(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value == "spo2":
        return "oxygen_saturation"
    return value


def source_type_for(source: str | None) -> str:
    return _SOURCE_TYPES.get((source or "").strip().lower(), "unknown")


def is_simulated_source(source: str | None) -> bool:
    return (source or "").strip().lower() in SIMULATED_SOURCES


def default_unit(measurement_type: str, unit: str | None) -> str | None:
    if unit is not None and str(unit).strip() == "":
        return ""
    if unit:
        return str(unit).strip()
    key = normalize_measurement_type(measurement_type)
    if key in READING_UNITS:
        return READING_UNITS[key]
    if measurement_type in READING_UNITS:
        return READING_UNITS[measurement_type]
    return unit


def fingerprint(
    *,
    measurement_type: str,
    value: Any,
    value_secondary: Any = None,
    unit: str | None,
    source: str | None,
    captured_at: datetime | None,
) -> str:
    ts = ""
    stamped = _aware(captured_at)
    if stamped is not None:
        ts = stamped.replace(microsecond=0).isoformat()
    raw = "|".join(
        [
            normalize_measurement_type(measurement_type),
            "" if value is None else str(value),
            "" if value_secondary is None else str(value_secondary),
            (unit or "").strip(),
            (source or "").strip().lower(),
            ts,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


@dataclass
class ObservationAssessment:
    quality_status: str
    quality_reason: str
    trusted: bool
    source: str
    source_type: str
    measurement_type: str
    value: float | None
    value_secondary: float | None
    unit: str | None
    captured_at: datetime
    received_at: datetime
    simulated: bool
    fingerprint: str
    would_alert: bool
    provenance_id: str | None = None
    replayed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_type": self.source_type,
            "measurement_type": self.measurement_type,
            "value": self.value,
            "value_secondary": self.value_secondary,
            "unit": self.unit,
            "captured_at": self.captured_at.isoformat() if self.captured_at else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "quality_status": self.quality_status,
            "quality_reason": self.quality_reason,
            "simulated": self.simulated,
            "trusted": self.trusted,
            "provenance_id": self.provenance_id,
            "observation_fingerprint": self.fingerprint,
            "would_alert": self.would_alert,
        }


def _mark(
    status: str,
    reason: str,
    *,
    source: str,
    measurement_type: str,
    value: float | None,
    value_secondary: float | None,
    unit: str | None,
    captured_at: datetime,
    received_at: datetime,
    fingerprint_value: str,
    replayed: bool = False,
) -> ObservationAssessment:
    trusted = status == QUALITY_VALID
    return ObservationAssessment(
        quality_status=status,
        quality_reason=reason,
        trusted=trusted,
        source=source,
        source_type=source_type_for(source),
        measurement_type=measurement_type,
        value=value,
        value_secondary=value_secondary,
        unit=unit,
        captured_at=captured_at,
        received_at=received_at,
        simulated=is_simulated_source(source),
        fingerprint=fingerprint_value,
        would_alert=trusted,
        replayed=replayed,
    )


def assess(
    *,
    measurement_type: str | None,
    value: Any,
    value_secondary: Any = None,
    unit: str | None = None,
    source: str | None = None,
    source_type: str | None = None,
    captured_at: datetime | None = None,
    received_at: datetime | None = None,
    prior_fingerprints: Iterable[str] | None = None,
    latest_captured_at: datetime | None = None,
    replayed: bool = False,
    unit_explicitly_missing: bool = False,
) -> ObservationAssessment:
    received = _aware(received_at) or now()
    captured = _aware(captured_at) or received
    source_value = (source or SOURCE_SIMULATED).strip().lower()
    raw_type = (measurement_type or "").strip()
    normalized_type = normalize_measurement_type(raw_type)
    resolved_unit = default_unit(raw_type or normalized_type, unit)
    if unit_explicitly_missing:
        resolved_unit = ""
    primary = _finite(value)
    secondary = _finite(value_secondary)
    digest = fingerprint(
        measurement_type=normalized_type or raw_type,
        value=primary if primary is not None else value,
        value_secondary=secondary if secondary is not None else value_secondary,
        unit=resolved_unit,
        source=source_value,
        captured_at=captured,
    )

    def finish(status: str, reason: str, **extra: Any) -> ObservationAssessment:
        row = _mark(
            status,
            reason,
            source=source_value,
            measurement_type=normalized_type or raw_type or "unknown",
            value=primary,
            value_secondary=secondary,
            unit=resolved_unit,
            captured_at=captured,
            received_at=received,
            fingerprint_value=digest,
            replayed=replayed,
        )
        if extra:
            for key, item in extra.items():
                setattr(row, key, item)
        if source_type:
            row.source_type = source_type
        return row

    if replayed:
        return finish(QUALITY_DUPLICATE, "Replayed observation matched a stored request identifier.")
    if source_value == SOURCE_EXTERNAL_RESERVED or source_value not in SUPPORTED_SOURCES:
        return finish(QUALITY_UNSUPPORTED, "Unsupported observation source.")
    if not normalized_type or normalized_type not in SUPPORTED_MEASUREMENTS:
        return finish(QUALITY_UNSUPPORTED, "Unsupported measurement type.")
    if normalized_type == "blood_pressure" and secondary is None and value_secondary is None:
        return finish(QUALITY_MISSING, "Blood pressure is missing a diastolic value.")
    if primary is None:
        if value is None or value == "":
            return finish(QUALITY_MISSING, "Observation is missing a numeric value.")
        return finish(QUALITY_INVALID, "Observation value is not a finite number.")
    if normalized_type in _UNIT_REQUIRED and not (resolved_unit or "").strip():
        return finish(QUALITY_MISSING, "Observation is missing a unit.")
    if normalized_type == "blood_pressure" and value_secondary is not None and secondary is None:
        return finish(QUALITY_INVALID, "Diastolic value is not a finite number.")

    bounds = _RANGES.get(normalized_type) or _RANGES.get(raw_type)
    if normalized_type == "temperature" and (resolved_unit or "").lower() in {"c", "celsius", "°c"}:
        bounds = {"primary": _TEMP_C_RANGE}
    if bounds:
        low, high = bounds["primary"]
        if primary < low or primary > high:
            return finish(QUALITY_INVALID, "Observation value is outside the accepted software range.")
        if "secondary" in bounds and secondary is not None:
            slow, shigh = bounds["secondary"]
            if secondary < slow or secondary > shigh:
                return finish(QUALITY_INVALID, "Secondary observation value is outside the accepted software range.")

    if captured > received.replace(microsecond=0) and (captured - received).total_seconds() > FUTURE_GRACE_SECONDS:
        return finish(QUALITY_INVALID, "Observation timestamp is in the future.")

    prior = {item for item in (prior_fingerprints or []) if item}
    if digest in prior:
        return finish(QUALITY_DUPLICATE, "Duplicate observation fingerprint.")

    age_seconds = (received - captured).total_seconds()
    if age_seconds > STALE_SECONDS:
        return finish(QUALITY_STALE, "Observation is older than the stale-reading window.")

    latest = _aware(latest_captured_at)
    if latest is not None and captured < latest:
        return finish(QUALITY_OUT_OF_ORDER, "Observation timestamp is older than the latest stored reading of this type.")

    return finish(QUALITY_VALID, "Observation passed software quality checks.")


def trusted_status(quality_status: str | None, *, ingestion_status: str | None = None) -> bool:
    if quality_status:
        return quality_status == QUALITY_VALID
    return (ingestion_status or "accepted") in {"accepted", "accepted_simulated"}


def row_quality(row: Any) -> str:
    status = getattr(row, "quality_status", None)
    if status:
        return str(status)
    if trusted_status(None, ingestion_status=getattr(row, "ingestion_status", None)):
        return QUALITY_VALID
    return QUALITY_INVALID


def normalize_record(row: Any, *, default_source: str | None = None) -> dict[str, Any]:
    measurement = getattr(row, "reading_type", None) or getattr(row, "reading_kind", None) or ""
    source = getattr(row, "source", None) or default_source or SOURCE_SIMULATED
    captured = _aware(getattr(row, "captured_at", None) or getattr(row, "recorded_at", None))
    received = _aware(getattr(row, "received_at", None) or getattr(row, "created_at", None) or captured)
    quality = row_quality(row)
    simulated = bool(getattr(row, "simulated", is_simulated_source(source)))
    return {
        "id": getattr(row, "id", None),
        "source": source,
        "source_type": getattr(row, "source_type", None) or source_type_for(source),
        "measurement_type": normalize_measurement_type(measurement),
        "value": getattr(row, "value_primary", None),
        "value_secondary": getattr(row, "value_secondary", None),
        "unit": getattr(row, "unit", None),
        "captured_at": captured.isoformat() if captured else None,
        "received_at": received.isoformat() if received else None,
        "quality_status": quality,
        "quality_reason": getattr(row, "quality_reason", None) or "",
        "simulated": simulated,
        "trusted": trusted_status(quality, ingestion_status=getattr(row, "ingestion_status", None)),
        "provenance_id": getattr(row, "provenance_id", None) or getattr(row, "id", None),
        "observation_fingerprint": getattr(row, "observation_fingerprint", None),
    }


def apply_fields(target: Any, assessment: ObservationAssessment, *, provenance_id: str | None = None) -> None:
    assessment.provenance_id = provenance_id or getattr(target, "id", None)
    if hasattr(target, "quality_status"):
        target.quality_status = assessment.quality_status
    if hasattr(target, "quality_reason"):
        target.quality_reason = assessment.quality_reason[:160]
    if hasattr(target, "source_type"):
        target.source_type = assessment.source_type
    if hasattr(target, "captured_at"):
        target.captured_at = assessment.captured_at
    if hasattr(target, "received_at"):
        target.received_at = assessment.received_at
    if hasattr(target, "trusted"):
        target.trusted = assessment.trusted
    if hasattr(target, "provenance_id"):
        target.provenance_id = assessment.provenance_id
    if hasattr(target, "observation_fingerprint"):
        target.observation_fingerprint = assessment.fingerprint
    if hasattr(target, "simulated"):
        target.simulated = assessment.simulated
