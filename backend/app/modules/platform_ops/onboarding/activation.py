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
