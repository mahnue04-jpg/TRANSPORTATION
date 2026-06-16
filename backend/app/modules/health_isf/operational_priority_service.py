"""Priority and severity scoring for operational recommendation candidates."""

from __future__ import annotations

from typing import Any

from app.modules.health_isf.operational_decision_models import OperationalPressureSnapshot


class OperationalPriorityService:
    @staticmethod
    def build_pressure_snapshot(
        *,
        metrics: dict[str, Any],
        geospatial_snapshot: dict[str, Any],
        sync_snapshot: dict[str, Any],
    ) -> OperationalPressureSnapshot:
        live_map = geospatial_snapshot.get("live_operational_map_state") or {}
        event_bus = sync_snapshot.get("event_bus") or {}

        active_rides = float(metrics.get("active_rides") or 0.0)
        unassigned_rides = float(metrics.get("unassigned_rides") or 0.0)
        available_drivers = float(metrics.get("available_drivers") or 0.0)
        active_drivers = float(metrics.get("active_drivers") or 0.0)
        active_providers = float(metrics.get("active_providers") or 0.0)

        incidents = float(len(live_map.get("incident_clustering") or []))
        emergency = float(len(live_map.get("emergency_overlays") or []))
        density_regions = float(len(live_map.get("operational_density_regions") or []))
        disconnects = float((metrics.get("websocket") or {}).get("disconnects_last_5m") or 0.0)
        total_events = float(event_bus.get("total_events") or 0.0)

        regional_congestion = min(1.0, (density_regions * 0.1 + incidents * 0.12 + emergency * 0.15))
        driver_load_pressure = min(
            1.0,
            (active_rides / max(1.0, available_drivers + active_drivers)) * 0.65 + (unassigned_rides / 10.0) * 0.35,
        )
        provider_queue_pressure = min(1.0, (active_rides / max(1.0, active_providers)) * 0.7 + emergency * 0.08)
        escalation_surge = min(1.0, emergency * 0.2 + incidents * 0.1)
        incident_clustering = min(1.0, incidents * 0.16 + density_regions * 0.07)
        continuity_degradation_risk = min(1.0, disconnects * 0.08 + total_events / 300.0)

        return OperationalPressureSnapshot(
            regional_congestion=regional_congestion,
            driver_load_pressure=driver_load_pressure,
            provider_queue_pressure=provider_queue_pressure,
            escalation_surge=escalation_surge,
            incident_clustering=incident_clustering,
            continuity_degradation_risk=continuity_degradation_risk,
        )

    @staticmethod
    def severity_weight(*, recommendation_type: str, pressure: OperationalPressureSnapshot) -> float:
        base = {
            "escalation_prioritization": 0.95,
            "dispatch_rebalance": 0.85,
            "congestion_reroute": 0.78,
            "workload_balance": 0.72,
            "continuity_risk_warning": 0.9,
            "resource_pressure_watch": 0.7,
        }.get(recommendation_type, 0.68)

        intensity = (
            pressure.regional_congestion * 0.2
            + pressure.driver_load_pressure * 0.2
            + pressure.provider_queue_pressure * 0.2
            + pressure.escalation_surge * 0.2
            + pressure.continuity_degradation_risk * 0.2
        )
        return round(min(1.0, max(0.15, base * 0.75 + intensity * 0.35)), 4)

    @staticmethod
    def escalation_score(*, severity_weight: float, pressure: OperationalPressureSnapshot) -> float:
        score = (
            severity_weight * 0.45
            + pressure.escalation_surge * 0.2
            + pressure.incident_clustering * 0.2
            + pressure.continuity_degradation_risk * 0.15
        )
        return round(min(1.0, max(0.0, score)), 4)

    @staticmethod
    def priority_score(*, severity_weight: float, escalation_score: float, confidence: float) -> float:
        score = severity_weight * 0.45 + escalation_score * 0.35 + confidence * 0.2
        return round(min(1.0, max(0.0, score)), 4)
