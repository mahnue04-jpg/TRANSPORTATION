"""Advisory compliance-readiness indicators for driver onboarding."""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.modules.platform_ops.models import (
    DOCUMENT_CATEGORIES,
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    STATUS_ONLY_DOCUMENT_CATEGORIES,
)
from app.modules.health_isf.models import HealthISFDriver


REQUIRED_AGREEMENT_CATEGORIES = frozenset(
    {
        "background_check_consent",
        "motor_vehicle_record_consent",
        "independent_contractor_agreement",
    }
)

UPLOAD_REQUIRED_CATEGORIES = frozenset(
    category
    for category in DOCUMENT_CATEGORIES
    if category not in STATUS_ONLY_DOCUMENT_CATEGORIES
)


def _identity_complete(app: PlatformDriverOnboardingApplication) -> bool:
    return bool(
        app.legal_first_name
        and app.legal_last_name
        and app.date_of_birth
        and app.email
        and app.mobile_phone
        and app.home_address
        and app.city
        and app.state
        and app.zip_code
    )


def _license_valid(app: PlatformDriverOnboardingApplication) -> bool:
    if not app.drivers_license_number or not app.license_expiration_date:
        return False
    return app.license_expiration_date >= date.today()


def _accepted_doc_by_category(
    documents: list[PlatformDriverOnboardingDocument],
    category: str,
) -> PlatformDriverOnboardingDocument | None:
    for doc in documents:
        if doc.category == category and doc.review_status == "accepted":
            return doc
    return None


def _document_unexpired(doc: PlatformDriverOnboardingDocument | None) -> bool:
    if doc is None:
        return False
    if doc.expires_at is None:
        return True
    return doc.expires_at >= date.today()


def _status_only_complete(
    documents: list[PlatformDriverOnboardingDocument],
    category: str,
) -> bool:
    doc = _accepted_doc_by_category(documents, category)
    if doc is None:
        for row in documents:
            if row.category == category and row.status_only_value in {"provided", "verified", "signed"}:
                return True
        return False
    return doc.status_only_value in {"provided", "verified", "signed", None}


def compute_readiness_summary(
    db: Session,
    application: PlatformDriverOnboardingApplication,
) -> dict[str, Any]:
    documents = list(application.documents or [])
    if not documents:
        documents = (
            db.query(PlatformDriverOnboardingDocument)
            .filter(PlatformDriverOnboardingDocument.application_id == application.id)
            .all()
        )

    insurance_doc = _accepted_doc_by_category(documents, "proof_of_auto_insurance")
    registration_doc = _accepted_doc_by_category(documents, "vehicle_registration")
    training_doc = _accepted_doc_by_category(documents, "training_certificates")
    cpr_doc = _accepted_doc_by_category(documents, "cpr_first_aid_certificate")

    agreements_signed = all(
        _accepted_doc_by_category(documents, category) is not None
        or _status_only_complete(documents, category)
        for category in REQUIRED_AGREEMENT_CATEGORIES
    )

    background_complete = application.status in {"background_review", "approved", "activated"} or bool(
        _accepted_doc_by_category(documents, "background_check_consent")
    )
    mvr_complete = bool(_accepted_doc_by_category(documents, "motor_vehicle_record_consent"))

    vehicle_assignment_complete = False
    if application.activated_driver_id:
        driver = db.query(HealthISFDriver).filter(HealthISFDriver.id == application.activated_driver_id).first()
        if driver and driver.vehicle_plate and not str(driver.vehicle_plate).upper().startswith("ONBD-"):
            vehicle_assignment_complete = True

    uploaded_categories = {doc.category for doc in documents if doc.review_status == "accepted"}
    missing_documents = sorted(UPLOAD_REQUIRED_CATEGORIES - uploaded_categories)

    indicators = {
        "identity_information_complete": _identity_complete(application),
        "drivers_license_valid_and_unexpired": _license_valid(application),
        "insurance_present_and_unexpired": _document_unexpired(insurance_doc),
        "vehicle_registration_present_and_unexpired": _document_unexpired(registration_doc),
        "required_agreements_signed": agreements_signed,
        "background_review_complete": background_complete,
        "motor_vehicle_record_review_complete": mvr_complete,
        "required_training_complete": training_doc is not None,
        "vehicle_assignment_complete": vehicle_assignment_complete,
    }

    completion_pct = round(
        100.0 * sum(1 for value in indicators.values() if value) / max(len(indicators), 1),
        1,
    )
    warnings = [key for key, value in indicators.items() if not value]

    return {
        "indicators": indicators,
        "document_completion_percentage": completion_pct,
        "missing_documents": missing_documents,
        "compliance_warnings": warnings,
        "advisory_only": True,
    }
