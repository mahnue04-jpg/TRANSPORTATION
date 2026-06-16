"""Incident and risk analysis based on live operational state."""

from __future__ import annotations

from collections import Counter
from typing import Any


def analyze_incident_state(
    *,
    organization_id: str,
    metrics: dict[str, Any],
    websocket_health: dict[str, Any],
    queue_stats: dict[str, Any],
    live_incidents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    pending_rides = float(metrics.get("unassigned_rides") or metrics.get("pending_rides") or 0)
    active_rides = float(metrics.get("active_rides") or 0)
    driver_utilization = float(metrics.get("driver_utilization_percent") or 0)
    failed_events = float(metrics.get("failed_event_count") or 0)
    disconnects = float(websocket_health.get("disconnects_last_5m") or 0)
    retry_queued = float(queue_stats.get("queued") or 0)

    provider_types = [str(item.get("incident_type") or "") for item in live_incidents]
    provider_failure_events = sum(1 for value in provider_types if "provider" in value)

    if pending_rides >= 8 and driver_utilization >= 70:
        findings.append(
            {
                "type": "driver_imbalance",
                "severity": "high" if pending_rides >= 15 else "medium",
                "severity_score": min(1.0, (pending_rides / max(1.0, active_rides + 1.0)) * 0.8 + 0.2),
                "confidence": min(0.98, 0.55 + min(0.35, pending_rides / 40.0) + min(0.08, driver_utilization / 1000.0)),
                "reasoning_trace": [
                    "Measured pending or unassigned rides against active volume",
                    "Compared pressure with live driver utilization",
                    "Flagged potential assignment imbalance when both exceed threshold",
                ],
                "evidence": [
                    {"pending_rides": pending_rides},
                    {"driver_utilization_percent": driver_utilization},
                ],
                "affected_systems": ["dispatch", "driver_capacity"],
                "operational_impact": "Increased assignment latency and queue growth risk.",
                "recommended_action": "Rebalance assignments and prioritize high-acuity rides.",
                "rollback_impact": "Recommendation-only; no automated rollback required.",
                "tenant_scope": organization_id,
            }
        )

    if retry_queued >= 20 or failed_events >= 5:
        findings.append(
            {
                "type": "routing_instability",
                "severity": "high" if retry_queued >= 35 else "medium",
                "severity_score": min(1.0, retry_queued / 50.0 + failed_events / 20.0),
                "confidence": min(0.97, 0.6 + min(0.2, retry_queued / 100.0) + min(0.12, failed_events / 100.0)),
                "reasoning_trace": [
                    "Checked retry queue backlog for dispatch pipeline strain",
                    "Checked failed event count for routing reliability regressions",
                    "Combined backlog and failure evidence for routing instability signal",
                ],
                "evidence": [
                    {"retry_queue": retry_queued},
                    {"failed_event_count": failed_events},
                ],
                "affected_systems": ["routing", "event_bus", "workflow_engine"],
                "operational_impact": "May increase delayed dispatch and replay pressure.",
                "recommended_action": "Investigate queue backlog and apply controlled retry tuning.",
                "rollback_impact": "Recommendation-only; no runtime state mutation.",
                "tenant_scope": organization_id,
            }
        )

    if disconnects >= 4:
        findings.append(
            {
                "type": "websocket_instability_pattern",
                "severity": "high" if disconnects >= 10 else "medium",
                "severity_score": min(1.0, disconnects / 15.0),
                "confidence": min(0.96, 0.58 + min(0.3, disconnects / 40.0)),
                "reasoning_trace": [
                    "Read websocket disconnect trend in the last 5 minutes",
                    "Compared disconnect count with continuity thresholds",
                    "Flagged instability pattern due to elevated reconnect churn",
                ],
                "evidence": [
                    {"disconnects_last_5m": disconnects},
                    {"active_connections": websocket_health.get("active_connections", 0)},
                ],
                "affected_systems": ["realtime", "dashboard_hydration"],
                "operational_impact": "Can degrade live-feed consistency and operator confidence.",
                "recommended_action": "Review token refresh cadence and reconnect burst controls.",
                "rollback_impact": "Recommendation-only; websocket continuity logic unchanged.",
                "tenant_scope": organization_id,
            }
        )

    if provider_failure_events >= 1:
        type_counts = Counter(provider_types)
        findings.append(
            {
                "type": "overloaded_provider_signal",
                "severity": "medium" if provider_failure_events < 3 else "high",
                "severity_score": min(1.0, provider_failure_events / 5.0),
                "confidence": min(0.95, 0.52 + provider_failure_events * 0.1),
                "reasoning_trace": [
                    "Inspected live incidents for provider-related failure types",
                    "Counted provider-linked incident density",
                    "Raised overloaded provider signal based on incident mix",
                ],
                "evidence": [
                    {"provider_failure_incidents": provider_failure_events},
                    {"incident_type_mix": dict(type_counts)},
                ],
                "affected_systems": ["provider_network", "dispatch"],
                "operational_impact": "Provider saturation can increase cancellations and SLA pressure.",
                "recommended_action": "Shift load to healthy providers and monitor completion rate.",
                "rollback_impact": "Recommendation-only; no provider routing mutation executed.",
                "tenant_scope": organization_id,
            }
        )

    return findings
