"""Validation tests for operational decision intelligence phase."""

from __future__ import annotations

from app.modules.health_isf.operational_decision_engine import OperationalDecisionEngine
from app.modules.health_isf.operational_forecast_service import OperationalForecastService
from app.modules.health_isf.operational_priority_service import OperationalPriorityService
from app.modules.health_isf.operational_recommendation_pipeline import OperationalRecommendationPipeline


def _metrics() -> dict[str, float | int | dict[str, int]]:
    return {
        "active_rides": 18,
        "unassigned_rides": 6,
        "available_drivers": 7,
        "active_drivers": 8,
        "active_providers": 4,
        "websocket": {
            "disconnects_last_5m": 2,
        },
    }


def _geospatial() -> dict[str, object]:
    return {
        "live_operational_map_state": {
            "driver_positioning": [{"driver_id": "d1"}],
            "incident_clustering": [{"cluster_id": "c1"}, {"cluster_id": "c2"}],
            "emergency_overlays": [{"incident_id": "i1"}],
            "operational_density_regions": [{"region": "north"}, {"region": "south"}],
        }
    }


def _dispatch() -> dict[str, object]:
    return {
        "summary": {
            "total": 10,
            "emergency_recommendations": 3,
        }
    }


def _sync() -> dict[str, object]:
    return {
        "event_bus": {
            "organization_id": "org-decision",
            "total_events": 42,
            "latest_sequence": 42,
            "tenant_scoped": True,
            "ordered": True,
            "replay_safe": True,
        },
        "ordered_operational_event_sequencing": True,
        "reconnect_safe_replay_handling": True,
    }


def test_operational_pressure_and_forecast_are_tenant_scoped_and_replay_safe():
    pressure = OperationalPriorityService.build_pressure_snapshot(
        metrics=_metrics(),
        geospatial_snapshot=_geospatial(),
        sync_snapshot=_sync(),
    )
    forecast = OperationalForecastService.build_forecast(pressure=pressure, sync_snapshot=_sync())

    assert 0.0 <= pressure.regional_congestion <= 1.0
    assert 0.0 <= pressure.driver_load_pressure <= 1.0
    assert forecast["tenant_scoped"] is True
    assert forecast["replay_safe"] is True
    assert forecast["recommendation_only"] is True


def test_operational_recommendations_are_explainable_and_ranked():
    pressure = OperationalPriorityService.build_pressure_snapshot(
        metrics=_metrics(),
        geospatial_snapshot=_geospatial(),
        sync_snapshot=_sync(),
    )
    forecast = OperationalForecastService.build_forecast(pressure=pressure, sync_snapshot=_sync())

    recommendations = OperationalDecisionEngine.build_recommendations(
        organization_id="org-decision",
        pressure=pressure,
        forecast=forecast,
        dispatch_snapshot=_dispatch(),
    )

    assert len(recommendations) >= 4
    assert recommendations == sorted(recommendations, key=lambda item: item.priority_score, reverse=True)
    assert all(item.recommendation_only is True for item in recommendations)
    assert all(item.approval_required is True for item in recommendations)
    assert all(item.evidence_chain for item in recommendations)
    assert all(item.reasoning_chain for item in recommendations)


def test_pipeline_snapshot_preserves_backend_authority_and_governance():
    snapshot = OperationalRecommendationPipeline.build_snapshot(
        organization_id="org-decision",
        telemetry_metrics=_metrics(),
        geospatial_snapshot=_geospatial(),
        dispatch_snapshot=_dispatch(),
        sync_snapshot=_sync(),
    )

    assert snapshot["backend_authoritative"] is True
    assert snapshot["approval_governed"] is True
    assert snapshot["tenant_scoped"] is True
    assert snapshot["recommendation_only"] is True
    assert snapshot["summary"]["no_hidden_inference_paths"] is True
    assert snapshot["summary"]["confidence_scored"] is True
    assert snapshot["summary"]["total_recommendations"] >= 1
