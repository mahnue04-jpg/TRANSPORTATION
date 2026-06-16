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
from app.core.nova.compliance_storage import storage_abstraction
from app.db.models import (
    ComplianceAuditEvent,
    ComplianceDocumentEvidence,
    ComplianceDocumentLineageEvent,
    ComplianceExportBundle,
    ComplianceSignedAccessGrant,
    ComplianceSupervisorHandoffEvent,
    ComplianceRetentionEvent,
    DriverComplianceProfile,
    ComplianceDocumentMetadata,
)
from app.helpers import json_dumps, json_loads_or, now, uuid4
from app.monitoring.runtime_logger import record_supervision_event


RETENTION_CLASSES = {"temporary", "operational", "regulatory", "legal_hold", "permanent"}
POLICY_JURISDICTIONS = {"minnesota", "wisconsin", "iowa", "north dakota", "south dakota"}
TRANSPORT_TYPES = {"non_emergency", "wheelchair", "stretcher", "medical"}
HANDOFF_SEQUENCE = [
    "review_started",
    "compliance_verified",
    "supervisor_review",
    "secondary_confirmation",
    "approved",
    "rejected",
]


_POLICY_PACKS: dict[str, dict[str, Any]] = {
    "minnesota": {
        "jurisdiction": "Minnesota",
        "license_expiration_threshold_days": 30,
        "insurance_minimum": "state_required",
        "medical_transport_class": "NEMT",
        "transport_types": ["non_emergency", "wheelchair", "medical"],
    },
    "wisconsin": {
        "jurisdiction": "Wisconsin",
        "license_expiration_threshold_days": 30,
        "insurance_minimum": "state_required",
        "medical_transport_class": "NEMT",
        "transport_types": ["non_emergency", "wheelchair", "medical"],
    },
    "iowa": {
        "jurisdiction": "Iowa",
        "license_expiration_threshold_days": 30,
        "insurance_minimum": "state_required",
        "medical_transport_class": "NEMT",
        "transport_types": ["non_emergency", "medical"],
    },
    "north dakota": {
        "jurisdiction": "North Dakota",
        "license_expiration_threshold_days": 30,
        "insurance_minimum": "state_required",
        "medical_transport_class": "NEMT",
        "transport_types": ["non_emergency", "medical"],
    },
    "south dakota": {
        "jurisdiction": "South Dakota",
        "license_expiration_threshold_days": 30,
        "insurance_minimum": "state_required",
        "medical_transport_class": "NEMT",
        "transport_types": ["non_emergency", "medical"],
    },
}


def _require_reason(reason: str | None, field: str = "reason") -> str:
    text = str(reason or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"{field} is required")
    return text


def _max_sequence(db: Session, model: Any) -> int:
    return int(db.query(func.max(model.sequence)).scalar() or 0)


def _checksum_for_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json_dumps(payload).encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _role_scope(actor_role: str) -> list[str]:
    role = str(actor_role or "").lower()
    if role == ROLE_MEDICAL_COORDINATOR:
        return ["medical_coordinator", "compliance_officer", "supervisor", "admin"]
    if role == ROLE_DRIVER_SUPPORT:
        return ["driver_support", "compliance_officer", "supervisor", "admin"]
    if role in {ROLE_COMPLIANCE_OFFICER, ROLE_SUPERVISOR, ROLE_ADMIN}:
        return ["compliance_officer", "supervisor", "admin"]
    return ["admin"]


def _serialize_evidence(row: ComplianceDocumentEvidence) -> dict[str, Any]:
    return {
        "document_id": row.document_id,
        "driver_id": row.driver_id,
        "storage_provider": row.storage_provider,
        "checksum": row.checksum,
        "mime_type": row.mime_type,
        "retention_class": row.retention_class,
        "encryption_status": row.encryption_status,
        "uploaded_by": row.uploaded_by,
        "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
        "immutable_reference_id": row.immutable_reference_id,
        "superseded_by": row.superseded_by,
        "replaces_document_id": row.replaces_document_id,
        "lineage_root_id": row.lineage_root_id,
    }


