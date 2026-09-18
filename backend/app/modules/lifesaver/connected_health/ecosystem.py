"""Future AMICOR ecosystem hooks. Interfaces only — no frozen-product writes."""
from __future__ import annotations

from typing import Any


def _inactive(name: str, purpose: str) -> dict[str, Any]:
    return {
        "hook": name,
        "activated": False,
        "writes_external": False,
        "real_order": False,
        "real_ride": False,
        "real_notification": False,
        "real_provider_message": False,
        "purpose": purpose,
        "status": "placeholder_only",
    }


def snapshot() -> dict[str, Any]:
    return {
        "activated": False,
        "disclaimer": "These contracts do not import or write Health ISF, Delivery, Nova Core, Freight, Driver 001, or Stripe.",
        "hooks": {
            "amicor_health_appointment": _inactive(
                "amicor_health_appointment",
                "Future appointment / healthcare-access coordination.",
            ),
            "amicor_delivery_kit_logistics": _inactive(
                "amicor_delivery_kit_logistics",
                "Future approved kit/supply delivery or pickup request.",
            ),
            "nova_coordination_summary": _inactive(
                "nova_coordination_summary",
                "Future coordination/recommendation summary. Not a diagnosis.",
            ),
            "provider_share": _inactive(
                "provider_share",
                "Local provider-share record only. No real provider message.",
            ),
            "care_circle_notification": _inactive(
                "care_circle_notification",
                "Local Care Circle share flag only. No email or SMS.",
            ),
        },
    }


def invoke(name: str) -> dict[str, Any]:
    data = snapshot()
    hook = data["hooks"].get(name)
    if hook is None:
        return {"activated": False, "hook": name, "status": "unknown_hook"}
    return hook
