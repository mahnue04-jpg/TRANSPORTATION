"""AI application review — validates, scores readiness, opens next actions.

Never fabricates external verification results.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.audit import record_audit
from app.modules.approval_engine.models import (
    ApprovalCase,
    ApprovalExternalTask,
    ApprovalRequirement,
    ApprovalTrainingModule,
    ApprovalVehicleRecord,
)
from app.modules.approval_engine.requirements import (
    build_requirement_plan,
    fingerprint_required_for_tiers,
    normalize_tiers,
    training_modules_for_tiers,
)
from app.modules.approval_engine.external_verification import normalize_external_status
from app.modules.approval_engine.statuses import assert_transition_allowed, normalize_status
from app.modules.platform_ops.masking import mask_license_number, mask_phone
from app.modules.platform_ops.models import (
    PlatformDriverOnboardingApplication,
    PlatformDriverOnboardingDocument,
)


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return []


def _set_json_list(values: list[str] | None) -> str:
    return json.dumps(list(values or []))


def _latest_doc(docs: list[PlatformDriverOnboardingDocument], category: str) -> PlatformDriverOnboardingDocument | None:
    matches = [doc for doc in docs if doc.category == category]
    if not matches:
        return None
    return sorted(matches, key=lambda doc: str(doc.created_at or ""), reverse=True)[0]


def _present(docs: list[PlatformDriverOnboardingDocument], category: str) -> PlatformDriverOnboardingDocument | None:
    """Return the latest uploaded evidence on file if it is still reviewable.

    Applicant uploads start as review_status=pending. That is evidence present
    (awaiting human/system accept), not verified — and must not score as MISSING.
    A later reject/return replaces an older accepted copy.
    """
    latest = _latest_doc(docs, category)
    if latest is not None and latest.review_status in {"pending", "accepted"}:
        return latest
    return None


def _rejected_latest(docs: list[PlatformDriverOnboardingDocument], category: str) -> PlatformDriverOnboardingDocument | None:
    latest = _latest_doc(docs, category)
    if latest is not None and latest.review_status in {"rejected", "correction_requested"}:
        return latest
    return None


def _accepted(docs: list[PlatformDriverOnboardingDocument], category: str) -> PlatformDriverOnboardingDocument | None:
    """Backward-compatible alias — evidence present includes pending uploads."""
    return _present(docs, category)


def _status_only_ok(docs: list[PlatformDriverOnboardingDocument], category: str) -> bool:
    for doc in docs:
        if doc.category == category and (
            doc.review_status == "accepted"
            or doc.status_only_value in {"provided", "verified", "signed"}
        ):
            return True
    return False


def _doc_unexpired(doc: PlatformDriverOnboardingDocument | None) -> bool:
    if doc is None:
        return False
    if doc.expires_at is None:
        return True
    return doc.expires_at >= date.today()


def _traffic(ok: bool, *, pending_external: bool = False, expired: bool = False) -> str:
    if ok:
        return "green"
    if expired or pending_external:
        return "yellow" if pending_external and not expired else "red"
    return "red"


def evaluate_requirement_state(
    *,
    key: str,
    timing: str,
    application: PlatformDriverOnboardingApplication | None,
    documents: list[PlatformDriverOnboardingDocument],
    case: ApprovalCase,
    tiers: list[str],
) -> dict[str, Any]:
    """Return status/traffic for a requirement without inventing external completions."""
    if timing == "not_required":
        return {
            "status": "NOT_REQUIRED",
            "traffic_light": "green",
            "is_blocking": False,
            "verification_source": "tier_rule",
        }
    if timing == "future_requirement":
        return {
            "status": "FUTURE",
            "traffic_light": "yellow",
            "is_blocking": False,
            "verification_source": "tier_rule",
        }

    today = date.today()
    app = application

    if key == "identity_complete":
        ok = bool(
            app
            and app.legal_first_name
            and app.legal_last_name
            and app.email
            and app.mobile_phone
            and app.home_address
            and app.city
            and app.state
            and app.zip_code
        )
        return {"status": "COMPLETE" if ok else "MISSING", "traffic_light": _traffic(ok), "is_blocking": True}

    if key == "age_verified":
        ok = bool(app and app.date_of_birth)
        return {
            "status": "COMPLETE" if ok else "MISSING",
            "traffic_light": _traffic(ok),
            "is_blocking": True,
            "verification_source": "application_fields",
        }

    if key == "drivers_license":
        rejected = _rejected_latest(documents, "drivers_license_front")
        if rejected is not None:
            return {
                "status": "REJECTED" if rejected.review_status == "rejected" else "CORRECTION_REQUESTED",
                "traffic_light": "red",
                "is_blocking": True,
                "evidence_ref": rejected.id,
                "notes": rejected.review_reason or "License document rejected or returned",
            }
        field_ok = bool(
            app
            and app.drivers_license_number
            and app.license_issuing_state
            and app.license_expiration_date
            and app.license_expiration_date >= today
        )
        front = _present(documents, "drivers_license_front")
        expired = bool(app and app.license_expiration_date and app.license_expiration_date < today)
        # Field present is not the same as verified — verification stays PENDING until human/system verifies.
        if field_ok and front:
            status = case.license_verification_status if case.license_verification_status in {"VERIFIED", "COMPLETE"} else "PENDING_VERIFICATION"
            ok = status in {"VERIFIED", "COMPLETE"}
            return {
                "status": "VERIFIED" if ok else "PENDING_EXTERNAL",
                "traffic_light": "green" if ok else "yellow",
                "is_blocking": True,
                "expiration_date": app.license_expiration_date if app else None,
                "evidence_ref": front.id if front else None,
                "external_status": "VERIFIED" if ok else "PENDING_EXTERNAL",
                "external_task": None if ok else "drivers_license_verification",
            }
        missing_bits = []
        if not (app and app.drivers_license_number):
            missing_bits.append("number")
        if not (app and app.license_issuing_state):
            missing_bits.append("state")
        if not (app and app.license_expiration_date):
            missing_bits.append("expiration")
        if not front:
            missing_bits.append("front_image")
        return {
            "status": "EXPIRED" if expired else "MISSING",
            "traffic_light": "red",
            "is_blocking": True,
            "expiration_date": app.license_expiration_date if app else None,
            "external_status": "EXPIRED" if expired else "ACTION_REQUIRED",
            "notes": ("Missing: " + ", ".join(missing_bits)) if missing_bits else None,
        }

    if key == "mvr":
        consent = _accepted(documents, "motor_vehicle_record_consent") or (
            app and app.declaration_mvr_authorization
        )
        if case.mvr_status in {"COMPLETE", "VERIFIED", "CLEAR", "CLEARED"}:
            return {
                "status": "VERIFIED",
                "traffic_light": "green",
                "is_blocking": True,
                "verification_source": "external_mvr",
                "external_status": "VERIFIED",
            }
        if consent:
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "verification_source": "external_mvr",
                "external_task": "mvr_request",
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING_CONSENT",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
        }

    if key == "vehicle_registration":
        rejected = _rejected_latest(documents, "vehicle_registration")
        if rejected is not None:
            return {
                "status": "REJECTED" if rejected.review_status == "rejected" else "CORRECTION_REQUESTED",
                "traffic_light": "red",
                "is_blocking": True,
                "evidence_ref": rejected.id,
                "notes": rejected.review_reason or "Registration document rejected or returned",
            }
        doc = _accepted(documents, "vehicle_registration")
        ok = _doc_unexpired(doc)
        if doc and not ok:
            return {
                "status": "EXPIRED",
                "traffic_light": "red",
                "is_blocking": True,
                "expiration_date": doc.expires_at,
                "evidence_ref": doc.id,
                "external_status": "EXPIRED",
            }
        if doc:
            if case.vehicle_registration_status in {"VERIFIED", "COMPLETE"}:
                return {
                    "status": "VERIFIED",
                    "traffic_light": "green",
                    "is_blocking": True,
                    "evidence_ref": doc.id,
                    "expiration_date": doc.expires_at,
                    "external_status": "VERIFIED",
                }
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_task": "vehicle_registration_verification",
                "evidence_ref": doc.id,
                "expiration_date": doc.expires_at,
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
        }

    if key == "vehicle_insurance":
        rejected = _rejected_latest(documents, "proof_of_auto_insurance")
        if rejected is not None:
            return {
                "status": "REJECTED" if rejected.review_status == "rejected" else "CORRECTION_REQUESTED",
                "traffic_light": "red",
                "is_blocking": True,
                "evidence_ref": rejected.id,
                "notes": rejected.review_reason or "Insurance document rejected or returned",
            }
        doc = _accepted(documents, "proof_of_auto_insurance")
        metadata_exp = getattr(app, "insurance_expiration_date", None) if app else None
        case_exp = case.insurance_expiration
        effective_exp = metadata_exp or case_exp or (doc.expires_at if doc else None)
        if effective_exp and effective_exp < today:
            return {
                "status": "EXPIRED",
                "traffic_light": "red",
                "is_blocking": True,
                "expiration_date": effective_exp,
                "evidence_ref": doc.id if doc else None,
                "external_status": "EXPIRED",
            }
        ok = _doc_unexpired(doc)
        if doc and not ok:
            return {
                "status": "EXPIRED",
                "traffic_light": "red",
                "is_blocking": True,
                "expiration_date": doc.expires_at,
                "evidence_ref": doc.id,
                "external_status": "EXPIRED",
            }
        if doc:
            # Accepted upload still needs verification tracking — do not invent insurer confirmation.
            if case.insurance_status in {"VERIFIED", "COMPLETE"}:
                return {
                    "status": "VERIFIED",
                    "traffic_light": "green",
                    "is_blocking": True,
                    "evidence_ref": doc.id,
                    "expiration_date": doc.expires_at,
                    "external_status": "VERIFIED",
                }
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_task": "insurance_verification",
                "evidence_ref": doc.id,
                "expiration_date": doc.expires_at,
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
        }

    if key == "vehicle_inspection":
        rejected = _rejected_latest(documents, "vehicle_inspection_record")
        if rejected is not None:
            return {
                "status": "REJECTED" if rejected.review_status == "rejected" else "CORRECTION_REQUESTED",
                "traffic_light": "red",
                "is_blocking": True,
                "evidence_ref": rejected.id,
                "notes": rejected.review_reason or "Inspection document rejected or returned",
            }
        doc = _accepted(documents, "vehicle_inspection_record")
        ok = _doc_unexpired(doc)
        if doc and not ok:
            return {
                "status": "EXPIRED",
                "traffic_light": "red",
                "is_blocking": True,
                "expiration_date": doc.expires_at,
                "evidence_ref": doc.id,
                "external_status": "EXPIRED",
            }
        if doc:
            if case.inspection_status in {"VERIFIED", "COMPLETE"}:
                return {
                    "status": "VERIFIED",
                    "traffic_light": "green",
                    "is_blocking": True,
                    "evidence_ref": doc.id,
                    "expiration_date": doc.expires_at,
                    "external_status": "VERIFIED",
                }
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_task": "vehicle_inspection_verification",
                "evidence_ref": doc.id,
                "expiration_date": doc.expires_at,
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
            "external_task": "vehicle_inspection",
        }

    if key == "contractor_agreement":
        rejected = _rejected_latest(documents, "independent_contractor_agreement")
        if rejected is not None:
            return {
                "status": "REJECTED" if rejected.review_status == "rejected" else "CORRECTION_REQUESTED",
                "traffic_light": "red",
                "is_blocking": True,
                "evidence_ref": rejected.id,
                "notes": rejected.review_reason or "Agreement document rejected or returned",
            }
        doc = _accepted(documents, "independent_contractor_agreement")
        if case.contractor_agreement_status in {"COMPLETE", "SIGNED", "VERIFIED"}:
            return {
                "status": "VERIFIED",
                "traffic_light": "green",
                "is_blocking": True,
                "evidence_ref": doc.id if doc else None,
                "external_status": "VERIFIED",
            }
        if doc:
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "evidence_ref": doc.id,
                "external_task": "contractor_agreement_esign",
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
        }

    if key == "w9":
        provided = _status_only_ok(documents, "w9_status")
        if case.w9_status in {"COMPLETE", "VERIFIED", "SIGNED"}:
            return {
                "status": "VERIFIED",
                "traffic_light": "green",
                "is_blocking": True,
                "external_status": "VERIFIED",
            }
        if provided:
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_task": "w9_secure_status",
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
        }

    if key == "payout_setup":
        ok = case.payout_setup_status in {"COMPLETE", "VERIFIED", "READY"}
        return {
            "status": "VERIFIED" if ok else "MISSING",
            "traffic_light": _traffic(ok),
            "is_blocking": True,
            "external_status": "VERIFIED" if ok else "ACTION_REQUIRED",
            "external_task": None if ok else "payout_setup",
        }

    if key == "base_training":
        modules = [
            m
            for m in (case.training_modules or [])
            if m.module_key not in {"sts_service_rules", "behind_wheel_eval"}
        ]
        if not modules:
            return {
                "status": "NOT_STARTED",
                "traffic_light": "red",
                "is_blocking": True,
                "external_status": "NOT_STARTED",
            }
        all_done = all(m.status == "completed" for m in modules)
        if all_done:
            # In-app completion is not enough — adapter confirmation required for BASE readiness.
            prior_external = next(
                (
                    req
                    for req in (case.requirements or [])
                    if req.requirement_key == "base_training"
                    and req.external_status == "VERIFIED"
                    and (req.evidence_ref or req.evidence_source or req.provider_reference_id)
                ),
                None,
            )
            if prior_external:
                return {
                    "status": "VERIFIED",
                    "traffic_light": "green",
                    "is_blocking": True,
                    "external_status": "VERIFIED",
                }
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_task": "base_training_completion",
                "external_status": "PENDING_EXTERNAL",
                "notes": "All assigned BASE modules marked completed — awaiting external/manual confirmation",
            }
        if any(m.status in {"completed", "in_progress"} for m in modules):
            return {
                "status": "IN_PROGRESS",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_status": "SUBMITTED",
            }
        return {
            "status": "NOT_STARTED",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "NOT_STARTED",
        }

    if key == "background_study":
        if not any(t in {"STS_ELIGIBLE", "FUTURE_MHCP_NEMT"} for t in tiers):
            return {
                "status": "CONDITIONAL_NOT_APPLICABLE",
                "traffic_light": "green",
                "is_blocking": False,
                "notes": (
                    "Not currently required for the requested service tier. "
                    "Remains available when STS/MHCP or authoritative Minnesota rules apply."
                ),
            }
        consent = _accepted(documents, "background_check_consent") or (
            app and app.declaration_background_authorization
        )
        if case.background_study_status in {"COMPLETE", "CLEARED", "VERIFIED"}:
            return {"status": "VERIFIED", "traffic_light": "green", "is_blocking": True, "external_status": "VERIFIED"}
        if consent:
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": True,
                "external_task": "background_study_consent",
                "external_status": "PENDING_EXTERNAL",
            }
        return {
            "status": "MISSING_CONSENT",
            "traffic_light": "red",
            "is_blocking": True,
            "external_status": "ACTION_REQUIRED",
        }

    if key == "fingerprint":
        if not fingerprint_required_for_tiers(tiers):
            return {
                "status": "CONDITIONAL_NOT_APPLICABLE",
                "traffic_light": "green",
                "is_blocking": False,
                "notes": (
                    "Fingerprinting is not universally required. "
                    "Applicable when background-study / STS / MHCP rules demand it."
                ),
            }
        if case.fingerprint_status == "COMPLETE":
            return {"status": "VERIFIED", "traffic_light": "green", "is_blocking": True, "external_status": "VERIFIED"}
        if case.fingerprint_status == "FAILED":
            return {"status": "FAILED", "traffic_light": "red", "is_blocking": True, "external_status": "FAILED"}
        return {
            "status": "PENDING_EXTERNAL",
            "traffic_light": "yellow",
            "is_blocking": True,
            "external_task": "fingerprint_appointment",
            "external_status": "PENDING_EXTERNAL",
        }

    if key == "sts_training":
        if not any(t in {"STS_ELIGIBLE", "FUTURE_MHCP_NEMT"} for t in tiers):
            return {
                "status": "CONDITIONAL_NOT_APPLICABLE",
                "traffic_light": "green",
                "is_blocking": False,
                "notes": "STS training applies only when STS/MHCP service tiers are requested.",
            }
        modules = [m for m in (case.training_modules or []) if m.module_key in {"sts_service_rules", "behind_wheel_eval"}]
        ok = bool(modules) and all(m.status == "completed" for m in modules)
        return {
            "status": "VERIFIED" if ok else ("IN_PROGRESS" if modules else "NOT_STARTED"),
            "traffic_light": "green" if ok else "red",
            "is_blocking": True,
        }

    if key == "mhcp_credentialing":
        if "FUTURE_MHCP_NEMT" not in tiers:
            return {
                "status": "CONDITIONAL_NOT_APPLICABLE",
                "traffic_light": "green",
                "is_blocking": False,
                "notes": "MHCP/NEMT credentialing applies only when that service tier is requested.",
            }
        return {
            "status": "FUTURE",
            "traffic_light": "yellow",
            "is_blocking": False,
            "external_task": "government_credentialing",
            "external_status": "NOT_STARTED",
        }

    if key == "medical_qualification":
        if case.medical_qualification_status in {"COMPLETE", "CLEARED", "VERIFIED"}:
            return {
                "status": "VERIFIED",
                "traffic_light": "green",
                "is_blocking": False,
                "external_status": "VERIFIED",
            }
        if case.medical_qualification_status in {"REQUIRED", "PENDING"}:
            return {
                "status": "PENDING_EXTERNAL",
                "traffic_light": "yellow",
                "is_blocking": False,
                "external_task": "medical_physical_qualification",
                "external_status": "PENDING_EXTERNAL",
                "notes": "Only required when authoritative rules establish applicability",
            }
        return {
            "status": "NOT_REQUIRED",
            "traffic_light": "green",
            "is_blocking": False,
            "external_status": "NOT_STARTED",
            "notes": "Not applied to BASE unless authoritative requirements establish it",
        }

    return {"status": "UNKNOWN", "traffic_light": "red", "is_blocking": True}


def _ensure_training(db: Session, case: ApprovalCase, tiers: list[str]) -> None:
    existing = {m.module_key: m for m in (case.training_modules or [])}
    for key, label in training_modules_for_tiers(tiers):
        if key in existing:
            continue
        module = ApprovalTrainingModule(
            id=uuid4(),
            case_id=case.id,
            organization_id=case.organization_id,
            module_key=key,
            label=label,
            status="assigned",
            assigned_at=now(),
            created_at=now(),
            updated_at=now(),
        )
        db.add(module)
    db.flush()


def _sync_vehicle_from_application(
    db: Session,
    case: ApprovalCase,
    application: PlatformDriverOnboardingApplication | None,
) -> None:
    if application is None:
        return
    year = getattr(application, "vehicle_year", None)
    make = getattr(application, "vehicle_make", None)
    model = getattr(application, "vehicle_model", None)
    plate = getattr(application, "vehicle_license_plate", None)
    vin = getattr(application, "vehicle_vin", None)
    if not any([year, make, model, plate, vin]):
        return
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
    existing.year = year or existing.year
    existing.make = make or existing.make
    existing.model = model or existing.model
    if plate and not str(plate).upper().startswith("ONBD-"):
        existing.license_plate = str(plate).strip().upper()
    # Store plate in vin_ref only when VIN absent — plate is not a secret; keep VIN ref masked-style.
    if vin:
        existing.vin_ref = f"vin-ref:{vin[-6:]}" if len(str(vin)) >= 6 else "vin-ref:provided"
    existing.dispatch_activated = False
    existing.updated_at = now()
    db.flush()


def _ensure_external_task(
    db: Session,
    case: ApprovalCase,
    *,
    task_type: str,
    title: str,
    instructions: str,
) -> None:
    open_tasks = [
        t
        for t in (case.external_tasks or [])
        if t.task_type == task_type and t.status in {"OPEN", "IN_PROGRESS"}
    ]
    if open_tasks:
        return
    db.add(
        ApprovalExternalTask(
            id=uuid4(),
            case_id=case.id,
            organization_id=case.organization_id,
            task_type=task_type,
            title=title,
            instructions=instructions,
            status="OPEN",
            created_at=now(),
            updated_at=now(),
        )
    )


def _sync_requirements(
    db: Session,
    case: ApprovalCase,
    plan: list[dict[str, Any]],
    evaluations: dict[str, dict[str, Any]],
) -> None:
    existing = {r.requirement_key: r for r in (case.requirements or [])}
    for item in plan:
        key = item["requirement_key"]
        evaluation = evaluations.get(key) or {}
        row = existing.get(key)
        if row is None:
            row = ApprovalRequirement(
                id=uuid4(),
                case_id=case.id,
                organization_id=case.organization_id,
                requirement_key=key,
                label=item.get("label") or key,
                service_tier=item.get("service_tier") or "BASE_PRIVATE_AMBULATORY",
                created_at=now(),
            )
            db.add(row)
        row.timing = item.get("timing") or "required_before_activation"
        row.is_blocking = bool(evaluation.get("is_blocking", item.get("is_blocking", True)))
        row.is_legal_block = bool(item.get("is_legal_block", False))
        row.status = str(evaluation.get("status") or "PENDING")
        row.traffic_light = str(evaluation.get("traffic_light") or "red")
        row.expiration_date = evaluation.get("expiration_date")
        row.verification_source = evaluation.get("verification_source") or item.get("verification_source")
        row.evidence_ref = evaluation.get("evidence_ref")
        if evaluation.get("external_status"):
            row.external_status = normalize_external_status(str(evaluation.get("external_status")))
        else:
            row.external_status = normalize_external_status(row.status)
        row.updated_at = now()
        row.notes = evaluation.get("notes")
    db.flush()


def build_ai_summary(case: ApprovalCase, evaluations: dict[str, dict[str, Any]], tiers: list[str]) -> str:
    badge = case.display_badge or case.id[:8]
    parts = [
        f"Driver {badge} is {case.readiness_percentage:.0f}% complete.",
    ]
    labels = {
        "drivers_license": "License",
        "vehicle_registration": "Registration",
        "vehicle_insurance": "Insurance",
        "mvr": "MVR",
        "background_study": "Background study",
        "fingerprint": "Fingerprint",
        "base_training": "Training",
        "payout_setup": "Payout setup",
        "contractor_agreement": "Contractor agreement",
        "w9": "W-9",
    }
    for key, label in labels.items():
        state = evaluations.get(key)
        if not state:
            continue
        status = state.get("status")
        if status in {"NOT_REQUIRED", "CONDITIONAL_NOT_APPLICABLE"}:
            if key == "fingerprint":
                parts.append("Fingerprinting not currently applicable for requested service tier.")
            elif key == "background_study":
                parts.append("Background study applies when STS/MHCP or authoritative rules require it.")
            continue
        if status in {"COMPLETE", "VERIFIED", "CLEARED"}:
            parts.append(f"{label} verified/complete.")
        elif status in {
            "PENDING_EXTERNAL",
            "PENDING_VERIFICATION",
            "REQUIRED",
            "IN_PROGRESS",
            "SUBMITTED",
            "MANUAL_REVIEW",
        }:
            parts.append(f"{label} pending external/manual verification.")
        elif status == "NOT_STARTED":
            parts.append(f"{label} not started.")
        else:
            parts.append(f"{label} {str(status).lower().replace('_', ' ')}.")
    if "STS_ELIGIBLE" not in tiers and "FUTURE_MHCP_NEMT" not in tiers:
        parts.append("Background study required only for STS service.")
    if case.workflow_status != "ACTIVE":
        parts.append("Driver cannot be activated.")
    return " ".join(parts)


def run_ai_review(
    db: Session,
    case: ApprovalCase,
    *,
    application: PlatformDriverOnboardingApplication | None = None,
    actor_type: str = "AI",
    actor_id: str | None = "approval_engine",
) -> ApprovalCase:
    """Evaluate requirements, open external tasks, advance workflow status deterministically."""
    previous = normalize_status(case.workflow_status)
    if previous == "PENDING":
        assert_transition_allowed(previous, "AI_REVIEW")
        case.workflow_status = "AI_REVIEW"

    tiers = normalize_tiers(_json_list(case.requested_service_tiers_json))
    if application:
        case.legal_name = " ".join(
            part for part in [application.legal_first_name, application.legal_middle_name, application.legal_last_name] if part
        ).strip() or case.legal_name
        case.contact_phone = mask_phone(application.mobile_phone) if application.mobile_phone else case.contact_phone
        case.contact_email = application.email or case.contact_email
        case.license_number_masked = (
            mask_license_number(application.drivers_license_number)
            if application.drivers_license_number
            else case.license_number_masked
        )
        case.license_state = application.license_issuing_state
        case.license_expiration = application.license_expiration_date
        case.age_verification_status = "PRESENT" if application.date_of_birth else "MISSING"
        case.platform_ops_application_id = application.id
        case.application_id = application.id
        if application.willing_wheelchair and "STS_ELIGIBLE" not in tiers:
            # Willingness alone does not auto-approve STS; keep as requested interest only.
            pass

    case.requested_service_tiers_json = _set_json_list(tiers)
    if not fingerprint_required_for_tiers(tiers):
        case.fingerprint_status = "NOT_REQUIRED"
    elif case.fingerprint_status == "NOT_REQUIRED":
        case.fingerprint_status = "REQUIRED"

    _ensure_training(db, case, tiers)
    db.refresh(case)

    documents: list[PlatformDriverOnboardingDocument] = []
    if application is not None:
        documents = list(application.documents or [])
        if not documents:
            documents = (
                db.query(PlatformDriverOnboardingDocument)
                .filter(PlatformDriverOnboardingDocument.application_id == application.id)
                .all()
            )

    plan = build_requirement_plan(tiers)
    evaluations: dict[str, dict[str, Any]] = {}
    next_actions: list[str] = []
    external_needed = False
    action_required = False

    existing_reqs = {r.requirement_key: r for r in (case.requirements or [])}
    for item in plan:
        key = item["requirement_key"]
        prior = existing_reqs.get(key)
        # Never let AI overwrite a human/external verification that already has evidence.
        if (
            prior
            and prior.verified_by
            and prior.status in {"COMPLETE", "VERIFIED", "CLEARED", "NOT_REQUIRED"}
            and (prior.evidence_ref or prior.evidence_source or prior.provider_reference_id)
            and getattr(prior, "external_status", None) != "EXPIRED"
        ):
            evaluation = {
                "status": prior.status,
                "traffic_light": prior.traffic_light or "green",
                "is_blocking": prior.is_blocking,
                "expiration_date": prior.expiration_date,
                "evidence_ref": prior.evidence_ref,
                "verification_source": prior.verification_source or "human_or_external",
                "external_status": getattr(prior, "external_status", None) or "VERIFIED",
            }
        else:
            evaluation = evaluate_requirement_state(
                key=key,
                timing=item["timing"],
                application=application,
                documents=documents,
                case=case,
                tiers=tiers,
            )
        evaluations[key] = evaluation
        if evaluation.get("external_task"):
            external_needed = True
            _ensure_external_task(
                db,
                case,
                task_type=str(evaluation["external_task"]),
                title=item.get("label") or key,
                instructions=(
                    f"External verification required for {item.get('label') or key}. "
                    "AI prepared this task but cannot fabricate a verification result."
                ),
            )
            next_actions.append(f"Complete external task: {evaluation['external_task']}")
        status = str(evaluation.get("status") or "")
        satisfied_statuses = {
            "COMPLETE",
            "VERIFIED",
            "CLEARED",
            "NOT_REQUIRED",
            "FUTURE",
            "CONDITIONAL_NOT_APPLICABLE",
        }
        if item.get("timing") in {"required_now", "required_before_activation"} and status not in satisfied_statuses:
            action_required = True
            if status in {"MISSING", "MISSING_CONSENT", "NOT_STARTED", "EXPIRED", "FAILED"}:
                next_actions.append(f"Resolve {item.get('label') or key} ({status})")

    _sync_requirements(db, case, plan, evaluations)
    _sync_vehicle_from_application(db, case, application)

    scored = [
        e
        for key, e in evaluations.items()
        if next((p for p in plan if p["requirement_key"] == key), {}).get("timing")
        in {"required_now", "required_before_activation"}
    ]
    # Verified/complete = full credit. Uploaded/awaiting external check = half credit
    # so applicant package progress is visible without fabricating verification.
    progress = 0.0
    for e in scored:
        status = e.get("status")
        if status in {"COMPLETE", "VERIFIED", "CLEARED", "NOT_REQUIRED", "CONDITIONAL_NOT_APPLICABLE"}:
            progress += 1.0
        elif status in {"PENDING_EXTERNAL", "PENDING_VERIFICATION", "IN_PROGRESS", "SUBMITTED"}:
            progress += 0.5
    case.readiness_percentage = round(100.0 * progress / max(len(scored), 1), 1)
    case.compliance_score = case.readiness_percentage
    case.next_required_action = "; ".join(next_actions[:8]) if next_actions else "No outstanding AI-tracked actions"
    case.ai_summary = build_ai_summary(case, evaluations, tiers)
    case.last_ai_review_at = now()
    case.updated_at = now()

    blocking_incomplete = any(
        e.get("is_blocking")
        and e.get("status")
        not in {"COMPLETE", "VERIFIED", "CLEARED", "NOT_REQUIRED", "FUTURE", "CONDITIONAL_NOT_APPLICABLE"}
        for e in scored
    )

    current = normalize_status(case.workflow_status)
    target = current
    if blocking_incomplete:
        target = "EXTERNAL_VERIFICATION" if external_needed and not any(
            e.get("status") in {"MISSING", "MISSING_CONSENT", "NOT_STARTED", "EXPIRED"} for e in scored
        ) else "ACTION_REQUIRED"
        if action_required and any(
            e.get("status") in {"MISSING", "MISSING_CONSENT", "NOT_STARTED", "EXPIRED", "FAILED"} for e in scored
        ):
            target = "ACTION_REQUIRED"
        elif external_needed:
            target = "EXTERNAL_VERIFICATION"
    else:
        target = "READY_FOR_APPROVAL"

    # Do not auto-demote ACTIVE/OWNER_APPROVED/APPROVED via AI review.
    if current in {"ACTIVE", "OWNER_APPROVED", "APPROVED", "REJECTED", "SUSPENDED"}:
        target = current
    elif current != target:
        assert_transition_allowed(current, target)
        case.workflow_status = target

    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        entity_id=case.entity_id or case.health_isf_driver_id,
        actor_type=actor_type,
        actor_id=actor_id,
        previous_status=previous,
        new_status=case.workflow_status,
        action="ai_application_review",
        reason=case.ai_summary,
        metadata={
            "readiness_percentage": case.readiness_percentage,
            "next_actions": next_actions,
            "tiers": tiers,
            "external_needed": external_needed,
        },
    )
    db.commit()
    db.refresh(case)
    return case
