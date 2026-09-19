"""Compatibility guardrails. Live values come from the V2 configuration layer.

LIVE_DISCOVERY also honors the owner-authorized V3 discovery flag
``NOVA_V3_LIVE_DISCOVERY_ENABLED``. That flag enables read-only discovery only;
it does not enable external submission, client contact, or financial execution.
"""
from __future__ import annotations

import os

from app.core.nova.work_revenue.config import V1_FLAG_NAMES, is_capability_enabled

# Import-time constants remain False so accidental `if FLAG:` checks cannot enable live behavior
# without going through is_capability_enabled() / engine_guardrails().
LIVE_DISCOVERY_ENABLED = False
EXTERNAL_SUBMISSION_ENABLED = False
FINANCIAL_ACTIONS_ENABLED = False
AUTONOMOUS_CLIENT_CONTACT_ENABLED = False

_TRUE = {"1", "true", "yes", "on"}
_V3_DISCOVERY_ENV = "NOVA_V3_LIVE_DISCOVERY_ENABLED"
_DISCOVERY_PROVIDER_ID = "remotive"
_DISCOVERY_PROVIDER_LABEL = "Remotive"


def _env_true(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in _TRUE


def v3_live_discovery_env_enabled() -> bool:
    """Runtime read of the owner-facing discovery flag. No secrets."""
    return _env_true(_V3_DISCOVERY_ENV)


def live_discovery_enabled() -> bool:
    """True when either the WR capability path or the V3 discovery flag is on."""
    if v3_live_discovery_env_enabled():
        return True
    return bool(is_capability_enabled("LIVE_DISCOVERY"))


def discovery_diagnostics() -> dict[str, object]:
    """Safe, non-secret discovery status for Today / Work diagnostics."""
    v3_on = v3_live_discovery_env_enabled()
    wr_on = bool(is_capability_enabled("LIVE_DISCOVERY"))
    enabled = bool(v3_on or wr_on)
    if v3_on:
        source = _V3_DISCOVERY_ENV
    elif wr_on:
        source = "NOVA_WR_LIVE_DISCOVERY"
    else:
        source = "off"
    return {
        "live_discovery_enabled": enabled,
        "discovery_provider_configured": True,
        "discovery_provider": _DISCOVERY_PROVIDER_ID,
        "discovery_provider_label": _DISCOVERY_PROVIDER_LABEL,
        "discovery_requires_api_key": False,
        "flag_source": source,
        "v3_discovery_env_enabled": v3_on,
        "wr_capability_enabled": wr_on,
        "authenticated_required": True,
        "external_submission_enabled": False,
        "financial_actions_enabled": False,
        "auto_submit": False,
    }


def engine_guardrails() -> dict[str, bool]:
    flags = {
        name: is_capability_enabled(capability)
        for name, capability in V1_FLAG_NAMES.items()
    }
    # Bridge: Today and Work guardrails must reflect the V3 discovery env flag
    # without enabling submission or finance capabilities.
    flags["LIVE_DISCOVERY_ENABLED"] = live_discovery_enabled()
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
