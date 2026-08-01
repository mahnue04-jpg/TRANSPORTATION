"""Workforce readiness adapter — advisory gate for newly onboarded drivers only."""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from app.modules.platform_ops.models import PlatformDriverOnboardingApplication
from app.modules.platform_ops.readiness import compute_readiness_summary


def onboarding_gate_enabled() -> bool:
    return os.getenv("PLATFORM_OPS_DRIVER_ONBOARDING_GATE", "").strip().lower() in {"1", "true", "yes", "on"}


def find_onboarding_application_for_driver(
    db: Session,
    *,
    driver_id: str,
) -> PlatformDriverOnboardingApplication | None:
    return (
        db.query(PlatformDriverOnboardingApplication)
        .filter(PlatformDriverOnboardingApplication.activated_driver_id == driver_id)
        .order_by(PlatformDriverOnboardingApplication.created_at.desc())
        .first()
    )


def evaluate_workforce_readiness(
    db: Session,
    *,
    driver_id: str,
) -> dict[str, Any]:
    """Advisory readiness check. Legacy drivers without onboarding records pass."""
    if not onboarding_gate_enabled():
        return {"eligible": True, "gate_enabled": False, "warnings": [], "legacy_driver": True}

    application = find_onboarding_application_for_driver(db, driver_id=driver_id)
    if application is None:
        return {"eligible": True, "gate_enabled": True, "warnings": [], "legacy_driver": True}

    if not application.onboarding_gate_enabled:
        return {"eligible": True, "gate_enabled": True, "warnings": [], "legacy_driver": False}

    summary = compute_readiness_summary(db, application)
    warnings = list(summary.get("compliance_warnings") or [])
    eligible = len(warnings) == 0 and application.status == "activated"
    return {
        "eligible": eligible,
        "gate_enabled": True,
        "legacy_driver": False,
        "application_id": application.id,
        "application_status": application.status,
        "warnings": warnings,
        "readiness": summary,
    }
