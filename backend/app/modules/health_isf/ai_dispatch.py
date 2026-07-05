"""AI dispatch orchestration helpers for Health ISF.

This module composes the existing operations, intelligence, workflow, and
realtime services into additive tenant-scoped payloads for the dispatcher UI.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf import service
from app.modules.health_isf.intake import (
    build_ai_dispatch_context,
    build_intake_fingerprint,
    calculate_duration_minutes,
    calculate_priority_score,
    normalize_priority_tag,
)
from app.modules.health_isf.intelligence import OperationalIntelligenceService
from app.modules.health_isf.models import (
    DispatcherActivityLog,
    DriverStatus,
    HealthISFProvider,
    HealthISFRide,
    HealthISFWorkflowAuditLog,
    OperationalAlertLog,
    RealTimeEvent,
    RideStatus,
)
from app.modules.health_isf.operations import (
    build_operational_dashboard,
    build_operational_metrics,
    evaluate_operational_alerts,
)
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.realtime_service import ActivityLogService, RetryQueueService
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService


logger = logging.getLogger("amicor.health_isf.ai_dispatch")


class AIDispatchOrchestrationService:
    """Compose autonomous operations payloads without changing core workflows."""

    _RIDE_ID_RE = re.compile(r"\bride\s+(?!from\b|to\b|for\b|passenger\b|driver\b|phone\b)([a-z0-9\-]{4,36})\b", re.IGNORECASE)
    _DRIVER_ID_RE = re.compile(r"\bdriver\s+([a-z0-9\-]{2,36})\b", re.IGNORECASE)
    _FROM_TO_RE = re.compile(r"\bfrom\s+(.+?)\s+to\s+(.+?)(?:\bfor\b|\bpassenger\b|\bphone\b|\bservice\b|\bpriority\b|$)", re.IGNORECASE)
    _PASSENGER_RE = re.compile(
        r"\bpassenger\s+([a-z][a-z\s.'\-]{1,80}?)(?:\s+\b(?:phone|from|to|pickup|dropoff|service|priority|emergency|urgent)\b|$)",
        re.IGNORECASE,
    )
    _PHONE_RE = re.compile(r"(\+?[0-9][0-9()\-\s]{6,20})")
    _SERVICE_TYPE_RE = re.compile(r"\b(dialysis|discharge|oncology|medical transport|specialist|appointment)\b", re.IGNORECASE)
    _PRIORITY_RE = re.compile(r"\b(priority\s+)?(emergency|urgent|high|normal|low)\b", re.IGNORECASE)

    @classmethod
    def build_operations_snapshot(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "Building AI dispatch operations snapshot",
            extra={"organization_id": organization_id, "ride_id": ride_id},
        )

        logger.info("Reached websocket payload build step")
        websocket_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)

        logger.info("Reached retry queue lookup step")
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)

        logger.info("Reached operational alert aggregation step")
        alerts = evaluate_operational_alerts(
            db,
            queue_stats=queue_stats,
            websocket_stats=websocket_stats,
            organization_id=organization_id,
        )

        logger.info("Reached operational metrics aggregation step")
        metrics = build_operational_metrics(db, organization_id=organization_id)

        logger.info("Reached dashboard operational metrics step")
        dashboard = build_operational_dashboard(db, organization_id=organization_id)

        logger.info("Reached intelligence snapshot step")
        summary = OperationalIntelligenceService.summarize(db, organization_id, ride_id=ride_id)
        recommendations = OperationalIntelligenceService.build_recommendations(db, organization_id, ride_id=ride_id)
        anomalies = OperationalIntelligenceService.detect_anomalies(db, organization_id)
        risk = OperationalIntelligenceService.build_risk_profile(db, organization_id, anomalies=anomalies)
        operational_state_awareness = summary.get("operational_state_awareness") or OperationalIntelligenceService.build_operational_state_awareness(
            db,
            organization_id,
            anomalies=anomalies,
        )
        operational_context_aggregation = summary.get("operational_context_aggregation") or OperationalIntelligenceService.build_operational_context_aggregation(
            db,
            organization_id,
            anomalies=anomalies,
            risk=risk,
        )
        operational_correlations = summary.get("operational_correlations") or OperationalIntelligenceService.build_operational_correlations(
            db,
            organization_id,
        )
        operational_anomaly_surface = summary.get("operational_anomaly_surface") or OperationalIntelligenceService.build_operational_anomaly_surface(
            db,
            organization_id,
            anomalies=anomalies,
        )
        backend_state_verification = summary.get("backend_state_verification") or OperationalIntelligenceService.verify_backend_state_sources(
            db,
            organization_id,
            ride_id=ride_id,
        )

        logger.info("Reached operational timeline build step")
        timeline = cls.build_timeline(db, organization_id=organization_id, ride_id=ride_id, limit=40)

        logger.info("Reached notification payload build step")
        notifications = cls.build_notifications(
            db,
            organization_id=organization_id,
            alerts=alerts,
            anomalies=anomalies,
            recommendations=recommendations,
            websocket_stats=websocket_stats,
        )

        logger.info("Reached analytics aggregation step")
        analytics = cls.build_analytics(db, organization_id=organization_id, metrics=metrics)

        logger.info("Reached orchestration engine synthesis step")
        orchestration = cls.build_orchestration_state(
            organization_id=organization_id,
            summary=summary,
            alerts=alerts,
            recommendations=recommendations,
            anomalies=anomalies,
            risk=risk,
            websocket_stats=websocket_stats,
            analytics=analytics,
            timeline=timeline,
        )

        logger.info("Reached event stream aggregation step")
        event_stream = cls.build_event_stream(
            db,
            organization_id=organization_id,
            ride_id=ride_id,
        )

        live_dispatch = cls.build_live_dispatch_context(
            db,
            organization_id=organization_id,
            ride_id=ride_id,
        )

        logger.info("Reached memory snapshot persistence step")
        memory_snapshot = cls.persist_memory_snapshot(
            db,
            organization_id=organization_id,
            snapshot_payload={
                "summary": summary,
                "risk": risk,
                "analytics": {
                    "driver_efficiency": analytics.get("driver_efficiency", {}),
                    "delay_percentages": analytics.get("delay_percentages", {}),
                    "cancellation_rates": analytics.get("cancellation_rates", {}),
                },
                "orchestration": orchestration,
                "event_stream": event_stream,
            },
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "summary": summary,
            "metrics": metrics,
            "dashboard": dashboard,
            "analytics": analytics,
            "alerts": alerts,
            "notifications": notifications,
            "recommendations": recommendations,
            "timeline": timeline,
            "resilience": {
                "websocket": websocket_stats,
                "retry_queue": queue_stats,
                "offline_buffering": {
                    "enabled": True,
                    "queued_events": queue_stats.get("queued", 0),
                    "dead_letters": queue_stats.get("dead_letter", 0),
                },
                "duplicate_event_prevention": {
                    "enabled": True,
                    "idempotency_scope": "health_isf_dispatch",
                },
                "event_replay": {
                    "available": queue_stats.get("dead_letter", 0) > 0,
                    "replayable_events": queue_stats.get("dead_letter", 0),
                },
            },
            "assistant": {
                "operational_status": summary.get("summary"),
                "priority_focus": cls._top_priority_focus(recommendations, alerts),
                "recommended_actions": recommendations.get("dispatcher_recommendation_payloads", [])[:5],
                "overloaded_driver_count": analytics["driver_efficiency"]["overloaded_count"],
                "delayed_ride_count": analytics["delay_percentages"]["delayed_ride_count"],
                "emergency_ride_count": analytics["emergency_ride_statistics"]["active_emergency_rides"],
                "operational_state_awareness": operational_state_awareness,
                "operational_context_aggregation": operational_context_aggregation,
            },
            "orchestration": orchestration,
            "event_stream": event_stream,
            "memory_snapshot": memory_snapshot,
            "operational_state_awareness": operational_state_awareness,
            "operational_context_aggregation": operational_context_aggregation,
            "operational_correlations": operational_correlations,
            "operational_anomaly_surface": operational_anomaly_surface,
            "backend_state_verification": backend_state_verification,
            "live_dispatch": live_dispatch,
        }

    @classmethod
    def build_live_dispatch_context(
        cls,
        db: Session,
        *,
        organization_id: str,
        ride_id: str | None = None,
    ) -> dict[str, Any]:
        queue = service.get_dispatch_queue(db, organization_id=organization_id, limit=50)
        focused_ride: dict[str, Any] | None = None
        target_ride_id = str(ride_id or "").strip()
        if not target_ride_id and queue:
            target_ride_id = str(queue[0].get("ride_id") or "")

        if target_ride_id:
            ride = service.get_ride_by_id(db, target_ride_id)
            if ride and ride.organization_id == organization_id:
                queue_row = next((row for row in queue if str(row.get("ride_id")) == target_ride_id), None)
                driver = service.get_driver_by_id(db, ride.driver_id) if ride.driver_id else None
                active_assignment = service._active_assignment_for_ride(db, ride.id)
                focused_ride = {
                    "ride_id": ride.id,
                    "passenger_name": ride.passenger_name,
                    "pickup_address": ride.pickup_address,
                    "dropoff_address": ride.dropoff_address,
                    "ride_status": service._normalize_status_token(ride.lifecycle_state or ride.status),
                    "assignment_state": (
                        str(queue_row.get("assignment_state"))
                        if queue_row
                        else (str(active_assignment.assignment_state) if active_assignment else None)
                    ),
                    "driver_id": str(ride.driver_id) if ride.driver_id else None,
                    "driver_name": driver.name if driver else None,
                }

        return {
            "queue_count": len(queue),
            "queue_ride_ids": [str(row.get("ride_id") or "") for row in queue[:25]],
            "queue": queue[:25],
            "focused_ride": focused_ride,
        }

    @classmethod
    def build_orchestration_state(
        cls,
        *,
        organization_id: str,
        summary: dict[str, Any],
        alerts: list[dict[str, Any]],
        recommendations: dict[str, Any],
        anomalies: list[dict[str, Any]],
        risk: dict[str, Any],
        websocket_stats: dict[str, Any],
        analytics: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> dict[str, Any]:
        top_recommendations = recommendations.get("recommendations", [])[:6]
        dispatch_confidence = 0.0
        if top_recommendations:
            dispatch_confidence = round(
                sum(float(item.get("confidence") or 0.0) for item in top_recommendations) / len(top_recommendations),
                3,
            )

        high_alerts = [item for item in alerts if str(item.get("severity", "")).lower() == "high"]
        escalations = [item for item in timeline if str(item.get("severity", "")).lower() == "high"][:10]
        agent_health = "healthy"
        if high_alerts or websocket_stats.get("disconnects_last_5m", 0) >= 5:
            agent_health = "degraded"

        decisions: list[dict[str, Any]] = []
        for item in top_recommendations:
            decisions.append(
                {
                    "decision_type": str(item.get("entity_type") or "dispatch_action"),
                    "entity_id": str(item.get("entity_id") or "unknown"),
                    "confidence": float(item.get("confidence") or 0.0),
                    "summary": str(item.get("explanation_summary") or "AI recommendation ready"),
                    "explanation": list(item.get("explanation") or []),
                }
            )

        if not decisions:
            decisions.append(
                {
                    "decision_type": "stability_hold",
                    "entity_id": "global",
                    "confidence": 0.92,
                    "summary": "System stable: continue current dispatch posture with proactive monitoring.",
                    "explanation": ["No critical anomalies detected", "Queue and websocket health within thresholds"],
                }
            )

        active_agents = [
            {
                "agent_id": "dispatch_supervisor",
                "status": "active",
                "focus": cls._top_priority_focus(recommendations, alerts),
                "health": agent_health,
            },
            {
                "agent_id": "anomaly_guardian",
                "status": "active",
                "focus": f"Monitoring {len(anomalies)} anomaly signals",
                "health": "healthy" if len(high_alerts) == 0 else "degraded",
            },
            {
                "agent_id": "capacity_planner",
                "status": "active",
                "focus": f"Driver utilization {analytics.get('realtime_operational_load', {}).get('driver_utilization_percent', 0)}%",
                "health": "healthy",
            },
            {
                "agent_id": "workflow_recovery",
                "status": "active",
                "focus": "Retry queue replay and escalation orchestration",
                "health": "healthy",
            },
        ]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "dispatch_confidence": dispatch_confidence,
            "system_health": {
                "status": agent_health,
                "operational_health_score": summary.get("operational_health_score", 0),
                "risk_score": risk.get("risk_score", 0),
                "websocket_disconnects_last_5m": websocket_stats.get("disconnects_last_5m", 0),
                "active_connections": websocket_stats.get("active_connections", 0),
            },
            "active_agents": active_agents,
            "decisions": decisions,
            "escalation_events": escalations,
            "anomaly_watch": [item.get("message") for item in anomalies[:8]],
        }

    @classmethod
    def build_event_stream(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
    ) -> dict[str, Any]:
        since = now() - timedelta(minutes=15)
        event_query = db.query(RealTimeEvent).filter(
            RealTimeEvent.organization_id == organization_id,
            RealTimeEvent.created_at >= since,
        )
        if ride_id:
            event_query = event_query.filter(RealTimeEvent.ride_id == ride_id)
        events = event_query.all()

        activity_query = db.query(DispatcherActivityLog).filter(
            DispatcherActivityLog.organization_id == organization_id,
            DispatcherActivityLog.created_at >= since,
        )
        if ride_id:
            activity_query = activity_query.filter(DispatcherActivityLog.ride_id == ride_id)
        activities = activity_query.all()

        event_counts: dict[str, int] = defaultdict(int)
        for row in events:
            event_counts[str(row.event_type)] += 1

        action_counts: dict[str, int] = defaultdict(int)
        for row in activities:
            action_counts[str(row.action)] += 1

        return {
            "window_minutes": 15,
            "total_realtime_events": len(events),
            "total_dispatch_actions": len(activities),
            "events_by_type": dict(sorted(event_counts.items(), key=lambda item: item[0])),
            "actions_by_type": dict(sorted(action_counts.items(), key=lambda item: item[0])),
            "last_event_at": events[0].created_at.isoformat() if events else None,
            "last_action_at": activities[0].created_at.isoformat() if activities else None,
        }

    @classmethod
    def persist_memory_snapshot(
        cls,
        db: Session,
        organization_id: str,
        snapshot_payload: dict[str, Any],
    ) -> dict[str, Any]:
        # Load platform ORM metadata so workflow audit foreign keys resolve consistently.
        from app.db import models as _platform_models  # noqa: F401

        cutoff = now() - timedelta(seconds=45)
        latest = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(
                HealthISFWorkflowAuditLog.organization_id == organization_id,
                HealthISFWorkflowAuditLog.event_type == "ai_orchestration_snapshot",
            )
            .order_by(HealthISFWorkflowAuditLog.created_at.desc())
            .first()
        )

        latest_created_at = getattr(latest, "created_at", None)
        if latest_created_at and latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(tzinfo=timezone.utc)

        if latest and latest_created_at and latest_created_at >= cutoff:
            return {
                "snapshot_id": latest.id,
                "persisted": False,
                "reason": "throttled",
                "created_at": latest_created_at.isoformat(),
            }

        record = HealthISFWorkflowAuditLog(
            organization_id=organization_id,
            workflow_execution_id=None,
            incident_id=None,
            escalation_id=None,
            event_type="ai_orchestration_snapshot",
            actor_user_id=None,
            payload=json.dumps(snapshot_payload, default=str),
            created_at=now(),
        )
        db.add(record)
        try:
            db.commit()
            db.refresh(record)
            return {
                "snapshot_id": record.id,
                "persisted": True,
                "reason": "created",
                "created_at": record.created_at.isoformat(),
            }
        except Exception:
            db.rollback()
            logger.exception("Failed to persist AI orchestration snapshot", extra={"organization_id": organization_id})
            return {
                "snapshot_id": None,
                "persisted": False,
                "reason": "persist_failed",
                "created_at": now().isoformat(),
            }

    @classmethod
    async def publish_operations_update(
        cls,
        organization_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, int]:
        broadcaster = get_broadcaster()
        delivered: dict[str, int] = {}

        delivered["autonomous_operations_snapshot"] = await broadcaster.broadcast_event(
            event_type="autonomous_operations_snapshot",
            payload={
                "organization_id": organization_id,
                "generated_at": snapshot.get("generated_at"),
                "summary": snapshot.get("summary", {}),
                "orchestration": snapshot.get("orchestration", {}),
                "assistant": snapshot.get("assistant", {}),
                "event_stream": snapshot.get("event_stream", {}),
                "memory_snapshot": snapshot.get("memory_snapshot", {}),
            },
            organization_id=organization_id,
            subscription_types=["dispatcher_board", "workflow_events"],
        )

        delivered["intelligence_summary"] = await broadcaster.broadcast_event(
            event_type="intelligence_summary",
            payload=snapshot.get("summary", {}),
            organization_id=organization_id,
            subscription_types=["dispatcher_board"],
        )

        delivered["intelligence_recommendations"] = await broadcaster.broadcast_event(
            event_type="intelligence_recommendations",
            payload=snapshot.get("recommendations", {}),
            organization_id=organization_id,
            subscription_types=["dispatcher_board", "ride_updates"],
        )

        delivered["intelligence_risk"] = await broadcaster.broadcast_event(
            event_type="intelligence_risk",
            payload={
                "organization_id": organization_id,
                "risk": snapshot.get("summary", {}).get("risk_score"),
                "orchestration": snapshot.get("orchestration", {}).get("system_health", {}),
            },
            organization_id=organization_id,
            subscription_types=["dispatcher_board"],
        )

        delivered["orchestration_update"] = await broadcaster.broadcast_event(
            event_type="orchestration_update",
            payload=snapshot.get("orchestration", {}),
            organization_id=organization_id,
            subscription_types=["dispatcher_board", "workflow_events"],
        )

        return delivered

    @classmethod
    def build_analytics(
        cls,
        db: Session,
        organization_id: str,
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        metrics = metrics or build_operational_metrics(db, organization_id=organization_id)
        logger.info("Reached analytics DB query step: rides/providers/drivers")
        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        providers = {
            provider.id: provider
            for provider in db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == organization_id).all()
        }
        drivers = [driver for driver in service.get_all_drivers(db, skip=0, limit=500) if driver.organization_id == organization_id]

        total_rides = len(rides) or 1
        delayed_rides = 0
        cancellations = 0
        emergency_rides = 0
        workflow_failures = 0
        workflow_successes = 0
        provider_rollup: dict[str, dict[str, Any]] = defaultdict(lambda: {"provider_id": None, "provider_name": "Unknown", "completed": 0, "cancelled": 0, "active": 0})
        driver_rollup: dict[str, dict[str, Any]] = defaultdict(lambda: {"driver_id": None, "driver_name": "Unknown", "active": 0, "completed": 0, "status": "offline"})
        current_epoch = now().timestamp()

        for ride in rides:
            provider_key = str(ride.provider_id) if ride.provider_id else "unassigned"
            provider_entry = provider_rollup[provider_key]
            provider_entry["provider_id"] = provider_key
            provider = providers.get(provider_key)
            provider_entry["provider_name"] = provider.name if provider else "Unassigned"
            driver_entry = driver_rollup[str(ride.driver_id or "unassigned")]
            driver_entry["driver_id"] = str(ride.driver_id or "unassigned")
            driver_entry["driver_name"] = getattr(ride.driver, "name", None) or "Unassigned"
            driver_entry["status"] = str(getattr(ride.driver, "status", "offline"))

            if ride.status == RideStatus.CANCELLED:
                cancellations += 1
                provider_entry["cancelled"] += 1
            if ride.status == RideStatus.COMPLETED:
                provider_entry["completed"] += 1
                driver_entry["completed"] += 1
            if ride.status in {RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT}:
                provider_entry["active"] += 1
                driver_entry["active"] += 1
            if ride.is_emergency:
                emergency_rides += 1
            if ride.status in {RideStatus.PENDING, RideStatus.ACCEPTED} and ride.requested_at:
                eta_cutoff_epoch = (
                    ride.requested_at.timestamp() +
                    timedelta(minutes=int(ride.estimated_duration_minutes or 20)).total_seconds()
                )
                if current_epoch > eta_cutoff_epoch:
                    delayed_rides += 1

        workflows = WorkflowOrchestrationService.list_workflows(db, organization_id=organization_id, limit=200)
        logger.info("Reached workflow analytics aggregation step")
        for workflow in workflows:
            status = str(workflow.get("status") or "")
            if status in {"failed", "errored"}:
                workflow_failures += 1
            elif status:
                workflow_successes += 1

        overloaded_drivers = [
            item for item in driver_rollup.values()
            if item["active"] >= 3 or item["status"] in {DriverStatus.BUSY.value, DriverStatus.IN_TRANSIT.value}
        ]

        return {
            "live_ride_throughput": {
                "dispatch_throughput_per_minute": metrics.get("dispatch_throughput_per_minute", 0),
                "active_rides": metrics.get("active_rides", 0),
                "unassigned_rides": metrics.get("unassigned_rides", 0),
            },
            "provider_performance": {
                "leaders": sorted(provider_rollup.values(), key=lambda item: (-item["completed"], item["cancelled"], item["provider_name"]))[:5],
                "provider_count": len(provider_rollup),
            },
            "driver_efficiency": {
                "leaders": sorted(driver_rollup.values(), key=lambda item: (-item["completed"], item["active"], item["driver_name"]))[:5],
                "overloaded_count": len(overloaded_drivers),
                "overloaded_drivers": overloaded_drivers[:5],
            },
            "delay_percentages": {
                "delayed_ride_count": delayed_rides,
                "delay_percentage": round((delayed_rides / total_rides) * 100.0, 2),
            },
            "cancellation_rates": {
                "cancelled_ride_count": cancellations,
                "cancellation_rate": round((cancellations / total_rides) * 100.0, 2),
            },
            "realtime_operational_load": {
                "driver_utilization_percent": metrics.get("driver_utilization_percent", 0.0),
                "websocket_connection_count": metrics.get("websocket_connection_count", 0),
                "failed_event_count": metrics.get("failed_event_count", 0),
            },
            "ai_dispatch_recommendations": {
                "summary": OperationalIntelligenceService.summarize(db, organization_id).get("recommendation_summaries", [])[:5],
            },
            "emergency_ride_statistics": {
                "active_emergency_rides": emergency_rides,
                "emergency_percentage": round((emergency_rides / total_rides) * 100.0, 2),
            },
            "workflow_success_failure_metrics": {
                "workflow_successes": workflow_successes,
                "workflow_failures": workflow_failures,
                "success_rate": round((workflow_successes / max(workflow_successes + workflow_failures, 1)) * 100.0, 2),
            },
        }

    @classmethod
    def build_notifications(
        cls,
        db: Session,
        organization_id: str,
        alerts: list[dict[str, Any]] | None = None,
        anomalies: list[dict[str, Any]] | None = None,
        recommendations: dict[str, Any] | None = None,
        websocket_stats: dict[str, Any] | None = None,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        alerts = alerts or []
        anomalies = anomalies or []
        recommendations = recommendations or {"recommendations": [], "dispatcher_recommendation_payloads": []}
        websocket_stats = websocket_stats or get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        logger.info("Reached websocket payload build for notifications")
        notifications: list[dict[str, Any]] = []

        for alert in alerts[:10]:
            notifications.append({
                "id": f"alert:{alert['type']}:{alert['timestamp']}",
                "type": "alert",
                "severity": alert["severity"],
                "title": alert["type"].replace("_", " ").title(),
                "message": alert["message"],
                "created_at": alert["timestamp"],
                "source": "ops_alert",
                "ride_id": alert.get("details", {}).get("ride_id"),
            })

        for anomaly in anomalies[:8]:
            notifications.append({
                "id": f"anomaly:{anomaly['type']}:{anomaly['timestamp']}",
                "type": "warning",
                "severity": anomaly["severity"],
                "title": "Operational anomaly",
                "message": anomaly["message"],
                "created_at": anomaly["timestamp"],
                "source": "ai_detection",
                "ride_id": anomaly.get("details", {}).get("ride_ids", [None])[0],
            })

        for item in recommendations.get("dispatcher_recommendation_payloads", [])[:6]:
            notifications.append({
                "id": f"recommendation:{item.get('action_type')}:{item.get('ride_id', 'global')}",
                "type": "recommendation",
                "severity": "medium",
                "title": "AI dispatch recommendation",
                "message": item.get("summary") or item.get("explanation_summary") or "Recommended dispatcher action available",
                "created_at": recommendations.get("generated_at") or now().isoformat(),
                "source": "ai_recommendation",
                "ride_id": item.get("ride_id"),
            })

        if websocket_stats.get("disconnects_last_5m", 0) > 0:
            notifications.append({
                "id": f"ws:{websocket_stats['disconnects_last_5m']}",
                "type": "system",
                "severity": "high" if websocket_stats.get("disconnects_last_5m", 0) >= 5 else "medium",
                "title": "Realtime reconnect alert",
                "message": f"Detected {websocket_stats.get('disconnects_last_5m', 0)} websocket disconnects in the last 5 minutes.",
                "created_at": now().isoformat(),
                "source": "websocket_health",
                "ride_id": None,
            })

        logger.info("Reached notifications DB query step: persisted alert logs")
        persisted = (
            db.query(OperationalAlertLog)
            .filter(OperationalAlertLog.organization_id == organization_id)
            .order_by(OperationalAlertLog.created_at.desc())
            .limit(10)
            .all()
        )
        for item in persisted:
            notifications.append({
                "id": f"persisted:{item.id}",
                "type": "persisted_alert",
                "severity": item.severity,
                "title": item.alert_type.replace("_", " ").title(),
                "message": item.message,
                "created_at": item.created_at.isoformat(),
                "source": "alert_log",
                "ride_id": cls._safe_json(item.payload).get("ride_id"),
            })

        notifications.sort(key=lambda item: item["created_at"], reverse=True)
        return notifications[:limit]

    @classmethod
    def build_timeline(
        cls,
        db: Session,
        organization_id: str,
        ride_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        logger.info("Reached timeline DB query step: dispatcher activity")
        activities, _ = ActivityLogService.get_activity_feed(db, organization_id, limit=limit, skip=0, ride_id=ride_id)
        for row in activities:
            items.append({
                "id": f"activity:{row.id}",
                "kind": "dispatcher_activity",
                "timestamp": row.created_at.isoformat(),
                "title": str(row.action).replace("_", " ").title(),
                "summary": row.description,
                "severity": cls._severity_from_activity(str(row.action)),
                "ride_id": row.ride_id,
                "driver_id": row.driver_id,
                "payload": cls._safe_json(row.details),
            })

        logger.info("Reached timeline DB query step: realtime events")
        event_query = db.query(RealTimeEvent).filter(RealTimeEvent.organization_id == organization_id)
        if ride_id:
            event_query = event_query.filter(RealTimeEvent.ride_id == ride_id)
        for row in event_query.order_by(RealTimeEvent.created_at.desc()).limit(limit).all():
            items.append({
                "id": f"event:{row.id}",
                "kind": "websocket_event",
                "timestamp": row.created_at.isoformat(),
                "title": str(row.event_type).replace("_", " ").title(),
                "summary": cls._event_summary(row),
                "severity": cls._severity_from_event(str(row.event_type)),
                "ride_id": row.ride_id,
                "driver_id": row.driver_id,
                "payload": cls._safe_json(row.payload),
            })

        logger.info("Reached timeline DB query step: workflow audit logs")
        audit_query = db.query(HealthISFWorkflowAuditLog).filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
        if ride_id:
            workflows = WorkflowOrchestrationService.list_workflows(db, organization_id=organization_id, limit=200)
            ride_workflow_ids = {item["id"] for item in workflows if item.get("ride_id") == ride_id}
            if ride_workflow_ids:
                audit_query = audit_query.filter(HealthISFWorkflowAuditLog.workflow_execution_id.in_(ride_workflow_ids))
        for row in audit_query.order_by(HealthISFWorkflowAuditLog.created_at.desc()).limit(limit).all():
            payload = cls._safe_json(row.payload)
            items.append({
                "id": f"workflow:{row.id}",
                "kind": "workflow_audit",
                "timestamp": row.created_at.isoformat(),
                "title": str(row.event_type).replace("_", " ").title(),
                "summary": cls._stringify_timeline_value(payload.get("summary") or payload.get("message") or row.event_type),
                "severity": cls._severity_from_workflow(str(row.event_type)),
                "ride_id": payload.get("ride_id"),
                "driver_id": payload.get("driver_id"),
                "payload": payload,
            })

        if ride_id:
            for row in service.get_ride_status_history(db, ride_id):
                items.append({
                    "id": f"ride_history:{row.id}",
                    "kind": "ride_lifecycle",
                    "timestamp": row.created_at.isoformat(),
                    "title": "Ride lifecycle",
                    "summary": f"{row.from_status or 'unknown'} -> {row.to_status}",
                    "severity": "high" if row.to_status == RideStatus.CANCELLED.value else "info",
                    "ride_id": ride_id,
                    "driver_id": None,
                    "payload": {
                        "from_status": row.from_status,
                        "to_status": row.to_status,
                        "note": row.note,
                    },
                })

        items.sort(key=lambda item: item["timestamp"], reverse=True)
        return items[:limit]

    @classmethod
    def assist_intake(
        cls,
        db: Session,
        organization_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        distance = float(payload.get("estimated_distance_miles") or 0.0)
        duration = payload.get("estimated_duration_minutes") or calculate_duration_minutes(distance)
        priority_tag = normalize_priority_tag(payload.get("priority_tag"))
        is_emergency = bool(payload.get("is_emergency") or priority_tag == "emergency")
        priority_score = calculate_priority_score(
            priority_tag=priority_tag,
            service_type=str(payload.get("service_type") or "medical_transport"),
            appointment_time=payload.get("appointment_time"),
            distance_miles=distance,
            is_emergency=is_emergency,
        )
        ai_context = build_ai_dispatch_context(
            organization_id=organization_id,
            service_type=str(payload.get("service_type") or "medical_transport"),
            priority_tag=priority_tag,
            priority_score=priority_score,
            estimated_distance_miles=distance,
            estimated_duration_minutes=int(duration),
            appointment_time=payload.get("appointment_time"),
            recurring_trip_pattern=payload.get("recurring_trip_pattern"),
            is_emergency=is_emergency,
        )

        providers = [item for item in service.get_all_providers(db, skip=0, limit=200) if item.organization_id == organization_id and item.is_active]
        suggested_providers = sorted(
            providers,
            key=lambda item: cls._provider_score(item, str(payload.get("service_type") or ""), str(payload.get("pickup_address") or "")),
            reverse=True,
        )[:5]
        drivers = [item for item in service.get_available_drivers(db) if item.organization_id == organization_id]
        suggested_drivers = sorted(drivers, key=lambda item: (float(item.rating or 0.0), -(item.total_trips or 0)), reverse=True)[:5]

        fingerprint = build_intake_fingerprint(
            organization_id=organization_id,
            passenger_name=str(payload.get("passenger_name") or "Unknown Passenger"),
            passenger_phone=str(payload.get("passenger_phone") or "unknown"),
            pickup_address=str(payload.get("pickup_address") or "unknown"),
            dropoff_address=str(payload.get("dropoff_address") or "unknown"),
            service_type=str(payload.get("service_type") or "medical_transport"),
            provider_id=str(payload.get("provider_id") or (suggested_providers[0].id if suggested_providers else "")),
            appointment_time=payload.get("appointment_time"),
        )
        recent_duplicate = service.find_recent_duplicate_ride(
            db,
            organization_id=organization_id,
            intake_fingerprint=fingerprint,
            within_seconds=60 * 60,
        )
        duplicate_candidates = []
        if recent_duplicate:
            duplicate_candidates.append({
                "ride_id": recent_duplicate.id,
                "passenger_name": recent_duplicate.passenger_name,
                "status": str(recent_duplicate.status),
                "pickup_address": recent_duplicate.pickup_address,
                "requested_at": recent_duplicate.requested_at.isoformat() if recent_duplicate.requested_at else None,
            })

        dispatcher_notes = cls._build_dispatcher_notes(
            service_type=str(payload.get("service_type") or "medical_transport"),
            is_emergency=is_emergency,
            priority_score=priority_score,
            duplicate_count=len(duplicate_candidates),
            suggested_provider=suggested_providers[0].name if suggested_providers else None,
            suggested_driver=suggested_drivers[0].name if suggested_drivers else None,
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "urgency": cls._urgency_band(priority_score, is_emergency),
            "priority_score": priority_score,
            "estimated_duration_minutes": int(duration),
            "suggested_provider_ids": [item.id for item in suggested_providers],
            "suggested_driver_ids": [item.id for item in suggested_drivers],
            "duplicate_candidates": duplicate_candidates,
            "dispatcher_notes": dispatcher_notes,
            "ai_dispatch_context": ai_context,
        }

    @classmethod
    def parse_voice_command(
        cls,
        db: Session,
        organization_id: str,
        transcript: str,
        ride_id: str | None = None,
    ) -> dict[str, Any]:
        text = " ".join(str(transcript or "").split())
        lowered = text.lower()
        extracted_ride_id = ride_id or cls._extract_match(cls._RIDE_ID_RE, text)
        extracted_driver_id = cls._extract_match(cls._DRIVER_ID_RE, text)

        intent = "summarize_operations"
        action_label = "Summarize operations"
        recommended_endpoint = "/api/health-isf/intelligence/summary"

        if "reassign" in lowered:
            intent = "reassign_driver"
            action_label = "Reassign driver"
            recommended_endpoint = f"/api/health-isf/dispatcher/rides/{extracted_ride_id or '{ride_id}'}/reassign-driver"
        elif "assign" in lowered and "driver" in lowered:
            intent = "assign_driver"
            action_label = "Assign driver"
            recommended_endpoint = f"/api/health-isf/rides/{extracted_ride_id or '{ride_id}'}/assign-driver"
        elif "cancel" in lowered:
            intent = "cancel_ride"
            action_label = "Cancel ride"
            recommended_endpoint = f"/api/health-isf/dispatcher/rides/{extracted_ride_id or '{ride_id}'}/cancel"
        elif "intake" in lowered or "create ride" in lowered or "new ride" in lowered:
            intent = "prepare_intake"
            action_label = "Prepare ride intake"
            recommended_endpoint = "/api/health-isf/ai-dispatch/intake/assist"
        elif "escalate" in lowered or "emergency" in lowered:
            intent = "escalate_issue"
            action_label = "Escalate issue"
            recommended_endpoint = f"/api/health-isf/dispatcher/rides/{extracted_ride_id or '{ride_id}'}/escalate"
        elif "delay" in lowered or "late" in lowered:
            intent = "review_delays"
            action_label = "Review delayed rides"
            recommended_endpoint = "/api/health-isf/ops/alerts"
        elif "replay" in lowered or "recover" in lowered:
            intent = "replay_failed_events"
            action_label = "Replay failed events"
            recommended_endpoint = "/api/health-isf/ai-dispatch/resilience/replay"

        recommendations = OperationalIntelligenceService.build_recommendations(db, organization_id, ride_id=extracted_ride_id)
        summary = OperationalIntelligenceService.summarize(db, organization_id, ride_id=extracted_ride_id)
        intake_entities = cls._extract_intake_entities(text)

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "transcript": text,
            "intent": intent,
            "action_label": action_label,
            "extracted_entities": {
                "ride_id": extracted_ride_id,
                "driver_id": extracted_driver_id,
                "passenger_name": intake_entities.get("passenger_name"),
                "pickup_address": intake_entities.get("pickup_address"),
                "dropoff_address": intake_entities.get("dropoff_address"),
                "passenger_phone": intake_entities.get("passenger_phone"),
                "service_type": intake_entities.get("service_type"),
                "priority_tag": intake_entities.get("priority_tag"),
                "is_emergency": intake_entities.get("is_emergency"),
            },
            "recommendation_summary": summary.get("summary"),
            "recommended_endpoint": recommended_endpoint,
            "automation_hints": recommendations.get("dispatcher_recommendation_payloads", [])[:5],
        }

    @staticmethod
    def _safe_json(raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            return {}

    @staticmethod
    def _extract_match(pattern: re.Pattern[str], text: str) -> str | None:
        match = pattern.search(text)
        return match.group(1) if match else None

    @classmethod
    def _extract_intake_entities(cls, text: str) -> dict[str, str | None]:
        entities: dict[str, str | None] = {
            "passenger_name": None,
            "pickup_address": None,
            "dropoff_address": None,
            "passenger_phone": None,
            "service_type": None,
            "priority_tag": None,
            "is_emergency": None,
        }

        route_match = cls._FROM_TO_RE.search(text)
        if route_match:
            entities["pickup_address"] = route_match.group(1).strip(" .,")
            entities["dropoff_address"] = route_match.group(2).strip(" .,")

        passenger_match = cls._PASSENGER_RE.search(text)
        if passenger_match:
            entities["passenger_name"] = passenger_match.group(1).strip(" .,")

        phone_match = cls._PHONE_RE.search(text)
        if phone_match:
            entities["passenger_phone"] = re.sub(r"\s+", " ", phone_match.group(1)).strip()

        service_match = cls._SERVICE_TYPE_RE.search(text)
        if service_match:
            entities["service_type"] = service_match.group(1).lower().replace(" ", "_")

        priority_match = cls._PRIORITY_RE.search(text)
        if priority_match:
            priority_value = priority_match.group(2).lower()
            entities["priority_tag"] = priority_value
            entities["is_emergency"] = "true" if priority_value == "emergency" else "false"
        elif "emergency" in text.lower() or "stat" in text.lower():
            entities["priority_tag"] = "emergency"
            entities["is_emergency"] = "true"

        return entities

    @staticmethod
    def _urgency_band(priority_score: float, is_emergency: bool) -> str:
        if is_emergency or priority_score >= 85:
            return "emergency"
        if priority_score >= 70:
            return "high"
        if priority_score >= 50:
            return "normal"
        return "low"

    @staticmethod
    def _provider_score(provider: HealthISFProvider, service_type: str, pickup_address: str) -> tuple[int, int, str]:
        service_match = 1 if service_type and service_type.lower() in str(provider.service_type or "").lower() else 0
        address_match = 1 if pickup_address and pickup_address.lower().split(",")[0] in str(provider.address or "").lower() else 0
        return (service_match, address_match, provider.name)

    @staticmethod
    def _build_dispatcher_notes(
        *,
        service_type: str,
        is_emergency: bool,
        priority_score: float,
        duplicate_count: int,
        suggested_provider: str | None,
        suggested_driver: str | None,
    ) -> list[str]:
        notes = [
            f"Priority score computed at {priority_score} for {service_type} transport.",
            "Elevate to emergency dispatch flow immediately." if is_emergency else "Standard dispatch workflow can proceed with AI safeguards.",
        ]
        if duplicate_count:
            notes.append("Potential duplicate intake detected. Review before creating a new ride.")
        if suggested_provider:
            notes.append(f"Suggested provider: {suggested_provider}.")
        if suggested_driver:
            notes.append(f"Suggested available driver: {suggested_driver}.")
        return notes

    @staticmethod
    def _severity_from_activity(action: str) -> str:
        action = action.lower()
        if "cancel" in action or "escalat" in action:
            return "high"
        if "retry" in action or "reassign" in action:
            return "medium"
        return "info"

    @staticmethod
    def _severity_from_event(event_type: str) -> str:
        event_type = event_type.lower()
        if "disconnect" in event_type or "failed" in event_type:
            return "high"
        if "escalat" in event_type or "retry" in event_type:
            return "medium"
        return "info"

    @staticmethod
    def _severity_from_workflow(event_type: str) -> str:
        event_type = event_type.lower()
        if "failed" in event_type or "incident" in event_type:
            return "high"
        if "replay" in event_type or "escalation" in event_type:
            return "medium"
        return "info"

    @staticmethod
    def _event_summary(row: RealTimeEvent) -> str:
        payload = AIDispatchOrchestrationService._safe_json(row.payload)
        return AIDispatchOrchestrationService._stringify_timeline_value(
            payload.get("summary") or payload.get("status") or row.event_type
        )

    @staticmethod
    def _stringify_timeline_value(value: Any) -> str:
        if isinstance(value, dict):
            for key in ("summary", "message", "status", "detail", "title"):
                nested = value.get(key)
                if nested not in (None, ""):
                    return AIDispatchOrchestrationService._stringify_timeline_value(nested)
            return json.dumps(value, default=str)
        if isinstance(value, list):
            return ", ".join(
                AIDispatchOrchestrationService._stringify_timeline_value(item)
                for item in value
                if item not in (None, "")
            ) or "update"
        if value in (None, ""):
            return "update"
        return str(value)

    @staticmethod
    def _top_priority_focus(recommendations: dict[str, Any], alerts: list[dict[str, Any]]) -> str:
        if alerts:
            return alerts[0]["message"]
        items = recommendations.get("recommendations", [])
        if items:
            return items[0].get("explanation_summary") or items[0].get("entity_id") or "Action available"
        return "No urgent dispatch intervention required"