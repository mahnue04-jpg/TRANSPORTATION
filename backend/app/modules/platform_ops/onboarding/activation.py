"""Activation adapter — links approved applicants to HealthISFDriver records."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf import service as health_isf_service
from app.modules.health_isf.models import HealthISFDriver
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication
from app.modules.platform_ops.onboarding import service as onboarding_service
from app.modules.platform_ops.readiness import compute_readiness_summary
from app.modules.platform_ops.status_machine import ACTIVATION_SOURCE_STATUSES

logger = logging.getLogger("amicor.platform_ops.onboarding.activation")

COMPLIANCE_ACTIVATION_BLOCKED = (
    "COMPLIANCE_ACTIVATION_BLOCKED: Platform Ops cannot create or activate an "
    "is_active HealthISFDriver until the Approval Engine case is APPROVED or ACTIVE "
    "and blocking requirements are satisfied. Do not bypass compliance."
)


def _approval_case_for_application(db: Session, application: PlatformDriverOnboardingApplication):
    from app.modules.approval_engine.models import ApprovalCase

    return (
        db.query(ApprovalCase)
        .filter(
            ApprovalCase.organization_id == application.organization_id,
            ApprovalCase.platform_ops_application_id == application.id,
        )
        .order_by(ApprovalCase.updated_at.desc())
        .first()
    )


def assert_approval_engine_allows_activation(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
) -> object:
    """Server-side gate: Platform Ops approve is not enough."""
    from app.modules.approval_engine.workflow import blocking_requirements

    case = _approval_case_for_application(db, application)
    if case is None:
        raise ValueError(COMPLIANCE_ACTIVATION_BLOCKED + " No Approval Engine case is on file.")
    status = str(case.workflow_status or "").strip().upper()
    if status not in {"APPROVED", "OWNER_APPROVED", "ACTIVE"}:
        raise ValueError(
            COMPLIANCE_ACTIVATION_BLOCKED
            + f" Approval Engine status is {status or 'UNKNOWN'}, not APPROVED/ACTIVE."
        )
    blockers = blocking_requirements(case)
    if blockers:
        keys = ", ".join(str(item.requirement_key) for item in blockers)
        raise ValueError(
            COMPLIANCE_ACTIVATION_BLOCKED
            + f" Blocking requirements remain: {keys}."
        )
    return case


def activate_application(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    actor_role: str,
) -> tuple[HealthISFDriver, bool]:
    """Create or return linked driver. Idempotent when already activated."""
    if application.status == "activated" and application.activated_driver_id:
        driver = health_isf_service.get_driver_by_id(db, application.activated_driver_id)
        if driver is not None:
            return driver, True
    if application.status not in ACTIVATION_SOURCE_STATUSES:
        raise ValueError("Application must be approved before activation.")
    try:
        case = assert_approval_engine_allows_activation(db, application=application)
    except ValueError as exc:
        onboarding_service._record_audit(
            db,
            application=application,
            event_type="application_activation_blocked",
            from_status=application.status,
            to_status=application.status,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            reason=str(exc),
        )
        db.commit()
        raise

    if application.activated_driver_id:
        driver = health_isf_service.get_driver_by_id(db, application.activated_driver_id)
        if driver is not None:
            if application.status != "activated":
                previous = application.status
                application.status = "activated"
                application.activated_at = application.activated_at or now()
                application.updated_at = now()
                onboarding_service._record_audit(
                    db,
                    application=application,
                    event_type="application_activated",
                    from_status=previous,
                    to_status="activated",
                    actor_user_id=actor_user_id,
                    actor_role=actor_role,
                )
                db.commit()
                db.refresh(application)
            return driver, True

    name = " ".join(
        part
        for part in (
            application.legal_first_name or "",
            application.legal_middle_name or "",
            application.legal_last_name or "",
        )
        if part
    ).strip()
    if not name:
        raise ValueError("Applicant name is required for activation.")
    if not application.mobile_phone:
        raise ValueError("Applicant mobile phone is required for activation.")

    plate_token = application.id.replace("-", "")[:8].upper()
    placeholder_plate = f"ONBD-{plate_token}"

    existing_phone = (
        db.query(HealthISFDriver)
        .filter(HealthISFDriver.phone == str(application.mobile_phone).strip())
        .first()
    )
    if existing_phone:
        raise ValueError("A driver with this phone number already exists. Link manually or reject duplicate application.")

    driver = health_isf_service.create_driver(
        db,
        organization_id=application.organization_id,
        name=name,
        phone=str(application.mobile_phone).strip(),
        vehicle_type="pending_assignment",
        vehicle_plate=placeholder_plate,
    )
    # Onboarding-created drivers stay inactive unless Approval Engine is already ACTIVE.
    # They remain ineligible for live dispatch while the production gate is off.
    ae_active = str(getattr(case, "workflow_status", "") or "").strip().upper() == "ACTIVE"
    if not ae_active:
        driver.is_active = False
        db.add(driver)
        db.flush()
    if getattr(case, "health_isf_driver_id", None) in {None, ""}:
        case.health_isf_driver_id = driver.id
        case.entity_id = case.entity_id or driver.id

    previous = application.status
    application.activated_driver_id = driver.id
    application.status = "activated"
    application.activated_at = now()
    application.updated_at = now()
    application.onboarding_gate_enabled = True

    onboarding_service._record_audit(
        db,
        application=application,
        event_type="application_activated",
        from_status=previous,
        to_status="activated",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        metadata={"driver_id": driver.id},
    )
    db.commit()
    db.refresh(application)
    db.refresh(driver)

    if str(getattr(driver.status, "value", getattr(driver, "status", ""))).lower() not in {"offline", "unavailable"}:
        logger.warning("Activated driver %s expected offline/unavailable default", driver.id)

    return driver, False
