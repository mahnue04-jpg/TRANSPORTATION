"""Trend analysis helpers built from real operational data."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.models import DispatchEventRetry, HealthISFRide, RideStatus


class TrendAnalysis:
    @staticmethod
    def compute_trends(db: Session, *, organization_id: str) -> dict[str, Any]:
        now_dt = now()
        one_hour = now_dt - timedelta(hours=1)
        six_hours = now_dt - timedelta(hours=6)

        rides_1h = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .filter(HealthISFRide.created_at >= one_hour)
            .all()
        )
        rides_6h = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == organization_id)
            .filter(HealthISFRide.created_at >= six_hours)
            .all()
        )

        pending_1h = sum(1 for row in rides_1h if str(row.status) == RideStatus.PENDING.value)
        pending_6h = sum(1 for row in rides_6h if str(row.status) == RideStatus.PENDING.value)
        emergency_1h = sum(1 for row in rides_1h if bool(getattr(row, "is_emergency", False)))

        retry_rows_1h = (
            db.query(DispatchEventRetry)
            .filter(DispatchEventRetry.organization_id == organization_id)
            .filter(DispatchEventRetry.created_at >= one_hour)
            .all()
        )
        retry_rows_6h = (
            db.query(DispatchEventRetry)
            .filter(DispatchEventRetry.organization_id == organization_id)
            .filter(DispatchEventRetry.created_at >= six_hours)
            .all()
        )

        avg_hourly_rides = (len(rides_6h) / 6.0) if rides_6h else 0.0
        avg_hourly_pending = (pending_6h / 6.0) if pending_6h else 0.0
        avg_hourly_retries = (len(retry_rows_6h) / 6.0) if retry_rows_6h else 0.0

        return {
            "rides_last_1h": float(len(rides_1h)),
            "rides_avg_hour_6h": float(avg_hourly_rides),
            "pending_last_1h": float(pending_1h),
            "pending_avg_hour_6h": float(avg_hourly_pending),
            "emergency_last_1h": float(emergency_1h),
            "retry_last_1h": float(len(retry_rows_1h)),
            "retry_avg_hour_6h": float(avg_hourly_retries),
            "retry_failed_last_1h": float(sum(1 for row in retry_rows_1h if int(row.attempts or 0) > 0)),
        }
