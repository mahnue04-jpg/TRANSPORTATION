"""Workflow orchestration and self-healing automation for Health ISF.

This module adds additive workflow control-plane behavior on top of the
existing dispatch, intelligence, retry, and websocket primitives.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf import service as health_service
from app.modules.health_isf.intelligence import IntelligenceThresholds, OperationalIntelligenceService
from app.modules.health_isf.models import (
    AutomationPolicyScope,
    DispatchDeadLetterEvent,
    HealthISFAutomationPolicy,
    HealthISFDriver,
    HealthISFRide,
    HealthISFWorkflowAuditLog,
    HealthISFWorkflowEscalation,
    HealthISFWorkflowExecution,
    HealthISFWorkflowIncident,
    RideStatus,
    WorkflowEscalationStatus,
    WorkflowExecutionStatus,
    WorkflowIncidentStatus,
)
from app.modules.health_isf.realtime import SubscriptionType, get_broadcaster, get_emitter
from app.modules.health_isf.realtime_service import RetryQueueService

logger = logging.getLogger("amicor.health_isf.workflow")


def _json_load(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except Exception:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _json_dump(value: Any) -> str:
    return json.dumps(value, default=str, separators=(",", ":"))


def _workflow_execution_dict(row: HealthISFWorkflowExecution) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workflow_name": row.workflow_name,
        "status": row.status,
        "trigger_type": row.trigger_type,
        "ride_id": row.ride_id,
        "driver_id": row.driver_id,
        "policy_id": row.policy_id,
        "input_payload": _json_load(row.input_payload),
        "output_payload": _json_load(row.output_payload),
        "error_message": row.error_message,
        "retry_count": row.retry_count,
        "max_attempts": row.max_attempts,
        "approval_required": row.approval_required,
        "approved_by_user_id": row.approved_by_user_id,
        "created_by_user_id": row.created_by_user_id,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _workflow_incident_dict(row: HealthISFWorkflowIncident) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workflow_execution_id": row.workflow_execution_id,
        "ride_id": row.ride_id,
        "driver_id": row.driver_id,
        "incident_type": row.incident_type,
        "severity": row.severity,
        "status": row.status,
        "summary": row.summary,
        "details": _json_load(row.details),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "resolved_at": row.resolved_at,
        "escalated_at": row.escalated_at,
    }


def _workflow_escalation_dict(row: HealthISFWorkflowEscalation) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "workflow_execution_id": row.workflow_execution_id,
        "incident_id": row.incident_id,
        "escalation_level": row.escalation_level,
        "target_queue": row.target_queue,
        "target_role": row.target_role,
        "status": row.status,
        "summary": row.summary,
        "details": _json_load(row.details),
        "created_at": row.created_at,
        "acknowledged_at": row.acknowledged_at,
        "resolved_at": row.resolved_at,
    }


def _workflow_policy_dict(row: HealthISFAutomationPolicy) -> dict[str, Any]:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "name": row.name,
        "scope": row.scope,
        "is_enabled": row.is_enabled,
        "approval_required": row.approval_required,
        "auto_reassign_enabled": row.auto_reassign_enabled,
        "auto_escalation_enabled": row.auto_escalation_enabled,
        "allow_replay": row.allow_replay,
        "max_retry_attempts": row.max_retry_attempts,
        "stuck_ride_minutes": row.stuck_ride_minutes,
        "delayed_pickup_minutes": row.delayed_pickup_minutes,
        "escalation_minutes": row.escalation_minutes,
        "policy_rules": _json_load(row.policy_rules),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class WorkflowOrchestrationService:
    """Tenant-scoped orchestration layer for workflow recovery and escalation."""

    _org_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    @classmethod
    def _lock_for_org(cls, organization_id: str) -> asyncio.Lock:
        lock = cls._org_locks.get(organization_id)
        if lock is None:
            lock = asyncio.Lock()
            cls._org_locks[organization_id] = lock
        return lock

    @staticmethod
    def _default_policy_payload() -> dict[str, Any]:
        return {
            "name": "Default workflow policy",
            "scope": AutomationPolicyScope.TENANT.value,
            "is_enabled": True,
            "approval_required": False,
            "auto_reassign_enabled": True,
            "auto_escalation_enabled": True,
            "allow_replay": True,
            "max_retry_attempts": 3,
            "stuck_ride_minutes": 45,
            "delayed_pickup_minutes": 20,
            "escalation_minutes": 30,
            "policy_rules": {
                "safe_automation": True,
                "tenant_scoped": True,
                "preserve_rbac": True,
                "preserve_audit_log": True,
                "approval_required_for_high_risk": False,
            },
        }

    @classmethod
    def ensure_policy(cls, db: Session, organization_id: str) -> HealthISFAutomationPolicy:
        policy = db.query(HealthISFAutomationPolicy).filter(
            HealthISFAutomationPolicy.organization_id == organization_id,
            HealthISFAutomationPolicy.is_enabled == True,  # noqa: E712
        ).order_by(HealthISFAutomationPolicy.updated_at.desc()).first()
        if policy:
            return policy

        defaults = cls._default_policy_payload()
        policy = HealthISFAutomationPolicy(
            id=uuid4(),
            organization_id=organization_id,
            name=defaults["name"],
            scope=defaults["scope"],
            is_enabled=defaults["is_enabled"],
            approval_required=defaults["approval_required"],
            auto_reassign_enabled=defaults["auto_reassign_enabled"],
            auto_escalation_enabled=defaults["auto_escalation_enabled"],
            allow_replay=defaults["allow_replay"],
            max_retry_attempts=defaults["max_retry_attempts"],
            stuck_ride_minutes=defaults["stuck_ride_minutes"],
            delayed_pickup_minutes=defaults["delayed_pickup_minutes"],
            escalation_minutes=defaults["escalation_minutes"],
            policy_rules=_json_dump(defaults["policy_rules"]),
            created_at=now(),
            updated_at=now(),
        )
        db.add(policy)
        db.commit()
        return policy

    @classmethod
    def list_workflows(cls, db: Session, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = (
            db.query(HealthISFWorkflowExecution)
            .filter(HealthISFWorkflowExecution.organization_id == organization_id)
            .order_by(HealthISFWorkflowExecution.updated_at.desc())
            .limit(limit)
            .all()
        )
        return [_workflow_execution_dict(row) for row in rows]

    @classmethod
    def list_incidents(
        cls,
        db: Session,
        organization_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = db.query(HealthISFWorkflowIncident).filter(HealthISFWorkflowIncident.organization_id == organization_id)
        if status:
            query = query.filter(HealthISFWorkflowIncident.status == status)
        rows = query.order_by(HealthISFWorkflowIncident.updated_at.desc()).limit(limit).all()
        return [_workflow_incident_dict(row) for row in rows]

    @classmethod
    def list_escalations(
        cls,
        db: Session,
        organization_id: str,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        query = db.query(HealthISFWorkflowEscalation).filter(HealthISFWorkflowEscalation.organization_id == organization_id)
        if status:
            query = query.filter(HealthISFWorkflowEscalation.status == status)
        rows = query.order_by(HealthISFWorkflowEscalation.created_at.desc()).limit(limit).all()
        return [_workflow_escalation_dict(row) for row in rows]

    @classmethod
    def list_policies(cls, db: Session, organization_id: str) -> list[dict[str, Any]]:
        rows = (
            db.query(HealthISFAutomationPolicy)
            .filter(HealthISFAutomationPolicy.organization_id == organization_id)
            .order_by(HealthISFAutomationPolicy.updated_at.desc())
            .all()
        )
        if not rows:
            rows = [cls.ensure_policy(db, organization_id)]
        return [_workflow_policy_dict(row) for row in rows]

    @classmethod
    def record_intake_hook(
        cls,
        db: Session,
        *,
        organization_id: str,
        ride_id: str,
        actor_user_id: str | None,
        payload: dict[str, Any],
    ) -> None:
        audit = HealthISFWorkflowAuditLog(
            id=uuid4(),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type="workflow.intake.submitted",
            actor_user_id=actor_user_id,
            payload=_json_dump({"ride_id": ride_id, **payload}),
            created_at=now(),
        )
        db.add(audit)
        db.commit()

    @classmethod
    def record_onboarding_hook(
        cls,
        db: Session,
        *,
        organization_id: str,
        entity_type: str,
        entity_id: str,
        actor_user_id: str | None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event_entity = str(entity_type or "entity").strip().lower()
        audit = HealthISFWorkflowAuditLog(
            id=uuid4(),
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type=f"workflow.onboarding.{event_entity}.created",
            actor_user_id=actor_user_id,
            payload=_json_dump(
                {
                    "entity_type": event_entity,
                    "entity_id": entity_id,
                    **dict(payload or {}),
                }
            ),
            created_at=now(),
        )
        db.add(audit)
        db.commit()

    @classmethod
    async def run_recovery(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
        actor_user_id: str | None = None,
        note: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        async with cls._lock_for_org(organization_id):
            policy = cls.ensure_policy(db, organization_id)
            thresholds = IntelligenceThresholds(
                stuck_ride_minutes=policy.stuck_ride_minutes,
                delayed_pickup_minutes=policy.delayed_pickup_minutes,
                auto_reassign_confidence_threshold=0.7,
            )
            execution = cls._create_execution(
                db,
                organization_id=organization_id,
                workflow_name="automated_recovery",
                trigger_type="manual" if note else "event",
                actor_user_id=actor_user_id,
                policy=policy,
                ride_id=ride_id,
                input_payload={"ride_id": ride_id, "dry_run": dry_run, "note": note},
            )

            rides = cls._target_rides_for_recovery(db, organization_id, ride_id, policy)
            incidents: list[HealthISFWorkflowIncident] = []
            escalations: list[HealthISFWorkflowEscalation] = []
            recommendations: list[dict[str, Any]] = []
            broadcast_events = 0

            try:
                for ride in rides:
                    result = await cls._recover_single_ride(
                        db=db,
                        organization_id=organization_id,
                        ride=ride,
                        workflow_execution_id=execution.id,
                        policy=policy,
                        thresholds=thresholds,
                        actor_user_id=actor_user_id,
                        dry_run=dry_run,
                        note=note,
                    )
                    if result.get("incident"):
                        incidents.append(result["incident"])
                    if result.get("escalation"):
                        escalations.append(result["escalation"])
                    if result.get("recommendations"):
                        recommendations.extend(result["recommendations"])
                    broadcast_events += result.get("broadcast_events", 0)

                execution.status = WorkflowExecutionStatus.SUCCEEDED.value
                execution.output_payload = _json_dump(
                    {
                        "recovered_rides": [ride.id for ride in rides],
                        "recommendations": recommendations,
                        "dry_run": dry_run,
                    }
                )
                execution.completed_at = now()
            except Exception as exc:
                execution.status = WorkflowExecutionStatus.FAILED.value
                execution.error_message = str(exc)[:1024]
                execution.completed_at = now()
                cls._audit(
                    db,
                    organization_id=organization_id,
                    workflow_execution_id=execution.id,
                    actor_user_id=actor_user_id,
                    event_type="workflow.recovery.failed",
                    payload={"error": str(exc), "ride_id": ride_id},
                )
                db.commit()
                raise

            db.commit()
            await cls._broadcast_workflow_event(
                organization_id=organization_id,
                event_type="workflow_recovery_completed",
                payload={
                    "workflow_id": execution.id,
                    "ride_id": ride_id,
                    "status": execution.status,
                    "dry_run": dry_run,
                    "incident_count": len(incidents),
                    "escalation_count": len(escalations),
                },
            )
            return {
                "execution": _workflow_execution_dict(execution),
                "incidents": [_workflow_incident_dict(row) for row in incidents],
                "escalations": [_workflow_escalation_dict(row) for row in escalations],
                "recommendations": recommendations,
                "policy": _workflow_policy_dict(policy),
                "summary": f"Recovered {len(rides)} ride(s) with {len(incidents)} incident(s)",
                "broadcast_events": broadcast_events + 1,
                "dry_run": dry_run,
            }

    @classmethod
    async def run_reassign(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str,
        actor_user_id: str | None = None,
        driver_id: str | None = None,
        suggest_only: bool = False,
        approval_override: bool = False,
    ) -> dict[str, Any]:
        async with cls._lock_for_org(organization_id):
            policy = cls.ensure_policy(db, organization_id)
            execution = cls._create_execution(
                db,
                organization_id=organization_id,
                workflow_name="reassignment",
                trigger_type="manual",
                actor_user_id=actor_user_id,
                policy=policy,
                ride_id=ride_id,
                input_payload={"driver_id": driver_id, "suggest_only": suggest_only, "approval_override": approval_override},
            )

            ride = health_service.get_ride_by_id(db, ride_id)
            if not ride:
                raise ValueError("Ride not found")
            if ride.organization_id != organization_id:
                raise ValueError("Ride outside organization scope")

            recommendations = OperationalIntelligenceService.build_recommendations(
                db,
                organization_id=organization_id,
                ride_id=ride.id,
                thresholds=IntelligenceThresholds(
                    stuck_ride_minutes=policy.stuck_ride_minutes,
                    delayed_pickup_minutes=policy.delayed_pickup_minutes,
                    auto_reassign_confidence_threshold=0.7,
                ),
            )
            candidate_driver = cls._select_driver_recommendation(recommendations)
            chosen_driver_id = driver_id or (candidate_driver or {}).get("entity_id")

            if not chosen_driver_id:
                incident = cls._create_incident(
                    db,
                    organization_id=organization_id,
                    workflow_execution_id=execution.id,
                    ride=ride,
                    incident_type="no_reassignment_candidate",
                    severity="high",
                    summary="No safe driver reassignment candidate was available",
                    details={"recommendations": recommendations.get("recommendations", [])},
                    actor_user_id=actor_user_id,
                )
                escalation = cls._create_escalation(
                    db,
                    organization_id=organization_id,
                    workflow_execution_id=execution.id,
                    incident=incident,
                    escalation_level=1,
                    target_role="dispatcher",
                    target_queue="dispatcher_escalation_queue",
                    summary="Dispatcher review required for manual reassignment",
                    details={"reason": "no_candidate"},
                    actor_user_id=actor_user_id,
                )
                execution.status = WorkflowExecutionStatus.BLOCKED.value
                execution.output_payload = _json_dump({"recommendations": recommendations, "reason": "no_candidate"})
                execution.completed_at = now()
                cls._audit(
                    db,
                    organization_id=organization_id,
                    workflow_execution_id=execution.id,
                    actor_user_id=actor_user_id,
                    event_type="workflow.reassignment.blocked",
                    payload={"ride_id": ride_id, "reason": "no_candidate"},
                )
                db.commit()
                await cls._broadcast_workflow_event(
                    organization_id=organization_id,
                    event_type="workflow_reassignment_blocked",
                    payload={"ride_id": ride_id, "workflow_id": execution.id, "incident_id": incident.id},
                )
                return {
                    "execution": _workflow_execution_dict(execution),
                    "incidents": [_workflow_incident_dict(incident)],
                    "escalations": [_workflow_escalation_dict(escalation)],
                    "recommendations": recommendations.get("recommendations", []),
                    "policy": _workflow_policy_dict(policy),
                    "summary": "No reassignment candidate found",
                    "broadcast_events": 1,
                    "dry_run": True,
                }

            target_driver = db.query(HealthISFDriver).filter(
                HealthISFDriver.id == chosen_driver_id,
                HealthISFDriver.organization_id == organization_id,
            ).first()
            if not target_driver:
                raise ValueError("Driver not found")

            if suggest_only or (policy.approval_required and not approval_override):
                execution.status = WorkflowExecutionStatus.BLOCKED.value if policy.approval_required and not approval_override else WorkflowExecutionStatus.SUCCEEDED.value
                execution.output_payload = _json_dump({"recommendations": recommendations, "suggested_driver_id": chosen_driver_id})
                execution.completed_at = now()
                cls._audit(
                    db,
                    organization_id=organization_id,
                    workflow_execution_id=execution.id,
                    actor_user_id=actor_user_id,
                    event_type="workflow.reassignment.suggested",
                    payload={"ride_id": ride_id, "driver_id": chosen_driver_id, "suggest_only": True},
                )
                db.commit()
                await cls._broadcast_workflow_event(
                    organization_id=organization_id,
                    event_type="workflow_reassignment_suggested",
                    payload={"ride_id": ride_id, "driver_id": chosen_driver_id, "workflow_id": execution.id},
                )
                return {
                    "execution": _workflow_execution_dict(execution),
                    "incidents": [],
                    "escalations": [],
                    "recommendations": recommendations.get("recommendations", []),
                    "policy": _workflow_policy_dict(policy),
                    "summary": "Reassignment recommendation generated",
                    "broadcast_events": 1,
                    "dry_run": True,
                }

            assigned = health_service.assign_driver_to_ride(
                db,
                ride_id=ride.id,
                driver_id=target_driver.id,
                actor_user_id=actor_user_id,
            )
            if not assigned:
                raise ValueError("Failed to assign driver")

            execution.status = WorkflowExecutionStatus.SUCCEEDED.value
            execution.output_payload = _json_dump(
                {
                    "assigned_driver_id": target_driver.id,
                    "recommendations": recommendations,
                }
            )
            execution.completed_at = now()
            cls._audit(
                db,
                organization_id=organization_id,
                workflow_execution_id=execution.id,
                actor_user_id=actor_user_id,
                event_type="workflow.reassignment.executed",
                payload={"ride_id": ride_id, "driver_id": target_driver.id},
            )
            db.commit()
            await cls._broadcast_workflow_event(
                organization_id=organization_id,
                event_type="workflow_reassignment_executed",
                payload={"ride_id": ride_id, "driver_id": target_driver.id, "workflow_id": execution.id},
            )
            return {
                "execution": _workflow_execution_dict(execution),
                "incidents": [],
                "escalations": [],
                "recommendations": recommendations.get("recommendations", []),
                "policy": _workflow_policy_dict(policy),
                "summary": f"Ride reassigned to driver {target_driver.id}",
                "broadcast_events": 1,
                "dry_run": False,
            }

    @classmethod
    async def replay_dead_letters(
        cls,
        db: Session,
        organization_id: str,
        actor_user_id: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        async with cls._lock_for_org(organization_id):
            policy = cls.ensure_policy(db, organization_id)
            execution = cls._create_execution(
                db,
                organization_id=organization_id,
                workflow_name="dead_letter_replay",
                trigger_type="manual",
                actor_user_id=actor_user_id,
                policy=policy,
                input_payload={"limit": limit},
            )
            dead_letters = (
                db.query(DispatchDeadLetterEvent)
                .filter(DispatchDeadLetterEvent.organization_id == organization_id)
                .order_by(DispatchDeadLetterEvent.created_at.desc())
                .limit(limit)
                .all()
            )
            replayed: list[dict[str, Any]] = []
            for item in dead_letters:
                payload = _json_load(item.payload)
                retry = RetryQueueService.enqueue_failed_event(
                    db,
                    organization_id=organization_id,
                    event_type=item.event_type,
                    payload=payload,
                    error_message=item.error_message,
                    idempotency_key=f"replay:{item.id}",
                    ride_id=payload.get("ride_id") or payload.get("id") or None,
                    driver_id=payload.get("driver_id") or None,
                    max_attempts=policy.max_retry_attempts,
                )
                replayed.append({"dead_letter_id": item.id, "retry_event_id": retry.id, "event_type": item.event_type})

            execution.status = WorkflowExecutionStatus.REPLAYED.value
            execution.output_payload = _json_dump({"replayed": replayed})
            execution.completed_at = now()
            cls._audit(
                db,
                organization_id=organization_id,
                workflow_execution_id=execution.id,
                actor_user_id=actor_user_id,
                event_type="workflow.replay.completed",
                payload={"replayed_count": len(replayed)},
            )
            db.commit()
            await cls._broadcast_workflow_event(
                organization_id=organization_id,
                event_type="workflow_replay_completed",
                payload={"workflow_id": execution.id, "replayed_count": len(replayed)},
            )
            return {
                "execution": _workflow_execution_dict(execution),
                "incidents": [],
                "escalations": [],
                "recommendations": replayed,
                "policy": _workflow_policy_dict(policy),
                "summary": f"Replayed {len(replayed)} dead-letter event(s)",
                "broadcast_events": 1,
                "dry_run": False,
            }

    @classmethod
    async def escalate_incident(
        cls,
        db: Session,
        organization_id: str,
        actor_user_id: str | None = None,
        incident_id: str | None = None,
        ride_id: str | None = None,
        summary: str | None = None,
        severity: str = "high",
        target_role: str = "dispatcher",
        escalation_level: int = 1,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        async with cls._lock_for_org(organization_id):
            policy = cls.ensure_policy(db, organization_id)
            execution = cls._create_execution(
                db,
                organization_id=organization_id,
                workflow_name="escalation",
                trigger_type="manual",
                actor_user_id=actor_user_id,
                policy=policy,
                ride_id=ride_id,
                input_payload={"incident_id": incident_id, "summary": summary, "severity": severity},
            )

            incident = None
            if incident_id:
                incident = db.query(HealthISFWorkflowIncident).filter(
                    HealthISFWorkflowIncident.id == incident_id,
                    HealthISFWorkflowIncident.organization_id == organization_id,
                ).first()
            if incident is None and ride_id:
                ride = health_service.get_ride_by_id(db, ride_id)
                if ride and ride.organization_id == organization_id:
                    incident = cls._create_incident(
                        db,
                        organization_id=organization_id,
                        workflow_execution_id=execution.id,
                        ride=ride,
                        incident_type="manual_escalation",
                        severity=severity,
                        summary=summary or "Manual escalation requested",
                        details=details or {},
                        actor_user_id=actor_user_id,
                    )
            if incident is None:
                raise ValueError("Incident or ride required for escalation")

            escalation = cls._create_escalation(
                db,
                organization_id=organization_id,
                workflow_execution_id=execution.id,
                incident=incident,
                escalation_level=escalation_level,
                target_role=target_role,
                target_queue=f"{target_role}_escalation_queue",
                summary=summary or incident.summary,
                details=details or {"incident_type": incident.incident_type},
                actor_user_id=actor_user_id,
            )

            incident.status = WorkflowIncidentStatus.ACKNOWLEDGED.value
            incident.escalated_at = now()
            execution.status = WorkflowExecutionStatus.ESCALATED.value
            execution.output_payload = _json_dump({"incident_id": incident.id, "escalation_id": escalation.id})
            execution.completed_at = now()

            cls._audit(
                db,
                organization_id=organization_id,
                workflow_execution_id=execution.id,
                incident_id=incident.id,
                escalation_id=escalation.id,
                actor_user_id=actor_user_id,
                event_type="workflow.escalation.created",
                payload={"incident_id": incident.id, "escalation_id": escalation.id},
            )
            db.commit()
            await cls._broadcast_workflow_event(
                organization_id=organization_id,
                event_type="workflow_escalated",
                payload={"workflow_id": execution.id, "incident_id": incident.id, "escalation_id": escalation.id},
            )
            return {
                "execution": _workflow_execution_dict(execution),
                "incidents": [_workflow_incident_dict(incident)],
                "escalations": [_workflow_escalation_dict(escalation)],
                "recommendations": [],
                "policy": _workflow_policy_dict(policy),
                "summary": summary or incident.summary,
                "broadcast_events": 1,
                "dry_run": False,
            }

    @classmethod
    def _target_rides_for_recovery(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None,
        policy: HealthISFAutomationPolicy,
    ) -> list[HealthISFRide]:
        query = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id)
        if ride_id:
            ride = query.filter(HealthISFRide.id == ride_id).first()
            return [ride] if ride else []

        stuck_cutoff = now() - timedelta(minutes=policy.stuck_ride_minutes)
        delayed_cutoff = now() - timedelta(minutes=policy.delayed_pickup_minutes)
        return query.filter(
            (
                (HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]))
                & (HealthISFRide.updated_at < stuck_cutoff)
            )
            |
            (
                (HealthISFRide.status == RideStatus.PENDING)
                & (HealthISFRide.driver_id.is_(None))
                & (HealthISFRide.requested_at < delayed_cutoff)
            )
        ).order_by(HealthISFRide.updated_at.asc()).limit(25).all()

    @classmethod
    async def _recover_single_ride(
        cls,
        db: Session,
        organization_id: str,
        ride: HealthISFRide,
        workflow_execution_id: str,
        policy: HealthISFAutomationPolicy,
        thresholds: IntelligenceThresholds,
        actor_user_id: str | None,
        dry_run: bool,
        note: str | None,
    ) -> dict[str, Any]:
        recommendations = OperationalIntelligenceService.build_recommendations(
            db,
            organization_id=organization_id,
            ride_id=ride.id,
            thresholds=thresholds,
        )
        best_driver = cls._select_driver_recommendation(recommendations)
        best_provider = cls._select_provider_recommendation(recommendations)
        incident_type = cls._classify_incident(ride, policy)
        incident = cls._create_incident(
            db,
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            ride=ride,
            incident_type=incident_type,
            severity="high" if incident_type in {"stuck_ride", "no_driver_available"} else "medium",
            summary=f"{incident_type.replace('_', ' ').title()} detected for ride {ride.id}",
            details={
                "recommendations": recommendations.get("recommendations", []),
                "note": note,
                "policy": _workflow_policy_dict(policy),
            },
            actor_user_id=actor_user_id,
        )

        escalation = None
        broadcast_events = 0
        assigned_driver = None
        if policy.auto_reassign_enabled and best_driver and not dry_run and not policy.approval_required:
            assigned_driver = health_service.assign_driver_to_ride(
                db,
                ride_id=ride.id,
                driver_id=best_driver["entity_id"],
                actor_user_id=actor_user_id,
            )
            if assigned_driver:
                await get_emitter().emit_ride_assigned(
                    organization_id=organization_id,
                    ride_id=ride.id,
                    driver_id=best_driver["entity_id"],
                    driver_name=assigned_driver.driver.name if assigned_driver.driver else None,
                    actor_user_id=actor_user_id,
                    details={"workflow": "automated_recovery"},
                )
                broadcast_events += 1

        if policy.auto_escalation_enabled and not assigned_driver:
            escalation = cls._create_escalation(
                db,
                organization_id=organization_id,
                workflow_execution_id=workflow_execution_id,
                incident=incident,
                escalation_level=1,
                target_role="dispatcher",
                target_queue="dispatcher_escalation_queue",
                summary=incident.summary,
                details={
                    "best_driver": best_driver,
                    "best_provider": best_provider,
                    "incident_type": incident_type,
                },
                actor_user_id=actor_user_id,
            )
            await get_broadcaster().broadcast_event(
                event_type="workflow_escalated",
                payload={
                    "incident_id": incident.id,
                    "escalation_id": escalation.id,
                    "ride_id": ride.id,
                    "incident_type": incident_type,
                },
                organization_id=organization_id,
                subscription_types=[
                    SubscriptionType.DISPATCHER_BOARD.value,
                    SubscriptionType.WORKFLOW_EVENTS.value,
                ],
            )
            broadcast_events += 1

        cls._audit(
            db,
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            incident_id=incident.id,
            escalation_id=escalation.id if escalation else None,
            actor_user_id=actor_user_id,
            event_type="workflow.recovery.ride_processed",
            payload={
                "ride_id": ride.id,
                "incident_type": incident_type,
                "assigned_driver_id": getattr(assigned_driver, "driver_id", None),
            },
        )
        return {
            "incident": incident,
            "escalation": escalation,
            "recommendations": recommendations.get("recommendations", []),
            "broadcast_events": broadcast_events,
        }

    @classmethod
    def _classify_incident(cls, ride: HealthISFRide, policy: HealthISFAutomationPolicy) -> str:
        if ride.status in (RideStatus.ACCEPTED, RideStatus.IN_TRANSIT):
            return "stuck_ride"
        if ride.status == RideStatus.PENDING and ride.driver_id is None:
            return "no_driver_available" if policy.auto_reassign_enabled else "delayed_pickup"
        return "workflow_recovery"

    @classmethod
    def _select_driver_recommendation(cls, recommendations: dict[str, Any]) -> dict[str, Any] | None:
        for item in recommendations.get("recommendations", []):
            if item.get("entity_type") == "driver":
                return item
        return None

    @classmethod
    def _select_provider_recommendation(cls, recommendations: dict[str, Any]) -> dict[str, Any] | None:
        for item in recommendations.get("recommendations", []):
            if item.get("entity_type") == "provider":
                return item
        return None

    @classmethod
    def _create_execution(
        cls,
        db: Session,
        organization_id: str,
        workflow_name: str,
        trigger_type: str,
        policy: HealthISFAutomationPolicy,
        actor_user_id: str | None = None,
        ride_id: str | None = None,
        driver_id: str | None = None,
        input_payload: dict[str, Any] | None = None,
    ) -> HealthISFWorkflowExecution:
        execution = HealthISFWorkflowExecution(
            id=uuid4(),
            organization_id=organization_id,
            workflow_name=workflow_name,
            status=WorkflowExecutionStatus.RUNNING.value,
            trigger_type=trigger_type,
            ride_id=ride_id,
            driver_id=driver_id,
            policy_id=policy.id,
            input_payload=_json_dump(input_payload or {}),
            retry_count=0,
            max_attempts=policy.max_retry_attempts,
            approval_required=policy.approval_required,
            created_by_user_id=actor_user_id,
            started_at=now(),
            created_at=now(),
            updated_at=now(),
        )
        db.add(execution)
        db.flush()
        cls._audit(
            db,
            organization_id=organization_id,
            workflow_execution_id=execution.id,
            actor_user_id=actor_user_id,
            event_type=f"workflow.{workflow_name}.started",
            payload=input_payload or {},
        )
        return execution

    @classmethod
    def _create_incident(
        cls,
        db: Session,
        organization_id: str,
        workflow_execution_id: str | None,
        ride: HealthISFRide,
        incident_type: str,
        severity: str,
        summary: str,
        details: dict[str, Any],
        actor_user_id: str | None = None,
    ) -> HealthISFWorkflowIncident:
        incident = HealthISFWorkflowIncident(
            id=uuid4(),
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            ride_id=ride.id,
            driver_id=ride.driver_id,
            incident_type=incident_type,
            severity=severity,
            status=WorkflowIncidentStatus.OPEN.value,
            summary=summary,
            details=_json_dump(details),
            created_at=now(),
            updated_at=now(),
        )
        db.add(incident)
        db.flush()
        cls._audit(
            db,
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            incident_id=incident.id,
            actor_user_id=actor_user_id,
            event_type="workflow.incident.created",
            payload={"incident_type": incident_type, "ride_id": ride.id, "severity": severity},
        )
        return incident

    @classmethod
    def _create_escalation(
        cls,
        db: Session,
        organization_id: str,
        workflow_execution_id: str | None,
        incident: HealthISFWorkflowIncident,
        escalation_level: int,
        target_role: str,
        target_queue: str,
        summary: str,
        details: dict[str, Any],
        actor_user_id: str | None = None,
    ) -> HealthISFWorkflowEscalation:
        escalation = HealthISFWorkflowEscalation(
            id=uuid4(),
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            incident_id=incident.id,
            escalation_level=escalation_level,
            target_role=target_role,
            target_queue=target_queue,
            status=WorkflowEscalationStatus.ROUTED.value,
            summary=summary,
            details=_json_dump(details),
            created_at=now(),
        )
        db.add(escalation)
        db.flush()
        incident.status = WorkflowIncidentStatus.ACKNOWLEDGED.value
        incident.escalated_at = now()
        incident.updated_at = now()
        cls._audit(
            db,
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            incident_id=incident.id,
            escalation_id=escalation.id,
            actor_user_id=actor_user_id,
            event_type="workflow.escalation.routed",
            payload={"target_role": target_role, "target_queue": target_queue, "escalation_level": escalation_level},
        )
        return escalation

    @staticmethod
    def _audit(
        db: Session,
        organization_id: str,
        workflow_execution_id: str | None,
        actor_user_id: str | None,
        event_type: str,
        payload: dict[str, Any],
        incident_id: str | None = None,
        escalation_id: str | None = None,
    ) -> HealthISFWorkflowAuditLog:
        record = HealthISFWorkflowAuditLog(
            id=uuid4(),
            organization_id=organization_id,
            workflow_execution_id=workflow_execution_id,
            incident_id=incident_id,
            escalation_id=escalation_id,
            event_type=event_type,
            actor_user_id=actor_user_id,
            payload=_json_dump(payload),
            created_at=now(),
        )
        db.add(record)
        return record

    @staticmethod
    async def _broadcast_workflow_event(
        organization_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> int:
        broadcaster = get_broadcaster()
        return await broadcaster.broadcast_event(
            event_type=event_type,
            payload=payload,
            organization_id=organization_id,
            subscription_types=[
                SubscriptionType.DISPATCHER_BOARD.value,
                SubscriptionType.WORKFLOW_EVENTS.value,
            ],
        )


def serialize_workflow_execution(row: HealthISFWorkflowExecution) -> dict[str, Any]:
    return _workflow_execution_dict(row)


def serialize_workflow_incident(row: HealthISFWorkflowIncident) -> dict[str, Any]:
    return _workflow_incident_dict(row)


def serialize_workflow_escalation(row: HealthISFWorkflowEscalation) -> dict[str, Any]:
    return _workflow_escalation_dict(row)


def serialize_workflow_policy(row: HealthISFAutomationPolicy) -> dict[str, Any]:
    return _workflow_policy_dict(row)
