"""Phase 2B P1 owner/compliance onboarding workflow.

Controlled review using test/placeholder data. Does not activate drivers,
enable dispatch, enable STS/MHCP, store SSN/TIN, or invent vendors.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.audit import record_audit
from app.modules.approval_engine.eligibility import (
    dispatch_gate_enabled,
    sts_mhcp_dispatch_enabled,
    vehicle_is_assignable,
)
from app.modules.approval_engine.esign_provider import esign_provider_capability
from app.modules.approval_engine.external_verification import is_externally_satisfied
from app.modules.approval_engine.models import (
    ApprovalCase,
    ApprovalTrainingModule,
    ApprovalVehicleRecord,
)
from app.modules.approval_engine.sensitive_providers import reject_raw_sensitive_payload
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
    PlatformDriverOnboardingInternalNote,
)
from app.modules.platform_ops.onboarding.service import SIMPLE_REQUIRED_UPLOAD_CATEGORIES

READINESS_STATES = (
    "READY",
    "PENDING",
    "BLOCKED",
    "EXPIRED",
    "NOT_REQUIRED",
    "NOT_AVAILABLE_YET",
)

W9_WORKFLOW_STATUSES = frozenset(
    {"requested", "pending", "completed", "externally_verified"}
)
AGREEMENT_STATUSES = frozenset(
    {"pending", "accepted", "signed", "returned", "expired"}
)
INSURANCE_REVIEW_STATUSES = frozenset(
    {"pending", "accepted", "rejected", "expired", "correction_requested"}
)
VEHICLE_ELIGIBILITY_STATUSES = frozenset(
    {"PENDING", "REVIEWED", "ELIGIBLE_NOT_ACTIVE", "BLOCKED", "EXPIRED"}
)

_REQUIRED_DOC_LABELS = {
    "drivers_license_front": "Driver's license (front)",
    "drivers_license_back": "Driver's license (back)",
    "vehicle_registration": "Vehicle registration",
    "proof_of_auto_insurance": "Proof of auto insurance",
    "independent_contractor_agreement": "Contractor agreement",
}


def mask_policy_reference(raw: str | None) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return ("*" * max(4, len(value) - 4)) + value[-4:]


def _latest_doc(
    documents: list[PlatformDriverOnboardingDocument], category: str
) -> PlatformDriverOnboardingDocument | None:
    matches = [doc for doc in documents if doc.category == category]
    if not matches:
        return None
    return sorted(matches, key=lambda doc: str(doc.created_at or ""), reverse=True)[0]


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _req(case: ApprovalCase, key: str):
    return next((row for row in (case.requirements or []) if row.requirement_key == key), None)


def _item(
    *,
    key: str,
    label: str,
    state: str,
    status: str | None = None,
    tier: str = "BASE_PRIVATE_AMBULATORY",
    notes: str | None = None,
    expiration: date | None = None,
) -> dict[str, Any]:
    if state not in READINESS_STATES:
        state = "PENDING"
    return {
        "key": key,
        "label": label,
        "state": state,
        "status": status,
        "tier": tier,
        "notes": notes,
        "expiration": _iso(expiration),
    }


def _state_from_requirement(req, *, not_required_ok: bool = True) -> str:
    if req is None:
        return "PENDING"
    status = str(req.status or "").upper()
    if status in {"NOT_REQUIRED", "CONDITIONAL_NOT_APPLICABLE", "FUTURE"}:
        return "NOT_REQUIRED" if not_required_ok else "NOT_AVAILABLE_YET"
    if status in {"EXPIRED"}:
        return "EXPIRED"
    if status in {"FAILED", "DISQUALIFIED", "REJECTED", "CORRECTION_REQUESTED", "MISSING", "MISSING_CONSENT"}:
        return "BLOCKED"
    if status in {"COMPLETE", "VERIFIED", "CLEARED", "SIGNED"}:
        if req.expiration_date and req.expiration_date < date.today():
            return "EXPIRED"
        return "READY"
    if status in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW", "PENDING_VERIFICATION", "IN_PROGRESS", "PENDING"}:
        return "PENDING"
    return "PENDING"


def _document_item(
    documents: list[PlatformDriverOnboardingDocument],
    category: str,
    label: str,
) -> dict[str, Any]:
    latest = _latest_doc(documents, category)
    if latest is None:
        return _item(key=category, label=label, state="BLOCKED", status="MISSING", notes="No upload on file")
    if latest.review_status == "rejected":
        return _item(key=category, label=label, state="BLOCKED", status="rejected", notes=latest.review_reason)
    if latest.review_status == "correction_requested":
        return _item(key=category, label=label, state="BLOCKED", status="correction_requested", notes=latest.review_reason)
    if latest.expires_at and latest.expires_at < date.today():
        return _item(
            key=category,
            label=label,
            state="EXPIRED",
            status=latest.review_status,
            expiration=latest.expires_at,
        )
    if latest.review_status == "accepted":
        return _item(key=category, label=label, state="READY", status="accepted", expiration=latest.expires_at)
    return _item(key=category, label=label, state="PENDING", status=latest.review_status or "pending")


def load_application_documents(
    db: Session, application: PlatformDriverOnboardingApplication | None
) -> list[PlatformDriverOnboardingDocument]:
    if application is None:
        return []
    return (
        db.query(PlatformDriverOnboardingDocument)
        .filter(PlatformDriverOnboardingDocument.application_id == application.id)
        .order_by(PlatformDriverOnboardingDocument.created_at.desc())
        .all()
    )


def p1_approval_blockers(
    db: Session,
    case: ApprovalCase,
    application: PlatformDriverOnboardingApplication | None = None,
) -> list[str]:
    """Extra P1 blockers that must stop owner APPROVE even if requirement rows were marked complete."""
    blockers: list[str] = []
    documents = load_application_documents(db, application)
    for category in SIMPLE_REQUIRED_UPLOAD_CATEGORIES:
        latest = _latest_doc(documents, category)
        if latest is None:
            continue
        if latest.review_status == "rejected":
            blockers.append(f"Required document rejected: {category}")
        elif latest.review_status == "correction_requested":
            blockers.append(f"Required document returned for correction: {category}")

    insurance_exp = None
    if application is not None:
        insurance_exp = getattr(application, "insurance_expiration_date", None)
    insurance_exp = insurance_exp or case.insurance_expiration
    if insurance_exp and insurance_exp < date.today():
        blockers.append("Insurance is expired")
    insurance_doc = _latest_doc(documents, "proof_of_auto_insurance")
    if insurance_doc and insurance_doc.expires_at and insurance_doc.expires_at < date.today():
        if "Insurance is expired" not in blockers:
            blockers.append("Insurance is expired")

    mvr = _req(case, "mvr")
    if mvr is not None and mvr.timing in {"required_now", "required_before_activation"} and mvr.is_blocking:
        if not is_externally_satisfied(mvr.status) and str(mvr.status or "").upper() not in {
            "COMPLETE",
            "VERIFIED",
            "CLEARED",
        }:
            blockers.append("MVR is incomplete")

    base_modules = [
        module
        for module in (case.training_modules or [])
        if module.module_key not in {"sts_service_rules", "behind_wheel_eval"}
    ]
    if base_modules and any(module.status != "completed" for module in base_modules):
        blockers.append("Required training is incomplete")

    vehicles = list(case.vehicles or [])
    for vehicle in vehicles:
        eligibility = str(getattr(vehicle, "eligibility_status", None) or vehicle.vehicle_status or "PENDING")
        if eligibility in {"BLOCKED", "EXPIRED"} or (
            getattr(vehicle, "insurance_expiration", None)
            and vehicle.insurance_expiration < date.today()
        ):
            blockers.append("Vehicle review is blocked or expired")
            break
        if eligibility in {"PENDING"} or str(vehicle.vehicle_status or "").upper() == "PENDING":
            blockers.append("Required vehicle review is incomplete")
            break

    return blockers


def build_readiness_view(
    db: Session,
    case: ApprovalCase,
    application: PlatformDriverOnboardingApplication | None = None,
) -> dict[str, Any]:
    documents = load_application_documents(db, application)
    items: list[dict[str, Any]] = []

    identity_docs = [
        _document_item(documents, "drivers_license_front", "Identity document — license front"),
        _document_item(documents, "drivers_license_back", "Identity document — license back"),
    ]
    if any(row["state"] == "BLOCKED" for row in identity_docs):
        identity_state = "BLOCKED"
    elif any(row["state"] == "EXPIRED" for row in identity_docs):
        identity_state = "EXPIRED"
    elif all(row["state"] == "READY" for row in identity_docs):
        identity_state = "READY"
    else:
        identity_state = "PENDING"
    items.append(
        _item(
            key="identity_documents",
            label="Identity documents",
            state=identity_state,
            status=", ".join(f"{row['key']}={row['status']}" for row in identity_docs),
        )
    )
    items.append(_document_item(documents, "drivers_license_front", "Driver's license"))
    items.append(_item(key="mvr", label="MVR", state=_state_from_requirement(_req(case, "mvr")), status=(_req(case, "mvr").status if _req(case, "mvr") else case.mvr_status)))

    insurance_req = _req(case, "vehicle_insurance")
    insurance_exp = None
    if application is not None:
        insurance_exp = getattr(application, "insurance_expiration_date", None)
    insurance_exp = insurance_exp or case.insurance_expiration
    insurance_state = _state_from_requirement(insurance_req)
    if insurance_exp and insurance_exp < date.today():
        insurance_state = "EXPIRED"
    items.append(
        _item(
            key="insurance",
            label="Insurance",
            state=insurance_state,
            status=(
                getattr(application, "insurance_review_status", None)
                if application is not None
                else None
            )
            or (insurance_req.status if insurance_req else case.insurance_status),
            expiration=insurance_exp,
            notes=(
                getattr(application, "insurance_carrier", None) if application is not None else None
            ),
        )
    )
    items.append(
        _item(
            key="vehicle_registration",
            label="Vehicle registration",
            state=_state_from_requirement(_req(case, "vehicle_registration")),
            status=_req(case, "vehicle_registration").status if _req(case, "vehicle_registration") else case.vehicle_registration_status,
            expiration=case.vehicle_registration_expiration,
        )
    )
    items.append(
        _item(
            key="vehicle_inspection",
            label="Vehicle inspection",
            state=_state_from_requirement(_req(case, "vehicle_inspection")),
            status=_req(case, "vehicle_inspection").status if _req(case, "vehicle_inspection") else case.inspection_status,
            expiration=case.inspection_expiration,
        )
    )

    agreement_status = None
    if application is not None:
        agreement_status = getattr(application, "agreement_status", None)
    agreement_req = _req(case, "contractor_agreement")
    agreement_state = _state_from_requirement(agreement_req)
    if agreement_status in {"accepted", "signed"} and getattr(application, "agreement_version", None):
        agreement_state = "READY"
    items.append(
        _item(
            key="contractor_agreement",
            label="Contractor agreement",
            state=agreement_state,
            status=agreement_status or (agreement_req.status if agreement_req else case.contractor_agreement_status),
            notes=getattr(application, "agreement_version", None) if application is not None else None,
        )
    )

    w9_status = getattr(application, "w9_workflow_status", None) if application is not None else None
    w9_req = _req(case, "w9")
    if w9_status in {"completed", "externally_verified"}:
        w9_state = "READY"
    elif w9_status in {"requested", "pending"}:
        w9_state = "PENDING"
    else:
        w9_state = _state_from_requirement(w9_req)
    items.append(_item(key="w9", label="W-9 workflow", state=w9_state, status=w9_status or (w9_req.status if w9_req else case.w9_status)))

    training_req = _req(case, "base_training")
    items.append(
        _item(
            key="training",
            label="Training",
            state=_state_from_requirement(training_req),
            status=training_req.status if training_req else None,
        )
    )

    background = _req(case, "background_study")
    fingerprint = _req(case, "fingerprint")
    items.append(
        _item(
            key="background_study",
            label="Background study",
            state=_state_from_requirement(background),
            status=background.status if background else case.background_study_status,
            tier="STS_ELIGIBLE",
            notes="Not required for PRIVATE / BASE ambulatory",
        )
    )
    items.append(
        _item(
            key="fingerprinting",
            label="Fingerprinting",
            state=_state_from_requirement(fingerprint),
            status=fingerprint.status if fingerprint else case.fingerprint_status,
            tier="STS_ELIGIBLE",
            notes="Not required for PRIVATE / BASE ambulatory",
        )
    )

    from app.modules.platform_ops.secure_storage import secure_document_storage_readiness

    storage_ready = secure_document_storage_readiness()
    items.append(
        _item(
            key="secure_document_storage",
            label="SECURE_DOCUMENT_STORAGE",
            state="READY" if storage_ready["state"] == "READY" else "BLOCKED",
            status=str(storage_ready.get("backend") or ""),
            notes=str(storage_ready.get("reason") or "Production-safe private storage is required"),
        )
    )

    payout = _req(case, "payout_setup")
    payout_state = "NOT_AVAILABLE_YET"
    if case.payout_setup_status in {"COMPLETE", "VERIFIED", "READY"}:
        payout_state = "READY"
    elif payout is not None and payout.status not in {"MISSING", "NOT_STARTED", "ACTION_REQUIRED"}:
        payout_state = _state_from_requirement(payout)
    items.append(
        _item(
            key="payout_setup",
            label="Payout setup",
            state=payout_state,
            status=case.payout_setup_status,
            notes="Tokenized payout provider is not selected",
        )
    )

    approval_status = str(case.owner_approval_status or case.workflow_status or "PENDING")
    if str(case.workflow_status or "").upper() in {"APPROVED", "OWNER_APPROVED", "ACTIVE"}:
        approval_state = "READY"
    elif str(case.workflow_status or "").upper() in {"REJECTED", "DENIED", "FAILED"}:
        approval_state = "BLOCKED"
    else:
        approval_state = "PENDING"
    items.append(
        _item(
            key="overall_approval",
            label="Overall approval status",
            state=approval_state,
            status=approval_status,
        )
    )

    dispatch_state = "BLOCKED"
    dispatch_notes = "Live dispatch remains closed for onboarding-origin drivers"
    if dispatch_gate_enabled():
        dispatch_notes = "Dispatch gate is ON — unexpected for this phase"
    items.append(
        _item(
            key="dispatch_eligibility",
            label="Dispatch eligibility",
            state=dispatch_state,
            status="BLOCKED",
            notes=dispatch_notes,
        )
    )
    items.append(
        _item(
            key="private_eligibility",
            label="PRIVATE / BASE eligibility",
            state="PENDING" if approval_state != "READY" else "PENDING",
            status=case.workflow_status,
            notes="PRIVATE review is separate from STS/MHCP. Dispatch stays blocked in this phase.",
        )
    )
    items.append(
        _item(
            key="sts_mhcp_eligibility",
            label="STS / MHCP eligibility",
            state="NOT_REQUIRED" if not sts_mhcp_dispatch_enabled() else "BLOCKED",
            status="DISABLED",
            tier="STS_ELIGIBLE",
            notes="STS/MHCP passenger dispatch is disabled. AMICOR is not authorized.",
        )
    )

    counts = {state: 0 for state in READINESS_STATES}
    for row in items:
        counts[row["state"]] = counts.get(row["state"], 0) + 1

    return {
        "case_id": case.id,
        "display_badge": case.display_badge,
        "application_id": case.platform_ops_application_id,
        "workflow_status": case.workflow_status,
        "activation_status": case.activation_status,
        "dispatch_gate_enabled": dispatch_gate_enabled(),
        "sts_mhcp_dispatch_enabled": sts_mhcp_dispatch_enabled(),
        "private_and_sts_remain_separate": True,
        "secure_document_storage": storage_ready,
        "items": items,
        "counts": counts,
        "p1_blockers": p1_approval_blockers(db, case, application),
    }


def record_insurance_review(
    db: Session,
    *,
    case: ApprovalCase,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    carrier: str | None = None,
    policy_reference: str | None = None,
    effective_date: date | None = None,
    expiration_date: date | None = None,
    vehicle_association: str | None = None,
    review_status: str = "pending",
    notes: str | None = None,
    evidence_ref: str | None = None,
) -> dict[str, Any]:
    status = str(review_status or "pending").strip().lower()
    if status not in INSURANCE_REVIEW_STATUSES:
        raise ValueError(f"Invalid insurance review status: {review_status}")
    if expiration_date and expiration_date < date.today():
        status = "expired"
    application.insurance_carrier = (carrier or application.insurance_carrier or "").strip() or None
    application.insurance_policy_ref_masked = mask_policy_reference(policy_reference) or application.insurance_policy_ref_masked
    application.insurance_effective_date = effective_date or application.insurance_effective_date
    application.insurance_expiration_date = expiration_date or application.insurance_expiration_date
    application.insurance_vehicle_association = vehicle_association or application.insurance_vehicle_association
    application.insurance_review_status = status
    application.insurance_reviewed_by = actor_user_id
    application.insurance_reviewed_at = now()
    application.insurance_review_notes = notes
    application.insurance_evidence_ref = evidence_ref
    application.updated_at = now()
    case.insurance_expiration = application.insurance_expiration_date
    if status == "expired":
        case.insurance_status = "EXPIRED"
    elif status == "accepted":
        case.insurance_status = "REVIEWED"
    elif status == "rejected":
        case.insurance_status = "FAILED"
    case.updated_at = now()
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        actor_type="USER",
        actor_id=actor_user_id,
        action="insurance_review_recorded",
        reason=notes or f"Insurance review {status}",
        evidence_ref=evidence_ref,
        metadata={
            "carrier": application.insurance_carrier,
            "policy_ref_masked": application.insurance_policy_ref_masked,
            "effective_date": _iso(application.insurance_effective_date),
            "expiration_date": _iso(application.insurance_expiration_date),
            "review_status": status,
            "vehicle_association": application.insurance_vehicle_association,
        },
    )
    db.commit()
    db.refresh(application)
    return serialize_insurance(application)


def serialize_insurance(application: PlatformDriverOnboardingApplication) -> dict[str, Any]:
    expired = bool(
        application.insurance_expiration_date
        and application.insurance_expiration_date < date.today()
    )
    return {
        "carrier": getattr(application, "insurance_carrier", None),
        "policy_ref_masked": getattr(application, "insurance_policy_ref_masked", None),
        "effective_date": _iso(getattr(application, "insurance_effective_date", None)),
        "expiration_date": _iso(getattr(application, "insurance_expiration_date", None)),
        "vehicle_association": getattr(application, "insurance_vehicle_association", None),
        "review_status": "expired" if expired else getattr(application, "insurance_review_status", None),
        "reviewer": getattr(application, "insurance_reviewed_by", None),
        "reviewed_at": _iso(getattr(application, "insurance_reviewed_at", None)),
        "notes": getattr(application, "insurance_review_notes", None),
        "evidence_ref": getattr(application, "insurance_evidence_ref", None),
        "expired": expired,
        "commercial_policy_not_required_for_private": True,
    }


def record_agreement(
    db: Session,
    *,
    case: ApprovalCase,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    version: str,
    status: str = "accepted",
    accepted_at: datetime | None = None,
    evidence_document_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    status_norm = str(status or "accepted").strip().lower()
    if status_norm not in AGREEMENT_STATUSES:
        raise ValueError(f"Invalid agreement status: {status}")
    version_norm = str(version or "").strip()
    if not version_norm:
        raise ValueError("Agreement version is required")
    documents = load_application_documents(db, application)
    latest_agreement = _latest_doc(documents, "independent_contractor_agreement")
    evidence_id = evidence_document_id or (latest_agreement.id if latest_agreement else None)
    application.agreement_version = version_norm
    application.agreement_status = status_norm
    application.agreement_accepted_at = accepted_at or (
        now() if status_norm in {"accepted", "signed"} else application.agreement_accepted_at
    )
    application.agreement_evidence_document_id = evidence_id
    application.updated_at = now()
    if status_norm in {"accepted", "signed"}:
        case.contractor_agreement_status = "SIGNED"
    case.updated_at = now()
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        actor_type="USER",
        actor_id=actor_user_id,
        action="contractor_agreement_version_recorded",
        reason=notes or f"Agreement {version_norm} {status_norm}",
        evidence_ref=evidence_id,
        metadata={
            "version": version_norm,
            "status": status_norm,
            "applicant": f"{application.legal_first_name or ''} {application.legal_last_name or ''}".strip(),
            "typed_signature": application.electronic_signature,
            "signed_date": _iso(application.signed_date),
        },
    )
    db.commit()
    db.refresh(application)
    return serialize_agreement(application)


def serialize_agreement(application: PlatformDriverOnboardingApplication) -> dict[str, Any]:
    evidence_id = getattr(application, "agreement_evidence_document_id", None)
    inspect_path = None
    if evidence_id:
        inspect_path = (
            f"/api/platform-ops/driver-onboarding/applications/{application.id}"
            f"/documents/{evidence_id}/download"
        )
    cap = esign_provider_capability()
    return {
        "agreement_version": getattr(application, "agreement_version", None),
        "status": getattr(application, "agreement_status", None),
        "accepted_at": _iso(getattr(application, "agreement_accepted_at", None)),
        "applicant": f"{application.legal_first_name or ''} {application.legal_last_name or ''}".strip() or None,
        "typed_signature": application.electronic_signature,
        "signed_date": _iso(application.signed_date),
        "evidence_document_id": evidence_id,
        "inspect_path": inspect_path,
        "public_url_exposed": False,
        "esign_provider": {
            "provider_key": cap.provider_key,
            "mode": cap.mode,
            "live": cap.live,
            "vendor_selected": cap.vendor_selected,
            "notes": cap.notes,
        },
    }


def record_w9_workflow(
    db: Session,
    *,
    case: ApprovalCase,
    application: PlatformDriverOnboardingApplication,
    actor_user_id: str,
    status: str,
    external_provider: str | None = None,
    external_reference: str | None = None,
    notes: str | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reject_raw_sensitive_payload(payload)
    status_norm = str(status or "").strip().lower()
    if status_norm not in W9_WORKFLOW_STATUSES:
        raise ValueError(f"Invalid W-9 workflow status: {status}")
    application.w9_workflow_status = status_norm
    application.w9_workflow_updated_at = now()
    application.w9_external_provider = (external_provider or "").strip() or None
    application.w9_external_reference = (external_reference or "").strip() or None
    application.updated_at = now()
    if status_norm in {"completed", "externally_verified"}:
        case.w9_status = "COMPLETE"
    case.updated_at = now()
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        actor_type="USER",
        actor_id=actor_user_id,
        action="w9_workflow_recorded",
        reason=notes or f"W-9 workflow {status_norm}",
        evidence_ref=application.w9_external_reference,
        metadata={
            "status": status_norm,
            "external_provider": application.w9_external_provider,
            "stores_ssn_tin": False,
        },
    )
    db.commit()
    db.refresh(application)
    return serialize_w9(application)


def serialize_w9(application: PlatformDriverOnboardingApplication) -> dict[str, Any]:
    return {
        "status": getattr(application, "w9_workflow_status", None),
        "updated_at": _iso(getattr(application, "w9_workflow_updated_at", None)),
        "external_provider": getattr(application, "w9_external_provider", None),
        "external_reference": getattr(application, "w9_external_reference", None),
        "stores_ssn_tin": False,
    }


def upsert_vehicle_record(
    db: Session,
    *,
    case: ApprovalCase,
    actor_user_id: str,
    make: str | None = None,
    model: str | None = None,
    year: int | None = None,
    license_plate: str | None = None,
    registration_expiration: date | None = None,
    inspection_status: str | None = None,
    inspection_expiration: date | None = None,
    insurance_association_ref: str | None = None,
    insurance_expiration: date | None = None,
    eligibility_status: str = "PENDING",
    health_isf_vehicle_id: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    status = str(eligibility_status or "PENDING").strip().upper()
    if status not in VEHICLE_ELIGIBILITY_STATUSES:
        raise ValueError(f"Invalid vehicle eligibility status: {eligibility_status}")
    plate = str(license_plate or "").strip().upper() or None
    if plate and plate.startswith("ONBD-"):
        raise ValueError("ONBD- placeholder plates cannot be used for the real-plate vehicle record")
    today = date.today()
    if (
        (registration_expiration and registration_expiration < today)
        or (insurance_expiration and insurance_expiration < today)
        or (inspection_expiration and inspection_expiration < today)
    ):
        status = "EXPIRED"
    existing = next(iter(case.vehicles or []), None)
    if existing is None:
        existing = ApprovalVehicleRecord(
            id=uuid4(),
            case_id=case.id,
            organization_id=case.organization_id,
            created_at=now(),
            updated_at=now(),
        )
        db.add(existing)
        if case.vehicles is not None:
            case.vehicles.append(existing)
    existing.make = make or existing.make
    existing.model = model or existing.model
    existing.year = year or existing.year
    existing.license_plate = plate or existing.license_plate
    existing.registration_expiration = registration_expiration or existing.registration_expiration
    existing.inspection_status = inspection_status or existing.inspection_status
    existing.inspection_expiration = inspection_expiration or existing.inspection_expiration
    existing.insurance_association_ref = insurance_association_ref or existing.insurance_association_ref
    existing.insurance_expiration = insurance_expiration or existing.insurance_expiration
    existing.eligibility_status = status
    existing.vehicle_status = "EXPIRED" if status == "EXPIRED" else ("REVIEWED" if status in {"REVIEWED", "ELIGIBLE_NOT_ACTIVE"} else existing.vehicle_status)
    existing.dispatch_activated = False
    if health_isf_vehicle_id:
        existing.health_isf_vehicle_id = health_isf_vehicle_id
    existing.updated_at = now()
    case.updated_at = now()
    assignable, assign_reason = vehicle_is_assignable(existing, required_tier="BASE_PRIVATE_AMBULATORY")
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="vehicle",
        entity_id=existing.id,
        actor_type="USER",
        actor_id=actor_user_id,
        action="vehicle_record_upserted",
        reason=notes or f"Test vehicle recorded ({existing.license_plate or 'no plate'})",
        metadata={
            "make": existing.make,
            "model": existing.model,
            "year": existing.year,
            "license_plate": existing.license_plate,
            "eligibility_status": existing.eligibility_status,
            "dispatch_activated": False,
            "assignable_for_live_dispatch": assignable,
            "assign_reason": assign_reason,
        },
    )
    db.commit()
    db.refresh(existing)
    return serialize_vehicle(existing)


def serialize_vehicle(vehicle: ApprovalVehicleRecord) -> dict[str, Any]:
    assignable, reason = vehicle_is_assignable(vehicle, required_tier="BASE_PRIVATE_AMBULATORY")
    return {
        "id": vehicle.id,
        "make": vehicle.make,
        "model": vehicle.model,
        "year": vehicle.year,
        "license_plate": getattr(vehicle, "license_plate", None),
        "registration_expiration": _iso(vehicle.registration_expiration),
        "inspection_status": getattr(vehicle, "inspection_status", None),
        "inspection_expiration": _iso(vehicle.inspection_expiration),
        "insurance_association_ref": getattr(vehicle, "insurance_association_ref", None),
        "insurance_expiration": _iso(vehicle.insurance_expiration),
        "eligibility_status": getattr(vehicle, "eligibility_status", None) or vehicle.vehicle_status,
        "vehicle_status": vehicle.vehicle_status,
        "dispatch_activated": bool(getattr(vehicle, "dispatch_activated", False)),
        "health_isf_vehicle_id": vehicle.health_isf_vehicle_id,
        "assignable_for_live_dispatch": assignable and bool(getattr(vehicle, "dispatch_activated", False)),
        "assign_reason": reason if not getattr(vehicle, "dispatch_activated", False) else reason,
    }


def serialize_training(module: ApprovalTrainingModule) -> dict[str, Any]:
    return {
        "id": module.id,
        "module_key": module.module_key,
        "label": module.label,
        "module_version": getattr(module, "module_version", None),
        "status": module.status,
        "assigned_at": _iso(module.assigned_at),
        "completed_at": _iso(module.completed_at),
        "expires_at": _iso(module.expires_at),
        "evidence_ref": module.evidence_ref,
    }


def list_internal_notes(
    db: Session, application: PlatformDriverOnboardingApplication
) -> list[dict[str, Any]]:
    notes = (
        db.query(PlatformDriverOnboardingInternalNote)
        .filter(PlatformDriverOnboardingInternalNote.application_id == application.id)
        .order_by(PlatformDriverOnboardingInternalNote.created_at.desc())
        .all()
    )
    return [
        {
            "id": note.id,
            "category": getattr(note, "category", None),
            "note_text": note.note_text,
            "author_user_id": note.author_user_id,
            "created_at": _iso(note.created_at),
        }
        for note in notes
    ]
