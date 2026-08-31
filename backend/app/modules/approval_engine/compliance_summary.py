"""Master Driver Compliance Summary — traffic lights and overall status.

Reuses Platform Ops applications + Approval Engine cases. Never fabricates
background-check or fingerprint results.
"""
from __future__ import annotations

import os
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.approval_engine.models import ApprovalCase, ApprovalTrainingModule
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
)

SUMMARY_ITEM_KEYS = (
    "application",
    "driver_license",
    "vehicle_registration",
    "insurance",
    "background_check",
    "fingerprint",
    "training",
    "agreements",
    "vehicle_approval",
    "final_admin_approval",
)

OVERALL_STATUSES = (
    "NOT_STARTED",
    "IN_PROGRESS",
    "NEEDS_REVIEW",
    "APPROVED",
    "SUSPENDED",
    "EXPIRED",
)

LICENSE_VERIFICATION = frozenset(
    {"NOT_STARTED", "PENDING", "VERIFIED", "REJECTED", "EXPIRED"}
)
BACKGROUND_STATUSES = frozenset(
    {"NOT_STARTED", "CONSENT_REQUIRED", "PENDING", "CLEAR", "REVIEW_REQUIRED", "FAILED"}
)
FINGERPRINT_STATUSES = frozenset(
    {
        "NOT_REQUIRED",
        "NOT_STARTED",
        "SCHEDULED",
        "PENDING_VERIFICATION",
        "VERIFIED",
        "REJECTED",
    }
)


