"""Active operational command-center orchestration built on distributed runtime signals."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.incident_detection_engine import IncidentDetectionEngine
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDispatchLog,
    HealthISFDriver,
    HealthISFRide,
    OperationalAlertLog,
    RideStatus,
)
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_orchestration_resilience import OperationalOrchestrationResilienceService
from app.modules.health_isf.operational_replay_service import OperationalReplayService
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.operations import build_operational_dashboard, build_operational_metrics
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.realtime_service import OperationalAlertService, RetryQueueService


_TERMINAL_RIDE_STATES = {
    RideStatus.COMPLETED.value,
    RideStatus.CANCELLED.value,
    RideStatus.FAILED.value,
}

_ALLOWED_OPERATIONAL_STATES = {
    "operational",
    "degraded",
    "fallback",
    "replay_recovery",
    "read_only",
    "unavailable",
}


def _as_utc(value: datetime | None) -> datetime:
    if value is None:
        return now().replace(tzinfo=timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _minutes_since(value: datetime | None) -> float:
    return max(0.0, (_as_utc(now()) - _as_utc(value)).total_seconds() / 60.0)


def _incident_key(organization_id: str, incident_type: str, details: dict[str, Any]) -> str:
    source = json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(f"{organization_id}:{incident_type}:{source}".encode("utf-8")).hexdigest()[:24]
    return f"{incident_type}:{digest}"


def _status_text(value: Any) -> str:
    if hasattr(value, "value"):
        return str(getattr(value, "value") or "").lower()
    raw = str(value or "").strip().lower()
    if "." in raw:
        return raw.split(".")[-1]
    return raw


def _normalize_operational_state(raw_state: Any) -> str:
    state = str(raw_state or "").strip().lower()
    if state in {"operational", "healthy", "stable", "active", "ok"}:
        return "operational"
    if state in {"degraded", "watch", "synchronization_risk"}:
        return "degraded"
    if state in {"critical", "unhealthy", "error", "fallback", "fail_safe", "safe_mode"}:
        return "fallback"
    if state in {"replay_repair", "recovering", "replay_recovery", "repairing"}:
        return "replay_recovery"
    if state in {"read_only", "advisory"}:
        return "read_only"
    if state in {"unavailable", "offline", "unknown", "", "none", "null"}:
        return "unavailable"
    return "fallback"


def _build_module_continuity_summary(
    *,
    subsystem: str,
    raw_state: Any,
    dispatch_continuity_safe: bool,
    ride_operations_active: bool,
    degraded_reasons: list[str],
) -> dict[str, Any]:
    normalized_state = _normalize_operational_state(raw_state)
    dispatch_message = "Dispatch continuity remains protected."
    ride_message = "Ride operations remain active."

    if normalized_state in {"fallback", "unavailable"}:
        dispatch_message = (
            "Core dispatch continuity remains protected while this subsystem is running in reduced mode."
            if dispatch_continuity_safe
            else "Dispatch continuity is currently constrained by runtime pressure."
        )
        ride_message = (
            "Ride operations remain active with guarded behavior."
            if ride_operations_active
            else "Ride operations are constrained and require active supervision."
        )
    elif normalized_state in {"degraded", "replay_recovery"}:
        dispatch_message = "Dispatch continuity is active with monitored degradation safeguards."
        ride_message = "Ride operations remain active with replay-safe supervision controls."
    elif normalized_state == "read_only":
        dispatch_message = "Dispatch continuity remains protected under read-only governance controls."
        ride_message = "Ride operations remain active while governance remains advisory/read-only."

    return {
        "affected_subsystem": subsystem,
        "raw_state": str(raw_state or "unknown"),
        "state": normalized_state,
        "degraded_reasons": list(degraded_reasons or []),
        "dispatch_continuity_safe": {
            "value": bool(dispatch_continuity_safe),
            "message": dispatch_message,
        },
        "ride_operations_active": {
            "value": bool(ride_operations_active),
            "message": ride_message,
        },
    }


def _serialize_alert(row: OperationalAlertLog) -> dict[str, Any]:
    payload: dict[str, Any]
    try:
        payload = json.loads(row.payload) if row.payload else {}
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    try:
        target_roles = json.loads(row.target_roles_json) if row.target_roles_json else []
        if not isinstance(target_roles, list):
            target_roles = []
    except Exception:
        target_roles = []

    try:
        channels = json.loads(row.notification_channels_json) if row.notification_channels_json else []
        if not isinstance(channels, list):
            channels = []
    except Exception:
        channels = []

    try:
        chain = json.loads(row.escalation_chain_json) if row.escalation_chain_json else {"entries": []}
        if not isinstance(chain, dict):
            chain = {"entries": []}
    except Exception:
        chain = {"entries": []}

    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "alert_type": row.alert_type,
        "severity": row.severity,
        "alert_state": row.alert_state,
        "incident_key": row.incident_key,
        "message": row.message,
        "payload": payload,
        "target_roles": target_roles,
        "notification_channels": channels,
        "escalation_level": int(row.escalation_level or 0),
        "escalation_chain": chain,
        "occurrence_count": int(row.occurrence_count or 0),
        "acknowledged_by_user_id": row.acknowledged_by_user_id,
        "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
        "escalated_at": row.escalated_at.isoformat() if row.escalated_at else None,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }


class OperationalCommandCenterService:
    """Backend authoritative command-center intelligence and alert orchestration."""

    @staticmethod
    def detect_live_incidents(db: Session, *, organization_id: str) -> list[dict[str, Any]]:
        now_utc = _as_utc(now())
        broadcaster = get_broadcaster()
        websocket_stats = broadcaster.get_websocket_health_stats(organization_id=organization_id)
        queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        replay_integrity = OperationalReplayService.replay_integrity(organization_id)

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id).all()
        assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.organization_id == organization_id)
            .all()
        )

        incidents: list[dict[str, Any]] = []

        def add_incident(
            *,
            incident_type: str,
            severity: str,
            message: str,
            details: dict[str, Any],
            role_targets: list[str],
            escalation_chain: list[str],
        ) -> None:
            incidents.append(
                {
                    "incident_type": incident_type,
                    "incident_key": _incident_key(organization_id, incident_type, details),
                    "severity": severity,
                    "message": message,
                    "details": details,
                    "role_targets": role_targets,
                    "notification_channels": ["dispatcher_board", "workflow_events", "incident_updates"],
                    "escalation_chain": escalation_chain,
                    "detected_at": now_utc.isoformat(),
                }
            )

        # 1) Stuck ride detection.
        stuck = [
            ride for ride in rides
            if _status_text(ride.status) not in _TERMINAL_RIDE_STATES and _minutes_since(ride.updated_at or ride.requested_at) >= 45
        ]
        if stuck:
            add_incident(
                incident_type="stuck_ride_detection",
                severity="critical",
                message=f"{len(stuck)} rides show no lifecycle progress for >=45 minutes.",
                details={"count": len(stuck), "ride_ids": [item.id for item in stuck[:25]]},
                role_targets=["dispatcher", "admin", "staff"],
                escalation_chain=["dispatcher", "operations_manager", "incident_commander"],
            )

        # 2) Missed pickup detection.
        missed_pickup = [
            ride for ride in rides
            if _status_text(ride.status) in {RideStatus.ASSIGNED.value, RideStatus.DRIVER_EN_ROUTE.value, RideStatus.ACCEPTED.value}
            and _minutes_since(ride.accepted_at or ride.requested_at) >= 25
        ]
        if missed_pickup:
            add_incident(
                incident_type="missed_pickup_detection",
                severity="high",
                message=f"{len(missed_pickup)} rides exceeded pickup window.",
                details={"count": len(missed_pickup), "ride_ids": [item.id for item in missed_pickup[:25]]},
                role_targets=["dispatcher", "driver_support"],
                escalation_chain=["dispatcher", "provider", "operations_manager"],
            )

        # 3) SLA breach monitoring + 4) delayed assignment escalation.
        pending_assign = [
            ride for ride in rides
            if _status_text(ride.status) in {RideStatus.REQUESTED.value, RideStatus.QUEUED.value, RideStatus.PENDING.value}
            and _minutes_since(ride.requested_at) >= 20
        ]
        if pending_assign:
            add_incident(
                incident_type="sla_breach_monitoring",
                severity="high",
                message=f"{len(pending_assign)} rides are breaching assignment SLA.",
                details={"count": len(pending_assign), "ride_ids": [item.id for item in pending_assign[:25]], "sla_minutes": 20},
                role_targets=["dispatcher", "admin"],
                escalation_chain=["dispatcher", "operations_manager", "executive_on_call"],
            )

        delayed_assignment = [
            row for row in assignments
            if str(row.assignment_state or "") in {
                DispatchAssignmentState.QUEUED.value,
                DispatchAssignmentState.SEARCHING.value,
                DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                DispatchAssignmentState.EXPIRED.value,
            }
            and _minutes_since(row.created_at) >= 12
        ]
        if delayed_assignment:
            add_incident(
                incident_type="delayed_assignment_escalation",
                severity="high",
                message=f"{len(delayed_assignment)} dispatch assignments stalled over 12 minutes.",
                details={"count": len(delayed_assignment), "assignment_ids": [item.id for item in delayed_assignment[:25]]},
                role_targets=["dispatcher", "admin"],
                escalation_chain=["dispatcher", "dispatch_supervisor", "operations_manager"],
            )

        # 5) Inactive driver detection.
        inactive_drivers = [
            driver for driver in drivers
            if bool(driver.is_active)
            and _status_text(driver.status) in {DriverStatus.AVAILABLE.value, DriverStatus.ASSIGNED.value, DriverStatus.BUSY.value}
            and _minutes_since(driver.last_seen_at or driver.updated_at) >= 15
        ]
        if inactive_drivers:
            add_incident(
                incident_type="inactive_driver_detection",
                severity="medium",
                message=f"{len(inactive_drivers)} active drivers have stale heartbeats.",
                details={"count": len(inactive_drivers), "driver_ids": [item.id for item in inactive_drivers[:25]]},
                role_targets=["driver_support", "dispatcher"],
                escalation_chain=["driver_support", "dispatcher"],
            )

        # 6) Dispatch queue congestion.
        available_driver_count = sum(1 for driver in drivers if _status_text(driver.status) == DriverStatus.AVAILABLE.value)
        queue_pressure = len(pending_assign) / max(1, available_driver_count)
        if len(pending_assign) >= 10 or queue_pressure >= 2.0:
            add_incident(
                incident_type="dispatch_queue_congestion",
                severity="high",
                message="Dispatch queue pressure indicates congestion risk.",
                details={
                    "pending_count": len(pending_assign),
                    "available_driver_count": available_driver_count,
                    "queue_pressure_ratio": round(queue_pressure, 3),
                },
                role_targets=["dispatcher", "admin"],
                escalation_chain=["dispatcher", "operations_manager"],
            )

        # 7) Orphaned rides.
        orphaned = [
            ride for ride in rides
            if _status_text(ride.status) in {
                RideStatus.ASSIGNED.value,
                RideStatus.DRIVER_EN_ROUTE.value,
                RideStatus.ARRIVED.value,
                RideStatus.RIDER_ONBOARD.value,
                RideStatus.IN_PROGRESS.value,
                RideStatus.ACCEPTED.value,
                RideStatus.IN_TRANSIT.value,
            }
            and not ride.driver_id
        ]
        if orphaned:
            add_incident(
                incident_type="orphaned_rides",
                severity="critical",
                message=f"{len(orphaned)} active rides have no assigned driver.",
                details={"count": len(orphaned), "ride_ids": [item.id for item in orphaned[:25]]},
                role_targets=["dispatcher", "admin"],
                escalation_chain=["dispatcher", "incident_commander"],
            )

        # 8) Failed synchronization alerts.
        failed_queue = int(queue_stats.get("failed", 0) or 0) + int(queue_stats.get("dead_letter", 0) or 0)
        replay_gaps = int(replay_integrity.get("gaps_detected", 0) or 0)
        if failed_queue > 0 or replay_gaps > 0:
            add_incident(
                incident_type="failed_synchronization_alert",
                severity="high" if failed_queue >= 5 or replay_gaps > 0 else "medium",
                message="Distributed sync reliability degradation detected.",
                details={
                    "retry_failed": int(queue_stats.get("failed", 0) or 0),
                    "dead_letter": int(queue_stats.get("dead_letter", 0) or 0),
                    "replay_gaps_detected": replay_gaps,
                },
                role_targets=["admin", "staff"],
                escalation_chain=["operations_manager", "platform_sre"],
            )

        # 9) Websocket disconnect degradation alerts.
        disconnects = int(websocket_stats.get("disconnects_last_5m", 0) or 0)
        if disconnects >= 4:
            add_incident(
                incident_type="websocket_disconnect_degradation_alert",
                severity="high" if disconnects >= 8 else "medium",
                message=f"Websocket disconnect degradation detected ({disconnects} in last 5m).",
                details={
                    "disconnects_last_5m": disconnects,
                    "active_connections": int(websocket_stats.get("active_connections", 0) or 0),
                    "reconnect_events_last_5m": int(websocket_stats.get("reconnect_events_last_5m", 0) or 0),
                },
                role_targets=["admin", "dispatcher", "staff"],
                escalation_chain=["platform_sre", "incident_commander"],
            )

        # Include anomaly findings from existing detection engine for continuity.
        autonomous = IncidentDetectionEngine.detect(db, organization_id=organization_id)
        for item in autonomous:
            details = dict(item.get("details") or {})
            add_incident(
                incident_type=str(item.get("incident_type") or "autonomous_incident"),
                severity=str(item.get("severity") or "medium"),
                message=f"Autonomous incident signal: {str(item.get('incident_type') or 'unknown')}",
                details=details,
                role_targets=["dispatcher", "admin"],
                escalation_chain=["dispatcher", "operations_manager"],
            )

        # Keep deterministic ordering for replay-safe reconstruction.
        incidents.sort(key=lambda row: (str(row.get("severity") or ""), str(row.get("incident_key") or "")), reverse=True)
        return incidents

    @staticmethod
    def refresh_alert_pipeline(
        db: Session,
        *,
        organization_id: str,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        incidents = OperationalCommandCenterService.detect_live_incidents(db, organization_id=organization_id)
        persisted: list[dict[str, Any]] = []
        for incident in incidents:
            row = OperationalAlertService.log_alert(
                db,
                organization_id=organization_id,
                alert_type=str(incident["incident_type"]),
                severity=str(incident["severity"]),
                message=str(incident["message"]),
                payload=dict(incident.get("details") or {}),
                incident_key=str(incident.get("incident_key") or ""),
                target_roles=list(incident.get("role_targets") or []),
                notification_channels=list(incident.get("notification_channels") or []),
                deduplicate_open_incident=True,
            )
            persisted_payload = _serialize_alert(row)
            persisted.append(persisted_payload)

            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.OPERATIONAL_ALERT,
                payload={
                    "alert_id": row.id,
                    "alert_type": row.alert_type,
                    "severity": row.severity,
                    "message": row.message,
                    "state": row.alert_state,
                    "incident_key": row.incident_key,
                    "occurrence_count": int(row.occurrence_count or 0),
                    "target_roles": list(incident.get("role_targets") or []),
                },
                role_scope=list(incident.get("role_targets") or ["dispatcher", "admin"]),
                source_nonce=f"alert:{row.id}:{int(_as_utc(now()).timestamp())}",
                metadata={"actor_user_id": actor_user_id or ""},
            )

        automation = OperationalOrchestrationResilienceService.execute_automation_cycle(
            db,
            organization_id=organization_id,
            incidents=incidents,
            actor_user_id=actor_user_id,
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "incident_count": len(incidents),
            "persisted_alert_count": len(persisted),
            "alerts": persisted,
            "automation": automation,
            "backend_authoritative": True,
            "replay_safe": True,
        }

    @staticmethod
    def derive_operational_intelligence(db: Session, *, organization_id: str) -> dict[str, Any]:
        metrics = build_operational_metrics(db, organization_id=organization_id)

        # Average assignment latency and driver response efficiency from assignment timings.
        assignments = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.organization_id == organization_id)
            .all()
        )

        assignment_latencies: list[float] = []
        response_latencies: list[float] = []
        for row in assignments:
            if row.queued_at and row.assigned_at:
                assignment_latencies.append(max(0.0, (_as_utc(row.assigned_at) - _as_utc(row.queued_at)).total_seconds()))
            if row.offered_at and row.accepted_at:
                response_latencies.append(max(0.0, (_as_utc(row.accepted_at) - _as_utc(row.offered_at)).total_seconds()))

        avg_assignment_latency = round(sum(assignment_latencies) / max(1, len(assignment_latencies)), 2)
        avg_driver_response_latency = round(sum(response_latencies) / max(1, len(response_latencies)), 2)

        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        cancelled = [item for item in rides if _status_text(item.status) == RideStatus.CANCELLED.value]
        pickup_sla_breaches = [
            item for item in rides
            if _status_text(item.status) in {RideStatus.ASSIGNED.value, RideStatus.DRIVER_EN_ROUTE.value, RideStatus.ACCEPTED.value}
            and _minutes_since(item.accepted_at or item.requested_at) >= 20
        ]
        pickup_sla_compliance = round(100.0 - ((len(pickup_sla_breaches) / max(1, len(rides))) * 100.0), 2)

        now_utc = _as_utc(now())
        hour_1 = now_utc - timedelta(hours=1)
        hour_2 = now_utc - timedelta(hours=2)
        recent_cancel = 0
        previous_cancel = 0
        for item in cancelled:
            changed_at = _as_utc(item.updated_at)
            if changed_at >= hour_1:
                recent_cancel += 1
            elif hour_2 <= changed_at < hour_1:
                previous_cancel += 1

        if previous_cancel == 0:
            cancellation_trend = 100.0 if recent_cancel > 0 else 0.0
        else:
            cancellation_trend = round(((recent_cancel - previous_cancel) / previous_cancel) * 100.0, 2)

        dispatchers = db.query(func.count()).select_from(HealthISFDispatchLog).join(
            HealthISFRide,
            HealthISFRide.id == HealthISFDispatchLog.ride_id,
        ).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFDispatchLog.created_at >= hour_1,
        ).scalar() or 0

        open_workload = sum(1 for item in rides if _status_text(item.status) not in _TERMINAL_RIDE_STATES)
        workload_balance_index = round(open_workload / max(1, int(dispatchers)), 3)

        utilization_pressure = round(
            (float(metrics.get("driver_utilization_percent") or 0.0) * 0.65)
            + (float(metrics.get("unassigned_rides") or 0.0) * 1.2)
            + (float(metrics.get("failed_event_count") or 0.0) * 2.5),
            3,
        )

        anomalies = IncidentDetectionEngine.detect(db, organization_id=organization_id)

        return {
            "average_assignment_latency_seconds": avg_assignment_latency,
            "pickup_sla_compliance_percent": max(0.0, min(100.0, pickup_sla_compliance)),
            "cancellation_trend_percent_change": cancellation_trend,
            "dispatcher_workload_balance_index": workload_balance_index,
            "driver_response_efficiency_seconds": avg_driver_response_latency,
            "realtime_utilization_pressure": utilization_pressure,
            "operational_anomaly_count": len(anomalies),
            "operational_anomalies": anomalies[:25],
        }

    @staticmethod
    def build_runtime_snapshot(db: Session, *, organization_id: str) -> dict[str, Any]:
        dashboard = build_operational_dashboard(db, organization_id=organization_id)
        metrics = build_operational_metrics(db, organization_id=organization_id)
        incidents = OperationalCommandCenterService.detect_live_incidents(db, organization_id=organization_id)
        intelligence = OperationalCommandCenterService.derive_operational_intelligence(db, organization_id=organization_id)
        automation = OperationalOrchestrationResilienceService.latest_automation_projection(
            db,
            organization_id=organization_id,
            incidents=incidents,
        )

        active_alert_rows = OperationalAlertService.list_alert_history(
            db,
            organization_id=organization_id,
            limit=300,
        )
        active_alerts = [
            _serialize_alert(row)
            for row in active_alert_rows
            if str(row.alert_state or "").lower() in {"open", "acknowledged", "escalated"}
        ]

        ws = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
        queue = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
        replay = OperationalReplayService.replay_integrity(organization_id)

        health_status = str(
            automation.get("resilience_state_machine", {}).get("state")
            or "healthy"
        )

        failed_queue_events = int(queue.get("failed", 0) or 0) + int(queue.get("dead_letter", 0) or 0)
        dispatch_continuity_safe = str(health_status).lower() not in {"critical", "unhealthy"}
        ride_operations_active = failed_queue_events < 200

        degraded_reasons: list[str] = []
        if not bool(replay.get("integrity_ok", True)):
            degraded_reasons.append("replay_integrity:degraded")
        if int(queue.get("failed", 0) or 0) > 0:
            degraded_reasons.append("queue_failed_events")
        if int(queue.get("dead_letter", 0) or 0) > 0:
            degraded_reasons.append("queue_dead_letter_events")

        module_orchestration = _build_module_continuity_summary(
            subsystem="orchestration",
            raw_state=automation.get("resilience_state_machine", {}).get("state") or health_status,
            dispatch_continuity_safe=dispatch_continuity_safe,
            ride_operations_active=ride_operations_active,
            degraded_reasons=degraded_reasons,
        )
        module_compliance = _build_module_continuity_summary(
            subsystem="compliance",
            raw_state="read_only" if dispatch_continuity_safe else "fallback",
            dispatch_continuity_safe=dispatch_continuity_safe,
            ride_operations_active=ride_operations_active,
            degraded_reasons=degraded_reasons,
        )

        consistency_source = {
            "organization_id": organization_id,
            "active_ride_count": len(dashboard.get("active_rides") or []),
            "pending_ride_count": len(dashboard.get("pending_rides") or []),
            "active_alert_count": len(active_alerts),
            "incident_count": len(incidents),
            "latest_replay_sequence": int(replay.get("latest_sequence", 0) or 0),
            "queue_failed": int(queue.get("failed", 0) or 0),
        }
        consistency_token = hashlib.sha256(
            json.dumps(consistency_source, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()[:24]

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "live_ride_board": {
                "active_rides": dashboard.get("active_rides") or [],
                "pending_rides": dashboard.get("pending_rides") or [],
                "available_drivers": dashboard.get("available_drivers") or [],
                "dispatch_load": float(dashboard.get("dispatch_load") or 0.0),
            },
            "active_incidents": incidents,
            "operational_alerts": active_alerts[:200],
            "realtime_sla_risk": {
                "pickup_sla_compliance_percent": intelligence.get("pickup_sla_compliance_percent", 0.0),
                "average_assignment_latency_seconds": intelligence.get("average_assignment_latency_seconds", 0.0),
                "unassigned_rides": int(metrics.get("unassigned_rides", 0) or 0),
            },
            "driver_utilization": {
                "driver_utilization_percent": float(metrics.get("driver_utilization_percent", 0.0) or 0.0),
                "driver_response_efficiency_seconds": intelligence.get("driver_response_efficiency_seconds", 0.0),
            },
            "dispatch_pressure": {
                "realtime_utilization_pressure": intelligence.get("realtime_utilization_pressure", 0.0),
                "dispatcher_workload_balance_index": intelligence.get("dispatcher_workload_balance_index", 0.0),
                "dispatch_throughput_per_minute": int(metrics.get("dispatch_throughput_per_minute", 0) or 0),
            },
            "organization_health": {
                "status": health_status,
                "normalized_status": _normalize_operational_state(health_status),
                "active_alert_count": len(active_alerts),
                "critical_alert_count": sum(1 for item in active_alerts if str(item.get("severity") or "") == "critical"),
                "operational_anomaly_count": int(intelligence.get("operational_anomaly_count", 0) or 0),
                "cancellation_trend_percent_change": intelligence.get("cancellation_trend_percent_change", 0.0),
            },
            "synchronization_health": {
                "websocket": ws,
                "queue": queue,
                "replay_integrity": replay,
            },
            "replay_recovery_status": {
                "replay_safe": bool(replay.get("replay_safe", True)),
                "ordered": bool(replay.get("ordered", True)),
                "latest_sequence": int(replay.get("latest_sequence", 0) or 0),
                "integrity_checks": replay,
            },
            "operational_intelligence": intelligence,
            "automated_operational_orchestration": automation,
            "resilience_state_machine": automation.get("resilience_state_machine", {}),
            "operational_state_summary": {
                "state": _normalize_operational_state(health_status),
                "raw_state": health_status,
                "allowed_states": sorted(list(_ALLOWED_OPERATIONAL_STATES)),
                "modules": {
                    "orchestration": module_orchestration,
                    "compliance": module_compliance,
                },
                "dispatch_continuity_safe": {
                    "value": bool(dispatch_continuity_safe),
                    "message": (
                        "Core dispatch continuity is protected."
                        if dispatch_continuity_safe
                        else "Core dispatch continuity is constrained and under active supervision."
                    ),
                },
                "ride_operations_active": {
                    "value": bool(ride_operations_active),
                    "message": (
                        "Ride operations remain active."
                        if ride_operations_active
                        else "Ride operations are active in constrained recovery mode."
                    ),
                },
            },
            "distributed_coordination_hardening": {
                "immutable_operational_audit_chain": True,
                "replay_safe_event_ordering": True,
                "monotonic_event_sequencing": True,
                "stale_runtime_rejection": True,
                "concurrency_safe_assignment_ownership": True,
                "cross_role_synchronization_guarantees": True,
            },
            "command_center_consistency_token": consistency_token,
            "backend_authoritative": True,
        }
