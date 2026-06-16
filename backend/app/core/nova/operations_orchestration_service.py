from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
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
from app.db.models import (
    OperationsAcknowledgementEvent,
    OperationsAdvisoryReasoningChain,
    OperationsDecisionProvenance,
    OperationsDecisionSnapshot,
    OperationsAssignmentEvent,
    OperationsCapacityForecastEvent,
    OperationsCapacityPrediction,
    OperationsClosureApprovalEvent,
    OperationsContinuityCheckpoint,
    OperationsCrossRegionHandoffEvent,
    OperationsAnomalyForecast,
    OperationsConstraintProfile,
    OperationsConstraintEvaluation,
    OperationsConstraintViolation,
    OperationsConstraintViolationProjection,
    OperationsEscalationEvent,
    OperationsFederatedQueueSnapshot,
    OperationsFrameworkRuleMapping,
    OperationsGovernanceDecisionTrace,
    OperationsGovernanceDriftEvent,
    OperationsGovernancePrediction,
    OperationsGovernanceRationaleChain,
    OperationsGovernanceTrend,
    OperationsHandoffEvent,
    OperationsNotificationEvent,
    OperationsOptimizationRecommendation,
    OperationsPolicyConstraint,
    OperationsPolicyConstraintVersion,
    OperationsPolicyScoreSnapshot,
    OperationsProjectionCheckpoint,
    OperationsRegulatoryEvidenceRef,
    OperationsRegulatoryFramework,
    OperationsReplayEvidenceEvent,
    OperationsReplayFrame,
    OperationsReplaySession,
    OperationsSimulationScenario,
    OperationsRiskForecast,
    OperationsSimulationProjection,
    OperationsForecastComparison,
    OperationsGovernanceExplanation,
    OperationsGovernanceMemory,
    OperationsTimelineBranch,
    OperationsGovernanceRationale,
    OperationsContinuitySimulation,
    OperationsHistoricalGovernanceState,
    OperationsOperationalAncestry,
    OperationsRecommendationLineage,
    OperationsRegion,
    OperationsRegionMembership,
    OperationsRegionalProjectionEvent,
    OperationsResolutionEvent,
    OperationsSLAThresholdEvent,
    OperationsStreamCursor,
    OperationsTask,
    OperationsTrendMemory,
)
from app.helpers import json_dumps, now, uuid4


HANDOFF_STAGES = ["queued", "assigned", "acknowledged", "escalated", "handoff_pending", "handoff_complete"]
ESCALATION_STAGES = ["level_1", "level_2", "level_3", "critical"]
FRAMEWORK_PRIORITY_WEIGHTS = {
    "SOC2": 0.92,
    "ISO27001": 0.88,
    "HIPAA": 0.97,
    "NIST": 0.9,
    "GDPR": 0.89,
    "PCI-DSS": 0.91,
    "Internal Governance Policies": 0.86,
}
POLICY_CONSTRAINT_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "policy_id": "policy-soc2-access-review",
        "framework_name": "SOC2",
        "regulation_family": "Trust Services Criteria",
        "policy_category": "access_control",
        "rule_code": "CC6.1",
        "severity_weight": 0.91,
        "operational_domain": "identity_governance",
        "evidence_requirements": ["assignment_event", "acknowledgement_event", "approval_event"],
        "rationale_template": "Access changes require explainable supervisory lineage.",
    },
    {
        "policy_id": "policy-iso27001-change-control",
        "framework_name": "ISO27001",
        "regulation_family": "Annex A",
        "policy_category": "change_management",
        "rule_code": "A.8.32",
        "severity_weight": 0.87,
        "operational_domain": "change_control",
        "evidence_requirements": ["timeline_branch", "projection_checkpoint", "resolution_event"],
        "rationale_template": "Operational changes must preserve deterministic and reconstructable lineage.",
    },
    {
        "policy_id": "policy-hipaa-minimum-necessary",
        "framework_name": "HIPAA",
        "regulation_family": "Security Rule",
        "policy_category": "privacy",
        "rule_code": "164.308(a)(1)",
        "severity_weight": 0.96,
        "operational_domain": "medical_operations",
        "evidence_requirements": ["handoff", "notification", "closure_approval"],
        "rationale_template": "Medical transport governance must remain least-privilege and explainable.",
    },
    {
        "policy_id": "policy-nist-auditability",
        "framework_name": "NIST",
        "regulation_family": "CSF",
        "policy_category": "auditability",
        "rule_code": "DE.AE-03",
        "severity_weight": 0.89,
        "operational_domain": "audit_chain",
        "evidence_requirements": ["replay_evidence", "governance_explanation", "decision_snapshot"],
        "rationale_template": "Governance decisions must remain replay-safe and attributable.",
    },
    {
        "policy_id": "policy-gdpr-data-minimization",
        "framework_name": "GDPR",
        "regulation_family": "Data Protection Principles",
        "policy_category": "data_governance",
        "rule_code": "Art.5(1)(c)",
        "severity_weight": 0.88,
        "operational_domain": "data_minimization",
        "evidence_requirements": ["notification_event", "compliance_profile", "evidence_export"],
        "rationale_template": "Only minimally necessary governance evidence should flow across advisory chains.",
    },
    {
        "policy_id": "policy-pci-segmentation-review",
        "framework_name": "PCI-DSS",
        "regulation_family": "Security Controls",
        "policy_category": "network_security",
        "rule_code": "7.2.5",
        "severity_weight": 0.9,
        "operational_domain": "segmentation_review",
        "evidence_requirements": ["federated_queue", "capacity_forecast", "health_region"],
        "rationale_template": "Cross-region governance requires deterministic segmentation evidence.",
    },
    {
        "policy_id": "policy-internal-supervision-first",
        "framework_name": "Internal Governance Policies",
        "regulation_family": "Amicor Governance",
        "policy_category": "supervision",
        "rule_code": "NOVA-GOV-01",
        "severity_weight": 0.93,
        "operational_domain": "supervision_first",
        "evidence_requirements": ["escalation_event", "resolution_event", "governance_provenance"],
        "rationale_template": "No operational pathway may bypass human-governed supervision.",
    },
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat()


def _next_sequence(db: Session, model: Any) -> int:
    return int(db.query(func.max(model.sequence)).scalar() or 0) + 1


def _short_uuid() -> str:
    return str(uuid4()).replace("-", "")[:16]


def _advisory_flags(actor: UserContext) -> str:
    return json_dumps(
        {
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
            "actor_role": actor.role,
            "actor_id": actor.user_id,
        }
    )


def _require_reason(value: str | None, field: str = "reason") -> str:
    text = str(value or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail=f"{field} is required")
    return text


def _must_have_role(actor: UserContext, allowed: set[str], detail: str) -> None:
    if actor.role not in allowed:
        raise HTTPException(status_code=403, detail=detail)


def _resolve_assignee(payload: dict[str, Any]) -> tuple[str, str]:
    assigned_to = str(payload.get("assigned_to") or "").strip()
    assigned_to_role = str(payload.get("assigned_to_role") or "").strip().lower()
    if not assigned_to or not assigned_to_role:
        raise HTTPException(status_code=422, detail="assigned_to and assigned_to_role are required")
    return assigned_to, assigned_to_role


