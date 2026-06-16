"""Supervised operational cognition for bounded runtime decision support."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.coordination_recommendation_pipeline import CoordinationRecommendationPipeline
from app.modules.health_isf.dispatch_orchestration_engine import DispatchOrchestrationEngine
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.operational_decision_engine import OperationalDecisionEngine
from app.modules.health_isf.operational_forecast_engine import OperationalForecastEngine
from app.modules.health_isf.operational_memory_engine import OperationalMemoryEngine
from app.modules.health_isf.operational_priority_service import OperationalPriorityService
from app.modules.health_isf.operational_recommendation_pipeline import OperationalRecommendationPipeline
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.operational_workflow_orchestration import build_geospatial_foundation
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.runtime_governor import get_runtime_governor


class OperationalCognitionEngine:
    @staticmethod
    def _clamp(value: float) -> float:
        return round(max(0.0, min(1.0, float(value))), 4)

    @staticmethod
    def _band(value: float) -> str:
        if value >= 0.82:
            return "critical"
        if value >= 0.62:
            return "high"
        if value >= 0.4:
            return "elevated"
        return "low"

    @staticmethod
    def _stable_id(organization_id: str, label: str, material: dict[str, Any]) -> str:
        digest = hashlib.sha256(
            json.dumps(
                {
                    "organization_id": organization_id,
                    "label": label,
                    "material": material,
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:16]
        return f"cog_{digest}"

    @classmethod
    def build_snapshot(
        cls,
        db: Session,
        *,
        organization_id: str,
        role: str = "dispatcher",
    ) -> dict[str, Any]:
        metrics = build_operational_metrics(db, organization_id=organization_id)
        geospatial_snapshot = build_geospatial_foundation(organization_id)
        sync_snapshot = OperationalSynchronizationEngine.synchronization_snapshot(organization_id)
        overload_snapshot = DispatchOrchestrationEngine.evaluate_overload(db, organization_id)
        queue_rows = DispatchOrchestrationEngine.prioritized_queue(db, organization_id, limit=50)
        dispatch_snapshot = {
            "summary": {
                "total": len(queue_rows),
                "emergency_recommendations": sum(1 for row in queue_rows if bool(row.get("is_emergency"))),
                "overloaded": bool(overload_snapshot.get("overloaded", False)),
                "safe_capacity": int(overload_snapshot.get("safe_capacity", 0) or 0),
                "queued": int(overload_snapshot.get("queued", 0) or 0),
                "escalated": int(overload_snapshot.get("escalated", 0) or 0),
            },
            "overload": overload_snapshot,
            "queue": queue_rows,
        }
        memory_snapshot = OperationalMemoryEngine.build_snapshot(db, organization_id=organization_id, role=role)
        history_features = OperationalMemoryService.history_features(db, organization_id=organization_id, role=role)
        decision_snapshot = OperationalRecommendationPipeline.build_snapshot(
            organization_id=organization_id,
            telemetry_metrics=metrics,
            geospatial_snapshot=geospatial_snapshot,
            dispatch_snapshot=dispatch_snapshot,
            sync_snapshot=sync_snapshot,
        )
        adaptive_forecast_snapshot = OperationalForecastEngine.build_snapshot(
            organization_id=organization_id,
            decision=decision_snapshot,
            memory=memory_snapshot,
            sync=sync_snapshot,
        )
        coordination_snapshot = CoordinationRecommendationPipeline.build_snapshot(
            organization_id=organization_id,
            metrics=metrics,
            decision=decision_snapshot,
            memory=memory_snapshot,
            adaptive_forecast=adaptive_forecast_snapshot,
            sync_snapshot=sync_snapshot,
        )
        runtime_governor_snapshot: dict[str, Any] = {}
        workflow_coordination: dict[str, Any] = {}
        distributed_governance: dict[str, Any] = {}
        websocket_health: dict[str, Any] = {}
        try:
            runtime_governor = get_runtime_governor()
            runtime_governor_snapshot = runtime_governor.get_health_snapshot() or {}
            workflow_coordination = runtime_governor.get_workflow_coordination_diagnostics(organization_id) or {}
            distributed_governance = runtime_governor.get_distributed_governance_diagnostics(organization_id) or {}
        except Exception:
            runtime_governor_snapshot = {}
            workflow_coordination = {}
            distributed_governance = {}

        try:
            broadcaster = get_broadcaster()
            websocket_health = broadcaster.get_runtime_reliability_diagnostics(organization_id=organization_id)
        except Exception:
            websocket_health = {}

        return cls.build_from_context(
            organization_id=organization_id,
            metrics=metrics,
            geospatial_snapshot=geospatial_snapshot,
            sync_snapshot=sync_snapshot,
            dispatch_snapshot=dispatch_snapshot,
            memory_snapshot=memory_snapshot,
            history_features=history_features,
            decision_snapshot=decision_snapshot,
            adaptive_forecast_snapshot=adaptive_forecast_snapshot,
            coordination_snapshot=coordination_snapshot,
            runtime_governor_snapshot=runtime_governor_snapshot,
            workflow_coordination=workflow_coordination,
            distributed_governance=distributed_governance,
            websocket_health=websocket_health,
        )

    @classmethod
    def build_from_context(
        cls,
        *,
        organization_id: str,
        metrics: dict[str, Any],
        geospatial_snapshot: dict[str, Any],
        sync_snapshot: dict[str, Any],
        dispatch_snapshot: dict[str, Any],
        memory_snapshot: dict[str, Any],
        history_features: dict[str, float],
        decision_snapshot: dict[str, Any],
        adaptive_forecast_snapshot: dict[str, Any],
        coordination_snapshot: dict[str, Any],
        runtime_governor_snapshot: dict[str, Any],
        workflow_coordination: dict[str, Any],
        distributed_governance: dict[str, Any],
        websocket_health: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        websocket_health = websocket_health or {}
        pressure = OperationalPriorityService.build_pressure_snapshot(
            metrics=metrics,
            geospatial_snapshot=geospatial_snapshot,
            sync_snapshot=sync_snapshot,
        )

        decision_recommendations = list(decision_snapshot.get("recommendations") or [])
        coordination_recommendations = list(coordination_snapshot.get("recommendations") or [])
        top_recommendations = [*decision_recommendations[:3], *coordination_recommendations[:3]]
        top_confidences = [float(item.get("confidence") or 0.0) for item in top_recommendations if isinstance(item, dict)]
        avg_top_confidence = sum(top_confidences) / max(1, len(top_confidences)) if top_confidences else 0.0

        pattern_summary = dict(memory_snapshot.get("pattern_summary") or {})
        recall_summary = dict(memory_snapshot.get("recall_summary") or {})
        incident_growth_ratio = float(history_features.get("incident_growth_ratio") or 0.0)
        incidents_60m = float(history_features.get("incidents_60m") or 0.0)
        incidents_360m = float(history_features.get("incidents_360m") or 0.0)
        executions_60m = float(history_features.get("executions_60m") or 0.0)
        predictions_60m = float(history_features.get("predictions_60m") or 0.0)

        distributed_queue_depth = int(distributed_governance.get("distributed_queue_depth", 0) or 0)
        active_runtimes = int(distributed_governance.get("active_runtimes", 0) or 0)
        task_reassignment_count = int(distributed_governance.get("task_reassignment_count", 0) or 0)
        runtime_failover_count = int(distributed_governance.get("runtime_failover_count", 0) or 0)
        isolation_violation_count = int(distributed_governance.get("isolation_violation_count", 0) or 0)
        pressure_warnings = list((distributed_governance.get("workload_pressure") or {}).get("warnings") or [])
        distributed_pressure = float((distributed_governance.get("workload_pressure") or {}).get("score", 0.0) or 0.0)
        recovery_ratios = dict(distributed_governance.get("recovery_failover_ratios") or {})

        queue_pressure = min(1.0, distributed_queue_depth / max(1.0, active_runtimes * 4.0) if active_runtimes else distributed_queue_depth / 8.0)
        history_pressure = min(1.0, (incident_growth_ratio * 0.25) + (incidents_60m / 24.0) + (predictions_60m / 40.0))
        continuity_risk = float(pressure.continuity_degradation_risk)
        escalated_pressure = float(pressure.escalation_surge)
        memory_drift = min(1.0, incident_growth_ratio / 2.0 + incidents_360m / 48.0)
        bottleneck_likelihood = cls._clamp(
            max(
                float((adaptive_forecast_snapshot.get("dispatch_bottleneck_forecast") or {}).get("value") or 0.0),
                float((adaptive_forecast_snapshot.get("continuity_degradation_forecast") or {}).get("value") or 0.0),
                queue_pressure,
            )
        )

        workflow_health_score = cls._clamp(
            1.0
            - (
                float(pressure.regional_congestion) * 0.14
                + float(pressure.driver_load_pressure) * 0.2
                + float(pressure.provider_queue_pressure) * 0.18
                + float(pressure.escalation_surge) * 0.16
                + continuity_risk * 0.16
                + queue_pressure * 0.09
                + history_pressure * 0.07
            )
        )
        runtime_stability_score = cls._clamp(workflow_health_score * 0.55 + (1.0 - bottleneck_likelihood) * 0.25 + (1.0 - continuity_risk) * 0.2)
        orchestration_confidence = cls._clamp(avg_top_confidence * 0.45 + (1.0 - bottleneck_likelihood) * 0.25 + (1.0 - memory_drift) * 0.15 + workflow_health_score * 0.15)
        execution_risk_score = cls._clamp(1.0 - runtime_stability_score + bottleneck_likelihood * 0.18 + memory_drift * 0.12 + queue_pressure * 0.08)
        recovery_confidence = cls._clamp(
            (1.0 - continuity_risk) * 0.34
            + (1.0 - queue_pressure) * 0.2
            + (1.0 - memory_drift) * 0.16
            + (1.0 - float(recovery_ratios.get("failure_ratio", 0.0) or 0.0)) * 0.18
            + workflow_health_score * 0.12
        )

        risk_level = cls._band(execution_risk_score)
        pressure_classification = "critical" if bottleneck_likelihood >= 0.82 else "high" if bottleneck_likelihood >= 0.62 else "elevated" if bottleneck_likelihood >= 0.4 else "steady"
        stability_assessment = "stable" if runtime_stability_score >= 0.76 else "watch" if runtime_stability_score >= 0.58 else "degraded" if runtime_stability_score >= 0.38 else "critical"
        anomaly_events = []
        if incident_growth_ratio >= 1.25:
            anomaly_events.append(
                {
                    "event_type": "runtime_drift",
                    "confidence": cls._clamp(min(1.0, incident_growth_ratio / 2.0)),
                    "summary": "Incident growth suggests operational drift beyond baseline history.",
                }
            )
        if queue_pressure >= 0.6 or pressure_warnings:
            anomaly_events.append(
                {
                    "event_type": "workload_pressure",
                    "confidence": cls._clamp(max(queue_pressure, distributed_pressure)),
                    "summary": "Workload pressure is elevated and may require supervised redistribution.",
                }
            )
        if continuity_risk >= 0.55:
            anomaly_events.append(
                {
                    "event_type": "continuity_degradation",
                    "confidence": cls._clamp(continuity_risk),
                    "summary": "Continuity risk indicates a likely need for checkpointed recovery planning.",
                }
            )
        if task_reassignment_count > 0 or runtime_failover_count > 0:
            anomaly_events.append(
                {
                    "event_type": "failover_activity",
                    "confidence": cls._clamp(min(1.0, (task_reassignment_count + runtime_failover_count) / 10.0)),
                    "summary": "Previous failover activity suggests supervision should prefer safe replay paths.",
                }
            )

        retry_strategy = "conservative"
        timeout_multiplier = 1.0
        queue_priority_policy = "standard"
        workload_redistribution = "local"
        degraded_fallback = "normal"
        recovery_sequence = [
            "evaluate_checkpoint",
            "reconcile_ownership",
            "resume_queued_workflow",
        ]
        congestion_mitigation = "monitor"

        if risk_level in {"high", "critical"}:
            retry_strategy = "bounded_exponential"
            timeout_multiplier = 1.6 if risk_level == "critical" else 1.35
            queue_priority_policy = "critical_first"
            workload_redistribution = "rebalance_to_low_pressure_workers"
            degraded_fallback = "checkpoint_restore_then_safe_replay"
            congestion_mitigation = "throttle_background_work"
            recovery_sequence = [
                "stabilize_runtime",
                "restore_checkpoint",
                "replay_safe_events",
                "resume_supervised_execution",
            ]
        elif risk_level == "elevated":
            retry_strategy = "adaptive_exponential"
            timeout_multiplier = 1.2
            queue_priority_policy = "priority_first"
            workload_redistribution = "selective_rebalance"
            degraded_fallback = "checkpoint_replay"
            congestion_mitigation = "delay_background_tasks"

        if bottleneck_likelihood < 0.3:
            congestion_mitigation = "normal"
            if risk_level == "low":
                retry_strategy = "conservative"
                timeout_multiplier = 1.0

        recovery_severity = "high" if execution_risk_score >= 0.82 else "medium" if execution_risk_score >= 0.58 else "low"
        checkpoint_strategy = "latest_safe_checkpoint"
        if int(runtime_governor_snapshot.get("checkpoint_restore_count", 0) or 0) == 0:
            checkpoint_strategy = "lease_snapshot_then_rollback"
        if recovery_confidence >= 0.78:
            checkpoint_strategy = "latest_safe_checkpoint"

        top_summary: list[dict[str, Any]] = []
        for item in top_recommendations[:6]:
            if not isinstance(item, dict):
                continue
            top_summary.append(
                {
                    "recommendation_id": str(item.get("recommendation_id") or cls._stable_id(organization_id, str(item.get("recommendation_type") or "recommendation"), item)),
                    "recommendation_type": str(item.get("recommendation_type") or item.get("coordination_type") or "recommendation"),
                    "confidence": cls._clamp(float(item.get("confidence") or 0.0)),
                    "priority_score": cls._clamp(float(item.get("priority_score") or item.get("score") or 0.0)),
                    "summary": str(item.get("operational_impact") or item.get("summary") or item.get("reasoning_summary") or "Supervised recommendation available."),
                }
            )

        return {
            "organization_id": organization_id,
            "generated_at": datetime.utcnow().isoformat(),
            "backend_authoritative": True,
            "tenant_scoped": True,
            "supervised": True,
            "recommendation_only": True,
            "approval_governed": True,
            "runtime_stability_score": runtime_stability_score,
            "orchestration_confidence": orchestration_confidence,
            "execution_risk_score": execution_risk_score,
            "execution_risk_level": risk_level,
            "workflow_health_score": workflow_health_score,
            "workload_pressure_classification": pressure_classification,
            "recovery_confidence": recovery_confidence,
            "bottleneck_likelihood": bottleneck_likelihood,
            "runtime_cognition": {
                "operational_state_evaluator": stability_assessment,
                "workflow_health_score": workflow_health_score,
                "runtime_pressure_analysis": {
                    "regional_congestion": pressure.regional_congestion,
                    "driver_load_pressure": pressure.driver_load_pressure,
                    "provider_queue_pressure": pressure.provider_queue_pressure,
                    "escalation_surge": pressure.escalation_surge,
                    "continuity_degradation_risk": pressure.continuity_degradation_risk,
                    "distributed_queue_pressure": round(queue_pressure, 4),
                },
                "execution_risk_classification": risk_level,
                "recovery_confidence_score": recovery_confidence,
                "degraded_runtime_interpretation": stability_assessment,
                "orchestration_stability_assessment": stability_assessment,
                "workflow_health_band": pressure_classification,
                "operational_state_summary": (
                    "runtime is stable" if stability_assessment == "stable" else
                    "runtime requires observation" if stability_assessment == "watch" else
                    "runtime is degraded" if stability_assessment == "degraded" else
                    "runtime is critically degraded"
                ),
            },
            "adaptive_execution_strategies": {
                "retry_strategy": retry_strategy,
                "timeout_multiplier": timeout_multiplier,
                "queue_prioritization": queue_priority_policy,
                "workload_redistribution": workload_redistribution,
                "degraded_state_fallback": degraded_fallback,
                "recovery_path_optimization": recovery_sequence,
                "runtime_congestion_mitigation": congestion_mitigation,
                "execution_domain_guardrails": [
                    "bounded_retries",
                    "approval_required",
                    "preserve_lease_ownership",
                    "avoid_uncontrolled_replay",
                ],
            },
            "supervised_orchestration_reasoning": {
                "execution_chain_analysis": workflow_coordination,
                "dependency_aware_orchestration_reasoning": {
                    "active_chain_count": int(workflow_coordination.get("active_workflow_count", 0) or 0),
                    "queued_task_count": int(workflow_coordination.get("queued_task_count", 0) or 0),
                    "recovery_attempts": int(workflow_coordination.get("retry_attempts", 0) or 0),
                    "interruptions": int(runtime_governor_snapshot.get("interrupted_execution_recovery_count", 0) or 0),
                },
                "stalled_workflow_detection": bool(runtime_governor_snapshot.get("stuck_executions_detected", 0) or queue_pressure >= 0.75),
                "cascading_failure_prediction": {
                    "value": cls._clamp(max(continuity_risk, bottleneck_likelihood, history_pressure)),
                    "confidence": cls._clamp(max(continuity_risk, bottleneck_likelihood)),
                },
                "workflow_anomaly_detection": anomaly_events,
                "orchestration_bottleneck_analysis": {
                    "bottleneck_likelihood": bottleneck_likelihood,
                    "distributed_pressure": round(distributed_pressure, 4),
                    "queue_pressure": round(queue_pressure, 4),
                    "pressure_warnings": pressure_warnings,
                },
                "operational_recommendation_engine": top_summary,
            },
            "cognitive_recovery_planning": {
                "recovery_path_selection": degraded_fallback,
                "interruption_severity_assessment": recovery_severity,
                "checkpoint_restoration_strategy": checkpoint_strategy,
                "safe_replay_recommendation": bool(risk_level in {"high", "critical"} or continuity_risk >= 0.45),
                "failover_confidence_scoring": recovery_confidence,
                "runtime_stabilization_sequencing": recovery_sequence,
                "orchestration_continuity_planning": {
                    "continuity_plan": "retain supervised ownership, restore safe checkpoint, and resume only bounded retries",
                    "replay_boundary": "latest_safe_sequence",
                    "ownership_reconciliation": bool(runtime_failover_count > 0 or task_reassignment_count > 0),
                    "checkpoint_restore_count": int(runtime_governor_snapshot.get("checkpoint_restore_count", 0) or 0),
                },
            },
            "operational_memory_intelligence": {
                "historical_runtime_pattern_analysis": {
                    "incidents_60m": incidents_60m,
                    "incidents_360m": incidents_360m,
                    "executions_60m": executions_60m,
                    "predictions_60m": predictions_60m,
                    "incident_growth_ratio": round(incident_growth_ratio, 4),
                },
                "recurring_failure_pattern_recognition": {
                    "recognized": bool(incident_growth_ratio >= 1.15 or runtime_failover_count > 0 or continuity_risk >= 0.5),
                    "signals": [
                        signal for signal, enabled in {
                            "incident_growth": incident_growth_ratio >= 1.15,
                            "continuity_risk": continuity_risk >= 0.5,
                            "queue_growth": queue_pressure >= 0.6,
                            "failover_activity": runtime_failover_count > 0,
                        }.items() if enabled
                    ],
                },
                "execution_success_failure_learning": {
                    "success_bias": round(max(0.0, 1.0 - execution_risk_score), 4),
                    "failure_bias": round(execution_risk_score, 4),
                    "history_features": history_features,
                },
                "workload_behavior_profiling": {
                    "profile": "bursty" if incident_growth_ratio >= 1.25 else "degraded" if risk_level in {"high", "critical"} else "steady",
                    "pressure_classification": pressure_classification,
                    "distributed_pressure": round(distributed_pressure, 4),
                },
                "orchestration_trend_analysis": {
                    "trend": "worsening" if incident_growth_ratio >= 1.2 or queue_pressure >= 0.6 else "stable",
                    "recall_summary": recall_summary,
                    "pattern_summary": pattern_summary,
                },
                "runtime_drift_detection": {
                    "detected": bool(incident_growth_ratio >= 1.2 or memory_drift >= 0.45),
                    "memory_drift": round(memory_drift, 4),
                    "queue_pressure": round(queue_pressure, 4),
                },
                "operational_optimization_history": {
                    "history_summary": memory_snapshot.get("recall_summary") or {},
                    "priority_history": memory_snapshot.get("pattern_summary") or {},
                },
            },
            "diagnostics_intelligence_layer": {
                "runtime_stability_score": runtime_stability_score,
                "orchestration_confidence": orchestration_confidence,
                "execution_risk_level": risk_level,
                "workload_pressure_classification": pressure_classification,
                "recovery_confidence": recovery_confidence,
                "anomaly_detection_events": anomaly_events,
                "bottleneck_likelihood": bottleneck_likelihood,
                "workflow_health_score": workflow_health_score,
                "adaptive_strategy_selections": {
                    "retry_strategy": retry_strategy,
                    "timeout_multiplier": timeout_multiplier,
                    "queue_prioritization": queue_priority_policy,
                    "workload_redistribution": workload_redistribution,
                    "degraded_state_fallback": degraded_fallback,
                    "recovery_path_optimization": recovery_sequence,
                    "runtime_congestion_mitigation": congestion_mitigation,
                },
                "operational_recommendation_summaries": top_summary,
                "runtime_governor": runtime_governor_snapshot,
                "workflow_coordination": workflow_coordination,
                "distributed_governance": distributed_governance,
                "websocket_health": websocket_health,
                "decision_snapshot": decision_snapshot,
                "adaptive_forecast_snapshot": adaptive_forecast_snapshot,
                "coordination_snapshot": coordination_snapshot,
            },
            "operational_recommendation_summaries": top_summary,
            "cognitive_diagnostics": {
                "runtime_stability_score": runtime_stability_score,
                "orchestration_confidence": orchestration_confidence,
                "execution_risk_level": risk_level,
                "workload_pressure_classification": pressure_classification,
                "recovery_confidence": recovery_confidence,
                "anomaly_detection_events": anomaly_events,
                "bottleneck_likelihood": bottleneck_likelihood,
                "workflow_health_score": workflow_health_score,
                "adaptive_strategy_selections": {
                    "retry_strategy": retry_strategy,
                    "timeout_multiplier": timeout_multiplier,
                    "queue_prioritization": queue_priority_policy,
                    "workload_redistribution": workload_redistribution,
                    "degraded_state_fallback": degraded_fallback,
                    "recovery_path_optimization": recovery_sequence,
                    "runtime_congestion_mitigation": congestion_mitigation,
                },
                "operational_recommendation_summaries": top_summary,
            },
        }
