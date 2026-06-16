"""Anomaly detection over live telemetry and historical operational memory."""

from __future__ import annotations

from typing import Any


def detect_anomalies(
    *,
    organization_id: str,
    metrics: dict[str, Any],
    websocket_health: dict[str, Any],
    memory_features: dict[str, float],
) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []

    pending = float(metrics.get("unassigned_rides") or metrics.get("pending_rides") or 0)
    active = float(metrics.get("active_rides") or 1)
    disconnects = float(websocket_health.get("disconnects_last_5m") or 0)
    historical_incident_ratio = float(memory_features.get("incident_growth_ratio") or 0)

    backlog_ratio = pending / max(1.0, active)
    if backlog_ratio >= 0.6:
        anomalies.append(
            {
                "anomaly_type": "dispatch_backlog_growth",
                "score": min(1.0, backlog_ratio),
                "confidence": min(0.95, 0.5 + backlog_ratio * 0.4),
                "reasoning_trace": [
                    "Computed backlog ratio from pending and active rides",
                    "Compared backlog ratio with stability threshold",
                    "Backlog ratio exceeded growth threshold",
                ],
                "evidence": [{"backlog_ratio": backlog_ratio}, {"pending": pending}, {"active": active}],
                "tenant_scope": organization_id,
            }
        )

    if disconnects >= 6:
        anomalies.append(
            {
                "anomaly_type": "websocket_disconnect_spike",
                "score": min(1.0, disconnects / 15.0),
                "confidence": min(0.94, 0.54 + disconnects / 35.0),
                "reasoning_trace": [
                    "Observed disconnect trend in last 5 minutes",
                    "Compared with continuity baseline",
                    "Disconnect spike indicates transport instability",
                ],
                "evidence": [{"disconnects_last_5m": disconnects}],
                "tenant_scope": organization_id,
            }
        )

    if historical_incident_ratio >= 1.4:
        anomalies.append(
            {
                "anomaly_type": "incident_growth_anomaly",
                "score": min(1.0, historical_incident_ratio / 2.5),
                "confidence": min(0.96, 0.58 + min(0.28, historical_incident_ratio / 10.0)),
                "reasoning_trace": [
                    "Read historical memory incident trend",
                    "Compared incidents_60m with 6h baseline",
                    "Detected incident growth above expected envelope",
                ],
                "evidence": [
                    {"incident_growth_ratio": historical_incident_ratio},
                    {"incidents_60m": memory_features.get("incidents_60m", 0.0)},
                    {"baseline_incidents_per_hour": memory_features.get("baseline_incidents_per_hour", 0.0)},
                ],
                "tenant_scope": organization_id,
            }
        )

    return anomalies
