"""Driver onboarding business logic."""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import date, datetime
from io import BytesIO
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.platform_ops.masking import mask_license_number, mask_phone
from app.modules.platform_ops.models import (
    DOCUMENT_CATEGORIES,
    STATUS_ONLY_DOCUMENT_CATEGORIES,
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingAuditEvent,
    PlatformDriverOnboardingDocument,
    PlatformDriverOnboardingInternalNote,
)
from app.modules.platform_ops.readiness import compute_readiness_summary
from app.modules.platform_ops.schemas import (
    DocumentCategoryInfo,
    DocumentMetadataResponse,
    DriverApplicationDetailResponse,
    DriverApplicationDraftRequest,
    DriverApplicationListItemResponse,
    ReadinessSummaryResponse,
)
from app.modules.platform_ops.status_machine import (
    ACTIVATION_SOURCE_STATUSES,
    APPROVAL_SOURCE_STATUSES,
    assert_transition_allowed,
    list_allowed_next_statuses,
    normalize_status,
)
from app.modules.platform_ops.storage import get_document_storage

logger = logging.getLogger("amicor.platform_ops.onboarding")

DOCUMENT_LABELS = {
    "drivers_license_front": "Driver's License (Front)",
    "drivers_license_back": "Driver's License (Back)",
    "proof_of_auto_insurance": "Proof of Auto Insurance",
    "vehicle_registration": "Vehicle Registration",
    "vehicle_inspection_record": "Vehicle Inspection Record",
    "driver_profile_photo": "Driver Profile Photo",
    "ssn_tax_verification_status": "SSN / Tax Verification Status",
    "w9_status": "W-9 Status (Contractors)",
    "background_check_consent": "Background Check Consent",
    "motor_vehicle_record_consent": "Motor Vehicle Record Consent",
    "independent_contractor_agreement": "Independent Contractor Agreement",
    "training_certificates": "Training Certificates",
    "cpr_first_aid_certificate": "CPR / First Aid Certificate",
}

SENSITIVE_CATEGORIES = frozenset(
    {
        "ssn_tax_verification_status",
        "background_check_consent",
        "motor_vehicle_record_consent",
    }
)

