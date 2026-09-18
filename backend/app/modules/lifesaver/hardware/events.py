"""Safe hardware event helpers. Never store media or call emergency services."""
from __future__ import annotations

import json
from typing import Any

from app.helpers import now
from app.modules.lifesaver.hardware.models import LifesaverDeviceEvent
from app.modules.lifesaver.hardware.registry import FALL_REVIEW_COPY


def serialize_event(row: LifesaverDeviceEvent) -> dict[str, Any]:
    review = getattr(row, "review_status", None) or (
        "NEEDS_REVIEW" if row.status == "needs_human_review" else "ACKNOWLEDGED"
    )
    return {
        "id": row.id,
        "event_id": row.id,
        "device_id": row.device_id,
        "event_type": row.event_type,
        "status": row.status,
        "review_status": review,
        "confidence": getattr(row, "confidence", None) or "low",
        "source": getattr(row, "source", None) or "simulated",
        "escalation_state": getattr(row, "escalation_state", None) or "none",
        "summary": row.summary,
        "needs_human_review": row.status == "needs_human_review" or review == "NEEDS_REVIEW",
        "emergency_services_contacted": False,
        "simulated": True,
        "label": "SIMULATION",
        "clinical": False,
        "detected_at": row.created_at.isoformat() if row.created_at else None,
        "acknowledged_by": getattr(row, "acknowledged_by", None),
        "acknowledged_at": row.acknowledged_at.isoformat() if getattr(row, "acknowledged_at", None) else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


def new_power_event(
    *,
    organization_id: str,
    device_id: str,
    profile_id: str,
    event_type: str,
    from_state: str,
    to_state: str,
    event_at=None,
) -> LifesaverDeviceEvent:
    stamped = event_at or now()
    return LifesaverDeviceEvent(
        organization_id=organization_id,
        device_id=device_id,
        profile_id=profile_id,
        event_type=event_type,
        status="recorded",
        summary=(
            f"Simulated power event {event_type}: {from_state} -> {to_state}. "
            "Virtual power state only. No physical battery is connected."
        ),
        emergency_services_contacted=False,
        simulated=True,
        confidence="n/a",
        review_status="ACKNOWLEDGED",
        escalation_state="none",
        source="simulated",
        metadata_json=json.dumps(
            {
                "from_state": from_state,
                "to_state": to_state,
                "physical_battery_connected": False,
                "simulated": True,
                "media_stored": False,
                "external_call": False,
            }
        ),
        created_at=stamped,
    )


def new_fall_event(*, organization_id: str, device_id: str, profile_id: str) -> LifesaverDeviceEvent:
    return LifesaverDeviceEvent(
        organization_id=organization_id,
        device_id=device_id,
        profile_id=profile_id,
        event_type="SIMULATED_FALL_EVENT",
        status="needs_human_review",
        summary=FALL_REVIEW_COPY,
        emergency_services_contacted=False,
        simulated=True,
        confidence="low",
        review_status="NEEDS_REVIEW",
        escalation_state="none",
        source="simulated",
        metadata_json=json.dumps({"media_stored": False, "external_call": False}),
        created_at=now(),
    )