def fingerprint_required_by_config() -> bool:
    return str(os.getenv("AMICOR_FINGERPRINT_REQUIRED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _latest_doc(
    documents: list[PlatformDriverOnboardingDocument], category: str
) -> PlatformDriverOnboardingDocument | None:
    matches = [doc for doc in documents if doc.category == category]
    if not matches:
        return None
    return sorted(matches, key=lambda doc: str(doc.created_at or ""), reverse=True)[0]


def _req(case: ApprovalCase | None, key: str):
    if case is None:
        return None
    return next((row for row in (case.requirements or []) if row.requirement_key == key), None)


def _expired(value: date | None) -> bool:
    return bool(value and value < date.today())


def _item(
    *,
    key: str,
    label: str,
    light: str,
    status: str,
    required: bool = True,
    notes: str | None = None,
    expiration: date | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "light": light if light in {"GREEN", "YELLOW", "RED"} else "RED",
        "status": status,
        "required": required,
        "notes": notes,
        "expiration": _iso(expiration),
        "missing": list(missing or []),
    }


def _doc_light(doc: PlatformDriverOnboardingDocument | None, *, required: bool = True) -> tuple[str, str, list[str]]:
    if doc is None:
        return ("RED" if required else "GREEN", "MISSING", ["upload"] if required else [])
    if doc.review_status == "rejected":
        return "RED", "REJECTED", [doc.review_reason or "rejected"]
    if _expired(doc.expires_at):
        return "RED", "EXPIRED", ["expired"]
    if doc.review_status == "accepted":
        return "GREEN", "VERIFIED", []
    if doc.review_status in {"pending", "correction_requested"}:
        return "YELLOW", "PENDING", []
    return "YELLOW", str(doc.review_status or "PENDING").upper(), []


def _requirement_light(req, *, fallback_red: bool = True) -> tuple[str, str]:
    if req is None:
        return ("RED" if fallback_red else "YELLOW"), "NOT_STARTED"
    status = str(req.status or "").upper()
    if status in {"NOT_REQUIRED", "CONDITIONAL_NOT_APPLICABLE", "FUTURE"}:
        return "GREEN", "NOT_REQUIRED"
    if status in {"EXPIRED"} or (req.expiration_date and _expired(req.expiration_date)):
        return "RED", "EXPIRED"
    if status in {"FAILED", "DISQUALIFIED", "REJECTED", "MISSING", "MISSING_CONSENT"}:
        return "RED", status
    if status in {"COMPLETE", "VERIFIED", "CLEARED", "SIGNED"}:
        return "GREEN", status
    if status in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW", "PENDING_VERIFICATION", "IN_PROGRESS", "PENDING"}:
        return "YELLOW", status
    return "YELLOW", status or "PENDING"


def _fingerprint_required(case: ApprovalCase | None) -> bool:
    if case is not None:
        raw = str(getattr(case, "fingerprint_status", "") or "").upper()
        if raw == "NOT_REQUIRED":
            return False
        if bool(getattr(case, "fingerprint_required", False)):
            return True
    return fingerprint_required_by_config()


def _application_item(application: PlatformDriverOnboardingApplication | None) -> dict[str, Any]:
    if application is None:
        return _item(
            key="application",
            label="Application",
            light="RED",
            status="NOT_STARTED",
            missing=["application record"],
        )
    missing = []
    for label, value in (
        ("legal first name", application.legal_first_name),
        ("legal last name", application.legal_last_name),
        ("date of birth", application.date_of_birth),
        ("phone", application.mobile_phone),
        ("email", application.email),
        ("home address", application.home_address),
        ("emergency contact name", application.emergency_contact_name),
        ("emergency contact phone", application.emergency_contact_phone),
    ):
        if not value:
            missing.append(label)
    if application.status in {"suspended"}:
        return _item(key="application", label="Application", light="RED", status="SUSPENDED", notes=application.suspension_reason)
    if application.status in {"rejected"}:
        return _item(key="application", label="Application", light="RED", status="REJECTED", notes=application.rejection_reason)
    if missing:
        return _item(key="application", label="Application", light="RED", status="INCOMPLETE", missing=missing)
    if application.status in {"draft"}:
        return _item(key="application", label="Application", light="YELLOW", status="DRAFT")
    if application.status in {"submitted", "under_review", "documents_pending", "background_review"}:
        return _item(key="application", label="Application", light="YELLOW", status=application.status.upper())
    return _item(key="application", label="Application", light="GREEN", status=str(application.status or "COMPLETE").upper())


def _license_item(
    application: PlatformDriverOnboardingApplication | None,
    case: ApprovalCase | None,
    documents: list[PlatformDriverOnboardingDocument],
) -> dict[str, Any]:
    missing = []
    if application is None or not application.drivers_license_number:
        missing.append("license number")
    if application is None or not application.license_issuing_state:
        missing.append("issuing state")
    if application is None or not application.license_expiration_date:
        missing.append("expiration date")
    front = _latest_doc(documents, "drivers_license_front")
    back = _latest_doc(documents, "drivers_license_back")
    if front is None:
        missing.append("license front upload")
    if back is None:
        missing.append("license back upload")
    expiration = application.license_expiration_date if application else None
    req = _req(case, "drivers_license")
    req_light, req_status = _requirement_light(req, fallback_red=False)
    if _expired(expiration):
        return _item(key="driver_license", label="Driver License", light="RED", status="EXPIRED", expiration=expiration, missing=missing)
    if front and front.review_status == "rejected":
        return _item(key="driver_license", label="Driver License", light="RED", status="REJECTED", notes=front.review_reason, expiration=expiration)
    if missing:
        return _item(key="driver_license", label="Driver License", light="RED", status="NOT_STARTED" if not application or not application.drivers_license_number else "MISSING", expiration=expiration, missing=missing)
    case_status = str(getattr(case, "license_verification_status", "") or "").upper()
    if case_status == "VERIFIED" or req_status in {"COMPLETE", "VERIFIED"}:
        return _item(key="driver_license", label="Driver License", light="GREEN", status="VERIFIED", expiration=expiration)
    if case_status == "REJECTED":
        return _item(key="driver_license", label="Driver License", light="RED", status="REJECTED", expiration=expiration)
    if front.review_status == "accepted" and back.review_status == "accepted":
        return _item(key="driver_license", label="Driver License", light="GREEN", status="VERIFIED", expiration=expiration)
    return _item(key="driver_license", label="Driver License", light="YELLOW", status="PENDING", expiration=expiration)


def _registration_item(
    application: PlatformDriverOnboardingApplication | None,
    case: ApprovalCase | None,
    documents: list[PlatformDriverOnboardingDocument],
) -> dict[str, Any]:
    missing = []
    if application is None or not application.vehicle_year:
        missing.append("year")
    if application is None or not application.vehicle_make:
        missing.append("make")
    if application is None or not application.vehicle_model:
        missing.append("model")
    if application is None or not application.vehicle_license_plate:
        missing.append("plate number")
    doc = _latest_doc(documents, "vehicle_registration")
    if doc is None:
        missing.append("registration document")
    expiration = getattr(application, "vehicle_registration_expiration", None) if application else None
    expiration = expiration or getattr(case, "vehicle_registration_expiration", None)
    if doc and doc.expires_at:
        expiration = expiration or doc.expires_at
    light, status, extra = _doc_light(doc)
    if _expired(expiration):
        return _item(key="vehicle_registration", label="Vehicle Registration", light="RED", status="EXPIRED", expiration=expiration, missing=missing)
    if missing:
        return _item(key="vehicle_registration", label="Vehicle Registration", light="RED", status="MISSING", expiration=expiration, missing=missing)
    if light == "GREEN":
        return _item(key="vehicle_registration", label="Vehicle Registration", light="GREEN", status="VERIFIED", expiration=expiration)
    return _item(key="vehicle_registration", label="Vehicle Registration", light=light, status=status, expiration=expiration, missing=extra)


def _insurance_item(
    application: PlatformDriverOnboardingApplication | None,
    case: ApprovalCase | None,
    documents: list[PlatformDriverOnboardingDocument],
) -> dict[str, Any]:
    missing = []
    if application is None or not getattr(application, "insurance_carrier", None):
        missing.append("insurance company")
    doc = _latest_doc(documents, "proof_of_auto_insurance")
    if doc is None:
        missing.append("proof of insurance upload")
    expiration = getattr(application, "insurance_expiration_date", None) if application else None
    expiration = expiration or getattr(case, "insurance_expiration", None)
    review = str(getattr(application, "insurance_review_status", "") or "").upper()
    if _expired(expiration):
        return _item(
            key="insurance",
            label="Insurance",
            light="RED",
            status="EXPIRED",
            expiration=expiration,
            notes="Personal auto insurance is collected for review only; it does not satisfy commercial/TNC coverage.",
            missing=missing,
        )
    if review == "REJECTED":
        return _item(key="insurance", label="Insurance", light="RED", status="REJECTED", expiration=expiration, notes=getattr(application, "insurance_review_notes", None))
    if missing:
        return _item(
            key="insurance",
            label="Insurance",
            light="RED",
            status="MISSING",
            expiration=expiration,
            notes="Collected for review only until company insurance requirements are finalized.",
            missing=missing,
        )
    if review in {"ACCEPTED", "VERIFIED"} or (doc and doc.review_status == "accepted"):
        return _item(
            key="insurance",
            label="Insurance",
            light="GREEN",
            status="VERIFIED",
            expiration=expiration,
            notes="Admin reviewed uploaded personal auto insurance. Not a commercial/TNC determination.",
        )
    return _item(
        key="insurance",
        label="Insurance",
        light="YELLOW",
        status="PENDING",
        expiration=expiration,
        notes="Awaiting admin review of uploaded insurance evidence.",
    )


def _background_item(
    application: PlatformDriverOnboardingApplication | None,
    case: ApprovalCase | None,
    documents: list[PlatformDriverOnboardingDocument],
) -> dict[str, Any]:
    consented = bool(application and (application.declaration_background_authorization or getattr(application, "background_consent_at", None)))
    consent_doc = _latest_doc(documents, "background_check_consent")
    req = _req(case, "background_study")
    case_status = str(getattr(case, "background_study_status", "") or "").upper()
    if case_status in {"CLEAR", "CLEARED", "COMPLETE", "VERIFIED"}:
        # Only if a human/external actor recorded it on the case — never auto-set here.
        return _item(key="background_check", label="Background Check", light="GREEN", status="CLEAR", notes="Recorded by admin/vendor — not fabricated.")
    if case_status in {"FAILED", "DISQUALIFIED"}:
        return _item(key="background_check", label="Background Check", light="RED", status="FAILED")
    if case_status in {"REVIEW_REQUIRED", "MANUAL_REVIEW"}:
        return _item(key="background_check", label="Background Check", light="YELLOW", status="REVIEW_REQUIRED")
    if req and str(req.status or "").upper() in {"FAILED", "REJECTED"}:
        return _item(key="background_check", label="Background Check", light="RED", status="FAILED", notes=req.notes)
    if not consented and consent_doc is None:
        return _item(key="background_check", label="Background Check", light="RED", status="CONSENT_REQUIRED", missing=["background-check consent"])
    if case_status in {"PENDING", "PENDING_EXTERNAL"} or (consented or consent_doc):
        return _item(
            key="background_check",
            label="Background Check",
            light="YELLOW",
            status="PENDING",
            notes="Consent captured. Vendor result is not connected; admin must record a real result later.",
        )
    return _item(key="background_check", label="Background Check", light="RED", status="NOT_STARTED")


def _fingerprint_item(case: ApprovalCase | None) -> dict[str, Any]:
    required = _fingerprint_required(case)
    status = str(getattr(case, "fingerprint_status", "") or "NOT_REQUIRED").upper()
    if not required:
        return _item(
            key="fingerprint",
            label="Fingerprint",
            light="GREEN",
            status="NOT_REQUIRED",
            required=False,
            notes="Not marked legally required in current Amicor BASE configuration.",
        )
    if status == "VERIFIED":
        return _item(key="fingerprint", label="Fingerprint", light="GREEN", status="VERIFIED")
    if status == "REJECTED":
        return _item(key="fingerprint", label="Fingerprint", light="RED", status="REJECTED", notes=getattr(case, "fingerprint_notes", None))
    if status in {"SCHEDULED", "PENDING_VERIFICATION"}:
        return _item(key="fingerprint", label="Fingerprint", light="YELLOW", status=status)
    return _item(key="fingerprint", label="Fingerprint", light="RED", status=status or "NOT_STARTED", required=True)


def _training_item(case: ApprovalCase | None) -> dict[str, Any]:
    modules: list[ApprovalTrainingModule] = list(getattr(case, "training_modules", None) or [])
    required = [m for m in modules if bool(getattr(m, "is_required", False))]
    if not required:
        return _item(
            key="training",
            label="Training",
            light="GREEN",
            status="NOT_REQUIRED",
            required=False,
            notes="No required training modules configured. Admins may assign modules; none are legally invented.",
        )
    incomplete = []
    expired = []
    for module in required:
        status = str(module.status or "").lower()
        if module.expires_at and _expired(module.expires_at):
            expired.append(module.label or module.module_key)
        elif status not in {"completed", "complete"}:
            incomplete.append(module.label or module.module_key)
    if expired:
        return _item(key="training", label="Training", light="RED", status="EXPIRED", missing=expired)
    if incomplete:
        return _item(key="training", label="Training", light="YELLOW", status="IN_PROGRESS", missing=incomplete)
    return _item(key="training", label="Training", light="GREEN", status="COMPLETED")


def _agreements_item(
    application: PlatformDriverOnboardingApplication | None,
    case: ApprovalCase | None,
    documents: list[PlatformDriverOnboardingDocument],
) -> dict[str, Any]:
    doc = _latest_doc(documents, "independent_contractor_agreement")
    agreement_status = str(getattr(application, "agreement_status", "") or getattr(case, "contractor_agreement_status", "") or "").upper()
    if agreement_status in {"ACCEPTED", "SIGNED"} or (doc and doc.review_status == "accepted"):
        return _item(key="agreements", label="Agreements", light="GREEN", status="SIGNED")
    if doc is None and not (application and application.electronic_signature):
        return _item(key="agreements", label="Agreements", light="RED", status="NOT_STARTED", missing=["contractor agreement or acknowledgment"])
    if doc and doc.review_status == "rejected":
        return _item(key="agreements", label="Agreements", light="RED", status="REJECTED", notes=doc.review_reason)
    return _item(key="agreements", label="Agreements", light="YELLOW", status=agreement_status or "PENDING")


def _vehicle_approval_item(case: ApprovalCase | None) -> dict[str, Any]:
    vehicles = list(getattr(case, "vehicles", None) or [])
    if not vehicles:
        status = str(getattr(case, "vehicle_registration_status", "") or "").upper()
        if status in {"APPROVED", "VERIFIED", "COMPLETE"}:
            return _item(key="vehicle_approval", label="Vehicle Approval", light="GREEN", status="APPROVED")
        return _item(key="vehicle_approval", label="Vehicle Approval", light="YELLOW", status="PENDING", notes="Vehicle details collected; admin has not recorded vehicle approval.")
    lights = []
    for vehicle in vehicles:
        eligibility = str(getattr(vehicle, "eligibility_status", "") or "").upper()
        vstatus = str(getattr(vehicle, "vehicle_status", "") or "").upper()
        if eligibility in {"BLOCKED", "EXPIRED"} or vstatus in {"RESTRICTED", "EXPIRED", "SUSPENDED", "REJECTED"}:
            lights.append("RED")
        elif eligibility in {"ELIGIBLE", "REVIEWED"} or vstatus in {"APPROVED", "ACTIVE", "REVIEWED"}:
            lights.append("GREEN")
        else:
            lights.append("YELLOW")
    if "RED" in lights:
        return _item(key="vehicle_approval", label="Vehicle Approval", light="RED", status="REJECTED")
    if lights and all(item == "GREEN" for item in lights):
        return _item(key="vehicle_approval", label="Vehicle Approval", light="GREEN", status="APPROVED")
    return _item(key="vehicle_approval", label="Vehicle Approval", light="YELLOW", status="PENDING")


def _final_approval_item(
    application: PlatformDriverOnboardingApplication | None,
    case: ApprovalCase | None,
) -> dict[str, Any]:
    if application and application.status == "suspended":
        return _item(key="final_admin_approval", label="Final Admin Approval", light="RED", status="SUSPENDED", notes=application.suspension_reason)
    if case and str(case.workflow_status or "").upper() == "SUSPENDED":
        return _item(key="final_admin_approval", label="Final Admin Approval", light="RED", status="SUSPENDED", notes=case.suspension_restriction_reason)
    owner = str(getattr(case, "owner_approval_status", "") or "").upper() if case else ""
    if owner == "APPROVED" and getattr(case, "owner_approval_timestamp", None):
        return _item(key="final_admin_approval", label="Final Admin Approval", light="GREEN", status="APPROVED")
    if application and application.status == "approved" and application.approved_at:
        return _item(key="final_admin_approval", label="Final Admin Approval", light="GREEN", status="APPROVED")
    if owner == "REJECTED" or (application and application.status == "rejected"):
        return _item(key="final_admin_approval", label="Final Admin Approval", light="RED", status="REJECTED")
    if case or (application and application.status not in {None, "draft"}):
        return _item(key="final_admin_approval", label="Final Admin Approval", light="YELLOW", status="PENDING")
    return _item(key="final_admin_approval", label="Final Admin Approval", light="RED", status="NOT_STARTED")


def _overall(items: list[dict[str, Any]], application: PlatformDriverOnboardingApplication | None, case: ApprovalCase | None) -> str:
    if application and application.status == "suspended":
        return "SUSPENDED"
    if case and str(case.workflow_status or "").upper() == "SUSPENDED":
        return "SUSPENDED"
    required = [item for item in items if item.get("required")]
    if any(item["status"] == "EXPIRED" or item["light"] == "RED" and item["status"] == "EXPIRED" for item in required):
        if any(item["status"] == "EXPIRED" for item in required):
            # Expired required item dominates unless nothing started.
            if any(item["status"] == "EXPIRED" for item in required):
                return "EXPIRED"
    if any(item["status"] == "EXPIRED" for item in required):
        return "EXPIRED"
    if all(item["light"] == "RED" and item["status"] in {"NOT_STARTED", "MISSING", "INCOMPLETE", "CONSENT_REQUIRED"} for item in required):
        if application is None:
            return "NOT_STARTED"
    greens = [item for item in required if item["light"] == "GREEN"]
    reds = [item for item in required if item["light"] == "RED"]
    yellows = [item for item in required if item["light"] == "YELLOW"]
    final = next((item for item in items if item["key"] == "final_admin_approval"), None)
    if final and final["status"] == "APPROVED" and not reds and not yellows:
        return "APPROVED"
    if not application and case is None:
        return "NOT_STARTED"
    # Draft with no required progress yet is NOT_STARTED. Once any required item
    # is pending/missing/complete, the file is IN_PROGRESS (or NEEDS_REVIEW).
    if application and application.status == "draft" and not greens and not yellows and not reds:
        return "NOT_STARTED"
    if yellows or (final and final["status"] == "PENDING" and not reds):
        return "NEEDS_REVIEW" if greens and not reds else "IN_PROGRESS"
    if reds:
        return "IN_PROGRESS"
    return "IN_PROGRESS"


def build_compliance_summary(
    db: Session,
    *,
    application: PlatformDriverOnboardingApplication | None = None,
    case: ApprovalCase | None = None,
) -> dict[str, Any]:
    documents: list[PlatformDriverOnboardingDocument] = []
    if application is not None:
        documents = list(application.documents or [])
        if not documents:
            documents = (
                db.query(PlatformDriverOnboardingDocument)
                .filter(PlatformDriverOnboardingDocument.application_id == application.id)
                .all()
            )
    items = [
        _application_item(application),
        _license_item(application, case, documents),
        _registration_item(application, case, documents),
        _insurance_item(application, case, documents),
        _background_item(application, case, documents),
        _fingerprint_item(case),
        _training_item(case),
        _agreements_item(application, case, documents),
        _vehicle_approval_item(case),
        _final_approval_item(application, case),
    ]
    overall = _overall(items, application, case)
    required = [item for item in items if item.get("required")]
    complete = [item for item in required if item["light"] == "GREEN"]
    pending = [item for item in required if item["light"] == "YELLOW"]
    missing = [item for item in required if item["light"] == "RED"]
    # GREEN = full credit; YELLOW pending/review = half credit so draft progress is visible.
    progress = (
        int(round(((len(complete) + 0.5 * len(pending)) / len(required)) * 100))
        if required
        else 0
    )
    next_action = None
    if missing:
        next_action = f"Complete {missing[0]['label']}: {', '.join(missing[0]['missing']) or missing[0]['status']}"
    elif pending:
        next_action = f"Waiting on review: {pending[0]['label']}"
    elif overall != "APPROVED":
        next_action = "Final admin approval is still required."
    else:
        next_action = "All configured required items are complete."
    blocked_reasons = [
        f"{item['label']}: {item['status']}"
        + (f" ({', '.join(item['missing'])})" if item.get("missing") else "")
        for item in missing
    ]
    if overall != "APPROVED":
        if not any("Final Admin Approval" in row for row in blocked_reasons) and (not items[-1]["status"] == "APPROVED"):
            blocked_reasons.append("Final admin approval is not APPROVED")
    return {
        "overall_status": overall,
        "progress_percent": progress,
        "next_required_action": next_action,
        "items": items,
        "completed_items": [item["key"] for item in complete],
        "pending_review_items": [item["key"] for item in pending],
        "missing_or_rejected_items": [item["key"] for item in missing],
        "blocked_from_online_reasons": blocked_reasons if overall != "APPROVED" else [],
        "online_eligible": overall == "APPROVED" and not missing and not pending,
        "driver_badge": getattr(case, "display_badge", None) if case else None,
        "application_id": application.id if application else None,
        "case_id": case.id if case else None,
        "health_isf_driver_id": (
            getattr(case, "health_isf_driver_id", None)
            or getattr(application, "activated_driver_id", None)
        ),
        "internal_driver_number": getattr(application, "internal_driver_number", None)
        or getattr(case, "display_badge", None),
        "fingerprint_required": _fingerprint_required(case),
        "insurance_disclaimer": (
            "Uploaded personal auto insurance is collected for review only and does not "
            "automatically satisfy AMICORE commercial/TNC requirements."
        ),
    }


def resolve_case_and_application(
    db: Session,
    *,
    case: ApprovalCase | None = None,
    application: PlatformDriverOnboardingApplication | None = None,
) -> tuple[ApprovalCase | None, PlatformDriverOnboardingApplication | None]:
    if case is None and application is not None:
        case = (
            db.query(ApprovalCase)
            .filter(ApprovalCase.platform_ops_application_id == application.id)
            .order_by(ApprovalCase.updated_at.desc())
            .first()
        )
    if application is None and case is not None and case.platform_ops_application_id:
        application = (
            db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.id == case.platform_ops_application_id)
            .first()
        )
    return case, application