# Simple applicant flow — required uploads before submit (TEST placeholders OK locally).
SIMPLE_REQUIRED_UPLOAD_CATEGORIES = (
    "drivers_license_front",
    "drivers_license_back",
    "vehicle_registration",
    "proof_of_auto_insurance",
    "independent_contractor_agreement",
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _generate_applicant_token() -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    return token, _hash_token(token)


def _serialize_availability_days(days: list[str] | None) -> str | None:
    if not days:
        return None
    return json.dumps(sorted({str(day).strip().lower() for day in days if str(day).strip()}))


def _deserialize_availability_days(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return []


def _record_audit(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    event_type: str,
    from_status: str | None = None,
    to_status: str | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> PlatformDriverOnboardingAuditEvent:
    event = PlatformDriverOnboardingAuditEvent(
        id=uuid4(),
        application_id=application.id,
        organization_id=application.organization_id,
        event_type=event_type,
        from_status=from_status,
        to_status=to_status,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
        metadata_json=json.dumps(metadata) if metadata else None,
        created_at=now(),
    )
    db.add(event)
    return event


def _apply_draft_fields(
    application: PlatformDriverOnboardingApplication,
    payload: DriverApplicationDraftRequest,
) -> None:
    for field in (
        "legal_first_name",
        "legal_middle_name",
        "legal_last_name",
        "date_of_birth",
        "email",
        "mobile_phone",
        "home_address",
        "city",
        "state",
        "zip_code",
        "emergency_contact_name",
        "emergency_contact_phone",
        "preferred_language",
        "drivers_license_number",
        "license_issuing_state",
        "license_expiration_date",
        "years_driving_experience",
        "employment_type",
        "availability_start_time",
        "availability_end_time",
        "willing_weekends",
        "willing_wheelchair",
        "service_area_counties",
        "vehicle_year",
        "vehicle_make",
        "vehicle_model",
        "vehicle_license_plate",
        "vehicle_vin",
        "vehicle_color",
        "vehicle_plate_state",
        "vehicle_registration_expiration",
        "insurance_carrier",
        "insurance_effective_date",
        "insurance_expiration_date",
        "declaration_valid_license",
        "declaration_mvr_authorization",
        "declaration_background_authorization",
        "declaration_drug_alcohol_policy",
        "declaration_truthful_information",
        "electronic_signature",
        "signed_date",
    ):
        value = getattr(payload, field, None)
        if value is None:
            continue
        # Never wipe an already-true declaration with an omitted/unchecked false from a partial form save.
        if field.startswith("declaration_") and value is False and bool(getattr(application, field, False)):
            continue
        # Blank frontend defaults must not erase values already stored on the draft.
        if isinstance(value, str) and value.strip() == "" and getattr(application, field, None) not in (None, ""):
            continue
        setattr(application, field, value)
    if payload.availability_days is not None:
        application.availability_days_json = _serialize_availability_days(payload.availability_days)
    # Simplified apply: one authorization maps to applicable compliance consents.
    if getattr(payload, "authorize_qualification_checks", None):
        application.declaration_valid_license = True
        application.declaration_mvr_authorization = True
        application.declaration_background_authorization = True
        application.declaration_drug_alcohol_policy = True
        application.declaration_truthful_information = True
    policy_number = getattr(payload, "insurance_policy_number", None)
    if policy_number:
        from app.modules.approval_engine.phase2b import mask_policy_reference

        application.insurance_policy_ref_masked = mask_policy_reference(policy_number)
    if application.declaration_background_authorization and not getattr(application, "background_consent_at", None):
        application.background_consent_at = now()
    application.updated_at = now()


def apply_simple_application_defaults(application: PlatformDriverOnboardingApplication) -> None:
    """Fill operational defaults so the driver-facing form can stay minimal."""
    if not application.preferred_language:
        application.preferred_language = "English"
    if not application.employment_type:
        application.employment_type = "independent_contractor"
    if not _deserialize_availability_days(application.availability_days_json):
        application.availability_days_json = _serialize_availability_days(
            ["monday", "tuesday", "wednesday", "thursday", "friday"]
        )
    if not application.availability_start_time:
        application.availability_start_time = "08:00"
    if not application.availability_end_time:
        application.availability_end_time = "18:00"
    if application.willing_weekends is None:
        application.willing_weekends = True
    if application.willing_wheelchair is None:
        # BASE default — STS wheelchair eligibility remains a later tier decision.
        application.willing_wheelchair = False
    if not application.service_area_counties:
        application.service_area_counties = application.state or "TBD"
    if not application.signed_date and application.electronic_signature:
        application.signed_date = date.today()


def validate_complete_application(application: PlatformDriverOnboardingApplication) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    # Driver-minimum required fields. Operational scheduling details are defaulted.
    required_fields = {
        "legal_first_name": "Legal first name is required.",
        "legal_last_name": "Legal last name is required.",
        "date_of_birth": "Date of birth is required.",
        "email": "Email is required.",
        "mobile_phone": "Mobile phone is required.",
        "home_address": "Home address is required.",
        "city": "City is required.",
        "state": "State is required.",
        "zip_code": "ZIP code is required.",
        "emergency_contact_name": "Emergency contact name is required.",
        "emergency_contact_phone": "Emergency contact phone is required.",
        "drivers_license_number": "Driver's license number is required.",
        "license_issuing_state": "License issuing state is required.",
        "license_expiration_date": "License expiration date is required.",
        "electronic_signature": "Electronic signature is required.",
        "signed_date": "Signed date is required.",
    }
    for field, message in required_fields.items():
        if getattr(application, field) in (None, ""):
            errors.append({"field": field, "message": message})

    declarations = {
        "declaration_valid_license": "You must confirm a valid driver's license.",
        "declaration_mvr_authorization": "Driving-record authorization is required.",
        "declaration_truthful_information": "Truthful information certification is required.",
    }
    for field, message in declarations.items():
        if not getattr(application, field):
            errors.append({"field": field, "message": message})

    if application.license_expiration_date and application.license_expiration_date < date.today():
        errors.append({"field": "license_expiration_date", "message": "Driver's license must not be expired."})

    documents = list(application.documents or [])
    present_categories = {
        str(doc.category)
        for doc in documents
        if doc.review_status in {"pending", "accepted"}
    }
    for category in SIMPLE_REQUIRED_UPLOAD_CATEGORIES:
        if category not in present_categories:
            label = DOCUMENT_LABELS.get(category, category)
            errors.append(
                {
                    "field": category,
                    "message": f"{label} upload is required before submit.",
                }
            )

    return errors


def find_existing_driver_001_application(
    db: Session,
    *,
    organization_id: str,
) -> PlatformDriverOnboardingApplication | None:
    return (
        db.query(PlatformDriverOnboardingApplication)
        .filter(
            PlatformDriverOnboardingApplication.organization_id == organization_id,
            PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001",
        )
        .order_by(PlatformDriverOnboardingApplication.created_at.asc())
        .first()
    )


def _payload_matches_driver_001(
    payload: DriverApplicationDraftRequest | None,
    existing: PlatformDriverOnboardingApplication,
) -> bool:
    if payload is None:
        return False
    email = str(getattr(payload, "email", None) or "").strip().lower()
    existing_email = str(existing.email or "").strip().lower()
    first = str(getattr(payload, "legal_first_name", None) or "").strip().lower()
    last = str(getattr(payload, "legal_last_name", None) or "").strip().lower()
    if email and existing_email and email == existing_email:
        return True
    if first == "driver" and last == "001":
        return True
    return False


def create_draft_application(
    db: Session,
    *,
    organization_id: str,
    payload: DriverApplicationDraftRequest | None = None,
) -> tuple[PlatformDriverOnboardingApplication, str]:
    existing_driver_001 = find_existing_driver_001_application(db, organization_id=organization_id)
    if existing_driver_001 and _payload_matches_driver_001(payload, existing_driver_001):
        raise ValueError(
            "Cannot create a duplicate Driver 001 application. An application already exists. "
            "Use the original application link. A new application was not created."
        )
    token, token_hash = _generate_applicant_token()
    application = PlatformDriverOnboardingApplication(
        id=uuid4(),
        organization_id=organization_id,
        status="draft",
        applicant_access_token_hash=token_hash,
        created_at=now(),
        updated_at=now(),
    )
    db.add(application)
    if payload:
        _apply_draft_fields(application, payload)
    _record_audit(
        db,
        application=application,
        event_type="application_created",
        to_status="draft",
    )
    db.commit()
    db.refresh(application)
    return application, token


def get_application_by_id(db: Session, application_id: str) -> PlatformDriverOnboardingApplication | None:
    return (
        db.query(PlatformDriverOnboardingApplication)
        .filter(PlatformDriverOnboardingApplication.id == application_id)
        .first()
    )


def verify_applicant_token(application: PlatformDriverOnboardingApplication, token: str | None) -> bool:
    if not token or not application.applicant_access_token_hash:
        return False
    return _hash_token(token) == application.applicant_access_token_hash


def reissue_applicant_access_token(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    actor_role: str,
) -> str:
    """Rotate the applicant token hash. Returns plaintext once; never persist or log it."""
    if application.status == "activated" or application.activated_driver_id:
        raise ValueError("Cannot reissue applicant access for an activated application.")
    token, token_hash = _generate_applicant_token()
    application.applicant_access_token_hash = token_hash
    application.updated_at = now()
    _record_audit(
        db,
        application=application,
        event_type="applicant_access_reissued",
        from_status=application.status,
        to_status=application.status,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason="Applicant access link reissued. Previous applicant token revoked.",
        metadata={"rotated": True, "token_included": False},
    )
    db.commit()
    db.refresh(application)
    return token


def update_draft_application(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    payload: DriverApplicationDraftRequest,
    actor_user_id: str | None = None,
) -> PlatformDriverOnboardingApplication:
    if application.status != "draft":
        raise ValueError("Only draft applications can be edited.")
    _apply_draft_fields(application, payload)
    _record_audit(
        db,
        application=application,
        event_type="draft_updated",
        from_status=application.status,
        to_status=application.status,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(application)
    # Secure workflows: record status-only markers without collecting SSN/bank details here.
    if getattr(payload, "w9_secure_workflow_started", None):
        upsert_status_only_document(
            db, application=application, category="w9_status", status_only_value="provided"
        )
        db.refresh(application)
    return application


def submit_application(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str | None = None,
) -> PlatformDriverOnboardingApplication:
    if application.status != "draft":
        raise ValueError("Only draft applications can be submitted.")
    apply_simple_application_defaults(application)
    errors = validate_complete_application(application)
    if errors:
        raise ValueError(json.dumps({"detail": "Application is incomplete.", "errors": errors}))

    previous = application.status
    application.status = "submitted"
    application.submitted_at = now()
    application.updated_at = now()
    assert_transition_allowed(previous, application.status)
    _record_audit(
        db,
        application=application,
        event_type="application_submitted",
        from_status=previous,
        to_status=application.status,
        actor_user_id=actor_user_id,
    )
    db.commit()
    db.refresh(application)
    # AI Approval Engine: create/sync case and run automated review (non-breaking).
    try:
        from app.modules.approval_engine.workflow import create_or_sync_case_from_platform_ops

        create_or_sync_case_from_platform_ops(
            db,
            application=application,
            run_review=True,
        )
    except Exception as exc:  # pragma: no cover - never block applicant submit
        logger.warning("approval_engine sync after submit skipped: %s", exc)
    return application


def transition_application_status(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    to_status: str,
    reason: str | None,
    actor_user_id: str,
    actor_role: str,
    assigned_reviewer_id: str | None = None,
) -> PlatformDriverOnboardingApplication:
    previous = application.status
    target = normalize_status(to_status)
    assert_transition_allowed(previous, target)
    if target == "activated":
        from app.modules.platform_ops.onboarding.activation import (
            COMPLIANCE_ACTIVATION_BLOCKED,
            assert_approval_engine_allows_activation,
        )

        try:
            assert_approval_engine_allows_activation(db, application=application)
        except ValueError as exc:
            _record_audit(
                db,
                application=application,
                event_type="application_activation_blocked",
                from_status=previous,
                to_status=previous,
                actor_user_id=actor_user_id,
                actor_role=actor_role,
                reason=str(exc),
            )
            db.commit()
            raise
        raise ValueError(
            COMPLIANCE_ACTIVATION_BLOCKED
            + " Status cannot be set to activated directly. Use the compliance-gated activate endpoint."
        )

    application.status = target
    application.status_reason = reason
    application.updated_at = now()
    if assigned_reviewer_id:
        application.assigned_reviewer_id = assigned_reviewer_id
    if target in {"under_review", "documents_pending", "background_review"}:
        application.reviewed_at = now()
    if target == "rejected":
        application.rejection_reason = reason
        application.rejected_at = now()

    _record_audit(
        db,
        application=application,
        event_type="status_transition",
        from_status=previous,
        to_status=target,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
    )
    db.commit()
    db.refresh(application)
    return application


def approve_application(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    actor_role: str,
    reason: str | None = None,
) -> PlatformDriverOnboardingApplication:
    if application.status not in APPROVAL_SOURCE_STATUSES and application.status != "approved":
        raise ValueError(f"Application cannot be approved from status {application.status}")
    if application.status == "approved":
        return application

    previous = application.status
    application.status = "approved"
    application.approved_at = now()
    application.updated_at = now()
    application.status_reason = reason
    assert_transition_allowed(previous, "approved")
    _record_audit(
        db,
        application=application,
        event_type="application_approved",
        from_status=previous,
        to_status="approved",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
    )
    db.commit()
    db.refresh(application)
    return application


def reject_application(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    actor_role: str,
    reason: str,
) -> PlatformDriverOnboardingApplication:
    if application.status in {"rejected", "activated"}:
        raise ValueError(f"Application cannot be rejected from status {application.status}")
    previous = application.status
    application.status = "rejected"
    application.rejection_reason = reason
    application.rejected_at = now()
    application.updated_at = now()
    _record_audit(
        db,
        application=application,
        event_type="application_rejected",
        from_status=previous,
        to_status="rejected",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
    )
    db.commit()
    db.refresh(application)
    return application


def suspend_application(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    actor_role: str,
    reason: str,
) -> PlatformDriverOnboardingApplication:
    if application.status not in {"under_review", "approved", "activated", "background_review", "documents_pending"}:
        raise ValueError(f"Application cannot be suspended from status {application.status}")
    previous = application.status
    application.status = "suspended"
    application.suspension_reason = reason
    application.suspended_at = now()
    application.updated_at = now()
    assert_transition_allowed(previous, "suspended")
    _record_audit(
        db,
        application=application,
        event_type="application_suspended",
        from_status=previous,
        to_status="suspended",
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        reason=reason,
    )
    db.commit()
    db.refresh(application)
    return application


def add_internal_note(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    author_user_id: str,
    note_text: str,
    category: str | None = None,
) -> PlatformDriverOnboardingInternalNote:
    note = PlatformDriverOnboardingInternalNote(
        id=uuid4(),
        application_id=application.id,
        author_user_id=author_user_id,
        note_text=note_text.strip(),
        category=(category or "").strip() or None,
        created_at=now(),
    )
    db.add(note)
    _record_audit(
        db,
        application=application,
        event_type="internal_note_added",
        actor_user_id=author_user_id,
        reason=note_text[:200],
    )
    db.commit()
    db.refresh(note)
    return note


def list_applications_for_org(
    db: Session,
    *,
    organization_id: str,
    status: str | None = None,
    limit: int = 100,
) -> list[PlatformDriverOnboardingApplication]:
    query = db.query(PlatformDriverOnboardingApplication).filter(
        PlatformDriverOnboardingApplication.organization_id == organization_id
    )
    if status:
        query = query.filter(PlatformDriverOnboardingApplication.status == normalize_status(status))
    return query.order_by(PlatformDriverOnboardingApplication.created_at.desc()).limit(limit).all()


def upload_document(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    category: str,
    filename: str,
    content_type: str,
    file_bytes: bytes,
    expires_at: date | None = None,
) -> PlatformDriverOnboardingDocument:
    if category not in DOCUMENT_CATEGORIES:
        raise ValueError(f"Unsupported document category: {category}")
    if category in STATUS_ONLY_DOCUMENT_CATEGORIES:
        raise ValueError("Use status-only endpoint for this document category.")

    from app.modules.platform_ops.secure_storage import (
        SecureStorageNotConfigured,
        validate_document_upload,
    )

    validate_document_upload(filename=filename, content_type=content_type, file_bytes=file_bytes)

    incoming_size = len(file_bytes)
    # Idempotent: Continue/Save/Submit often re-posts the same selected file.
    identical = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.application_id == application.id,
            PlatformDriverOnboardingDocument.category == category,
            PlatformDriverOnboardingDocument.original_filename == filename,
            PlatformDriverOnboardingDocument.byte_size == incoming_size,
            PlatformDriverOnboardingDocument.review_status.in_(("pending", "accepted")),
        )
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .first()
    )
    if identical is not None:
        return identical

    try:
        storage = get_document_storage()
    except SecureStorageNotConfigured:
        raise
    backend, storage_ref, byte_size = storage.store(
        organization_id=application.organization_id,
        application_id=application.id,
        category=category,
        filename=filename,
        content_type=content_type,
        stream=BytesIO(file_bytes),
    )

    # Replace the latest pending row for this category instead of stacking duplicates.
    latest_pending = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.application_id == application.id,
            PlatformDriverOnboardingDocument.category == category,
            PlatformDriverOnboardingDocument.review_status == "pending",
        )
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .first()
    )
    if latest_pending is not None:
        previous_ref = latest_pending.storage_ref
        latest_pending.storage_backend = backend
        latest_pending.storage_ref = storage_ref
        latest_pending.original_filename = filename
        latest_pending.content_type = content_type
        latest_pending.byte_size = byte_size
        latest_pending.expires_at = expires_at
        latest_pending.updated_at = now()
        if previous_ref and previous_ref != storage_ref:
            try:
                storage.delete(storage_ref=previous_ref)
            except Exception:
                logger.warning(
                    "document_replace_cleanup_failed application_id=%s document_id=%s",
                    application.id,
                    latest_pending.id,
                )
        _record_audit(
            db,
            application=application,
            event_type="document_replaced",
            metadata={"category": category, "document_id": latest_pending.id},
        )
        db.commit()
        db.refresh(latest_pending)
        return latest_pending

    document = PlatformDriverOnboardingDocument(
        id=uuid4(),
        application_id=application.id,
        organization_id=application.organization_id,
        category=category,
        storage_backend=backend,
        storage_ref=storage_ref,
        original_filename=filename,
        content_type=content_type,
        byte_size=byte_size,
        expires_at=expires_at,
        review_status="pending",
        created_at=now(),
        updated_at=now(),
    )
    db.add(document)
    _record_audit(
        db,
        application=application,
        event_type="document_uploaded",
        metadata={"category": category, "document_id": document.id},
    )
    db.commit()
    db.refresh(document)
    return document


