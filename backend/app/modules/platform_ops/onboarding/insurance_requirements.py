"""Insurance requirement configuration.

Does not invent coverage minimums. Presence/expiration remain enforced in readiness
and activation. Optional numeric minimums apply only when Amicor explicitly sets env.
"""
from __future__ import annotations

import os
from typing import Any


def _optional_float(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def insurance_requirements_config() -> dict[str, Any]:
    liability = _optional_float("AMICOR_INSURANCE_MIN_LIABILITY_USD")
    combined = _optional_float("AMICOR_INSURANCE_MIN_COMBINED_SINGLE_LIMIT_USD")
    configured = liability is not None or combined is not None
    return {
        "business_confirmation_required": not configured,
        "minimums_configured": configured,
        "minimum_liability_usd": liability,
        "minimum_combined_single_limit_usd": combined,
        "note": (
            "Insurance presence and unexpired proof are required for activation. "
            "Numeric coverage minimums are applied only after Amicor sets "
            "AMICOR_INSURANCE_MIN_LIABILITY_USD and/or "
            "AMICOR_INSURANCE_MIN_COMBINED_SINGLE_LIMIT_USD following business/legal confirmation."
        ),
    }
