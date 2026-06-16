"""Predictive operations engine with rolling-window telemetry analysis."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.models import HealthISFRide, RideStatus
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.realtime_service import RetryQueueService


class PredictiveOperationsEngine:
    @classmethod
    def predict(cls, db: Session, *, organization_id: str) -> list[dict[str, Any]]:
        metrics = build_operational_metrics(db, organization_id=organization_id)
        queue = RetryQueueService.get_queue_stats(db, organization_id=organization_id)

        now_ts = now()
        one_hour_ago = now_ts - timedelta(hours=1)
        six_hours_ago = now_ts - timedelta(hours=6)

        rides_1h = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .filter(HealthISFRide.created_at >= one_hour_ago)
            .all()
        )
        rides_6h = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .filter(HealthISFRide.created_at >= six_hours_ago)
            .all()
        )

        pending_1h = sum(1 for r in rides_1h if str(r.status) == RideStatus.PENDING.value)
        emergency_1h = sum(1 for r in rides_1h if bool(getattr(r, "is_emergency", False)))
        avg_hourly_volume = (len(rides_6h) / 6.0) if rides_6h else 0.0
        demand_ratio = (len(rides_1h) / avg_hourly_volume) if avg_hourly_volume > 0 else 0.0

        available_drivers = int(metrics.get("available_drivers") or 0)
        pending_rides = int(metrics.get("pending_rides") or 0)
        retry_queued = int(queue.get("queued") or 0)

        predictions: list[dict[str, Any]] = []

        def add(window: str, risk_score: float, issue: str, prevention: list[str]) -> None:
            predictions.append(
                {
                    "prediction_window": window,
                    "risk_score": round(max(0.0, min(1.0, risk_score)), 4),
                    "predicted_issue": issue,
                    "recommended_prevention": prevention,
                }
            )

        overload_risk = min(1.0, (pending_rides / max(available_drivers, 1)) / 5.0)
        add(
            "next_30m",
            overload_risk,
            "dispatch_overload_window" if overload_risk >= 0.45 else "stable_dispatch_window",
            [
                "preemptive_driver_rebalance",
                "prioritize_high_acuity_rides",
                "activate_provider_balance_plan",
            ],
        )

        sla_risk = min(1.0, float(metrics.get("sla_breach_rate_percent") or 0.0) / 100.0 + overload_risk * 0.25)
        add(
            "next_60m",
            sla_risk,
            "sla_degradation_probability" if sla_risk >= 0.35 else "sla_stable_probability",
            [
                "run_proactive_reassignments",
                "monitor_emergency_latency",
                "enable_auto_escalation_for_high_risk",
            ],
        )

        provider_risk = min(1.0, float(metrics.get("provider_failures") or 0) / 10.0 + max(0.0, demand_ratio - 1.0) * 0.2)
        add(
            "next_90m",
            provider_risk,
            "provider_bottleneck_risk" if provider_risk >= 0.4 else "provider_throughput_stable",
            [
                "spread_load_across_top_providers",
                "watch_provider_completion_rate",
                "queue_backup_provider_activation",
            ],
        )

        driver_shortage_risk = min(1.0, max(0.0, (pending_1h - available_drivers) / max(available_drivers, 1)) * 0.2)
        add(
            "next_2h",
            driver_shortage_risk,
            "driver_shortage_risk" if driver_shortage_risk >= 0.35 else "driver_capacity_stable",
            [
                "stage_oncall_drivers",
                "reduce_non_urgent_dispatch",
                "auto-balance_ride_queue",
            ],
        )

        emergency_spike_risk = min(1.0, emergency_1h / max(len(rides_1h), 1) + max(0.0, demand_ratio - 1.0) * 0.15)
        add(
            "next_45m",
            emergency_spike_risk,
            "emergency_spike_probability" if emergency_spike_risk >= 0.3 else "emergency_load_normal",
            [
                "reserve_high_priority_driver_pool",
                "pre-warm_emergency_workflows",
                "increase_realtime_incident_polling",
            ],
        )

        retry_storm_risk = min(1.0, retry_queued / 50.0)
        add(
            "next_30m",
            retry_storm_risk,
            "retry_storm_probability" if retry_storm_risk >= 0.4 else "retry_queue_stable",
            [
                "increase_retry_backoff",
                "drain_retry_queue_gradually",
                "open_dead_letter_audit_if_needed",
            ],
        )

        return predictions
