"""Recommendation-only routing engine for controlled dispatch intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import uuid4
from app.modules.health_isf.dispatch_models import DispatchRecommendation
from app.modules.health_isf.models import DriverStatus, HealthISFDriver, HealthISFRide, RideStatus


class RoutingRecommendationEngine:
    @staticmethod
    def build_recommendations(db: Session, organization_id: str) -> list[DispatchRecommendation]:
        rides = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .filter(HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED]))
            .order_by(HealthISFRide.requested_at.asc())
            .limit(50)
            .all()
        )
        drivers = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == organization_id)
            .filter(HealthISFDriver.status.in_([DriverStatus.AVAILABLE, DriverStatus.ASSIGNED]))
            .all()
        )

        if not rides or not drivers:
            return []

        recommendations: list[DispatchRecommendation] = []
        driver_load: dict[str, int] = {item.id: 0 for item in drivers}

        for ride in rides:
            ranked = sorted(
                drivers,
                key=lambda drv: (
                    driver_load.get(drv.id, 0),
                    0 if drv.status == DriverStatus.AVAILABLE else 1,
                    -(drv.rating or 0.0),
                    drv.total_trips,
                ),
            )
            best = ranked[0]
            driver_load[best.id] = driver_load.get(best.id, 0) + 1

            emergency_boost = 0.1 if bool(getattr(ride, "is_emergency", False)) else 0.0
            availability_boost = 0.15 if best.status == DriverStatus.AVAILABLE else 0.0
            quality_boost = min(0.2, max(0.0, float(best.rating or 0.0) / 25.0))
            load_penalty = min(0.25, driver_load.get(best.id, 0) * 0.05)
            confidence = max(0.05, min(0.98, 0.5 + emergency_boost + availability_boost + quality_boost - load_penalty))

            evidence: dict[str, Any] = {
                "driver_status": str(best.status),
                "driver_rating": float(best.rating or 0.0),
                "driver_total_trips": int(best.total_trips or 0),
                "ride_is_emergency": bool(getattr(ride, "is_emergency", False)),
                "current_load_for_driver": driver_load.get(best.id, 0),
                "sla_aware_priority": str(getattr(ride, "priority_tag", "normal") or "normal"),
            }

            recommendation_type = "emergency_priority_assignment" if bool(getattr(ride, "is_emergency", False)) else "assignment_recommendation"
            explainability = [
                f"Driver status considered: {best.status}.",
                f"Driver rating contributed to confidence: {float(best.rating or 0.0):.2f}.",
                f"Current modeled driver load: {driver_load.get(best.id, 0)} active recommendations.",
                "This is recommendation-only output and requires approval before execution.",
            ]
            if recommendation_type == "emergency_priority_assignment":
                explainability.append("Emergency ride priority increased ranking weight.")

            recommendations.append(
                DispatchRecommendation(
                    recommendation_id=str(uuid4()),
                    organization_id=organization_id,
                    ride_id=ride.id,
                    recommendation_type=recommendation_type,
                    target_id=best.id,
                    confidence=round(confidence, 4),
                    explainability=explainability,
                    evidence=evidence,
                    approval_required=True,
                    execution_mode="recommendation_only",
                )
            )

        return recommendations
