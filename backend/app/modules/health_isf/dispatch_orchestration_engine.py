"""Dispatch orchestration helpers for live ride execution.

This module is additive and keeps existing mutation paths intact. It provides
priority queue ordering, overload evaluation, and best-driver selection for
dispatcher-assisted auto-assignment.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager


class DispatchOrchestrationEngine:
    """Operational dispatch orchestration without replacing existing systems."""

    _QUEUE_PRIORITIES: dict[str, int] = {
        RideStatus.ESCALATED.value: 0,
        RideStatus.REQUESTED.value: 1,
        RideStatus.QUEUED.value: 2,
        RideStatus.ASSIGNED.value: 3,
        RideStatus.DRIVER_EN_ROUTE.value: 4,
        RideStatus.ARRIVED.value: 5,
        RideStatus.RIDER_ONBOARD.value: 6,
        RideStatus.IN_PROGRESS.value: 7,
        RideStatus.FAILED.value: 8,
        RideStatus.CANCELLED.value: 9,
        RideStatus.COMPLETED.value: 10,
    }

    @classmethod
    def _active_ride_counts(cls, db: Session, organization_id: str) -> dict[str, int]:
        rows = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.driver_id.is_not(None),
        ).all()
        counts: dict[str, int] = defaultdict(int)
        for ride in rows:
            state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            if state in {
                RideStatus.ASSIGNED.value,
                RideStatus.DRIVER_EN_ROUTE.value,
                RideStatus.ARRIVED.value,
                RideStatus.RIDER_ONBOARD.value,
                RideStatus.IN_PROGRESS.value,
                RideStatus.ESCALATED.value,
            }:
                if ride.driver_id:
                    counts[str(ride.driver_id)] += 1
        return counts

    @classmethod
    def evaluate_overload(cls, db: Session, organization_id: str) -> dict[str, Any]:
        rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id).all()
        queued = 0
        escalated = 0
        for ride in rides:
            state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            if state in {RideStatus.REQUESTED.value, RideStatus.QUEUED.value}:
                queued += 1
            elif state == RideStatus.ESCALATED.value:
                escalated += 1

        available = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
            HealthISFDriver.is_active == True,
        ).count()

        safe_capacity = max(available, 1) * 3
        overloaded = queued > safe_capacity

        return {
            "queued": queued,
            "available_drivers": available,
            "safe_capacity": safe_capacity,
            "escalated": escalated,
            "overloaded": overloaded,
        }

    @classmethod
    def suggest_provider(cls, db: Session, organization_id: str) -> str | None:
        providers = db.query(HealthISFProvider).filter(
            HealthISFProvider.organization_id == organization_id,
            HealthISFProvider.is_active == True,
        ).all()
        if not providers:
            return None

        workloads: dict[str, int] = defaultdict(int)
        rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.provider_id.is_not(None),
        ).all()
        for ride in rides:
            state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            if state in {
                RideStatus.REQUESTED.value,
                RideStatus.QUEUED.value,
                RideStatus.ASSIGNED.value,
                RideStatus.DRIVER_EN_ROUTE.value,
                RideStatus.ARRIVED.value,
                RideStatus.RIDER_ONBOARD.value,
                RideStatus.IN_PROGRESS.value,
                RideStatus.ESCALATED.value,
            } and ride.provider_id:
                workloads[str(ride.provider_id)] += 1

        best = sorted(
            providers,
            key=lambda provider: (workloads.get(str(provider.id), 0), str(provider.name).lower()),
        )[0]
        return str(best.id)

    @classmethod
    def select_best_driver(
        cls,
        db: Session,
        *,
        organization_id: str,
        ride: HealthISFRide,
        exclude_driver_ids: set[str] | None = None,
    ) -> HealthISFDriver | None:
        exclude = exclude_driver_ids or set()
        candidates = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.is_active == True,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        ).all()
        if not candidates:
            return None

        active_counts = cls._active_ride_counts(db, organization_id)

        def _score(driver: HealthISFDriver) -> tuple[Any, ...]:
            if str(driver.id) in exclude:
                # Excluded drivers are effectively deprioritized out.
                return (9999, 0.0, str(driver.updated_at), str(driver.id))
            score_bias = 0
            if ride.is_emergency and float(driver.rating or 0.0) >= 4.7:
                score_bias = -1
            return (
                active_counts.get(str(driver.id), 0),
                score_bias,
                -float(driver.rating or 0.0),
                str(driver.updated_at),
                str(driver.id),
            )

        ordered = sorted(candidates, key=_score)
        selected = ordered[0]
        if str(selected.id) in exclude:
            return None
        return selected

    @classmethod
    def prioritized_queue(cls, db: Session, organization_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
        ).all()

        queue_rows: list[dict[str, Any]] = []
        for ride in rides:
            state = RideLifecycleManager.normalize_state(ride.lifecycle_state or ride.status)
            queue_rows.append(
                {
                    "ride_id": str(ride.id),
                    "state": state,
                    "priority_tag": str(ride.priority_tag or "normal"),
                    "priority_score": float(ride.priority_score or 0.0),
                    "is_emergency": bool(ride.is_emergency),
                    "requested_at": ride.requested_at.isoformat() if ride.requested_at else None,
                    "driver_id": str(ride.driver_id) if ride.driver_id else None,
                    "provider_id": str(ride.provider_id) if ride.provider_id else None,
                }
            )

        queue_rows.sort(
            key=lambda row: (
                cls._QUEUE_PRIORITIES.get(str(row.get("state")), 99),
                -int(bool(row.get("is_emergency"))),
                -float(row.get("priority_score") or 0.0),
                str(row.get("requested_at") or ""),
            )
        )
        return queue_rows[: max(1, limit)]
