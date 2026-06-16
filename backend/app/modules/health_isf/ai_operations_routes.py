"""Operational command center APIs for enterprise autonomous intelligence."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

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
from app.db.session import get_db
from app.modules.health_isf.ai_action_executor import AIActionExecutor
from app.modules.health_isf.ai_agent_coordinator import AIAgentCoordinator
from app.modules.health_isf.ai_governance_engine import AIGovernanceEngine
from app.modules.health_isf.ai_audit_engine import AIAuditEngine
from app.modules.health_isf.ai_reasoning_engine import AIReasoningEngine
from app.modules.health_isf.approval_models import GovernanceApprovalRequest
from app.modules.health_isf.correlation_engine import CorrelationEngine
from app.modules.health_isf.governance_models import (
    GovernanceApprovalResponse,
    GovernanceAuditRecord,
    GovernanceCorrelationItem,
    GovernanceStatusResponse,
    GovernanceTimelineItem,
)
from app.modules.health_isf.governance_registry import APPROVAL_ROLES
from app.modules.health_isf.enterprise_feature_flags import get_feature_snapshot, is_feature_enabled
from app.modules.health_isf.incident_detection_engine import IncidentDetectionEngine
from app.modules.health_isf.memory_service import OperationalMemoryService
from app.modules.health_isf.operations import build_operational_metrics
from app.modules.health_isf.prediction_engine import AIPredictionEngine
from app.modules.health_isf.predictive_operations import PredictiveOperationsEngine
from app.modules.health_isf.realtime import get_broadcaster
from app.modules.health_isf.operational_timeline import OperationalTimelineEngine
from app.modules.health_isf.models import HealthISFDriver, HealthISFProvider, HealthISFRide
from app.modules.health_isf.operational_identity_engine import OperationalIdentityEngine
from app.modules.health_isf.operational_map_service import OperationalMapService
from app.modules.health_isf.dispatch_intelligence import DispatchIntelligenceEngine
from app.modules.health_isf.distributed_operations import DistributedOperationsService
from app.modules.health_isf.graph_correlation_service import GraphCorrelationService
from app.modules.health_isf.live_client_contracts import build_live_client_contracts
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_memory_engine import OperationalMemoryEngine
from app.modules.health_isf.operational_forecast_engine import OperationalForecastEngine
from app.modules.health_isf.coordination_recommendation_pipeline import CoordinationRecommendationPipeline
from app.modules.health_isf.operational_approval_engine import OperationalApprovalEngine
from app.modules.health_isf.audit_playback_service import AuditPlaybackService
from app.modules.health_isf.reasoning_inspection_service import ReasoningInspectionService
from app.modules.health_isf.operational_replay_service import OperationalReplayService
from app.modules.health_isf.operational_recommendation_pipeline import OperationalRecommendationPipeline
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.security import enforce_tenant_scope
from app.core.nova.execution_intelligence import NovaExecutionIntelligence


router = APIRouter(
    prefix="/api/ai",
    tags=["ai-operations"],
    dependencies=[Depends(require_any_role(
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_DISPATCHER,
        ROLE_STAFF,
        ROLE_ANALYTICS_READONLY,
    ))],
)


class AIActionExecuteRequest(BaseModel):
    organization_id: str | None = None
    action_type: str
    parameters: dict[str, Any] = {}


class AIIncidentEscalateRequest(BaseModel):
    organization_id: str | None = None
    incident_id: str | None = None
    ride_id: str | None = None
    summary: str | None = None
    severity: str = "high"
    target_role: str = "dispatcher"
    escalation_level: int = 1
    details: dict[str, Any] = {}


def _memory_response(organization_id: str, stream: str, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "organization_id": organization_id,
        "stream": stream,
        "count": len(events),
        "events": events,
    }


def _extract_coordinates(payload: Any) -> tuple[float, float] | None:
    if not isinstance(payload, dict):
        return None
    lat = payload.get("lat") or payload.get("latitude")
    lng = payload.get("lng") or payload.get("lon") or payload.get("longitude")
    try:
        if lat is None or lng is None:
            return None
        lat_f = float(lat)
        lng_f = float(lng)
    except (TypeError, ValueError):
        return None
    if not (-90.0 <= lat_f <= 90.0 and -180.0 <= lng_f <= 180.0):
        return None
    return lat_f, lng_f


def _build_operational_intelligence_expansion_snapshot(
    db: Session,
    organization_id: str,
    telemetry_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    broadcaster = get_broadcaster()
    connection_ids = broadcaster.organization_connections.get(organization_id, set()).copy()

    for connection_id in connection_ids:
        connection = broadcaster.connections.get(connection_id)
        if connection is None:
            continue
        role = str(connection.role or "staff")
        identity_type = role if role in {"driver", "provider", "dispatcher", "staff", "admin"} else "staff"
        OperationalIdentityEngine.register_identity(
            organization_id=organization_id,
            identity_id=str(connection.user_id),
            identity_type=identity_type,
            role=role,
            display_name=str(connection.user_id),
            metadata={"source": "websocket"},
        )
        OperationalIdentityEngine.open_session(
            organization_id=organization_id,
            identity_id=str(connection.user_id),
            websocket_connection_id=connection_id,
            session_id=connection_id,
        )

    rides = (
        db.query(HealthISFRide)
        .filter(HealthISFRide.organization_id == organization_id)
        .order_by(HealthISFRide.requested_at.desc())
        .limit(100)
        .all()
    )
    drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id).all()
    providers = db.query(HealthISFProvider).filter(HealthISFProvider.organization_id == organization_id).all()

    for driver in drivers:
        context = {}
        try:
            context = {} if driver.vehicle_type is None else {"vehicle_type": str(driver.vehicle_type)}
        except Exception:
            context = {}
        coords = _extract_coordinates(context)
        if coords is None:
            continue
        OperationalMapService.update_driver_position(
            organization_id=organization_id,
            driver_id=str(driver.id),
            lat=coords[0],
            lng=coords[1],
            status=str(driver.status),
        )

    for provider in providers:
        coords = None
        if isinstance(provider.address, str) and provider.address.strip().startswith("{"):
            try:
                import json
                address_payload = json.loads(provider.address)
                coords = _extract_coordinates(address_payload)
            except Exception:
                coords = None
        if coords is None:
            continue
        OperationalMapService.update_provider_zone(
            organization_id=organization_id,
            provider_id=str(provider.id),
            center_lat=coords[0],
            center_lng=coords[1],
            radius_km=5.0,
            metadata={"source": "provider_address_payload"},
        )

    for ride in rides:
        context_payload: dict[str, Any] = {}
        if isinstance(ride.ai_dispatch_context, str) and ride.ai_dispatch_context.strip().startswith("{"):
            try:
                import json
                context_payload = json.loads(ride.ai_dispatch_context)
            except Exception:
                context_payload = {}
        incident_coords = _extract_coordinates(context_payload.get("incident_location"))
        if incident_coords is not None:
            OperationalMapService.update_incident_signal(
                organization_id=organization_id,
                incident_id=f"ride-{ride.id}",
                lat=incident_coords[0],
                lng=incident_coords[1],
                severity="high" if bool(getattr(ride, "is_emergency", False)) else "medium",
                category="dispatch_incident",
            )

        GraphCorrelationService.correlate(
            organization_id=organization_id,
            source={"id": f"ride:{ride.id}", "type": "incident", "label": ride.id, "status": str(ride.status)},
            target={"id": f"provider:{ride.provider_id or 'unassigned'}", "type": "provider", "label": str(ride.provider_id or "unassigned")},
            relationship_type="served_by",
            confidence=0.9 if ride.provider_id else 0.6,
            explanation="Ride to provider relationship derived from dispatch record.",
        )
        if ride.driver_id:
            GraphCorrelationService.correlate(
                organization_id=organization_id,
                source={"id": f"ride:{ride.id}", "type": "incident", "label": ride.id, "status": str(ride.status)},
                target={"id": f"driver:{ride.driver_id}", "type": "driver", "label": str(ride.driver_id)},
                relationship_type="assigned_to",
                confidence=0.95,
                explanation="Ride to driver relationship derived from assignment state.",
            )

    identity_snapshot = OperationalIdentityEngine.continuity_snapshot(organization_id)
    geospatial_snapshot = OperationalMapService.get_map_state(organization_id=organization_id)
    dispatch_snapshot = DispatchIntelligenceEngine.build_bundle(db, organization_id)
    diaspora_snapshot = DistributedOperationsService.get_snapshot(organization_id=organization_id)
    graph_snapshot = GraphCorrelationService.snapshot(organization_id=organization_id)
    contracts_snapshot = build_live_client_contracts(organization_id)

    event_publications = []
    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.DISPATCH_RECOMMENDATION,
            payload={
                "recommendation_count": int(dispatch_snapshot.get("summary", {}).get("total", 0)),
                "emergency_recommendations": int(dispatch_snapshot.get("summary", {}).get("emergency_recommendations", 0)),
            },
            role_scope=["dispatcher", "driver", "provider"],
            source_nonce=f"dispatch:{organization_id}:{int(dispatch_snapshot.get('summary', {}).get('total', 0))}",
        )
    )
    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.GEOSPATIAL_UPDATE,
            payload={
                "driver_positions": len(geospatial_snapshot.get("live_operational_map_state", {}).get("driver_positioning", [])),
                "incident_clusters": len(geospatial_snapshot.get("live_operational_map_state", {}).get("incident_clustering", [])),
                "density_regions": len(geospatial_snapshot.get("live_operational_map_state", {}).get("operational_density_regions", [])),
            },
            role_scope=["dispatcher", "driver", "provider", "staff"],
            source_nonce=f"geo:{organization_id}:{len(geospatial_snapshot.get('live_operational_map_state', {}).get('incident_clustering', []))}",
        )
    )

    alert_count = len(geospatial_snapshot.get("live_operational_map_state", {}).get("emergency_overlays", []))
    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.OPERATIONAL_ALERT,
            payload={"alert_count": alert_count},
            role_scope=["dispatcher", "driver", "provider", "admin"],
            source_nonce=f"alerts:{organization_id}:{alert_count}",
        )
    )

    if alert_count > 0:
        event_publications.append(
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.ESCALATION,
                payload={
                    "escalation_reason": "emergency_overlay_detected",
                    "count": alert_count,
                },
                role_scope=["dispatcher", "staff", "admin"],
                source_nonce=f"escalation:{organization_id}:{alert_count}",
            )
        )

    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.DRIVER_STATE,
            payload={
                "active_sessions": identity_snapshot.get("operational_session_continuity", {}).get("active_sessions", 0),
                "active_identities": identity_snapshot.get("operational_session_continuity", {}).get("active_identities", 0),
            },
            role_scope=["dispatcher", "driver", "admin"],
            source_nonce=f"driverstate:{organization_id}:{identity_snapshot.get('operational_session_continuity', {}).get('active_sessions', 0)}",
        )
    )

    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.PROVIDER_STATUS,
            payload={
                "clusters": len(diaspora_snapshot.get("regional_tenant_clustering", [])),
            },
            role_scope=["provider", "dispatcher", "admin"],
            source_nonce=f"providerstatus:{organization_id}:{len(diaspora_snapshot.get('regional_tenant_clustering', []))}",
        )
    )

    reconnect_count = int(get_broadcaster().get_websocket_health_stats(organization_id).get("disconnects_last_5m", 0))
    if reconnect_count > 0:
        event_publications.append(
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.WEBSOCKET_RECONNECT,
                payload={
                    "disconnects_last_5m": reconnect_count,
                    "reconnect_safe": True,
                },
                role_scope=["dispatcher", "driver", "provider", "admin"],
                source_nonce=f"reconnect:{organization_id}:{reconnect_count}",
            )
        )

    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.INCIDENT,
            payload={
                "graph_relationships": int(graph_snapshot.get("relationship_count", 0)),
                "tenant_isolated": bool(graph_snapshot.get("tenant_isolated", False)),
            },
            role_scope=["dispatcher", "driver", "provider", "staff"],
            source_nonce=f"incident:{organization_id}:{int(graph_snapshot.get('relationship_count', 0))}",
        )
    )

    sync_snapshot = OperationalSynchronizationEngine.synchronization_snapshot(organization_id)
    replay_snapshot = OperationalReplayService.replay(
        organization_id=organization_id,
        after_sequence=max(0, int(sync_snapshot.get("event_bus", {}).get("latest_sequence", 0)) - 100),
        role="dispatcher",
        limit=100,
    )
    replay_integrity = OperationalReplayService.replay_integrity(organization_id)
    decision_snapshot = OperationalRecommendationPipeline.build_snapshot(
        organization_id=organization_id,
        telemetry_metrics=telemetry_metrics or build_operational_metrics(db, organization_id=organization_id),
        geospatial_snapshot=geospatial_snapshot,
        dispatch_snapshot=dispatch_snapshot,
        sync_snapshot=sync_snapshot,
    )
    memory_snapshot = OperationalMemoryEngine.build_snapshot(
        db,
        organization_id=organization_id,
        role="dispatcher",
    )
    adaptive_forecast_snapshot = OperationalForecastEngine.build_snapshot(
        organization_id=organization_id,
        decision=decision_snapshot,
        memory=memory_snapshot,
        sync=sync_snapshot,
    )
    coordination_snapshot = CoordinationRecommendationPipeline.build_snapshot(
        organization_id=organization_id,
        metrics=telemetry_metrics or build_operational_metrics(db, organization_id=organization_id),
        decision=decision_snapshot,
        memory=memory_snapshot,
        adaptive_forecast=adaptive_forecast_snapshot,
        sync_snapshot=sync_snapshot,
    )
    supervisory_snapshot = OperationalApprovalEngine.build_snapshot(
        db,
        organization_id=organization_id,
        coordination=coordination_snapshot,
        decision=decision_snapshot,
    )
    supervisory_snapshot["audit_playback"] = AuditPlaybackService.build(
        db,
        organization_id=organization_id,
        limit=25,
    )
    supervisory_snapshot["reasoning_inspection"] = ReasoningInspectionService.build(
        decision=decision_snapshot,
        coordination=coordination_snapshot,
        adaptive_forecast=adaptive_forecast_snapshot,
    )

    top_recommendation = (decision_snapshot.get("recommendations") or [None])[0] or {}
    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.DISPATCH_RECOMMENDATION,
            payload={
                "decision_intelligence": True,
                "recommendation_id": str(top_recommendation.get("recommendation_id") or ""),
                "recommendation_type": str(top_recommendation.get("recommendation_type") or ""),
                "priority_score": float(top_recommendation.get("priority_score") or 0.0),
                "confidence": float(top_recommendation.get("confidence") or 0.0),
            },
            role_scope=["dispatcher", "driver", "provider", "admin"],
            source_nonce=(
                "decision:"
                f"{organization_id}:"
                f"{str(top_recommendation.get('recommendation_id') or 'none')}"
            ),
        )
    )
    top_coordination = (coordination_snapshot.get("recommendations") or [None])[0] or {}
    event_publications.append(
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.COORDINATION_RECOMMENDATION,
            payload={
                "multi_agent_coordination": True,
                "recommendation_id": str(top_coordination.get("recommendation_id") or ""),
                "coordination_type": str(top_coordination.get("coordination_type") or ""),
                "confidence": float(top_coordination.get("confidence") or 0.0),
            },
            role_scope=["dispatcher", "driver", "provider", "staff", "admin"],
            source_nonce=(
                "coordination:"
                f"{organization_id}:"
                f"{str(top_coordination.get('recommendation_id') or 'none')}"
            ),
        )
    )

    return {
        "operational_identity": identity_snapshot,
        "geospatial_intelligence": geospatial_snapshot,
        "dispatch_intelligence": dispatch_snapshot,
        "diaspora_distributed_network": diaspora_snapshot,
        "operational_knowledge_graph": graph_snapshot,
        "live_client_foundation_contracts": contracts_snapshot,
        "operational_decision_intelligence": decision_snapshot,
        "operational_memory_fabric": memory_snapshot,
        "adaptive_operational_forecasting": adaptive_forecast_snapshot,
        "multi_agent_operational_coordination": coordination_snapshot,
        "human_oversight_intelligence": supervisory_snapshot,
        "distributed_operational_event_fabric": {
            "event_types_supported": [item.value for item in OperationalEventType],
            "synchronization": sync_snapshot,
            "replay": replay_snapshot,
            "replay_integrity": replay_integrity,
            "event_publication_results": event_publications,
            "backend_authoritative": True,
            "approval_governed": True,
            "tenant_scoped": True,
        },
    }


@router.get("/operations/status")
async def get_operations_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    telemetry = {
        "websocket": get_broadcaster().get_websocket_health_stats(organization_id=effective_org_id),
        "metrics": build_operational_metrics(db, organization_id=effective_org_id),
    }
    if is_feature_enabled("ENABLE_AI_MEMORY", role=user.role):
        OperationalMemoryService.record_operation(
            db,
            organization_id=effective_org_id,
            actor_user_id=user.user_id,
            operation={
                "operation_type": "operations_status_snapshot",
                "telemetry": telemetry,
            },
            replay_hint=f"ops:{effective_org_id}:{telemetry.get('metrics', {}).get('active_rides', 0)}:{telemetry.get('metrics', {}).get('unassigned_rides', 0)}",
        )
    coordinator = await AIAgentCoordinator.orchestrate(
        db,
        organization_id=effective_org_id,
        user=user,
        telemetry=telemetry,
        auto_execute=False,
    )
    
    # Include execution intelligence (optional, gracefully degrades)
    execution_intelligence = {}
    try:
        execution_intelligence = await NovaExecutionIntelligence.build_execution_status_snapshot(
            effective_org_id
        )
    except Exception:
        pass  # Graceful degradation - execution intelligence is optional
    
    return {
        "organization_id": effective_org_id,
        "features": get_feature_snapshot(role=user.role),
        "autonomous_mode": is_feature_enabled("AI_AUTONOMOUS_MODE", role=user.role),
        "telemetry": telemetry,
        "coordinator": coordinator,
        "operational_intelligence_expansion": _build_operational_intelligence_expansion_snapshot(
            db,
            effective_org_id,
            telemetry_metrics=telemetry.get("metrics") or {},
        ),
        "execution_intelligence": execution_intelligence,
    }


@router.get("/incidents/live")
def get_live_incidents(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    incidents = IncidentDetectionEngine.detect(db, organization_id=effective_org_id)
    if is_feature_enabled("ENABLE_AI_MEMORY", role=user.role):
        for incident in incidents:
            OperationalMemoryService.record_incident(
                db,
                organization_id=effective_org_id,
                actor_user_id=user.user_id,
                incident=incident,
                replay_hint=str(incident.get("incident_id") or ""),
            )
    return {
        "organization_id": effective_org_id,
        "count": len(incidents),
        "incidents": incidents,
    }


@router.get("/predictions")
def get_predictions(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if not is_feature_enabled("AI_PREDICTIVE_OPERATIONS", role=user.role):
        return {
            "organization_id": effective_org_id,
            "enabled": False,
            "predictions": [],
        }
    predictions = PredictiveOperationsEngine.predict(db, organization_id=effective_org_id)
    return {
        "organization_id": effective_org_id,
        "enabled": True,
        "predictions": predictions,
    }


@router.get("/memory/incidents")
def get_memory_incidents(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if not is_feature_enabled("ENABLE_AI_MEMORY", role=user.role):
        return _memory_response(effective_org_id, "incidents", [])
    events = OperationalMemoryService.list_stream(
        db,
        organization_id=effective_org_id,
        stream="incidents",
        role=user.role,
        limit=limit,
    )
    return _memory_response(effective_org_id, "incidents", events)


@router.get("/memory/operations")
def get_memory_operations(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if not is_feature_enabled("ENABLE_AI_MEMORY", role=user.role):
        return _memory_response(effective_org_id, "operations", [])
    events = OperationalMemoryService.list_stream(
        db,
        organization_id=effective_org_id,
        stream="operations",
        role=user.role,
        limit=limit,
    )
    return _memory_response(effective_org_id, "operations", events)


@router.get("/memory/predictions")
def get_memory_predictions(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if not is_feature_enabled("ENABLE_AI_MEMORY", role=user.role):
        return _memory_response(effective_org_id, "predictions", [])
    events = OperationalMemoryService.list_stream(
        db,
        organization_id=effective_org_id,
        stream="predictions",
        role=user.role,
        limit=limit,
    )
    return _memory_response(effective_org_id, "predictions", events)


@router.get("/memory/executions")
def get_memory_executions(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if not is_feature_enabled("ENABLE_AI_MEMORY", role=user.role):
        return _memory_response(effective_org_id, "executions", [])
    events = OperationalMemoryService.list_stream(
        db,
        organization_id=effective_org_id,
        stream="executions",
        role=user.role,
        limit=limit,
    )
    return _memory_response(effective_org_id, "executions", events)


@router.get("/reasoning/incidents")
def get_reasoning_incidents(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return AIReasoningEngine.reason_incidents(
        db,
        organization_id=effective_org_id,
        user=user,
    )


@router.get("/reasoning/anomalies")
def get_reasoning_anomalies(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return AIReasoningEngine.reason_anomalies(
        db,
        organization_id=effective_org_id,
        user=user,
    )


@router.get("/reasoning/risk-score")
def get_reasoning_risk_score(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return AIReasoningEngine.risk_score(
        db,
        organization_id=effective_org_id,
        user=user,
    )


@router.get("/predictions/sla")
def get_prediction_sla(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return AIPredictionEngine.predict_sla(
        db,
        organization_id=effective_org_id,
        user=user,
    )


@router.get("/predictions/load")
def get_prediction_load(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return AIPredictionEngine.predict_load(
        db,
        organization_id=effective_org_id,
        user=user,
    )


@router.get("/predictions/emergency")
def get_prediction_emergency(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return AIPredictionEngine.predict_emergency(
        db,
        organization_id=effective_org_id,
        user=user,
    )


@router.get("/decision-stream")
def get_decision_stream(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    events = AIAuditEngine.recent_audit_events(db, organization_id=effective_org_id, limit=limit)
    return {
        "organization_id": effective_org_id,
        "events": events,
    }


@router.post("/actions/execute")
async def execute_ai_action(
    request: AIActionExecuteRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, request.organization_id)
    try:
        result = await AIActionExecutor.execute(
            db,
            user=user,
            organization_id=effective_org_id,
            action_type=request.action_type,
            parameters=request.parameters,
        )
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/incidents/escalate")
async def escalate_incident(
    request: AIIncidentEscalateRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, request.organization_id)
    try:
        result = await AIActionExecutor.execute(
            db,
            user=user,
            organization_id=effective_org_id,
            action_type="escalate_incident",
            parameters={
                "incident_id": request.incident_id,
                "ride_id": request.ride_id,
                "summary": request.summary,
                "severity": request.severity,
                "target_role": request.target_role,
                "escalation_level": request.escalation_level,
                "details": request.details,
            },
        )
        return result
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/governance/status", response_model=GovernanceStatusResponse)
def get_governance_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = AIGovernanceEngine.validate_tenant_scope(user, organization_id)
    metrics = build_operational_metrics(db, organization_id=effective_org_id)
    websocket_health = get_broadcaster().get_websocket_health_stats(organization_id=effective_org_id)
    audits = AIGovernanceEngine.audit_snapshot(db, organization_id=effective_org_id, limit=500)
    approvals = AIGovernanceEngine.approval_snapshot(db, organization_id=effective_org_id, limit=500)
    return GovernanceStatusResponse(
        organization_id=effective_org_id,
        confidence_threshold=0.65,
        approval_required=True,
        rollback_required=True,
        tenant_scoped=True,
        append_only_audit=True,
        audit_count=len(audits),
        approval_count=len(approvals),
        reasoning_count=sum(1 for item in audits if str(item.get("event_type", "")).endswith("reasoning_registered")),
        prediction_count=sum(1 for item in audits if str(item.get("event_type", "")).endswith("prediction_registered")),
        execution_count=sum(1 for item in audits if str(item.get("event_type", "")).endswith("execution_policy_checked")),
        websocket_health=websocket_health,
        metrics=metrics,
    )


@router.get("/governance/audits", response_model=list[GovernanceAuditRecord])
def get_governance_audits(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = AIGovernanceEngine.validate_tenant_scope(user, organization_id)
    events = AIGovernanceEngine.audit_snapshot(db, organization_id=effective_org_id, limit=limit)
    return [GovernanceAuditRecord(**event) for event in events]


@router.get("/governance/approvals", response_model=list[GovernanceApprovalResponse])
def get_governance_approvals(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = AIGovernanceEngine.validate_tenant_scope(user, organization_id)
    approvals = AIGovernanceEngine.approval_snapshot(db, organization_id=effective_org_id, limit=limit)
    return [GovernanceApprovalResponse(**approval) for approval in approvals]


@router.post("/governance/approvals", response_model=GovernanceApprovalResponse)
def upsert_governance_approval(
    request: GovernanceApprovalRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = AIGovernanceEngine.validate_tenant_scope(user, request.organization_id or request.tenant_scope)
    if request.approval_id and request.approval_token and request.approved:
        AIGovernanceEngine.validate_role_scope(user, APPROVAL_ROLES)
        approval = AIGovernanceEngine.approve_approval(
            db,
            organization_id=effective_org_id,
            actor_user_id=user.user_id,
            approval_id=request.approval_id,
            approval_token=request.approval_token,
        )
        return GovernanceApprovalResponse(**approval.model_dump())

    AIGovernanceEngine.validate_role_scope(user, APPROVAL_ROLES)
    contract = AIGovernanceEngine.create_approval_proposal(
        db,
        organization_id=effective_org_id,
        actor_user_id=user.user_id,
        action_type=str(request.action_type or "").strip(),
        parameters=request.parameters,
        confidence_score=request.confidence_score,
        rollback_available=request.rollback_available,
        expiration_minutes=request.execution_expiration_minutes,
        tenant_scope=effective_org_id,
    )
    return GovernanceApprovalResponse(**contract.model_dump())


@router.get("/governance/timeline", response_model=list[GovernanceTimelineItem])
def get_governance_timeline(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = AIGovernanceEngine.validate_tenant_scope(user, organization_id)
    timeline = OperationalTimelineEngine.reconstruct_operational_timeline(
        db,
        organization_id=effective_org_id,
        role=user.role,
        limit=limit,
    )
    return [GovernanceTimelineItem(**item) for item in timeline]


@router.get("/governance/correlations", response_model=list[GovernanceCorrelationItem])
def get_governance_correlations(
    organization_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = AIGovernanceEngine.validate_tenant_scope(user, organization_id)
    correlations = CorrelationEngine.build_correlations(
        db,
        organization_id=effective_org_id,
        role=user.role,
        limit=limit,
    )
    return [GovernanceCorrelationItem(**item) for item in correlations]


# ─── Nova Execution Intelligence ──────────────────────────────────────────────

@router.get("/execution/status")
async def get_execution_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get Nova execution orchestration status - pending actions, executing, failed, rollbacks."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    try:
        execution_snapshot = await NovaExecutionIntelligence.build_execution_status_snapshot(
            effective_org_id
        )
        return execution_snapshot
    except Exception as exc:
        # Graceful degradation - execution intelligence is optional
        return {
            "organization_id": effective_org_id,
            "approval_queue": {"awaiting_approval_count": 0},
            "execution": {"executing_count": 0, "failed_count": 0},
            "recovery": {"rollback_count": 0},
            "error": str(exc),
        }


@router.get("/execution/pending-approvals")
async def get_pending_approvals(
    organization_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get actions awaiting operator approval - safe human-approval workflow."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    try:
        actions = await NovaExecutionIntelligence.get_pending_approval_actions(
            effective_org_id,
            limit=limit,
        )
        return {
            "organization_id": effective_org_id,
            "pending_count": len(actions),
            "actions": actions,
        }
    except Exception as exc:
        return {
            "organization_id": effective_org_id,
            "pending_count": 0,
            "actions": [],
            "error": str(exc),
        }


@router.get("/execution/evidence/{action_id}")
async def get_execution_evidence(
    action_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get execution evidence and results for completed action."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    try:
        evidence = await NovaExecutionIntelligence.get_execution_evidence(
            effective_org_id,
            action_id,
        )
        if not evidence:
            raise HTTPException(status_code=404, detail="Action not found")
        return evidence
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

