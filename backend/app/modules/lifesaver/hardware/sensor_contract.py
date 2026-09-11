"""Non-diagnostic hardware safety-event contract."""
from __future__ import annotations

SENSOR_EVENT_TYPES = frozenset({
    "MOTION_EVENT",
    "POSTURE_CHANGE",
    "POSSIBLE_FALL_EVENT",
    "INACTIVITY_THRESHOLD",
    "OBSTRUCTION_EVENT",
    "DEVICE_TIPPED",
})

SENSOR_REVIEW_COPY = "Possible safety event — human review required."


def normalize_sensor_event(raw: str) -> str:
    value = (raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "MOTION": "MOTION_EVENT",
        "FALL": "POSSIBLE_FALL_EVENT",
        "POSSIBLE_FALL": "POSSIBLE_FALL_EVENT",
        "INACTIVITY": "INACTIVITY_THRESHOLD",
        "OBSTRUCTION": "OBSTRUCTION_EVENT",
        "TIPPED": "DEVICE_TIPPED",
    }
    return aliases.get(value, value)


def is_sensor_event(raw: str) -> bool:
    return normalize_sensor_event(raw) in SENSOR_EVENT_TYPES
