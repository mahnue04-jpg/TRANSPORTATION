"""Service-tier requirement rules for driver onboarding.

Fingerprinting is conditional — REQUIRED only when Minnesota background-study /
STS (or future MHCP) service-category rules apply. Rules remain configurable
rather than hardcoding every legal nuance.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.modules.approval_engine.statuses import SERVICE_TIERS

# Configurable catalog — legal/compliance rules stay data-driven.
REQUIREMENT_CATALOG: dict[str, dict[str, Any]] = {
    "identity_complete": {
        "label": "Identity / contact information complete",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "application_fields",
    },
    "age_verified": {
        "label": "Date of birth / age verification",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "application_fields",
    },
    "drivers_license": {
        "label": "Valid driver license (number/state/expiration + front image)",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "license_document_or_field",
    },
    "mvr": {
        "label": "Motor vehicle record (MVR)",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "external_mvr",
    },
    "vehicle_registration": {
        "label": "Vehicle registration",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "registration_document",
    },
    "vehicle_insurance": {
        "label": "Auto insurance",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "insurance_document",
    },
    "vehicle_inspection": {
        "label": "Vehicle inspection",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "inspection_document",
    },
    "contractor_agreement": {
        "label": "Independent contractor agreement",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "agreement_document",
    },
    "w9": {
        "label": "W-9 / tax documentation status",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "tax_status",
    },
    "payout_setup": {
        "label": "Payout method setup",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "payout_system",
    },
    "base_training": {
        "label": "Required base training modules",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "training_tracker",
    },
    "background_study": {
        "label": "Minnesota background study",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "external_background_study",
    },
    "fingerprint": {
        "label": "Fingerprinting",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "external_fingerprint",
    },
    "sts_training": {
        "label": "STS-specific training",
        "is_blocking": True,
        "is_legal_block": False,
        "verification_source": "training_tracker",
    },
    "mhcp_credentialing": {
        "label": "MHCP / NEMT credentialing (future)",
        "is_blocking": True,
        "is_legal_block": True,
        "verification_source": "external_mhcp",
    },
    "medical_qualification": {
        "label": "Medical / physical qualification",
        "is_blocking": False,
        "is_legal_block": False,
        "verification_source": "external_medical",
    },
}

# timing per tier: required_now | required_before_activation | conditional |
# future_requirement | not_required
TIER_REQUIREMENT_TIMING: dict[str, dict[str, str]] = {
    "BASE_PRIVATE_AMBULATORY": {
        "identity_complete": "required_now",
        "age_verified": "required_now",
        "drivers_license": "required_before_activation",
        "mvr": "required_before_activation",
        "vehicle_registration": "required_before_activation",
        "vehicle_insurance": "required_before_activation",
        "vehicle_inspection": "required_before_activation",
        "contractor_agreement": "required_before_activation",
        "w9": "required_before_activation",
        "payout_setup": "required_before_activation",
        "base_training": "required_before_activation",
        # Tier-gated — NOT a permanent universal waiver. Applicable when STS/MHCP
        # or authoritative Minnesota rules require these for the requested service.
        "background_study": "conditional",
        "fingerprint": "conditional",
        "sts_training": "conditional",
        "mhcp_credentialing": "conditional",
        "medical_qualification": "conditional",
    },
    "STS_ELIGIBLE": {
        "identity_complete": "required_now",
        "age_verified": "required_now",
        "drivers_license": "required_before_activation",
        "mvr": "required_before_activation",
        "vehicle_registration": "required_before_activation",
        "vehicle_insurance": "required_before_activation",
        "vehicle_inspection": "required_before_activation",
        "contractor_agreement": "required_before_activation",
        "w9": "required_before_activation",
        "payout_setup": "required_before_activation",
        "base_training": "required_before_activation",
        "background_study": "required_before_activation",
        "fingerprint": "conditional",  # REQUIRED only when background-study rule demands it
        "sts_training": "required_before_activation",
        "mhcp_credentialing": "not_required",
        "medical_qualification": "conditional",
    },
    "FUTURE_MHCP_NEMT": {
        "identity_complete": "required_now",
        "age_verified": "required_now",
        "drivers_license": "required_before_activation",
        "mvr": "required_before_activation",
        "vehicle_registration": "required_before_activation",
        "vehicle_insurance": "required_before_activation",
        "vehicle_inspection": "required_before_activation",
        "contractor_agreement": "required_before_activation",
        "w9": "required_before_activation",
        "payout_setup": "required_before_activation",
        "base_training": "required_before_activation",
        "background_study": "required_before_activation",
        "fingerprint": "conditional",
        "sts_training": "required_before_activation",
        "mhcp_credentialing": "future_requirement",
        "medical_qualification": "conditional",
    },
}

DEFAULT_TRAINING_MODULES = (
    ("passenger_assistance", "Passenger assistance"),
    ("emergency_procedures", "Emergency procedures"),
    ("communications", "Communications"),
    ("vehicle_inspection", "Vehicle inspection"),
    ("sanitation", "Sanitation"),
    ("defensive_driving", "Defensive driving"),
    ("first_aid", "First aid"),
    ("abuse_prevention", "Abuse prevention"),
    ("privacy", "Privacy"),
    ("incident_reporting", "Incident reporting"),
    ("no_show_cancellation", "No-show / cancellation handling"),
    ("driver_app_usage", "Driver-app usage"),
)

STS_EXTRA_TRAINING = (
    ("sts_service_rules", "STS service rules"),
    ("behind_wheel_eval", "Behind-the-wheel evaluation"),
)


def normalize_tiers(tiers: list[str] | None) -> list[str]:
    if not tiers:
        return ["BASE_PRIVATE_AMBULATORY"]
    out: list[str] = []
    for tier in tiers:
        key = str(tier or "").strip().upper()
        if key in SERVICE_TIERS and key not in out:
            out.append(key)
    return out or ["BASE_PRIVATE_AMBULATORY"]


def fingerprint_required_for_tiers(
    tiers: list[str],
    *,
    background_study_requires_fingerprint: bool = True,
) -> bool:
    """Fingerprinting is never universal — only when STS/MHCP tiers apply and rule says so."""
    normalized = normalize_tiers(tiers)
    if not any(t in {"STS_ELIGIBLE", "FUTURE_MHCP_NEMT"} for t in normalized):
        return False
    return bool(background_study_requires_fingerprint)


def build_requirement_plan(tiers: list[str] | None) -> list[dict[str, Any]]:
    normalized = normalize_tiers(tiers)
    plan: dict[str, dict[str, Any]] = {}
    for tier in normalized:
        timing_map = TIER_REQUIREMENT_TIMING.get(tier, {})
        for key, timing in timing_map.items():
            catalog = REQUIREMENT_CATALOG.get(key) or {"label": key}
            existing = plan.get(key)
            # Most restrictive timing wins across requested tiers.
            rank = {
                "required_now": 5,
                "required_before_activation": 4,
                "conditional": 3,
                "future_requirement": 2,
                "not_required": 1,
            }
            if existing is None or rank.get(timing, 0) > rank.get(existing["timing"], 0):
                entry = deepcopy(catalog)
                entry.update(
                    {
                        "requirement_key": key,
                        "service_tier": tier if existing is None else (
                            existing["service_tier"] if existing["timing"] == timing else "MULTI"
                        ),
                        "timing": timing,
                    }
                )
                if key == "fingerprint":
                    if fingerprint_required_for_tiers(normalized):
                        entry["timing"] = "required_before_activation"
                        entry["fingerprint_status"] = "REQUIRED"
                    else:
                        # Keep conditional — not a permanent universal waiver.
                        entry["timing"] = "conditional"
                        entry["fingerprint_status"] = "NOT_REQUIRED"
                        entry["is_blocking"] = False
                plan[key] = entry
    return list(plan.values())


def training_modules_for_tiers(tiers: list[str] | None) -> list[tuple[str, str]]:
    normalized = normalize_tiers(tiers)
    modules = list(DEFAULT_TRAINING_MODULES)
    if any(t in {"STS_ELIGIBLE", "FUTURE_MHCP_NEMT"} for t in normalized):
        modules.extend(STS_EXTRA_TRAINING)
    return modules


def activation_blocking_keys(plan: list[dict[str, Any]]) -> list[str]:
    return [
        item["requirement_key"]
        for item in plan
        if item.get("timing") in {"required_now", "required_before_activation"}
        and item.get("is_blocking")
    ]
