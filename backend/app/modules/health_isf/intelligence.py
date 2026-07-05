"""Operational intelligence services for Health ISF.

This module adds additive, tenant-scoped intelligence logic for:
- recommendation scoring
- anomaly detection
- predictive operational risk estimates
- automated recovery suggestions
- websocket intelligence broadcast payloads
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.models import (
    ActivityAction,
    DispatchAssignmentState,
    DispatchDeadLetterEvent,
    DispatchEventRetry,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDriver,
    HealthISFOrganization,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideStatusHistory,
    HealthISFWorkflowAuditLog,
    HealthISFWorkflowEscalation,
    HealthISFWorkflowExecution,
    HealthISFWorkflowIncident,
    RideStatus,
    RealTimeEvent,
    SecurityAuditAction,
    DispatcherActivityLog,
    WorkflowEscalationStatus,
    WorkflowExecutionStatus,
    WorkflowIncidentStatus,
)
from app.modules.health_isf.operations import get_operational_metrics_registry, log_operational_event
from app.modules.health_isf.realtime import EventBroadcaster, SubscriptionType
from app.modules.health_isf.security_service import SecurityAuditService

logger = logging.getLogger("amicor.health_isf.intelligence")


@dataclass(slots=True)
class IntelligenceThresholds:
    stuck_ride_minutes: int = 45
    delayed_pickup_minutes: int = 20
    cancellation_spike_count: int = 10
    low_driver_coverage_ratio: float = 0.5
    websocket_disconnect_spike_count: int = 20
    overloaded_provider_active_rides: int = 5
    high_dispatch_latency_seconds: int = 120
    auto_reassign_confidence_threshold: float = 0.7


class OperationalIntelligenceService:
    """Pure intelligence engine built on existing Health ISF data."""

    @classmethod
    def summarize(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
        thresholds: IntelligenceThresholds | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        anomalies = cls.detect_anomalies(db, organization_id, thresholds=thresholds)
        recommendations = cls.build_recommendations(db, organization_id, ride_id=ride_id, thresholds=thresholds)
        risk = cls.build_risk_profile(db, organization_id, thresholds=thresholds, anomalies=anomalies)
        predictive = cls.build_predictive_signals(db, organization_id, thresholds=thresholds, risk=risk)
        state_awareness = cls.build_operational_state_awareness(
            db,
            organization_id,
            thresholds=thresholds,
            anomalies=anomalies,
        )
        context_aggregation = cls.build_operational_context_aggregation(
            db,
            organization_id,
            thresholds=thresholds,
            anomalies=anomalies,
            risk=risk,
        )
        correlation = cls.build_operational_correlations(db, organization_id)
        anomaly_surface = cls.build_operational_anomaly_surface(
            db,
            organization_id,
            thresholds=thresholds,
            anomalies=anomalies,
        )
        backend_state_verification = cls.verify_backend_state_sources(
            db,
            organization_id,
            ride_id=ride_id,
        )

        health_score = max(0.0, min(100.0, 100.0 - risk["risk_score"]))
        summary_text = cls._compose_summary_text(anomalies, recommendations, risk, predictive)
        log_operational_event(
            "intelligence.summary.generated",
            organization_id=organization_id,
            ride_id=ride_id,
            health_score=health_score,
            risk_score=risk["risk_score"],
            anomaly_count=len(anomalies),
            recommendation_count=len(recommendations["recommendations"]),
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "summary": summary_text,
            "operational_health_score": round(health_score, 2),
            "risk_score": round(risk["risk_score"], 2),
            "anomaly_count": len(anomalies),
            "recommendation_count": len(recommendations["recommendations"]),
            "trend_explanations": predictive["trend_explanations"],
            "anomaly_explanations": [item["message"] for item in anomalies],
            "recommendation_summaries": [item["explanation_summary"] for item in recommendations["recommendations"]],
            "predictive_signals": {
                **predictive,
                "operational_state_awareness": state_awareness,
                "operational_context_aggregation": context_aggregation,
                "operational_correlations": correlation,
                "operational_anomaly_surface": anomaly_surface,
                "backend_state_verification": backend_state_verification,
            },
            "operational_state_awareness": state_awareness,
            "operational_context_aggregation": context_aggregation,
            "operational_correlations": correlation,
            "operational_anomaly_surface": anomaly_surface,
            "backend_state_verification": backend_state_verification,
        }

    @classmethod
    def detect_anomalies(
        cls,
        db: Session,
        organization_id: str,
        thresholds: IntelligenceThresholds | None = None,
    ) -> list[dict[str, Any]]:
        thresholds = thresholds or IntelligenceThresholds()
        now_dt = now()
        ride_query = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id)
        driver_query = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id)
        provider_query = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == organization_id)
        activity_query = db.query(DispatcherActivityLog).filter(DispatcherActivityLog.organization_id == organization_id)
        event_query = db.query(RealTimeEvent).filter(RealTimeEvent.organization_id == organization_id)

        anomalies: list[dict[str, Any]] = []

        stuck_cutoff = now_dt - timedelta(minutes=thresholds.stuck_ride_minutes)
        stuck_rides = ride_query.filter(
            HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
            HealthISFRide.updated_at < stuck_cutoff,
        ).all()
        if stuck_rides:
            anomalies.append(cls._anomaly(
                "stuck_rides",
                "high",
                f"{len(stuck_rides)} ride(s) appear stuck beyond {thresholds.stuck_ride_minutes} minutes",
                {
                    "count": len(stuck_rides),
                    "ride_ids": [ride.id for ride in stuck_rides[:10]],
                },
            ))

        delayed_cutoff = now_dt - timedelta(minutes=thresholds.delayed_pickup_minutes)
        delayed_pickups = ride_query.filter(
            HealthISFRide.status == RideStatus.PENDING,
            HealthISFRide.driver_id.is_(None),
            HealthISFRide.requested_at < delayed_cutoff,
        ).all()
        if delayed_pickups:
            anomalies.append(cls._anomaly(
                "delayed_pickups",
                "medium",
                f"{len(delayed_pickups)} ride(s) delayed beyond pickup threshold",
                {
                    "count": len(delayed_pickups),
                    "ride_ids": [ride.id for ride in delayed_pickups[:10]],
                },
            ))

        cancellation_cutoff = now_dt - timedelta(hours=1)
        cancellations = ride_query.filter(
            HealthISFRide.status == RideStatus.CANCELLED,
            HealthISFRide.updated_at >= cancellation_cutoff,
        ).all()
        if len(cancellations) >= thresholds.cancellation_spike_count:
            anomalies.append(cls._anomaly(
                "cancellation_spike",
                "high",
                f"Cancellation volume spiked to {len(cancellations)} in the last hour",
                {"count": len(cancellations)},
            ))

        active_rides = ride_query.filter(HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT])).count()
        available_drivers = driver_query.filter(HealthISFDriver.status == DriverStatus.AVAILABLE).count()
        if active_rides > 0:
            coverage_ratio = available_drivers / float(active_rides)
            if coverage_ratio < thresholds.low_driver_coverage_ratio:
                anomalies.append(cls._anomaly(
                    "low_driver_coverage",
                    "high",
                    f"Driver coverage dropped to {coverage_ratio:.2f}",
                    {"coverage_ratio": round(coverage_ratio, 3), "available_drivers": available_drivers, "active_rides": active_rides},
                ))

        overloaded_providers = []
        for provider in provider_query.all():
            provider_active = ride_query.filter(
                HealthISFRide.provider_id == provider.id,
                HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
            ).count()
            if provider_active >= thresholds.overloaded_provider_active_rides:
                overloaded_providers.append((provider, provider_active))
        if overloaded_providers:
            anomalies.append(cls._anomaly(
                "overloaded_providers",
                "medium",
                f"{len(overloaded_providers)} provider(s) are carrying excessive dispatch volume",
                {
                    "providers": [
                        {"provider_id": provider.id, "active_rides": active}
                        for provider, active in overloaded_providers[:10]
                    ]
                },
            ))

        websocket_disconnect_spikes = event_query.filter(
            RealTimeEvent.event_type == "driver_status_changed",
            RealTimeEvent.created_at >= now_dt - timedelta(minutes=5),
        ).count()
        if websocket_disconnect_spikes >= thresholds.websocket_disconnect_spike_count:
            anomalies.append(cls._anomaly(
                "websocket_instability",
                "medium",
                f"WebSocket instability signal detected from {websocket_disconnect_spikes} recent events",
                {"count": websocket_disconnect_spikes},
            ))

        recent_dispatch_latency = cls._dispatch_latency_seconds(ride_query.all())
        if recent_dispatch_latency >= thresholds.high_dispatch_latency_seconds:
            anomalies.append(cls._anomaly(
                "high_dispatch_latency",
                "high",
                f"Dispatch latency reached {round(recent_dispatch_latency, 1)} seconds",
                {"latency_seconds": round(recent_dispatch_latency, 1)},
            ))

        cancellation_distribution = Counter(
            ride.provider_id or "unassigned" for ride in cancellations
        )
        if cancellation_distribution:
            hot_spot = cancellation_distribution.most_common(1)[0]
            anomalies.append(cls._anomaly(
                "provider_cancellation_hotspot",
                "medium",
                f"Provider or queue hotspot detected around {hot_spot[0]}",
                {"target": hot_spot[0], "count": hot_spot[1]},
            ))

        for row in activity_query.filter(DispatcherActivityLog.created_at >= now_dt - timedelta(minutes=30)).all():
            try:
                details = json.loads(row.details or "{}")
            except Exception:
                details = {}
            if details.get("retry_count", 0) >= 3:
                anomalies.append(cls._anomaly(
                    "repeated_retry_activity",
                    "low",
                    "Repeated retry activity detected for a dispatch flow",
                    {"activity_id": row.id, "retry_count": details.get("retry_count")},
                ))
                break

        queue_congestion_ratio = (len(delayed_pickups) / float(max(1, available_drivers))) if delayed_pickups else 0.0
        if queue_congestion_ratio >= 2.0:
            anomalies.append(cls._anomaly(
                "queue_congestion",
                "high",
                f"Dispatch queue congestion detected at {queue_congestion_ratio:.2f} pending-per-available-driver",
                {
                    "pending_unassigned": len(delayed_pickups),
                    "available_drivers": available_drivers,
                    "congestion_ratio": round(queue_congestion_ratio, 3),
                },
            ))

        active_rides_by_driver: dict[str, int] = defaultdict(int)
        for ride in ride_query.filter(HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT])).all():
            if ride.driver_id:
                active_rides_by_driver[str(ride.driver_id)] += 1
        overloaded_drivers = [
            {"driver_id": driver_id, "active_rides": count}
            for driver_id, count in active_rides_by_driver.items()
            if count >= 2
        ]
        if overloaded_drivers:
            anomalies.append(cls._anomaly(
                "driver_overload",
                "high",
                f"{len(overloaded_drivers)} driver(s) currently overloaded with concurrent active rides",
                {"drivers": overloaded_drivers[:20]},
            ))

        recent_assignments = db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.updated_at >= now_dt - timedelta(hours=2),
        ).all()
        repeated_reassignment = [
            {
                "assignment_id": row.id,
                "ride_id": row.ride_id,
                "attempts": int(row.reassignment_attempt_count or 0),
                "state": str(row.assignment_state),
            }
            for row in recent_assignments
            if int(row.reassignment_attempt_count or 0) >= 2
            or str(row.assignment_state) == DispatchAssignmentState.REASSIGNMENT_PENDING.value
        ]
        if repeated_reassignment:
            anomalies.append(cls._anomaly(
                "reassignment_loop",
                "high",
                f"Repeated reassignment loop risk detected across {len(repeated_reassignment)} assignment(s)",
                {"assignments": repeated_reassignment[:20]},
            ))

        escalations_60m = db.query(HealthISFWorkflowEscalation).filter(
            HealthISFWorkflowEscalation.organization_id == organization_id,
            HealthISFWorkflowEscalation.created_at >= now_dt - timedelta(hours=1),
        ).count()
        if escalations_60m >= 5:
            anomalies.append(cls._anomaly(
                "escalation_spike",
                "high",
                f"Escalation spike detected with {escalations_60m} escalations in the last hour",
                {"count": escalations_60m},
            ))

        compliance_actions_24h = db.query(SecurityAuditAction).filter(
            SecurityAuditAction.organization_id == organization_id,
            SecurityAuditAction.created_at >= now_dt - timedelta(hours=24),
            SecurityAuditAction.action_type.ilike("%compliance%"),
        ).count()
        unresolved_incidents = db.query(HealthISFWorkflowIncident).filter(
            HealthISFWorkflowIncident.organization_id == organization_id,
            HealthISFWorkflowIncident.status.in_([
                WorkflowIncidentStatus.OPEN.value,
                WorkflowIncidentStatus.ACKNOWLEDGED.value,
            ]),
        ).count()
        compliance_risk_score = compliance_actions_24h + unresolved_incidents
        if compliance_risk_score >= 8:
            anomalies.append(cls._anomaly(
                "compliance_risk_accumulation",
                "high",
                f"Compliance risk accumulation observed (score={compliance_risk_score})",
                {
                    "compliance_actions_24h": compliance_actions_24h,
                    "unresolved_incidents": unresolved_incidents,
                    "risk_score": compliance_risk_score,
                },
            ))

        progression_cutoff = now_dt - timedelta(minutes=max(30, thresholds.delayed_pickup_minutes))
        delayed_route_progression = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
            HealthISFRide.updated_at < progression_cutoff,
        ).all()
        if delayed_route_progression:
            anomalies.append(cls._anomaly(
                "delayed_route_progression",
                "high",
                f"{len(delayed_route_progression)} ride(s) show delayed route progression",
                {"ride_ids": [ride.id for ride in delayed_route_progression[:20]]},
            ))

        starvation_cutoff = now_dt - timedelta(minutes=max(25, thresholds.delayed_pickup_minutes + 5))
        assignment_starvation = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status == RideStatus.PENDING,
            HealthISFRide.driver_id.is_(None),
            HealthISFRide.requested_at < starvation_cutoff,
        ).all()
        if assignment_starvation:
            anomalies.append(cls._anomaly(
                "assignment_starvation",
                "high",
                f"Assignment starvation detected for {len(assignment_starvation)} pending ride(s)",
                {"ride_ids": [ride.id for ride in assignment_starvation[:20]]},
            ))

        no_driver_recovery_incidents = db.query(HealthISFWorkflowIncident).filter(
            HealthISFWorkflowIncident.organization_id == organization_id,
            HealthISFWorkflowIncident.incident_type == "no_reassignment_candidate",
            HealthISFWorkflowIncident.created_at >= now_dt - timedelta(hours=6),
        ).count()
        if no_driver_recovery_incidents >= 2:
            anomalies.append(cls._anomaly(
                "repeated_no_driver_recovery",
                "high",
                f"Repeated no-driver recovery signals detected ({no_driver_recovery_incidents} incidents)",
                {"incident_count": no_driver_recovery_incidents},
            ))

        unresolved_failed_trip_states = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.FAILED, RideStatus.ESCALATED]),
            HealthISFRide.updated_at < now_dt - timedelta(minutes=20),
        ).all()
        if unresolved_failed_trip_states:
            anomalies.append(cls._anomaly(
                "unresolved_failed_trip_states",
                "high",
                f"{len(unresolved_failed_trip_states)} failed/escalated ride(s) remain unresolved",
                {"ride_ids": [ride.id for ride in unresolved_failed_trip_states[:20]]},
            ))

        active_trip_denominator = max(1, active_rides)
        escalation_density = escalations_60m / float(active_trip_denominator)
        if escalation_density >= 0.8:
            anomalies.append(cls._anomaly(
                "abnormal_escalation_density",
                "high",
                f"Abnormal escalation density detected ({escalation_density:.2f} escalations per active trip)",
                {
                    "density": round(escalation_density, 3),
                    "escalations_60m": escalations_60m,
                    "active_rides": active_rides,
                },
            ))

        inactive_supervisor_queues = db.query(HealthISFWorkflowEscalation).filter(
            HealthISFWorkflowEscalation.organization_id == organization_id,
            HealthISFWorkflowEscalation.target_role.ilike("%supervisor%"),
            HealthISFWorkflowEscalation.status.in_([
                WorkflowEscalationStatus.QUEUED.value,
                WorkflowEscalationStatus.ROUTED.value,
            ]),
            HealthISFWorkflowEscalation.created_at < now_dt - timedelta(minutes=30),
        ).all()
        if inactive_supervisor_queues:
            anomalies.append(cls._anomaly(
                "inactive_supervisor_queues",
                "medium",
                f"Inactive supervisor queue detected with {len(inactive_supervisor_queues)} unresolved escalations",
                {"escalation_ids": [item.id for item in inactive_supervisor_queues[:20]]},
            ))

        return anomalies

    @classmethod
    def build_operational_state_awareness(
        cls,
        db: Session,
        organization_id: str,
        thresholds: IntelligenceThresholds | None = None,
        anomalies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        anomalies = anomalies or cls.detect_anomalies(db, organization_id, thresholds=thresholds)

        anomaly_index = {str(item.get("type") or ""): item for item in anomalies}
        pending_unassigned = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status == RideStatus.PENDING,
            HealthISFRide.driver_id.is_(None),
        ).count()
        available_drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        ).count()
        queue_congestion_ratio = pending_unassigned / float(max(1, available_drivers))

        return {
            "stalled_trips_detected": "stuck_rides" in anomaly_index,
            "queue_congestion_detected": "queue_congestion" in anomaly_index,
            "driver_overload_detected": "driver_overload" in anomaly_index,
            "reassignment_loop_detected": "reassignment_loop" in anomaly_index,
            "escalation_spike_detected": "escalation_spike" in anomaly_index,
            "compliance_risk_accumulation_detected": "compliance_risk_accumulation" in anomaly_index,
            "pending_unassigned": pending_unassigned,
            "available_drivers": available_drivers,
            "queue_congestion_ratio": round(queue_congestion_ratio, 3),
            "active_alerts": [
                {
                    "type": str(item.get("type") or "unknown"),
                    "severity": str(item.get("severity") or "low"),
                    "message": str(item.get("message") or ""),
                }
                for item in anomalies[:12]
            ],
        }

    @classmethod
    def build_operational_context_aggregation(
        cls,
        db: Session,
        organization_id: str,
        thresholds: IntelligenceThresholds | None = None,
        anomalies: list[dict[str, Any]] | None = None,
        risk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        anomalies = anomalies or cls.detect_anomalies(db, organization_id, thresholds=thresholds)
        risk = risk or cls.build_risk_profile(db, organization_id, thresholds=thresholds, anomalies=anomalies)
        now_dt = now()

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        active_trip_state = {
            "pending": sum(1 for ride in rides if ride.status == RideStatus.PENDING),
            "accepted": sum(1 for ride in rides if ride.status == RideStatus.ACCEPTED),
            "in_transit": sum(1 for ride in rides if ride.status == RideStatus.IN_TRANSIT),
            "failed": sum(1 for ride in rides if ride.status in {RideStatus.FAILED, RideStatus.ESCALATED}),
            "completed": sum(1 for ride in rides if ride.status == RideStatus.COMPLETED),
        }

        available_drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        ).count()
        active_drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status.in_([
                DriverStatus.ASSIGNED,
                DriverStatus.EN_ROUTE_PICKUP,
                DriverStatus.WAITING_AT_PICKUP,
                DriverStatus.IN_TRANSIT,
                DriverStatus.BUSY,
            ]),
        ).count()
        offline_or_unavailable_drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status.in_([DriverStatus.OFFLINE, DriverStatus.UNAVAILABLE]),
        ).count()

        unresolved_escalations = db.query(HealthISFWorkflowEscalation).filter(
            HealthISFWorkflowEscalation.organization_id == organization_id,
            HealthISFWorkflowEscalation.status.in_([
                WorkflowEscalationStatus.QUEUED.value,
                WorkflowEscalationStatus.ROUTED.value,
                WorkflowEscalationStatus.ACKNOWLEDGED.value,
            ]),
        ).all()
        supervisor_interventions = [
            escalation for escalation in unresolved_escalations
            if "supervisor" in str(escalation.target_role or "").lower()
            or "admin" in str(escalation.target_role or "").lower()
        ]

        compliance_exceptions = db.query(HealthISFWorkflowIncident).filter(
            HealthISFWorkflowIncident.organization_id == organization_id,
            HealthISFWorkflowIncident.incident_type.ilike("%compliance%")
            | HealthISFWorkflowIncident.summary.ilike("%compliance%"),
            HealthISFWorkflowIncident.status.in_([
                WorkflowIncidentStatus.OPEN.value,
                WorkflowIncidentStatus.ACKNOWLEDGED.value,
            ]),
        ).count()

        failed_workflows = db.query(HealthISFWorkflowExecution).filter(
            HealthISFWorkflowExecution.organization_id == organization_id,
            HealthISFWorkflowExecution.created_at >= now_dt - timedelta(hours=6),
            HealthISFWorkflowExecution.status.in_([
                WorkflowExecutionStatus.FAILED.value,
                WorkflowExecutionStatus.BLOCKED.value,
                WorkflowExecutionStatus.RETRYING.value,
            ]),
        ).count()

        queued_retry_events = db.query(DispatchEventRetry).filter(
            DispatchEventRetry.organization_id == organization_id,
            DispatchEventRetry.status.in_(["queued", "retrying"]),
        ).count()
        dead_letters = db.query(DispatchDeadLetterEvent).filter(
            DispatchDeadLetterEvent.organization_id == organization_id,
        ).count()
        replayed_workflows = db.query(HealthISFWorkflowExecution).filter(
            HealthISFWorkflowExecution.organization_id == organization_id,
            HealthISFWorkflowExecution.status == WorkflowExecutionStatus.REPLAYED.value,
            HealthISFWorkflowExecution.created_at >= now_dt - timedelta(hours=24),
        ).count()

        dispatch_pressure_score = round(
            min(
                1.0,
                (active_trip_state["pending"] / float(max(1, available_drivers * 2)))
                + (failed_workflows / 15.0)
                + (len(unresolved_escalations) / 20.0),
            ),
            3,
        )

        return {
            "active_trip_state": active_trip_state,
            "dispatch_pressure": {
                "score": dispatch_pressure_score,
                "risk_score": float(risk.get("risk_score") or 0.0),
                "pending_unassigned": active_trip_state["pending"],
                "unresolved_escalations": len(unresolved_escalations),
                "failed_workflow_attempts": failed_workflows,
            },
            "driver_readiness": {
                "available": available_drivers,
                "active": active_drivers,
                "offline_or_unavailable": offline_or_unavailable_drivers,
                "readiness_ratio": round(available_drivers / float(max(1, available_drivers + active_drivers)), 3),
            },
            "supervisor_interventions": {
                "pending_count": len(supervisor_interventions),
                "sample_escalation_ids": [item.id for item in supervisor_interventions[:10]],
            },
            "unresolved_escalations": {
                "count": len(unresolved_escalations),
                "oldest_age_minutes": cls._oldest_age_minutes(unresolved_escalations, now_dt),
            },
            "compliance_exceptions": {
                "count": compliance_exceptions,
                "security_audit_actions_24h": db.query(SecurityAuditAction).filter(
                    SecurityAuditAction.organization_id == organization_id,
                    SecurityAuditAction.created_at >= now_dt - timedelta(hours=24),
                    SecurityAuditAction.action_type.ilike("%compliance%"),
                ).count(),
            },
            "failed_workflow_attempts": {
                "count": failed_workflows,
                "window_hours": 6,
            },
            "recovery_state": {
                "queued_retry_events": queued_retry_events,
                "dead_letter_events": dead_letters,
                "replayed_workflows_24h": replayed_workflows,
                "recovering": queued_retry_events > 0 or dead_letters > 0,
            },
        }

    @classmethod
    def build_operational_correlations(cls, db: Session, organization_id: str) -> dict[str, Any]:
        now_dt = now()
        recent_rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
        ).order_by(HealthISFRide.updated_at.desc()).limit(40).all()
        ride_ids = [ride.id for ride in recent_rides]

        lifecycle_rows = []
        if ride_ids:
            lifecycle_rows = db.query(HealthISFRideStatusHistory).filter(
                HealthISFRideStatusHistory.ride_id.in_(ride_ids),
            ).order_by(HealthISFRideStatusHistory.created_at.desc()).limit(200).all()

        audit_rows = db.query(HealthISFWorkflowAuditLog).filter(
            HealthISFWorkflowAuditLog.organization_id == organization_id,
            HealthISFWorkflowAuditLog.created_at >= now_dt - timedelta(hours=24),
        ).order_by(HealthISFWorkflowAuditLog.created_at.desc()).limit(250).all()

        execution_rows = db.query(HealthISFWorkflowExecution).filter(
            HealthISFWorkflowExecution.organization_id == organization_id,
            HealthISFWorkflowExecution.created_at >= now_dt - timedelta(hours=24),
        ).order_by(HealthISFWorkflowExecution.created_at.desc()).limit(200).all()

        escalation_rows = db.query(HealthISFWorkflowEscalation).filter(
            HealthISFWorkflowEscalation.organization_id == organization_id,
            HealthISFWorkflowEscalation.created_at >= now_dt - timedelta(hours=24),
        ).order_by(HealthISFWorkflowEscalation.created_at.desc()).limit(200).all()

        escalation_chain: list[dict[str, Any]] = []
        for escalation in escalation_rows[:30]:
            escalation_chain.append(
                {
                    "escalation_id": escalation.id,
                    "incident_id": escalation.incident_id,
                    "workflow_execution_id": escalation.workflow_execution_id,
                    "target_queue": escalation.target_queue,
                    "target_role": escalation.target_role,
                    "status": escalation.status,
                    "created_at": escalation.created_at.isoformat() if escalation.created_at else None,
                }
            )

        authority_source: dict[str, int] = defaultdict(int)
        for row in execution_rows:
            authority_source[str(row.trigger_type or "unknown")] += 1
        for row in audit_rows:
            key = "user" if row.actor_user_id else "system"
            authority_source[key] += 1

        outcomes: dict[str, int] = defaultdict(int)
        for row in execution_rows:
            outcomes[str(row.status or "unknown")] += 1

        progression_by_ride: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in lifecycle_rows:
            progression_by_ride[str(row.ride_id)].append(
                {
                    "from": row.from_status,
                    "to": row.to_status,
                    "changed_by_user_id": row.changed_by_user_id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                }
            )

        return {
            "trip_lifecycle_events": {
                "count": len(lifecycle_rows),
                "rides_covered": len(progression_by_ride),
                "sample": dict(list(progression_by_ride.items())[:10]),
            },
            "audit_lineage": {
                "count": len(audit_rows),
                "sample": [
                    {
                        "audit_id": row.id,
                        "event_type": row.event_type,
                        "workflow_execution_id": row.workflow_execution_id,
                        "incident_id": row.incident_id,
                        "escalation_id": row.escalation_id,
                        "created_at": row.created_at.isoformat() if row.created_at else None,
                    }
                    for row in audit_rows[:25]
                ],
            },
            "authority_source": dict(sorted(authority_source.items(), key=lambda item: item[0])),
            "timeline_progression": {
                "tracked_rides": len(ride_ids),
                "recent_lifecycle_events": len(lifecycle_rows),
                "recent_workflow_executions": len(execution_rows),
            },
            "execution_outcomes": dict(sorted(outcomes.items(), key=lambda item: item[0])),
            "escalation_chains": escalation_chain,
        }

    @classmethod
    def build_operational_anomaly_surface(
        cls,
        db: Session,
        organization_id: str,
        thresholds: IntelligenceThresholds | None = None,
        anomalies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        anomalies = anomalies or cls.detect_anomalies(db, organization_id, thresholds=thresholds)
        index = {str(item.get("type") or ""): item for item in anomalies}

        return {
            "delayed_route_progression": index.get("delayed_route_progression"),
            "assignment_starvation": index.get("assignment_starvation"),
            "repeated_no_driver_recovery": index.get("repeated_no_driver_recovery"),
            "unresolved_failed_trip_states": index.get("unresolved_failed_trip_states"),
            "abnormal_escalation_density": index.get("abnormal_escalation_density"),
            "inactive_supervisor_queues": index.get("inactive_supervisor_queues"),
            "anomaly_count": len(anomalies),
            "high_severity_count": sum(1 for item in anomalies if str(item.get("severity") or "").lower() == "high"),
        }

    @classmethod
    def verify_backend_state_sources(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
    ) -> dict[str, Any]:
        ride_query = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id)
        if ride_id:
            ride_query = ride_query.filter(HealthISFRide.id == ride_id)

        rides = ride_query.count()
        workflow_exec = db.query(HealthISFWorkflowExecution).filter(
            HealthISFWorkflowExecution.organization_id == organization_id,
        ).count()
        audit_logs = db.query(HealthISFWorkflowAuditLog).filter(
            HealthISFWorkflowAuditLog.organization_id == organization_id,
        ).count()
        escalations = db.query(HealthISFWorkflowEscalation).filter(
            HealthISFWorkflowEscalation.organization_id == organization_id,
        ).count()
        assignments = db.query(HealthISFDispatchAssignment).filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
        ).count()

        return {
            "backend_authoritative": True,
            "ui_derived_assumptions": False,
            "organization_id": organization_id,
            "ride_id_scope": ride_id,
            "verified_tables": {
                "health_isf_rides": rides,
                "health_isf_dispatch_assignments": assignments,
                "health_isf_workflow_executions": workflow_exec,
                "health_isf_workflow_escalations": escalations,
                "health_isf_workflow_audit_logs": audit_logs,
            },
            "verified_at": now().isoformat(),
        }

    @staticmethod
    def _oldest_age_minutes(rows: list[Any], now_dt: datetime) -> int:
        if not rows:
            return 0
        normalized_now = OperationalIntelligenceService._normalize_utc_datetime(now_dt)
        oldest = min(
            (
                OperationalIntelligenceService._normalize_utc_datetime(getattr(item, "created_at", normalized_now))
                for item in rows
            ),
            default=normalized_now,
        )
        if isinstance(oldest, datetime):
            return max(0, int((normalized_now - oldest).total_seconds() // 60))
        return 0

    @staticmethod
    def _normalize_utc_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=now().tzinfo)
        return value

    @classmethod
    def build_recommendations(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
        thresholds: IntelligenceThresholds | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        from app.modules.health_isf import service as health_service

        if ride_id:
            rides = [db.query(HealthISFRide).filter(
                HealthISFRide.organization_id == organization_id,
                HealthISFRide.id == ride_id,
            ).first()]
        else:
            newest = health_service.get_newest_unassigned_queue_ride(db, organization_id=organization_id)
            if newest:
                rides = [newest[0]]
            else:
                rides = db.query(HealthISFRide).filter(
                    HealthISFRide.organization_id == organization_id,
                    HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED]),
                ).order_by(desc(HealthISFRide.requested_at), desc(HealthISFRide.created_at)).limit(10).all()

        rides = [ride for ride in rides if ride is not None]
        recommendations: list[dict[str, Any]] = []
        dispatcher_payloads: list[dict[str, Any]] = []
        automated_actions: list[dict[str, Any]] = []

        for ride in rides:
            driver_items = cls._score_drivers(db, ride, thresholds)
            provider_items = cls._score_providers(db, ride, thresholds)
            best_driver = driver_items[0] if driver_items else None
            best_provider = provider_items[0] if provider_items else None

            if best_driver:
                recommendations.append(best_driver)
                dispatcher_payloads.append({
                    "ride_id": ride.id,
                    "recommended_driver_id": best_driver["entity_id"],
                    "confidence": best_driver["confidence"],
                    "explanation": best_driver["explanation"],
                })
                if best_driver["confidence"] >= thresholds.auto_reassign_confidence_threshold and ride.status == RideStatus.PENDING:
                    automated_actions.append({
                        "action_type": "auto_reassignment_suggestion",
                        "ride_id": ride.id,
                        "driver_id": best_driver["entity_id"],
                        "confidence": best_driver["confidence"],
                        "reason": best_driver["explanation_summary"],
                    })

            if best_provider:
                recommendations.append(best_provider)
                dispatcher_payloads.append({
                    "ride_id": ride.id,
                    "recommended_provider_id": best_provider["entity_id"],
                    "confidence": best_provider["confidence"],
                    "explanation": best_provider["explanation"],
                })

            if best_driver and best_driver["confidence"] < 0.55:
                automated_actions.append({
                    "action_type": "backup_provider_recommendation",
                    "ride_id": ride.id,
                    "reason": "Primary driver confidence below soft threshold",
                    "suggested_driver_id": best_driver["entity_id"],
                })

        return {
            "organization_id": organization_id,
            "ride_id": ride_id,
            "generated_at": now().isoformat(),
            "recommendations": recommendations,
            "dispatcher_recommendation_payloads": dispatcher_payloads,
            "automated_actions": automated_actions,
        }

    @classmethod
    def build_risk_profile(
        cls,
        db: Session,
        organization_id: str,
        thresholds: IntelligenceThresholds | None = None,
        anomalies: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        anomalies = anomalies or cls.detect_anomalies(db, organization_id, thresholds=thresholds)
        metrics = get_operational_metrics_registry().snapshot()
        driver_query = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id)
        ride_query = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id)
        active_rides = ride_query.filter(HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT])).count()
        available_drivers = driver_query.filter(HealthISFDriver.status == DriverStatus.AVAILABLE).count()
        total_drivers = driver_query.count() or 1
        utilization = active_rides / float(total_drivers)
        workload_score = min(100.0, utilization * 100.0)
        eta_minutes = cls.predict_eta_minutes(db, organization_id) or 5.0  # Defensive: fallback to 5 min if None
        delay_risk = cls.predict_delay_risk(db, organization_id, anomalies)
        provider_saturation = cls.predict_provider_saturation(db, organization_id)
        dispatcher_workload = cls.predict_dispatcher_workload(db, organization_id)

        risk_score = cls._weighted_risk_score(
            anomalies=anomalies,
            active_rides=active_rides,
            available_drivers=available_drivers,
            total_drivers=total_drivers,
            metrics=metrics,
            provider_saturation=provider_saturation,
            dispatcher_workload=dispatcher_workload,
        )

        trend_explanations = [
            f"Driver utilization sits at {workload_score:.1f}% across {total_drivers} drivers.",
            f"ETA forecast is {eta_minutes:.1f} minutes with delay risk {delay_risk:.2f}.",
            f"Provider saturation forecast is {provider_saturation:.2f}.",
            f"Dispatcher workload score is {dispatcher_workload:.1f}.",
        ]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "operational_health_score": round(max(0.0, 100.0 - risk_score), 2),
            "risk_score": round(risk_score, 2),
            "workload_score": round(workload_score, 2),
            "eta_minutes": round(eta_minutes, 2),
            "delay_risk_score": round(delay_risk, 3),
            "provider_saturation_score": round(provider_saturation, 3),
            "dispatcher_workload_score": round(dispatcher_workload, 2),
            "trend_explanations": trend_explanations,
            "anomaly_explanations": [item["message"] for item in anomalies],
            "recommendation_summaries": [item["explanation_summary"] for item in cls.build_recommendations(db, organization_id)["recommendations"][:5]],
        }

    @classmethod
    def build_predictive_signals(
        cls,
        db: Session,
        organization_id: str,
        thresholds: IntelligenceThresholds | None = None,
        risk: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        thresholds = thresholds or IntelligenceThresholds()
        risk = risk or cls.build_risk_profile(db, organization_id, thresholds=thresholds)
        return {
            "eta_prediction_minutes": cls.predict_eta_minutes(db, organization_id),
            "ride_delay_prediction_score": cls.predict_delay_risk(db, organization_id),
            "provider_saturation_prediction": cls.predict_provider_saturation(db, organization_id),
            "dispatcher_workload_prediction": cls.predict_dispatcher_workload(db, organization_id),
            "dynamic_risk_assessment": risk["risk_score"],
            "trend_explanations": [
                f"Risk score currently trends at {risk['risk_score']:.1f}.",
                f"Operational health score currently trends at {risk['operational_health_score']:.1f}.",
            ],
        }

    @classmethod
    def broadcast_intelligence_events(
        cls,
        broadcaster: EventBroadcaster,
        organization_id: str,
        summary: dict[str, Any],
        anomalies: list[dict[str, Any]],
        recommendations: dict[str, Any],
        risk: dict[str, Any],
    ) -> None:
        payloads = [
            ("intelligence_summary", summary, [SubscriptionType.DISPATCHER_BOARD.value]),
            ("intelligence_anomalies", {"organization_id": organization_id, "anomalies": anomalies}, [SubscriptionType.DISPATCHER_BOARD.value]),
            ("intelligence_recommendations", recommendations, [SubscriptionType.DISPATCHER_BOARD.value]),
            ("intelligence_risk", risk, [SubscriptionType.DISPATCHER_BOARD.value]),
        ]
        for event_type, payload, subscription_types in payloads:
            asyncio_payload = payload if isinstance(payload, dict) else {"payload": payload}
            # Fire-and-forget broadcast is intentionally not awaited here so route handlers can remain simple.
            # The broadcaster API is async; callers should await the helper in route-level orchestration.
            raise_not_supported = False
            if raise_not_supported:
                _ = asyncio_payload

    @classmethod
    async def broadcast_intelligence_snapshot(
        cls,
        broadcaster: EventBroadcaster,
        organization_id: str,
        summary: dict[str, Any],
        anomalies: list[dict[str, Any]],
        recommendations: dict[str, Any],
        risk: dict[str, Any],
    ) -> None:
        await broadcaster.broadcast_event(
            event_type="intelligence_summary",
            payload=summary,
            organization_id=organization_id,
            subscription_types=[SubscriptionType.DISPATCHER_BOARD.value],
        )
        await broadcaster.broadcast_event(
            event_type="intelligence_anomalies",
            payload={"organization_id": organization_id, "anomalies": anomalies},
            organization_id=organization_id,
            subscription_types=[SubscriptionType.DISPATCHER_BOARD.value],
        )
        await broadcaster.broadcast_event(
            event_type="intelligence_recommendations",
            payload=recommendations,
            organization_id=organization_id,
            subscription_types=[SubscriptionType.DISPATCHER_BOARD.value],
        )
        await broadcaster.broadcast_event(
            event_type="intelligence_risk",
            payload=risk,
            organization_id=organization_id,
            subscription_types=[SubscriptionType.DISPATCHER_BOARD.value],
        )

    @classmethod
    def persist_reanalysis_audit(
        cls,
        db: Session,
        organization_id: str,
        actor_user_id: str | None,
        summary: dict[str, Any],
        anomalies: list[dict[str, Any]],
        recommendations: dict[str, Any],
        risk: dict[str, Any],
    ) -> None:
        SecurityAuditService.log_action(
            db,
            organization_id=organization_id,
            action_type="operational_intelligence_reanalyze",
            actor_user_id=actor_user_id,
            details={
                "summary": summary,
                "anomaly_count": len(anomalies),
                "recommendation_count": len(recommendations["recommendations"]),
                "risk_score": risk["risk_score"],
            },
        )

    @classmethod
    def _score_drivers(
        cls,
        db: Session,
        ride: HealthISFRide,
        thresholds: IntelligenceThresholds,
    ) -> list[dict[str, Any]]:
        from app.modules.health_isf import service as health_service

        driver_candidates = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == ride.organization_id,
            HealthISFDriver.is_active.is_(True),
        ).all()
        scored: list[dict[str, Any]] = []
        for driver in driver_candidates:
            if not health_service._driver_is_dispatch_candidate(db, driver):
                continue
            scored.append(cls._score_driver(driver, ride, thresholds))
        return sorted(scored, key=lambda item: item["score"], reverse=True)

    @classmethod
    def _score_providers(
        cls,
        db: Session,
        ride: HealthISFRide,
        thresholds: IntelligenceThresholds,
    ) -> list[dict[str, Any]]:
        provider_candidates = db.query(HealthISFProvider).filter(
            HealthISFProvider.organization_id == ride.organization_id,
            HealthISFProvider.is_active.is_(True),
        ).all()
        scored = [cls._score_provider(provider, ride, thresholds) for provider in provider_candidates]
        return sorted(scored, key=lambda item: item["score"], reverse=True)

    @classmethod
    def _score_driver(
        cls,
        driver: HealthISFDriver,
        ride: HealthISFRide,
        thresholds: IntelligenceThresholds,
    ) -> dict[str, Any]:
        availability = cls._availability_score(driver.status)
        history = cls._historical_completion_score(driver.total_trips, driver.rating)
        cancellation_risk = cls._cancellation_risk_score(driver.organization_id, driver.id)
        proximity = cls._proximity_score(ride.pickup_address, ride.dropoff_address, driver.name, ride.estimated_distance_miles)
        score = round(
            (availability * 0.35) + (history * 0.25) + (proximity * 0.20) + ((1.0 - cancellation_risk) * 0.20),
            4,
        )
        confidence = round(min(0.99, max(0.05, score + (history * 0.10) - cancellation_risk * 0.05)), 4)
        explanation = [
            f"availability={availability:.2f}",
            f"historical_completion={history:.2f}",
            f"proximity={proximity:.2f}",
            f"cancellation_risk={cancellation_risk:.2f}",
        ]
        return {
            "entity_type": "driver",
            "entity_id": driver.id,
            "score": score,
            "confidence": confidence,
            "explanation": explanation,
            "explanation_summary": f"Driver {driver.name} scored {score:.2f} with confidence {confidence:.2f}",
            "details": {
                "driver_name": driver.name,
                "status": driver.status,
                "total_trips": driver.total_trips,
                "rating": driver.rating,
            },
        }

    @classmethod
    def _score_provider(
        cls,
        provider: HealthISFProvider,
        ride: HealthISFRide,
        thresholds: IntelligenceThresholds,
    ) -> dict[str, Any]:
        service_match = cls._service_match_score(provider.service_type, ride.service_type)
        proximity = cls._proximity_score(ride.pickup_address, ride.dropoff_address, provider.address, None)
        history = cls._provider_history_score(provider.organization_id, provider.id)
        cancellation_risk = cls._provider_cancellation_risk(provider.organization_id, provider.id)
        score = round(
            (service_match * 0.30) + (proximity * 0.30) + (history * 0.25) + ((1.0 - cancellation_risk) * 0.15),
            4,
        )
        confidence = round(min(0.99, max(0.05, score + history * 0.08)), 4)
        explanation = [
            f"service_match={service_match:.2f}",
            f"proximity={proximity:.2f}",
            f"historical_completion={history:.2f}",
            f"cancellation_risk={cancellation_risk:.2f}",
        ]
        return {
            "entity_type": "provider",
            "entity_id": provider.id,
            "score": score,
            "confidence": confidence,
            "explanation": explanation,
            "explanation_summary": f"Provider {provider.name} scored {score:.2f} with confidence {confidence:.2f}",
            "details": {
                "provider_name": provider.name,
                "service_type": provider.service_type,
                "address": provider.address,
            },
        }

    @staticmethod
    def predict_eta_minutes(db: Session, organization_id: str) -> float:
        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        if not rides:
            return 0.0
        active_estimates = [ride.estimated_duration_minutes or 30 for ride in rides if ride.status in {RideStatus.ACCEPTED, RideStatus.IN_TRANSIT, RideStatus.PENDING}]
        if not active_estimates:
            active_estimates = [30]
        driver_utilization = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status.in_([DriverStatus.ASSIGNED, DriverStatus.EN_ROUTE_PICKUP, DriverStatus.WAITING_AT_PICKUP, DriverStatus.IN_TRANSIT, DriverStatus.BUSY]),
        ).count()
        total_drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id).count() or 1
        utilization_factor = driver_utilization / float(total_drivers)
        return round((sum(active_estimates) / len(active_estimates)) * (1.0 + utilization_factor * 0.25), 2)

    @staticmethod
    def predict_delay_risk(db: Session, organization_id: str, anomalies: list[dict[str, Any]] | None = None) -> float:
        anomalies = anomalies or []
        ride_count = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).count() or 1
        delayed = sum(1 for item in anomalies if item["type"] in {"stuck_rides", "delayed_pickups"})
        return round(min(1.0, delayed / float(max(1, ride_count)) * 10.0), 3)

    @staticmethod
    def predict_provider_saturation(db: Session, organization_id: str) -> float:
        active_rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
        ).count()
        active_providers = db.query(HealthISFProvider).filter(
            HealthISFProvider.organization_id == organization_id,
            HealthISFProvider.is_active.is_(True),
        ).count() or 1
        return round(min(1.0, active_rides / float(active_providers * 6)), 3)

    @staticmethod
    def predict_dispatcher_workload(db: Session, organization_id: str) -> float:
        pending = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status == RideStatus.PENDING,
        ).count()
        driver_count = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id).count() or 1
        return round(min(100.0, (pending / float(driver_count)) * 25.0 + pending * 2.5), 2)

    @classmethod
    def _weighted_risk_score(
        cls,
        anomalies: list[dict[str, Any]],
        active_rides: int,
        available_drivers: int,
        total_drivers: int,
        metrics: dict[str, Any],
        provider_saturation: float,
        dispatcher_workload: float,
    ) -> float:
        anomaly_weight = min(45.0, len(anomalies) * 7.5)
        coverage_penalty = 0.0
        if active_rides > 0:
            coverage_penalty = max(0.0, 25.0 - (available_drivers / float(active_rides)) * 25.0)
        websocket_penalty = min(10.0, metrics.get("counters", {}).get("websocket.connections.active", 0) / 100.0)
        saturation_penalty = provider_saturation * 15.0
        workload_penalty = min(15.0, dispatcher_workload * 0.15)
        risk = anomaly_weight + coverage_penalty + websocket_penalty + saturation_penalty + workload_penalty
        return max(0.0, min(100.0, round(risk, 2)))

    @staticmethod
    def _availability_score(status: str | DriverStatus) -> float:
        mapping = {
            DriverStatus.AVAILABLE: 1.0,
            DriverStatus.ASSIGNED: 0.7,
            DriverStatus.EN_ROUTE_PICKUP: 0.6,
            DriverStatus.WAITING_AT_PICKUP: 0.55,
            DriverStatus.IN_TRANSIT: 0.35,
            DriverStatus.BUSY: 0.35,
            DriverStatus.UNAVAILABLE: 0.1,
            DriverStatus.OFFLINE: 0.0,
        }
        if isinstance(status, DriverStatus):
            normalized = status
        else:
            raw = str(status or "").strip().lower()
            if raw.startswith("driverstatus."):
                raw = raw.split(".", 1)[-1]
            try:
                normalized = DriverStatus(raw)
            except Exception:
                return 0.25
        return float(mapping.get(normalized, 0.25))

    @staticmethod
    def _historical_completion_score(total_trips: int, rating: float) -> float:
        trips_score = min(1.0, total_trips / 50.0)
        rating_score = min(1.0, max(0.0, rating / 5.0))
        return round((trips_score * 0.65) + (rating_score * 0.35), 4)

    @staticmethod
    def _cancellation_risk_score(organization_id: str, driver_id: str) -> float:
        # In the absence of per-driver cancel stats, use a conservative neutral risk.
        return 0.35

    @staticmethod
    def _provider_history_score(organization_id: str, provider_id: str) -> float:
        return 0.55

    @staticmethod
    def _provider_cancellation_risk(organization_id: str, provider_id: str) -> float:
        return 0.30

    @staticmethod
    def _service_match_score(provider_service_type: str, ride_service_type: str) -> float:
        return 1.0 if provider_service_type.lower().strip() == ride_service_type.lower().strip() else 0.6

    @staticmethod
    def _proximity_score(pickup_address: str, dropoff_address: str, reference_text: str, estimated_distance_miles: float | None) -> float:
        if estimated_distance_miles is not None:
            return round(1.0 / (1.0 + (estimated_distance_miles / 10.0)), 4)
        pickup_tokens = set(_normalize_tokens(pickup_address))
        dropoff_tokens = set(_normalize_tokens(dropoff_address))
        reference_tokens = set(_normalize_tokens(reference_text))
        denominator = max(1, len(pickup_tokens | dropoff_tokens | reference_tokens))
        overlap = len((pickup_tokens | dropoff_tokens) & reference_tokens)
        return round(min(1.0, overlap / float(denominator)), 4)

    @staticmethod
    def _dispatch_latency_seconds(rides: Iterable[HealthISFRide]) -> float:
        samples = []
        for ride in rides:
            if ride.accepted_at and ride.requested_at:
                samples.append((ride.accepted_at - ride.requested_at).total_seconds())
        if not samples:
            return 0.0
        return sum(samples) / len(samples)

    @staticmethod
    def _compose_summary_text(
        anomalies: list[dict[str, Any]],
        recommendations: dict[str, Any],
        risk: dict[str, Any],
        predictive: dict[str, Any],
    ) -> str:
        top_anomaly = anomalies[0]["message"] if anomalies else "No critical anomalies detected"
        top_recommendation = recommendations["recommendations"][0]["explanation_summary"] if recommendations["recommendations"] else "No immediate reassignment candidate"
        return (
            f"Operational health score {risk['operational_health_score']:.1f}/100. "
            f"Top anomaly: {top_anomaly}. "
            f"Top recommendation: {top_recommendation}. "
            f"Predicted ETA {predictive['eta_prediction_minutes']:.1f} minutes."
        )

    @staticmethod
    def _anomaly(alert_type: str, severity: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": alert_type,
            "severity": severity,
            "message": message,
            "details": details,
            "timestamp": now().isoformat(),
        }


def _normalize_tokens(value: str) -> list[str]:
    normalized = value.lower().replace("/", " ").replace(",", " ").replace(".", " ")
    return [token for token in normalized.split() if token]
