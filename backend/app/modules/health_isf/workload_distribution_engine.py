"""Workload balancing recommendations for coordinated operational intelligence."""

from __future__ import annotations

from typing import Any


class WorkloadDistributionEngine:
    @staticmethod
    def summarize(*, metrics: dict[str, Any], forecast: dict[str, Any], decision: dict[str, Any]) -> dict[str, float]:
        active_rides = float(metrics.get("active_rides") or 0.0)
        active_drivers = float(metrics.get("active_drivers") or 0.0)
        providers = float(metrics.get("active_providers") or 0.0)
        workload_balance = float(forecast.get("workload_balance_forecast") or 0.0)
        resource_pressure = float(forecast.get("resource_pressure_forecast") or 0.0)
        decision_pressure = float((decision.get("pressure_analysis") or {}).get("driver_load_pressure") or 0.0)

        provider_driver_balance = min(1.0, (active_rides / max(1.0, active_drivers + providers)) * 0.6 + workload_balance * 0.4)
        operational_distribution = min(1.0, resource_pressure * 0.5 + decision_pressure * 0.5)
        return {
            "provider_driver_balance": round(provider_driver_balance, 4),
            "operational_distribution": round(operational_distribution, 4),
        }