def upsert_status_only_document(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    category: str,
    status_only_value: str,
) -> PlatformDriverOnboardingDocument:
    if category not in STATUS_ONLY_DOCUMENT_CATEGORIES:
        raise ValueError("Category is not status-only.")
    existing = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(
            PlatformDriverOnboardingDocument.application_id == application.id,
            PlatformDriverOnboardingDocument.category == category,
        )
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .first()
    )
    if existing:
        existing.status_only_value = status_only_value
        existing.review_status = "accepted" if status_only_value in {"provided", "verified", "signed"} else "pending"
        existing.updated_at = now()
        document = existing
    else:
        document = PlatformDriverOnboardingDocument(
            id=uuid4(),
            application_id=application.id,
            organization_id=application.organization_id,
            category=category,
            storage_backend="status_only",
            status_only_value=status_only_value,
            review_status="accepted" if status_only_value in {"provided", "verified", "signed"} else "pending",
            created_at=now(),
            updated_at=now(),
        )
        db.add(document)
    _record_audit(
        db,
        application=application,
        event_type="document_status_updated",
        metadata={"category": category, "status_only_value": status_only_value},
    )
    db.commit()
    db.refresh(document)
    return document


def review_document(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication,
    document: PlatformDriverOnboardingDocument,
    review_status: str,
    review_reason: str | None,
    reviewer_user_id: str,
    expires_at: date | None = None,
) -> PlatformDriverOnboardingDocument:
    document.review_status = review_status
    document.review_reason = review_reason
    document.reviewed_by = reviewer_user_id
    document.reviewed_at = now()
    if expires_at is not None:
        document.expires_at = expires_at
    document.updated_at = now()
    _record_audit(
        db,
        application=application,
        event_type="document_reviewed",
        actor_user_id=reviewer_user_id,
        reason=review_reason,
        metadata={"document_id": document.id, "review_status": review_status},
    )
    db.commit()
    db.refresh(document)
    return document


