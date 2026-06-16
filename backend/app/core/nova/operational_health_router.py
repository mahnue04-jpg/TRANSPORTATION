"""
PHASE 7B: Operational Health Router
REST API endpoints for health checks, recovery, insights, UI hydration, stress tests, and executive intelligence.
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.health_check_engine import (
    health_check_engine,
    HealthCheckType,
)
from app.core.nova.memory_intelligence import memory_intelligence_fabric
from app.core.nova.runtime_recovery_engine import runtime_recovery_engine
from app.core.nova.operational_insights import operational_insights_engine
from app.core.nova.command_center_hydration import command_center_hydration
from app.core.nova.stress_test_validator import stress_test_validator
from app.core.nova.executive_intelligence import founder_intelligence_mode
from app.core.nova.router import _resolve_org


require_nova_health = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_ANALYTICS_READONLY,
)

router = APIRouter(
    prefix="/api/nova/health",
    tags=["nova-health"],
    dependencies=[Depends(require_nova_health)],
)


@router.get("/check/all")
async def run_all_health_checks(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Run all health checks"""
    try:
        org = _resolve_org(user, organization_id)
        report = await health_check_engine.run_all_checks(org)
        
        return {
            "organization_id": org,
            "timestamp": report.timestamp.isoformat(),
            "overall_status": report.overall_status.value,
            "total_checks": report.total_checks,
            "healthy_count": report.healthy_count,
            "degraded_count": report.degraded_count,
            "critical_count": report.critical_count,
            "checks": [
                {
                    "type": c.check_type.value,
                    "status": c.status.value,
                    "message": c.message,
                    "duration_ms": c.check_duration_ms,
                }
                for c in report.checks
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/check/{check_type}")
async def run_specific_health_check(
    check_type: str,
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Run specific health check"""
    try:
        org = _resolve_org(user, organization_id)
        
        # Convert check_type string to enum
        for ct in HealthCheckType:
            if ct.value == check_type:
                result = await health_check_engine.run_health_check(org, ct)
                return {
                    "organization_id": org,
                    "check_type": result.check_type.value,
                    "status": result.status.value,
                    "message": result.message,
                    "details": result.details,
                    "duration_ms": result.check_duration_ms,
                }
        
        raise HTTPException(status_code=400, detail="Invalid check type")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/diagnostics")
async def get_diagnostic_report(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get complete diagnostic report"""
    try:
        org = _resolve_org(user, organization_id)
        return health_check_engine.build_diagnostic_report(org)
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/runtime/diagnostics")
async def get_runtime_diagnostics(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Unified live runtime diagnostics for websocket, queue, execution, approval, replay, memory, latency, and hydration."""
    org = _resolve_org(user, organization_id)
    report = await health_check_engine.run_all_checks(org)

    checks_by_type = {item.check_type.value: item for item in report.checks}

    memory_check = checks_by_type.get("memory_persistence")
    queue_check = checks_by_type.get("event_queue_health")
    ws_check = checks_by_type.get("websocket_connectivity")
    approval_check = checks_by_type.get("approval_pipeline")
    execution_check = checks_by_type.get("execution_engine")
    replay_check = checks_by_type.get("duplicate_detection")
    hydration_check = checks_by_type.get("command_center_hydration")
    latency_check = checks_by_type.get("runtime_latency")
    metrics_check = checks_by_type.get("metrics_freshness")

    stability = await founder_intelligence_mode.calculate_system_readiness(org)

    def _pack_check(item: Any) -> Dict[str, Any]:
        if not item:
            return {
                "status": "unknown",
                "message": "Check unavailable",
                "details": {},
                "recovery_applicable": False,
                "duration_ms": 0,
            }
        return {
            "status": item.status.value,
            "message": item.message,
            "details": item.details,
            "recovery_applicable": item.recovery_applicable,
            "duration_ms": item.check_duration_ms,
        }

    queue_details = (queue_check.details if queue_check else {}) or {}
    hydration_details = (hydration_check.details if hydration_check else {}) or {}
    memory_details = (memory_check.details if memory_check else {}) or {}
    ws_details = (ws_check.details if ws_check else {}) or {}
    metrics_details = (metrics_check.details if metrics_check else {}) or {}

    max_capacity = int(queue_details.get("max_capacity", 0) or 0)
    queue_depth = int(queue_details.get("event_count", 0) or 0)
    queue_pressure = (queue_depth / max(max_capacity, 1)) if max_capacity else 0.0

    degraded_subsystems = [
        {
            "check_type": check.check_type.value,
            "status": check.status.value,
            "message": check.message,
            "details": check.details,
        }
        for check in report.checks
        if check.status.value != "healthy"
    ]

    return {
        "organization_id": org,
        "timestamp": report.timestamp.isoformat(),
        "overall_status": report.overall_status.value,
        "summary": {
            "total_checks": report.total_checks,
            "healthy_count": report.healthy_count,
            "degraded_count": report.degraded_count,
            "critical_count": report.critical_count,
        },
        "degraded_subsystems": degraded_subsystems,
        "checks": {
            "websocket": _pack_check(ws_check),
            "queue": _pack_check(queue_check),
            "execution": _pack_check(execution_check),
            "approval": _pack_check(approval_check),
            "replay": _pack_check(replay_check),
            "memory": _pack_check(memory_check),
            "latency": _pack_check(latency_check),
            "hydration": _pack_check(hydration_check),
            "metrics_freshness": _pack_check(metrics_check),
        },
        "stability": {
            "execution_readiness": stability.execution_readiness,
            "approval_readiness": stability.approval_readiness,
            "operational_stability": stability.operational_stability,
            "memory_integrity": stability.memory_integrity,
            "websocket_stability": stability.websocket_stability,
        },
        "observability": {
            "degraded_indicator_count": len(degraded_subsystems),
            "reconnect_diagnostics": {
                "active_connections": int(ws_details.get("active_connections", 0) or 0),
                "disconnects_last_5m": int(ws_details.get("disconnects_last_5m", 0) or 0),
                "disconnect_rate": float(ws_details.get("disconnect_rate", 0.0) or 0.0),
            },
            "runtime_drift": {
                "metrics_age_seconds": int(metrics_details.get("age_seconds", 0) or 0),
                "drift_detected": int(metrics_details.get("age_seconds", 0) or 0) > 300,
            },
            "queue_pressure": {
                "event_count": queue_depth,
                "max_capacity": max_capacity,
                "pressure_ratio": round(queue_pressure, 4),
                "failed_events": int(queue_details.get("failed_events", 0) or 0),
            },
            "hydration_failures": {
                "missing_fields": list(hydration_details.get("missing_fields", []) or []),
                "missing_field_count": len(list(hydration_details.get("missing_fields", []) or [])),
            },
            "persistence_integrity": {
                "fabric_checksum": memory_details.get("fabric_checksum"),
                "missing_field_count": len(list(memory_details.get("missing_fields", []) or [])),
                "pending_actions": int(memory_details.get("pending_actions", 0) or 0),
            },
        },
        "production_safe": report.critical_count == 0,
    }


@router.get("/memory/snapshot")
async def get_memory_snapshot(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get memory intelligence snapshot"""
    try:
        org = _resolve_org(user, organization_id)
        return memory_intelligence_fabric.build_memory_snapshot(org)
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/recovery/proposals")
async def get_recovery_proposals(
    organization_id: Optional[str] = Query(None),
    pending_only: bool = Query(False),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get recovery proposals"""
    try:
        org = _resolve_org(user, organization_id)
        
        if pending_only:
            proposals = runtime_recovery_engine.get_pending_proposals(org)
        else:
            proposals = runtime_recovery_engine.get_recovery_proposals(org)
        
        return {
            "organization_id": org,
            "timestamp": datetime.utcnow().isoformat(),
            "total_proposals": len(proposals),
            "proposals": [
                {
                    "proposal_id": p.proposal_id,
                    "recovery_type": p.recovery_type.value,
                    "severity": p.severity,
                    "description": p.description,
                    "requires_approval": p.requires_approval,
                }
                for p in proposals
            ],
        }
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/insights/risk-analysis")
async def get_risk_analysis(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get operational risk analysis"""
    try:
        org = _resolve_org(user, organization_id)
        analysis = await operational_insights_engine.analyze_operational_risk(org)
        
        return {
            "organization_id": org,
            "timestamp": analysis.timestamp.isoformat(),
            "overall_risk_score": analysis.overall_risk_score,
            "execution_risk": analysis.execution_risk,
            "deployment_risk": analysis.deployment_risk,
            "operational_risk": analysis.operational_risk,
            "provider_risk": analysis.provider_risk,
            "infrastructure_risk": analysis.infrastructure_risk,
            "risk_factors": analysis.risk_factors,
            "mitigations": analysis.mitigations,
        }
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/insights/anomalies")
async def detect_anomalies(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Detect operational anomalies"""
    try:
        org = _resolve_org(user, organization_id)
        anomalies = await operational_insights_engine.detect_anomalies(org)
        
        return {
            "organization_id": org,
            "timestamp": datetime.utcnow().isoformat(),
            "total_anomalies": len(anomalies),
            "anomalies": [
                {
                    "insight_id": a.insight_id,
                    "title": a.title,
                    "severity": a.severity,
                    "confidence": a.confidence,
                    "description": a.description,
                }
                for a in anomalies
            ],
        }
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/hydration/full")
async def get_full_hydration(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get complete UI hydration"""
    try:
        org = _resolve_org(user, organization_id)
        return command_center_hydration.build_full_hydration(org)
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/hydration/incident-cards")
async def hydrate_incident_cards(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Hydrate incident cards"""
    try:
        org = _resolve_org(user, organization_id)
        return command_center_hydration.hydrate_incident_cards(org)
    except Exception as e:
        return {"incidents": [], "error": str(e)}


@router.get("/hydration/execution-stream")
async def hydrate_execution_stream(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Hydrate execution stream"""
    try:
        org = _resolve_org(user, organization_id)
        return command_center_hydration.hydrate_execution_stream(org)
    except Exception as e:
        return {"executions": [], "error": str(e)}


@router.get("/hydration/approval-inbox")
async def hydrate_approval_inbox(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Hydrate approval inbox"""
    try:
        org = _resolve_org(user, organization_id)
        return command_center_hydration.hydrate_approval_inbox(org)
    except Exception as e:
        return {"pending_approvals": [], "error": str(e)}


@router.post("/validation/stress-test/reconnect-storm")
async def test_reconnect_storm(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Run reconnect storm stress test"""
    try:
        org = _resolve_org(user, organization_id)
        result = await stress_test_validator.run_reconnect_storm_test(org)
        
        return {
            "organization_id": org,
            "test_id": result.test_id,
            "test_type": result.test_type.value,
            "status": result.status,
            "duration_ms": result.duration_ms,
            "evidence": result.evidence,
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/validation/stress-test/all")
async def run_all_stress_tests(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Run all stress tests"""
    try:
        org = _resolve_org(user, organization_id)
        results = await stress_test_validator.run_all_stress_tests(org)
        
        passed = len([r for r in results if r.status == "passed"])
        failed = len([r for r in results if r.status == "failed"])
        
        return {
            "organization_id": org,
            "timestamp": datetime.utcnow().isoformat(),
            "total_tests": len(results),
            "passed": passed,
            "failed": failed,
            "pass_rate": passed / len(results) if results else 0,
            "test_results": [
                {
                    "test_type": r.test_type.value,
                    "status": r.status,
                    "duration_ms": r.duration_ms,
                }
                for r in results
            ],
        }
    except Exception as e:
        return {"error": str(e)}


@router.post("/validation/stress-test/live")
async def run_live_stress_validation(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Run live stress validations and return enterprise stability verdict."""
    org = _resolve_org(user, organization_id)
    results = await stress_test_validator.run_all_stress_tests(org)
    passed = [r for r in results if r.status == "passed"]
    failed = [r for r in results if r.status == "failed"]

    return {
        "organization_id": org,
        "timestamp": datetime.utcnow().isoformat(),
        "total_tests": len(results),
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": (len(passed) / len(results)) if results else 0.0,
        "enterprise_stability_validated": len(failed) == 0,
        "tests": [
            {
                "test_type": r.test_type.value,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "evidence": r.evidence,
                "failures": r.failures,
            }
            for r in results
        ],
    }


@router.get("/executive/readiness-score")
async def get_readiness_score(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get system readiness score for founder"""
    try:
        org = _resolve_org(user, organization_id)
        readiness = await founder_intelligence_mode.calculate_system_readiness(org)
        
        return {
            "organization_id": org,
            "timestamp": readiness.timestamp.isoformat(),
            "overall_score": readiness.overall_score,
            "execution_readiness": readiness.execution_readiness,
            "approval_readiness": readiness.approval_readiness,
            "deployment_readiness": readiness.deployment_readiness,
            "operational_stability": readiness.operational_stability,
            "memory_integrity": readiness.memory_integrity,
            "websocket_stability": readiness.websocket_stability,
            "recommendations": readiness.recommendations,
        }
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/executive/snapshot")
async def get_executive_snapshot(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get executive operational snapshot"""
    try:
        org = _resolve_org(user, organization_id)
        snapshot = await founder_intelligence_mode.build_executive_snapshot(org)
        
        return {
            "organization_id": org,
            "timestamp": snapshot.timestamp.isoformat(),
            "system_readiness_score": snapshot.system_readiness_score,
            "deployment_readiness_score": snapshot.deployment_readiness_score,
            "runtime_stability_score": snapshot.runtime_stability_score,
            "operational_risk_score": snapshot.operational_risk_score,
            "founder_checklist": snapshot.founder_checklist,
            "all_systems_ready": all(snapshot.founder_checklist.values()),
            "critical_alerts": snapshot.critical_alerts,
            "next_actions": snapshot.next_actions,
        }
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }


@router.get("/executive/report")
async def get_executive_report(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get complete executive report"""
    try:
        org = _resolve_org(user, organization_id)
        return founder_intelligence_mode.build_executive_report(org)
    except Exception as e:
        return {
            "organization_id": org,
            "error": str(e),
        }
