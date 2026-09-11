"""Connected-health-device ingestion foundation. Local simulation only."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.helpers import now
from app.modules.lifesaver.constants import (
    DEVICE_SIM_LABEL,
    READING_TYPES,
    READING_UNITS,
    SOURCE_EXTERNAL_RESERVED,
    SOURCE_SIMULATED_DEVICE,
    SOURCE_USER_ENTERED,
)


class FutureDeviceProvider:
    """Stub interface for Apple Health / Fitbit / Bluetooth / medical devices."""

    name = "reserved"
    makes_network_calls = False

    def ingest(self, *_args, **_kwargs):
        raise HTTPException(
            status_code=409,
            detail="EXTERNAL_DEVICE_RESERVED cannot ingest real data in Phase 2.",
        )


def normalize_reading_type(reading_type: str) -> str:
    value = (reading_type or "").strip()
    if value == "spo2":
        return "oxygen_saturation"
    return value


def validate_ingest(*, reading_type: str, source: str, recorded_at: datetime | None, device_alias: str | None) -> dict:
    normalized = normalize_reading_type(reading_type)
    if normalized not in READING_TYPES and normalized != "oxygen_saturation":
        raise HTTPException(status_code=422, detail="Unsupported reading type.")
    if source == SOURCE_EXTERNAL_RESERVED:
        FutureDeviceProvider().ingest()
    if source != SOURCE_SIMULATED_DEVICE:
        raise HTTPException(status_code=422, detail="This surface accepts simulated-device readings only.")
    if recorded_at is None:
        recorded_at = now()
    return {
        "reading_type": "oxygen_saturation" if normalized == "spo2" else normalized,
        "source": SOURCE_SIMULATED_DEVICE,
        "unit": READING_UNITS["oxygen_saturation" if normalized == "spo2" else normalized],
        "device_alias": (device_alias or "local-simulator")[:64],
        "ingestion_status": "accepted_simulated",
        "recorded_at": recorded_at,
        "label": DEVICE_SIM_LABEL,
        "device_sourced": False,
    }


def serialize_reading_flags(source: str) -> dict:
    return {
        "source": source,
        "device_sourced": False,
        "simulated_device": source == SOURCE_SIMULATED_DEVICE,
        "user_entered": source == SOURCE_USER_ENTERED,
        "external_reserved": source == SOURCE_EXTERNAL_RESERVED,
        "label": DEVICE_SIM_LABEL if source == SOURCE_SIMULATED_DEVICE else None,
    }
