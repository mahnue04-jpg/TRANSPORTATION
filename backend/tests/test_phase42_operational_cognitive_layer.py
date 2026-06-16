from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf.operational_cognition_engine import OperationalCognitionEngine


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.organization_id)


def _high_pressure_context() -> dict:
    return {
        "organization_id": "org-phase42",
        "metrics": {
            "active_rides": 28,
            "unassigned_rides": 19,
            "available_drivers": 2,
            "active_drivers": 1,
            "active_providers": 1,
            "websocket": {"disconnects_last_5m": 9},
        },
        "geospatial_snapshot": {
            "live_operational_map_state": {
                "incident_clustering": [1, 2, 3, 4],
                "emergency_overlays": [1, 2],
                "operational_density_regions": [1, 2, 3, 4, 5],
            }
        },
        "sync_snapshot": {"event_bus": {"latest_sequence": 940, "total_events": 280}},
        "dispatch_snapshot": {
            "summary": {
                "total": 42,
                "emergency_recommendations": 8,
                "overloaded": True,
                "safe_capacity": 3,
                "queued": 34,
                "escalated": 6,
            },
            "queue": [],
            "overload": {"queued": 34, "available_drivers": 2, "safe_capacity": 3, "escalated": 6, "overloaded": True},
        },
        "memory_snapshot": {
            "pattern_summary": {"incident_growth_ratio": 1.9, "stability_profile": "degraded"},
            "recall_summary": {"recent_event_types": ["incident", "execution", "prediction"]},
        },
        "history_features": {
            "incidents_60m": 14.0,
            "incidents_360m": 32.0,
            "executions_60m": 19.0,
            "predictions_60m": 8.0,
            "baseline_incidents_per_hour": 5.3,
            "incident_growth_ratio": 1.9,
        },
        "decision_snapshot": {
            "recommendations": [
                {
                    "recommendation_id": "dec-1",
                    "recommendation_type": "workload_balance",
                    "confidence": 0.78,
                    "priority_score": 0.91,
                    "operational_impact": "Redistribute workload across lower pressure runtimes.",
                },
                {
                    "recommendation_id": "dec-2",
                    "recommendation_type": "continuity_risk_warning",
                    "confidence": 0.74,
                    "priority_score": 0.88,
                    "operational_impact": "Restore checkpointed state before resuming execution.",
                },
            ],
            "forecast": {"continuity_risk_forecast": 0.82, "dispatch_bottleneck_forecast": 0.84},
            "pressure_analysis": {"continuity_degradation_risk": 0.83},
        },
        "adaptive_forecast_snapshot": {
            "dispatch_bottleneck_forecast": {"value": 0.87},
            "continuity_degradation_forecast": {"value": 0.9},
            "operational_resilience_scoring": {"confidence": 0.61},
        },
        "coordination_snapshot": {
            "recommendations": [
                {
                    "recommendation_id": "coord-1",
                    "recommendation_type": "selective_rebalance",
                    "confidence": 0.72,
                    "priority_score": 0.87,
                    "operational_impact": "Balance active chains across lower pressure workers.",
                }
            ],
            "coordination_summary": {"workload_summary": {"provider_driver_balance": 0.78, "operational_distribution": 0.81}},
        },
        "runtime_governor_snapshot": {
            "checkpoint_restore_count": 2,
            "interrupted_execution_recovery_count": 4,
            "stuck_executions_detected": 3,
            "active_execution_chains": 5,
            "queued_task_count": 12,
        },
        "workflow_coordination": {
            "active_workflow_count": 5,
            "queued_task_count": 12,
            "retry_attempts": 4,
        },
        "distributed_governance": {
            "active_runtimes": 2,
            "distributed_queue_depth": 12,
            "task_reassignment_count": 3,
            "runtime_failover_count": 2,
            "isolation_violation_count": 0,
            "workload_pressure": {"score": 0.88, "warnings": ["queue_pressure"], "priority_distribution": {"critical": 5}},
            "recovery_failover_ratios": {"completion_ratio": 0.41, "failure_ratio": 0.59},
        },
        "websocket_health": {"disconnects_last_5m": 9, "reconnects_last_5m": 2},
    }


