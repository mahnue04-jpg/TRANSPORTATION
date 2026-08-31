"""Go-online / live-offer gate for drivers with a compliance file.

Legacy seed drivers without a Platform Ops application or Approval Engine case
remain eligible so existing ride/dispatch tests keep working.

AMICOR_DRIVER_COMPLIANCE_ONLINE_OVERRIDE=1 bypasses the gate (default OFF).
"""
from __future__ import annotations

import os
from typing import Any

from sqlalchemy.orm import Session

from app.modules.approval_engine.compliance_summary import (
    build_compliance_summary,
    resolve_case_and_application,
)
from app.modules.approval_engine.models import ApprovalCase
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication


def online_gate_override_enabled() -> bool:
    return str(os.getenv("AMICOR_DRIVER_COMPLIANCE_ONLINE_OVERRIDE", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _find_application_for_driver(db: Session, driver_id: str) -> PlatformDriverOnboardingApplication | None:
    return (
        db.query(PlatformDriverOnboardingApplication)
        .filter(PlatformDriverOnboardingApplication.activated_driver_id == driver_id)
        .order_by(PlatformDriverOnboardingApplication.updated_at.desc())
        .first()
    )


def _find_case_for_driver(db: Session, driver_id: str) -> ApprovalCase | None:
    return (
        db.query(ApprovalCase)
        .filter(ApprovalCase.health_isf_driver_id == driver_id)
        .order_by(ApprovalCase.updated_at.desc())
        .first()
    )


def evaluate_online_eligibility(
    db: Session,
    *,
    driver_id: str,
    organization_id: str | None = None,
) -> dict[str, Any]:
    if online_gate_override_enabled():
        return {
            "eligible": True,
            "override": True,
            "legacy_driver": False,
            "reason": "AMICOR_DRIVER_COMPLIANCE_ONLINE_OVERRIDE is enabled (development/test only).",
            "summary": None,
        }

    application = _find_application_for_driver(db, driver_id)
    case = _find_case_for_driver(db, driver_id)
    if application is None and case is None:
        return {
            "eligible": True,
            "override": False,
            "legacy_driver": True,
            "reason": "No onboarding/compliance file on this operational driver.",
            "summary": None,
        }

    case, application = resolve_case_and_application(db, case=case, application=application)
    summary = build_compliance_summary(db, application=application, case=case)
    eligible = bool(summary.get("online_eligible"))
    reasons = list(summary.get("blocked_from_online_reasons") or [])
    return {
        "eligible": eligible,
        "override": False,
        "legacy_driver": False,
        "reason": "ok" if eligible else ("; ".join(reasons) or "Required compliance items are incomplete."),
        "summary": summary,
        "application_id": application.id if application else None,
        "case_id": case.id if case else None,
        "organization_id": organization_id,
    }


def assert_driver_may_go_online(db: Session, *, driver_id: str) -> dict[str, Any]:
    result = evaluate_online_eligibility(db, driver_id=driver_id)
    if not result.get("eligible"):
        raise ValueError(
            "Driver is blocked from going online: "
            + str(result.get("reason") or "required compliance items are incomplete")
        )
    return result
