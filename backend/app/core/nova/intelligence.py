"""
Nova Operational Intelligence Engine

Structured internal orchestration for:
- deployment readiness scoring
- operational health scoring
- workflow bottleneck detection
- stale ride detection
- overloaded driver detection
- provider imbalance detection
- recommended next operational actions

No external AI services used. All reasoning is deterministic and data-driven.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.health_isf.models import (
    DriverStatus,
    HealthISFDriver,
    HealthISFProvider,
    HealthISFRide,
    RideStatus,
)
from app.modules.health_isf.realtime_service import RetryQueueService
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService

logger = logging.getLogger("amicor.nova.intelligence")

# ─── Thresholds ─────────────────────────────────────────────────────────────

_STALE_RIDE_MINUTES = 60          # ride in_transit/accepted with no update
_OVERLOADED_DRIVER_RIDES = 3      # rides assigned to one driver simultaneously
_PROVIDER_IMBALANCE_RATIO = 2.5   # one provider has 2.5× the average load
_BOTTLENECK_PENDING_RATIO = 0.45  # pending rides > 45% of total → bottleneck
_DEPLOYMENT_CHECK_ITEMS = [
    "DATABASE_URL",
    "SECRET_KEY",
    "JWT_SECRET",
    "ALLOWED_ORIGINS",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _safe_avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


# ─── Engine ──────────────────────────────────────────────────────────────────

class NovaIntelligenceEngine:
    """Pure structured intelligence reasoning over operational data."""

    # ── Deployment Readiness ─────────────────────────────────────────────────

    @classmethod
    def score_deployment_readiness(
        cls,
        db: Session,
        organization_id: str,
    ) -> dict[str, Any]:
        """
        Produce a 0–100 deployment readiness score with labeled criteria.
        Criteria: env vars present, DB accessible, dispatch stable, test coverage signals,
        auth seeded, queue healthy.
        """
        import os
        criteria: list[dict[str, Any]] = []

        # 1. Required environment variables
        missing_env = [v for v in _DEPLOYMENT_CHECK_ITEMS if not os.environ.get(v)]
        criteria.append({
            "name": "environment_variables",
            "passed": len(missing_env) == 0,
            "detail": f"Missing: {missing_env}" if missing_env else "All required env vars present",
            "weight": 20,
        })

        # 2. Database accessible
        try:
            from app.db.session import check_db_connection
            db_ok = check_db_connection()
        except Exception:
            db_ok = False
        criteria.append({
            "name": "database_connectivity",
            "passed": db_ok,
            "detail": "Database connection verified" if db_ok else "Database unreachable",
            "weight": 25,
        })

        # 3. Dispatch queue health
        try:
            queue_stats = RetryQueueService.get_queue_stats(db, organization_id=organization_id)
            dead_letter = queue_stats.get("dead_letter", 0)
            queue_ok = dead_letter < 10
        except Exception:
            queue_ok = False
            dead_letter = -1
        criteria.append({
            "name": "dispatch_queue_health",
            "passed": queue_ok,
            "detail": f"Dead-letter queue size: {dead_letter}" if not queue_ok else "Queue healthy",
            "weight": 15,
        })

        # 4. No critical stale rides
        stale = cls.detect_stale_rides(db, organization_id)
        criteria.append({
            "name": "stale_ride_free",
            "passed": len(stale) == 0,
            "detail": f"{len(stale)} stale rides detected" if stale else "No stale rides",
            "weight": 15,
        })

        # 5. Drivers available (at least one coverage signal)
        available_drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id,
            HealthISFDriver.status == DriverStatus.AVAILABLE,
        ).count()
        criteria.append({
            "name": "driver_coverage",
            "passed": available_drivers >= 1,
            "detail": f"{available_drivers} available drivers" if available_drivers else "No available drivers",
            "weight": 10,
        })

        # 6. WebSocket service reachable
        try:
            ws_stats = get_broadcaster().get_websocket_health_stats(organization_id=organization_id)
            ws_ok = isinstance(ws_stats, dict)
        except Exception:
            ws_ok = False
        criteria.append({
            "name": "websocket_service",
            "passed": ws_ok,
            "detail": "WebSocket service healthy" if ws_ok else "WebSocket service unreachable",
            "weight": 15,
        })

        # ── Score ───────────────────────────────────────────────────────────
        max_score = sum(c["weight"] for c in criteria)
        achieved = sum(c["weight"] for c in criteria if c["passed"])
        score = round((achieved / max_score) * 100) if max_score > 0 else 0
        label = (
            "production_ready" if score >= 85 else
            "staging_ready" if score >= 65 else
            "development_only" if score >= 40 else
            "not_ready"
        )

        blockers = [c["name"] for c in criteria if not c["passed"] and c["weight"] >= 20]

        return {
            "score": score,
            "label": label,
            "criteria": criteria,
            "blockers": blockers,
            "recommendation": cls._deployment_recommendation(score, blockers),
        }

    @classmethod
    def _deployment_recommendation(cls, score: int, blockers: list[str]) -> str:
        if score >= 85:
            return "System meets production deployment thresholds. Proceed with staged rollout."
        if "database_connectivity" in blockers:
            return "Database connectivity failure is a hard blocker. Resolve before any deployment."
        if "environment_variables" in blockers:
            return "Set all required environment variables in your deployment target."
        if score >= 65:
            return "System is staging-ready. Resolve remaining criteria before production launch."
        return "Multiple deployment blockers present. Run readiness checks and fix all failing criteria."

    # ── Operational Health Scoring ───────────────────────────────────────────

    @classmethod
    def score_operational_health(
        cls,
        db: Session,
        organization_id: str,
    ) -> dict[str, Any]:
        """
        Produce a 0–100 operational health score with labelled indicators.
        Dimensions: pending ratio, stale rides, driver availability, queue health.
        """
        indicators: list[dict[str, Any]] = []
        now_dt = _utc_now()

        rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id
        ).all()
        total_rides = len(rides)
        pending = sum(1 for r in rides if r.status == RideStatus.PENDING)
        in_transit = sum(1 for r in rides if r.status == RideStatus.IN_TRANSIT)

        # 1. Pending ratio
        pending_ratio = (pending / total_rides) if total_rides else 0.0
        indicators.append({
            "name": "pending_queue_ratio",
            "value": round(pending_ratio, 3),
            "healthy": pending_ratio <= _BOTTLENECK_PENDING_RATIO,
            "detail": f"{pending}/{total_rides} rides pending",
        })

        # 2. Stale rides
        stale_count = len(cls.detect_stale_rides(db, organization_id))
        indicators.append({
            "name": "stale_rides",
            "value": stale_count,
            "healthy": stale_count == 0,
            "detail": f"{stale_count} rides with no status update >60 minutes",
        })

        # 3. Driver availability ratio
        drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id
        ).all()
        total_drivers = len(drivers)
        available = sum(1 for d in drivers if d.status == DriverStatus.AVAILABLE)
        avail_ratio = (available / total_drivers) if total_drivers else 0.0
        indicators.append({
            "name": "driver_availability",
            "value": round(avail_ratio, 3),
            "healthy": avail_ratio >= 0.2 or total_drivers == 0,
            "detail": f"{available}/{total_drivers} drivers available",
        })

        # 4. Overloaded drivers
        overloaded = cls.detect_overloaded_drivers(db, organization_id)
        indicators.append({
            "name": "overloaded_drivers",
            "value": len(overloaded),
            "healthy": len(overloaded) == 0,
            "detail": f"{len(overloaded)} overloaded driver(s)" if overloaded else "No overloaded drivers",
        })

        # 5. Provider imbalance
        imbalance = cls.detect_provider_imbalance(db, organization_id)
        indicators.append({
            "name": "provider_imbalance",
            "value": len(imbalance),
            "healthy": len(imbalance) == 0,
            "detail": f"{len(imbalance)} provider(s) with imbalanced load" if imbalance else "Provider load balanced",
        })

        # ── Score ────────────────────────────────────────────────────────────
        healthy_count = sum(1 for i in indicators if i["healthy"])
        score = round((healthy_count / len(indicators)) * 100) if indicators else 100
        label = (
            "excellent" if score >= 90 else
            "good" if score >= 70 else
            "fair" if score >= 50 else
            "poor"
        )

        return {
            "score": score,
            "label": label,
            "indicators": indicators,
        }

    # ── Bottleneck Detection ─────────────────────────────────────────────────

    @classmethod
    def detect_workflow_bottlenecks(
        cls,
        db: Session,
        organization_id: str,
    ) -> list[dict[str, Any]]:
        """Detect workflow bottlenecks from operational data."""
        bottlenecks: list[dict[str, Any]] = []
        now_dt = _utc_now()

        # Pending rides with no driver assigned for >30 minutes
        unassigned_cutoff = now_dt - timedelta(minutes=30)
        long_pending = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status == RideStatus.PENDING,
            HealthISFRide.driver_id.is_(None),
            HealthISFRide.requested_at < unassigned_cutoff,
        ).all()

        if long_pending:
            oldest = min(
                (r for r in long_pending if r.requested_at),
                key=lambda r: r.requested_at,
                default=None,
            )
            wait_minutes = (
                int((now_dt - oldest.requested_at).total_seconds() / 60)
                if oldest and oldest.requested_at
                else "?"
            )
            bottlenecks.append({
                "type": "unassigned_pending_queue",
                "severity": "high" if len(long_pending) >= 5 else "medium",
                "count": len(long_pending),
                "detail": f"{len(long_pending)} rides unassigned >30 min; oldest wait ~{wait_minutes} min",
                "action": "Triage pending queue and manually assign available drivers.",
            })

        # All available drivers busy → assignment bottleneck
        drivers = db.query(HealthISFDriver).filter(
            HealthISFDriver.organization_id == organization_id
        ).all()
        available_count = sum(1 for d in drivers if d.status == DriverStatus.AVAILABLE)
        if drivers and available_count == 0:
            bottlenecks.append({
                "type": "no_available_drivers",
                "severity": "high",
                "count": 0,
                "detail": "All drivers are currently busy or inactive.",
                "action": "Contact off-duty drivers or escalate to on-call coverage.",
            })

        # Open workflow incidents > threshold
        try:
            workflows = WorkflowOrchestrationService.list_workflows(
                db, organization_id=organization_id, limit=200
            )
            open_wf = [
                w for w in workflows
                if str(w.get("status", "")).lower() not in {"completed", "resolved"}
            ]
            if len(open_wf) >= 8:
                bottlenecks.append({
                    "type": "workflow_incident_backlog",
                    "severity": "medium",
                    "count": len(open_wf),
                    "detail": f"{len(open_wf)} open workflow incidents accumulating.",
                    "action": "Review and close resolved workflows; escalate blocked ones.",
                })
        except Exception:
            pass

        return bottlenecks

    # ── Stale Ride Detection ─────────────────────────────────────────────────

    @classmethod
    def detect_stale_rides(
        cls,
        db: Session,
        organization_id: str,
        minutes: int = _STALE_RIDE_MINUTES,
    ) -> list[dict[str, Any]]:
        """Return rides in active status with no update for >minutes."""
        cutoff = _utc_now() - timedelta(minutes=minutes)
        stale_rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
            HealthISFRide.updated_at < cutoff,
        ).all()

        result = []
        for ride in stale_rides:
            age_minutes = (
                int((_utc_now() - ride.updated_at).total_seconds() / 60)
                if ride.updated_at
                else "?"
            )
            result.append({
                "ride_id": ride.id,
                "status": str(ride.status),
                "driver_id": ride.driver_id,
                "age_minutes": age_minutes,
                "last_updated": ride.updated_at.isoformat() if ride.updated_at else None,
                "action": "Verify driver status; escalate if driver unreachable.",
            })
        return result

    # ── Overloaded Driver Detection ──────────────────────────────────────────

    @classmethod
    def detect_overloaded_drivers(
        cls,
        db: Session,
        organization_id: str,
    ) -> list[dict[str, Any]]:
        """Return drivers with more than threshold simultaneous active ride assignments."""
        active_rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
            HealthISFRide.driver_id.isnot(None),
        ).all()

        driver_ride_counts: Counter = Counter(
            ride.driver_id for ride in active_rides if ride.driver_id
        )

        overloaded = []
        for driver_id, count in driver_ride_counts.items():
            if count >= _OVERLOADED_DRIVER_RIDES:
                driver = db.query(HealthISFDriver).filter(
                    HealthISFDriver.id == driver_id
                ).first()
                overloaded.append({
                    "driver_id": driver_id,
                    "driver_name": driver.name if driver else "Unknown",
                    "active_ride_count": count,
                    "action": "Reassign one or more rides to an available driver.",
                })
        return overloaded

    # ── Provider Imbalance Detection ─────────────────────────────────────────

    @classmethod
    def detect_provider_imbalance(
        cls,
        db: Session,
        organization_id: str,
    ) -> list[dict[str, Any]]:
        """
        Return providers whose active ride load is significantly above average.
        Flags providers with load ≥ 2.5× the per-provider average.
        """
        active_rides = db.query(HealthISFRide).filter(
            HealthISFRide.organization_id == organization_id,
            HealthISFRide.status.in_([RideStatus.PENDING, RideStatus.ACCEPTED, RideStatus.IN_TRANSIT]),
        ).all()

        if not active_rides:
            return []

        provider_counts: Counter = Counter(
            ride.provider_id for ride in active_rides if ride.provider_id
        )
        if not provider_counts:
            return []

        avg_load = _safe_avg(list(provider_counts.values()))
        threshold = avg_load * _PROVIDER_IMBALANCE_RATIO

        imbalanced = []
        for provider_id, count in provider_counts.items():
            if count >= threshold and count > 1:
                provider = db.query(HealthISFProvider).filter(
                    HealthISFProvider.id == provider_id
                ).first()
                imbalanced.append({
                    "provider_id": provider_id,
                    "provider_name": provider.name if provider else "Unknown",
                    "active_rides": count,
                    "average_load": round(avg_load, 2),
                    "ratio": round(count / avg_load, 2) if avg_load else None,
                    "action": "Review ride scheduling to balance load across providers.",
                })
        return imbalanced

    # ── Recommended Next Actions ─────────────────────────────────────────────

    @classmethod
    def build_recommended_actions(
        cls,
        db: Session,
        organization_id: str,
    ) -> list[dict[str, Any]]:
        """
        Produce a priority-ranked list of next operational actions based on live state.
        Returns at most 8 items, ordered by priority descending.
        """
        actions: list[dict[str, Any]] = []

        stale = cls.detect_stale_rides(db, organization_id)
        if stale:
            actions.append({
                "priority": 90,
                "category": "stale_rides",
                "action": f"Resolve {len(stale)} stale active ride(s) — verify driver status.",
                "urgency": "high",
            })

        bottlenecks = cls.detect_workflow_bottlenecks(db, organization_id)
        for b in bottlenecks:
            actions.append({
                "priority": 80 if b["severity"] == "high" else 60,
                "category": b["type"],
                "action": b["action"],
                "urgency": b["severity"],
            })

        overloaded = cls.detect_overloaded_drivers(db, organization_id)
        if overloaded:
            actions.append({
                "priority": 70,
                "category": "overloaded_drivers",
                "action": f"Rebalance workload for {len(overloaded)} overloaded driver(s).",
                "urgency": "medium",
            })

        imbalance = cls.detect_provider_imbalance(db, organization_id)
        if imbalance:
            actions.append({
                "priority": 50,
                "category": "provider_imbalance",
                "action": f"Redistribute ride load from {len(imbalance)} overloaded provider(s).",
                "urgency": "medium",
            })

        # Default action if nothing flagged
        if not actions:
            actions.append({
                "priority": 10,
                "category": "routine_monitoring",
                "action": "Operations nominal. Continue standard dispatch monitoring.",
                "urgency": "low",
            })

        return sorted(actions, key=lambda a: a["priority"], reverse=True)[:8]

    # ── Full Intelligence Report ──────────────────────────────────────────────

    @classmethod
    def full_intelligence_report(
        cls,
        db: Session,
        organization_id: str,
    ) -> dict[str, Any]:
        """
        Produce a unified intelligence report combining all scoring dimensions.
        Safe to call from request paths — does NOT call validate_query_optimization.
        """
        deployment = cls.score_deployment_readiness(db, organization_id)
        health = cls.score_operational_health(db, organization_id)
        bottlenecks = cls.detect_workflow_bottlenecks(db, organization_id)
        stale = cls.detect_stale_rides(db, organization_id)
        overloaded = cls.detect_overloaded_drivers(db, organization_id)
        imbalance = cls.detect_provider_imbalance(db, organization_id)
        actions = cls.build_recommended_actions(db, organization_id)

        composite = round(
            (deployment["score"] * 0.4 + health["score"] * 0.6), 1
        )
        composite_label = (
            "enterprise_ready" if composite >= 80 else
            "alpha_ready" if composite >= 60 else
            "pre_alpha" if composite >= 40 else
            "not_ready"
        )

        logger.info(
            "nova.intelligence.report org=%s composite=%.1f deploy=%d health=%d",
            organization_id, composite, deployment["score"], health["score"],
        )

        return {
            "organization_id": organization_id,
            "generated_at": now().isoformat(),
            "composite_score": composite,
            "composite_label": composite_label,
            "deployment_readiness": deployment,
            "operational_health": health,
            "workflow_bottlenecks": bottlenecks,
            "stale_rides": stale,
            "overloaded_drivers": overloaded,
            "provider_imbalance": imbalance,
            "recommended_actions": actions,
            "summary": cls._compose_summary(composite, bottlenecks, stale, overloaded),
        }

    @classmethod
    def _compose_summary(
        cls,
        composite: float,
        bottlenecks: list,
        stale: list,
        overloaded: list,
    ) -> str:
        parts = []
        if stale:
            parts.append(f"{len(stale)} stale ride(s) requiring attention")
        if bottlenecks:
            severe = [b for b in bottlenecks if b.get("severity") == "high"]
            if severe:
                parts.append(f"{len(severe)} high-severity bottleneck(s) detected")
        if overloaded:
            parts.append(f"{len(overloaded)} overloaded driver(s)")
        if not parts:
            return f"Operations are stable with composite readiness score of {composite}."
        return (
            f"Composite readiness {composite}/100. Issues: {'; '.join(parts)}. "
            "Immediate dispatch triage is recommended."
        )