def _checksum_payload(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _event_sort_key(row: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(row.get("timestamp") or ""),
        str(row.get("event_id") or ""),
        int(row.get("sequence") or 0),
    )


class OperationsOrchestrationService:
    @staticmethod
    def _policy_constraint_catalog() -> list[dict[str, Any]]:
        catalog: list[dict[str, Any]] = []
        for item in POLICY_CONSTRAINT_CATALOG:
            record = dict(item)
            record["immutable_hash"] = _checksum_payload(item)
            catalog.append(record)
        return OperationsOrchestrationService._deterministic_constraint_sort(catalog)

    @staticmethod
    def _deterministic_constraint_sort(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            rows,
            key=lambda row: (
                -float(row.get("severity_weight") or 0.0),
                str(row.get("framework_name") or ""),
                str(row.get("policy_id") or ""),
                str(row.get("rule_code") or ""),
            ),
        )

    @staticmethod
    def _calculate_domain_weighting(row: dict[str, Any]) -> float:
        domain = str(row.get("operational_domain") or "").strip().lower()
        if domain in {"medical_operations", "supervision_first", "identity_governance"}:
            return 1.15
        if domain in {"audit_chain", "change_control", "segmentation_review"}:
            return 1.05
        return 0.95

    @staticmethod
    def _normalize_constraint_weights(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        weighted_rows: list[dict[str, Any]] = []
        total = 0.0
        for row in constraints:
            framework_priority = float(FRAMEWORK_PRIORITY_WEIGHTS.get(str(row.get("framework_name") or ""), 0.8))
            domain_weight = OperationsOrchestrationService._calculate_domain_weighting(row)
            raw_weight = float(row.get("severity_weight") or 0.0) * framework_priority * domain_weight
            enriched = dict(row)
            enriched["framework_priority"] = round(framework_priority, 6)
            enriched["domain_weight"] = round(domain_weight, 6)
            enriched["raw_weight"] = round(raw_weight, 6)
            weighted_rows.append(enriched)
            total += raw_weight
        if total <= 0.0:
            total = 1.0
        for row in weighted_rows:
            row["normalized_weight"] = round(float(row["raw_weight"]) / total, 6)
        return OperationsOrchestrationService._deterministic_constraint_sort(weighted_rows)

    @staticmethod
    def _collect_policy_evidence(
        replay_entries: list[dict[str, Any]],
        predictive_entries: list[dict[str, Any]],
        *,
        policy_id: str,
        limit: int = 4,
    ) -> list[dict[str, Any]]:
        evidence_rows: list[dict[str, Any]] = []
        for row in sorted(replay_entries + predictive_entries, key=_event_sort_key)[:limit]:
            evidence_rows.append(
                {
                    "policy_id": policy_id,
                    "event_id": row.get("event_id"),
                    "event_type": row.get("event_type"),
                    "timestamp": row.get("timestamp"),
                    "replay_lineage_ref": row.get("replay_lineage_ref"),
                    "immutable_audit_ref": row.get("immutable_audit_ref"),
                }
            )
        return evidence_rows

    @staticmethod
    def _build_rationale_segments(
        constraint_row: dict[str, Any],
        evidence_rows: list[dict[str, Any]],
        *,
        score_parts: dict[str, float],
    ) -> list[dict[str, Any]]:
        segments = [
            {
                "segment_order": 1,
                "segment_type": "policy",
                "segment_ref": str(constraint_row.get("policy_id") or "unknown-policy"),
                "summary": str(constraint_row.get("rationale_template") or "Policy rationale unavailable."),
            },
            {
                "segment_order": 2,
                "segment_type": "constraint",
                "segment_ref": str(constraint_row.get("rule_code") or "unknown-rule"),
                "summary": "Constraint evaluated with deterministic severity and framework weighting.",
            },
        ]
        for index, evidence in enumerate(evidence_rows, start=3):
            segments.append(
                {
                    "segment_order": index,
                    "segment_type": "evidence",
                    "segment_ref": str(evidence.get("event_id") or "unknown-evidence"),
                    "summary": "Evidence lineage contributes to explainable governance scoring.",
                }
            )
        segments.append(
            {
                "segment_order": len(segments) + 1,
                "segment_type": "score",
                "segment_ref": str(constraint_row.get("framework_name") or "framework"),
                "summary": "Weighted score uses severity, framework priority, evidence quality, lineage confidence, rationale completeness, policy criticality, and historical consistency.",
                "score_parts": score_parts,
            }
        )
        return sorted(segments, key=lambda row: (int(row.get("segment_order") or 0), str(row.get("segment_ref") or "")))

    @staticmethod
    def _reconstruct_constraint_context(snapshot: dict[str, Any], constraint_row: dict[str, Any]) -> dict[str, Any]:
        return {
            "ordering": str(snapshot.get("ordering") or "deterministic_timestamp_eventid_ascending"),
            "determinism_checksum": snapshot.get("determinism_checksum"),
            "policy_id": constraint_row.get("policy_id"),
            "framework_name": constraint_row.get("framework_name"),
            "rule_code": constraint_row.get("rule_code"),
            "event_volume": snapshot.get("total_event_count", 0),
            "historical_consistency": round(max(0.0, 100.0 - float(snapshot.get("total_event_count", 0)) * 0.4), 3),
        }

    @staticmethod
    def _generate_explainable_score(score_parts: dict[str, float]) -> dict[str, Any]:
        weights = {
            "severity": 0.2,
            "operational_impact": 0.14,
            "replay_evidence_quality": 0.12,
            "lineage_confidence": 0.12,
            "rationale_completeness": 0.11,
            "framework_priority": 0.11,
            "policy_criticality": 0.1,
            "historical_governance_consistency": 0.1,
        }
        weighted_score = 0.0
        contributions: dict[str, float] = {}
        for key, weight in weights.items():
            contribution = float(score_parts.get(key, 0.0)) * weight
            contributions[key] = round(contribution, 6)
            weighted_score += contribution
        return {
            "weighted_score": round(weighted_score, 6),
            "weights": weights,
            "contributions": contributions,
        }

    @staticmethod
    def _collect_framework_mappings(constraints: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in constraints:
            rows.append(
                {
                    "policy_id": row.get("policy_id"),
                    "framework_name": row.get("framework_name"),
                    "regulation_family": row.get("regulation_family"),
                    "rule_code": row.get("rule_code"),
                    "operational_domain": row.get("operational_domain"),
                    "evidence_requirements": row.get("evidence_requirements"),
                    "framework_priority": FRAMEWORK_PRIORITY_WEIGHTS.get(str(row.get("framework_name") or ""), 0.8),
                }
            )
        return sorted(rows, key=lambda row: (str(row.get("framework_name") or ""), str(row.get("rule_code") or ""), str(row.get("policy_id") or "")))

    @staticmethod
    def create_task(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(
            actor,
            {ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN},
            "role is not allowed to create tasks",
        )

        title = _require_reason(payload.get("title"), "title")
        description = _require_reason(payload.get("description"), "description")
        task_id = f"task-{uuid4()}"
        task = OperationsTask(
            task_id=task_id,
            organization_id=organization_id,
            title=title,
            description=description,
            category=str(payload.get("category") or "operational").strip().lower(),
            priority=str(payload.get("priority") or "normal").strip().lower(),
            target_driver_id=str(payload.get("target_driver_id") or "").strip() or None,
            created_by=actor.user_id,
            created_by_role=actor.role,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-task-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(task)

        bootstrap_note = OperationsNotificationEvent(
            sequence=_next_sequence(db, OperationsNotificationEvent),
            event_id=f"notify-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            notification_type="task_created",
            notification_scope="role_scoped",
            actor_id=actor.user_id,
            actor_role=actor.role,
            message="Task created and awaiting supervised assignment.",
            metadata_json=json_dumps({"task_title": title, "priority": task.priority}),
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-notify-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(bootstrap_note)
        db.commit()

        return {
            "task_id": task.task_id,
            "title": task.title,
            "priority": task.priority,
            "category": task.category,
            "created_at": _iso_utc(task.created_at),
            "immutable_audit_ref": task.immutable_audit_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def assign_task(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_SUPERVISOR, ROLE_ADMIN}, "role is not allowed to assign tasks")

        task_id = _require_reason(payload.get("task_id"), "task_id")
        assigned_to, assigned_to_role = _resolve_assignee(payload)
        reason = _require_reason(payload.get("reason"), "reason")

        task = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id, OperationsTask.task_id == task_id)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        row = OperationsAssignmentEvent(
            sequence=_next_sequence(db, OperationsAssignmentEvent),
            event_id=f"assign-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            assigned_to=assigned_to,
            assigned_to_role=assigned_to_role,
            actor_id=actor.user_id,
            actor_role=actor.role,
            reason=reason,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-assign-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "assignment_event_id": row.event_id,
            "assigned_to": assigned_to,
            "assigned_to_role": assigned_to_role,
            "reason": reason,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def acknowledge_task(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(
            actor,
            {ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER, ROLE_DRIVER_SUPPORT, ROLE_ADMIN},
            "role is not allowed to acknowledge tasks",
        )

        task_id = _require_reason(payload.get("task_id"), "task_id")
        note = _require_reason(payload.get("note"), "note")
        acknowledgement_type = str(payload.get("acknowledgement_type") or "task_acknowledged").strip().lower()

        task = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id, OperationsTask.task_id == task_id)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        if actor.role == ROLE_DRIVER_SUPPORT:
            latest_assignment = (
                db.query(OperationsAssignmentEvent)
                .filter(
                    OperationsAssignmentEvent.organization_id == organization_id,
                    OperationsAssignmentEvent.task_id == task_id,
                    OperationsAssignmentEvent.assigned_to == actor.user_id,
                )
                .order_by(OperationsAssignmentEvent.sequence.desc())
                .first()
            )
            if latest_assignment is None:
                raise HTTPException(status_code=403, detail="driver support can acknowledge assigned tasks only")

        row = OperationsAcknowledgementEvent(
            sequence=_next_sequence(db, OperationsAcknowledgementEvent),
            event_id=f"ack-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            acknowledgement_type=acknowledgement_type,
            actor_id=actor.user_id,
            actor_role=actor.role,
            note=note,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-ack-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "ack_event_id": row.event_id,
            "acknowledgement_type": acknowledgement_type,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def escalate_task(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_SUPERVISOR, ROLE_ADMIN}, "role is not allowed to escalate tasks")

        task_id = _require_reason(payload.get("task_id"), "task_id")
        escalation_level = str(payload.get("escalation_level") or "").strip().lower()
        routed_to, routed_to_role = _resolve_assignee(
            {
                "assigned_to": payload.get("routed_to"),
                "assigned_to_role": payload.get("routed_to_role"),
            }
        )
        reason = _require_reason(payload.get("reason"), "reason")

        if escalation_level not in ESCALATION_STAGES:
            raise HTTPException(status_code=422, detail="invalid escalation_level")

        task = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id, OperationsTask.task_id == task_id)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        last_escalation = (
            db.query(OperationsEscalationEvent)
            .filter(OperationsEscalationEvent.organization_id == organization_id, OperationsEscalationEvent.task_id == task_id)
            .order_by(OperationsEscalationEvent.sequence.desc())
            .first()
        )
        if last_escalation is not None:
            prior = ESCALATION_STAGES.index(str(last_escalation.escalation_level))
            nxt = ESCALATION_STAGES.index(escalation_level)
            if nxt < prior:
                raise HTTPException(status_code=409, detail="escalation ordering violation")

        row = OperationsEscalationEvent(
            sequence=_next_sequence(db, OperationsEscalationEvent),
            event_id=f"escalate-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            escalation_level=escalation_level,
            routed_to=routed_to,
            routed_to_role=routed_to_role,
            actor_id=actor.user_id,
            actor_role=actor.role,
            reason=reason,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-escalate-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "escalation_event_id": row.event_id,
            "escalation_level": escalation_level,
            "routed_to": routed_to,
            "routed_to_role": routed_to_role,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def handoff_task(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_SUPERVISOR, ROLE_ADMIN}, "role is not allowed to handoff tasks")

        task_id = _require_reason(payload.get("task_id"), "task_id")
        to_user_id = _require_reason(payload.get("to_user_id"), "to_user_id")
        to_role = _require_reason(payload.get("to_role"), "to_role").lower()
        stage = str(payload.get("stage") or "handoff_pending").strip().lower()
        note = _require_reason(payload.get("note"), "note")

        if stage not in HANDOFF_STAGES:
            raise HTTPException(status_code=422, detail="invalid handoff stage")

        task = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id, OperationsTask.task_id == task_id)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        latest = (
            db.query(OperationsHandoffEvent)
            .filter(OperationsHandoffEvent.organization_id == organization_id, OperationsHandoffEvent.task_id == task_id)
            .order_by(OperationsHandoffEvent.sequence.desc())
            .first()
        )
        if latest is not None:
            prev_index = HANDOFF_STAGES.index(str(latest.stage))
            next_index = HANDOFF_STAGES.index(stage)
            if next_index < prev_index:
                raise HTTPException(status_code=409, detail="handoff sequencing violation")

        row = OperationsHandoffEvent(
            sequence=_next_sequence(db, OperationsHandoffEvent),
            event_id=f"handoff-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            stage=stage,
            from_user_id=str(payload.get("from_user_id") or "").strip() or None,
            from_role=str(payload.get("from_role") or "").strip().lower() or None,
            to_user_id=to_user_id,
            to_role=to_role,
            actor_id=actor.user_id,
            actor_role=actor.role,
            note=note,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-handoff-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "handoff_event_id": row.event_id,
            "stage": stage,
            "to_user_id": to_user_id,
            "to_role": to_role,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def append_notification(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(
            actor,
            {ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN},
            "role is not allowed to append notifications",
        )

        task_id = _require_reason(payload.get("task_id"), "task_id")
        notification_type = _require_reason(payload.get("notification_type"), "notification_type").lower()
        message = _require_reason(payload.get("message"), "message")

        task = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id, OperationsTask.task_id == task_id)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

        row = OperationsNotificationEvent(
            sequence=_next_sequence(db, OperationsNotificationEvent),
            event_id=f"notify-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            notification_type=notification_type,
            notification_scope=str(payload.get("notification_scope") or "role_scoped").strip().lower(),
            actor_id=actor.user_id,
            actor_role=actor.role,
            message=message,
            metadata_json=json_dumps(payload.get("metadata") or {}),
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-notify-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "notification_event_id": row.event_id,
            "notification_type": notification_type,
            "message": message,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def _latest_resolution_event(
        db: Session,
        *,
        organization_id: str,
        task_id: str,
    ) -> OperationsResolutionEvent | None:
        return (
            db.query(OperationsResolutionEvent)
            .filter(
                OperationsResolutionEvent.organization_id == organization_id,
                OperationsResolutionEvent.task_id == task_id,
            )
            .order_by(OperationsResolutionEvent.sequence.desc())
            .first()
        )

    @staticmethod
    def _closure_already_achieved(
        db: Session,
        *,
        organization_id: str,
        task_id: str,
    ) -> bool:
        found = (
            db.query(OperationsClosureApprovalEvent.id)
            .filter(
                OperationsClosureApprovalEvent.organization_id == organization_id,
                OperationsClosureApprovalEvent.task_id == task_id,
                OperationsClosureApprovalEvent.closure_achieved.is_(True),
            )
            .first()
        )
        return found is not None

    @staticmethod
    def _task_exists(db: Session, *, organization_id: str, task_id: str) -> None:
        task = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id, OperationsTask.task_id == task_id)
            .first()
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")

    @staticmethod
    def request_resolution(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(
            actor,
            {ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER, ROLE_DRIVER_SUPPORT, ROLE_ADMIN},
            "role is not allowed to request resolution",
        )
        task_id = _require_reason(payload.get("task_id"), "task_id")
        reason = _require_reason(payload.get("reason"), "reason")
        OperationsOrchestrationService._task_exists(db, organization_id=organization_id, task_id=task_id)

        if OperationsOrchestrationService._closure_already_achieved(
            db,
            organization_id=organization_id,
            task_id=task_id,
        ):
            raise HTTPException(status_code=409, detail="task already closed via supervised approvals")

        latest_resolution = OperationsOrchestrationService._latest_resolution_event(
            db,
            organization_id=organization_id,
            task_id=task_id,
        )
        if latest_resolution and latest_resolution.resolution_state == "resolution_requested":
            raise HTTPException(status_code=409, detail="resolution request already pending")

        row = OperationsResolutionEvent(
            sequence=_next_sequence(db, OperationsResolutionEvent),
            event_id=f"resolve-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            resolution_state="resolution_requested",
            resolution_reason=reason,
            requested_by=actor.user_id,
            requested_by_role=actor.role,
            requires_dual_approval=True,
            supervisor_approval_required=True,
            replay_parent_event_id=latest_resolution.event_id if latest_resolution else None,
            replay_lineage_ref=f"resolution-lineage-{task_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-resolution-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "resolution_event_id": row.event_id,
            "resolution_state": row.resolution_state,
            "requires_dual_approval": True,
            "supervisor_approval_required": True,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def approve_resolution(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(
            actor,
            {ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN},
            "role is not allowed to approve resolution",
        )
        task_id = _require_reason(payload.get("task_id"), "task_id")
        reason = _require_reason(payload.get("reason"), "reason")
        OperationsOrchestrationService._task_exists(db, organization_id=organization_id, task_id=task_id)

        latest_resolution = OperationsOrchestrationService._latest_resolution_event(
            db,
            organization_id=organization_id,
            task_id=task_id,
        )
        if latest_resolution is None or latest_resolution.resolution_state != "resolution_requested":
            raise HTTPException(status_code=409, detail="resolution request must exist before approval")

        if OperationsOrchestrationService._closure_already_achieved(
            db,
            organization_id=organization_id,
            task_id=task_id,
        ):
            raise HTTPException(status_code=409, detail="resolution already closed")

        duplicate = (
            db.query(OperationsClosureApprovalEvent.id)
            .filter(
                OperationsClosureApprovalEvent.organization_id == organization_id,
                OperationsClosureApprovalEvent.task_id == task_id,
                OperationsClosureApprovalEvent.resolution_event_id == latest_resolution.event_id,
                OperationsClosureApprovalEvent.approval_action == "approved",
                OperationsClosureApprovalEvent.actor_id == actor.user_id,
            )
            .first()
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="same actor cannot approve closure twice")

        prior_approvals = (
            db.query(OperationsClosureApprovalEvent)
            .filter(
                OperationsClosureApprovalEvent.organization_id == organization_id,
                OperationsClosureApprovalEvent.task_id == task_id,
                OperationsClosureApprovalEvent.resolution_event_id == latest_resolution.event_id,
                OperationsClosureApprovalEvent.approval_action == "approved",
            )
            .order_by(OperationsClosureApprovalEvent.sequence.asc())
            .all()
        )

        prior_actor_ids = {row.actor_id for row in prior_approvals}
        prior_actor_ids.add(actor.user_id)
        prior_has_supervisor = any(row.supervisor_approval for row in prior_approvals)
        current_is_supervisor = actor.role in {ROLE_SUPERVISOR, ROLE_ADMIN}
        closure_achieved = len(prior_actor_ids) >= 2 and (prior_has_supervisor or current_is_supervisor)

        row = OperationsClosureApprovalEvent(
            sequence=_next_sequence(db, OperationsClosureApprovalEvent),
            event_id=f"closure-approve-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            resolution_event_id=latest_resolution.event_id,
            approval_action="approved",
            approval_reason=reason,
            actor_id=actor.user_id,
            actor_role=actor.role,
            supervisor_approval=current_is_supervisor,
            closure_achieved=closure_achieved,
            replay_parent_event_id=latest_resolution.event_id,
            replay_lineage_ref=latest_resolution.replay_lineage_ref,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-closure-approve-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "resolution_event_id": latest_resolution.event_id,
            "approval_event_id": row.event_id,
            "closure_achieved": closure_achieved,
            "dual_approval_satisfied": len(prior_actor_ids) >= 2,
            "supervisor_approval_present": prior_has_supervisor or current_is_supervisor,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def reject_resolution(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(
            actor,
            {ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER, ROLE_ADMIN},
            "role is not allowed to reject resolution",
        )
        task_id = _require_reason(payload.get("task_id"), "task_id")
        reason = _require_reason(payload.get("reason"), "reason")
        OperationsOrchestrationService._task_exists(db, organization_id=organization_id, task_id=task_id)

        latest_resolution = OperationsOrchestrationService._latest_resolution_event(
            db,
            organization_id=organization_id,
            task_id=task_id,
        )
        if latest_resolution is None or latest_resolution.resolution_state != "resolution_requested":
            raise HTTPException(status_code=409, detail="resolution request must exist before rejection")

        if OperationsOrchestrationService._closure_already_achieved(
            db,
            organization_id=organization_id,
            task_id=task_id,
        ):
            raise HTTPException(status_code=409, detail="resolution already closed")

        rejection = OperationsClosureApprovalEvent(
            sequence=_next_sequence(db, OperationsClosureApprovalEvent),
            event_id=f"closure-reject-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            resolution_event_id=latest_resolution.event_id,
            approval_action="rejected",
            approval_reason=reason,
            actor_id=actor.user_id,
            actor_role=actor.role,
            supervisor_approval=actor.role in {ROLE_SUPERVISOR, ROLE_ADMIN},
            closure_achieved=False,
            replay_parent_event_id=latest_resolution.event_id,
            replay_lineage_ref=latest_resolution.replay_lineage_ref,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-closure-reject-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(rejection)

        rejected_resolution = OperationsResolutionEvent(
            sequence=_next_sequence(db, OperationsResolutionEvent),
            event_id=f"resolve-rejected-{_short_uuid()}",
            task_id=task_id,
            organization_id=organization_id,
            resolution_state="resolution_rejected",
            resolution_reason=reason,
            requested_by=actor.user_id,
            requested_by_role=actor.role,
            requires_dual_approval=True,
            supervisor_approval_required=True,
            replay_parent_event_id=rejection.event_id,
            replay_lineage_ref=latest_resolution.replay_lineage_ref,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-resolution-reject-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(rejected_resolution)
        db.commit()

        return {
            "task_id": task_id,
            "resolution_event_id": rejected_resolution.event_id,
            "rejection_event_id": rejection.event_id,
            "resolution_state": "resolution_rejected",
            "timestamp": _iso_utc(rejected_resolution.created_at),
            "immutable_audit_ref": rejected_resolution.immutable_audit_ref,
            "replay_lineage_ref": rejected_resolution.replay_lineage_ref,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def _collect_live_events(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        visible_task_ids: set[str],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        def _append_row(
            *,
            sequence: int,
            event_id: str,
            task_id: str,
            event_type: str,
            actor_role: str,
            timestamp: datetime | None,
            immutable_audit_ref: str,
            correlation_id: str,
            replay_lineage_ref: str,
            metadata: dict[str, Any] | None = None,
        ) -> None:
            if actor.role != ROLE_MEDICAL_COORDINATOR and task_id not in visible_task_ids:
                return
            payload = {
                "sequence": sequence,
                "event_id": event_id,
                "task_id": "masked" if actor.role == ROLE_MEDICAL_COORDINATOR else task_id,
                "event_type": event_type,
                "actor_role": actor_role,
                "timestamp": _iso_utc(timestamp),
                "immutable_audit_ref": immutable_audit_ref,
                "correlation_id": correlation_id,
                "replay_lineage_ref": replay_lineage_ref,
            }
            if metadata:
                payload["metadata"] = metadata
            events.append(payload)

        for row in (
            db.query(OperationsAssignmentEvent)
            .filter(OperationsAssignmentEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="assignment",
                actor_role=row.actor_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=f"task-lineage-{row.task_id}",
            )

        for row in (
            db.query(OperationsEscalationEvent)
            .filter(OperationsEscalationEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="escalation",
                actor_role=row.actor_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=f"task-lineage-{row.task_id}",
                metadata={"escalation_level": row.escalation_level},
            )

        for row in (
            db.query(OperationsHandoffEvent)
            .filter(OperationsHandoffEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="handoff",
                actor_role=row.actor_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=f"task-lineage-{row.task_id}",
                metadata={"stage": row.stage},
            )

        for row in (
            db.query(OperationsAcknowledgementEvent)
            .filter(OperationsAcknowledgementEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="acknowledgement",
                actor_role=row.actor_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=f"task-lineage-{row.task_id}",
                metadata={"acknowledgement_type": row.acknowledgement_type},
            )

        for row in (
            db.query(OperationsNotificationEvent)
            .filter(OperationsNotificationEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="notification",
                actor_role=row.actor_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=f"task-lineage-{row.task_id}",
                metadata={"notification_type": row.notification_type},
            )

        for row in (
            db.query(OperationsResolutionEvent)
            .filter(OperationsResolutionEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="resolution",
                actor_role=row.requested_by_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=row.replay_lineage_ref,
                metadata={
                    "resolution_state": row.resolution_state,
                    "requires_dual_approval": row.requires_dual_approval,
                    "supervisor_approval_required": row.supervisor_approval_required,
                },
            )

        for row in (
            db.query(OperationsClosureApprovalEvent)
            .filter(OperationsClosureApprovalEvent.organization_id == organization_id)
            .all()
        ):
            _append_row(
                sequence=row.sequence,
                event_id=row.event_id,
                task_id=row.task_id,
                event_type="closure_approval",
                actor_role=row.actor_role,
                timestamp=row.created_at,
                immutable_audit_ref=row.immutable_audit_ref,
                correlation_id=row.correlation_id,
                replay_lineage_ref=row.replay_lineage_ref,
                metadata={
                    "approval_action": row.approval_action,
                    "closure_achieved": row.closure_achieved,
                    "supervisor_approval": row.supervisor_approval,
                },
            )

        return sorted(events, key=_event_sort_key)

    @staticmethod
    def generate_live_projection(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        after_sequence: int,
        limit: int,
        correlation_id: str,
    ) -> dict[str, Any]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)
        all_events = OperationsOrchestrationService._collect_live_events(
            db,
            organization_id=organization_id,
            actor=actor,
            visible_task_ids=visible_task_ids,
        )

        projected_rows: list[dict[str, Any]] = []
        for idx, row in enumerate(all_events, start=1):
            if idx <= after_sequence:
                continue
            entry = dict(row)
            entry["projection_sequence"] = idx
            projected_rows.append(entry)
            if len(projected_rows) >= limit:
                break

        next_cursor = max([int(row.get("projection_sequence", 0)) for row in projected_rows], default=after_sequence)
        projection_checksum = _checksum_payload(projected_rows)

        checkpoint = OperationsProjectionCheckpoint(
            sequence=_next_sequence(db, OperationsProjectionCheckpoint),
            checkpoint_id=f"checkpoint-{_short_uuid()}",
            organization_id=organization_id,
            stream_name="ops_orchestration_live",
            replay_start_sequence=after_sequence,
            replay_end_sequence=next_cursor,
            projection_checksum=projection_checksum,
            projection_size=len(projected_rows),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_lineage_ref=f"projection-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-projection-checkpoint-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(checkpoint)

        cursor = OperationsStreamCursor(
            sequence=_next_sequence(db, OperationsStreamCursor),
            cursor_id=f"cursor-{_short_uuid()}",
            organization_id=organization_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            stream_name="ops_orchestration_live",
            cursor_position=next_cursor,
            checkpoint_id=checkpoint.checkpoint_id,
            replay_lineage_ref=f"projection-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-stream-cursor-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(cursor)
        db.commit()

        return {
            "role_view": actor.role,
            "after_sequence": after_sequence,
            "next_cursor": next_cursor,
            "ordering": "deterministic_timestamp_eventid_ascending",
            "projection_checksum": projection_checksum,
            "events": projected_rows,
            "checkpoint": {
                "checkpoint_id": checkpoint.checkpoint_id,
                "replay_start_sequence": checkpoint.replay_start_sequence,
                "replay_end_sequence": checkpoint.replay_end_sequence,
                "projection_checksum": checkpoint.projection_checksum,
                "created_at": _iso_utc(checkpoint.created_at),
            },
            "stream_cursor": {
                "cursor_id": cursor.cursor_id,
                "cursor_position": cursor.cursor_position,
                "checkpoint_id": cursor.checkpoint_id,
                "created_at": _iso_utc(cursor.created_at),
            },
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_sla_snapshot(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)
        tasks = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id)
            .order_by(OperationsTask.created_at.asc())
            .all()
        )
        if actor.role != ROLE_MEDICAL_COORDINATOR:
            tasks = [row for row in tasks if row.task_id in visible_task_ids]

        acknowledgements = (
            db.query(OperationsAcknowledgementEvent)
            .filter(OperationsAcknowledgementEvent.organization_id == organization_id)
            .order_by(OperationsAcknowledgementEvent.sequence.desc())
            .all()
        )
        handoffs = (
            db.query(OperationsHandoffEvent)
            .filter(OperationsHandoffEvent.organization_id == organization_id)
            .order_by(OperationsHandoffEvent.sequence.desc())
            .all()
        )
        escalations = (
            db.query(OperationsEscalationEvent)
            .filter(OperationsEscalationEvent.organization_id == organization_id)
            .order_by(OperationsEscalationEvent.sequence.desc())
            .all()
        )
        resolution_events = (
            db.query(OperationsResolutionEvent)
            .filter(OperationsResolutionEvent.organization_id == organization_id)
            .order_by(OperationsResolutionEvent.sequence.desc())
            .all()
        )
        approvals = (
            db.query(OperationsClosureApprovalEvent)
            .filter(OperationsClosureApprovalEvent.organization_id == organization_id)
            .order_by(OperationsClosureApprovalEvent.sequence.desc())
            .all()
        )

        ack_map: dict[str, OperationsAcknowledgementEvent] = {}
        for row in acknowledgements:
            if row.task_id not in ack_map:
                ack_map[row.task_id] = row

        handoff_map: dict[str, OperationsHandoffEvent] = {}
        for row in handoffs:
            if row.task_id not in handoff_map:
                handoff_map[row.task_id] = row

        escalation_map: dict[str, OperationsEscalationEvent] = {}
        for row in escalations:
            if row.task_id not in escalation_map:
                escalation_map[row.task_id] = row

        resolution_map: dict[str, OperationsResolutionEvent] = {}
        for row in resolution_events:
            if row.task_id not in resolution_map:
                resolution_map[row.task_id] = row

        supervisor_approval_age_seconds: list[int] = []
        alerts: list[dict[str, Any]] = []
        now_utc = _as_utc(now())

        for task in tasks:
            task_age = int((now_utc - _as_utc(task.created_at)).total_seconds())
            task_key = "masked" if actor.role == ROLE_MEDICAL_COORDINATOR else task.task_id

            if task.task_id not in ack_map and task_age >= 900:
                alerts.append(
                    {
                        "task_id": task_key,
                        "metric": "unacknowledged_tasks",
                        "severity": "advisory",
                        "threshold_seconds": 900,
                        "observed_seconds": task_age,
                        "recommendation": "Highlight task in supervisor queue for manual acknowledgement follow-up.",
                    }
                )

            if task.task_id in escalation_map and task_age >= 1800:
                alerts.append(
                    {
                        "task_id": task_key,
                        "metric": "escalation_delays",
                        "severity": "advisory",
                        "threshold_seconds": 1800,
                        "observed_seconds": task_age,
                        "recommendation": "Surface delayed escalations for human review. No automatic escalation is permitted.",
                    }
                )

            handoff = handoff_map.get(task.task_id)
            if handoff is not None and handoff.stage == "handoff_pending":
                handoff_age = int((now_utc - _as_utc(handoff.created_at)).total_seconds())
                if handoff_age >= 1200:
                    alerts.append(
                        {
                            "task_id": task_key,
                            "metric": "unresolved_handoffs",
                            "severity": "advisory",
                            "threshold_seconds": 1200,
                            "observed_seconds": handoff_age,
                            "recommendation": "Increase visibility of pending handoff in supervised timeline.",
                        }
                    )

            resolution = resolution_map.get(task.task_id)
            if resolution is not None and resolution.resolution_state == "resolution_requested":
                approval_rows = [
                    row
                    for row in approvals
                    if row.task_id == task.task_id
                    and row.resolution_event_id == resolution.event_id
                    and row.approval_action == "approved"
                ]
                if not any(row.supervisor_approval for row in approval_rows):
                    resolution_age = int((now_utc - _as_utc(resolution.created_at)).total_seconds())
                    supervisor_approval_age_seconds.append(resolution_age)
                    if resolution_age >= 900:
                        alerts.append(
                            {
                                "task_id": task_key,
                                "metric": "supervisor_approval_latency",
                                "severity": "advisory",
                                "threshold_seconds": 900,
                                "observed_seconds": resolution_age,
                                "recommendation": "Supervisor approval latency is elevated; raise visibility only.",
                            }
                        )

        queue_congestion = len(tasks)
        if queue_congestion >= 20:
            alerts.append(
                {
                    "task_id": "organization",
                    "metric": "queue_congestion",
                    "severity": "advisory",
                    "threshold_seconds": 0,
                    "observed_seconds": queue_congestion,
                    "recommendation": "Queue congestion is elevated; surface advisory signal in operations dashboard.",
                }
            )

        next_sla_sequence = _next_sequence(db, OperationsSLAThresholdEvent)
        for alert in alerts[:100]:
            if alert.get("task_id") == "organization" and actor.role == ROLE_MEDICAL_COORDINATOR:
                task_ref = "masked"
            else:
                task_ref = str(alert.get("task_id") or "")
            sla_row = OperationsSLAThresholdEvent(
                sequence=next_sla_sequence,
                event_id=f"sla-{_short_uuid()}",
                task_id=task_ref,
                organization_id=organization_id,
                threshold_metric=str(alert.get("metric") or "advisory_metric"),
                severity=str(alert.get("severity") or "advisory"),
                threshold_seconds=int(alert.get("threshold_seconds") or 0),
                observed_seconds=int(alert.get("observed_seconds") or 0),
                recommendation=str(alert.get("recommendation") or "Advisory threshold observed."),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"sla-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-sla-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(sla_row)
            next_sla_sequence += 1
        db.commit()

        return {
            "role_view": actor.role,
            "alerts": alerts,
            "metrics": {
                "unacknowledged_tasks": len([a for a in alerts if a.get("metric") == "unacknowledged_tasks"]),
                "escalation_delays": len([a for a in alerts if a.get("metric") == "escalation_delays"]),
                "unresolved_handoffs": len([a for a in alerts if a.get("metric") == "unresolved_handoffs"]),
                "queue_congestion": queue_congestion,
                "supervisor_approval_latency_seconds": max(supervisor_approval_age_seconds, default=0),
            },
            "advisory_limitations": {
                "escalation_actions_automatic": False,
                "closure_automatic": False,
                "dispatch_automatic": False,
            },
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_queue_health_metrics(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService.generate_queue_snapshot(
            db,
            organization_id=organization_id,
            actor=actor,
        )
        queue_health = snapshot.get("queue_health", {})
        pending = int(queue_health.get("pending", 0) or 0)
        escalated = int(queue_health.get("escalated", 0) or 0)
        handoff_pending = int(queue_health.get("handoff_pending", 0) or 0)
        acknowledged = int(queue_health.get("acknowledged", 0) or 0)
        pressure_index = pending + (escalated * 2) + handoff_pending

        return {
            "role_view": actor.role,
            "queue_pressure_dashboard": {
                "pending": pending,
                "escalated": escalated,
                "handoff_pending": handoff_pending,
                "acknowledged": acknowledged,
                "pressure_index": pressure_index,
                "pressure_level": "high" if pressure_index >= 30 else "elevated" if pressure_index >= 15 else "normal",
            },
            "advisory_notes": [
                "Queue pressure is advisory telemetry only.",
                "No automatic escalation or dispatch decisions are executed.",
            ],
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def export_orchestration_evidence_bundle(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)
        events = OperationsOrchestrationService._collect_live_events(
            db,
            organization_id=organization_id,
            actor=actor,
            visible_task_ids=visible_task_ids,
        )

        chain: list[dict[str, Any]] = []
        prior_hash = "GENESIS"
        for row in events:
            digest = _checksum_payload(
                {
                    "event_id": row.get("event_id"),
                    "event_type": row.get("event_type"),
                    "timestamp": row.get("timestamp"),
                    "immutable_audit_ref": row.get("immutable_audit_ref"),
                    "prior_hash": prior_hash,
                }
            )
            chain.append(
                {
                    "event_id": row.get("event_id"),
                    "prior_hash": prior_hash,
                    "event_hash": digest,
                }
            )
            prior_hash = digest

        bundle_payload = {
            "organization_id": organization_id,
            "generated_at": _iso_utc(now()),
            "generated_by": actor.user_id,
            "generated_by_role": actor.role,
            "event_count": len(events),
            "events": events,
            "immutable_chain": chain,
            "chain_tail_hash": prior_hash,
        }
        bundle_checksum = _checksum_payload(bundle_payload)

        return {
            "bundle_id": f"ops-export-{_short_uuid()}",
            "bundle_checksum": bundle_checksum,
            "chain_tail_hash": prior_hash,
            "replay_reconstruction": {
                "ordering": "deterministic_timestamp_eventid_ascending",
                "event_count": len(events),
            },
            "payload": bundle_payload,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
            "correlation_id": correlation_id,
        }

    @staticmethod
    def _visible_region_ids(db: Session, organization_id: str, actor: UserContext) -> set[str]:
        all_region_ids = {
            row.region_id
            for row in db.query(OperationsRegion.region_id)
            .filter(OperationsRegion.organization_id == organization_id)
            .all()
        }
        if actor.role in {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER}:
            return all_region_ids
        if actor.role == ROLE_DRIVER_SUPPORT:
            rows = (
                db.query(OperationsRegionMembership)
                .filter(
                    OperationsRegionMembership.organization_id == organization_id,
                    OperationsRegionMembership.member_user_id == actor.user_id,
                )
                .order_by(OperationsRegionMembership.sequence.desc())
                .all()
            )
            by_region: dict[str, OperationsRegionMembership] = {}
            for row in rows:
                if row.region_id not in by_region:
                    by_region[row.region_id] = row
            return {k for k, v in by_region.items() if v.membership_state == "active"}
        return set()

    @staticmethod
    def _task_region_map(
        db: Session,
        *,
        organization_id: str,
        task_ids: list[str],
    ) -> dict[str, str]:
        region_ids = [
            row.region_id
            for row in db.query(OperationsRegion)
            .filter(OperationsRegion.organization_id == organization_id)
            .order_by(OperationsRegion.region_id.asc())
            .all()
        ]
        if not region_ids:
            return {task_id: "region-unassigned" for task_id in task_ids}
        mapping: dict[str, str] = {}
        for task_id in task_ids:
            digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()
            idx = int(digest[:8], 16) % len(region_ids)
            mapping[task_id] = region_ids[idx]
        return mapping

    @staticmethod
    def register_region(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_ADMIN, ROLE_SUPERVISOR}, "role is not allowed to register region")
        region_code = _require_reason(payload.get("region_code"), "region_code").lower()
        region_name = _require_reason(payload.get("region_name"), "region_name")
        region_id = str(payload.get("region_id") or f"region-{region_code}").strip().lower()

        existing = (
            db.query(OperationsRegion)
            .filter(
                OperationsRegion.organization_id == organization_id,
                OperationsRegion.region_code == region_code,
            )
            .first()
        )
        if existing is not None:
            raise HTTPException(status_code=409, detail="region already registered")

        seq = _next_sequence(db, OperationsRegion)
        region_row = OperationsRegion(
            sequence=seq,
            region_event_id=f"region-{_short_uuid()}",
            region_id=region_id,
            organization_id=organization_id,
            region_code=region_code,
            region_name=region_name,
            governance_scope="isolated",
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"region-lineage-{region_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-region-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(region_row)

        memberships = payload.get("memberships") or []
        if isinstance(memberships, list) and memberships:
            next_membership_seq = _next_sequence(db, OperationsRegionMembership)
            for member in memberships[:100]:
                user_id = str((member or {}).get("user_id") or "").strip()
                if not user_id:
                    continue
                member_role = str((member or {}).get("role") or "driver_support").strip().lower()
                member_state = str((member or {}).get("state") or "active").strip().lower()
                row = OperationsRegionMembership(
                    sequence=next_membership_seq,
                    membership_event_id=f"membership-{_short_uuid()}",
                    organization_id=organization_id,
                    region_id=region_id,
                    member_user_id=user_id,
                    member_role=member_role,
                    membership_state=member_state,
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    replay_parent_event_id=region_row.region_event_id,
                    replay_lineage_ref=f"region-lineage-{region_id}",
                    correlation_id=correlation_id,
                    immutable_audit_ref=f"audit-region-membership-{_short_uuid()}",
                    advisory_flags=_advisory_flags(actor),
                    created_at=now(),
                )
                db.add(row)
                next_membership_seq += 1

        db.commit()
        return {
            "region_id": region_id,
            "region_code": region_code,
            "region_name": region_name,
            "governance_scope": "isolated",
            "immutable_audit_ref": region_row.immutable_audit_ref,
            "replay_lineage_ref": region_row.replay_lineage_ref,
            "timestamp": _iso_utc(region_row.created_at),
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_cross_region_queue_snapshot(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        visible_region_ids = OperationsOrchestrationService._visible_region_ids(db, organization_id, actor)
        queue = OperationsOrchestrationService.generate_queue_snapshot(db, organization_id=organization_id, actor=actor)
        tasks = queue.get("tasks", [])
        task_ids = [str(task.get("task_id") or "") for task in tasks if str(task.get("task_id") or "")]
        region_map = OperationsOrchestrationService._task_region_map(
            db,
            organization_id=organization_id,
            task_ids=task_ids,
        )

        region_stats: dict[str, dict[str, int]] = {}
        for task in tasks:
            task_id = str(task.get("task_id") or "")
            region_id = region_map.get(task_id, "region-unassigned")
            if visible_region_ids and region_id not in visible_region_ids:
                continue
            if region_id not in region_stats:
                region_stats[region_id] = {
                    "pending": 0,
                    "escalated": 0,
                    "handoff_pending": 0,
                    "acknowledged": 0,
                }
            bucket = region_stats[region_id]
            bucket["pending"] += 1
            if task.get("escalation_level"):
                bucket["escalated"] += 1
            if task.get("handoff_stage") == "handoff_pending":
                bucket["handoff_pending"] += 1
            if task.get("last_acknowledged_by"):
                bucket["acknowledged"] += 1

        rows = []
        next_seq = _next_sequence(db, OperationsFederatedQueueSnapshot)
        for region_id in sorted(region_stats.keys()):
            stats = region_stats[region_id]
            checksum = _checksum_payload({"region_id": region_id, **stats})
            row = OperationsFederatedQueueSnapshot(
                sequence=next_seq,
                snapshot_event_id=f"federated-queue-{_short_uuid()}",
                organization_id=organization_id,
                region_id=region_id,
                pending_count=stats["pending"],
                escalated_count=stats["escalated"],
                handoff_pending_count=stats["handoff_pending"],
                acknowledged_count=stats["acknowledged"],
                snapshot_checksum=checksum,
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"federated-queue-lineage-{region_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-federated-queue-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            rows.append(
                {
                    "region_id": region_id,
                    "pending": stats["pending"],
                    "escalated": stats["escalated"],
                    "handoff_pending": stats["handoff_pending"],
                    "acknowledged": stats["acknowledged"],
                    "snapshot_checksum": checksum,
                    "timestamp": _iso_utc(row.created_at),
                }
            )
            next_seq += 1
        db.commit()

        return {
            "role_view": actor.role,
            "regions": rows,
            "ordering": "region_id_ascending",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_federated_projection(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        after_sequence: int,
        limit: int,
        correlation_id: str,
    ) -> dict[str, Any]:
        visible_region_ids = OperationsOrchestrationService._visible_region_ids(db, organization_id, actor)
        queue_payload = OperationsOrchestrationService.generate_cross_region_queue_snapshot(
            db,
            organization_id=organization_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        regions = queue_payload.get("regions", [])

        raw_events: list[dict[str, Any]] = []
        for region in regions:
            region_id = str(region.get("region_id") or "")
            if visible_region_ids and region_id not in visible_region_ids:
                continue
            raw_events.append(
                {
                    "timestamp": _iso_utc(now()),
                    "event_id": f"federated-projection-{_short_uuid()}",
                    "region_id": region_id,
                    "event_type": "federated_queue_projection",
                    "payload": {
                        "pending": int(region.get("pending") or 0),
                        "escalated": int(region.get("escalated") or 0),
                        "handoff_pending": int(region.get("handoff_pending") or 0),
                        "acknowledged": int(region.get("acknowledged") or 0),
                    },
                }
            )

        handoffs = (
            db.query(OperationsCrossRegionHandoffEvent)
            .filter(OperationsCrossRegionHandoffEvent.organization_id == organization_id)
            .order_by(OperationsCrossRegionHandoffEvent.sequence.asc())
            .all()
        )
        for row in handoffs:
            if visible_region_ids and row.source_region_id not in visible_region_ids and row.target_region_id not in visible_region_ids:
                continue
            raw_events.append(
                {
                    "timestamp": _iso_utc(row.created_at),
                    "event_id": row.handoff_event_id,
                    "region_id": row.target_region_id,
                    "event_type": "cross_region_handoff",
                    "payload": {
                        "task_id": row.task_id,
                        "source_region_id": row.source_region_id,
                        "target_region_id": row.target_region_id,
                        "handoff_state": row.handoff_state,
                    },
                }
            )

        raw_events = sorted(raw_events, key=_event_sort_key)
        sliced = raw_events[after_sequence: after_sequence + limit]
        next_cursor = after_sequence + len(sliced)

        persisted = []
        next_seq = _next_sequence(db, OperationsRegionalProjectionEvent)
        for idx, event in enumerate(sliced, start=1):
            payload_json = json_dumps(event.get("payload") or {})
            row = OperationsRegionalProjectionEvent(
                sequence=next_seq,
                projection_event_id=f"regional-projection-{_short_uuid()}",
                organization_id=organization_id,
                region_id=str(event.get("region_id") or "region-unassigned"),
                event_type=str(event.get("event_type") or "projection"),
                projection_order=after_sequence + idx,
                source_event_id=str(event.get("event_id") or "unknown"),
                payload_json=payload_json,
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=str(event.get("event_id") or None),
                replay_lineage_ref=f"federated-projection-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-regional-projection-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            persisted.append(
                {
                    "projection_sequence": row.projection_order,
                    "event_id": row.projection_event_id,
                    "source_event_id": row.source_event_id,
                    "region_id": row.region_id,
                    "event_type": row.event_type,
                    "payload": json.loads(row.payload_json),
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "replay_lineage_ref": row.replay_lineage_ref,
                }
            )
            next_seq += 1
        db.commit()

        return {
            "role_view": actor.role,
            "after_sequence": after_sequence,
            "next_cursor": next_cursor,
            "events": persisted,
            "ordering": "deterministic_timestamp_eventid_ascending",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def create_cross_region_handoff(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER}, "role is not allowed to create cross-region handoff")
        task_id = _require_reason(payload.get("task_id"), "task_id")
        source_region_id = _require_reason(payload.get("source_region_id"), "source_region_id")
        target_region_id = _require_reason(payload.get("target_region_id"), "target_region_id")
        reason = _require_reason(payload.get("reason"), "reason")

        if source_region_id == target_region_id:
            raise HTTPException(status_code=422, detail="source_region_id and target_region_id must differ")

        region_ids = {
            row.region_id
            for row in db.query(OperationsRegion)
            .filter(OperationsRegion.organization_id == organization_id)
            .all()
        }
        if source_region_id not in region_ids or target_region_id not in region_ids:
            raise HTTPException(status_code=404, detail="source or target region not found")

        OperationsOrchestrationService._task_exists(db, organization_id=organization_id, task_id=task_id)

        row = OperationsCrossRegionHandoffEvent(
            sequence=_next_sequence(db, OperationsCrossRegionHandoffEvent),
            handoff_event_id=f"cross-region-handoff-{_short_uuid()}",
            organization_id=organization_id,
            task_id=task_id,
            source_region_id=source_region_id,
            target_region_id=target_region_id,
            handoff_state="handoff_requested",
            handoff_reason=reason,
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"cross-region-lineage-{task_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-cross-region-handoff-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()

        return {
            "task_id": task_id,
            "handoff_event_id": row.handoff_event_id,
            "source_region_id": source_region_id,
            "target_region_id": target_region_id,
            "handoff_state": row.handoff_state,
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_capacity_forecast(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        queue = OperationsOrchestrationService.generate_cross_region_queue_snapshot(
            db,
            organization_id=organization_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        regions = queue.get("regions", [])
        handoff_rows = (
            db.query(OperationsCrossRegionHandoffEvent)
            .filter(OperationsCrossRegionHandoffEvent.organization_id == organization_id)
            .all()
        )

        forecasts = []
        next_seq = _next_sequence(db, OperationsCapacityForecastEvent)
        for region in regions:
            region_id = str(region.get("region_id") or "")
            pending = int(region.get("pending") or 0)
            escalated = int(region.get("escalated") or 0)
            handoff_pending = int(region.get("handoff_pending") or 0)
            unresolved_cross = len([
                row
                for row in handoff_rows
                if row.target_region_id == region_id and row.handoff_state != "handoff_complete"
            ])
            supervisor_bottleneck = escalated + unresolved_cross
            escalation_cluster = escalated
            pressure_score = float((pending * 1.1) + (supervisor_bottleneck * 1.7) + (escalation_cluster * 1.4))
            risk = "high" if pressure_score >= 25 else "elevated" if pressure_score >= 12 else "normal"
            note = "Advisory visibility only. Manual supervision required for all actions."

            row = OperationsCapacityForecastEvent(
                sequence=next_seq,
                forecast_event_id=f"capacity-forecast-{_short_uuid()}",
                organization_id=organization_id,
                region_id=region_id,
                forecast_window="next_30m",
                pressure_score=pressure_score,
                saturation_risk=risk,
                advisory_note=note,
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"capacity-forecast-lineage-{region_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-capacity-forecast-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            forecasts.append(
                {
                    "region_id": region_id,
                    "forecast_window": row.forecast_window,
                    "pressure_score": row.pressure_score,
                    "saturation_risk": row.saturation_risk,
                    "advisory_note": row.advisory_note,
                    "supervisor_bottlenecks": supervisor_bottleneck,
                    "escalation_clustering": escalation_cluster,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                }
            )
            next_seq += 1
        db.commit()

        return {
            "role_view": actor.role,
            "forecasts": forecasts,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_continuity_projection(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        forecasts = OperationsOrchestrationService.generate_capacity_forecast(
            db,
            organization_id=organization_id,
            actor=actor,
            correlation_id=correlation_id,
        )
        handoff_rows = (
            db.query(OperationsCrossRegionHandoffEvent)
            .filter(OperationsCrossRegionHandoffEvent.organization_id == organization_id)
            .all()
        )

        continuity = []
        next_seq = _next_sequence(db, OperationsContinuityCheckpoint)
        for forecast in forecasts.get("forecasts", []):
            region_id = str(forecast.get("region_id") or "")
            unresolved = len([
                row
                for row in handoff_rows
                if row.target_region_id == region_id and row.handoff_state != "handoff_complete"
            ])
            pressure = float(forecast.get("pressure_score") or 0.0)
            risk_score = pressure + (unresolved * 2.0)
            state = "degraded" if risk_score >= 25 else "watch" if risk_score >= 12 else "stable"
            checksum = _checksum_payload({"region_id": region_id, "risk_score": risk_score, "state": state})

            row = OperationsContinuityCheckpoint(
                sequence=next_seq,
                continuity_event_id=f"continuity-{_short_uuid()}",
                organization_id=organization_id,
                region_id=region_id,
                continuity_state=state,
                unresolved_handoffs=unresolved,
                continuity_risk_score=risk_score,
                checkpoint_checksum=checksum,
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"continuity-lineage-{region_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-continuity-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            continuity.append(
                {
                    "region_id": region_id,
                    "continuity_state": state,
                    "unresolved_handoffs": unresolved,
                    "continuity_risk_score": risk_score,
                    "checkpoint_checksum": checksum,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                }
            )
            next_seq += 1
        db.commit()

        return {
            "role_view": actor.role,
            "continuity_projection": continuity,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def build_regional_health_summary(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
    ) -> dict[str, Any]:
        visible_region_ids = OperationsOrchestrationService._visible_region_ids(db, organization_id, actor)
        region_rows = (
            db.query(OperationsRegion)
            .filter(OperationsRegion.organization_id == organization_id)
            .order_by(OperationsRegion.region_code.asc())
            .all()
        )
        latest_forecasts = (
            db.query(OperationsCapacityForecastEvent)
            .filter(OperationsCapacityForecastEvent.organization_id == organization_id)
            .order_by(OperationsCapacityForecastEvent.sequence.desc())
            .all()
        )
        latest_continuity = (
            db.query(OperationsContinuityCheckpoint)
            .filter(OperationsContinuityCheckpoint.organization_id == organization_id)
            .order_by(OperationsContinuityCheckpoint.sequence.desc())
            .all()
        )

        forecast_map: dict[str, OperationsCapacityForecastEvent] = {}
        for row in latest_forecasts:
            if row.region_id not in forecast_map:
                forecast_map[row.region_id] = row
        continuity_map: dict[str, OperationsContinuityCheckpoint] = {}
        for row in latest_continuity:
            if row.region_id not in continuity_map:
                continuity_map[row.region_id] = row

        health = []
        for region in region_rows:
            if visible_region_ids and region.region_id not in visible_region_ids:
                continue
            forecast = forecast_map.get(region.region_id)
            cont = continuity_map.get(region.region_id)
            health.append(
                {
                    "region_id": region.region_id,
                    "region_code": region.region_code,
                    "region_name": region.region_name,
                    "governance_scope": region.governance_scope,
                    "capacity_risk": forecast.saturation_risk if forecast else "unknown",
                    "pressure_score": float(forecast.pressure_score) if forecast else 0.0,
                    "continuity_state": cont.continuity_state if cont else "unknown",
                    "continuity_risk_score": float(cont.continuity_risk_score) if cont else 0.0,
                    "advisory_only": True,
                }
            )

        return {
            "role_view": actor.role,
            "regions": health,
            "regional_isolation": True,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def export_federated_evidence_bundle(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        visible_region_ids = OperationsOrchestrationService._visible_region_ids(db, organization_id, actor)

        rows: list[dict[str, Any]] = []
        for region in (
            db.query(OperationsRegion)
            .filter(OperationsRegion.organization_id == organization_id)
            .order_by(OperationsRegion.sequence.asc())
            .all()
        ):
            if visible_region_ids and region.region_id not in visible_region_ids:
                continue
            rows.append(
                {
                    "event_type": "region",
                    "event_id": region.region_event_id,
                    "region_id": region.region_id,
                    "timestamp": _iso_utc(region.created_at),
                    "immutable_audit_ref": region.immutable_audit_ref,
                }
            )

        for row in (
            db.query(OperationsCrossRegionHandoffEvent)
            .filter(OperationsCrossRegionHandoffEvent.organization_id == organization_id)
            .order_by(OperationsCrossRegionHandoffEvent.sequence.asc())
            .all()
        ):
            if visible_region_ids and row.source_region_id not in visible_region_ids and row.target_region_id not in visible_region_ids:
                continue
            rows.append(
                {
                    "event_type": "cross_region_handoff",
                    "event_id": row.handoff_event_id,
                    "region_id": row.target_region_id,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                }
            )

        for row in (
            db.query(OperationsContinuityCheckpoint)
            .filter(OperationsContinuityCheckpoint.organization_id == organization_id)
            .order_by(OperationsContinuityCheckpoint.sequence.asc())
            .all()
        ):
            if visible_region_ids and row.region_id not in visible_region_ids:
                continue
            rows.append(
                {
                    "event_type": "continuity",
                    "event_id": row.continuity_event_id,
                    "region_id": row.region_id,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                }
            )

        rows = sorted(rows, key=_event_sort_key)
        chain = []
        prior_hash = "GENESIS"
        for row in rows:
            event_hash = _checksum_payload(
                {
                    "event_id": row["event_id"],
                    "event_type": row["event_type"],
                    "timestamp": row["timestamp"],
                    "prior_hash": prior_hash,
                }
            )
            chain.append({"event_id": row["event_id"], "prior_hash": prior_hash, "event_hash": event_hash})
            prior_hash = event_hash

        payload = {
            "organization_id": organization_id,
            "generated_at": _iso_utc(now()),
            "generated_by": actor.user_id,
            "generated_by_role": actor.role,
            "regional_events": rows,
            "immutable_chain": chain,
            "chain_tail_hash": prior_hash,
            "replay_reconstruction": {
                "ordering": "deterministic_timestamp_eventid_ascending",
                "event_count": len(rows),
            },
        }
        checksum = _checksum_payload(payload)
        return {
            "bundle_id": f"federated-export-{_short_uuid()}",
            "bundle_checksum": checksum,
            "chain_tail_hash": prior_hash,
            "payload": payload,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def list_regions(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
    ) -> dict[str, Any]:
        visible_region_ids = OperationsOrchestrationService._visible_region_ids(db, organization_id, actor)
        rows = (
            db.query(OperationsRegion)
            .filter(OperationsRegion.organization_id == organization_id)
            .order_by(OperationsRegion.sequence.asc())
            .all()
        )
        regions = []
        for row in rows:
            if visible_region_ids and row.region_id not in visible_region_ids:
                continue
            regions.append(
                {
                    "region_id": row.region_id,
                    "region_code": row.region_code,
                    "region_name": row.region_name,
                    "governance_scope": row.governance_scope,
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
            )
        return {
            "role_view": actor.role,
            "regions": regions,
            "regional_isolation": True,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def _visible_task_ids(db: Session, organization_id: str, actor: UserContext) -> set[str]:
        if actor.role in {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER}:
            return {
                row.task_id
                for row in db.query(OperationsTask.task_id)
                .filter(OperationsTask.organization_id == organization_id)
                .all()
            }

        if actor.role == ROLE_DRIVER_SUPPORT:
            return {
                row.task_id
                for row in db.query(OperationsAssignmentEvent.task_id)
                .filter(
                    OperationsAssignmentEvent.organization_id == organization_id,
                    OperationsAssignmentEvent.assigned_to == actor.user_id,
                )
                .all()
            }

        if actor.role == ROLE_MEDICAL_COORDINATOR:
            return set()

        return set()

    @staticmethod
    def generate_queue_snapshot(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
    ) -> dict[str, Any]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)

        tasks = (
            db.query(OperationsTask)
            .filter(OperationsTask.organization_id == organization_id)
            .order_by(OperationsTask.created_at.desc())
            .all()
        )

        if actor.role == ROLE_MEDICAL_COORDINATOR:
            return {
                "role_view": actor.role,
                "task_count": len(tasks),
                "masked": True,
                "queue_health": {
                    "pending": len(tasks),
                    "escalated": db.query(OperationsEscalationEvent).filter(OperationsEscalationEvent.organization_id == organization_id).count(),
                    "handoff_pending": db.query(OperationsHandoffEvent).filter(
                        OperationsHandoffEvent.organization_id == organization_id,
                        OperationsHandoffEvent.stage == "handoff_pending",
                    ).count(),
                },
                "tasks": [],
                "advisory_only": True,
                "execution_disabled": True,
                "autonomous_execution": False,
                "append_only": True,
                "replay_safe": True,
            }

        visible_tasks = [task for task in tasks if task.task_id in visible_task_ids]
        assignments = (
            db.query(OperationsAssignmentEvent)
            .filter(OperationsAssignmentEvent.organization_id == organization_id)
            .order_by(OperationsAssignmentEvent.sequence.desc())
            .all()
        )
        escalations = (
            db.query(OperationsEscalationEvent)
            .filter(OperationsEscalationEvent.organization_id == organization_id)
            .order_by(OperationsEscalationEvent.sequence.desc())
            .all()
        )
        acknowledgements = (
            db.query(OperationsAcknowledgementEvent)
            .filter(OperationsAcknowledgementEvent.organization_id == organization_id)
            .order_by(OperationsAcknowledgementEvent.sequence.desc())
            .all()
        )
        handoffs = (
            db.query(OperationsHandoffEvent)
            .filter(OperationsHandoffEvent.organization_id == organization_id)
            .order_by(OperationsHandoffEvent.sequence.desc())
            .all()
        )

        assign_map: dict[str, OperationsAssignmentEvent] = {}
        for row in assignments:
            if row.task_id not in assign_map:
                assign_map[row.task_id] = row

        escalation_map: dict[str, OperationsEscalationEvent] = {}
        for row in escalations:
            if row.task_id not in escalation_map:
                escalation_map[row.task_id] = row

        ack_map: dict[str, OperationsAcknowledgementEvent] = {}
        for row in acknowledgements:
            if row.task_id not in ack_map:
                ack_map[row.task_id] = row

        handoff_map: dict[str, OperationsHandoffEvent] = {}
        for row in handoffs:
            if row.task_id not in handoff_map:
                handoff_map[row.task_id] = row

        inbox = []
        for task in visible_tasks[:200]:
            ass = assign_map.get(task.task_id)
            esc = escalation_map.get(task.task_id)
            ack = ack_map.get(task.task_id)
            hof = handoff_map.get(task.task_id)
            inbox.append(
                {
                    "task_id": task.task_id,
                    "title": task.title,
                    "priority": task.priority,
                    "category": task.category,
                    "assigned_to": ass.assigned_to if ass else None,
                    "assigned_to_role": ass.assigned_to_role if ass else None,
                    "escalation_level": esc.escalation_level if esc else None,
                    "last_acknowledged_by": ack.actor_id if ack else None,
                    "handoff_stage": hof.stage if hof else "queued",
                    "immutable_audit_ref": task.immutable_audit_ref,
                    "created_at": _iso_utc(task.created_at),
                }
            )

        return {
            "role_view": actor.role,
            "task_count": len(inbox),
            "masked": False,
            "queue_health": {
                "pending": len(inbox),
                "escalated": len([row for row in inbox if row.get("escalation_level")]),
                "handoff_pending": len([row for row in inbox if row.get("handoff_stage") == "handoff_pending"]),
                "acknowledged": len([row for row in inbox if row.get("last_acknowledged_by")]),
            },
            "tasks": inbox,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_timeline_projection(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        after_sequence: int,
        limit: int,
    ) -> dict[str, Any]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)

        events: list[dict[str, Any]] = []

        assignment_rows = (
            db.query(OperationsAssignmentEvent)
            .filter(OperationsAssignmentEvent.organization_id == organization_id, OperationsAssignmentEvent.sequence > after_sequence)
            .order_by(OperationsAssignmentEvent.sequence.asc())
            .limit(limit)
            .all()
        )
        for row in assignment_rows:
            if actor.role != ROLE_MEDICAL_COORDINATOR and row.task_id not in visible_task_ids:
                continue
            events.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "task_id": row.task_id,
                    "event_type": "assignment",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                }
            )

        escalation_rows = (
            db.query(OperationsEscalationEvent)
            .filter(OperationsEscalationEvent.organization_id == organization_id, OperationsEscalationEvent.sequence > after_sequence)
            .order_by(OperationsEscalationEvent.sequence.asc())
            .limit(limit)
            .all()
        )
        for row in escalation_rows:
            if actor.role != ROLE_MEDICAL_COORDINATOR and row.task_id not in visible_task_ids:
                continue
            events.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "task_id": row.task_id,
                    "event_type": "escalation",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                }
            )

        handoff_rows = (
            db.query(OperationsHandoffEvent)
            .filter(OperationsHandoffEvent.organization_id == organization_id, OperationsHandoffEvent.sequence > after_sequence)
            .order_by(OperationsHandoffEvent.sequence.asc())
            .limit(limit)
            .all()
        )
        for row in handoff_rows:
            if actor.role != ROLE_MEDICAL_COORDINATOR and row.task_id not in visible_task_ids:
                continue
            events.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "task_id": row.task_id,
                    "event_type": "handoff",
                    "stage": row.stage,
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                }
            )

        ack_rows = (
            db.query(OperationsAcknowledgementEvent)
            .filter(OperationsAcknowledgementEvent.organization_id == organization_id, OperationsAcknowledgementEvent.sequence > after_sequence)
            .order_by(OperationsAcknowledgementEvent.sequence.asc())
            .limit(limit)
            .all()
        )
        for row in ack_rows:
            if actor.role != ROLE_MEDICAL_COORDINATOR and row.task_id not in visible_task_ids:
                continue
            events.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "task_id": row.task_id,
                    "event_type": "acknowledgement",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                }
            )

        events = sorted(events, key=lambda item: int(item.get("sequence", 0)))[:limit]
        next_cursor = max([int(item.get("sequence", 0)) for item in events], default=after_sequence)

        if actor.role == ROLE_MEDICAL_COORDINATOR:
            masked = []
            for row in events:
                masked.append(
                    {
                        "sequence": row.get("sequence"),
                        "event_id": row.get("event_id"),
                        "task_id": "masked",
                        "event_type": row.get("event_type"),
                        "timestamp": row.get("timestamp"),
                        "immutable_audit_ref": row.get("immutable_audit_ref"),
                        "correlation_id": row.get("correlation_id"),
                        "masked": True,
                    }
                )
            events = masked

        return {
            "role_view": actor.role,
            "after_sequence": after_sequence,
            "next_cursor": next_cursor,
            "events": events,
            "ordering": "sequence_ascending",
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def notification_feed(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        limit: int,
    ) -> dict[str, Any]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)
        rows = (
            db.query(OperationsNotificationEvent)
            .filter(OperationsNotificationEvent.organization_id == organization_id)
            .order_by(OperationsNotificationEvent.sequence.desc())
            .limit(limit)
            .all()
        )

        entries = []
        for row in rows:
            if actor.role != ROLE_MEDICAL_COORDINATOR and row.task_id not in visible_task_ids:
                continue
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.event_id,
                    "task_id": "masked" if actor.role == ROLE_MEDICAL_COORDINATOR else row.task_id,
                    "notification_type": row.notification_type,
                    "message": "masked" if actor.role == ROLE_MEDICAL_COORDINATOR else row.message,
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                }
            )

        return {
            "role_view": actor.role,
            "notifications": entries,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def _replay_historical_entries(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
    ) -> list[dict[str, Any]]:
        visible_task_ids = OperationsOrchestrationService._visible_task_ids(db, organization_id, actor)
        entries = OperationsOrchestrationService._collect_live_events(
            db,
            organization_id=organization_id,
            actor=actor,
            visible_task_ids=visible_task_ids,
        )

        def _mask_payload(payload: dict[str, Any]) -> dict[str, Any]:
            masked = dict(payload)
            if actor.role == ROLE_MEDICAL_COORDINATOR and masked.get("task_id"):
                masked["task_id"] = "masked"
            return masked

        for row in (
            db.query(OperationsReplaySession)
            .filter(OperationsReplaySession.organization_id == organization_id)
            .order_by(OperationsReplaySession.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.replay_session_id,
                    "task_id": None,
                    "event_type": "replay_session",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(
                        {
                            "session_name": row.session_name,
                            "source_after_sequence": row.source_after_sequence,
                            "source_until_sequence": row.source_until_sequence,
                            "scenario_id": row.scenario_id,
                            "replay_session_id": row.replay_session_id,
                        }
                    ),
                }
            )

        for row in (
            db.query(OperationsReplayFrame)
            .filter(OperationsReplayFrame.organization_id == organization_id)
            .order_by(OperationsReplayFrame.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.replay_frame_id,
                    "task_id": None,
                    "event_type": row.source_event_type,
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload({**json.loads(row.payload_json), "replay_session_id": row.replay_session_id}),
                }
            )

        for row in (
            db.query(OperationsSimulationScenario)
            .filter(OperationsSimulationScenario.organization_id == organization_id)
            .order_by(OperationsSimulationScenario.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.scenario_id,
                    "task_id": None,
                    "event_type": "simulation_scenario",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(
                        {
                            "scenario_name": row.scenario_name,
                            "scenario_type": row.scenario_type,
                            "baseline_window": row.baseline_window,
                            "hypothesis": row.hypothesis,
                        }
                    ),
                }
            )

        for row in (
            db.query(OperationsSimulationProjection)
            .filter(OperationsSimulationProjection.organization_id == organization_id)
            .order_by(OperationsSimulationProjection.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.projection_event_id,
                    "task_id": None,
                    "event_type": row.projection_type,
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(json.loads(row.projection_json)),
                }
            )

        for row in (
            db.query(OperationsTimelineBranch)
            .filter(OperationsTimelineBranch.organization_id == organization_id)
            .order_by(OperationsTimelineBranch.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.branch_event_id,
                    "task_id": None,
                    "event_type": "timeline_branch",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(
                        {
                            "branch_id": row.branch_id,
                            "branch_name": row.branch_name,
                            "branch_type": row.branch_type,
                            "base_checksum": row.base_checksum,
                            "branch_checksum": row.branch_checksum,
                            "scenario_id": row.scenario_id,
                        }
                    ),
                }
            )

        for row in (
            db.query(OperationsForecastComparison)
            .filter(OperationsForecastComparison.organization_id == organization_id)
            .order_by(OperationsForecastComparison.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.comparison_event_id,
                    "task_id": None,
                    "event_type": "forecast_comparison",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(
                        {
                            "comparison_metric": row.comparison_metric,
                            "baseline_value": row.baseline_value,
                            "simulated_value": row.simulated_value,
                            "delta_value": row.delta_value,
                            "comparison_status": row.comparison_status,
                        }
                    ),
                }
            )

        for row in (
            db.query(OperationsContinuitySimulation)
            .filter(OperationsContinuitySimulation.organization_id == organization_id)
            .order_by(OperationsContinuitySimulation.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.continuity_simulation_id,
                    "task_id": None,
                    "event_type": "continuity_simulation",
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(
                        {
                            "continuity_state": row.continuity_state,
                            "continuity_score": row.continuity_score,
                            "scenario_id": row.scenario_id,
                            "validation_checksum": row.validation_checksum,
                        }
                    ),
                }
            )

        for row in (
            db.query(OperationsReplayEvidenceEvent)
            .filter(OperationsReplayEvidenceEvent.organization_id == organization_id)
            .order_by(OperationsReplayEvidenceEvent.sequence.asc())
            .all()
        ):
            entries.append(
                {
                    "sequence": row.sequence,
                    "event_id": row.evidence_event_id,
                    "task_id": None,
                    "event_type": row.evidence_type,
                    "actor_role": row.actor_role,
                    "timestamp": _iso_utc(row.created_at),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "correlation_id": row.correlation_id,
                    "replay_lineage_ref": row.replay_lineage_ref,
                    "payload": _mask_payload(json.loads(row.evidence_payload_json)),
                }
            )

        return sorted(entries, key=_event_sort_key)

    @staticmethod
    def _persist_replay_evidence(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str,
        evidence_type: str,
        payload: dict[str, Any],
        correlation_id: str,
        replay_parent_event_id: str | None = None,
        replay_lineage_ref: str | None = None,
    ) -> OperationsReplayEvidenceEvent:
        row = OperationsReplayEvidenceEvent(
            sequence=_next_sequence(db, OperationsReplayEvidenceEvent),
            evidence_event_id=f"replay-evidence-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            evidence_type=evidence_type,
            evidence_checksum=_checksum_payload(payload),
            evidence_payload_json=json_dumps(payload),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=replay_parent_event_id,
            replay_lineage_ref=replay_lineage_ref or f"replay-lineage-{replay_session_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-replay-evidence-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        return row

    @staticmethod
    def create_replay_session(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER}, "role is not allowed to create replay sessions")
        session_name = _require_reason(payload.get("session_name"), "session_name")
        after_sequence = int(payload.get("after_sequence") or 0)
        limit = max(1, min(int(payload.get("limit") or 120), 500))
        scenario_id = str(payload.get("scenario_id") or "").strip() or None

        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        filtered = [row for row in entries if int(row.get("sequence") or 0) > after_sequence]
        filtered = filtered[:limit]
        source_until_sequence = max([int(row.get("sequence") or 0) for row in filtered], default=after_sequence)

        session_row = OperationsReplaySession(
            sequence=_next_sequence(db, OperationsReplaySession),
            replay_session_id=f"replay-session-{_short_uuid()}",
            organization_id=organization_id,
            session_name=session_name,
            source_after_sequence=after_sequence,
            source_until_sequence=source_until_sequence,
            scenario_id=scenario_id,
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_lineage_ref=f"replay-session-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-replay-session-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(session_row)

        frames: list[dict[str, Any]] = []
        next_frame_seq = _next_sequence(db, OperationsReplayFrame)
        for idx, row in enumerate(filtered, start=1):
            payload_json = json_dumps(row.get("payload") or {})
            frame_row = OperationsReplayFrame(
                sequence=next_frame_seq,
                replay_frame_id=f"replay-frame-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=session_row.replay_session_id,
                source_event_id=str(row.get("event_id") or "unknown"),
                source_event_type=str(row.get("event_type") or "historical"),
                frame_order=idx,
                payload_json=payload_json,
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=str(row.get("event_id") or None),
                replay_lineage_ref=session_row.replay_lineage_ref,
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-replay-frame-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(frame_row)
            frames.append(
                {
                    "frame_order": idx,
                    "replay_frame_id": frame_row.replay_frame_id,
                    "source_event_id": frame_row.source_event_id,
                    "source_event_type": frame_row.source_event_type,
                    "payload": json.loads(frame_row.payload_json),
                    "timestamp": _iso_utc(frame_row.created_at),
                    "immutable_audit_ref": frame_row.immutable_audit_ref,
                    "replay_lineage_ref": frame_row.replay_lineage_ref,
                }
            )
            next_frame_seq += 1

        evidence_row = OperationsOrchestrationService._persist_replay_evidence(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=session_row.replay_session_id,
            evidence_type="replay_session",
            payload={
                "session_name": session_name,
                "source_after_sequence": after_sequence,
                "source_until_sequence": source_until_sequence,
                "frame_count": len(frames),
                "scenario_id": scenario_id,
            },
            correlation_id=correlation_id,
            replay_parent_event_id=session_row.replay_session_id,
            replay_lineage_ref=session_row.replay_lineage_ref,
        )
        db.commit()

        return {
            "replay_session_id": session_row.replay_session_id,
            "session_name": session_row.session_name,
            "scenario_id": session_row.scenario_id,
            "source_after_sequence": session_row.source_after_sequence,
            "source_until_sequence": session_row.source_until_sequence,
            "frame_count": len(frames),
            "frames": frames,
            "immutable_audit_ref": session_row.immutable_audit_ref,
            "replay_lineage_ref": session_row.replay_lineage_ref,
            "evidence_event_id": evidence_row.evidence_event_id,
            "timestamp": _iso_utc(session_row.created_at),
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def reconstruct_operational_timeline(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        after_sequence: int,
        limit: int,
    ) -> dict[str, Any]:
        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        filtered = [row for row in entries if int(row.get("sequence") or 0) > after_sequence]
        filtered = filtered[:limit]
        next_cursor = max([int(row.get("sequence") or 0) for row in filtered], default=after_sequence)
        return {
            "role_view": actor.role,
            "after_sequence": after_sequence,
            "next_cursor": next_cursor,
            "ordering": "deterministic_timestamp_eventid_ascending",
            "events": filtered,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def create_simulation_scenario(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER}, "role is not allowed to create simulation scenarios")
        scenario_name = _require_reason(payload.get("scenario_name"), "scenario_name")
        hypothesis = _require_reason(payload.get("hypothesis"), "hypothesis")
        scenario_type = str(payload.get("scenario_type") or "operational_replay").strip().lower()
        baseline_window = str(payload.get("baseline_window") or "historical").strip().lower()

        row = OperationsSimulationScenario(
            sequence=_next_sequence(db, OperationsSimulationScenario),
            scenario_id=f"simulation-scenario-{_short_uuid()}",
            organization_id=organization_id,
            scenario_name=scenario_name,
            scenario_type=scenario_type,
            baseline_window=baseline_window,
            hypothesis=hypothesis,
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_lineage_ref=f"simulation-scenario-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-simulation-scenario-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        evidence_row = OperationsOrchestrationService._persist_replay_evidence(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=row.scenario_id,
            evidence_type="simulation_scenario",
            payload={
                "scenario_name": scenario_name,
                "scenario_type": scenario_type,
                "baseline_window": baseline_window,
                "hypothesis": hypothesis,
            },
            correlation_id=correlation_id,
            replay_parent_event_id=None,
            replay_lineage_ref=row.replay_lineage_ref,
        )
        db.commit()
        return {
            "scenario_id": row.scenario_id,
            "scenario_name": row.scenario_name,
            "scenario_type": row.scenario_type,
            "baseline_window": row.baseline_window,
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "evidence_event_id": evidence_row.evidence_event_id,
            "timestamp": _iso_utc(row.created_at),
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_timeline_branch(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> dict[str, Any]:
        _must_have_role(actor, {ROLE_ADMIN, ROLE_SUPERVISOR, ROLE_COMPLIANCE_OFFICER}, "role is not allowed to generate timeline branches")
        replay_session_id = _require_reason(payload.get("replay_session_id"), "replay_session_id")
        branch_name = _require_reason(payload.get("branch_name"), "branch_name")
        branch_type = str(payload.get("branch_type") or "deterministic_replay").strip().lower()
        scenario_id = str(payload.get("scenario_id") or "").strip() or None

        session_row = (
            db.query(OperationsReplaySession)
            .filter(
                OperationsReplaySession.organization_id == organization_id,
                OperationsReplaySession.replay_session_id == replay_session_id,
            )
            .first()
        )
        if session_row is None:
            raise HTTPException(status_code=404, detail="replay session not found")

        frames = (
            db.query(OperationsReplayFrame)
            .filter(
                OperationsReplayFrame.organization_id == organization_id,
                OperationsReplayFrame.replay_session_id == replay_session_id,
            )
            .order_by(OperationsReplayFrame.frame_order.asc())
            .all()
        )
        base_checksum = _checksum_payload([json.loads(row.payload_json) for row in frames])
        branch_payload = {
            "branch_name": branch_name,
            "branch_type": branch_type,
            "scenario_id": scenario_id,
            "replay_session_id": replay_session_id,
            "frame_count": len(frames),
            "base_checksum": base_checksum,
        }
        branch_checksum = _checksum_payload(branch_payload)
        row = OperationsTimelineBranch(
            sequence=_next_sequence(db, OperationsTimelineBranch),
            branch_event_id=f"timeline-branch-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            branch_id=f"branch-{_short_uuid()}",
            branch_name=branch_name,
            branch_type=branch_type,
            branch_order=len(frames),
            base_checksum=base_checksum,
            branch_checksum=branch_checksum,
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=session_row.replay_session_id,
            replay_lineage_ref=f"timeline-branch-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-timeline-branch-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        evidence_row = OperationsOrchestrationService._persist_replay_evidence(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
            evidence_type="timeline_branch",
            payload=branch_payload,
            correlation_id=correlation_id,
            replay_parent_event_id=row.branch_event_id,
            replay_lineage_ref=row.replay_lineage_ref,
        )
        db.commit()
        return {
            "branch_id": row.branch_id,
            "branch_name": row.branch_name,
            "branch_type": row.branch_type,
            "scenario_id": row.scenario_id,
            "replay_session_id": row.replay_session_id,
            "base_checksum": row.base_checksum,
            "branch_checksum": row.branch_checksum,
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "evidence_event_id": evidence_row.evidence_event_id,
            "timestamp": _iso_utc(row.created_at),
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_replay_projection(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        after_sequence: int,
        limit: int,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        if replay_session_id:
            filtered_base = [
                row for row in entries
                if str(row.get("event_id") or "") == replay_session_id
                or str((row.get("payload") or {}).get("replay_session_id") or "") == replay_session_id
                or str((row.get("payload") or {}).get("session_id") or "") == replay_session_id
            ]
        else:
            filtered_base = entries
        filtered = [row for row in filtered_base if int(row.get("sequence") or 0) > after_sequence]
        filtered = filtered[:limit]
        persisted: list[dict[str, Any]] = []
        next_seq = _next_sequence(db, OperationsSimulationProjection)
        for idx, row in enumerate(filtered, start=1):
            projection_payload = {
                "source_event_id": row.get("event_id"),
                "source_event_type": row.get("event_type"),
                "advisory_projection": True,
                "summary": row.get("payload") or {},
                "replay_session_id": replay_session_id,
            }
            persisted_row = OperationsSimulationProjection(
                sequence=next_seq,
                projection_event_id=f"simulation-projection-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id or "unscoped-replay",
                scenario_id=str((row.get("payload") or {}).get("scenario_id") or "").strip() or None,
                frame_id=str(row.get("event_id") or "").strip() or None,
                projection_order=after_sequence + idx,
                projection_type="replay_projection",
                projection_json=json_dumps(projection_payload),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=str(row.get("event_id") or None),
                replay_lineage_ref=f"replay-projection-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-simulation-projection-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(persisted_row)
            persisted.append(
                {
                    "projection_sequence": persisted_row.projection_order,
                    "projection_event_id": persisted_row.projection_event_id,
                    "source_event_id": persisted_row.frame_id,
                    "source_event_type": row.get("event_type"),
                    "payload": json.loads(persisted_row.projection_json),
                    "timestamp": _iso_utc(persisted_row.created_at),
                    "immutable_audit_ref": persisted_row.immutable_audit_ref,
                }
            )
            next_seq += 1
        db.commit()
        return {
            "role_view": actor.role,
            "after_sequence": after_sequence,
            "next_cursor": max([int(row.get("sequence") or 0) for row in filtered], default=after_sequence),
            "ordering": "deterministic_timestamp_eventid_ascending",
            "events": persisted,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def compare_forecast_outcomes(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        visible = entries if replay_session_id is None else [
            row for row in entries
            if str(row.get("event_id") or "") == replay_session_id
            or str((row.get("payload") or {}).get("replay_session_id") or "") == replay_session_id
            or str((row.get("payload") or {}).get("session_id") or "") == replay_session_id
        ]
        baseline_event_count = float(len(visible))
        baseline_handoffs = float(len([row for row in visible if row.get("event_type") == "handoff" or row.get("event_type") == "timeline_branch"]))
        simulated_event_count = float(len([row for row in visible if row.get("event_type") not in {"replay_evidence", "simulation_scenario"}]))
        simulated_handoffs = float(len([row for row in visible if row.get("event_type") in {"timeline_branch", "simulation_scenario"}]))

        comparisons = []
        next_seq = _next_sequence(db, OperationsForecastComparison)
        for metric, baseline_value, simulated_value in [
            ("event_volume", baseline_event_count, simulated_event_count),
            ("handoff_volume", baseline_handoffs, simulated_handoffs),
        ]:
            delta = simulated_value - baseline_value
            row = OperationsForecastComparison(
                sequence=next_seq,
                comparison_event_id=f"forecast-comparison-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id or "unscoped-replay",
                scenario_id=None,
                comparison_metric=metric,
                baseline_value=baseline_value,
                simulated_value=simulated_value,
                delta_value=delta,
                comparison_status="advisory" if delta == 0 else "review",
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"forecast-comparison-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-forecast-comparison-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            comparisons.append(
                {
                    "comparison_metric": metric,
                    "baseline_value": baseline_value,
                    "simulated_value": simulated_value,
                    "delta_value": delta,
                    "comparison_status": row.comparison_status,
                    "immutable_audit_ref": row.immutable_audit_ref,
                }
            )
            next_seq += 1
        evidence_row = OperationsOrchestrationService._persist_replay_evidence(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id or "unscoped-replay",
            evidence_type="forecast_comparison",
            payload={"replay_session_id": replay_session_id, "comparisons": comparisons},
            correlation_id=correlation_id,
            replay_lineage_ref=f"forecast-comparison-lineage-{organization_id}",
        )
        db.commit()
        return {
            "role_view": actor.role,
            "comparisons": comparisons,
            "evidence_event_id": evidence_row.evidence_event_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_continuity_simulation(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        filtered = entries if replay_session_id is None else [
            row for row in entries
            if str(row.get("event_id") or "") == replay_session_id
            or str((row.get("payload") or {}).get("replay_session_id") or "") == replay_session_id
            or str((row.get("payload") or {}).get("session_id") or "") == replay_session_id
        ]
        continuity_score = max(0.0, 100.0 - float(len([row for row in filtered if row.get("event_type") in {"handoff", "timeline_branch", "forecast_comparison"}])) * 5.0)
        continuity_state = "stable" if continuity_score >= 80 else "watch" if continuity_score >= 50 else "degraded"
        validation_checksum = _checksum_payload({"count": len(filtered), "score": continuity_score, "state": continuity_state})
        row = OperationsContinuitySimulation(
            sequence=_next_sequence(db, OperationsContinuitySimulation),
            continuity_simulation_id=f"continuity-simulation-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id or "unscoped-replay",
            scenario_id=None,
            continuity_state=continuity_state,
            continuity_score=continuity_score,
            validation_checksum=validation_checksum,
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"continuity-simulation-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-continuity-simulation-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        evidence_row = OperationsOrchestrationService._persist_replay_evidence(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id or "unscoped-replay",
            evidence_type="continuity_simulation",
            payload={"replay_session_id": replay_session_id, "continuity_state": continuity_state, "continuity_score": continuity_score, "validation_checksum": validation_checksum},
            correlation_id=correlation_id,
            replay_lineage_ref=row.replay_lineage_ref,
        )
        db.commit()
        return {
            "continuity_simulation_id": row.continuity_simulation_id,
            "continuity_state": row.continuity_state,
            "continuity_score": row.continuity_score,
            "validation_checksum": row.validation_checksum,
            "evidence_event_id": evidence_row.evidence_event_id,
            "timestamp": _iso_utc(row.created_at),
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def export_replay_evidence_bundle(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        correlation_id: str,
    ) -> dict[str, Any]:
        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        chain: list[dict[str, Any]] = []
        prior_hash = "GENESIS"
        for row in entries:
            digest = _checksum_payload(
                {
                    "event_id": row.get("event_id"),
                    "event_type": row.get("event_type"),
                    "timestamp": row.get("timestamp"),
                    "prior_hash": prior_hash,
                }
            )
            chain.append({"event_id": row.get("event_id"), "prior_hash": prior_hash, "event_hash": digest})
            prior_hash = digest

        payload = {
            "organization_id": organization_id,
            "generated_at": _iso_utc(now()),
            "generated_by": actor.user_id,
            "generated_by_role": actor.role,
            "replay_events": entries,
            "immutable_chain": chain,
            "chain_tail_hash": prior_hash,
            "replay_reconstruction": {
                "ordering": "deterministic_timestamp_eventid_ascending",
                "event_count": len(entries),
            },
        }
        checksum = _checksum_payload(payload)
        return {
            "bundle_id": f"replay-export-{_short_uuid()}",
            "bundle_checksum": checksum,
            "chain_tail_hash": prior_hash,
            "payload": payload,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def _predictive_scoped_entries(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
    ) -> list[dict[str, Any]]:
        entries = OperationsOrchestrationService._replay_historical_entries(db, organization_id=organization_id, actor=actor)
        if replay_session_id is None:
            return entries
        scoped: list[dict[str, Any]] = []
        for row in entries:
            payload = row.get("payload") or {}
            if (
                str(row.get("event_id") or "") == replay_session_id
                or str(payload.get("replay_session_id") or "") == replay_session_id
                or str(payload.get("session_id") or "") == replay_session_id
            ):
                scoped.append(row)
        return scoped

    @staticmethod
    def _predictive_snapshot(entries: list[dict[str, Any]]) -> dict[str, Any]:
        ordered_entries = sorted(entries, key=_event_sort_key)

        def count_rows(rows: list[dict[str, Any]]) -> dict[str, int]:
            counts: dict[str, int] = {}
            for row in rows:
                event_type = str(row.get("event_type") or "unknown")
                counts[event_type] = counts.get(event_type, 0) + 1
            return counts

        def score_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
            counts = count_rows(rows)
            total = float(len(rows))
            event_type_count = float(len(counts))
            handoff_pressure = float(sum(counts.get(key, 0) for key in ("handoff", "timeline_branch", "cross_region_handoff")))
            escalation_pressure = float(counts.get("escalation", 0) + counts.get("alert", 0))
            resolution_pressure = float(counts.get("resolution", 0) + counts.get("closure_approval", 0))
            governance_score = round(max(0.0, 100.0 - (total * 0.5 + handoff_pressure * 4.0 + escalation_pressure * 7.0 + resolution_pressure * 2.0)), 3)
            constraint_pressure = round(min(100.0, total * 1.5 + handoff_pressure * 8.0 + escalation_pressure * 10.0 + event_type_count * 2.0), 3)
            capacity_pressure = round(min(100.0, total * 2.0 + handoff_pressure * 5.0 + event_type_count), 3)
            risk_score = round(min(100.0, escalation_pressure * 14.0 + handoff_pressure * 8.0 + event_type_count * 2.0), 3)
            anomaly_score = round(min(100.0, escalation_pressure * 10.0 + handoff_pressure * 6.0 + float(sum(1 for value in counts.values() if value > 1)) * 5.0), 3)
            return {
                "counts": counts,
                "total": total,
                "governance_score": governance_score,
                "constraint_pressure": constraint_pressure,
                "capacity_pressure": capacity_pressure,
                "risk_score": risk_score,
                "anomaly_score": anomaly_score,
            }

        midpoint = max(1, len(ordered_entries) // 2) if ordered_entries else 0
        baseline = score_rows(ordered_entries[:midpoint]) if ordered_entries else score_rows([])
        current = score_rows(ordered_entries[midpoint:] or ordered_entries)
        type_counts = count_rows(ordered_entries)
        ordered_type_rows = sorted(type_counts.items(), key=lambda item: (-item[1], item[0]))
        governance_drift = round(abs(float(current["governance_score"]) - float(baseline["governance_score"])) + abs(float(current["constraint_pressure"]) - float(baseline["constraint_pressure"])) + abs(float(current["risk_score"]) - float(baseline["risk_score"])), 3)
        return {
            "event_count": len(ordered_entries),
            "type_counts": type_counts,
            "ordered_type_rows": ordered_type_rows,
            "baseline": baseline,
            "current": current,
            "governance_score": float(current["governance_score"]),
            "constraint_pressure": float(current["constraint_pressure"]),
            "capacity_pressure": float(current["capacity_pressure"]),
            "risk_score": float(current["risk_score"]),
            "anomaly_score": float(current["anomaly_score"]),
            "governance_drift": governance_drift,
            "baseline_governance_score": float(baseline["governance_score"]),
            "baseline_constraint_pressure": float(baseline["constraint_pressure"]),
            "baseline_risk_score": float(baseline["risk_score"]),
            "governance_trend": round(float(current["governance_score"]) - float(baseline["governance_score"]), 3),
            "constraint_trend": round(float(current["constraint_pressure"]) - float(baseline["constraint_pressure"]), 3),
            "risk_trend": round(float(current["risk_score"]) - float(baseline["risk_score"]), 3),
            "anomaly_trend": round(float(current["anomaly_score"]) - float(baseline["anomaly_score"]), 3),
        }

    @staticmethod
    def _status_band(score: float) -> str:
        if score >= 80.0:
            return "stable"
        if score >= 50.0:
            return "watch"
        return "degraded"

    @staticmethod
    def _risk_band(score: float) -> str:
        if score >= 80.0:
            return "critical"
        if score >= 60.0:
            return "elevated"
        if score >= 35.0:
            return "moderate"
        return "low"

    @staticmethod
    def _drift_band(score: float) -> str:
        if score <= 15.0:
            return "stable"
        if score <= 40.0:
            return "watch"
        return "degraded"

    @staticmethod
    def generate_governance_prediction(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        scenario_id: str | None,
        prediction_scope: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        row = OperationsGovernancePrediction(
            sequence=_next_sequence(db, OperationsGovernancePrediction),
            prediction_event_id=f"governance-prediction-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            prediction_scope=prediction_scope,
            governance_score=float(snapshot["governance_score"]),
            prediction_label=OperationsOrchestrationService._status_band(float(snapshot["governance_score"])),
            prediction_json=json_dumps({"snapshot": snapshot, "prediction_scope": prediction_scope}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"predictive-governance-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-governance-prediction-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "prediction_event_id": row.prediction_event_id,
            "prediction_order": row.sequence,
            "prediction_scope": row.prediction_scope,
            "governance_score": row.governance_score,
            "prediction_label": row.prediction_label,
            "prediction_json": json.loads(row.prediction_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def analyze_operational_constraints(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        constraint_domain: str,
        scenario_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        profile = OperationsConstraintProfile(
            sequence=_next_sequence(db, OperationsConstraintProfile),
            profile_event_id=f"constraint-profile-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            constraint_domain=constraint_domain,
            constraint_status=OperationsOrchestrationService._status_band(float(snapshot["constraint_pressure"])),
            pressure_score=float(snapshot["constraint_pressure"]),
            profile_json=json_dumps({"snapshot": snapshot, "constraint_domain": constraint_domain}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"predictive-constraint-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-constraint-profile-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(profile)

        projections: list[OperationsConstraintViolationProjection] = []
        source_rows = snapshot["ordered_type_rows"][:3] or [(constraint_domain, 0)]
        next_seq = _next_sequence(db, OperationsConstraintViolationProjection)
        for rank, (constraint_name, count_value) in enumerate(source_rows, start=1):
            probability = round(min(100.0, float(snapshot["constraint_pressure"]) + float(count_value) * 5.0 + rank * 3.0), 3)
            row = OperationsConstraintViolationProjection(
                sequence=next_seq,
                violation_projection_event_id=f"constraint-violation-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=scenario_id,
                constraint_name=str(constraint_name),
                violation_probability=probability,
                mitigation_priority="critical" if probability >= 80.0 else "high" if probability >= 60.0 else "review",
                projection_json=json_dumps({"constraint_domain": constraint_domain, "snapshot": snapshot, "constraint_name": constraint_name, "rank": rank}),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=profile.replay_lineage_ref,
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-constraint-violation-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            projections.append(row)
            next_seq += 1

        db.commit()
        return {
            "constraint_profile_id": profile.profile_event_id,
            "constraint_domain": profile.constraint_domain,
            "constraint_status": profile.constraint_status,
            "pressure_score": profile.pressure_score,
            "constraint_profile": json.loads(profile.profile_json),
            "constraint_violation_projections": [
                {
                    "violation_projection_event_id": row.violation_projection_event_id,
                    "constraint_name": row.constraint_name,
                    "violation_probability": row.violation_probability,
                    "mitigation_priority": row.mitigation_priority,
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(projections, key=lambda item: (item.sequence, item.violation_projection_event_id))
            ],
            "timestamp": _iso_utc(profile.created_at),
            "immutable_audit_ref": profile.immutable_audit_ref,
            "replay_lineage_ref": profile.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_capacity_prediction(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        capacity_scope: str,
        scenario_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        pressure = float(snapshot["capacity_pressure"])
        row = OperationsCapacityPrediction(
            sequence=_next_sequence(db, OperationsCapacityPrediction),
            capacity_prediction_event_id=f"capacity-prediction-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            capacity_scope=capacity_scope,
            projected_capacity=round(max(0.0, 100.0 - pressure), 3),
            pressure_score=pressure,
            prediction_json=json_dumps({"snapshot": snapshot, "capacity_scope": capacity_scope}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"predictive-capacity-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-capacity-prediction-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "capacity_prediction_event_id": row.capacity_prediction_event_id,
            "capacity_scope": row.capacity_scope,
            "projected_capacity": row.projected_capacity,
            "pressure_score": row.pressure_score,
            "capacity_prediction": json.loads(row.prediction_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_risk_projection(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        risk_domain: str,
        scenario_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        risk_score = float(snapshot["risk_score"])
        row = OperationsRiskForecast(
            sequence=_next_sequence(db, OperationsRiskForecast),
            risk_forecast_event_id=f"risk-forecast-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            risk_domain=risk_domain,
            risk_level=OperationsOrchestrationService._risk_band(risk_score),
            risk_score=risk_score,
            forecast_json=json_dumps({"snapshot": snapshot, "risk_domain": risk_domain}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"predictive-risk-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-risk-forecast-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "risk_forecast_event_id": row.risk_forecast_event_id,
            "risk_domain": row.risk_domain,
            "risk_level": row.risk_level,
            "risk_score": row.risk_score,
            "risk_forecast": json.loads(row.forecast_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def detect_governance_drift(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        drift_rows: list[OperationsGovernanceDriftEvent] = []
        next_seq = _next_sequence(db, OperationsGovernanceDriftEvent)
        for rank, (dimension, score) in enumerate(
            [
                ("governance", float(snapshot["governance_drift"])),
                ("constraint", abs(float(snapshot["constraint_trend"]))),
                ("risk", abs(float(snapshot["risk_trend"]))),
            ],
            start=1,
        ):
            row = OperationsGovernanceDriftEvent(
                sequence=next_seq,
                drift_event_id=f"governance-drift-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=None,
                drift_dimension=dimension,
                drift_score=round(score, 3),
                drift_status=OperationsOrchestrationService._drift_band(score),
                drift_json=json_dumps({"snapshot": snapshot, "dimension": dimension, "rank": rank}),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"predictive-drift-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-governance-drift-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            drift_rows.append(row)
            next_seq += 1
        db.commit()
        return {
            "drift_events": [
                {
                    "drift_event_id": row.drift_event_id,
                    "drift_dimension": row.drift_dimension,
                    "drift_score": row.drift_score,
                    "drift_status": row.drift_status,
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(drift_rows, key=lambda item: (item.drift_score, item.sequence, item.drift_dimension), reverse=True)
            ],
            "snapshot": snapshot,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_optimization_recommendations(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        recommendation_inputs = [
            ("constraint_pressure", float(snapshot["constraint_pressure"]), "reduce_constraint_pressure", "Reduce constraint pressure by widening supervised thresholds and sequencing handoffs.", "constraint_safe"),
            ("risk_pressure", float(snapshot["risk_score"]), "reduce_risk_concentration", "Flatten risk concentration by rebalancing advisory review queues.", "risk_safe"),
            ("governance_drift", float(snapshot["governance_drift"]), "stabilize_governance_trend", "Stabilize governance drift by keeping advisory review cadence consistent.", "governance_safe"),
        ]
        ordered_inputs = sorted(recommendation_inputs, key=lambda item: (-item[1], item[0]))
        rows: list[OperationsOptimizationRecommendation] = []
        next_seq = _next_sequence(db, OperationsOptimizationRecommendation)
        for rank, (metric_name, metric_score, recommendation_type, recommendation_title, recommendation_bucket) in enumerate(ordered_inputs, start=1):
            row = OperationsOptimizationRecommendation(
                sequence=next_seq,
                recommendation_event_id=f"optimization-recommendation-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=None,
                recommendation_rank=rank,
                recommendation_type=recommendation_type,
                recommendation_title=recommendation_title,
                recommendation_json=json_dumps({
                    "metric_name": metric_name,
                    "metric_score": metric_score,
                    "recommendation_bucket": recommendation_bucket,
                    "snapshot": snapshot,
                }),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"predictive-recommendation-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-optimization-recommendation-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            rows.append(row)
            next_seq += 1
        db.commit()
        return {
            "recommendations": [
                {
                    "recommendation_event_id": row.recommendation_event_id,
                    "recommendation_rank": row.recommendation_rank,
                    "recommendation_type": row.recommendation_type,
                    "recommendation_title": row.recommendation_title,
                    "recommendation_json": json.loads(row.recommendation_json),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(rows, key=lambda item: (item.recommendation_rank, item.sequence))
            ],
            "snapshot": snapshot,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_anomaly_forecast(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        anomaly_scope: str,
        scenario_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        anomaly_inputs = [
            ("escalation_spike", float(snapshot["current"]["counts"].get("escalation", 0)), float(snapshot["anomaly_score"])),
            ("handoff_congestion", float(snapshot["current"]["counts"].get("handoff", 0) + snapshot["current"]["counts"].get("timeline_branch", 0)), float(snapshot["anomaly_score"]) * 0.9),
            ("governance_density", float(len(snapshot["type_counts"])), float(snapshot["anomaly_score"]) * 0.8),
        ]
        rows: list[OperationsAnomalyForecast] = []
        next_seq = _next_sequence(db, OperationsAnomalyForecast)
        for rank, (anomaly_type, basis_value, anomaly_score) in enumerate(sorted(anomaly_inputs, key=lambda item: (-item[2], item[0])), start=1):
            row = OperationsAnomalyForecast(
                sequence=next_seq,
                anomaly_forecast_event_id=f"anomaly-forecast-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=scenario_id,
                anomaly_type=anomaly_type,
                anomaly_score=round(min(100.0, anomaly_score), 3),
                anomaly_severity=OperationsOrchestrationService._risk_band(anomaly_score),
                forecast_json=json_dumps({"anomaly_scope": anomaly_scope, "basis_value": basis_value, "snapshot": snapshot, "rank": rank}),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"predictive-anomaly-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-anomaly-forecast-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            rows.append(row)
            next_seq += 1
        db.commit()
        return {
            "anomalies": [
                {
                    "anomaly_forecast_event_id": row.anomaly_forecast_event_id,
                    "anomaly_type": row.anomaly_type,
                    "anomaly_score": row.anomaly_score,
                    "anomaly_severity": row.anomaly_severity,
                    "forecast_json": json.loads(row.forecast_json),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(rows, key=lambda item: (item.anomaly_score, item.sequence, item.anomaly_type), reverse=True)
            ],
            "snapshot": snapshot,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_governance_trend_analysis(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        snapshot = OperationsOrchestrationService._predictive_snapshot(
            OperationsOrchestrationService._predictive_scoped_entries(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
            )
        )
        trend_inputs = [
            ("governance_score", float(snapshot["governance_trend"])),
            ("constraint_pressure", float(snapshot["constraint_trend"])),
            ("risk_score", float(snapshot["risk_trend"])),
        ]
        rows: list[OperationsGovernanceTrend] = []
        next_seq = _next_sequence(db, OperationsGovernanceTrend)
        for rank, (trend_metric, trend_slope) in enumerate(sorted(trend_inputs, key=lambda item: (abs(item[1]), item[0]), reverse=True), start=1):
            row = OperationsGovernanceTrend(
                sequence=next_seq,
                trend_event_id=f"governance-trend-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=None,
                trend_metric=trend_metric,
                trend_direction="stable" if abs(trend_slope) < 1.0 else "up" if trend_slope > 0 else "down",
                trend_slope=round(trend_slope, 3),
                trend_json=json_dumps({"snapshot": snapshot, "rank": rank}),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"predictive-trend-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-governance-trend-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            rows.append(row)
            next_seq += 1
        db.commit()
        return {
            "trends": [
                {
                    "trend_event_id": row.trend_event_id,
                    "trend_metric": row.trend_metric,
                    "trend_direction": row.trend_direction,
                    "trend_slope": row.trend_slope,
                    "trend_json": json.loads(row.trend_json),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(rows, key=lambda item: (abs(item.trend_slope), item.trend_metric), reverse=True)
            ],
            "snapshot": snapshot,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def export_predictive_evidence_bundle(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        predictive_rows: list[dict[str, Any]] = []
        predictive_models = [
            (OperationsGovernancePrediction, "governance_prediction", "prediction_event_id", "prediction_json"),
            (OperationsConstraintProfile, "constraint_profile", "profile_event_id", "profile_json"),
            (OperationsRiskForecast, "risk_forecast", "risk_forecast_event_id", "forecast_json"),
            (OperationsCapacityPrediction, "capacity_prediction", "capacity_prediction_event_id", "prediction_json"),
            (OperationsGovernanceDriftEvent, "governance_drift", "drift_event_id", "drift_json"),
            (OperationsOptimizationRecommendation, "optimization_recommendation", "recommendation_event_id", "recommendation_json"),
            (OperationsAnomalyForecast, "anomaly_forecast", "anomaly_forecast_event_id", "forecast_json"),
            (OperationsConstraintViolationProjection, "constraint_violation_projection", "violation_projection_event_id", "projection_json"),
            (OperationsGovernanceTrend, "governance_trend", "trend_event_id", "trend_json"),
        ]
        for model, event_type, id_attr, payload_attr in predictive_models:
            query = db.query(model).filter(model.organization_id == organization_id)
            if replay_session_id is not None:
                query = query.filter(model.replay_session_id == replay_session_id)
            rows = query.order_by(model.created_at.asc(), model.sequence.asc()).all()
            for row in rows:
                predictive_rows.append(
                    {
                        "sequence": row.sequence,
                        "event_id": getattr(row, id_attr),
                        "event_type": event_type,
                        "timestamp": _iso_utc(row.created_at),
                        "immutable_audit_ref": row.immutable_audit_ref,
                        "replay_lineage_ref": row.replay_lineage_ref,
                        "payload": json.loads(getattr(row, payload_attr)),
                    }
                )

        predictive_rows = sorted(predictive_rows, key=_event_sort_key)
        chain: list[dict[str, Any]] = []
        prior_hash = "GENESIS"
        for row in predictive_rows:
            digest = _checksum_payload({"event_id": row.get("event_id"), "event_type": row.get("event_type"), "timestamp": row.get("timestamp"), "prior_hash": prior_hash})
            chain.append({"event_id": row.get("event_id"), "prior_hash": prior_hash, "event_hash": digest})
            prior_hash = digest

        payload = {
            "organization_id": organization_id,
            "generated_at": _iso_utc(now()),
            "generated_by": actor.user_id,
            "generated_by_role": actor.role,
            "predictive_events": predictive_rows,
            "immutable_chain": chain,
            "chain_tail_hash": prior_hash,
            "predictive_reconstruction": {
                "ordering": "deterministic_timestamp_eventid_ascending",
                "event_count": len(predictive_rows),
                "snapshot": OperationsOrchestrationService._predictive_snapshot(predictive_rows),
            },
        }
        checksum = _checksum_payload(payload)
        return {
            "bundle_id": f"predictive-export-{_short_uuid()}",
            "bundle_checksum": checksum,
            "chain_tail_hash": prior_hash,
            "payload": payload,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def _collect_predictive_event_rows(
        db: Session,
        *,
        organization_id: str,
        replay_session_id: str | None,
    ) -> list[dict[str, Any]]:
        predictive_rows: list[dict[str, Any]] = []
        predictive_models = [
            (OperationsGovernancePrediction, "governance_prediction", "prediction_event_id", "prediction_json"),
            (OperationsConstraintProfile, "constraint_profile", "profile_event_id", "profile_json"),
            (OperationsRiskForecast, "risk_forecast", "risk_forecast_event_id", "forecast_json"),
            (OperationsCapacityPrediction, "capacity_prediction", "capacity_prediction_event_id", "prediction_json"),
            (OperationsGovernanceDriftEvent, "governance_drift", "drift_event_id", "drift_json"),
            (OperationsOptimizationRecommendation, "optimization_recommendation", "recommendation_event_id", "recommendation_json"),
            (OperationsAnomalyForecast, "anomaly_forecast", "anomaly_forecast_event_id", "forecast_json"),
            (OperationsConstraintViolationProjection, "constraint_violation_projection", "violation_projection_event_id", "projection_json"),
            (OperationsGovernanceTrend, "governance_trend", "trend_event_id", "trend_json"),
        ]
        for model, event_type, id_attr, payload_attr in predictive_models:
            query = db.query(model).filter(model.organization_id == organization_id)
            if replay_session_id is not None:
                query = query.filter(model.replay_session_id == replay_session_id)
            rows = query.order_by(model.created_at.asc(), model.sequence.asc()).all()
            for row in rows:
                predictive_rows.append(
                    {
                        "sequence": row.sequence,
                        "event_id": getattr(row, id_attr),
                        "event_type": event_type,
                        "timestamp": _iso_utc(row.created_at),
                        "immutable_audit_ref": row.immutable_audit_ref,
                        "replay_lineage_ref": row.replay_lineage_ref,
                        "payload": json.loads(getattr(row, payload_attr)),
                    }
                )
        return sorted(predictive_rows, key=_event_sort_key)

    @staticmethod
    def _governance_memory_snapshot(
        replay_entries: list[dict[str, Any]],
        predictive_entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ordered_replay = sorted(replay_entries, key=_event_sort_key)
        ordered_predictive = sorted(predictive_entries, key=_event_sort_key)
        merged = sorted(ordered_replay + ordered_predictive, key=_event_sort_key)

        counts: dict[str, int] = {}
        for row in merged:
            event_type = str(row.get("event_type") or "unknown")
            counts[event_type] = counts.get(event_type, 0) + 1
        ordered_counts = sorted(counts.items(), key=lambda item: (-item[1], item[0]))

        total_count = float(len(merged))
        replay_count = float(len(ordered_replay))
        predictive_count = float(len(ordered_predictive))
        unique_type_count = float(len(counts))
        provenance_score = round(max(0.0, 100.0 - total_count * 0.35 - unique_type_count * 1.5), 3)
        explanation_confidence = round(min(100.0, 45.0 + predictive_count * 3.0 + replay_count * 0.4 + unique_type_count), 3)
        reasoning_depth = int(min(10, max(1, unique_type_count)))
        trend_strength = round(min(100.0, predictive_count * 4.0 + unique_type_count * 2.5), 3)
        determinism_checksum = _checksum_payload(
            [
                {
                    "sequence": row.get("sequence"),
                    "event_id": row.get("event_id"),
                    "event_type": row.get("event_type"),
                    "timestamp": row.get("timestamp"),
                }
                for row in merged
            ]
        )

        return {
            "replay_event_count": int(replay_count),
            "predictive_event_count": int(predictive_count),
            "total_event_count": int(total_count),
            "event_type_counts": counts,
            "ordered_type_rows": ordered_counts,
            "provenance_score": provenance_score,
            "explanation_confidence": explanation_confidence,
            "reasoning_depth": reasoning_depth,
            "trend_strength": trend_strength,
            "determinism_checksum": determinism_checksum,
            "ordering": "deterministic_timestamp_eventid_ascending",
        }

    @staticmethod
    def build_decision_provenance(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        scenario_id: str | None,
        decision_scope: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        status = "traceable" if float(snapshot["provenance_score"]) >= 60.0 else "review"
        row = OperationsDecisionProvenance(
            sequence=_next_sequence(db, OperationsDecisionProvenance),
            provenance_event_id=f"decision-provenance-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            decision_scope=decision_scope,
            provenance_score=float(snapshot["provenance_score"]),
            provenance_status=status,
            provenance_json=json_dumps(
                {
                    "decision_scope": decision_scope,
                    "snapshot": snapshot,
                    "explainable": True,
                    "lineage_preserved": True,
                }
            ),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"governance-provenance-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-governance-provenance-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "provenance_event_id": row.provenance_event_id,
            "decision_scope": row.decision_scope,
            "provenance_score": row.provenance_score,
            "provenance_status": row.provenance_status,
            "provenance": json.loads(row.provenance_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_governance_explanation(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        scenario_id: str | None,
        explanation_scope: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        explanation = OperationsGovernanceExplanation(
            sequence=_next_sequence(db, OperationsGovernanceExplanation),
            explanation_event_id=f"governance-explanation-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            explanation_scope=explanation_scope,
            explanation_confidence=float(snapshot["explanation_confidence"]),
            explanation_json=json_dumps(
                {
                    "summary": "Governance recommendation remains advisory-only and explainable.",
                    "explanation_scope": explanation_scope,
                    "snapshot": snapshot,
                    "constraints": [
                        "execution_disabled",
                        "autonomous_execution_false",
                        "append_only_lineage",
                    ],
                }
            ),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"governance-explanation-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-governance-explanation-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        rationale = OperationsGovernanceRationale(
            sequence=_next_sequence(db, OperationsGovernanceRationale),
            rationale_event_id=f"governance-rationale-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            rationale_type="explanation_support",
            rationale_confidence=float(snapshot["explanation_confidence"]),
            rationale_json=json_dumps(
                {
                    "top_factors": snapshot["ordered_type_rows"][:3],
                    "determinism_checksum": snapshot["determinism_checksum"],
                    "explainable": True,
                }
            ),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=explanation.replay_lineage_ref,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-governance-rationale-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(explanation)
        db.add(rationale)
        db.commit()
        return {
            "explanation_event_id": explanation.explanation_event_id,
            "explanation_scope": explanation.explanation_scope,
            "explanation_confidence": explanation.explanation_confidence,
            "explanation": json.loads(explanation.explanation_json),
            "rationale": {
                "rationale_event_id": rationale.rationale_event_id,
                "rationale_type": rationale.rationale_type,
                "rationale_confidence": rationale.rationale_confidence,
                "rationale_json": json.loads(rationale.rationale_json),
                "timestamp": _iso_utc(rationale.created_at),
            },
            "timestamp": _iso_utc(explanation.created_at),
            "immutable_audit_ref": explanation.immutable_audit_ref,
            "replay_lineage_ref": explanation.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def reconstruct_reasoning_chain(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        scenario_id: str | None,
        reasoning_scope: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        chain = OperationsAdvisoryReasoningChain(
            sequence=_next_sequence(db, OperationsAdvisoryReasoningChain),
            reasoning_chain_event_id=f"reasoning-chain-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            chain_scope=reasoning_scope,
            chain_depth=int(snapshot["reasoning_depth"]),
            chain_json=json_dumps(
                {
                    "reasoning_scope": reasoning_scope,
                    "determinism_checksum": snapshot["determinism_checksum"],
                    "steps": [
                        "collect_immutable_history",
                        "apply_deterministic_ordering",
                        "emit_advisory_explanation",
                    ],
                    "snapshot": snapshot,
                }
            ),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"reasoning-chain-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-reasoning-chain-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(chain)

        rationale_rows: list[OperationsGovernanceRationale] = []
        next_seq = _next_sequence(db, OperationsGovernanceRationale)
        for depth, (event_type, count) in enumerate(snapshot["ordered_type_rows"][:3], start=1):
            row = OperationsGovernanceRationale(
                sequence=next_seq,
                rationale_event_id=f"reasoning-rationale-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=scenario_id,
                rationale_type="reasoning_step",
                rationale_confidence=round(min(100.0, float(snapshot["explanation_confidence"]) - depth), 3),
                rationale_json=json_dumps(
                    {
                        "depth": depth,
                        "event_type": event_type,
                        "event_count": count,
                        "reasoning_scope": reasoning_scope,
                    }
                ),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=chain.replay_lineage_ref,
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-reasoning-rationale-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            rationale_rows.append(row)
            next_seq += 1

        db.commit()
        return {
            "reasoning_chain_event_id": chain.reasoning_chain_event_id,
            "reasoning_scope": chain.chain_scope,
            "chain_depth": chain.chain_depth,
            "reasoning_chain": json.loads(chain.chain_json),
            "rationale_steps": [
                {
                    "rationale_event_id": row.rationale_event_id,
                    "rationale_confidence": row.rationale_confidence,
                    "rationale_json": json.loads(row.rationale_json),
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(rationale_rows, key=lambda item: (item.sequence, item.rationale_event_id))
            ],
            "timestamp": _iso_utc(chain.created_at),
            "immutable_audit_ref": chain.immutable_audit_ref,
            "replay_lineage_ref": chain.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_operational_memory_snapshot(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        scenario_id: str | None,
        memory_window: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        memory_row = OperationsGovernanceMemory(
            sequence=_next_sequence(db, OperationsGovernanceMemory),
            memory_event_id=f"governance-memory-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            memory_window=memory_window,
            memory_density=round(min(100.0, float(snapshot["total_event_count"]) * 1.2 + float(snapshot["reasoning_depth"]) * 3.0), 3),
            memory_json=json_dumps({"memory_window": memory_window, "snapshot": snapshot}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"governance-memory-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-governance-memory-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        historical_row = OperationsHistoricalGovernanceState(
            sequence=_next_sequence(db, OperationsHistoricalGovernanceState),
            historical_state_event_id=f"historical-governance-state-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=scenario_id,
            state_window=memory_window,
            state_score=float(snapshot["provenance_score"]),
            state_json=json_dumps({"snapshot": snapshot, "state_window": memory_window}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=memory_row.replay_lineage_ref,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-historical-governance-state-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(memory_row)
        db.add(historical_row)
        db.commit()
        return {
            "memory_event_id": memory_row.memory_event_id,
            "memory_window": memory_row.memory_window,
            "memory_density": memory_row.memory_density,
            "memory_snapshot": json.loads(memory_row.memory_json),
            "historical_state": {
                "historical_state_event_id": historical_row.historical_state_event_id,
                "state_window": historical_row.state_window,
                "state_score": historical_row.state_score,
                "state_json": json.loads(historical_row.state_json),
                "timestamp": _iso_utc(historical_row.created_at),
            },
            "timestamp": _iso_utc(memory_row.created_at),
            "immutable_audit_ref": memory_row.immutable_audit_ref,
            "replay_lineage_ref": memory_row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def build_recommendation_lineage(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        lineage_steps = [
            {"depth": idx, "event_type": item[0], "weight": item[1]}
            for idx, item in enumerate(snapshot["ordered_type_rows"][:5], start=1)
        ]
        lineage = OperationsRecommendationLineage(
            sequence=_next_sequence(db, OperationsRecommendationLineage),
            recommendation_lineage_event_id=f"recommendation-lineage-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=None,
            lineage_scope="recommendation_traceability",
            lineage_depth=len(lineage_steps),
            lineage_json=json_dumps({"lineage_steps": lineage_steps, "snapshot": snapshot}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"recommendation-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-recommendation-lineage-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        ancestry = OperationsOperationalAncestry(
            sequence=_next_sequence(db, OperationsOperationalAncestry),
            ancestry_event_id=f"recommendation-ancestry-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=None,
            ancestry_scope="recommendation_ancestry",
            ancestry_depth=len(lineage_steps),
            ancestry_json=json_dumps({"lineage_steps": lineage_steps}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=lineage.replay_lineage_ref,
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-recommendation-ancestry-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(lineage)
        db.add(ancestry)
        db.commit()
        return {
            "recommendation_lineage_event_id": lineage.recommendation_lineage_event_id,
            "lineage_scope": lineage.lineage_scope,
            "lineage_depth": lineage.lineage_depth,
            "lineage": json.loads(lineage.lineage_json),
            "ancestry": {
                "ancestry_event_id": ancestry.ancestry_event_id,
                "ancestry_depth": ancestry.ancestry_depth,
                "ancestry_json": json.loads(ancestry.ancestry_json),
                "timestamp": _iso_utc(ancestry.created_at),
            },
            "timestamp": _iso_utc(lineage.created_at),
            "immutable_audit_ref": lineage.immutable_audit_ref,
            "replay_lineage_ref": lineage.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_historical_governance_trace(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        rows: list[OperationsOperationalAncestry] = []
        next_seq = _next_sequence(db, OperationsOperationalAncestry)
        for depth, (scope_name, scope_value) in enumerate(
            [
                ("replay_event_count", snapshot["replay_event_count"]),
                ("predictive_event_count", snapshot["predictive_event_count"]),
                ("determinism_checksum", snapshot["determinism_checksum"]),
            ],
            start=1,
        ):
            row = OperationsOperationalAncestry(
                sequence=next_seq,
                ancestry_event_id=f"historical-ancestry-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=None,
                ancestry_scope=str(scope_name),
                ancestry_depth=depth,
                ancestry_json=json_dumps({"scope_value": scope_value, "snapshot": snapshot}),
                actor_id=actor.user_id,
                actor_role=actor.role,
                replay_parent_event_id=None,
                replay_lineage_ref=f"historical-governance-lineage-{organization_id}",
                correlation_id=correlation_id,
                immutable_audit_ref=f"audit-historical-ancestry-{_short_uuid()}",
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            rows.append(row)
            next_seq += 1
        db.commit()
        return {
            "ancestry_trace": [
                {
                    "ancestry_event_id": row.ancestry_event_id,
                    "ancestry_scope": row.ancestry_scope,
                    "ancestry_depth": row.ancestry_depth,
                    "ancestry_json": json.loads(row.ancestry_json),
                    "immutable_audit_ref": row.immutable_audit_ref,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(rows, key=lambda item: (item.ancestry_depth, item.sequence, item.ancestry_event_id))
            ],
            "snapshot": snapshot,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def aggregate_long_horizon_trends(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        trend_window: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        row = OperationsTrendMemory(
            sequence=_next_sequence(db, OperationsTrendMemory),
            trend_memory_event_id=f"trend-memory-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=None,
            trend_window=trend_window,
            trend_strength=float(snapshot["trend_strength"]),
            trend_memory_json=json_dumps({"trend_window": trend_window, "snapshot": snapshot}),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"trend-memory-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-trend-memory-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "trend_memory_event_id": row.trend_memory_event_id,
            "trend_window": row.trend_window,
            "trend_strength": row.trend_strength,
            "trend_memory": json.loads(row.trend_memory_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def reconstruct_decision_context(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        decision_scope: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        row = OperationsDecisionSnapshot(
            sequence=_next_sequence(db, OperationsDecisionSnapshot),
            decision_snapshot_event_id=f"decision-snapshot-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            scenario_id=None,
            decision_scope=decision_scope,
            snapshot_json=json_dumps(
                {
                    "decision_scope": decision_scope,
                    "snapshot": snapshot,
                    "context_reconstructed": True,
                    "explainable": True,
                }
            ),
            actor_id=actor.user_id,
            actor_role=actor.role,
            replay_parent_event_id=None,
            replay_lineage_ref=f"decision-context-lineage-{organization_id}",
            correlation_id=correlation_id,
            immutable_audit_ref=f"audit-decision-snapshot-{_short_uuid()}",
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "decision_snapshot_event_id": row.decision_snapshot_event_id,
            "decision_scope": row.decision_scope,
            "decision_context": json.loads(row.snapshot_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_policy_matrix(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        constraints = OperationsOrchestrationService._normalize_constraint_weights(
            OperationsOrchestrationService._policy_constraint_catalog()
        )
        constraint_rows: list[OperationsPolicyConstraint] = []
        version_rows: list[OperationsPolicyConstraintVersion] = []
        next_constraint_seq = _next_sequence(db, OperationsPolicyConstraint)
        next_version_seq = _next_sequence(db, OperationsPolicyConstraintVersion)
        for row in constraints:
            ancestry_ref = f"policy-ancestry-{row['policy_id']}"
            rationale_ref = f"policy-rationale-{row['policy_id']}"
            constraint = OperationsPolicyConstraint(
                sequence=next_constraint_seq,
                constraint_event_id=f"policy-constraint-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                scenario_id=None,
                policy_id=str(row["policy_id"]),
                framework_name=str(row["framework_name"]),
                regulation_family=str(row["regulation_family"]),
                policy_category=str(row["policy_category"]),
                rule_code=str(row["rule_code"]),
                severity_weight=float(row["severity_weight"]),
                operational_domain=str(row["operational_domain"]),
                evidence_requirements=json_dumps(row["evidence_requirements"]),
                rationale_template=str(row["rationale_template"]),
                immutable_hash=str(row["immutable_hash"]),
                ancestry_ref=ancestry_ref,
                rationale_segment_ref=rationale_ref,
                correlation_id=correlation_id,
                replay_parent_event_id=None,
                replay_lineage_ref=f"policy-matrix-lineage-{organization_id}",
                immutable_audit_ref=f"audit-policy-constraint-{_short_uuid()}",
                actor_id=actor.user_id,
                actor_role=actor.role,
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            version = OperationsPolicyConstraintVersion(
                sequence=next_version_seq,
                constraint_version_event_id=f"policy-constraint-version-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                policy_id=str(row["policy_id"]),
                version_label="v1",
                version_status="active",
                immutable_hash=str(row["immutable_hash"]),
                rationale_segment_ref=rationale_ref,
                ancestry_ref=ancestry_ref,
                version_payload_json=json_dumps(row),
                correlation_id=correlation_id,
                replay_parent_event_id=None,
                replay_lineage_ref=constraint.replay_lineage_ref,
                immutable_audit_ref=f"audit-policy-constraint-version-{_short_uuid()}",
                actor_id=actor.user_id,
                actor_role=actor.role,
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(constraint)
            db.add(version)
            constraint_rows.append(constraint)
            version_rows.append(version)
            next_constraint_seq += 1
            next_version_seq += 1
        db.commit()
        return {
            "policy_matrix": [
                {
                    "constraint_event_id": row.constraint_event_id,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "regulation_family": row.regulation_family,
                    "policy_category": row.policy_category,
                    "rule_code": row.rule_code,
                    "severity_weight": row.severity_weight,
                    "operational_domain": row.operational_domain,
                    "ancestry_ref": row.ancestry_ref,
                    "rationale_segment_ref": row.rationale_segment_ref,
                    "immutable_hash": row.immutable_hash,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(constraint_rows, key=lambda item: (item.sequence, item.framework_name, item.rule_code))
            ],
            "constraint_versions": [
                {
                    "constraint_version_event_id": row.constraint_version_event_id,
                    "policy_id": row.policy_id,
                    "version_label": row.version_label,
                    "version_status": row.version_status,
                    "immutable_hash": row.immutable_hash,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(version_rows, key=lambda item: (item.sequence, item.policy_id))
            ],
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def map_regulatory_frameworks(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        constraints = OperationsOrchestrationService._normalize_constraint_weights(
            OperationsOrchestrationService._policy_constraint_catalog()
        )
        mappings = OperationsOrchestrationService._collect_framework_mappings(constraints)
        frameworks: list[OperationsRegulatoryFramework] = []
        framework_rows: dict[str, OperationsRegulatoryFramework] = {}
        mapping_rows: list[OperationsFrameworkRuleMapping] = []
        next_framework_seq = _next_sequence(db, OperationsRegulatoryFramework)
        next_mapping_seq = _next_sequence(db, OperationsFrameworkRuleMapping)
        for mapping in mappings:
            framework_name = str(mapping["framework_name"])
            if framework_name not in framework_rows:
                framework = OperationsRegulatoryFramework(
                    sequence=next_framework_seq,
                    framework_event_id=f"regulatory-framework-{_short_uuid()}",
                    organization_id=organization_id,
                    framework_name=framework_name,
                    regulation_family=str(mapping["regulation_family"]),
                    framework_priority=float(mapping["framework_priority"]),
                    framework_payload_json=json_dumps(
                        {
                            "framework_name": framework_name,
                            "regulation_family": mapping["regulation_family"],
                            "priority": mapping["framework_priority"],
                        }
                    ),
                    immutable_hash=_checksum_payload({"framework": framework_name, "family": mapping["regulation_family"]}),
                    ancestry_ref=f"framework-ancestry-{framework_name}",
                    rationale_segment_ref=f"framework-rationale-{framework_name}",
                    correlation_id=correlation_id,
                    replay_lineage_ref=f"framework-mapping-lineage-{organization_id}",
                    immutable_audit_ref=f"audit-regulatory-framework-{_short_uuid()}",
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    advisory_flags=_advisory_flags(actor),
                    created_at=now(),
                )
                db.add(framework)
                framework_rows[framework_name] = framework
                frameworks.append(framework)
                next_framework_seq += 1
            row = OperationsFrameworkRuleMapping(
                sequence=next_mapping_seq,
                framework_rule_mapping_event_id=f"framework-rule-mapping-{_short_uuid()}",
                organization_id=organization_id,
                policy_id=str(mapping["policy_id"]),
                framework_name=framework_name,
                regulation_family=str(mapping["regulation_family"]),
                rule_code=str(mapping["rule_code"]),
                operational_domain=str(mapping["operational_domain"]),
                evidence_requirements=json_dumps(mapping["evidence_requirements"]),
                mapping_payload_json=json_dumps(mapping),
                immutable_hash=_checksum_payload(mapping),
                ancestry_ref=f"policy-ancestry-{mapping['policy_id']}",
                rationale_segment_ref=f"policy-rationale-{mapping['policy_id']}",
                correlation_id=correlation_id,
                replay_lineage_ref=framework_rows[framework_name].replay_lineage_ref,
                immutable_audit_ref=f"audit-framework-rule-mapping-{_short_uuid()}",
                actor_id=actor.user_id,
                actor_role=actor.role,
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(row)
            mapping_rows.append(row)
            next_mapping_seq += 1
        db.commit()
        return {
            "frameworks": [
                {
                    "framework_event_id": row.framework_event_id,
                    "framework_name": row.framework_name,
                    "regulation_family": row.regulation_family,
                    "framework_priority": row.framework_priority,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(frameworks, key=lambda item: (item.framework_name, item.sequence))
            ],
            "framework_rule_mappings": [
                {
                    "framework_rule_mapping_event_id": row.framework_rule_mapping_event_id,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "rule_code": row.rule_code,
                    "operational_domain": row.operational_domain,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(mapping_rows, key=lambda item: (item.framework_name, item.rule_code, item.sequence))
            ],
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def evaluate_policy_constraints(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        constraints = OperationsOrchestrationService._normalize_constraint_weights(
            OperationsOrchestrationService._policy_constraint_catalog()
        )
        evaluations: list[OperationsConstraintEvaluation] = []
        violations: list[OperationsConstraintViolation] = []
        evidence_refs: list[OperationsRegulatoryEvidenceRef] = []
        next_eval_seq = _next_sequence(db, OperationsConstraintEvaluation)
        next_violation_seq = _next_sequence(db, OperationsConstraintViolation)
        next_evidence_seq = _next_sequence(db, OperationsRegulatoryEvidenceRef)
        for row in constraints:
            evidence_rows = OperationsOrchestrationService._collect_policy_evidence(
                replay_entries,
                predictive_entries,
                policy_id=str(row["policy_id"]),
            )
            evidence_quality = min(100.0, float(len(evidence_rows)) * 18.0 + float(snapshot["predictive_event_count"]) * 4.0)
            lineage_confidence = max(0.0, 100.0 - float(snapshot["total_event_count"]) * 0.35)
            evaluation_score = round(
                min(
                    100.0,
                    float(row["normalized_weight"]) * 100.0
                    + float(snapshot["total_event_count"]) * 0.45
                    + evidence_quality * 0.18
                    + lineage_confidence * 0.12,
                ),
                6,
            )
            evaluation_status = "stable" if evaluation_score < 45.0 else "watch" if evaluation_score < 70.0 else "elevated"
            context = OperationsOrchestrationService._reconstruct_constraint_context(snapshot, row)
            evaluation = OperationsConstraintEvaluation(
                sequence=next_eval_seq,
                constraint_evaluation_event_id=f"constraint-evaluation-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                policy_id=str(row["policy_id"]),
                framework_name=str(row["framework_name"]),
                rule_code=str(row["rule_code"]),
                evaluation_score=evaluation_score,
                evaluation_status=evaluation_status,
                ancestry_ref=f"policy-ancestry-{row['policy_id']}",
                rationale_segment_ref=f"policy-rationale-{row['policy_id']}",
                evaluation_payload_json=json_dumps(
                    {
                        "constraint": row,
                        "evidence": evidence_rows,
                        "context": context,
                        "evidence_quality": evidence_quality,
                        "lineage_confidence": lineage_confidence,
                    }
                ),
                immutable_hash=_checksum_payload({"constraint": row, "context": context, "score": evaluation_score}),
                correlation_id=correlation_id,
                replay_parent_event_id=None,
                replay_lineage_ref=f"policy-evaluation-lineage-{organization_id}",
                immutable_audit_ref=f"audit-constraint-evaluation-{_short_uuid()}",
                actor_id=actor.user_id,
                actor_role=actor.role,
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(evaluation)
            evaluations.append(evaluation)
            next_eval_seq += 1
            for evidence in evidence_rows:
                evidence_ref = OperationsRegulatoryEvidenceRef(
                    sequence=next_evidence_seq,
                    regulatory_evidence_ref_event_id=f"regulatory-evidence-ref-{_short_uuid()}",
                    organization_id=organization_id,
                    replay_session_id=replay_session_id,
                    policy_id=str(row["policy_id"]),
                    framework_name=str(row["framework_name"]),
                    evidence_ref=str(evidence.get("event_id") or "unknown-evidence"),
                    evidence_type=str(evidence.get("event_type") or "unknown"),
                    ancestry_ref=f"policy-ancestry-{row['policy_id']}",
                    rationale_segment_ref=f"policy-rationale-{row['policy_id']}",
                    evidence_payload_json=json_dumps(evidence),
                    immutable_hash=_checksum_payload(evidence),
                    correlation_id=correlation_id,
                    replay_parent_event_id=None,
                    replay_lineage_ref=evaluation.replay_lineage_ref,
                    immutable_audit_ref=f"audit-regulatory-evidence-ref-{_short_uuid()}",
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    advisory_flags=_advisory_flags(actor),
                    created_at=now(),
                )
                db.add(evidence_ref)
                evidence_refs.append(evidence_ref)
                next_evidence_seq += 1
            if evaluation_score >= 70.0:
                violation = OperationsConstraintViolation(
                    sequence=next_violation_seq,
                    constraint_violation_event_id=f"constraint-violation-event-{_short_uuid()}",
                    organization_id=organization_id,
                    replay_session_id=replay_session_id,
                    policy_id=str(row["policy_id"]),
                    framework_name=str(row["framework_name"]),
                    rule_code=str(row["rule_code"]),
                    severity_weight=float(row["severity_weight"]),
                    violation_level="critical" if evaluation_score >= 85.0 else "high",
                    ancestry_ref=evaluation.ancestry_ref,
                    rationale_segment_ref=evaluation.rationale_segment_ref,
                    violation_payload_json=json_dumps({"evaluation_score": evaluation_score, "context": context}),
                    immutable_hash=_checksum_payload({"policy_id": row["policy_id"], "score": evaluation_score}),
                    correlation_id=correlation_id,
                    replay_parent_event_id=None,
                    replay_lineage_ref=evaluation.replay_lineage_ref,
                    immutable_audit_ref=f"audit-constraint-violation-event-{_short_uuid()}",
                    actor_id=actor.user_id,
                    actor_role=actor.role,
                    advisory_flags=_advisory_flags(actor),
                    created_at=now(),
                )
                db.add(violation)
                violations.append(violation)
                next_violation_seq += 1
        db.commit()
        return {
            "constraint_evaluations": [
                {
                    "constraint_evaluation_event_id": row.constraint_evaluation_event_id,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "rule_code": row.rule_code,
                    "evaluation_score": row.evaluation_score,
                    "evaluation_status": row.evaluation_status,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(evaluations, key=lambda item: (-item.evaluation_score, item.framework_name, item.rule_code, item.sequence))
            ],
            "constraint_violations": [
                {
                    "constraint_violation_event_id": row.constraint_violation_event_id,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "rule_code": row.rule_code,
                    "violation_level": row.violation_level,
                    "severity_weight": row.severity_weight,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(violations, key=lambda item: (-item.severity_weight, item.framework_name, item.rule_code, item.sequence))
            ],
            "regulatory_evidence_refs": [
                {
                    "regulatory_evidence_ref_event_id": row.regulatory_evidence_ref_event_id,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "evidence_ref": row.evidence_ref,
                    "evidence_type": row.evidence_type,
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(evidence_refs, key=lambda item: (item.policy_id, item.evidence_ref, item.sequence))
            ],
            "snapshot": snapshot,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def calculate_weighted_governance_score(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        policy_scope: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        constraints = OperationsOrchestrationService._normalize_constraint_weights(
            OperationsOrchestrationService._policy_constraint_catalog()
        )
        average_severity = sum(float(row["severity_weight"]) for row in constraints) / float(max(1, len(constraints)))
        average_priority = sum(float(row["framework_priority"]) for row in constraints) / float(max(1, len(constraints)))
        average_criticality = sum(float(row["normalized_weight"]) for row in constraints) / float(max(1, len(constraints)))
        evidence_quality = min(100.0, float(snapshot["predictive_event_count"]) * 10.0 + float(snapshot["replay_event_count"]) * 1.5)
        score_parts = {
            "severity": average_severity * 100.0,
            "operational_impact": min(100.0, float(snapshot["total_event_count"]) * 2.0),
            "replay_evidence_quality": evidence_quality,
            "lineage_confidence": max(0.0, 100.0 - float(snapshot["total_event_count"]) * 0.3),
            "rationale_completeness": min(100.0, 55.0 + float(snapshot["reasoning_depth"]) * 4.0),
            "framework_priority": average_priority * 100.0,
            "policy_criticality": average_criticality * 100.0,
            "historical_governance_consistency": max(0.0, 100.0 - float(snapshot["replay_event_count"]) * 0.5),
        }
        explainable = OperationsOrchestrationService._generate_explainable_score(score_parts)
        rationale_segments = [
            {
                "segment_order": index,
                "policy_id": row["policy_id"],
                "framework_name": row["framework_name"],
                "rule_code": row["rule_code"],
                "normalized_weight": row["normalized_weight"],
            }
            for index, row in enumerate(constraints, start=1)
        ]
        row = OperationsPolicyScoreSnapshot(
            sequence=_next_sequence(db, OperationsPolicyScoreSnapshot),
            policy_score_event_id=f"policy-score-snapshot-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            policy_scope=policy_scope,
            weighted_score=float(explainable["weighted_score"]),
            score_status="stable" if float(explainable["weighted_score"]) < 45.0 else "watch" if float(explainable["weighted_score"]) < 70.0 else "elevated",
            ancestry_ref=f"policy-score-ancestry-{organization_id}",
            rationale_segment_ref=f"policy-score-rationale-{organization_id}",
            score_payload_json=json_dumps(
                {
                    "score_parts": score_parts,
                    "explainable": explainable,
                    "rationale_segments": rationale_segments,
                    "framework_references": [row["framework_name"] for row in constraints],
                    "policy_mappings": [row["policy_id"] for row in constraints],
                    "evidence_lineage_refs": [entry.get("replay_lineage_ref") for entry in (replay_entries + predictive_entries)[:6]],
                }
            ),
            immutable_hash=_checksum_payload({"policy_scope": policy_scope, "score_parts": score_parts, "explainable": explainable}),
            correlation_id=correlation_id,
            replay_parent_event_id=None,
            replay_lineage_ref=f"policy-score-lineage-{organization_id}",
            immutable_audit_ref=f"audit-policy-score-snapshot-{_short_uuid()}",
            actor_id=actor.user_id,
            actor_role=actor.role,
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(row)
        db.commit()
        return {
            "policy_score_event_id": row.policy_score_event_id,
            "policy_scope": row.policy_scope,
            "weighted_score": row.weighted_score,
            "score_status": row.score_status,
            "score_snapshot": json.loads(row.score_payload_json),
            "timestamp": _iso_utc(row.created_at),
            "immutable_audit_ref": row.immutable_audit_ref,
            "replay_lineage_ref": row.replay_lineage_ref,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def build_rationale_chain(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        decision_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        replay_entries = OperationsOrchestrationService._predictive_scoped_entries(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
        )
        predictive_entries = OperationsOrchestrationService._collect_predictive_event_rows(
            db,
            organization_id=organization_id,
            replay_session_id=replay_session_id,
        )
        snapshot = OperationsOrchestrationService._governance_memory_snapshot(replay_entries, predictive_entries)
        constraints = OperationsOrchestrationService._normalize_constraint_weights(
            OperationsOrchestrationService._policy_constraint_catalog()
        )[:3]
        resolved_decision_id = str(decision_id or f"governance-decision-{_short_uuid()}")
        chain_rows: list[OperationsGovernanceRationaleChain] = []
        trace_rows: list[OperationsGovernanceDecisionTrace] = []
        next_chain_seq = _next_sequence(db, OperationsGovernanceRationaleChain)
        next_trace_seq = _next_sequence(db, OperationsGovernanceDecisionTrace)
        for order, constraint in enumerate(constraints, start=1):
            evidence_rows = OperationsOrchestrationService._collect_policy_evidence(
                replay_entries,
                predictive_entries,
                policy_id=str(constraint["policy_id"]),
            )
            score_parts = {
                "severity": float(constraint["severity_weight"]) * 100.0,
                "operational_impact": min(100.0, float(snapshot["total_event_count"]) * 2.5),
                "replay_evidence_quality": min(100.0, float(len(evidence_rows)) * 20.0),
                "lineage_confidence": max(0.0, 100.0 - float(snapshot["total_event_count"]) * 0.35),
                "rationale_completeness": min(100.0, 40.0 + len(evidence_rows) * 15.0),
                "framework_priority": float(constraint["framework_priority"]) * 100.0,
                "policy_criticality": float(constraint["normalized_weight"]) * 100.0,
                "historical_governance_consistency": max(0.0, 100.0 - float(snapshot["predictive_event_count"]) * 1.5),
            }
            segments = OperationsOrchestrationService._build_rationale_segments(constraint, evidence_rows, score_parts=score_parts)
            chain = OperationsGovernanceRationaleChain(
                sequence=next_chain_seq,
                rationale_chain_event_id=f"governance-rationale-chain-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                decision_id=resolved_decision_id,
                chain_scope="policy_rationale",
                chain_order=order,
                rationale_segment_ref=f"policy-rationale-{constraint['policy_id']}",
                ancestry_ref=f"policy-ancestry-{constraint['policy_id']}",
                chain_payload_json=json_dumps({"constraint": constraint, "segments": segments, "snapshot": snapshot}),
                immutable_hash=_checksum_payload({"constraint": constraint, "segments": segments}),
                correlation_id=correlation_id,
                replay_parent_event_id=None,
                replay_lineage_ref=f"governance-rationale-chain-lineage-{organization_id}",
                immutable_audit_ref=f"audit-governance-rationale-chain-{_short_uuid()}",
                actor_id=actor.user_id,
                actor_role=actor.role,
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            trace = OperationsGovernanceDecisionTrace(
                sequence=next_trace_seq,
                governance_decision_trace_event_id=f"governance-decision-trace-{_short_uuid()}",
                organization_id=organization_id,
                replay_session_id=replay_session_id,
                decision_id=resolved_decision_id,
                policy_id=str(constraint["policy_id"]),
                framework_name=str(constraint["framework_name"]),
                trace_stage="rationale_chain",
                ancestry_ref=chain.ancestry_ref,
                rationale_segment_ref=chain.rationale_segment_ref,
                trace_payload_json=json_dumps({"segments": segments}),
                immutable_hash=_checksum_payload({"decision_id": resolved_decision_id, "policy_id": constraint["policy_id"], "segments": segments}),
                correlation_id=correlation_id,
                replay_parent_event_id=None,
                replay_lineage_ref=chain.replay_lineage_ref,
                immutable_audit_ref=f"audit-governance-decision-trace-{_short_uuid()}",
                actor_id=actor.user_id,
                actor_role=actor.role,
                advisory_flags=_advisory_flags(actor),
                created_at=now(),
            )
            db.add(chain)
            db.add(trace)
            chain_rows.append(chain)
            trace_rows.append(trace)
            next_chain_seq += 1
            next_trace_seq += 1
        db.commit()
        return {
            "decision_id": resolved_decision_id,
            "rationale_chain": [
                {
                    "rationale_chain_event_id": row.rationale_chain_event_id,
                    "chain_order": row.chain_order,
                    "rationale_segment_ref": row.rationale_segment_ref,
                    "chain_payload": json.loads(row.chain_payload_json),
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(chain_rows, key=lambda item: (item.chain_order, item.sequence))
            ],
            "decision_trace": [
                {
                    "governance_decision_trace_event_id": row.governance_decision_trace_event_id,
                    "trace_stage": row.trace_stage,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "trace_payload": json.loads(row.trace_payload_json),
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in sorted(trace_rows, key=lambda item: (item.policy_id or "", item.sequence))
            ],
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_constraint_explanation(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        score_payload = OperationsOrchestrationService.calculate_weighted_governance_score(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
            policy_scope="governance_policy_constraints",
            correlation_id=f"{correlation_id}-score",
        )
        decision_id = f"constraint-explanation-{_short_uuid()}"
        trace = OperationsGovernanceDecisionTrace(
            sequence=_next_sequence(db, OperationsGovernanceDecisionTrace),
            governance_decision_trace_event_id=f"constraint-explanation-trace-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            decision_id=decision_id,
            policy_id=None,
            framework_name=None,
            trace_stage="constraint_explanation",
            ancestry_ref=score_payload["replay_lineage_ref"],
            rationale_segment_ref=score_payload["immutable_audit_ref"],
            trace_payload_json=json_dumps(
                {
                    "summary": "Governance policy score remains explainable and advisory-only.",
                    "score_snapshot": score_payload,
                }
            ),
            immutable_hash=_checksum_payload(score_payload),
            correlation_id=correlation_id,
            replay_parent_event_id=None,
            replay_lineage_ref=score_payload["replay_lineage_ref"],
            immutable_audit_ref=f"audit-constraint-explanation-trace-{_short_uuid()}",
            actor_id=actor.user_id,
            actor_role=actor.role,
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(trace)
        db.commit()
        return {
            "decision_id": decision_id,
            "summary": "Governance policy score remains explainable and advisory-only.",
            "score_snapshot": score_payload,
            "trace": {
                "governance_decision_trace_event_id": trace.governance_decision_trace_event_id,
                "trace_stage": trace.trace_stage,
                "trace_payload": json.loads(trace.trace_payload_json),
                "timestamp": _iso_utc(trace.created_at),
            },
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def trace_policy_lineage(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        query = db.query(OperationsPolicyConstraint).filter(OperationsPolicyConstraint.organization_id == organization_id)
        if replay_session_id is not None:
            query = query.filter(OperationsPolicyConstraint.replay_session_id == replay_session_id)
        constraints = query.order_by(OperationsPolicyConstraint.created_at.asc(), OperationsPolicyConstraint.sequence.asc()).all()
        if not constraints:
            OperationsOrchestrationService.generate_policy_matrix(
                db,
                organization_id=organization_id,
                actor=actor,
                replay_session_id=replay_session_id,
                correlation_id=f"{correlation_id}-bootstrap",
            )
            query = db.query(OperationsPolicyConstraint).filter(OperationsPolicyConstraint.organization_id == organization_id)
            if replay_session_id is not None:
                query = query.filter(OperationsPolicyConstraint.replay_session_id == replay_session_id)
            constraints = query.order_by(OperationsPolicyConstraint.created_at.asc(), OperationsPolicyConstraint.sequence.asc()).all()
        lineage = [
            {
                "policy_id": row.policy_id,
                "framework_name": row.framework_name,
                "rule_code": row.rule_code,
                "ancestry_ref": row.ancestry_ref,
                "rationale_segment_ref": row.rationale_segment_ref,
                "replay_lineage_ref": row.replay_lineage_ref,
                "timestamp": _iso_utc(row.created_at),
            }
            for row in sorted(constraints, key=lambda item: (item.framework_name, item.rule_code, item.sequence))
        ]
        trace = OperationsGovernanceDecisionTrace(
            sequence=_next_sequence(db, OperationsGovernanceDecisionTrace),
            governance_decision_trace_event_id=f"policy-lineage-trace-{_short_uuid()}",
            organization_id=organization_id,
            replay_session_id=replay_session_id,
            decision_id=f"policy-lineage-{_short_uuid()}",
            policy_id=None,
            framework_name=None,
            trace_stage="policy_lineage",
            ancestry_ref=f"policy-lineage-ancestry-{organization_id}",
            rationale_segment_ref=f"policy-lineage-rationale-{organization_id}",
            trace_payload_json=json_dumps({"lineage": lineage}),
            immutable_hash=_checksum_payload(lineage),
            correlation_id=correlation_id,
            replay_parent_event_id=None,
            replay_lineage_ref=f"policy-lineage-trace-lineage-{organization_id}",
            immutable_audit_ref=f"audit-policy-lineage-trace-{_short_uuid()}",
            actor_id=actor.user_id,
            actor_role=actor.role,
            advisory_flags=_advisory_flags(actor),
            created_at=now(),
        )
        db.add(trace)
        db.commit()
        return {
            "policy_lineage": lineage,
            "trace_event_id": trace.governance_decision_trace_event_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def reconstruct_governance_decision(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        decision_id: str,
        correlation_id: str,
    ) -> dict[str, Any]:
        chains = db.query(OperationsGovernanceRationaleChain).filter(
            OperationsGovernanceRationaleChain.organization_id == organization_id,
            OperationsGovernanceRationaleChain.decision_id == decision_id,
        ).order_by(OperationsGovernanceRationaleChain.chain_order.asc(), OperationsGovernanceRationaleChain.sequence.asc()).all()
        traces = db.query(OperationsGovernanceDecisionTrace).filter(
            OperationsGovernanceDecisionTrace.organization_id == organization_id,
            OperationsGovernanceDecisionTrace.decision_id == decision_id,
        ).order_by(OperationsGovernanceDecisionTrace.created_at.asc(), OperationsGovernanceDecisionTrace.sequence.asc()).all()
        return {
            "decision_id": decision_id,
            "rationale_chain": [
                {
                    "rationale_chain_event_id": row.rationale_chain_event_id,
                    "chain_order": row.chain_order,
                    "rationale_segment_ref": row.rationale_segment_ref,
                    "chain_payload": json.loads(row.chain_payload_json),
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in chains
            ],
            "decision_trace": [
                {
                    "governance_decision_trace_event_id": row.governance_decision_trace_event_id,
                    "trace_stage": row.trace_stage,
                    "policy_id": row.policy_id,
                    "framework_name": row.framework_name,
                    "trace_payload": json.loads(row.trace_payload_json),
                    "timestamp": _iso_utc(row.created_at),
                }
                for row in traces
            ],
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def generate_constraint_recommendations(
        *,
        evaluations: dict[str, Any],
        score_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        violations = list(evaluations.get("constraint_violations", []))
        recommendations: list[dict[str, Any]] = []
        for index, row in enumerate(sorted(violations, key=lambda item: (str(item.get("framework_name") or ""), str(item.get("rule_code") or ""))), start=1):
            recommendations.append(
                {
                    "recommendation_rank": index,
                    "policy_id": row.get("policy_id"),
                    "framework_name": row.get("framework_name"),
                    "rule_code": row.get("rule_code"),
                    "summary": "Increase supervised review coverage for this policy constraint before downstream advisory use.",
                    "score_reference": score_snapshot.get("policy_score_event_id"),
                }
            )
        if not recommendations:
            recommendations.append(
                {
                    "recommendation_rank": 1,
                    "policy_id": None,
                    "framework_name": "Internal Governance Policies",
                    "rule_code": "NOVA-GOV-BASELINE",
                    "summary": "Maintain supervision-first review cadence; no elevated policy violations detected.",
                    "score_reference": score_snapshot.get("policy_score_event_id"),
                }
            )
        return recommendations

    @staticmethod
    def evaluate_operational_risk(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        evaluations = OperationsOrchestrationService.evaluate_policy_constraints(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
            correlation_id=f"{correlation_id}-constraints",
        )
        score = OperationsOrchestrationService.calculate_weighted_governance_score(
            db,
            organization_id=organization_id,
            actor=actor,
            replay_session_id=replay_session_id,
            policy_scope="operational_risk",
            correlation_id=f"{correlation_id}-score",
        )
        recommendations = OperationsOrchestrationService.generate_constraint_recommendations(
            evaluations=evaluations,
            score_snapshot=score,
        )
        risk_score = round(min(100.0, float(score["weighted_score"]) + float(len(evaluations.get("constraint_violations", []))) * 4.5), 6)
        return {
            "risk_score": risk_score,
            "risk_level": "low" if risk_score < 35.0 else "moderate" if risk_score < 60.0 else "elevated" if risk_score < 80.0 else "critical",
            "constraint_evaluations": evaluations,
            "score_snapshot": score,
            "recommendations": recommendations,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }

    @staticmethod
    def export_governance_provenance_bundle(
        db: Session,
        *,
        organization_id: str,
        actor: UserContext,
        replay_session_id: str | None,
        correlation_id: str,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        governance_models = [
            (OperationsDecisionProvenance, "decision_provenance", "provenance_event_id", "provenance_json"),
            (OperationsGovernanceMemory, "governance_memory", "memory_event_id", "memory_json"),
            (OperationsAdvisoryReasoningChain, "advisory_reasoning_chain", "reasoning_chain_event_id", "chain_json"),
            (OperationsGovernanceRationale, "governance_rationale", "rationale_event_id", "rationale_json"),
            (OperationsOperationalAncestry, "operational_ancestry", "ancestry_event_id", "ancestry_json"),
            (OperationsTrendMemory, "trend_memory", "trend_memory_event_id", "trend_memory_json"),
            (OperationsGovernanceExplanation, "governance_explanation", "explanation_event_id", "explanation_json"),
            (OperationsRecommendationLineage, "recommendation_lineage", "recommendation_lineage_event_id", "lineage_json"),
            (OperationsDecisionSnapshot, "decision_snapshot", "decision_snapshot_event_id", "snapshot_json"),
            (OperationsHistoricalGovernanceState, "historical_governance_state", "historical_state_event_id", "state_json"),
            (OperationsPolicyConstraint, "policy_constraint", "constraint_event_id", None),
            (OperationsPolicyConstraintVersion, "policy_constraint_version", "constraint_version_event_id", "version_payload_json"),
            (OperationsRegulatoryFramework, "regulatory_framework", "framework_event_id", "framework_payload_json"),
            (OperationsFrameworkRuleMapping, "framework_rule_mapping", "framework_rule_mapping_event_id", "mapping_payload_json"),
            (OperationsGovernanceRationaleChain, "governance_rationale_chain", "rationale_chain_event_id", "chain_payload_json"),
            (OperationsConstraintEvaluation, "constraint_evaluation", "constraint_evaluation_event_id", "evaluation_payload_json"),
            (OperationsConstraintViolation, "constraint_violation", "constraint_violation_event_id", "violation_payload_json"),
            (OperationsPolicyScoreSnapshot, "policy_score_snapshot", "policy_score_event_id", "score_payload_json"),
            (OperationsRegulatoryEvidenceRef, "regulatory_evidence_ref", "regulatory_evidence_ref_event_id", "evidence_payload_json"),
            (OperationsGovernanceDecisionTrace, "governance_decision_trace", "governance_decision_trace_event_id", "trace_payload_json"),
        ]
        for model, event_type, id_attr, payload_attr in governance_models:
            query = db.query(model).filter(model.organization_id == organization_id)
            if replay_session_id is not None and hasattr(model, "replay_session_id"):
                query = query.filter(model.replay_session_id == replay_session_id)
            model_rows = query.order_by(model.created_at.asc(), model.sequence.asc()).all()
            for row in model_rows:
                rows.append(
                    {
                        "sequence": row.sequence,
                        "event_id": getattr(row, id_attr),
                        "event_type": event_type,
                        "timestamp": _iso_utc(row.created_at),
                        "immutable_audit_ref": row.immutable_audit_ref,
                        "replay_lineage_ref": row.replay_lineage_ref,
                        "payload": (
                            {
                                "policy_id": getattr(row, "policy_id", None),
                                "framework_name": getattr(row, "framework_name", None),
                                "rule_code": getattr(row, "rule_code", None),
                                "operational_domain": getattr(row, "operational_domain", None),
                                "severity_weight": getattr(row, "severity_weight", None),
                                "ancestry_ref": getattr(row, "ancestry_ref", None),
                                "rationale_segment_ref": getattr(row, "rationale_segment_ref", None),
                                "immutable_hash": getattr(row, "immutable_hash", None),
                            }
                            if payload_attr is None
                            else json.loads(getattr(row, payload_attr))
                        ),
                    }
                )

        rows = sorted(rows, key=_event_sort_key)
        chain: list[dict[str, Any]] = []
        prior_hash = "GENESIS"
        for row in rows:
            digest = _checksum_payload(
                {
                    "event_id": row.get("event_id"),
                    "event_type": row.get("event_type"),
                    "timestamp": row.get("timestamp"),
                    "prior_hash": prior_hash,
                }
            )
            chain.append({"event_id": row.get("event_id"), "prior_hash": prior_hash, "event_hash": digest})
            prior_hash = digest

        payload = {
            "organization_id": organization_id,
            "generated_at": _iso_utc(now()),
            "generated_by": actor.user_id,
            "generated_by_role": actor.role,
            "governance_events": rows,
            "immutable_chain": chain,
            "chain_tail_hash": prior_hash,
            "governance_reconstruction": {
                "ordering": "deterministic_timestamp_eventid_ascending",
                "event_count": len(rows),
            },
        }
        checksum = _checksum_payload(payload)
        return {
            "bundle_id": f"governance-export-{_short_uuid()}",
            "bundle_checksum": checksum,
            "chain_tail_hash": prior_hash,
            "payload": payload,
            "correlation_id": correlation_id,
            "advisory_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "append_only": True,
            "replay_safe": True,
        }