class ComplianceEvidenceService:
    @staticmethod
    def append_document_evidence(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        driver_id = str(payload.get("driver_id") or "").strip()
        document_id = str(payload.get("document_id") or "").strip()
        if not driver_id or not document_id:
            raise HTTPException(status_code=422, detail="driver_id and document_id are required")

        retention_class = str(payload.get("retention_class") or "operational").strip().lower()
        if retention_class not in RETENTION_CLASSES:
            raise HTTPException(status_code=422, detail=f"invalid retention_class: {retention_class}")

        replaces_document_id = str(payload.get("replaces_document_id") or "").strip() or None
        lineage_root_id = str(payload.get("lineage_root_id") or "").strip() or document_id
        immutable_reference_id = str(payload.get("immutable_reference_id") or f"imm-{uuid4()}")
        mime_type = str(payload.get("mime_type") or "application/octet-stream")
        storage_provider = str(payload.get("storage_provider") or "local_abstraction")

        content_seed = str(payload.get("content_seed") or f"{document_id}:{driver_id}:{immutable_reference_id}").encode("utf-8")
        stored = storage_abstraction.store_document(
            document_id=document_id,
            content=content_seed,
            metadata={
                "immutable_reference_id": immutable_reference_id,
                "storage_provider": storage_provider,
                "mime_type": mime_type,
                "retention_class": retention_class,
                "encryption_status": str(payload.get("encryption_status") or "encrypted_at_rest"),
            },
        )

        previous = (
            db.query(ComplianceDocumentEvidence)
            .filter(
                ComplianceDocumentEvidence.organization_id == organization_id,
                ComplianceDocumentEvidence.document_id == document_id,
            )
            .first()
        )

        evidence = ComplianceDocumentEvidence(
            organization_id=organization_id,
            document_id=document_id,
            driver_id=driver_id,
            storage_provider=storage_provider,
            checksum=stored["checksum"],
            mime_type=mime_type,
            retention_class=retention_class,
            encryption_status=str(payload.get("encryption_status") or "encrypted_at_rest"),
            uploaded_by=actor.user_id,
            uploaded_at=now(),
            immutable_reference_id=immutable_reference_id,
            superseded_by=None,
            replaces_document_id=replaces_document_id,
            lineage_root_id=lineage_root_id,
        )
        db.add(evidence)
        db.flush()

        if previous is not None:
            previous.superseded_by = document_id
            db.flush()

        lineage_event = ComplianceDocumentLineageEvent(
            sequence=_max_sequence(db, ComplianceDocumentLineageEvent) + 1,
            event_id=f"lineage-{uuid4().replace('-', '')[:16]}",
            organization_id=organization_id,
            driver_id=driver_id,
            document_id=document_id,
            immutable_reference_id=immutable_reference_id,
            superseded_by=None,
            replaces_document_id=replaces_document_id,
            lineage_root_id=lineage_root_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            action_type="document_linkage_appended",
            metadata_json=json_dumps(
                {
                    "advisory_only": True,
                    "execution_disabled": True,
                    "append_only": True,
                    "replay_safe": True,
                    "role_scope": _role_scope(actor.role),
                }
            ),
        )
        db.add(lineage_event)

        record_supervision_event(
            subsystem="compliance",
            event="document_linkage_appended",
            details={
                "organization_id": organization_id,
                "driver_id": driver_id,
                "document_id": document_id,
                "immutable_reference_id": immutable_reference_id,
                "replaces_document_id": replaces_document_id,
                "lineage_root_id": lineage_root_id,
                "actor_id": actor.user_id,
                "actor_role": actor.role,
                "correlation_id": correlation_id,
                "advisory_only": True,
                "execution_disabled": True,
                "append_only": True,
                "replay_safe": True,
            },
        )

        db.commit()
        return _serialize_evidence(evidence)

    @staticmethod
    def generate_signed_access(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        document_id = str(payload.get("document_id") or "").strip()
        reason = _require_reason(payload.get("access_reason"), "access_reason")
        ttl_minutes = int(payload.get("ttl_minutes") or 15)
        if ttl_minutes < 1 or ttl_minutes > 120:
            raise HTTPException(status_code=422, detail="ttl_minutes must be between 1 and 120")

        evidence = (
            db.query(ComplianceDocumentEvidence)
            .filter(
                ComplianceDocumentEvidence.organization_id == organization_id,
                ComplianceDocumentEvidence.document_id == document_id,
            )
            .order_by(ComplianceDocumentEvidence.created_at.desc())
            .first()
        )
        if evidence is None:
            raise HTTPException(status_code=404, detail="document evidence not found")

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
        signed = storage_abstraction.generate_signed_access(
            immutable_reference_id=evidence.immutable_reference_id,
            expires_at=expires_at,
            context={
                "generated_by": actor.user_id,
                "generated_by_role": actor.role,
                "access_reason": reason,
                "correlation_id": correlation_id,
            },
        )

        grant = ComplianceSignedAccessGrant(
            signed_access_id=signed["signed_access_id"],
            organization_id=organization_id,
            document_id=document_id,
            generated_by=actor.user_id,
            generated_by_role=actor.role,
            accessed_by=None,
            accessed_by_role=None,
            access_reason=reason,
            correlation_id=correlation_id,
            expires_at=expires_at,
            revoked_at=None,
        )
        db.add(grant)
        db.commit()

        record_supervision_event(
            subsystem="compliance",
            event="signed_access_generated",
            details={
                "organization_id": organization_id,
                "actor_id": actor.user_id,
                "actor_role": actor.role,
                "document_id": document_id,
                "signed_access_id": signed["signed_access_id"],
                "access_reason": reason,
                "expires_at": expires_at.isoformat(),
                "correlation_id": correlation_id,
                "advisory_only": True,
                "execution_disabled": True,
            },
        )

        return {
            "signed_access_id": signed["signed_access_id"],
            "expires_at": expires_at.isoformat(),
            "generated_by": actor.user_id,
            "access_reason": reason,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
        }

    @staticmethod
    def retrieve_document(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        signed_access_id = str(payload.get("signed_access_id") or "").strip()
        reason = _require_reason(payload.get("access_reason"), "access_reason")
        grant = (
            db.query(ComplianceSignedAccessGrant)
            .filter(
                ComplianceSignedAccessGrant.organization_id == organization_id,
                ComplianceSignedAccessGrant.signed_access_id == signed_access_id,
            )
            .first()
        )
        if grant is None:
            raise HTTPException(status_code=404, detail="signed access not found")
        if grant.revoked_at is not None:
            raise HTTPException(status_code=403, detail="signed access revoked")
        if _as_utc(grant.expires_at) < datetime.now(timezone.utc):
            raise HTTPException(status_code=403, detail="signed access expired")

        evidence = (
            db.query(ComplianceDocumentEvidence)
            .filter(
                ComplianceDocumentEvidence.organization_id == organization_id,
                ComplianceDocumentEvidence.document_id == grant.document_id,
            )
            .order_by(ComplianceDocumentEvidence.created_at.desc())
            .first()
        )
        if evidence is None:
            raise HTTPException(status_code=404, detail="document evidence not found")

        if actor.role == ROLE_MEDICAL_COORDINATOR:
            doc_meta = (
                db.query(ComplianceDocumentMetadata)
                .filter(
                    ComplianceDocumentMetadata.organization_id == organization_id,
                    ComplianceDocumentMetadata.document_id == grant.document_id,
                )
                .first()
            )
            if doc_meta is not None and str(doc_meta.type or "") != "certification":
                raise HTTPException(status_code=403, detail="medical coordinator is limited to certification documents")

        signed_row = storage_abstraction.validate_signed_access(signed_access_id=signed_access_id)
        if signed_row is None:
            raise HTTPException(status_code=403, detail="signed access invalid")

        document_payload = storage_abstraction.retrieve_document(immutable_reference_id=evidence.immutable_reference_id)
        if document_payload is None:
            raise HTTPException(status_code=404, detail="document payload not found")

        grant.accessed_by = actor.user_id
        grant.accessed_by_role = actor.role
        db.flush()

        record_supervision_event(
            subsystem="compliance",
            event="document_accessed",
            details={
                "organization_id": organization_id,
                "actor_id": actor.user_id,
                "actor_role": actor.role,
                "document_id": grant.document_id,
                "access_reason": reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "correlation_id": correlation_id,
                "signed_access_id": signed_access_id,
                "advisory_only": True,
                "execution_disabled": True,
            },
        )

        db.commit()

        return {
            "document_id": grant.document_id,
            "signed_access_id": signed_access_id,
            "immutable_reference_id": evidence.immutable_reference_id,
            "checksum": evidence.checksum,
            "mime_type": evidence.mime_type,
            "size_bytes": document_payload.get("size_bytes"),
            "access_reason": reason,
            "accessed_by": actor.user_id,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
        }

    @staticmethod
    def revoke_signed_access(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        signed_access_id = str(payload.get("signed_access_id") or "").strip()
        grant = (
            db.query(ComplianceSignedAccessGrant)
            .filter(
                ComplianceSignedAccessGrant.organization_id == organization_id,
                ComplianceSignedAccessGrant.signed_access_id == signed_access_id,
            )
            .first()
        )
        if grant is None:
            raise HTTPException(status_code=404, detail="signed access not found")

        grant.revoked_at = now()
        storage_abstraction.revoke_access(signed_access_id=signed_access_id)
        db.commit()

        record_supervision_event(
            subsystem="compliance",
            event="signed_access_revoked",
            details={
                "organization_id": organization_id,
                "actor_id": actor.user_id,
                "actor_role": actor.role,
                "signed_access_id": signed_access_id,
                "correlation_id": correlation_id,
                "advisory_only": True,
                "execution_disabled": True,
            },
        )

        return {
            "signed_access_id": signed_access_id,
            "revoked": True,
            "advisory_only": True,
            "execution_disabled": True,
        }

    @staticmethod
    def verify_integrity(
        db: Session,
        *,
        organization_id: str,
        document_id: str,
    ) -> dict[str, Any]:
        evidence = (
            db.query(ComplianceDocumentEvidence)
            .filter(
                ComplianceDocumentEvidence.organization_id == organization_id,
                ComplianceDocumentEvidence.document_id == document_id,
            )
            .order_by(ComplianceDocumentEvidence.created_at.desc())
            .first()
        )
        if evidence is None:
            raise HTTPException(status_code=404, detail="document evidence not found")
        valid = storage_abstraction.verify_integrity(
            immutable_reference_id=evidence.immutable_reference_id,
            expected_checksum=evidence.checksum,
        )
        return {
            "document_id": document_id,
            "immutable_reference_id": evidence.immutable_reference_id,
            "checksum": evidence.checksum,
            "integrity_valid": bool(valid),
            "replay_safe": True,
            "append_only": True,
        }

    @staticmethod
    def generate_export_bundle(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        driver_id = str(payload.get("driver_id") or "").strip() or None
        export_scope = str(payload.get("export_scope") or "driver_regulatory_bundle").strip()
        retention_class = str(payload.get("retention_class") or "regulatory").strip().lower()
        if retention_class not in RETENTION_CLASSES:
            raise HTTPException(status_code=422, detail=f"invalid retention_class: {retention_class}")

        profile = None
        if driver_id:
            profile = (
                db.query(DriverComplianceProfile)
                .filter(
                    DriverComplianceProfile.organization_id == organization_id,
                    DriverComplianceProfile.driver_id == driver_id,
                )
                .first()
            )

        timeline = (
            db.query(ComplianceAuditEvent)
            .filter(ComplianceAuditEvent.organization_id == organization_id)
            .order_by(ComplianceAuditEvent.sequence.asc())
            .all()
        )
        docs = (
            db.query(ComplianceDocumentMetadata)
            .filter(ComplianceDocumentMetadata.organization_id == organization_id)
            .all()
        )
        evidence = (
            db.query(ComplianceDocumentEvidence)
            .filter(ComplianceDocumentEvidence.organization_id == organization_id)
            .all()
        )

        if driver_id:
            timeline = [row for row in timeline if row.target_driver_id == driver_id]
            docs = [row for row in docs if row.driver_id == driver_id]
            evidence = [row for row in evidence if row.driver_id == driver_id]

        payload_json = {
            "export_scope": export_scope,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "driver_profile_snapshot": {
                "driver_id": profile.driver_id if profile else driver_id,
                "onboarding_status": profile.onboarding_status if profile else None,
                "compliance_status": profile.compliance_status if profile else None,
                "approval_status": profile.approval_status if profile else None,
            },
            "compliance_timeline": [
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "action_type": row.action_type,
                    "actor_id": row.actor_id,
                    "actor_role": row.actor_role,
                    "target_driver_id": row.target_driver_id,
                    "timestamp": row.created_at.isoformat() if row.created_at else None,
                    "advisory_flags": json_loads_or(row.advisory_flags, {}),
                }
                for row in timeline
            ],
            "expiration_history": [
                {
                    "document_id": row.document_id,
                    "expiration_date": row.expiration_date.isoformat() if row.expiration_date else None,
                    "verification_status": row.verification_status,
                }
                for row in docs
            ],
            "verification_history": [
                {
                    "document_id": row.document_id,
                    "reviewer_id": row.reviewer_id,
                    "reviewed_at": row.reviewed_at.isoformat() if row.reviewed_at else None,
                    "verification_status": row.verification_status,
                }
                for row in docs
            ],
            "linked_document_metadata": [_serialize_evidence(row) for row in evidence],
            "approval_chain": [
                {
                    "event_id": row.event_id,
                    "action_type": row.action_type,
                    "actor_role": row.actor_role,
                    "timestamp": row.created_at.isoformat() if row.created_at else None,
                }
                for row in timeline
                if row.action_type in {"supervisor_approval_required", "approved", "rejected", "secondary_confirmation"}
            ],
        }
        checksum = _checksum_for_payload(payload_json)
        export_id = f"exp-{uuid4()}"

        row = ComplianceExportBundle(
            export_id=export_id,
            organization_id=organization_id,
            target_driver_id=driver_id,
            generated_by=actor.user_id,
            generated_by_role=actor.role,
            export_scope=export_scope,
            checksum=checksum,
            retention_class=retention_class,
            payload_json=json_dumps(payload_json),
        )
        db.add(row)
        db.commit()

        record_supervision_event(
            subsystem="compliance",
            event="export_bundle_generated",
            details={
                "organization_id": organization_id,
                "export_id": export_id,
                "generated_by": actor.user_id,
                "export_scope": export_scope,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "checksum": checksum,
                "retention_class": retention_class,
                "correlation_id": correlation_id,
                "advisory_only": True,
                "execution_disabled": True,
            },
        )

        return {
            "export_id": export_id,
            "generated_by": actor.user_id,
            "export_scope": export_scope,
            "checksum": checksum,
            "retention_class": retention_class,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "append_only": True,
            "advisory_only": True,
            "execution_disabled": True,
        }

    @staticmethod
    def handoff_transition(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        driver_id = str(payload.get("driver_id") or "").strip()
        stage = str(payload.get("stage") or "").strip().lower()
        if stage not in HANDOFF_SEQUENCE:
            raise HTTPException(status_code=422, detail=f"invalid handoff stage: {stage}")
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")

        reason = _require_reason(payload.get("escalation_notes"), "escalation_notes")

        latest = (
            db.query(ComplianceSupervisorHandoffEvent)
            .filter(
                ComplianceSupervisorHandoffEvent.organization_id == organization_id,
                ComplianceSupervisorHandoffEvent.target_driver_id == driver_id,
            )
            .order_by(ComplianceSupervisorHandoffEvent.sequence.desc())
            .first()
        )

        if latest is not None:
            prev_index = HANDOFF_SEQUENCE.index(str(latest.stage or "review_started"))
            next_index = HANDOFF_SEQUENCE.index(stage)
            if next_index < prev_index:
                raise HTTPException(status_code=409, detail="handoff stage regression is not allowed")
            if next_index - prev_index > 1:
                raise HTTPException(status_code=409, detail="handoff stage ordering violation")

        if stage in {"approved", "rejected", "secondary_confirmation"} and actor.role not in {ROLE_SUPERVISOR, ROLE_ADMIN}:
            raise HTTPException(status_code=403, detail="supervisor or admin required for this handoff stage")

        countersign_id = str(payload.get("countersign_supervisor_id") or "").strip() or None
        if stage == "secondary_confirmation" and not countersign_id:
            raise HTTPException(status_code=422, detail="countersign_supervisor_id is required for secondary_confirmation")

        row = ComplianceSupervisorHandoffEvent(
            sequence=_max_sequence(db, ComplianceSupervisorHandoffEvent) + 1,
            event_id=f"handoff-{uuid4().replace('-', '')[:16]}",
            organization_id=organization_id,
            target_driver_id=driver_id,
            stage=stage,
            actor_id=actor.user_id,
            actor_role=actor.role,
            assigned_supervisor_id=str(payload.get("assigned_supervisor_id") or "").strip() or None,
            countersign_supervisor_id=countersign_id,
            escalation_notes=reason,
            review_reassignment_from=str(payload.get("review_reassignment_from") or "").strip() or None,
            correlation_id=correlation_id,
        )
        db.add(row)
        db.commit()

        return {
            "handoff_event_id": row.event_id,
            "stage": stage,
            "driver_id": driver_id,
            "actor_id": actor.user_id,
            "actor_role": actor.role,
            "assigned_supervisor_id": row.assigned_supervisor_id,
            "countersign_supervisor_id": row.countersign_supervisor_id,
            "escalation_notes": reason,
            "correlation_id": correlation_id,
            "append_only": True,
            "advisory_only": True,
            "execution_disabled": True,
        }

    @staticmethod
    def apply_retention(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        document_id = str(payload.get("document_id") or "").strip()
        retention_class = str(payload.get("retention_class") or "").strip().lower()
        action_type = str(payload.get("action_type") or "retention_class_applied").strip().lower()
        if not document_id:
            raise HTTPException(status_code=422, detail="document_id is required")
        if retention_class not in RETENTION_CLASSES:
            raise HTTPException(status_code=422, detail=f"invalid retention_class: {retention_class}")

        legal_hold = bool(payload.get("legal_hold"))
        release_required = legal_hold or retention_class in {"legal_hold", "permanent"}

        if action_type == "release_legal_hold":
            if actor.role not in {ROLE_SUPERVISOR, ROLE_ADMIN}:
                raise HTTPException(status_code=403, detail="only supervisor/admin can release legal hold")
            _require_reason(payload.get("release_reason"), "release_reason")

        row = ComplianceRetentionEvent(
            sequence=_max_sequence(db, ComplianceRetentionEvent) + 1,
            event_id=f"retain-{uuid4().replace('-', '')[:16]}",
            organization_id=organization_id,
            document_id=document_id,
            retention_class=retention_class,
            actor_id=actor.user_id,
            actor_role=actor.role,
            action_type=action_type,
            legal_hold=legal_hold,
            release_workflow_required=release_required,
            metadata_json=json_dumps(
                {
                    "advisory_only": True,
                    "execution_disabled": True,
                    "append_only": True,
                    "replay_safe": True,
                    "release_reason": payload.get("release_reason"),
                }
            ),
            correlation_id=correlation_id,
        )
        db.add(row)

        evidence_rows = (
            db.query(ComplianceDocumentEvidence)
            .filter(
                ComplianceDocumentEvidence.organization_id == organization_id,
                ComplianceDocumentEvidence.document_id == document_id,
            )
            .all()
        )
        for evidence in evidence_rows:
            evidence.retention_class = retention_class
        db.commit()

        return {
            "event_id": row.event_id,
            "document_id": document_id,
            "retention_class": retention_class,
            "legal_hold": legal_hold,
            "release_workflow_required": release_required,
            "advisory_only": True,
            "execution_disabled": True,
            "append_only": True,
        }

    @staticmethod
    def policy_pack(payload: dict[str, Any]) -> dict[str, Any]:
        jurisdiction = str(payload.get("jurisdiction") or "").strip().lower()
        transport_type = str(payload.get("transport_type") or "").strip().lower() or "non_emergency"
        medical_class = str(payload.get("medical_transport_class") or "NEMT").strip()

        if jurisdiction not in POLICY_JURISDICTIONS:
            raise HTTPException(status_code=422, detail=f"unsupported jurisdiction: {jurisdiction}")
        if transport_type not in TRANSPORT_TYPES:
            raise HTTPException(status_code=422, detail=f"unsupported transport_type: {transport_type}")

        pack = dict(_POLICY_PACKS[jurisdiction])
        pack["transport_type"] = transport_type
        pack["medical_transport_class"] = medical_class
        pack["operator_configurable"] = True
        pack["autonomous_enforcement"] = False
        return pack

    @staticmethod
    def evidence_dashboard_extensions(
        db: Session,
        *,
        organization_id: str,
        role_view: str,
    ) -> dict[str, Any]:
        evidence_rows = (
            db.query(ComplianceDocumentEvidence)
            .filter(ComplianceDocumentEvidence.organization_id == organization_id)
            .order_by(ComplianceDocumentEvidence.created_at.desc())
            .limit(200)
            .all()
        )
        lineage_rows = (
            db.query(ComplianceDocumentLineageEvent)
            .filter(ComplianceDocumentLineageEvent.organization_id == organization_id)
            .order_by(ComplianceDocumentLineageEvent.sequence.desc())
            .limit(200)
            .all()
        )
        signed_rows = (
            db.query(ComplianceSignedAccessGrant)
            .filter(ComplianceSignedAccessGrant.organization_id == organization_id)
            .order_by(ComplianceSignedAccessGrant.created_at.desc())
            .limit(200)
            .all()
        )
        export_rows = (
            db.query(ComplianceExportBundle)
            .filter(ComplianceExportBundle.organization_id == organization_id)
            .order_by(ComplianceExportBundle.created_at.desc())
            .limit(100)
            .all()
        )
        handoff_rows = (
            db.query(ComplianceSupervisorHandoffEvent)
            .filter(ComplianceSupervisorHandoffEvent.organization_id == organization_id)
            .order_by(ComplianceSupervisorHandoffEvent.sequence.desc())
            .limit(200)
            .all()
        )
        retention_rows = (
            db.query(ComplianceRetentionEvent)
            .filter(ComplianceRetentionEvent.organization_id == organization_id)
            .order_by(ComplianceRetentionEvent.sequence.desc())
            .limit(200)
            .all()
        )

        if role_view == ROLE_MEDICAL_COORDINATOR:
            allowed_ids = {
                row.document_id
                for row in db.query(ComplianceDocumentMetadata)
                .filter(
                    ComplianceDocumentMetadata.organization_id == organization_id,
                    ComplianceDocumentMetadata.type == "certification",
                )
                .all()
            }
            evidence_rows = [row for row in evidence_rows if row.document_id in allowed_ids]
            signed_rows = [row for row in signed_rows if row.document_id in allowed_ids]
            retention_rows = [row for row in retention_rows if row.document_id in allowed_ids]

        evidence_chain = [
            {
                "document_id": row.document_id,
                "driver_id": row.driver_id,
                "immutable_reference_id": row.immutable_reference_id,
                "checksum": row.checksum,
                "retention_class": row.retention_class,
                "encryption_status": row.encryption_status,
                "uploaded_at": row.uploaded_at.isoformat() if row.uploaded_at else None,
            }
            for row in evidence_rows[:80]
        ]

        lineage = [
            {
                "sequence": row.sequence,
                "document_id": row.document_id,
                "lineage_root_id": row.lineage_root_id,
                "replaces_document_id": row.replaces_document_id,
                "superseded_by": row.superseded_by,
                "actor_role": row.actor_role,
                "timestamp": row.created_at.isoformat() if row.created_at else None,
            }
            for row in lineage_rows[:120]
        ]

        signed_monitor = [
            {
                "signed_access_id": row.signed_access_id,
                "document_id": row.document_id,
                "generated_by": row.generated_by,
                "generated_by_role": row.generated_by_role,
                "accessed_by": row.accessed_by,
                "accessed_by_role": row.accessed_by_role,
                "access_reason": row.access_reason,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "revoked": row.revoked_at is not None,
                "correlation_id": row.correlation_id,
            }
            for row in signed_rows[:120]
        ]

        export_builder = [
            {
                "export_id": row.export_id,
                "generated_by": row.generated_by,
                "generated_by_role": row.generated_by_role,
                "export_scope": row.export_scope,
                "timestamp": row.created_at.isoformat() if row.created_at else None,
                "checksum": row.checksum,
                "retention_class": row.retention_class,
            }
            for row in export_rows[:80]
        ]

        supervisor_queue = [
            {
                "sequence": row.sequence,
                "event_id": row.event_id,
                "driver_id": row.target_driver_id,
                "stage": row.stage,
                "actor_role": row.actor_role,
                "assigned_supervisor_id": row.assigned_supervisor_id,
                "countersign_supervisor_id": row.countersign_supervisor_id,
                "review_reassignment_from": row.review_reassignment_from,
                "timestamp": row.created_at.isoformat() if row.created_at else None,
            }
            for row in handoff_rows[:120]
        ]

        retention_dashboard = [
            {
                "sequence": row.sequence,
                "document_id": row.document_id,
                "retention_class": row.retention_class,
                "legal_hold": row.legal_hold,
                "release_workflow_required": row.release_workflow_required,
                "action_type": row.action_type,
                "actor_role": row.actor_role,
                "timestamp": row.created_at.isoformat() if row.created_at else None,
            }
            for row in retention_rows[:120]
        ]

        return {
            "evidence_chain_viewer": evidence_chain,
            "document_lineage_viewer": lineage,
            "supervisor_review_queue": supervisor_queue,
            "regulatory_export_builder": export_builder,
            "signed_access_monitor": signed_monitor,
            "retention_status_dashboard": retention_dashboard,
        }
