"""Apply external verification adapter submit/record flows to approval cases."""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.approval_engine.audit import record_audit
from app.modules.approval_engine.external_verification import (
    BASE_EXTERNAL_REQUIREMENT_KEYS,
    PROTECTED_EXTERNAL_REQUIREMENT_KEYS,
    ExternalVerificationRecord,
    get_adapter,
    is_externally_satisfied,
    list_adapter_capabilities,
    normalize_external_status,
    traffic_for_external_status,
)
from app.modules.approval_engine.models import ApprovalCase, ApprovalExternalTask, ApprovalRequirement


def _mirror_case_fields(case: ApprovalCase, requirement_key: str, status: str) -> None:
    satisfied = status in {"VERIFIED", "COMPLETE", "CLEARED", "SIGNED", "READY"}
    if status == "DISQUALIFIED" and requirement_key == "fingerprint":
        case.fingerprint_status = "FAILED"
    if requirement_key == "mvr" and satisfied:
        case.mvr_status = "COMPLETE"
        case.mvr_review_date = date.today()
    if requirement_key == "background_study" and satisfied:
        case.background_study_status = "COMPLETE"
    if requirement_key == "fingerprint" and status in {
        "NOT_REQUIRED",
        "PENDING",
        "REQUIRED",
        "COMPLETE",
        "FAILED",
        "VERIFIED",
    }:
        case.fingerprint_status = "COMPLETE" if status == "VERIFIED" else status
    if requirement_key == "vehicle_insurance" and satisfied:
        case.insurance_status = "VERIFIED"
    if requirement_key == "vehicle_registration" and satisfied:
        case.vehicle_registration_status = "VERIFIED"
    if requirement_key == "vehicle_inspection" and satisfied:
        case.inspection_status = "VERIFIED"
    if requirement_key == "drivers_license" and satisfied:
        case.license_verification_status = "VERIFIED"
    if requirement_key == "payout_setup" and satisfied:
        case.payout_setup_status = "COMPLETE"
    if requirement_key == "contractor_agreement" and satisfied:
        case.contractor_agreement_status = "COMPLETE"
    if requirement_key == "w9" and satisfied:
        case.w9_status = "COMPLETE"
    if requirement_key == "base_training" and satisfied:
        pass  # training modules remain source of truth; requirement row tracks external confirmation
    if requirement_key == "medical_qualification" and satisfied:
        case.medical_qualification_status = "COMPLETE"


def _apply_record_to_requirement(
    req: ApprovalRequirement,
    record: ExternalVerificationRecord,
) -> None:
    normalized = record.normalized()
    req.external_status = normalized.status
    # Keep legacy status compatible with existing readiness checks.
    if normalized.status in {"VERIFIED", "CLEARED"}:
        req.status = "VERIFIED" if normalized.status == "VERIFIED" else "CLEARED"
    elif normalized.status == "EXPIRED":
        req.status = "EXPIRED"
    elif normalized.status in {"FAILED", "DISQUALIFIED"}:
        req.status = normalized.status
    elif normalized.status in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW"}:
        req.status = normalized.status
    elif normalized.status == "ACTION_REQUIRED":
        req.status = "ACTION_REQUIRED"
    elif normalized.status == "NOT_STARTED":
        req.status = "NOT_STARTED"
    req.traffic_light = traffic_for_external_status(normalized.status)
    req.provider_key = normalized.provider_key
    req.provider_reference_id = normalized.provider_reference_id
    req.evidence_source = normalized.evidence_source
    req.evidence_ref = normalized.evidence_source or req.evidence_ref
    if normalized.provider_reference_id:
        req.evidence_ref = normalized.provider_reference_id
    req.verification_date = normalized.verification_date
    if normalized.expiration_date is not None:
        req.expiration_date = normalized.expiration_date
    req.reviewer_source = normalized.reviewer_source
    req.verified_by = normalized.reviewer_id
    req.verified_at = now() if is_externally_satisfied(normalized.status) else req.verified_at
    req.verification_source = normalized.provider_key or req.verification_source
    if normalized.notes:
        req.notes = normalized.notes
    req.updated_at = now()


def _upsert_external_task(
    db: Session,
    case: ApprovalCase,
    *,
    requirement_key: str,
    record: ExternalVerificationRecord,
    title: str | None = None,
) -> ApprovalExternalTask:
    open_or_match = next(
        (
            t
            for t in (case.external_tasks or [])
            if getattr(t, "requirement_key", None) == requirement_key
            or t.task_type in {requirement_key, f"{requirement_key}_request", f"{requirement_key}_verification"}
        ),
        None,
    )
    task = open_or_match
    if task is None:
        task = ApprovalExternalTask(
            id=uuid4(),
            case_id=case.id,
            organization_id=case.organization_id,
            task_type=f"{requirement_key}_verification",
            requirement_key=requirement_key,
            title=title or f"External verification: {requirement_key}",
            status="OPEN",
            created_at=now(),
            updated_at=now(),
        )
        db.add(task)
        db.flush()
        if case.external_tasks is not None:
            case.external_tasks.append(task)

    task.requirement_key = requirement_key
    task.provider_key = record.provider_key
    task.provider_reference_id = record.provider_reference_id
    task.external_status = record.status
    task.evidence_source = record.evidence_source
    task.evidence_ref = record.evidence_source or record.provider_reference_id or task.evidence_ref
    task.verification_date = record.verification_date
    task.expiration_date = record.expiration_date
    task.result_status = record.status
    task.result_actor_type = record.reviewer_source
    task.result_actor_id = record.reviewer_id
    history = []
    if task.audit_history_json:
        try:
            history = json.loads(task.audit_history_json)
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
    history.append(
        {
            "at": now().isoformat(),
            "status": record.status,
            "provider_key": record.provider_key,
            "provider_reference_id": record.provider_reference_id,
            "evidence_source": record.evidence_source,
            "reviewer_source": record.reviewer_source,
            "reviewer_id": record.reviewer_id,
            "notes": record.notes,
        }
    )
    task.audit_history_json = json.dumps(history)
    if record.status in {"VERIFIED", "CLEARED", "FAILED", "DISQUALIFIED", "EXPIRED"}:
        task.status = "CLOSED" if record.status in {"VERIFIED", "CLEARED"} else "NEEDS_ATTENTION"
        task.completed_at = now() if record.status in {"VERIFIED", "CLEARED"} else None
    elif record.status in {"PENDING_EXTERNAL", "SUBMITTED", "MANUAL_REVIEW"}:
        task.status = "IN_PROGRESS"
    else:
        task.status = "OPEN"
    task.updated_at = now()
    task.instructions = (
        record.notes
        or task.instructions
        or "External/manual verification — AI must not invent the result."
    )
    return task


