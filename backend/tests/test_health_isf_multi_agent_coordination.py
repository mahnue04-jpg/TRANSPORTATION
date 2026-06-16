"""Validation tests for supervised multi-agent operational coordination."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.helpers import uuid4
from app.modules.health_isf.coordination_recommendation_pipeline import CoordinationRecommendationPipeline
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.models import HealthISFOrganization
from app.modules.health_isf.operational_forecast_engine import OperationalForecastEngine
from app.modules.health_isf.operational_memory_engine import OperationalMemoryEngine
from app.modules.health_isf.operational_approval_engine import OperationalApprovalEngine
from app.modules.health_isf.operational_recommendation_pipeline import OperationalRecommendationPipeline


def _make_db():
    import app.db.models  # noqa: F401

    engine = create_engine("sqlite:///:memory:")
    testing = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    return testing()


def _seed_org(db):
    org = HealthISFOrganization(
        id=uuid4(),
        name="Coordination Org",
        code=f"COORD-{uuid4()[:8]}",
        is_active=True,
    )
    db.add(org)
    db.commit()
    return org


def _telemetry_metrics() -> dict[str, object]:
    return {
        "active_rides": 14,
        "unassigned_rides": 4,
        "available_drivers": 6,
        "active_drivers": 7,
        "active_providers": 3,
        "websocket": {"disconnects_last_5m": 1},
    }


def _geo() -> dict[str, object]:
    return {
        "live_operational_map_state": {
            "driver_positioning": [{"driver_id": "d1"}],
            "incident_clustering": [{"cluster": "a"}, {"cluster": "b"}],
            "emergency_overlays": [{"incident": "e1"}],
            "operational_density_regions": [{"region": "east"}],
        }
    }


def _dispatch() -> dict[str, object]:
    return {
        "summary": {
            "total": 7,
            "emergency_recommendations": 2,
        }
    }


def _sync() -> dict[str, object]:
    return {
        "event_bus": {
            "organization_id": "org",
            "total_events": 24,
            "latest_sequence": 24,
            "tenant_scoped": True,
            "ordered": True,
            "replay_safe": True,
        },
        "ordered_operational_event_sequencing": True,
        "reconnect_safe_replay_handling": True,
    }


def test_memory_fabric_is_auditable_and_tenant_scoped():
    db = _make_db()
    try:
        org = _seed_org(db)
        OperationalMemoryService.record_incident(
            db,
            organization_id=org.id,
            actor_user_id=None,
            incident={"incident_type": "load_spike", "severity": "high"},
            replay_hint="incident:1",
        )
        OperationalMemoryService.record_operation(
            db,
            organization_id=org.id,
            actor_user_id=None,
            operation={"operation_type": "provider_continuity_review", "status": "warning"},
            replay_hint="op:1",
        )
        snapshot = OperationalMemoryEngine.build_snapshot(db, organization_id=org.id, role="dispatcher")
        assert snapshot["backend_authoritative"] is True
        assert snapshot["tenant_scoped"] is True
        assert snapshot["auditable"] is True
        assert snapshot["explainable_memory_references"] is True
        assert snapshot["recall_summary"]["replay_safe_operational_recall"] is True
    finally:
        db.close()


def test_adaptive_forecast_and_coordination_remain_recommendation_only():
    decision = OperationalRecommendationPipeline.build_snapshot(
        organization_id="org-coord",
        telemetry_metrics=_telemetry_metrics(),
        geospatial_snapshot=_geo(),
        dispatch_snapshot=_dispatch(),
        sync_snapshot=_sync(),
    )
    memory = {
        "pattern_summary": {"incident_growth_ratio": 0.4, "total_memory_references": 6},
        "recall_summary": {"replay_safe_operational_recall": True},
    }
    adaptive = OperationalForecastEngine.build_snapshot(
        organization_id="org-coord",
        decision=decision,
        memory=memory,
        sync=_sync(),
    )
    coordination = CoordinationRecommendationPipeline.build_snapshot(
        organization_id="org-coord",
        metrics=_telemetry_metrics(),
        decision=decision,
        memory=memory,
        adaptive_forecast=adaptive,
        sync_snapshot=_sync(),
    )

    assert adaptive["recommendation_only"] is True
    assert adaptive["explainable"] is True
    assert adaptive["confidence_scored"] is True
    assert coordination["backend_authoritative"] is True
    assert coordination["recommendation_only"] is True
    assert coordination["replay_safe"] is True
    assert len(coordination["recommendations"]) >= 1
    assert all(item["reasoning_chain"] for item in coordination["recommendations"])


def test_human_oversight_snapshot_prevents_automatic_execution():
    db = _make_db()
    try:
        org = _seed_org(db)
        coordination = {
            "recommendations": [
                {
                    "recommendation_id": "coord-1",
                    "approval_required": True,
                    "confidence": 0.6,
                    "reasoning_chain": ["explainable"],
                }
            ]
        }
        decision = {
            "recommendations": [
                {
                    "reasoning_chain": ["decision chain"],
                }
            ]
        }
        snapshot = OperationalApprovalEngine.build_snapshot(
            db,
            organization_id=org.id,
            coordination=coordination,
            decision=decision,
        )
        assert snapshot["approval_governed"] is True
        assert snapshot["recommendation_only"] is True
        assert snapshot["no_automatic_execution"] is True
        assert snapshot["replay_safe"] is True
    finally:
        db.close()
