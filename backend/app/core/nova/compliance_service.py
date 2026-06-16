from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DRIVER_SUPPORT,
    ROLE_MEDICAL_COORDINATOR,
    ROLE_SUPERVISOR,
    UserContext,
)
from app.core.nova.operational_timeline import TimelineEvent, TimelineEventType, operational_timeline
from app.db.models import ComplianceAuditEvent, ComplianceDocumentMetadata, DriverComplianceProfile
from app.helpers import json_dumps, json_loads_or, now, uuid4
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.monitoring.runtime_logger import record_supervision_event


PROFILE_STATUS_VALUES = {"pending", "under_review", "approved", "rejected", "suspended", "expired"}
DOCUMENT_TYPES = {
    "driver_license",
    "insurance",
    "registration",
    "inspection",
    "certification",
    "background_check",
}
VERIFICATION_VALUES = {"pending", "verified", "rejected", "expired"}
SEVERITY_VALUES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
WORKFLOW_SEQUENCE = [
    "driver_application_submitted",
    "compliance_review_started",
    "documents_verified",
    "background_review_completed",
    "supervisor_approval_required",
    "approved",
    "rejected",
]
WORKFLOW_ALLOWED_PREVIOUS: dict[str, set[str]] = {
    "driver_application_submitted": {"pending", "rejected"},
    "compliance_review_started": {"driver_application_submitted"},
    "documents_verified": {"compliance_review_started"},
    "background_review_completed": {"documents_verified"},
    "supervisor_approval_required": {"background_review_completed"},
    "approved": {"supervisor_approval_required"},
    "rejected": {"supervisor_approval_required"},
}
EXPIRING_SOON_DAYS = 30


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: str | datetime | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_profile(profile: DriverComplianceProfile) -> dict[str, Any]:
    return {
        "driver_id": profile.driver_id,
        "onboarding_status": profile.onboarding_status,
        "compliance_status": profile.compliance_status,
        "approval_status": profile.approval_status,
        "background_check_status": profile.background_check_status,
        "background_check_reference": profile.background_check_reference,
        "license_number": profile.license_number,
        "license_expiration": profile.license_expiration.isoformat() if profile.license_expiration else None,
        "insurance_provider": profile.insurance_provider,
        "insurance_expiration": profile.insurance_expiration.isoformat() if profile.insurance_expiration else None,
        "vehicle_registration_expiration": profile.vehicle_registration_expiration.isoformat() if profile.vehicle_registration_expiration else None,
        "vehicle_inspection_expiration": profile.vehicle_inspection_expiration.isoformat() if profile.vehicle_inspection_expiration else None,
        "medical_transport_certified": bool(profile.medical_transport_certified),
        "training_completed": bool(profile.training_completed),
        "notes": profile.notes,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _serialize_document(doc: ComplianceDocumentMetadata) -> dict[str, Any]:
    return {
        "document_id": doc.document_id,
        "driver_id": doc.driver_id,
        "type": doc.type,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at.isoformat() if doc.uploaded_at else None,
        "expiration_date": doc.expiration_date.isoformat() if doc.expiration_date else None,
        "verification_status": doc.verification_status,
        "reviewer_id": doc.reviewer_id,
        "reviewed_at": doc.reviewed_at.isoformat() if doc.reviewed_at else None,
    }


def _severity_for_days(days_remaining: int | None) -> str:
    if days_remaining is None:
        return "LOW"
    if days_remaining < 0:
        return "CRITICAL"
    if days_remaining <= 7:
        return "HIGH"
    if days_remaining <= EXPIRING_SOON_DAYS:
        return "MEDIUM"
    return "LOW"


def _expiration_state(expiration_value: datetime | None) -> tuple[str, int | None]:
    if expiration_value is None:
        return "compliant", None
    days_remaining = int((expiration_value.date() - _utc_now().date()).days)
    if days_remaining < 0:
        return "expired", days_remaining
    if days_remaining <= EXPIRING_SOON_DAYS:
        return "expiring_soon", days_remaining
    return "compliant", days_remaining


def _role_scope_for_action(action_type: str) -> list[str]:
    normalized = str(action_type or "").lower()
    if "medical" in normalized:
        return ["admin", "compliance_officer", "medical_coordinator", "supervisor"]
    if "approval" in normalized or normalized.endswith("approved") or normalized.endswith("rejected"):
        return ["admin", "supervisor", "compliance_officer"]
    return ["admin", "compliance_officer", "driver_support", "supervisor"]


def _ensure_allowed(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise HTTPException(status_code=422, detail=f"Invalid {field}: {value}")
    return normalized


def _require_reason(reason: str | None) -> str:
    text = str(reason or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="approval/rejection reason is required")
    return text


def _hash_token(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _emit_operational_audit_event(
    *,
    organization_id: str,
    event_id: str,
    actor_id: str,
    actor_role: str,
    driver_id: str,
    action_type: str,
    previous_state: dict[str, Any],
    new_state: dict[str, Any],
    advisory_flags: dict[str, Any],
    correlation_id: str,
) -> None:
    timeline_event = TimelineEvent(
        event_id=event_id,
        event_type=TimelineEventType.OPERATOR_COMMAND,
        timestamp=now(),
        organization_id=organization_id,
        correlation_id=correlation_id,
        action_id=driver_id,
        operator_identity=actor_id,
        source_reference_id=action_type,
        title=f"Compliance action: {action_type}",
        description=f"Compliance change for driver {driver_id} recorded in append-only audit log.",
        metadata={
            "actor_role": actor_role,
            "target_driver_id": driver_id,
            "action_type": action_type,
            "previous_state": previous_state,
            "new_state": new_state,
            "advisory_flags": advisory_flags,
            "role_scope": _role_scope_for_action(action_type),
            "advisory_only": True,
            "execution_disabled": True,
            "replay_safe": True,
            "append_only": True,
            "operator_supervised": True,
        },
    )
    operational_timeline.append_event(timeline_event)

    event_kind = OperationalEventType.OPERATIONAL_ALERT if advisory_flags.get("severity") in {"HIGH", "CRITICAL"} else OperationalEventType.WORKFLOW_TRANSITION
    OperationalSynchronizationEngine.publish_event(
        organization_id=organization_id,
        event_type=event_kind,
        role_scope=_role_scope_for_action(action_type),
        source_nonce=f"compliance:{event_id}",
        payload={
            "event_id": event_id,
            "source": "compliance_domain",
            "correlation_id": correlation_id,
            "severity": advisory_flags.get("severity", "LOW").lower(),
            "advisory_only": True,
            "execution_disabled": True,
            "append_only": True,
            "action_type": action_type,
            "target_driver_id": driver_id,
        },
    )


def _insert_audit_row(
    db: Session,
    *,
    organization_id: str,
    actor_id: str,
    actor_role: str,
    driver_id: str,
    action_type: str,
    previous_state: dict[str, Any],
    new_state: dict[str, Any],
    advisory_flags: dict[str, Any],
    correlation_id: str,
) -> ComplianceAuditEvent:
    max_sequence = db.query(func.max(ComplianceAuditEvent.sequence)).scalar() or 0
    event_id = f"cmp-audit-{uuid4().replace('-', '')[:16]}"
    event = ComplianceAuditEvent(
        sequence=int(max_sequence) + 1,
        event_id=event_id,
        organization_id=organization_id,
        actor_id=actor_id,
        actor_role=actor_role,
        target_driver_id=driver_id,
        action_type=action_type,
        previous_state=json_dumps(previous_state),
        new_state=json_dumps(new_state),
        advisory_flags=json_dumps(advisory_flags),
        correlation_id=correlation_id,
    )
    db.add(event)
    db.flush()

    _emit_operational_audit_event(
        organization_id=organization_id,
        event_id=event_id,
        actor_id=actor_id,
        actor_role=actor_role,
        driver_id=driver_id,
        action_type=action_type,
        previous_state=previous_state,
        new_state=new_state,
        advisory_flags=advisory_flags,
        correlation_id=correlation_id,
    )

    record_supervision_event(
        subsystem="compliance",
        event="audit_append",
        details={
            "organization_id": organization_id,
            "event_id": event_id,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "target_driver_id": driver_id,
            "action_type": action_type,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "append_only": True,
            "replay_safe": True,
        },
    )
    return event


def _ensure_profile(db: Session, organization_id: str, driver_id: str) -> DriverComplianceProfile:
    profile = (
        db.query(DriverComplianceProfile)
        .filter(
            DriverComplianceProfile.organization_id == organization_id,
            DriverComplianceProfile.driver_id == driver_id,
        )
        .first()
    )
    if profile is not None:
        return profile

    profile = DriverComplianceProfile(
        organization_id=organization_id,
        driver_id=driver_id,
        onboarding_status="pending",
        compliance_status="pending",
        approval_status="pending",
        background_check_status="pending",
    )
    db.add(profile)
    db.flush()
    return profile


def _can_view_medical_only(role_view: str) -> bool:
    return role_view == ROLE_MEDICAL_COORDINATOR


def _mask_profile_for_role(profile: dict[str, Any], role_view: str) -> dict[str, Any]:
    if not _can_view_medical_only(role_view):
        return profile

    return {
        "driver_id": profile.get("driver_id"),
        "onboarding_status": profile.get("onboarding_status"),
        "compliance_status": profile.get("compliance_status"),
        "approval_status": profile.get("approval_status"),
        "medical_transport_certified": profile.get("medical_transport_certified"),
        "training_completed": profile.get("training_completed"),
        "notes": "masked_for_role",
        "medical_scope": True,
    }


def _mask_doc_for_role(doc: dict[str, Any], role_view: str) -> dict[str, Any]:
    if not _can_view_medical_only(role_view):
        return doc
    if str(doc.get("type") or "") != "certification":
        return {
            "document_id": doc.get("document_id"),
            "driver_id": doc.get("driver_id"),
            "type": doc.get("type"),
            "verification_status": "masked_for_role",
            "medical_scope": True,
        }
    return doc


def _allowed_role_view(user_role: str, role_view: str | None) -> str:
    normalized = str(user_role or "").strip().lower()
    requested = str(role_view or normalized).strip().lower()
    if normalized == ROLE_ADMIN:
        return requested
    if normalized in {ROLE_COMPLIANCE_OFFICER, ROLE_SUPERVISOR, ROLE_DRIVER_SUPPORT, ROLE_MEDICAL_COORDINATOR}:
        return normalized
    return normalized


def _build_expiration_rows(profile: DriverComplianceProfile, docs: list[ComplianceDocumentMetadata]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    profile_expiration_fields: list[tuple[str, datetime | None, str]] = [
        ("license", profile.license_expiration, "license_expiration"),
        ("insurance", profile.insurance_expiration, "insurance_expiration"),
        ("registration", profile.vehicle_registration_expiration, "vehicle_registration_expiration"),
        ("inspection", profile.vehicle_inspection_expiration, "vehicle_inspection_expiration"),
    ]

    for item_type, expiration_value, source in profile_expiration_fields:
        status, days_remaining = _expiration_state(expiration_value)
        severity = _severity_for_days(days_remaining)
        rows.append(
            {
                "driver_id": profile.driver_id,
                "type": item_type,
                "source": source,
                "expiration_date": expiration_value.isoformat() if expiration_value else None,
                "status": status,
                "days_remaining": days_remaining,
                "severity": severity,
            }
        )

    for doc in docs:
        status, days_remaining = _expiration_state(doc.expiration_date)
        severity = _severity_for_days(days_remaining)
        rows.append(
            {
                "driver_id": doc.driver_id,
                "type": doc.type,
                "source": "document",
                "document_id": doc.document_id,
                "expiration_date": doc.expiration_date.isoformat() if doc.expiration_date else None,
                "status": status,
                "days_remaining": days_remaining,
                "severity": severity,
            }
        )

    return rows


def _workflow_step_index(step: str) -> int:
    try:
        return WORKFLOW_SEQUENCE.index(step)
    except ValueError:
        return -1


class ComplianceService:
    @staticmethod
    def upsert_profile(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        driver_id = str(payload.get("driver_id") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")

        profile = _ensure_profile(db, organization_id, driver_id)
        previous_state = _serialize_profile(profile)

        if "onboarding_status" in payload:
            profile.onboarding_status = _ensure_allowed(str(payload.get("onboarding_status")), PROFILE_STATUS_VALUES, "onboarding_status")
        if "compliance_status" in payload:
            profile.compliance_status = _ensure_allowed(str(payload.get("compliance_status")), PROFILE_STATUS_VALUES, "compliance_status")
        if "approval_status" in payload:
            profile.approval_status = _ensure_allowed(str(payload.get("approval_status")), PROFILE_STATUS_VALUES, "approval_status")
        if "background_check_status" in payload:
            profile.background_check_status = _ensure_allowed(str(payload.get("background_check_status")), PROFILE_STATUS_VALUES, "background_check_status")
        if "background_check_reference" in payload:
            profile.background_check_reference = str(payload.get("background_check_reference") or "").strip() or None
        if "license_number" in payload:
            profile.license_number = str(payload.get("license_number") or "").strip() or None
        if "license_expiration" in payload:
            profile.license_expiration = _coerce_datetime(payload.get("license_expiration"))
        if "insurance_provider" in payload:
            profile.insurance_provider = str(payload.get("insurance_provider") or "").strip() or None
        if "insurance_expiration" in payload:
            profile.insurance_expiration = _coerce_datetime(payload.get("insurance_expiration"))
        if "vehicle_registration_expiration" in payload:
            profile.vehicle_registration_expiration = _coerce_datetime(payload.get("vehicle_registration_expiration"))
        if "vehicle_inspection_expiration" in payload:
            profile.vehicle_inspection_expiration = _coerce_datetime(payload.get("vehicle_inspection_expiration"))
        if "medical_transport_certified" in payload:
            profile.medical_transport_certified = bool(payload.get("medical_transport_certified"))
        if "training_completed" in payload:
            profile.training_completed = bool(payload.get("training_completed"))
        if "notes" in payload:
            profile.notes = str(payload.get("notes") or "").strip() or None

        profile.updated_at = now()
        db.flush()

        new_state = _serialize_profile(profile)
        _insert_audit_row(
            db,
            organization_id=organization_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            driver_id=driver_id,
            action_type="profile_upserted",
            previous_state=previous_state,
            new_state=new_state,
            advisory_flags={
                "advisory_only": True,
                "execution_disabled": True,
                "append_only": True,
                "replay_safe": True,
                "severity": "LOW",
            },
            correlation_id=correlation_id,
        )
        db.commit()
        return new_state

    @staticmethod
    def upload_document_metadata(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        driver_id = str(payload.get("driver_id") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")

        doc_type = _ensure_allowed(str(payload.get("type") or ""), DOCUMENT_TYPES, "document type")
        document_id = str(payload.get("document_id") or "").strip() or f"doc-{uuid4().replace('-', '')[:12]}"

        doc = (
            db.query(ComplianceDocumentMetadata)
            .filter(
                ComplianceDocumentMetadata.organization_id == organization_id,
                ComplianceDocumentMetadata.document_id == document_id,
            )
            .first()
        )
        previous_state = _serialize_document(doc) if doc else {}

        if doc is None:
            doc = ComplianceDocumentMetadata(
                organization_id=organization_id,
                document_id=document_id,
                driver_id=driver_id,
                type=doc_type,
                uploaded_by=actor.user_id,
                uploaded_at=now(),
                expiration_date=_coerce_datetime(payload.get("expiration_date")),
                verification_status="pending",
                reviewer_id=None,
                reviewed_at=None,
            )
            db.add(doc)
        else:
            doc.driver_id = driver_id
            doc.type = doc_type
            doc.uploaded_by = actor.user_id
            doc.uploaded_at = now()
            doc.expiration_date = _coerce_datetime(payload.get("expiration_date"))
            doc.verification_status = "pending"
            doc.reviewer_id = None
            doc.reviewed_at = None

        db.flush()
        new_state = _serialize_document(doc)

        _insert_audit_row(
            db,
            organization_id=organization_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            driver_id=driver_id,
            action_type="document_metadata_uploaded",
            previous_state=previous_state,
            new_state=new_state,
            advisory_flags={
                "advisory_only": True,
                "execution_disabled": True,
                "append_only": True,
                "replay_safe": True,
                "severity": "LOW",
            },
            correlation_id=correlation_id,
        )
        db.commit()
        return new_state

    @staticmethod
    def verify_document(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        document_id: str,
        verification_status: str,
        reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        target_status = _ensure_allowed(verification_status, VERIFICATION_VALUES, "verification_status")
        doc = (
            db.query(ComplianceDocumentMetadata)
            .filter(
                ComplianceDocumentMetadata.organization_id == organization_id,
                ComplianceDocumentMetadata.document_id == document_id,
            )
            .first()
        )
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")

        previous_state = _serialize_document(doc)
        doc.verification_status = target_status
        doc.reviewer_id = actor.user_id
        doc.reviewed_at = now()
        db.flush()
        new_state = _serialize_document(doc)
        new_state["reason"] = reason

        _insert_audit_row(
            db,
            organization_id=organization_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            driver_id=doc.driver_id,
            action_type="document_verification_updated",
            previous_state=previous_state,
            new_state=new_state,
            advisory_flags={
                "advisory_only": True,
                "execution_disabled": True,
                "append_only": True,
                "replay_safe": True,
                "severity": "MEDIUM" if target_status == "verified" else "HIGH",
            },
            correlation_id=correlation_id,
        )
        db.commit()
        return new_state

    @staticmethod
    def workflow_action(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        driver_id: str,
        action: str,
        reason: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        normalized_action = str(action or "").strip().lower()
        if normalized_action not in WORKFLOW_SEQUENCE:
            raise HTTPException(status_code=422, detail=f"unsupported workflow action: {action}")

        if normalized_action in {"approved", "rejected"}:
            reason = _require_reason(reason)

        profile = _ensure_profile(db, organization_id, driver_id)
        previous_state = _serialize_profile(profile)
        current_step = str(profile.onboarding_status or "pending")

        if normalized_action in {"approved", "rejected"} and actor.role not in {ROLE_SUPERVISOR, ROLE_ADMIN}:
            raise HTTPException(status_code=403, detail="supervisor approval is mandatory")

        if normalized_action == "supervisor_approval_required" and actor.role not in {ROLE_COMPLIANCE_OFFICER, ROLE_SUPERVISOR, ROLE_ADMIN}:
            raise HTTPException(status_code=403, detail="only compliance officers or supervisors can request approval")

        if normalized_action == "documents_verified" and actor.role not in {ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN}:
            raise HTTPException(status_code=403, detail="only compliance officers can mark documents verified")

        if normalized_action == "driver_application_submitted" and actor.role not in {ROLE_DRIVER_SUPPORT, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN}:
            raise HTTPException(status_code=403, detail="only driver support or compliance can submit applications")

        allowed_previous = WORKFLOW_ALLOWED_PREVIOUS.get(normalized_action, set())
        if current_step not in allowed_previous:
            raise HTTPException(
                status_code=409,
                detail=f"workflow ordering violation: {current_step} -> {normalized_action}",
            )

        profile.onboarding_status = normalized_action
        if normalized_action in {"driver_application_submitted", "compliance_review_started", "documents_verified", "background_review_completed"}:
            profile.compliance_status = "under_review"
            profile.approval_status = "pending"
        elif normalized_action == "supervisor_approval_required":
            profile.compliance_status = "under_review"
            profile.approval_status = "under_review"
        elif normalized_action == "approved":
            profile.compliance_status = "approved"
            profile.approval_status = "approved"
            profile.background_check_status = "approved"
        elif normalized_action == "rejected":
            profile.compliance_status = "rejected"
            profile.approval_status = "rejected"

        if normalized_action == "background_review_completed" and profile.background_check_status in {"pending", "under_review"}:
            profile.background_check_status = "approved"

        profile.notes = reason
        profile.updated_at = now()
        db.flush()

        new_state = _serialize_profile(profile)
        new_state["workflow_reason"] = reason

        _insert_audit_row(
            db,
            organization_id=organization_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            driver_id=driver_id,
            action_type=normalized_action,
            previous_state=previous_state,
            new_state=new_state,
            advisory_flags={
                "advisory_only": True,
                "execution_disabled": True,
                "append_only": True,
                "replay_safe": True,
                "severity": "MEDIUM" if normalized_action in {"documents_verified", "background_review_completed"} else "HIGH",
                "approval_required": normalized_action in {"supervisor_approval_required", "approved", "rejected"},
            },
            correlation_id=correlation_id,
        )

        db.commit()
        return new_state

    @staticmethod
    def expiration_scan(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        profiles = db.query(DriverComplianceProfile).filter(DriverComplianceProfile.organization_id == organization_id).all()
        docs = db.query(ComplianceDocumentMetadata).filter(ComplianceDocumentMetadata.organization_id == organization_id).all()

        docs_by_driver: dict[str, list[ComplianceDocumentMetadata]] = {}
        for doc in docs:
            docs_by_driver.setdefault(doc.driver_id, []).append(doc)

        emitted = 0
        queue_rows: list[dict[str, Any]] = []
        for profile in profiles:
            rows = _build_expiration_rows(profile, docs_by_driver.get(profile.driver_id, []))
            for row in rows:
                queue_rows.append(row)
                if row["status"] not in {"expired", "expiring_soon"}:
                    continue
                row_hash = _hash_token(json_dumps(row))
                action_type = "compliance_expiration_alert"
                advisory_flags = {
                    "advisory_only": True,
                    "execution_disabled": True,
                    "append_only": True,
                    "replay_safe": True,
                    "severity": row["severity"],
                    "operator_action_required": True,
                    "auto_suspension": False,
                }
                _insert_audit_row(
                    db,
                    organization_id=organization_id,
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    driver_id=profile.driver_id,
                    action_type=action_type,
                    previous_state={"status": "none"},
                    new_state={"alert": row, "token": row_hash},
                    advisory_flags=advisory_flags,
                    correlation_id=f"{correlation_id}-{row_hash}",
                )
                emitted += 1

        db.commit()
        return {
            "organization_id": organization_id,
            "alerts_emitted": emitted,
            "queue_size": len(queue_rows),
            "advisory_only": True,
            "execution_disabled": True,
            "replay_safe": True,
        }

    @staticmethod
    def dashboard_summary(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        role_view: str | None,
    ) -> dict[str, Any]:
        effective_view = _allowed_role_view(actor.role, role_view)
        profiles = db.query(DriverComplianceProfile).filter(DriverComplianceProfile.organization_id == organization_id).all()
        docs = db.query(ComplianceDocumentMetadata).filter(ComplianceDocumentMetadata.organization_id == organization_id).all()
        audit_rows = (
            db.query(ComplianceAuditEvent)
            .filter(ComplianceAuditEvent.organization_id == organization_id)
            .order_by(ComplianceAuditEvent.sequence.desc())
            .limit(300)
            .all()
        )

        docs_by_driver: dict[str, list[ComplianceDocumentMetadata]] = {}
        for doc in docs:
            docs_by_driver.setdefault(doc.driver_id, []).append(doc)

        expiration_rows: list[dict[str, Any]] = []
        for profile in profiles:
            expiration_rows.extend(_build_expiration_rows(profile, docs_by_driver.get(profile.driver_id, [])))

        compliant_count = 0
        expiring_count = 0
        expired_count = 0
        under_review_count = 0
        for profile in profiles:
            if profile.compliance_status == "approved":
                compliant_count += 1
            if profile.compliance_status == "under_review":
                under_review_count += 1

        for row in expiration_rows:
            if row["status"] == "expired":
                expired_count += 1
            elif row["status"] == "expiring_soon":
                expiring_count += 1

        pending_approvals = [p for p in profiles if p.approval_status in {"pending", "under_review"}]
        pending_reviews = [p for p in profiles if p.compliance_status == "under_review"]
        rejected_items = [p for p in profiles if p.compliance_status == "rejected" or p.approval_status == "rejected"]

        timeline_rows: list[dict[str, Any]] = []
        for row in audit_rows:
            advisory_flags = json_loads_or(row.advisory_flags, {})
            timeline_rows.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "actor_id": row.actor_id,
                    "actor_role": row.actor_role,
                    "target_driver_id": row.target_driver_id,
                    "action_type": row.action_type,
                    "timestamp": row.created_at.isoformat() if row.created_at else None,
                    "correlation_id": row.correlation_id,
                    "severity": str((advisory_flags or {}).get("severity") or "LOW").upper(),
                    "advisory_only": True,
                    "append_only": True,
                    "role_scope": _role_scope_for_action(row.action_type),
                }
            )

        if effective_view != ROLE_ADMIN:
            timeline_rows = [item for item in timeline_rows if effective_view in item.get("role_scope", [])]

        profiles_payload = [_mask_profile_for_role(_serialize_profile(item), effective_view) for item in profiles]
        docs_payload = [_mask_doc_for_role(_serialize_document(item), effective_view) for item in docs]

        filtered_expiration = expiration_rows
        if effective_view == ROLE_MEDICAL_COORDINATOR:
            filtered_expiration = [row for row in expiration_rows if row.get("type") == "certification"]

        severity_buckets: dict[str, int] = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
        for row in filtered_expiration:
            severity = str(row.get("severity") or "LOW").upper()
            if severity not in SEVERITY_VALUES:
                severity = "LOW"
            severity_buckets[severity] += 1

        return {
            "organization_id": organization_id,
            "role_scope": actor.role,
            "role_view": effective_view,
            "compliance_overview": {
                "total_compliant": compliant_count,
                "expiring_soon": expiring_count,
                "expired": expired_count,
                "under_review": under_review_count,
            },
            "expiration_queue": {
                "licenses_expiring": [row for row in filtered_expiration if row.get("type") == "license" and row.get("status") != "compliant"],
                "insurance_expiring": [row for row in filtered_expiration if row.get("type") == "insurance" and row.get("status") != "compliant"],
                "inspection_expiring": [row for row in filtered_expiration if row.get("type") == "inspection" and row.get("status") != "compliant"],
                "severity_distribution": severity_buckets,
            },
            "approval_queue": {
                "pending_approvals": len(pending_approvals),
                "pending_reviews": len(pending_reviews),
                "rejected_items": len(rejected_items),
            },
            "compliance_timeline": timeline_rows[:120],
            "profiles": profiles_payload,
            "documents": docs_payload,
            "governance": {
                "execution_disabled": True,
                "advisory_only": True,
                "replay_safe": True,
                "append_only": True,
                "deny_by_default": True,
                "mutation_enabled": False,
                "dispatch_actions_enabled": False,
                "autonomous_execution": False,
                "operator_approval_required": True,
            },
        }
