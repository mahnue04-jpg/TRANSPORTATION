"""Autonomous incident detection engine for enterprise runtime health."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.realtime_service import RetryQueueService


class IncidentDetectionEngine:
    @staticmethod
    def _incident_id(organization_id: str, incident_type: str, details: dict[str, Any]) -> str:
        payload = json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)
        digest = hashlib.sha256(f"{organization_id}:{incident_type}:{payload}".encode("utf-8")).hexdigest()[:20]
        return f"inc_{digest}"

    @classmethod
    def detect(cls, db: Session, *, organization_id: str) -> list[dict[str, Any]]:
        metrics = build_operational_metrics(db, organization_id=organization_id)
        ws = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue = RetryQueueService.get_queue_stats(db, organization_id=organization_id)

        incidents: list[dict[str, Any]] = []

        def add_incident(incident_type: str, severity: str, affected_systems: list[str], recommended_actions: list[str], auto_recovery_possible: bool, details: dict[str, Any]) -> None:
            incidents.append(
                {
                    "incident_id": cls._incident_id(organization_id, incident_type, details),
                    "incident_type": incident_type,
                    "severity": severity,
                    "affected_systems": affected_systems,
                    "recommended_actions": recommended_actions,
                    "auto_recovery_possible": auto_recovery_possible,
                    "detected_at": now().isoformat(),
                    "details": details,
                }
            )

        if float(metrics.get("sla_breach_rate_percent") or 0.0) >= 20.0:
            add_incident(
                "sla_breach",
                "high",
                ["dispatch", "provider_network"],
                ["run_workflow_recovery", "prioritize_emergency_rides", "escalate_to_dispatch_supervisor"],
                True,
                {"sla_breach_rate_percent": metrics.get("sla_breach_rate_percent")},
            )

        if int(metrics.get("pending_rides") or 0) >= max(20, int(metrics.get("available_drivers") or 0) * 2):
            add_incident(
                "dispatch_congestion",
                "high",
                ["dispatch"],
                ["rebalance_driver_assignments", "activate_provider_failover", "trigger_auto_escalation"],
                True,
                {"pending_rides": metrics.get("pending_rides"), "available_drivers": metrics.get("available_drivers")},
            )

        if int(ws.get("disconnects_last_5m") or 0) >= 6:
            add_incident(
                "websocket_instability",
                "medium",
                ["realtime_event_system"],
                ["refresh_websocket_tokens", "reduce_client_reconnect_burst", "check_runtime_topology"],
                True,
                {"disconnects_last_5m": ws.get("disconnects_last_5m"), "active_connections": ws.get("active_connections")},
            )

        if int(metrics.get("provider_failures") or 0) >= 3:
            add_incident(
                "provider_failure_spike",
                "high",
                ["provider_network", "workflow_engine"],
                ["shift_volume_to_healthy_providers", "escalate_provider_ops", "audit_recent_provider_events"],
                True,
                {"provider_failures": metrics.get("provider_failures")},
            )

        if int(metrics.get("available_drivers") or 0) <= 2:
            add_incident(
                "driver_shortage",
                "high",
                ["driver_capacity", "dispatch"],
                ["throttle_non_urgent_dispatch", "request_standby_drivers", "optimize_active_routes"],
                False,
                {"available_drivers": metrics.get("available_drivers")},
            )

        if int(queue.get("queued") or 0) >= 25:
            add_incident(
                "retry_spike",
                "medium",
                ["retry_orchestration", "event_bus"],
                ["process_retry_queue", "open_dead_letter_review", "increase_backoff_window"],
                True,
                {"retry_queue": queue.get("queued"), "dead_letter": queue.get("dead_letter")},
            )

        if int(metrics.get("failed_event_count") or 0) >= 5:
            add_incident(
                "realtime_feed_degradation",
                "medium",
                ["realtime_event_system", "dashboard_hydration"],
                ["replay_failed_events", "verify_websocket_health", "run_ops_diagnostics"],
                True,
                {"failed_event_count": metrics.get("failed_event_count")},
            )

        return incidents
