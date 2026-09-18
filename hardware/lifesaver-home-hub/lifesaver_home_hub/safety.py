"""Non-diagnostic safety-event pipeline. Never contacts emergency services."""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from lifesaver_home_hub.audit import now_iso

EVENT_TYPES = frozenset({
    "POSSIBLE_FALL",
    "POSSIBLE_FALL_EVENT",
    "INACTIVITY",
    "INACTIVITY_THRESHOLD",
    "POSTURE_CHANGE",
    "DEVICE_TIPPED",
    "MOTOR_OBSTRUCTION",
    "DEVICE_OFFLINE",
    "POWER_LOSS",
    "HIGH_TEMPERATURE",
    "OBSTRUCTION_EVENT",
    "MOTION_EVENT",
})
REVIEW_STATES = frozenset({
    "DETECTED",
    "NEEDS_REVIEW",
    "ACKNOWLEDGED",
    "FALSE_ALARM",
    "ESCALATION_SIMULATED",
    "RESOLVED",
})
COPY = "Possible safety event — human review required."


def normalize_event(raw: str) -> str:
    value = (raw or "").strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "FALL": "POSSIBLE_FALL",
        "POSSIBLE_FALL_EVENT": "POSSIBLE_FALL",
        "INACTIVITY_THRESHOLD": "INACTIVITY",
        "OBSTRUCTION_EVENT": "MOTOR_OBSTRUCTION",
        "OBSTRUCTION": "MOTOR_OBSTRUCTION",
        "TIPPED": "DEVICE_TIPPED",
        "MOTION": "MOTION_EVENT",
    }
    return aliases.get(value, value)


class SafetyPipeline:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, event_type: str, *, device_id: str, source: str = "emulator", confidence: str = "low") -> dict[str, Any]:
        kind = normalize_event(event_type)
        if kind not in EVENT_TYPES:
            raise ValueError("Unsupported safety-event type.")
        row = {
            "event_id": str(uuid4()),
            "device_id": device_id,
            "event_type": kind,
            "severity_suggestion": "attention",
            "timestamp": now_iso(),
            "source": source,
            "confidence": confidence,
            "human_review_required": True,
            "acknowledgement": None,
            "resolution": None,
            "review_status": "NEEDS_REVIEW",
            "summary": COPY,
            "emergency_services_contacted": False,
            "label": "SIMULATION",
        }
        self.events.append(row)
        return row

    def review(self, event_id: str, status: str) -> dict[str, Any]:
        status = (status or "").upper()
        if status not in REVIEW_STATES:
            raise ValueError("Unsupported safety review status.")
        row = next((item for item in self.events if item["event_id"] == event_id), None)
        if row is None:
            raise KeyError("Safety event was not found.")
        row["review_status"] = status
        row["emergency_services_contacted"] = False
        if status == "ACKNOWLEDGED":
            row["acknowledgement"] = now_iso()
        if status in {"FALSE_ALARM", "RESOLVED", "ESCALATION_SIMULATED"}:
            row["resolution"] = status
            row["acknowledgement"] = row["acknowledgement"] or now_iso()
        return row

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        return list(reversed(self.events[-limit:]))
