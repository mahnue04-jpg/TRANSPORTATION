"""Activation adapter — links approved applicants to HealthISFDriver records."""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf import service as health_isf_service
from app.modules.health_isf.models import HealthISFDriver
from app.modules.platform_ops.models import PlatformDriverOnboardingApplication
from app.modules.platform_ops.onboarding import service as onboarding_service
from app.modules.platform_ops.onboarding.policies import required_policies_complete
from app.modules.platform_ops.onboarding.work_setup import agreement_is_signed
from app.modules.platform_ops.readiness import compute_readiness_summary
from app.modules.platform_ops.status_machine import ACTIVATION_SOURCE_STATUSES

logger = logging.getLogger("amicor.platform_ops.onboarding.activation")

COMPLIANCE_ACTIVATION_BLOCKED = (
    "COMPLIANCE_ACTIVATION_BLOCKED: Platform Ops cannot create or activate an "
    "is_active HealthISFDriver until the Approval Engine case is APPROVED or ACTIVE "
    "and blocking requirements are satisfied. Do not bypass compliance."
)
INSURANCE_ACTIVATION_BLOCKED = (
    "INSURANCE_ACTIVATION_BLOCKED: Cannot activate driver with missing or expired "
    "auto insurance proof."
)
POLICY_ACTIVATION_BLOCKED = (
    "POLICY_ACTIVATION_BLOCKED: Required driver policy acknowledgments are incomplete. "
    "Policies remain DRAFT FOR ATTORNEY REVIEW until counsel signs off."
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


def _assert_platform_activation_prerequisites(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
) -> None:
    readiness = compute_readiness_summary(db, application)
    indicators = readiness.get("indicators") or {}
    if not indicators.get("insurance_present_and_unexpired"):
        raise ValueError(INSURANCE_ACTIVATION_BLOCKED)
    exp = getattr(application, "insurance_expiration_date", None)
    if exp is not None and exp < date.today():
        raise ValueError(INSURANCE_ACTIVATION_BLOCKED + " Application insurance expiration is past due.")
    ica_signed = agreement_is_signed(application)
    if not required_policies_complete(application, ica_signed=ica_signed):
        raise ValueError(POLICY_ACTIVATION_BLOCKED)
    from app.modules.approval_engine.models import ApprovalCase
    from app.modules.approval_engine.screening_status import screening_summary_for_application

    case = (
        db.query(ApprovalCase)
        .filter(ApprovalCase.platform_ops_application_id == application.id)
        .order_by(ApprovalCase.updated_at.desc())
        .first()
    )
    screening = screening_summary_for_application(application=application, case=case)
    if screening.get("blocks_activation"):
        blockers = ", ".join(screening.get("activation_blockers") or [])
        raise ValueError(
            "SCREENING_ACTIVATION_BLOCKED: Required MVR/background screening is incomplete "
            f"({blockers}). External vendor clearance is required; do not fabricate results."
        )


def _resolve_activation_plate(application: PlatformDriverOnboardingApplication) -> str:
    plate = str(getattr(application, "vehicle_license_plate", "") or "").strip().upper()
    if plate and not plate.startswith("ONBD-"):
        return plate
    plate_token = application.id.replace("-", "")[:8].upper()
    return f"ONBD-{plate_token}"


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
        _assert_platform_activation_prerequisites(db, application=application)
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

    vehicle_plate = _resolve_activation_plate(application)

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
        vehicle_type=str(getattr(application, "vehicle_make", None) or "sedan"),
        vehicle_plate=vehicle_plate,
    )
    if getattr(case, "health_isf_driver_id", None) in {None, ""}:
        case.health_isf_driver_id = driver.id
        case.entity_id = case.entity_id or driver.id

    # Attempt AE ACTIVE transition when case is only APPROVED; keep inactive if blockers remain.
    ae_status = str(getattr(case, "workflow_status", "") or "").strip().upper()
    if ae_status in {"APPROVED", "OWNER_APPROVED"}:
        try:
            from app.modules.approval_engine.workflow import activate_if_eligible

            case = activate_if_eligible(
                db,
                case=case,
                actor_user_id=actor_user_id,
                health_isf_driver_id=driver.id,
            )
            ae_status = str(getattr(case, "workflow_status", "") or "").strip().upper()
        except ValueError as exc:
            logger.info("AE activate deferred for application %s: %s", application.id, exc)

    plate_ready = not str(driver.vehicle_plate or "").upper().startswith("ONBD-")
    driver.is_active = bool(ae_status == "ACTIVE" and plate_ready)
    db.add(driver)
    db.flush()

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
        metadata={
            "driver_id": driver.id,
            "dispatch_eligible": bool(driver.is_active),
            "approval_engine_status": ae_status,
        },
    )
    db.commit()
    db.refresh(application)
    db.refresh(driver)

    if str(getattr(driver.status, "value", getattr(driver, "status", ""))).lower() not in {"offline", "unavailable"}:
        logger.warning("Activated driver %s expected offline/unavailable default", driver.id)

    return driver, False