def submit_external_verification(
    db: Session,
    *,
    case: ApprovalCase,
    requirement_key: str,
    actor_user_id: str,
    payload: dict[str, Any] | None = None,
) -> ApprovalCase:
    adapter = get_adapter(requirement_key)
    capability = adapter.capability()
    if not capability.can_submit:
        raise ValueError(
            f"Adapter '{capability.provider_key}' cannot submit for {requirement_key}. "
            f"{capability.notes}"
        )
    record = adapter.submit(
        organization_id=case.organization_id,
        case_id=case.id,
        requirement_key=requirement_key,
        payload=payload,
        actor_id=actor_user_id,
    )
    req = next((r for r in (case.requirements or []) if r.requirement_key == requirement_key), None)
    if req is None:
        raise ValueError(f"Unknown requirement: {requirement_key}")
    _apply_record_to_requirement(req, record)
    _upsert_external_task(db, case, requirement_key=requirement_key, record=record, title=req.label)
    case.updated_at = now()
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        entity_id=case.entity_id or case.health_isf_driver_id,
        actor_type="USER",
        actor_id=actor_user_id,
        action="external_verification_submitted",
        reason=f"{requirement_key} submitted via {record.provider_key}",
        evidence_ref=record.provider_reference_id or record.evidence_source,
        metadata=record.to_dict(),
    )
    db.commit()
    db.refresh(case)
    return case


def record_external_verification(
    db: Session,
    *,
    case: ApprovalCase,
    requirement_key: str,
    status: str,
    actor_user_id: str,
    actor_type: str = "EXTERNAL",
    evidence_source: str | None = None,
    provider_reference_id: str | None = None,
    provider_key: str | None = None,
    verification_date: date | None = None,
    expiration_date: date | None = None,
    notes: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApprovalCase:
    if str(actor_type).upper() == "AI":
        raise ValueError("AI must not manufacture or record external verification results")
    if (
        requirement_key == "mvr"
        and normalize_external_status(status) in {"VERIFIED", "CLEARED"}
        and not (provider_key or evidence_source)
    ):
        raise ValueError("Manual MVR VERIFIED/CLEARED requires source/provider name and evidence/reference metadata")
    if (
        str(actor_type).upper() == "SYSTEM"
        and requirement_key in PROTECTED_EXTERNAL_REQUIREMENT_KEYS
        and normalize_external_status(status) in {"VERIFIED", "CLEARED"}
    ):
        raise ValueError(
            "Automatic internal logic must not mark MVR, background study, or fingerprint complete"
        )
    adapter = get_adapter(requirement_key)
    record = adapter.record_result(
        organization_id=case.organization_id,
        case_id=case.id,
        record=ExternalVerificationRecord(
            requirement_key=requirement_key,
            status=status,
            evidence_source=evidence_source,
            provider_key=provider_key,
            provider_reference_id=provider_reference_id,
            verification_date=verification_date or (date.today() if normalize_external_status(status) == "VERIFIED" else None),
            expiration_date=expiration_date,
            reviewer_source=actor_type,
            reviewer_id=actor_user_id,
            notes=notes,
            metadata=metadata or {},
        ),
    )
    req = next((r for r in (case.requirements or []) if r.requirement_key == requirement_key), None)
    if req is None:
        raise ValueError(f"Unknown requirement: {requirement_key}")
    _apply_record_to_requirement(req, record)
    _mirror_case_fields(case, requirement_key, record.status)
    _upsert_external_task(db, case, requirement_key=requirement_key, record=record, title=req.label)
    case.updated_at = now()
    record_audit(
        db,
        organization_id=case.organization_id,
        case=case,
        entity_type="driver",
        entity_id=case.entity_id or case.health_isf_driver_id,
        actor_type=str(actor_type).upper(),
        actor_id=actor_user_id,
        action="external_verification_recorded",
        reason=f"{requirement_key}: {record.status}",
        evidence_ref=record.provider_reference_id or record.evidence_source,
        metadata=record.to_dict(),
    )
    db.commit()
    db.refresh(case)
    return case


def adapters_for_base() -> list[dict[str, Any]]:
    return [
        row
        for row in list_adapter_capabilities()
        if row["requirement_key"] in BASE_EXTERNAL_REQUIREMENT_KEYS
    ]


def remaining_vendor_decisions() -> list[dict[str, str]]:
    return [
        {
            "requirement_key": row["requirement_key"],
            "decision": "Select commercial provider after business/legal review, or keep manual",
            "config_env": row["config_env"],
            "current_mode": row["mode"],
            "vendor_selected": str(row["vendor_selected"]),
        }
        for row in adapters_for_base()
    ]