def document_to_response(document: PlatformDriverOnboardingDocument) -> DocumentMetadataResponse:
    return DocumentMetadataResponse(
        id=document.id,
        category=document.category,
        review_status=document.review_status,
        review_reason=document.review_reason,
        reviewed_by=document.reviewed_by,
        reviewed_at=document.reviewed_at,
        expires_at=document.expires_at,
        status_only_value=document.status_only_value,
        original_filename=document.original_filename,
        content_type=document.content_type,
        byte_size=document.byte_size,
        storage_backend=document.storage_backend,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def application_to_detail(
    db: Session,
    application: PlatformDriverOnboardingApplication,
    *,
    include_full_license: bool = False,
    include_readiness: bool = True,
) -> DriverApplicationDetailResponse:
    documents = (
        db.query(PlatformDriverOnboardingDocument)
        .filter(PlatformDriverOnboardingDocument.application_id == application.id)
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .all()
    )
    readiness_raw = compute_readiness_summary(db, application) if include_readiness else None
    readiness = ReadinessSummaryResponse(**readiness_raw) if readiness_raw else None
    license_masked = mask_license_number(application.drivers_license_number)
    if include_full_license:
        license_masked = application.drivers_license_number

    return DriverApplicationDetailResponse(
        id=application.id,
        organization_id=application.organization_id,
        status=application.status,
        status_reason=application.status_reason,
        legal_first_name=application.legal_first_name,
        legal_middle_name=application.legal_middle_name,
        legal_last_name=application.legal_last_name,
        date_of_birth=application.date_of_birth,
        email=application.email,
        mobile_phone=mask_phone(application.mobile_phone) if not include_full_license else application.mobile_phone,
        home_address=application.home_address,
        city=application.city,
        state=application.state,
        zip_code=application.zip_code,
        emergency_contact_name=application.emergency_contact_name,
        emergency_contact_phone=mask_phone(application.emergency_contact_phone)
        if not include_full_license
        else application.emergency_contact_phone,
        preferred_language=application.preferred_language,
        drivers_license_number_masked=license_masked,
        license_issuing_state=application.license_issuing_state,
        license_expiration_date=application.license_expiration_date,
        years_driving_experience=application.years_driving_experience,
        employment_type=application.employment_type,
        availability_days=_deserialize_availability_days(application.availability_days_json),
        availability_start_time=application.availability_start_time,
        availability_end_time=application.availability_end_time,
        willing_weekends=application.willing_weekends,
        willing_wheelchair=application.willing_wheelchair,
        service_area_counties=application.service_area_counties,
        vehicle_year=getattr(application, "vehicle_year", None),
        vehicle_make=getattr(application, "vehicle_make", None),
        vehicle_model=getattr(application, "vehicle_model", None),
        vehicle_license_plate=getattr(application, "vehicle_license_plate", None),
        vehicle_vin=getattr(application, "vehicle_vin", None),
        vehicle_color=getattr(application, "vehicle_color", None),
        vehicle_plate_state=getattr(application, "vehicle_plate_state", None),
        vehicle_registration_expiration=getattr(application, "vehicle_registration_expiration", None),
        internal_driver_number=getattr(application, "internal_driver_number", None),
        insurance_carrier=getattr(application, "insurance_carrier", None),
        insurance_policy_ref_masked=getattr(application, "insurance_policy_ref_masked", None),
        insurance_effective_date=getattr(application, "insurance_effective_date", None),
        insurance_expiration_date=getattr(application, "insurance_expiration_date", None),
        insurance_review_status=getattr(application, "insurance_review_status", None),
        agreement_version=getattr(application, "agreement_version", None),
        agreement_status=getattr(application, "agreement_status", None),
        agreement_accepted_at=getattr(application, "agreement_accepted_at", None),
        w9_workflow_status=getattr(application, "w9_workflow_status", None),
        w9_workflow_updated_at=getattr(application, "w9_workflow_updated_at", None),
        declaration_valid_license=application.declaration_valid_license,
        declaration_mvr_authorization=application.declaration_mvr_authorization,
        declaration_background_authorization=application.declaration_background_authorization,
        declaration_drug_alcohol_policy=application.declaration_drug_alcohol_policy,
        declaration_truthful_information=application.declaration_truthful_information,
        electronic_signature=application.electronic_signature,
        signed_date=application.signed_date,
        assigned_reviewer_id=application.assigned_reviewer_id,
        reviewed_at=application.reviewed_at,
        approved_at=application.approved_at,
        activated_at=application.activated_at,
        rejected_at=application.rejected_at,
        suspended_at=application.suspended_at,
        rejection_reason=application.rejection_reason,
        suspension_reason=application.suspension_reason,
        activated_driver_id=application.activated_driver_id,
        submitted_at=application.submitted_at,
        created_at=application.created_at,
        updated_at=application.updated_at,
        documents=[document_to_response(doc) for doc in documents],
        readiness=readiness,
        allowed_next_statuses=list_allowed_next_statuses(application.status),
    )


def application_to_list_item(db: Session, application: PlatformDriverOnboardingApplication) -> DriverApplicationListItemResponse:
    readiness = compute_readiness_summary(db, application)
    name_parts = [application.legal_first_name or "", application.legal_last_name or ""]
    applicant_name = " ".join(part for part in name_parts if part).strip() or None
    return DriverApplicationListItemResponse(
        id=application.id,
        organization_id=application.organization_id,
        status=application.status,
        applicant_name=applicant_name,
        application_date=application.submitted_at or application.created_at,
        email=application.email,
        mobile_phone=mask_phone(application.mobile_phone),
        license_expiration_date=application.license_expiration_date,
        document_completion_percentage=readiness["document_completion_percentage"],
        missing_documents=readiness["missing_documents"],
        compliance_warnings=readiness["compliance_warnings"],
        assigned_reviewer_id=application.assigned_reviewer_id,
    )


def list_document_categories() -> list[DocumentCategoryInfo]:
    items: list[DocumentCategoryInfo] = []
    for category in DOCUMENT_CATEGORIES:
        items.append(
            DocumentCategoryInfo(
                category=category,
                label=DOCUMENT_LABELS.get(category, category.replace("_", " ").title()),
                requires_upload=category not in STATUS_ONLY_DOCUMENT_CATEGORIES,
                sensitive=category in SENSITIVE_CATEGORIES,
            )
        )
    return items