def _low_pressure_context() -> dict:
    return {
        "organization_id": "org-phase42-low",
        "metrics": {
            "active_rides": 3,
            "unassigned_rides": 1,
            "available_drivers": 12,
            "active_drivers": 8,
            "active_providers": 4,
            "websocket": {"disconnects_last_5m": 0},
        },
        "geospatial_snapshot": {
            "live_operational_map_state": {
                "incident_clustering": [],
                "emergency_overlays": [],
                "operational_density_regions": [1],
            }
        },
        "sync_snapshot": {"event_bus": {"latest_sequence": 50, "total_events": 12}},
        "dispatch_snapshot": {
            "summary": {
                "total": 4,
                "emergency_recommendations": 0,
                "overloaded": False,
                "safe_capacity": 36,
                "queued": 1,
                "escalated": 0,
            },
            "queue": [],
            "overload": {"queued": 1, "available_drivers": 12, "safe_capacity": 36, "escalated": 0, "overloaded": False},
        },
        "memory_snapshot": {
            "pattern_summary": {"incident_growth_ratio": 0.4, "stability_profile": "steady"},
            "recall_summary": {"recent_event_types": ["status"]},
        },
        "history_features": {
            "incidents_60m": 1.0,
            "incidents_360m": 5.0,
            "executions_60m": 4.0,
            "predictions_60m": 1.0,
            "baseline_incidents_per_hour": 0.8,
            "incident_growth_ratio": 0.4,
        },
        "decision_snapshot": {
            "recommendations": [
                {
                    "recommendation_id": "dec-low-1",
                    "recommendation_type": "resource_pressure_watch",
                    "confidence": 0.83,
                    "priority_score": 0.42,
                    "operational_impact": "Monitor and continue supervised execution.",
                }
            ],
            "forecast": {"continuity_risk_forecast": 0.16, "dispatch_bottleneck_forecast": 0.11},
            "pressure_analysis": {"continuity_degradation_risk": 0.08},
        },
        "adaptive_forecast_snapshot": {
            "dispatch_bottleneck_forecast": {"value": 0.11},
            "continuity_degradation_forecast": {"value": 0.12},
            "operational_resilience_scoring": {"confidence": 0.89},
        },
        "coordination_snapshot": {
            "recommendations": [
                {
                    "recommendation_id": "coord-low-1",
                    "recommendation_type": "steady_coordination",
                    "confidence": 0.81,
                    "priority_score": 0.38,
                    "operational_impact": "No redistribution needed.",
                }
            ],
            "coordination_summary": {"workload_summary": {"provider_driver_balance": 0.21, "operational_distribution": 0.18}},
        },
        "runtime_governor_snapshot": {
            "checkpoint_restore_count": 0,
            "interrupted_execution_recovery_count": 0,
            "stuck_executions_detected": 0,
            "active_execution_chains": 2,
            "queued_task_count": 1,
        },
        "workflow_coordination": {
            "active_workflow_count": 2,
            "queued_task_count": 1,
            "retry_attempts": 0,
        },
        "distributed_governance": {
            "active_runtimes": 3,
            "distributed_queue_depth": 1,
            "task_reassignment_count": 0,
            "runtime_failover_count": 0,
            "isolation_violation_count": 0,
            "workload_pressure": {"score": 0.1, "warnings": [], "priority_distribution": {"normal": 1}},
            "recovery_failover_ratios": {"completion_ratio": 1.0, "failure_ratio": 0.0},
        },
        "websocket_health": {"disconnects_last_5m": 0, "reconnects_last_5m": 0},
    }


def test_phase42_cognitive_overload_and_adaptive_mitigation() -> None:
    context = _high_pressure_context()
    snapshot = OperationalCognitionEngine.build_from_context(**context)
    repeated_snapshot = OperationalCognitionEngine.build_from_context(**context)

    assert snapshot["runtime_stability_score"] < 0.55
    assert snapshot["execution_risk_level"] in {"high", "critical"}
    assert snapshot["adaptive_execution_strategies"]["retry_strategy"] in {"bounded_exponential", "adaptive_exponential"}
    assert snapshot["adaptive_execution_strategies"]["queue_prioritization"] == "critical_first"
    assert snapshot["adaptive_execution_strategies"]["runtime_congestion_mitigation"] != "normal"
    assert snapshot["diagnostics_intelligence_layer"]["bottleneck_likelihood"] >= 0.6
    assert snapshot["supervised_orchestration_reasoning"]["workflow_anomaly_detection"]
    assert snapshot["operational_recommendation_summaries"] == repeated_snapshot["operational_recommendation_summaries"]
    assert snapshot["runtime_stability_score"] == repeated_snapshot["runtime_stability_score"]


def test_phase42_safe_recovery_recommendation_and_false_positive_suppression() -> None:
    context = _low_pressure_context()
    snapshot = OperationalCognitionEngine.build_from_context(**context)
    repeated_snapshot = OperationalCognitionEngine.build_from_context(**context)

    assert snapshot["runtime_stability_score"] > 0.7
    assert snapshot["execution_risk_level"] == "low"
    assert snapshot["cognitive_recovery_planning"]["safe_replay_recommendation"] is False
    assert snapshot["cognitive_recovery_planning"]["checkpoint_restoration_strategy"] in {
        "latest_safe_checkpoint",
        "lease_snapshot_then_rollback",
    }
    assert snapshot["supervised_orchestration_reasoning"]["workflow_anomaly_detection"] == []
    assert snapshot["runtime_cognition"]["orchestration_stability_assessment"] == "stable"
    assert snapshot["operational_memory_intelligence"]["runtime_drift_detection"]["detected"] is False
    assert snapshot["runtime_stability_score"] == repeated_snapshot["runtime_stability_score"]


def test_phase42_cognitive_diagnostics_endpoint_and_websocket_contract() -> None:
    ensure_auth_schema()
    seed_default_users()
    client = TestClient(app)

    auth = _login(client, "dispatcher@amicor.local")
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    org_id = _org_id("dispatcher@amicor.local")

    response = client.get(
        f"/api/health-isf/ops/cognitive-diagnostics?organization_id={org_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["organization_id"] == org_id
    assert "runtime_stability_score" in payload
    assert "diagnostics_intelligence_layer" in payload
    assert payload["cognition_governance"]["supervised"] is True

    ws_url = (
        f"/api/health-isf/ws/live/{org_id}/{auth['user_id']}"
        f"?role=dispatcher&token={auth['access_token']}"
    )

    with client.websocket_connect(ws_url) as websocket:
        connected = websocket.receive_json()
        assert connected["type"] == "connected"
        assert "cognitive_diagnostics" in connected
        assert "workflow_coordination" in connected
        assert "distributed_governance" in connected
        assert "runtime_stability_score" in connected["cognitive_diagnostics"]
