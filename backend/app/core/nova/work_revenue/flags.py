"""Compatibility guardrails. Live values come from the V2 configuration layer."""
from __future__ import annotations

from app.core.nova.work_revenue.config import V1_FLAG_NAMES, is_capability_enabled

# Import-time constants remain False so accidental `if FLAG:` checks cannot enable live behavior
# without going through is_capability_enabled(). engine_guardrails() is the status surface.
LIVE_DISCOVERY_ENABLED = False
EXTERNAL_SUBMISSION_ENABLED = False
FINANCIAL_ACTIONS_ENABLED = False
AUTONOMOUS_CLIENT_CONTACT_ENABLED = False


def engine_guardrails() -> dict[str, bool]:
    flags = {
        name: is_capability_enabled(capability)
        for name, capability in V1_FLAG_NAMES.items()
    }
    flags.update(
        {
            "APPROVED_EQUALS_SUBMITTED": False,
            "APPROVED_EQUALS_PAID": False,
            "COMPLETE_EQUALS_PAID": False,
            "OWNER_APPROVAL_REQUIRED": True,
            "APPROVAL_EQUALS_EXECUTION": False,
            "BACKGROUND_WORKER_ENABLED": False,
            "LIVE_CONNECTORS_ENABLED": False,
        }
    )
    return flags
