"""
API routes for Health ISF module.
MVP routes: status, rides (GET/POST), drivers, providers, dashboard.
Real-time routes: WebSocket, activity feed, events.
"""
import logging
import os
from datetime import datetime, timezone, timedelta
import asyncio
import json
import hashlib
from typing import Any, cast

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query, Request, Body
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.auth import (
    ROLE_ADMIN,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_ANALYTICS_READONLY,
    ROLE_SUPER_ADMIN_SUPPORT,
    require_any_role,
    get_current_user_context,
    decode_access_token,
    UserContext,
    _bearer,
    _jwt_verify,
    get_current_user,
    resolve_session_role,
    get_user_authorized_roles,
    normalize_role,
)
from app.db.session import SessionLocal, get_db
from app.helpers import now, uuid4
from app.modules.health_isf import service
from app.modules.health_isf.driver_mobile_auth import (
    DriverEndpointAuth,
    require_driver_accept_auth,
    require_driver_mobile_or_platform,
    require_driver_workflow_auth,
    require_ride_mobile_or_platform,
    _platform_user_context,
    _driver_session_context,
    HEALTH_ISF_PLATFORM_ROLES,
)
from app.modules.health_isf.driver_mobile_sync_log import (
    record_backend_assignment_sync,
    record_driver_mobile_assignment_sync,
    resolve_driver_session_id,
    safe_text as _sync_safe_text,
)
from app.modules.health_isf.financial_engine import TripFinancialEngine
from app.modules.health_isf.intake import (
    build_ai_dispatch_context,
    build_intake_fingerprint,
    calculate_duration_minutes,
    calculate_priority_score,
    normalize_priority_tag,
)
from app.modules.health_isf.models import HealthISFRide, HealthISFRecurringRideSchedule, EventType, ActivityAction, RideStatus, DriverStatus
from app.modules.health_isf.models import HealthISFDispatchLog, HealthISFRideStatusHistory, HealthISFDriver
from app.modules.health_isf.models import HealthISFWorkflowEscalation, HealthISFDispatchAssignment, DispatchAssignmentState
from app.modules.health_isf.schemas import (
    AdminDispatchAlertsResponse,
    AdminDispatchInterventionResponse,
    AdminForceExpireAssignmentRequest,
    AdminLiveOperationsResponse,
    AdminReassignDriverRequest,
    CustomerRideQueueMetricsResponse,
    CustomerRideRequestCreateRequest,
    CustomerRideRequestResponse,
    CustomerRideRequestStatusUpdateRequest,
    DriverActivePoolMetricsResponse,
    DriverAvailabilityRequest,
    DriverHeartbeatRequest,
    DriverLoginRequest,
    DriverMobileLoginRequest,
    DriverLoginResponse,
    DriverMobileAssignmentSyncLogRequest,
    DriverLogoutRequest,
    DriverRuntimeStatusResponse,
    DriverSessionValidationResponse,
    DriverLiveWorkspaceResponse,
    DriverActiveRideResponse,
    DriverRouteProgressRequest,
    DispatchActiveAssignmentItemResponse,
    DispatchAutoAssignRequest,
    DispatchAutoAssignResponse,
    DispatchOfferResponse,
    DispatchQueueItemResponse,
    DispatchRecommendationApproveRequest,
    DispatchRecommendationGenerateRequest,
    DispatchRecommendationResponse,
    DispatchReassignRequest,
    DispatcherCustomerRequestActionResponse,
    DispatcherCustomerRequestAssignDriverRequest,
    DispatcherCustomerRequestAutoDispatchRequest,
    DispatcherCustomerRequestReassignRequest,
    DispatcherCustomerRequestReasonRequest,
    DashboardMetrics, DispatchLogResponse, DriverCreate, DriverContactRiderRequest, DriverContactRiderResponse, DriverResponse, DriverRideActionRequest, DriverStatusUpdateRequest,
    DriverApplicationCreateRequest,
    DriverApplicationResponse,
    DriverApplicationStatusUpdateRequest,
    GrantProofSnapshotResponse,
    PayoutResponse, ProviderCreate, ProviderResponse, DriverUpdate, ProviderUpdate, RideAssignDriverRequest,
    RideAssignVehicleRequest,
    RecurringRideTemplateResponse,
    RecurringScheduleCreateRequest,
    RecurringScheduleResponse,
    RecurringScheduleStatusUpdateRequest,
    RideCreate, RideHistoryEventResponse, RideResponse, RideStatusUpdateRequest,
    RideArrivalStatusResponse,
    RideCompletionHandoffResponse,
    TripFinancialSummaryResponse,
    DriverEarningsSummaryResponse,
    DriverCompletionSnapshotResponse,
    BillingHandoffQueueItemResponse,
    TripDocumentResponse,
    AdminRevenueSummaryResponse,
    RidePickupStatusResponse,
    VehicleCreate,
    VehicleResponse,
    StatusResponse, TripResponse, ActivityFeedResponse, DispatcherActivityResponse, WebSocketMessage,
    ConcurrentAssignmentError,
    OperationalMetricsResponse,
    OperationalHealthResponse,
    OperationalAlertResponse,
    OperationalDashboardResponse,
    RoutePlanRequest,
    DriverLocationIngestRequest,
    MobileReconnectRequest,
    PaymentIntentRequest,
    PaymentCaptureRequest,
    PaymentSettlementRequest,
    IntelligenceAnomalyResponse,
    IntelligenceRecommendationResponse,
    IntelligenceRiskResponse,
    IntelligenceSummaryResponse,
    IntelligenceReanalyzeRequest,
    IntelligenceReanalyzeResponse,
    IntelligenceThresholds,
    WorkflowRecoverRequest,
    WorkflowReassignRequest,
    WorkflowReplayRequest,
    WorkflowEscalateRequest,
    WorkflowExecutionResponse,
    WorkflowIncidentResponse,
    WorkflowEscalationResponse,
    WorkflowOperationResponse,
    AIDispatchVoiceCommandRequest,
    AIDispatchVoiceCommandResponse,
    AIDispatchIntakeAssistRequest,
    AIDispatchIntakeAssistResponse,
    AIDispatchNotificationResponse,
    OperationalTimelineItemResponse,
    AutonomousOperationsSnapshotResponse,
    RiderEventFeedItem,
    RiderLiveTrackingResponse,
)
from app.modules.health_isf.realtime import (
    get_broadcaster, get_emitter, WebSocketConnection, SubscriptionType
)
from app.modules.health_isf.realtime_service import (
    RealTimeEventService, ActivityLogService, ConcurrentAssignmentService,
    RetryQueueService, IdempotencyService, OperationalAlertService,
)
from app.modules.health_isf.operations import (
    get_operational_metrics_registry,
    log_operational_event,
    build_operational_metrics,
    build_health_snapshot,
    evaluate_operational_alerts,
    build_operational_dashboard,
)
from app.modules.health_isf.intelligence import IntelligenceThresholds as RuntimeIntelligenceThresholds
from app.modules.health_isf.intelligence import OperationalIntelligenceService
from app.modules.health_isf.operational_cognition_engine import OperationalCognitionEngine
from app.modules.health_isf.ai_dispatch import AIDispatchOrchestrationService
from app.modules.health_isf.workflow_engine import WorkflowOrchestrationService
from app.modules.health_isf.ride_execution_engine import RideLifecycleManager
from app.modules.health_isf.dispatch_orchestration_engine import DispatchOrchestrationEngine
from app.modules.health_isf.operational_workflow_orchestration import (
    PHASE16_RIDE_STATES,
    PHASE16_RIDE_TRANSITIONS,
    build_geospatial_foundation,
    build_operational_workflow_overview,
    build_workflow_event_stream,
)
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_replay_service import OperationalReplayService
from app.modules.health_isf.operational_command_center import OperationalCommandCenterService
from app.modules.health_isf.operational_orchestration_resilience import OperationalOrchestrationResilienceService
from app.modules.health_isf.production_transport_ops import ProductionTransportOps, ProductionPaymentOps
from app.core.nova.service import NovaCoreService
from app.modules.health_isf.security import (
    enforce_tenant_scope,
    enforce_entity_tenant,
    authorize_subscription,
    ensure_admin_action,
)
from app.modules.health_isf.security_service import (
    SecurityAuditService,
    SuspiciousActivityService,
)
from app.modules.health_isf.models import HealthISFPaymentTransaction
from app.modules.health_isf.models import HealthISFWorkflowAuditLog
from app.modules.health_isf.runtime_state_manager import get_live_transport_runtime_manager
from app.modules.health_isf.service_categories import (
    ensure_active_service_category,
    serialize_service_category,
    service_category_status,
)
from app.modules.health_isf.workflow_extensions import get_workflow_extension_registry
from app.modules.health_isf.authorization_adapter import evaluate_customer_request_authorization
from app.observability import increment as increment_metric

logger = logging.getLogger("amicor.health_isf.routes")


def _ride_response_with_financials(db: Session, ride: HealthISFRide) -> RideResponse:
    payload = RideResponse.model_validate(ride).model_dump()
    if ride.driver_id:
        driver = service.get_driver_by_id(db, str(ride.driver_id))
        if driver:
            payload["driver_name"] = str(getattr(driver, "name", None) or "")
    financial = TripFinancialEngine.get_ride_financial_summary(db, ride_id=ride.id)
    if financial:
        payload["fare_amount"] = financial.get("fare_amount")
        payload["total_amount"] = financial.get("total_amount")
        payload["driver_pay_usd"] = financial.get("driver_pay_usd")
        payload["platform_revenue_usd"] = financial.get("platform_revenue_usd")
        payload["financial_record_id"] = financial.get("financial_record_id")
    return RideResponse(**payload)


require_health_isf_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_ANALYTICS_READONLY,
)

_DRIVER_SESSION_ROUTE_PREFIXES = (
    "/api/health-isf/drivers/",
    "/api/health-isf/rides/",
)

_HEALTH_ISF_ACCESS_ROLES = {
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_DRIVER,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_ANALYTICS_READONLY,
}


def require_health_isf_or_driver_session(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """Allow driver mobile session header on driver/ride handoff paths without platform JWT."""
    driver_session = (
        request.headers.get("X-Driver-Session-Token")
        or request.headers.get("x-driver-session-token")
        or ""
    ).strip()
    path = request.url.path
    if driver_session:
        if path.startswith("/api/health-isf/drivers/"):
            return None
        if path.startswith("/api/health-isf/rides/") and path.endswith("/completion-handoff"):
            return None

    if not creds:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.db.models import User as UserModel

    payload = _jwt_verify(creds.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing subject")
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive user")
    session_role = resolve_session_role(user, payload)
    authorized = get_user_authorized_roles(user)
    token_role = normalize_role(payload.get("role"))
    if token_role not in authorized or session_role not in authorized:
        raise HTTPException(status_code=403, detail="Invalid session role")
    if session_role not in _HEALTH_ISF_ACCESS_ROLES:
        raise HTTPException(status_code=403, detail="Insufficient role permissions")
    return user

require_health_isf_write_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
)
require_dispatcher_workflow_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_SUPERVISOR,
    ROLE_DISPATCHER,
)
require_driver_workflow_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_DRIVER,
)


def _build_session_authority(user: UserContext, token_payload: dict[str, Any]) -> dict[str, Any]:
    role = str(user.role or ROLE_STAFF)
    expires_at = token_payload.get("exp")
    expires_in_seconds: int | None = None
    if isinstance(expires_at, (int, float)):
        expires_in_seconds = max(0, int(expires_at - datetime.now(timezone.utc).timestamp()))

    scopes_by_role = {
        ROLE_ADMIN: ["enterprise.admin", "enterprise.dispatch", "enterprise.analytics", "enterprise.workflow"],
        ROLE_SUPER_ADMIN_SUPPORT: ["enterprise.support", "enterprise.dispatch", "enterprise.analytics", "enterprise.workflow"],
        ROLE_DISPATCHER: ["enterprise.dispatch", "enterprise.workflow", "enterprise.operations"],
        ROLE_STAFF: ["enterprise.operations", "enterprise.read"],
        ROLE_SUPERVISOR: ["enterprise.operations", "enterprise.workflow", "enterprise.read"],
        ROLE_ANALYTICS_READONLY: ["enterprise.analytics", "enterprise.read"],
        ROLE_DRIVER: ["enterprise.driver"],
        ROLE_PROVIDER: ["enterprise.provider"],
    }

    return {
        "user_id": user.user_id,
        "organization_id": user.organization_id,
        "role": role,
        "scopes": scopes_by_role.get(role, ["enterprise.read"]),
        "token_expires_at": expires_at,
        "token_expires_in_seconds": expires_in_seconds,
        "websocket_auth_continuity": {
            "refresh_required": bool(expires_in_seconds is not None and expires_in_seconds < 300),
            "refresh_window_seconds": 300,
            "accepted_message_type": "auth_refresh",
        },
    }


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return None


def _as_utc_datetime(value: datetime | str | None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        parsed = _parse_iso_timestamp(value)
        if parsed is not None:
            return parsed
    return now()


def _safe_json_load(payload: str | None, fallback: Any) -> Any:
    if not payload:
        return fallback
    try:
        parsed = json.loads(payload)
    except Exception:
        return fallback
    return parsed


def _normalize_replay_event_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    normalized: list[tuple[int, int, dict[str, Any]]] = []
    for index, item in enumerate(rows):
        if not isinstance(item, dict):
            continue
        sequence_value = item.get("sequence")
        try:
            sequence = int(sequence_value if sequence_value is not None else index + 1)
        except Exception:
            sequence = index + 1
        normalized.append(
            (
                sequence,
                index,
                {
                    "sequence": sequence,
                    "event_type": str(item.get("event_type") or "unknown"),
                    "emitted_at": _as_utc_datetime(item.get("emitted_at") or now()).isoformat(),
                    "payload": item.get("payload") if isinstance(item.get("payload"), dict) else {},
                    "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
                    "role_scope": list(item.get("role_scope") or []),
                },
            )
        )
    normalized.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in normalized]


def _normalize_runtime_replay_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    events = _normalize_replay_event_rows(payload.get("events"))
    monotonic = all(events[idx]["sequence"] >= events[idx - 1]["sequence"] for idx in range(1, len(events)))
    return {
        **payload,
        "events": events,
        "replay_safe": bool(payload.get("replay_safe", True)),
        "sequence_monotonic": bool(payload.get("sequence_monotonic", monotonic)),
        "hydration_safe": True,
        "backend_authoritative": True,
    }


_ALLOWED_OPERATIONAL_STATES = {
    "operational",
    "degraded",
    "fallback",
    "replay_recovery",
    "read_only",
    "unavailable",
}


def _normalize_operational_state(raw_state: Any) -> str:
    state = str(raw_state or "").strip().lower()
    if state in {"operational", "healthy", "stable", "active", "ok"}:
        return "operational"
    if state in {"degraded", "watch", "synchronization_risk"}:
        return "degraded"
    if state in {"critical", "unhealthy", "error", "fallback", "fail_safe", "safe_mode"}:
        return "fallback"
    if state in {"replay_repair", "recovering", "replay_recovery", "repairing"}:
        return "replay_recovery"
    if state in {"read_only", "advisory"}:
        return "read_only"
    if state in {"unavailable", "offline", "unknown", "", "none", "null"}:
        return "unavailable"
    return "fallback"


def _build_continuity_safe_module_summary(
    *,
    subsystem: str,
    raw_state: Any,
    degraded_reasons: list[str],
    dispatch_continuity_safe: bool,
    ride_operations_active: bool,
) -> dict[str, Any]:
    normalized_state = _normalize_operational_state(raw_state)
    dispatch_message = "Dispatch continuity remains protected."
    ride_message = "Ride operations remain active."

    if normalized_state in {"fallback", "unavailable"}:
        dispatch_message = (
            "Core dispatch continuity remains protected while this subsystem is running in reduced mode."
            if dispatch_continuity_safe
            else "Dispatch continuity is currently constrained by runtime pressure."
        )
        ride_message = (
            "Ride operations remain active with guarded behavior."
            if ride_operations_active
            else "Ride operations are constrained and require active supervision."
        )
    elif normalized_state in {"degraded", "replay_recovery"}:
        dispatch_message = "Dispatch continuity is active with monitored degradation safeguards."
        ride_message = "Ride operations remain active with replay-safe supervision controls."
    elif normalized_state == "read_only":
        dispatch_message = "Dispatch continuity remains protected under read-only governance controls."
        ride_message = "Ride operations remain active while governance remains advisory/read-only."

    return {
        "affected_subsystem": subsystem,
        "raw_state": str(raw_state or "unknown"),
        "state": normalized_state,
        "degraded_reasons": list(degraded_reasons or []),
        "dispatch_continuity_safe": {
            "value": bool(dispatch_continuity_safe),
            "message": dispatch_message,
        },
        "ride_operations_active": {
            "value": bool(ride_operations_active),
            "message": ride_message,
        },
    }


def _build_supervisor_operational_visibility(
    db: Session,
    *,
    organization_id: str,
    generated_at: datetime,
    limit: int,
) -> dict[str, Any]:
    safe_limit = max(20, min(300, int(limit or 200)))
    active_assignments = list(service.get_dispatch_active_assignments(db, organization_id=organization_id, limit=safe_limit) or [])
    dispatch_queue = list(service.get_dispatch_queue(db, organization_id=organization_id, limit=safe_limit) or [])
    alert_snapshot = service.get_admin_dispatch_alerts_data(db, organization_id=organization_id)
    alert_rows = list(alert_snapshot.get("alerts") or []) if isinstance(alert_snapshot, dict) else []

    stale_dispatch_queue: list[dict[str, Any]] = []
    for row in dispatch_queue:
        if not isinstance(row, dict):
            continue
        assignment_state = str(row.get("assignment_state") or "queued").lower()
        requested_at = row.get("requested_at")
        expires_at = row.get("offer_expires_at")
        is_stale = False
        if expires_at and _as_utc_datetime(expires_at) <= generated_at:
            is_stale = True
        elif assignment_state in {"queued", "reassignment_pending", "expired", "rejected"} and requested_at:
            is_stale = (_as_utc_datetime(generated_at) - _as_utc_datetime(requested_at)).total_seconds() >= 900
        if is_stale:
            stale_dispatch_queue.append(row)

    reassignment_chain_index: dict[str, dict[str, Any]] = {}
    for row in [*active_assignments, *dispatch_queue]:
        if not isinstance(row, dict):
            continue
        chain_id = str(row.get("reassignment_chain_id") or "").strip()
        if not chain_id:
            continue
        item = reassignment_chain_index.setdefault(
            chain_id,
            {
                "reassignment_chain_id": chain_id,
                "assignment_count": 0,
                "ride_ids": set(),
                "driver_ids": set(),
                "latest_transition_at": None,
            },
        )
        item["assignment_count"] = int(item["assignment_count"] or 0) + 1
        if row.get("ride_id"):
            item["ride_ids"].add(str(row.get("ride_id")))
        if row.get("driver_id"):
            item["driver_ids"].add(str(row.get("driver_id")))
        latest_transition = row.get("reassignment_pending_at") or row.get("accepted_at") or row.get("assigned_at") or row.get("queued_at")
        if latest_transition and (
            item["latest_transition_at"] is None
            or _as_utc_datetime(latest_transition) > _as_utc_datetime(item["latest_transition_at"])
        ):
            item["latest_transition_at"] = latest_transition

    reassignment_chains = [
        {
            "reassignment_chain_id": chain_id,
            "assignment_count": int(row.get("assignment_count") or 0),
            "ride_ids": sorted(list(row.get("ride_ids") or [])),
            "driver_ids": sorted(list(row.get("driver_ids") or [])),
            "latest_transition_at": _as_utc_datetime(row.get("latest_transition_at") or generated_at),
        }
        for chain_id, row in reassignment_chain_index.items()
    ]
    reassignment_chains.sort(key=lambda row: _as_utc_datetime(row.get("latest_transition_at")), reverse=True)

    escalation_rows = (
        db.query(HealthISFWorkflowEscalation)
        .filter(HealthISFWorkflowEscalation.organization_id == organization_id)
        .order_by(HealthISFWorkflowEscalation.created_at.desc())
        .limit(safe_limit)
        .all()
    )
    escalation_history: list[dict[str, Any]] = []
    for row in escalation_rows:
        level = int(getattr(row, "escalation_level", 0) or 0)
        status = str(getattr(row, "status", "queued") or "queued").lower()
        severity = "critical" if level >= 3 else "high" if level >= 2 else "warn"
        if status in {"resolved", "dismissed"}:
            severity = "info"
        escalation_history.append(
            {
                "id": str(row.id),
                "incident_id": str(row.incident_id),
                "ride_id": str(getattr(row.incident, "ride_id", "") or "") or None,
                "target_role": str(row.target_role or "operations"),
                "target_queue": str(row.target_queue or "dispatch"),
                "status": status,
                "escalation_level": level,
                "severity": severity,
                "summary": str(row.summary or ""),
                "created_at": _as_utc_datetime(row.created_at),
                "resolved_at": _as_utc_datetime(row.resolved_at) if row.resolved_at else None,
            }
        )

    orphaned_states = [
        row for row in alert_rows
        if isinstance(row, dict)
        and str(row.get("alert_type") or "") in {"orphaned_ride", "accepted_without_dispatch_continuity"}
    ]

    return {
        "read_only": True,
        "active_assignments": active_assignments,
        "reassignment_chains": reassignment_chains,
        "escalation_history": escalation_history,
        "orphaned_ride_states": orphaned_states,
        "stale_dispatch_queues": stale_dispatch_queue,
        "generated_at": _as_utc_datetime(generated_at),
        "hydration_safe": True,
    }


def _serialize_driver_application(app: Any) -> DriverApplicationResponse:
    categories = _safe_json_load(getattr(app, "preferred_service_categories", None), [])
    if not isinstance(categories, list):
        categories = []
    availability = _safe_json_load(getattr(app, "availability_json", None), None)
    if availability is not None and not isinstance(availability, dict):
        availability = None
    return DriverApplicationResponse(
        id=app.id,
        organization_id=app.organization_id,
        applicant_name=app.applicant_name,
        applicant_phone=app.applicant_phone,
        applicant_email=app.applicant_email,
        license_number=app.license_number,
        insurance_policy_number=app.insurance_policy_number,
        vehicle_make=app.vehicle_make,
        vehicle_model=app.vehicle_model,
        vehicle_year=app.vehicle_year,
        vehicle_plate=app.vehicle_plate,
        vehicle_color=app.vehicle_color,
        availability_summary=app.availability_summary,
        availability=availability,
        preferred_service_categories=[str(item) for item in categories if str(item).strip()],
        background_check_authorized=bool(app.background_check_authorized),
        license_document_ref=app.license_document_ref,
        insurance_document_ref=app.insurance_document_ref,
        registration_document_ref=app.registration_document_ref,
        onboarding_status=str(app.onboarding_status),
        review_notes=app.review_notes,
        reviewed_by_user_id=app.reviewed_by_user_id,
        reviewed_at=app.reviewed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


def _serialize_customer_request(row: Any) -> CustomerRideRequestResponse:
    recurring_pattern = _safe_json_load(getattr(row, "recurring_pattern_json", None), None)
    if recurring_pattern is not None and not isinstance(recurring_pattern, dict):
        recurring_pattern = None
    return CustomerRideRequestResponse(
        id=row.id,
        organization_id=row.organization_id,
        ride_id=row.ride_id,
        rider_name=row.rider_name,
        rider_phone=row.rider_phone,
        pickup_address=row.pickup_address,
        dropoff_address=row.dropoff_address,
        scheduled_time=row.scheduled_time,
        ride_type=row.ride_type,
        recurring=bool(row.is_recurring),
        recurring_pattern=recurring_pattern,
        notes=row.notes,
        dispatch_status=row.dispatch_status,
        pending_at=row.pending_at,
        broadcasted_at=row.broadcasted_at,
        accepted_at=row.accepted_at,
        assigned_at=row.assigned_at,
        in_progress_at=row.in_progress_at,
        completed_at=row.completed_at,
        cancelled_at=row.cancelled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _assert_request_dispatch_authorized(
    request_row: Any,
    *,
    allowed_statuses: set[str],
    operation: str,
) -> None:
    current_status = str(getattr(request_row, "dispatch_status", "") or "").lower()
    if current_status not in allowed_statuses:
        allowed = ", ".join(sorted(allowed_statuses))
        raise HTTPException(
            status_code=409,
            detail=(
                f"{operation} requires an authorized request status. "
                f"Current status '{current_status}' is not dispatch-authorized. Allowed: {allowed}."
            ),
        )


def _serialize_recurring_schedule(
    row: HealthISFRecurringRideSchedule,
    *,
    generated_ride_count: int,
) -> RecurringScheduleResponse:
    weekdays_payload = _safe_json_load(getattr(row, "weekday_mask_json", None), {})
    weekdays_raw = list((weekdays_payload or {}).get("weekdays") or [])
    weekdays = [int(item) for item in weekdays_raw if str(item).isdigit()]
    return RecurringScheduleResponse(
        id=row.id,
        organization_id=row.organization_id,
        provider_id=row.provider_id,
        passenger_name=row.passenger_name,
        passenger_phone=row.passenger_phone,
        pickup_address=row.pickup_address,
        dropoff_address=row.dropoff_address,
        service_type=row.service_type,
        pickup_time_local=row.pickup_time_local,
        frequency=row.frequency,
        interval_count=int(row.interval_count or 1),
        weekdays=weekdays,
        start_date=row.start_date,
        end_date=row.end_date,
        is_active=bool(row.is_active),
        last_generated_at=row.last_generated_at,
        generated_until=row.generated_until,
        created_at=row.created_at,
        updated_at=row.updated_at,
        generated_ride_count=int(generated_ride_count or 0),
    )


def _serialize_dispatch_offer(row: Any) -> DispatchOfferResponse:
    score_breakdown = {}
    raw_breakdown = getattr(row, "score_breakdown_json", None)
    if raw_breakdown:
        try:
            parsed = json.loads(raw_breakdown)
            if isinstance(parsed, dict):
                score_breakdown = parsed
        except Exception:
            score_breakdown = {}
    return DispatchOfferResponse(
        id=row.id,
        offer_id=row.id,
        organization_id=row.organization_id,
        ride_id=row.ride_id,
        driver_id=row.driver_id,
        assignment_state=row.assignment_state,
        attempt_index=int(row.attempt_index or 0),
        score=float(row.score) if row.score is not None else None,
        score_breakdown=score_breakdown,
        timeout_seconds=int(row.timeout_seconds or 90),
        queued_at=row.queued_at,
        search_started_at=row.search_started_at,
        offered_at=row.offered_at,
        offer_expires_at=row.offer_expires_at,
        assigned_at=row.assigned_at,
        accepted_at=row.accepted_at,
        en_route_pickup_at=row.en_route_pickup_at,
        pickup_complete_at=row.pickup_complete_at,
        dropoff_complete_at=row.dropoff_complete_at,
        reassignment_pending_at=row.reassignment_pending_at,
        reassignment_started_at=getattr(row, "reassignment_started_at", None),
        reassignment_completed_at=getattr(row, "reassignment_completed_at", None),
        reassignment_attempt_count=int(getattr(row, "reassignment_attempt_count", 0) or 0),
        reassignment_reason=getattr(row, "reassignment_reason", None),
        reassignment_chain_id=getattr(row, "reassignment_chain_id", None),
        rejected_at=row.rejected_at,
        expired_at=row.expired_at,
        closed_reason=row.closed_reason,
    )


def _serialize_active_assignment(row: Any) -> DispatchActiveAssignmentItemResponse:
    return DispatchActiveAssignmentItemResponse(
        offer_id=str(getattr(row, "id", "") or ""),
        ride_id=str(getattr(row, "ride_id", "") or ""),
        driver_id=getattr(row, "driver_id", None),
        driver_name=getattr(row, "driver_name", None),
        assignment_state=str(getattr(row, "assignment_state", "") or ""),
        attempt_index=int(getattr(row, "attempt_index", 0) or 0),
        offered_at=getattr(row, "offered_at", None),
        offer_expires_at=getattr(row, "offer_expires_at", None),
        assigned_at=getattr(row, "assigned_at", None),
        accepted_at=getattr(row, "accepted_at", None),
        en_route_pickup_at=getattr(row, "en_route_pickup_at", None),
        pickup_complete_at=getattr(row, "pickup_complete_at", None),
        dropoff_complete_at=getattr(row, "dropoff_complete_at", None),
        reassignment_pending_at=getattr(row, "reassignment_pending_at", None),
        reassignment_started_at=getattr(row, "reassignment_started_at", None),
        reassignment_completed_at=getattr(row, "reassignment_completed_at", None),
        reassignment_attempt_count=int(getattr(row, "reassignment_attempt_count", 0) or 0),
        reassignment_reason=getattr(row, "reassignment_reason", None),
        reassignment_chain_id=getattr(row, "reassignment_chain_id", None),
        score=float(getattr(row, "score", 0.0)) if getattr(row, "score", None) is not None else None,
        passenger_name=str(getattr(row, "passenger_name", "") or ""),
        ride_status=str(getattr(row, "ride_status", "") or ""),
        ownership_locked=bool(getattr(row, "ownership_locked", False)),
        ownership_locked_by_user_id=getattr(row, "ownership_locked_by_user_id", None),
        ownership_locked_at=getattr(row, "ownership_locked_at", None),
        ownership_lock_expires_at=getattr(row, "ownership_lock_expires_at", None),
        ownership_is_current_user=getattr(row, "ownership_is_current_user", None),
    )


def _resolve_request_id(request: Request | None) -> str:
    if request:
        return str(
            request.headers.get("x-request-id")
            or request.headers.get("x-correlation-id")
            or f"req_{now().timestamp()}"
        )
    return f"req_{now().timestamp()}"


def _filter_operational_replay_for_connection(
    *,
    replay_events: list[dict[str, Any]],
    connection: WebSocketConnection,
) -> list[dict[str, Any]]:
    connection_role = str(connection.role or "").strip().lower()
    filtered: list[dict[str, Any]] = []
    for event in replay_events:
        role_scope = [str(item).strip().lower() for item in list(event.get("role_scope") or []) if str(item).strip()]
        if role_scope and connection_role not in role_scope and connection_role not in {"admin", "super_admin_support"}:
            continue

        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        ride_id = str(
            event.get("ride_id")
            or (payload.get("ride_id") if isinstance(payload, dict) else "")
            or ""
        ).strip()
        if connection.ride_subscriptions and ride_id and ride_id not in connection.ride_subscriptions:
            continue

        filtered.append(
            {
                "sequence": int(event.get("sequence", 0) or 0),
                "event_id": str(
                    event.get("event_id")
                    or (payload.get("event_id") if isinstance(payload, dict) else "")
                    or f"{event.get('organization_id', '')}:{event.get('sequence', 0)}"
                ),
                "event_type": str(event.get("event_type") or "workflow_transition"),
                "organization_id": str(event.get("organization_id") or ""),
                "ride_id": ride_id or None,
                "role_scope": role_scope,
                "correlation_id": str(
                    event.get("correlation_id")
                    or (payload.get("correlation_id") if isinstance(payload, dict) else "")
                    or f"corr-{event.get('sequence', 0)}"
                ),
                "actor_user_id": str(
                    event.get("actor_user_id")
                    or (payload.get("actor_user_id") if isinstance(payload, dict) else "")
                    or ""
                )
                or None,
                "payload": payload,
                "timestamp": str(event.get("emitted_at") or event.get("timestamp") or now().isoformat()),
                "monotonic_timestamp": int(event.get("sequence", 0) or 0),
            }
        )
    filtered.sort(key=lambda item: int(item.get("sequence", 0) or 0))
    return filtered


async def _emit_dispatch_lifecycle_event(
    *,
    db: Session,
    organization_id: str,
    ride_id: str,
    event_name: str,
    actor_user_id: str | None,
    details: dict[str, Any],
    request_id: str,
    assignment_id: str | None = None,
    driver_id: str | None = None,
    lifecycle_state: str | None = None,
    transition_reason: str | None = None,
    assignment_transition_source: str | None = None,
) -> None:
    emitter = get_emitter()
    runtime_manager = get_live_transport_runtime_manager()
    extension_registry = get_workflow_extension_registry()
    runtime_event_category = extension_registry.categorize_runtime_event(event_name).value
    resolved_service_type = serialize_service_category((details or {}).get("service_type"))
    event_details = {
        **dict(details or {}),
        "ride_id": ride_id,
        "driver_id": driver_id,
        "assignment_id": assignment_id,
        "request_id": request_id,
        "lifecycle_state": lifecycle_state,
        "transition_reason": transition_reason,
        "assignment_transition_source": assignment_transition_source,
        "timestamp": now().isoformat(),
        "service_type": resolved_service_type,
        "runtime_event_category": runtime_event_category,
        "role_visibility_scope": ["admin", "dispatcher", "driver", "provider", "customer"],
    }
    await emitter.emit_dispatch_changed(
        organization_id=organization_id,
        event_name=event_name,
        actor_user_id=actor_user_id,
        details=event_details,
    )
    alias_event = _phase52_dispatch_alias(event_name)
    if alias_event and alias_event != str(event_name or ""):
        await emitter.emit_dispatch_changed(
            organization_id=organization_id,
            event_name=alias_event,
            actor_user_id=actor_user_id,
            details={
                **event_details,
                "phase": "phase52",
                "source_event": str(event_name or ""),
                "alias_event": alias_event,
            },
        )
    runtime_manager.record_lifecycle_event(
        organization_id=organization_id,
        event_name=str(event_name or ""),
        role_scope=["admin", "dispatcher", "driver", "provider", "customer"],
        details=event_details,
    )
    service.record_dispatch_event_emission(
        db,
        ride_id=ride_id,
        event_name=event_name,
        assignment_id=assignment_id,
        driver_id=driver_id,
        request_id=request_id,
        lifecycle_state=lifecycle_state,
        transition_reason=transition_reason,
        websocket_delivery_target="dispatcher_board,workflow_events,ride_updates,driver_dashboard",
        assignment_transition_source=assignment_transition_source,
        actor_user_id=actor_user_id,
    )
    canonical_event = _canonical_lifecycle_event(event_name=event_name) or _normalize_event_token(event_name)
    correlation_id = str(
        event_details.get("correlation_id")
        or request_id
        or f"corr:{organization_id}:{ride_id}:{canonical_event}:{now().timestamp()}"
    )
    OperationalSynchronizationEngine.publish_event(
        organization_id=organization_id,
        event_type=OperationalEventType.WORKFLOW_TRANSITION,
        payload={
            **event_details,
            "event_id": str(event_details.get("event_id") or f"{organization_id}:{ride_id}:{canonical_event}:{request_id}"),
            "event_type": canonical_event,
            "organization_id": organization_id,
            "ride_id": ride_id,
            "driver_id": driver_id,
            "actor_user_id": actor_user_id,
            "correlation_id": correlation_id,
            "role_scope": ["dispatcher", "driver", "rider", "operations", "admin"],
        },
        role_scope=["dispatcher", "driver", "rider", "operations", "admin"],
        source_nonce=f"lifecycle_bus:{organization_id}:{ride_id}:{canonical_event}:{request_id}",
        metadata={
            "source": "dispatch_lifecycle",
            "request_id": request_id,
            "assignment_id": assignment_id,
            "transition_reason": transition_reason,
            "assignment_transition_source": assignment_transition_source,
        },
    )
    db.commit()


def _sync_driver_progress_action(db: Session, ride_id: str, action):
    """Run a driver lifecycle mutation; surface conflicts instead of silent no-ops."""
    ride_before = service.get_ride_by_id(db, ride_id)
    before_state = ""
    if ride_before:
        before_state = RideLifecycleManager.normalize_state(
            getattr(ride_before, "lifecycle_state", None) or ride_before.status
        )
    try:
        ride = action()
    except service.RideLifecycleConflictError as exc:
        ride_after = service.get_ride_by_id(db, ride_id)
        after_state = ""
        if ride_after:
            after_state = RideLifecycleManager.normalize_state(
                getattr(ride_after, "lifecycle_state", None) or ride_after.status
            )
        if not ride_after or after_state == before_state:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ride_after
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    return ride


def _effective_driver_id_from_auth(driver_id: str, auth: DriverEndpointAuth) -> str:
    if auth.actor_user_id is None:
        return str(auth.user.user_id)
    return driver_id


async def _emit_driver_trip_completion_events(
    *,
    db: Session,
    ride: Any,
    driver_id: str,
    actor_user_id: str | None,
    previous_driver_status: str | None = None,
    source: str = "driver_dropoff_complete",
) -> None:
    emitter = get_emitter()
    organization_id = str(ride.organization_id)
    ride_id = str(ride.id)
    await emitter.emit_ride_completed(
        organization_id=organization_id,
        ride_id=ride_id,
        driver_id=driver_id,
        actor_user_id=actor_user_id,
    )
    await emitter.emit_driver_active_ride_state(
        organization_id=organization_id,
        driver_id=driver_id,
        active_ride_id=None,
        state=RideStatus.COMPLETED.value,
        actor_user_id=actor_user_id,
        details={"source": source},
    )
    await emitter.emit_driver_status_changed(
        organization_id=organization_id,
        driver_id=driver_id,
        from_status=previous_driver_status,
        to_status=DriverStatus.AVAILABLE.value,
        actor_user_id=actor_user_id,
        details={"source": source, "ride_id": ride_id},
    )
    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=organization_id,
        ride_id=ride_id,
        event_name="assignment-completed",
        actor_user_id=actor_user_id,
        details={"ride_id": ride_id, "driver_id": driver_id, "source": source},
        request_id=f"driver_complete_{ride_id}",
        driver_id=driver_id,
        lifecycle_state=RideStatus.COMPLETED.value,
        transition_reason="dropoff_complete",
        assignment_transition_source=source,
    )
    await emitter.emit_dispatch_changed(
        organization_id=organization_id,
        event_name="ride-completed",
        actor_user_id=actor_user_id,
        details={"ride_id": ride_id, "driver_id": driver_id, "source": source},
    )
    await emitter.emit_dispatch_changed(
        organization_id=organization_id,
        event_name="trip-completed",
        actor_user_id=actor_user_id,
        details={"ride_id": ride_id, "driver_id": driver_id, "source": source},
    )


async def _emit_intake_dispatch_outcome(
    *,
    db: Session,
    organization_id: str,
    ride: Any,
    actor_user_id: str | None,
    request_id: str | None = None,
) -> None:
    """Emit realtime dispatch events after intake automation completes."""
    db.refresh(ride)
    latest_assignment = (
        db.query(HealthISFDispatchAssignment)
        .filter(HealthISFDispatchAssignment.ride_id == ride.id)
        .order_by(desc(HealthISFDispatchAssignment.created_at))
        .first()
    )
    emitter = get_emitter()
    if ride.driver_id and latest_assignment and str(latest_assignment.assignment_state) == DispatchAssignmentState.OFFERED.value:
        selected_driver = service.get_driver_by_id(db, ride.driver_id)
        auto_assign_payload = {
            "ride_id": ride.id,
            "assignment_state": str(latest_assignment.assignment_state),
            "selected_driver_id": ride.driver_id,
            "selected_driver_name": getattr(selected_driver, "name", None),
            "selected_score": float(latest_assignment.score) if latest_assignment.score is not None else None,
            "organization_id": organization_id,
            "source": "intake_auto_dispatch",
            "request_id": request_id,
        }
        await _emit_with_retry_queue(
            db=db,
            organization_id=organization_id,
            event_type="dispatch_intake_auto_assigned",
            event_payload=auto_assign_payload,
            emit_callable=lambda: emitter.emit_dispatch_changed(
                organization_id=organization_id,
                event_name="dispatch_intake_auto_assigned",
                actor_user_id=actor_user_id,
                details=auto_assign_payload,
            ),
            idempotency_key=_event_key("dispatch_intake_auto_assigned", ride.id, str(latest_assignment.id)),
            ride_id=ride.id,
        )
        await _emit_with_retry_queue(
            db=db,
            organization_id=organization_id,
            event_type="ride_assigned",
            event_payload={
                "ride_id": ride.id,
                "driver_id": ride.driver_id,
                "driver_name": getattr(selected_driver, "name", None),
                "organization_id": organization_id,
                "source": "intake_auto_dispatch",
                "request_id": request_id,
            },
            emit_callable=lambda: emitter.emit_ride_assigned(
                organization_id=organization_id,
                ride_id=ride.id,
                driver_id=str(ride.driver_id),
                driver_name=getattr(selected_driver, "name", None),
                actor_user_id=actor_user_id,
                details={"source": "intake_auto_dispatch", "request_id": request_id},
            ),
            idempotency_key=_event_key("ride_assigned", ride.id, str(ride.driver_id), "intake_auto_dispatch"),
            ride_id=ride.id,
        )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=organization_id,
            ride_id=ride.id,
            event_name="driver-offer-issued",
            actor_user_id=actor_user_id,
            details={
                "request_id": request_id,
                "ride_id": ride.id,
                "offer_id": latest_assignment.id,
                "driver_id": ride.driver_id,
                "source": "intake_auto_dispatch",
            },
            request_id=request_id or f"intake_offer_{ride.id}",
            assignment_id=latest_assignment.id,
            driver_id=str(ride.driver_id),
            lifecycle_state=str(latest_assignment.assignment_state),
            transition_reason="intake_auto_dispatch",
            assignment_transition_source="customer_request_intake",
        )
        log_operational_event(
            "dispatch.intake.auto_assigned",
            organization_id=organization_id,
            ride_id=ride.id,
            selected_driver_id=ride.driver_id,
            selected_score=latest_assignment.score,
        )
    elif (
        latest_assignment
        and str(latest_assignment.assignment_state) == DispatchAssignmentState.AWAITING_APPROVAL.value
    ):
        selected_driver = (
            service.get_driver_by_id(db, latest_assignment.driver_id)
            if latest_assignment.driver_id
            else None
        )
        recommendation_payload = {
            "ride_id": ride.id,
            "assignment_state": str(latest_assignment.assignment_state),
            "recommended_driver_id": latest_assignment.driver_id,
            "recommended_driver_name": getattr(selected_driver, "name", None),
            "recommended_score": float(latest_assignment.score) if latest_assignment.score is not None else None,
            "organization_id": organization_id,
            "request_id": request_id,
        }
        await _emit_with_retry_queue(
            db=db,
            organization_id=organization_id,
            event_type="dispatch_recommendation_created",
            event_payload=recommendation_payload,
            emit_callable=lambda: emitter.emit_dispatch_changed(
                organization_id=organization_id,
                event_name="dispatch_recommendation_created",
                actor_user_id=actor_user_id,
                details=recommendation_payload,
            ),
            idempotency_key=_event_key("dispatch_recommendation_created", ride.id, str(latest_assignment.id)),
            ride_id=ride.id,
        )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=organization_id,
            ride_id=ride.id,
            event_name="dispatch-recommendation-created",
            actor_user_id=actor_user_id,
            details=recommendation_payload,
            request_id=request_id or f"intake_recommendation_{ride.id}",
            assignment_id=latest_assignment.id,
            driver_id=str(latest_assignment.driver_id) if latest_assignment.driver_id else None,
            lifecycle_state=str(latest_assignment.assignment_state),
            transition_reason="intake_ai_recommendation",
            assignment_transition_source="customer_request_intake",
        )
        log_operational_event(
            "dispatch.recommendation.created",
            organization_id=organization_id,
            ride_id=ride.id,
            recommended_driver_id=latest_assignment.driver_id,
            recommended_score=latest_assignment.score,
        )


async def _run_customer_request_side_effects(
    *,
    organization_id: str,
    request_id: str,
    ride_id: str,
    rider_phone: str,
    actor_user_id: str | None,
    idempotency_key: str,
    auth_decision_status: str,
    auth_decision_reason: str,
    auth_decision_source: str,
    ride_type: str,
    scheduled_time_iso: str | None,
    dispatch_status: str,
    passenger_name: str,
    priority_score: float,
    priority_tag: str,
    provider_id: str | None,
) -> None:
    """Emit intake events and optional SMS without blocking the create response."""
    import time

    from app.modules.health_isf.rider_request_timing_log import record_rider_request_timing

    intake_started = time.perf_counter()
    await asyncio.to_thread(
        _run_customer_request_intake_dispatch_sync,
        organization_id=organization_id,
        request_id=request_id,
        ride_id=ride_id,
        actor_user_id=actor_user_id,
        idempotency_key=idempotency_key,
    )
    record_rider_request_timing(
        stage="background_intake_dispatch_total",
        duration_ms=int((time.perf_counter() - intake_started) * 1000),
        idempotency_key=idempotency_key or None,
        ride_id=ride_id,
        request_id=request_id,
        organization_id=organization_id,
    )

    db = SessionLocal()
    try:
        request_row = service.get_customer_ride_request_by_id(db, request_id)
        ride = service.get_ride_by_id(db, ride_id)
        if not request_row or not ride:
            logger.warning(
                "Customer request side effects skipped: missing rows request_id=%s ride_id=%s",
                request_id,
                ride_id,
            )
            return
        try:
            emitter = get_emitter()
            await _emit_with_retry_queue(
                db=db,
                organization_id=organization_id,
                event_type="customer_ride_requested",
                event_payload={
                    "request_id": request_row.id,
                    "ride_id": ride.id,
                    "ride_type": ride_type,
                    "scheduled_time": scheduled_time_iso,
                    "dispatch_status": dispatch_status,
                    "authorization_status": auth_decision_status,
                    "authorization_reason": auth_decision_reason,
                    "authorization_source": auth_decision_source,
                },
                emit_callable=lambda: emitter.emit_ride_created(
                    organization_id=organization_id,
                    ride_id=ride.id,
                    passenger_name=passenger_name,
                    priority_score=priority_score,
                    priority_tag=priority_tag,
                    actor_user_id=actor_user_id,
                    details={
                        "source": "customer_request",
                        "request_id": request_row.id,
                        "ride_type": ride_type,
                        "authorization_status": auth_decision_status,
                        "authorization_source": auth_decision_source,
                    },
                ),
                idempotency_key=_event_key("customer_request_created", request_row.id, ride.id),
                ride_id=ride.id,
            )

            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=organization_id,
                ride_id=ride.id,
                event_name="ride-created",
                actor_user_id=actor_user_id,
                details={
                    "request_id": request_row.id,
                    "ride_id": ride.id,
                    "rider_name": request_row.rider_name,
                    "ride_type": ride_type,
                },
                request_id=idempotency_key or f"customer_request_{request_row.id}",
                lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
                transition_reason="customer_request_created",
                assignment_transition_source="customer_workspace",
            )

            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=organization_id,
                ride_id=ride.id,
                event_name="provider-request-created",
                actor_user_id=actor_user_id,
                details={
                    "provider_id": provider_id,
                    "request_id": request_row.id,
                    "ride_id": ride.id,
                },
                request_id=idempotency_key or f"provider_request_{request_row.id}",
                lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
                transition_reason="provider_request_created",
                assignment_transition_source="customer_workspace",
            )

            db.refresh(ride)
            db.refresh(request_row)
            await _emit_intake_dispatch_outcome(
                db=db,
                organization_id=organization_id,
                ride=ride,
                actor_user_id=actor_user_id,
                request_id=request_row.id,
            )
        except Exception:
            logger.warning(
                "Non-critical customer request side effects failed for request_id=%s ride_id=%s",
                request_row.id,
                ride.id,
                exc_info=True,
            )

        try:
            from app.modules.health_isf import notifications as notify

            base_url = (os.getenv("AMICOR_PUBLIC_URL") or "").strip().rstrip("/")
            if base_url:
                tracking_url = f"{base_url}/app/riders?track={ride.id}"
                notify.send_sms(
                    db,
                    to_phone=rider_phone,
                    message=notify.build_rider_tracking_message(ride_id=ride.id, tracking_url=tracking_url),
                    ride_id=ride.id,
                )
            else:
                logger.warning("AMICOR_PUBLIC_URL not set; skipping rider tracking SMS link")
        except Exception:
            logger.warning("Rider confirmation SMS failed for ride_id=%s", ride.id, exc_info=True)
    finally:
        db.close()


def _run_customer_request_intake_dispatch_sync(
    *,
    organization_id: str,
    request_id: str,
    ride_id: str,
    actor_user_id: str | None,
    idempotency_key: str,
) -> None:
    """Run intake automation in a worker thread so the HTTP event loop stays responsive."""
    import time

    from app.modules.health_isf.rider_request_timing_log import record_rider_request_timing

    db = SessionLocal()
    try:
        request_row = service.get_customer_ride_request_by_id(db, request_id)
        ride = service.get_ride_by_id(db, ride_id)
        if not request_row or not ride:
            record_rider_request_timing(
                stage="background_intake_skipped",
                idempotency_key=idempotency_key or None,
                ride_id=ride_id,
                request_id=request_id,
                organization_id=organization_id,
                error="missing_rows",
            )
            return
        try:
            automation_started = time.perf_counter()
            service.run_intake_dispatch_automation(
                db,
                ride_id=str(ride.id),
                organization_id=organization_id,
                actor_user_id=actor_user_id,
            )
            record_rider_request_timing(
                stage="background_intake_automation",
                duration_ms=int((time.perf_counter() - automation_started) * 1000),
                idempotency_key=idempotency_key or None,
                ride_id=ride_id,
                request_id=request_id,
                organization_id=organization_id,
            )
            db.refresh(ride)
            db.refresh(request_row)
            finalize_started = time.perf_counter()
            service.finalize_customer_request_intake_dispatch(
                db,
                request_obj=request_row,
                actor_user_id=actor_user_id,
            )
            record_rider_request_timing(
                stage="background_finalize_dispatch",
                duration_ms=int((time.perf_counter() - finalize_started) * 1000),
                idempotency_key=idempotency_key or None,
                ride_id=ride_id,
                request_id=request_id,
                organization_id=organization_id,
            )
            db.refresh(ride)
            db.refresh(request_row)
        except Exception as exc:
            record_rider_request_timing(
                stage="background_intake_failed",
                idempotency_key=idempotency_key or None,
                ride_id=ride_id,
                request_id=request_id,
                organization_id=organization_id,
                error=str(exc),
            )
            logger.warning(
                "Deferred intake dispatch automation failed for request_id=%s ride_id=%s",
                request_id,
                ride_id,
                exc_info=True,
            )
    finally:
        db.close()


def _schedule_customer_request_side_effects(**kwargs: Any) -> None:
    def _launch() -> None:
        try:
            asyncio.run(_run_customer_request_side_effects(**kwargs))
        except Exception:
            logger.error(
                "Customer request background side effects failed for request_id=%s ride_id=%s",
                kwargs.get("request_id"),
                kwargs.get("ride_id"),
                exc_info=True,
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        import threading

        threading.Thread(target=_launch, daemon=True, name="customer-request-side-effects").start()
        return

    async def _runner() -> None:
        try:
            await _run_customer_request_side_effects(**kwargs)
        except Exception:
            logger.error(
                "Customer request background side effects failed for request_id=%s ride_id=%s",
                kwargs.get("request_id"),
                kwargs.get("ride_id"),
                exc_info=True,
            )

    try:
        loop.create_task(_runner())
    except RuntimeError:
        import threading

        threading.Thread(target=_launch, daemon=True, name="customer-request-side-effects").start()


def _build_enterprise_dashboard_payload(db: Session, organization_id: str) -> dict[str, Any]:
    snapshot = AIDispatchOrchestrationService.build_operations_snapshot(
        db,
        organization_id=organization_id,
    )
    nova_context = NovaCoreService.get_context(db, organization_id)
    health_summary = nova_context.health_isf_summary.model_dump()
    analytics = snapshot.get("analytics", {})
    metrics = snapshot.get("metrics", {})
    resilience = snapshot.get("resilience", {})
    websocket_stats = resilience.get("websocket", {})
    retry_queue_stats = resilience.get("retry_queue", {})
    health_snapshot = build_health_snapshot(
        db,
        websocket_stats=websocket_stats,
        queue_stats=retry_queue_stats,
    )

    provider_performance = analytics.get("provider_performance", {}) if isinstance(analytics, dict) else {}
    realtime_operational_load = analytics.get("realtime_operational_load", {}) if isinstance(analytics, dict) else {}
    workflow_success_failure_metrics = analytics.get("workflow_success_failure_metrics", {}) if isinstance(analytics, dict) else {}
    emergency_ride_statistics = analytics.get("emergency_ride_statistics", {}) if isinstance(analytics, dict) else {}

    rides = [
        ride for ride in service.get_all_rides(db, skip=0, limit=300)
        if ride.organization_id == organization_id
    ]
    drivers = [
        driver for driver in service.get_all_drivers(db, skip=0, limit=200)
        if driver.organization_id == organization_id
    ]
    providers = [
        provider for provider in service.get_all_providers(db, skip=0, limit=200)
        if provider.organization_id == organization_id
    ]

    ride_status_counts: dict[str, int] = {}
    provider_status_counts: dict[str, int] = {"online": 0, "offline": 0}
    driver_status_counts: dict[str, int] = {}
    provider_load_map: dict[str, dict[str, Any]] = {}
    active_ride_count = 0
    delayed_ride_count = 0
    emergency_ride_count = 0

    for ride in rides:
        status = str(getattr(ride, "status", "unknown") or "unknown").lower()
        ride_status_counts[status] = ride_status_counts.get(status, 0) + 1

        if status in {"accepted", "in_transit"}:
            active_ride_count += 1

        requested_at = getattr(ride, "requested_at", None)
        if requested_at:
            try:
                if (now() - requested_at).total_seconds() > 35 * 60 and status not in {"completed", "cancelled"}:
                    delayed_ride_count += 1
            except Exception:
                pass

        if bool(getattr(ride, "is_emergency", False)):
            emergency_ride_count += 1

        provider_id = str(getattr(ride, "provider_id", "") or "")
        if provider_id:
            bucket = provider_load_map.setdefault(
                provider_id,
                {"provider_id": provider_id, "provider_name": provider_id, "active": 0, "completed": 0, "cancelled": 0},
            )
            if status == "completed":
                bucket["completed"] = int(bucket["completed"]) + 1
            elif status == "cancelled":
                bucket["cancelled"] = int(bucket["cancelled"]) + 1
            else:
                bucket["active"] = int(bucket["active"]) + 1

    for driver in drivers:
        status = str(getattr(driver, "status", "unknown") or "unknown").lower()
        driver_status_counts[status] = driver_status_counts.get(status, 0) + 1

    for provider in providers:
        provider_id = str(getattr(provider, "id", "") or "")
        provider_name = str(getattr(provider, "name", "") or provider_id or "Provider")
        is_online = bool(getattr(provider, "is_active", True))
        provider_status_counts["online" if is_online else "offline"] += 1
        if provider_id:
            bucket = provider_load_map.setdefault(
                provider_id,
                {"provider_id": provider_id, "provider_name": provider_name, "active": 0, "completed": 0, "cancelled": 0},
            )
            bucket["provider_name"] = provider_name

    available_driver_count = driver_status_counts.get("available", 0)
    busy_driver_count = sum(
        count
        for status, count in driver_status_counts.items()
        if status in {"assigned", "busy", "en_route_pickup", "waiting_at_pickup", "in_transit"}
    )
    offline_driver_count = sum(
        count
        for status, count in driver_status_counts.items()
        if status in {"offline", "unavailable"}
    )
    total_driver_count = max(len(drivers), available_driver_count + busy_driver_count + offline_driver_count)
    live_driver_utilization = round((busy_driver_count / max(total_driver_count, 1)) * 100.0, 2)
    dispatch_throughput = int(metrics.get("dispatch_throughput_per_minute") or 0)
    websocket_connections = int(realtime_operational_load.get("websocket_connection_count") or metrics.get("websocket_connection_count") or 0)
    failed_events = int(realtime_operational_load.get("failed_event_count") or metrics.get("failed_event_count") or 0)

    provider_leaders_live = sorted(
        provider_load_map.values(),
        key=lambda item: int(item.get("completed") or 0),
        reverse=True,
    )[:6]

    analytics_payload = dict(analytics) if isinstance(analytics, dict) else {}
    analytics_payload.setdefault(
        "ride_mix",
        {
            "status_counts": ride_status_counts,
            "total_rides": len(rides),
            "emergency_count": emergency_ride_count,
        },
    )
    analytics_payload.setdefault(
        "driver_capacity",
        {
            "total_drivers": total_driver_count,
            "available": available_driver_count,
            "busy": busy_driver_count,
            "offline": offline_driver_count,
            "utilization_percent": live_driver_utilization,
        },
    )
    analytics_payload.setdefault("driver_status", driver_status_counts)
    analytics_payload.setdefault(
        "provider_network",
        {
            "provider_count": len(providers),
            "online": provider_status_counts.get("online", 0),
            "offline": provider_status_counts.get("offline", 0),
        },
    )
    analytics_payload.setdefault(
        "provider_performance",
        {
            "provider_count": len(providers),
            "leaders": provider_leaders_live,
        },
    )
    analytics_payload.setdefault(
        "realtime_operational_load",
        {
            "queue_size": ride_status_counts.get("pending", 0),
            "active_ride_count": active_ride_count,
            "delayed_ride_count": delayed_ride_count,
            "dispatch_throughput_per_minute": dispatch_throughput,
            "driver_utilization_percent": live_driver_utilization,
            "websocket_connection_count": websocket_connections,
            "failed_event_count": failed_events,
        },
    )

    provider_count = int(provider_performance.get("provider_count") or health_summary.get("providers_total") or len(providers) or 0)
    active_rides = int(metrics.get("active_rides") or health_summary.get("rides_in_transit") or 0)
    pending_rides = int(health_summary.get("rides_pending") or 0)
    available_drivers = int(health_summary.get("drivers_available") or 0)
    busy_drivers = max(0, int(health_summary.get("drivers_total") or 0) - available_drivers)
    driver_utilization = float(realtime_operational_load.get("driver_utilization_percent") or metrics.get("driver_utilization_percent") or 0.0)

    workflow_health = str(health_summary.get("workflow_health") or snapshot.get("orchestration", {}).get("system_health", {}).get("status") or "stable")
    dispatch_health = str(health_summary.get("dispatch_health") or health_snapshot.get("status") or "stable")
    enterprise_readiness = str(health_summary.get("enterprise_readiness") or "medium")

    provider_completion_rate = 0.0
    provider_leaders = provider_performance.get("leaders") if isinstance(provider_performance, dict) else []
    if provider_leaders:
        total_completed = sum(int(item.get("completed") or 0) for item in provider_leaders)
        total_cancelled = sum(int(item.get("cancelled") or 0) for item in provider_leaders)
        total_active = sum(int(item.get("active") or 0) for item in provider_leaders)
        denominator = max(total_completed + total_cancelled + total_active, 1)
        provider_completion_rate = round((total_completed / denominator) * 100.0, 2)

    workflow_success_rate = float(workflow_success_failure_metrics.get("success_rate") or 0.0)
    emergency_percentage = float(emergency_ride_statistics.get("emergency_percentage") or 0.0)
    sla_score = round((provider_completion_rate * 0.45) + (workflow_success_rate * 0.35) + (max(0.0, 100.0 - emergency_percentage) * 0.2), 2)
    if sla_score >= 85:
        sla_status = "healthy"
    elif sla_score >= 65:
        sla_status = "watch"
    else:
        sla_status = "critical"

    operational_alerts = snapshot.get("alerts", []) or []
    ai_recommendations = (snapshot.get("recommendations", {}) or {}).get("dispatcher_recommendation_payloads", []) or []

    last_event_at = snapshot.get("event_stream", {}).get("last_event_at")
    freshness_seconds = None
    if isinstance(last_event_at, str) and last_event_at:
        try:
            freshness_seconds = max(0.0, (now() - datetime.fromisoformat(last_event_at)).total_seconds())
        except Exception:
            freshness_seconds = None

    recent_events = RealTimeEventService.get_recent_events(
        db,
        organization_id=organization_id,
        limit=500,
        minutes=15,
    )
    recent_activities, _ = ActivityLogService.get_activity_feed(
        db,
        organization_id=organization_id,
        limit=500,
        skip=0,
    )
    parsed_last_event_at = _parse_iso_timestamp(last_event_at if isinstance(last_event_at, str) else None)
    feed_freshness_seconds = None
    if parsed_last_event_at is not None:
        feed_freshness_seconds = max(0.0, (now() - parsed_last_event_at).total_seconds())

    return {
        "organization_id": organization_id,
        "generated_at": snapshot.get("generated_at") or now().isoformat(),
        "last_synced_at": now().isoformat(),
        "data_age_seconds": freshness_seconds,
        "stale": bool(freshness_seconds is not None and freshness_seconds > 90),
        "dispatch_health": dispatch_health,
        "active_rides": active_rides,
        "pending_rides": pending_rides,
        "available_drivers": available_drivers,
        "providers_online": provider_count,
        "workflow_health": workflow_health,
        "operational_alerts": operational_alerts,
        "ai_recommendations": ai_recommendations,
        "sla_status": {
            "status": sla_status,
            "score": sla_score,
            "provider_completion_rate": provider_completion_rate,
            "workflow_success_rate": round(workflow_success_rate, 2),
            "emergency_percentage": round(emergency_percentage, 2),
        },
        "utilization_metrics": {
            "driver_utilization_percent": round(driver_utilization, 2),
            "dispatch_throughput_per_minute": dispatch_throughput,
            "websocket_connection_count": websocket_connections,
            "failed_event_count": failed_events,
            "busy_drivers": busy_drivers,
            "available_drivers": available_drivers,
            "provider_count": provider_count,
        },
        "enterprise_readiness": enterprise_readiness,
        "health_snapshot": health_snapshot,
        "metrics": metrics,
        "dashboard": snapshot.get("dashboard", {}),
        "analytics": analytics_payload,
        "live_aggregation": {
            "ride_mix": analytics_payload.get("ride_mix", {}),
            "driver_capacity": analytics_payload.get("driver_capacity", {}),
            "driver_status": analytics_payload.get("driver_status", {}),
            "provider_network": analytics_payload.get("provider_network", {}),
            "provider_performance": analytics_payload.get("provider_performance", {}),
            "operational_load": analytics_payload.get("realtime_operational_load", {}),
            "emergency_metrics": analytics_payload.get("emergency_ride_statistics", {}),
            "sla_metrics": {
                "status": sla_status,
                "score": sla_score,
                "provider_completion_rate": provider_completion_rate,
                "workflow_success_rate": workflow_success_rate,
                "emergency_percentage": emergency_percentage,
            },
        },
        "live_feed_status": {
            "is_live": bool(feed_freshness_seconds is None or feed_freshness_seconds <= 90),
            "feed_freshness_seconds": feed_freshness_seconds,
            "events_last_15m": len(recent_events),
            "activities_last_15m": len(recent_activities),
            "last_event_at": snapshot.get("event_stream", {}).get("last_event_at"),
            "last_action_at": snapshot.get("event_stream", {}).get("last_action_at"),
        },
        "telemetry": {
            "websocket": websocket_stats,
            "retry_queue": retry_queue_stats,
            "counters": {
                "dispatch_throughput_per_minute": dispatch_throughput,
                "active_rides": active_rides,
                "pending_rides": pending_rides,
                "available_drivers": available_drivers,
                "failed_event_count": failed_events,
            },
        },
        "summary": health_summary,
        "workflow_status": snapshot.get("orchestration", {}).get("system_health", {}),
        "event_stream": snapshot.get("event_stream", {}),
        "assistant": snapshot.get("assistant", {}),
        "notifications": snapshot.get("notifications", []),
        "timeline": snapshot.get("timeline", []),
        "resilience": resilience,
    }

router = APIRouter(
    prefix="/api/health-isf",
    tags=["health-isf"],
    dependencies=[Depends(require_health_isf_or_driver_session)],
)

public_router = APIRouter(
    prefix="/api/health-isf",
    tags=["health-isf-public"],
)

websocket_router = APIRouter(
    prefix="/api/health-isf",
    tags=["health-isf"],
)


def _event_key(*parts: str) -> str:
    return ":".join(part.strip() for part in parts if part is not None)


def _phase52_dispatch_alias(event_name: str) -> str:
    key = str(event_name or "").strip().lower().replace("-", "_")
    aliases = {
        "ride_created": "ride_created",
        "ride_approved": "ride_approved",
        "customer_request_approved": "ride_approved",
        "assignment_issued": "driver_assigned",
        "driver_offer_issued": "driver_assigned",
        "assignment_accepted": "assignment_accepted",
        "pickup_arrived": "driver_arrived",
        "rider_loaded": "pickup_completed",
        "trip_started": "ride_started",
        "ride_in_progress": "ride_started",
        "trip_progress": "ride_started",
        "assignment_completed": "ride_completed",
        "trip_completed": "ride_completed",
        "ride_completed": "ride_completed",
        "ride_cancelled": "ride_cancelled",
        "provider_delay": "provider_delay",
        "escalation_requested": "escalation_created",
        "ride_escalated": "escalation_created",
        "runtime_reconnected": "runtime_reconnected",
        "admin_override": "admin_override",
    }
    return aliases.get(key, key)


def _normalize_event_token(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def _canonical_lifecycle_event(
    *,
    event_name: str | None = None,
    action: str | None = None,
    to_status: str | None = None,
    from_status: str | None = None,
) -> str | None:
    token = _normalize_event_token(event_name) or _normalize_event_token(action)
    mapping = {
        "ride_created": "request_created",
        "ride_intake_submitted": "request_created",
        "customer_request_created": "request_created",
        "assignment_issued": "assigned",
        "driver_offer_issued": "assigned",
        "ride_assigned": "assigned",
        "assignment_reassigned": "reassigned",
        "reassignment_completed": "reassigned",
        "admin_driver_reassigned": "reassigned",
        "assignment_accepted": "accepted",
        "driver_offer_accepted": "accepted",
        "driver_accepted_ride": "accepted",
        "driver_arrived_pickup": "arrived",
        "pickup_arrived": "arrived",
        "pickup_completed": "onboarded",
        "rider_loaded": "onboarded",
        "ride_in_progress": "onboarded",
        "driver_pickup_complete": "onboarded",
        "assignment_completed": "completed",
        "ride_completed": "completed",
        "trip_completed": "completed",
        "dropoff_completed": "completed",
        "driver_dropoff_complete": "completed",
        "ride_cancelled": "canceled",
        "cancelled": "canceled",
        "assignment_rejected": "rejected",
        "driver_offer_expired": "rejected",
        "ride_escalated": "escalated",
        "escalation_requested": "escalated",
        "supervisor_escalation_hook": "escalated",
    }
    if token in mapping:
        return mapping[token]

    to_token = _normalize_event_token(to_status)
    from_token = _normalize_event_token(from_status)
    if to_token in {"requested", "queued", "pending"} and not from_token:
        return "request_created"
    if to_token == "assigned":
        return "assigned"
    if to_token in {"accepted", "driver_en_route"}:
        return "accepted"
    if to_token == "arrived":
        return "arrived"
    if to_token in {"rider_onboard", "in_progress", "in_transit"}:
        return "onboarded"
    if to_token == "completed":
        return "completed"
    if to_token == "cancelled":
        return "canceled"
    if to_token == "escalated":
        return "escalated"
    if to_token in {"queued", "pending"} and from_token in {"assigned", "accepted", "driver_en_route", "arrived"}:
        return "reassigned"
    return None


def _default_role_scope_for_event(event_type: str) -> list[str]:
    if event_type == "request_created":
        return ["dispatcher", "rider", "operations"]
    return ["dispatcher", "driver", "rider", "operations"]


_LIFECYCLE_ORDER: list[str] = [
    "request_created",
    "assigned",
    "reassigned",
    "accepted",
    "arrived",
    "onboarded",
    "completed",
    "canceled",
    "escalated",
]

_ALLOWED_PREVIOUS_EVENTS: dict[str, set[str]] = {
    "request_created": set(),
    "assigned": {"request_created", "reassigned"},
    "reassigned": {"assigned", "accepted", "arrived"},
    "accepted": {"assigned", "reassigned"},
    "arrived": {"accepted"},
    "onboarded": {"arrived"},
    "completed": {"onboarded"},
    "canceled": {"request_created", "assigned", "reassigned", "accepted", "arrived", "onboarded"},
    "escalated": {"request_created", "assigned", "reassigned", "accepted", "arrived", "onboarded"},
}

_REQUIRED_LIFECYCLE_PAYLOAD_FIELDS: dict[str, set[str]] = {
    "request_created": {"ride_id", "role_scope"},
    "assigned": {"ride_id", "role_scope", "driver_id"},
    "reassigned": {"ride_id", "role_scope"},
    "accepted": {"ride_id", "role_scope", "driver_id"},
    "arrived": {"ride_id", "role_scope", "driver_id"},
    "onboarded": {"ride_id", "role_scope", "driver_id"},
    "completed": {"ride_id", "role_scope", "driver_id"},
    "canceled": {"ride_id", "role_scope", "reason"},
    "escalated": {"ride_id", "role_scope", "reason"},
}


def _latest_canonical_event_for_ride(db: Session, *, organization_id: str, ride_id: str) -> str | None:
    dispatch_rows = (
        db.query(HealthISFDispatchLog)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchLog.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
        .filter(HealthISFDispatchLog.ride_id == ride_id)
        .order_by(HealthISFDispatchLog.created_at.asc())
        .limit(200)
        .all()
    )
    latest_event: str | None = None
    for row in dispatch_rows:
        canonical = _canonical_lifecycle_event(event_name=row.emitted_event_name, action=row.action)
        if canonical:
            latest_event = canonical

    status_rows = (
        db.query(HealthISFRideStatusHistory)
        .join(HealthISFRide, HealthISFRide.id == HealthISFRideStatusHistory.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
        .filter(HealthISFRideStatusHistory.ride_id == ride_id)
        .order_by(HealthISFRideStatusHistory.created_at.asc())
        .limit(200)
        .all()
    )
    for row in status_rows:
        canonical = _canonical_lifecycle_event(to_status=row.to_status, from_status=row.from_status)
        if canonical:
            latest_event = canonical
    return latest_event


def _validate_lifecycle_event_contract(
    *,
    canonical_event: str,
    payload: dict[str, Any],
    previous_event: str | None,
) -> None:
    if canonical_event not in _LIFECYCLE_ORDER:
        raise HTTPException(status_code=400, detail=f"Unsupported lifecycle event type '{canonical_event}'")

    required = _REQUIRED_LIFECYCLE_PAYLOAD_FIELDS.get(canonical_event, {"ride_id", "role_scope"})
    missing = [field for field in sorted(required) if payload.get(field) in (None, "", [])]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required lifecycle payload fields: {', '.join(missing)}")

    allowed_previous = _ALLOWED_PREVIOUS_EVENTS.get(canonical_event, set())
    if previous_event is None:
        if allowed_previous:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid transition: initial lifecycle event cannot be '{canonical_event}'. "
                    "First event must be 'request_created'."
                ),
            )
        return
    if previous_event not in allowed_previous:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid transition: '{previous_event}' -> '{canonical_event}'. "
                f"Allowed previous states: {sorted(allowed_previous)}"
            ),
        )


def _estimate_ride_revenue_usd(ride: HealthISFRide) -> float:
    distance = float(ride.estimated_distance_miles or 0.0)
    duration = float(ride.estimated_duration_minutes or 0.0)
    baseline = 18.0
    variable = (distance * 2.2) + (duration * 0.6)
    return round(max(12.0, baseline + variable), 2)


def _build_operational_lifecycle_timeline(
    *,
    db: Session,
    organization_id: str,
    ride_id: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    timeline_rows: list[dict[str, Any]] = []

    dispatch_query = (
        db.query(HealthISFDispatchLog)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchLog.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
    )
    status_query = (
        db.query(HealthISFRideStatusHistory)
        .join(HealthISFRide, HealthISFRide.id == HealthISFRideStatusHistory.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
    )
    if ride_id:
        dispatch_query = dispatch_query.filter(HealthISFDispatchLog.ride_id == ride_id)
        status_query = status_query.filter(HealthISFRideStatusHistory.ride_id == ride_id)

    dispatch_rows = dispatch_query.order_by(HealthISFDispatchLog.created_at.asc()).limit(limit).all()
    for row in dispatch_rows:
        event_type = _canonical_lifecycle_event(event_name=row.emitted_event_name, action=row.action)
        if not event_type:
            continue
        ts = row.transition_timestamp or row.emitted_timestamp or row.created_at
        payload = {
            "action": row.action,
            "note": row.note,
            "transition_reason": row.transition_reason,
            "assignment_transition_source": row.assignment_transition_source,
            "emitted_event_name": row.emitted_event_name,
            "lifecycle_state": row.lifecycle_state,
        }
        timeline_rows.append(
            {
                "organization_id": organization_id,
                "ride_id": row.ride_id,
                "driver_id": row.driver_id,
                "event_type": event_type,
                "role_scope": _default_role_scope_for_event(event_type),
                "timestamp": ts,
                "source": "dispatch_log",
                "source_id": row.id,
                "payload": payload,
            }
        )

    status_rows = status_query.order_by(HealthISFRideStatusHistory.created_at.asc()).limit(limit).all()
    for row in status_rows:
        event_type = _canonical_lifecycle_event(
            to_status=row.to_status,
            from_status=row.from_status,
        )
        if not event_type:
            continue
        timeline_rows.append(
            {
                "organization_id": organization_id,
                "ride_id": row.ride_id,
                "driver_id": None,
                "event_type": event_type,
                "role_scope": _default_role_scope_for_event(event_type),
                "timestamp": row.created_at,
                "source": "status_history",
                "source_id": row.id,
                "payload": {
                    "from_status": row.from_status,
                    "to_status": row.to_status,
                    "note": row.note,
                    "changed_by_user_id": row.changed_by_user_id,
                },
            }
        )

    timeline_rows.sort(
        key=lambda item: (
            _as_utc_datetime(item.get("timestamp") or now()),
            0 if item.get("source") == "status_history" else 1,
            str(item.get("source_id") or ""),
        )
    )

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(timeline_rows[:limit], start=1):
        ts = _as_utc_datetime(item.get("timestamp") or now()).isoformat()
        event_material = "|".join(
            [
                organization_id,
                str(item.get("ride_id") or ""),
                str(item.get("driver_id") or ""),
                str(item.get("event_type") or ""),
                ts,
                str(item.get("source") or ""),
                str(item.get("source_id") or ""),
            ]
        )
        normalized.append(
            {
                "event_id": hashlib.sha256(event_material.encode("utf-8")).hexdigest()[:20],
                "sequence": idx,
                "organization_id": organization_id,
                "ride_id": item.get("ride_id"),
                "driver_id": item.get("driver_id"),
                "event_type": item.get("event_type"),
                "role_scope": item.get("role_scope") or ["dispatcher", "driver", "rider", "operations"],
                "timestamp": ts,
                "source": item.get("source"),
                "source_id": item.get("source_id"),
                "payload": item.get("payload") or {},
            }
        )

    return normalized


def _build_operational_revenue_kpis(
    *,
    db: Session,
    organization_id: str,
    timeline: list[dict[str, Any]],
    ride_id: str | None,
    window_hours: int,
) -> dict[str, Any]:
    window_hours = max(1, min(int(window_hours), 168))
    now_ts = _as_utc_datetime(now())
    cutoff = now_ts - timedelta(hours=window_hours)

    rides_query = db.query(HealthISFRide).filter(HealthISFRide.organization_id == organization_id)
    if ride_id:
        rides_query = rides_query.filter(HealthISFRide.id == ride_id)
    rides = rides_query.all()
    ride_by_id = {str(ride.id): ride for ride in rides}

    drivers_query = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == organization_id)
    drivers = drivers_query.all()
    total_drivers = len(drivers)
    available_drivers = sum(1 for driver in drivers if str(driver.status) == DriverStatus.AVAILABLE.value)
    busy_drivers = sum(
        1
        for driver in drivers
        if str(driver.status) in {
            DriverStatus.ASSIGNED.value,
            DriverStatus.EN_ROUTE_PICKUP.value,
            DriverStatus.WAITING_AT_PICKUP.value,
            DriverStatus.IN_TRANSIT.value,
            DriverStatus.BUSY.value,
        }
    )

    request_created_by_ride: dict[str, datetime] = {}
    assigned_by_ride: dict[str, datetime] = {}
    completed_trip_ids: set[str] = set()
    cancelled_ride_ids: set[str] = set()

    for event in timeline:
        ride_key = str(event.get("ride_id") or "")
        if not ride_key:
            continue
        event_ts = _as_utc_datetime(_parse_iso_timestamp(str(event.get("timestamp") or "")) or now())
        if event_ts < cutoff:
            continue

        event_type = str(event.get("event_type") or "")
        if event_type == "request_created" and ride_key not in request_created_by_ride:
            request_created_by_ride[ride_key] = event_ts
        if event_type in {"assigned", "accepted"} and ride_key not in assigned_by_ride:
            assigned_by_ride[ride_key] = event_ts
        if event_type == "completed":
            completed_trip_ids.add(ride_key)
        if event_type == "canceled":
            cancelled_ride_ids.add(ride_key)

    assignment_latency_samples: list[float] = []
    for ride_key, created_at in request_created_by_ride.items():
        assigned_at = assigned_by_ride.get(ride_key)
        if assigned_at and assigned_at >= created_at:
            assignment_latency_samples.append((assigned_at - created_at).total_seconds())

    terminal_states = {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}
    active_rides = 0
    pending_rides = 0
    stale_pending = 0
    for ride in rides:
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
        if lifecycle_state in terminal_states:
            continue
        active_rides += 1
        if lifecycle_state in {RideStatus.QUEUED.value, RideStatus.PENDING.value, RideStatus.ASSIGNED.value}:
            pending_rides += 1
            requested_at = _as_utc_datetime(ride.requested_at) if ride.requested_at else now_ts
            if (now_ts - requested_at).total_seconds() > 20 * 60:
                stale_pending += 1

    cancellation_loss = 0.0
    for cancelled_ride_id in cancelled_ride_ids:
        ride = ride_by_id.get(cancelled_ride_id)
        if not ride:
            continue
        cancellation_loss += _estimate_ride_revenue_usd(ride) * 0.75
    cancellation_loss = round(cancellation_loss, 2)

    completed_trips = len(completed_trip_ids)
    assignment_latency_seconds = round(
        (sum(assignment_latency_samples) / len(assignment_latency_samples)) if assignment_latency_samples else 0.0,
        2,
    )
    driver_utilization = round((busy_drivers / max(total_drivers, 1)) * 100.0, 2)
    rides_per_hour = round(completed_trips / float(window_hours), 3)
    dispatcher_load = round((active_rides + (pending_rides * 1.25)) / max(available_drivers, 1), 3)

    sla_alerts: list[dict[str, Any]] = []
    if assignment_latency_seconds > 900:
        sla_alerts.append(
            {
                "severity": "high",
                "code": "assignment_latency_breach",
                "message": "Assignment latency exceeds 15-minute operational SLA.",
                "value": assignment_latency_seconds,
            }
        )
    if stale_pending > 0:
        sla_alerts.append(
            {
                "severity": "high" if stale_pending >= 3 else "medium",
                "code": "stale_pending_dispatch_queue",
                "message": "One or more rides are pending beyond dispatch SLA.",
                "value": stale_pending,
            }
        )
    if dispatcher_load > 1.2:
        sla_alerts.append(
            {
                "severity": "high",
                "code": "dispatcher_overload",
                "message": "Dispatcher load indicates assignment pressure and coordination risk.",
                "value": dispatcher_load,
            }
        )

    return {
        "window_hours": window_hours,
        "completed_trips": completed_trips,
        "cancellation_loss": cancellation_loss,
        "assignment_latency": {
            "seconds": assignment_latency_seconds,
            "sample_count": len(assignment_latency_samples),
        },
        "active_rides": active_rides,
        "driver_utilization": {
            "percent": driver_utilization,
            "busy_drivers": busy_drivers,
            "total_drivers": total_drivers,
        },
        "rides_per_hour": rides_per_hour,
        "dispatcher_load": {
            "index": dispatcher_load,
            "pending_rides": pending_rides,
            "available_drivers": available_drivers,
        },
        "operational_sla_alerts": sla_alerts,
        "derived_from": "runtime_event_history_and_runtime_state",
    }


async def _emit_with_retry_queue(
    db: Session,
    organization_id: str,
    event_type: str,
    event_payload: dict,
    emit_callable,
    idempotency_key: str,
    ride_id: str | None = None,
    driver_id: str | None = None,
) -> None:
    metrics = get_operational_metrics_registry()
    runtime_manager = get_live_transport_runtime_manager()
    if not IdempotencyService.reserve_key(
        db,
        idempotency_key=idempotency_key,
        scope="dispatch_event",
        resource_id=ride_id or driver_id,
    ):
        metrics.increment("dispatch.events.idempotent_skips")
        return

    try:
        await emit_callable()
        alias_event = _phase52_dispatch_alias(event_type)
        if alias_event and alias_event != str(event_type or ""):
            await get_emitter().emit_dispatch_changed(
                organization_id=organization_id,
                event_name=alias_event,
                actor_user_id=None,
                details={
                    **dict(event_payload or {}),
                    "phase": "phase52",
                    "source_event": str(event_type or ""),
                    "alias_event": alias_event,
                    "timestamp": now().isoformat(),
                    "role_visibility_scope": ["admin", "dispatcher", "driver", "provider", "customer"],
                },
            )
        runtime_manager.record_lifecycle_event(
            organization_id=organization_id,
            event_name=str(event_type or ""),
            role_scope=["admin", "dispatcher", "driver", "provider", "customer"],
            details=dict(event_payload or {}),
        )
        metrics.increment("dispatch.events.success")
        metrics.record_event_ts("dispatch_events")
    except Exception as exc:
        metrics.increment("dispatch.events.failed")
        RetryQueueService.enqueue_failed_event(
            db,
            organization_id=organization_id,
            event_type=event_type,
            payload=event_payload,
            error_message=str(exc),
            idempotency_key=idempotency_key,
            ride_id=ride_id,
            driver_id=driver_id,
        )
        log_operational_event(
            "dispatch.event.emit_failed",
            level=logging.ERROR,
            event_type=event_type,
            organization_id=organization_id,
            ride_id=ride_id,
            driver_id=driver_id,
            error=str(exc),
        )


# ── Status Endpoint ───────────────────────────────────────────────────────────

@router.get("/status", response_model=StatusResponse)
def get_status():
    """Health check endpoint for Health ISF module."""
    return StatusResponse(timestamp=now())


@router.get("/operations/workflow-overview")
def get_operational_workflow_overview(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 16 unified orchestration overview (read-only, supervision-safe)."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = build_operational_workflow_overview(db, organization_id=effective_org_id)
    payload.setdefault("safety", {})
    payload["safety"].update(
        {
            "preview_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "automatic_dispatching": False,
            "self_triggering_workflows": False,
            "supervision_gated": True,
            "deny_by_default": True,
        }
    )
    return payload


@router.get("/operations/workflow-events")
def get_operational_workflow_events(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(120, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 16 append-only operational event stream view (read-only)."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = build_workflow_event_stream(
        db,
        organization_id=effective_org_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    payload["safety"] = {
        "preview_only": True,
        "execution_disabled": True,
        "supervision_gated": True,
    }
    return payload


@router.get("/operations/lifecycle-matrix")
def get_lifecycle_matrix() -> dict[str, Any]:
    """Expose deterministic Phase 16 lifecycle transitions for visualization/validation."""
    return {
        "states": list(PHASE16_RIDE_STATES),
        "transitions": {key: list(value) for key, value in PHASE16_RIDE_TRANSITIONS.items()},
        "deterministic": True,
        "immutable_transition_audit": True,
        "preview_only": True,
        "execution_disabled": True,
    }


@router.get("/operations/command-center")
def get_command_center_snapshot(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 17 command center snapshot (read-only, supervision-safe)."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    overview = build_operational_workflow_overview(db, organization_id=effective_org_id)
    alerts = dict(((overview.get("live_operational_telemetry_panels", {}) or {}).get("operational_alerts", {}) or {}))
    alerts.setdefault(
        "supervision_status",
        "attached" if bool((overview.get("governance_integrity", {}) or {}).get("supervision_classifications_attached", True)) else "missing",
    )
    return {
        "organization_id": effective_org_id,
        "command_center": overview,
        "safety": {
            "preview_only": True,
            "execution_disabled": True,
            "autonomous_execution": False,
            "automatic_dispatching": False,
            "self_triggering_workflows": False,
            "supervision_gated": True,
            "deny_by_default": True,
        },
        "alerts": alerts,
        "protected_endpoints": [
            "/api/health-isf/operations/workflow-overview",
            "/api/health-isf/operations/workflow-events",
            "/api/health-isf/operations/lifecycle-matrix",
            "/api/health-isf/operations/command-center",
            "/api/health-isf/operations/timeline",
            "/api/health-isf/operations/map-preview",
            "/api/health-isf/operations/alerts",
        ],
    }


@router.get("/operations/timeline")
def get_command_center_timeline(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(80, ge=1, le=240),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 17 timeline view for workflow and event stream visualization."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return {
        "organization_id": effective_org_id,
        "timeline": build_workflow_event_stream(
            db,
            organization_id=effective_org_id,
            after_sequence=after_sequence,
            limit=limit,
        ),
        "safety": {
            "preview_only": True,
            "execution_disabled": True,
            "supervision_gated": True,
        },
    }


@router.post("/operations/lifecycle-events")
def ingest_persistent_lifecycle_event(
    payload: dict[str, Any] = Body(...),
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Strict typed lifecycle event ingestion with append-only persistence and replay publication."""
    effective_org_id = enforce_tenant_scope(user, organization_id)

    raw_event_type = str(payload.get("event_type") or payload.get("event_name") or "")
    canonical_event = _canonical_lifecycle_event(event_name=raw_event_type)
    if not canonical_event:
        canonical_event = _normalize_event_token(raw_event_type)

    ride_id = str(payload.get("ride_id") or "").strip()
    if not ride_id:
        raise HTTPException(status_code=400, detail="Lifecycle payload requires non-empty ride_id")

    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    role_scope = payload.get("role_scope")
    if not isinstance(role_scope, list) or not role_scope:
        payload["role_scope"] = _default_role_scope_for_event(canonical_event)
    else:
        payload["role_scope"] = [str(item).strip().lower() for item in role_scope if str(item).strip()]
        if not payload["role_scope"]:
            payload["role_scope"] = _default_role_scope_for_event(canonical_event)

    if payload.get("driver_id") in (None, "") and getattr(ride, "driver_id", None):
        payload["driver_id"] = str(ride.driver_id)

    previous_event = _latest_canonical_event_for_ride(db, organization_id=effective_org_id, ride_id=ride_id)
    _validate_lifecycle_event_contract(
        canonical_event=canonical_event,
        payload=payload,
        previous_event=previous_event,
    )

    normalized_timestamp = _as_utc_datetime(payload.get("timestamp") if isinstance(payload.get("timestamp"), str) else None)
    lifecycle_payload = {
        "event_type": canonical_event,
        "ride_id": ride_id,
        "driver_id": payload.get("driver_id"),
        "role_scope": list(payload.get("role_scope") or []),
        "reason": payload.get("reason"),
        "from_status": payload.get("from_status"),
        "to_status": payload.get("to_status"),
        "timestamp": normalized_timestamp.isoformat(),
        "actor_user_id": user.user_id,
    }

    dispatch_log = HealthISFDispatchLog(
        id=str(uuid4()),
        ride_id=ride_id,
        driver_id=str(payload.get("driver_id") or "") or None,
        action=f"lifecycle_{canonical_event}",
        note=str(payload.get("reason") or "lifecycle event persisted"),
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason=str(payload.get("reason") or "contract_ingestion"),
        transition_timestamp=normalized_timestamp,
        emitted_event_name=canonical_event,
        emitted_timestamp=normalized_timestamp,
        assignment_transition_source="operations.lifecycle-events",
        acted_by_user_id=user.user_id,
        request_id=str(payload.get("request_id") or "") or None,
    )
    db.add(dispatch_log)

    to_status = str(payload.get("to_status") or "").strip().lower() or None
    from_status = str(payload.get("from_status") or "").strip().lower() or None
    if to_status:
        status_history = HealthISFRideStatusHistory(
            id=str(uuid4()),
            ride_id=ride_id,
            from_status=from_status,
            to_status=to_status,
            note=str(payload.get("reason") or f"{canonical_event} lifecycle transition"),
            changed_by_user_id=user.user_id,
            created_at=normalized_timestamp,
        )
        db.add(status_history)

    audit_log = HealthISFWorkflowAuditLog(
        id=str(uuid4()),
        organization_id=effective_org_id,
        workflow_execution_id=None,
        incident_id=None,
        escalation_id=None,
        event_type=f"operational.lifecycle.{canonical_event}",
        actor_user_id=user.user_id,
        payload=json.dumps(lifecycle_payload),
    )
    db.add(audit_log)
    db.commit()

    publication = OperationalSynchronizationEngine.publish_event(
        organization_id=effective_org_id,
        event_type=OperationalEventType.WORKFLOW_TRANSITION,
        payload=lifecycle_payload,
        role_scope=list(lifecycle_payload.get("role_scope") or []),
        source_nonce=str(payload.get("source_nonce") or f"lifecycle:{ride_id}:{canonical_event}:{lifecycle_payload['timestamp']}"),
        metadata={
            "contract_enforced": True,
            "timestamp_normalized_utc": True,
            "ordered_transition_checked": True,
            "persistence_backed": True,
        },
    )

    return {
        "organization_id": effective_org_id,
        "ride_id": ride_id,
        "event_type": canonical_event,
        "timestamp": lifecycle_payload["timestamp"],
        "transition_validated": True,
        "persisted": True,
        "audit_chain": {
            "dispatch_log_id": dispatch_log.id,
            "workflow_audit_log_id": audit_log.id,
        },
        "publication": publication,
    }


@router.get("/operations/persistent-recovery")
def get_persistent_operational_recovery(
    organization_id: str | None = Query(None),
    ride_id: str | None = Query(None),
    driver_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(200, ge=20, le=2000),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rebuild cross-role operational runtime state from persistent storage for reconnect/reload recovery."""
    effective_org_id = enforce_tenant_scope(user, organization_id)

    dispatcher_board = build_operational_dashboard(
        db,
        organization_id=effective_org_id,
        include_queue_details=True,
        include_driver_availability=True,
    )
    dispatcher_board = OperationalDashboardResponse(**dispatcher_board).model_dump(mode="json")
    dispatcher_board.setdefault("active_rides", [])
    dispatcher_board.setdefault("pending_rides", [])
    dispatcher_board.setdefault("alerts", [])
    dispatcher_board.setdefault("queue_status", {})
    dispatcher_board.setdefault("driver_availability", {})
    timeline = _build_operational_lifecycle_timeline(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride_id,
        limit=limit,
    )
    replay = _normalize_runtime_replay_payload(OperationalReplayService.replay(
        organization_id=effective_org_id,
        after_sequence=after_sequence,
        role=str(user.role or ROLE_DISPATCHER).lower(),
        limit=min(limit, 500),
    ))
    replay_integrity = OperationalReplayService.replay_integrity(effective_org_id)
    supervisor_operational_visibility = _build_supervisor_operational_visibility(
        db,
        organization_id=effective_org_id,
        generated_at=_as_utc_datetime(now()),
        limit=limit,
    )

    active_rider_ride: dict[str, Any] | None = None
    if ride_id:
        ride = service.get_ride_by_id(db, ride_id)
        if ride:
            enforce_entity_tenant(user, ride.organization_id)
            active_rider_ride = RideResponse.model_validate(ride).model_dump(mode="json")
    else:
        rider_ride = (
            db.query(HealthISFRide)
            .filter(HealthISFRide.organization_id == effective_org_id)
            .order_by(HealthISFRide.updated_at.desc())
            .limit(1)
            .first()
        )
        if rider_ride:
            active_rider_ride = RideResponse.model_validate(rider_ride).model_dump(mode="json")

    driver_workflow_state: dict[str, Any] | None = None
    if driver_id:
        driver = service.get_driver_by_id(db, driver_id)
        if not driver:
            raise HTTPException(status_code=404, detail="Driver not found")
        enforce_entity_tenant(user, driver.organization_id)
        driver_snapshot = service.get_driver_live_workspace_data(
            db,
            organization_id=effective_org_id,
            driver_id=driver_id,
        )
        assignment = driver_snapshot.get("assignment")
        driver_workflow_state = {
            "driver_id": driver_id,
            "reconnect_safe": bool(driver_snapshot.get("reconnect_safe", True)),
            "timeline_states": list(driver_snapshot.get("timeline_states") or []),
            "assignment": {
                "id": str(getattr(assignment, "id", "") or "") or None,
                "ride_id": str(getattr(assignment, "ride_id", "") or "") or None,
                "state": str(getattr(assignment, "assignment_state", "") or "") or None,
            }
            if assignment
            else None,
        }

    return {
        "organization_id": effective_org_id,
        "recovery_source": "persistent_operational_storage",
        "dispatcher_board": dispatcher_board,
        "rider_active_trip_state": active_rider_ride,
        "driver_active_workflow_state": driver_workflow_state,
        "lifecycle_timeline": timeline,
        "event_stream_replay": replay,
        "replay_integrity": replay_integrity,
        "supervisor_operational_visibility": supervisor_operational_visibility,
        "mobile_operational_hydration": {
            "hydration_safe": True,
            "replay_ordering_consistent": bool(replay.get("sequence_monotonic", True)),
            "utc_normalized": True,
            "partial_payload_tolerant": True,
        },
        "synchronization": {
            "rebuild_dispatcher_board_from_persistence": True,
            "rebuild_rider_state_from_persistence": True,
            "rebuild_driver_state_from_persistence": True,
            "replay_lifecycle_timeline": True,
            "append_only_audit_chain": True,
        },
    }


@router.get("/operations/revenue-workflow")
def get_operational_revenue_workflow(
    organization_id: str | None = Query(None),
    ride_id: str | None = Query(None),
    window_hours: int = Query(24, ge=1, le=168),
    limit: int = Query(500, ge=20, le=2000),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Canonical operational revenue workflow contract powered by runtime/event history."""
    effective_org_id = enforce_tenant_scope(user, organization_id)

    if ride_id:
        ride = service.get_ride_by_id(db, ride_id)
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        enforce_entity_tenant(user, ride.organization_id)

    timeline = _build_operational_lifecycle_timeline(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride_id,
        limit=limit,
    )
    kpis = _build_operational_revenue_kpis(
        db=db,
        organization_id=effective_org_id,
        timeline=timeline,
        ride_id=ride_id,
        window_hours=window_hours,
    )
    financial_summary = TripFinancialEngine.get_admin_revenue_summary(db, organization_id=effective_org_id)
    kpis["financial_engine"] = financial_summary
    if ride_id:
        ride_financial = TripFinancialEngine.get_ride_financial_summary(db, ride_id=ride_id)
        if ride_financial:
            kpis["ride_financial"] = ride_financial

    role_streams = {
        "dispatcher": [event for event in timeline if "dispatcher" in list(event.get("role_scope") or [])],
        "driver": [event for event in timeline if "driver" in list(event.get("role_scope") or [])],
        "rider": [event for event in timeline if "rider" in list(event.get("role_scope") or [])],
        "operations": [event for event in timeline if "operations" in list(event.get("role_scope") or [])],
    }

    event_types_present = {str(event.get("event_type") or "") for event in timeline}
    required_events = [
        "request_created",
        "assigned",
        "reassigned",
        "accepted",
        "arrived",
        "onboarded",
        "completed",
        "canceled",
        "escalated",
    ]

    return {
        "organization_id": effective_org_id,
        "ride_id": ride_id,
        "generated_at": now().isoformat(),
        "lifecycle_contract": {
            "version": "v1",
            "source_of_truth": "backend_runtime",
            "required_event_types": required_events,
            "event_types_present": sorted(event_types_present),
            "append_only_timeline": True,
            "replay_safe": True,
        },
        "kpis": kpis,
        "timeline": timeline,
        "role_streams": role_streams,
        "synchronization": {
            "single_contract_for_all_runtimes": True,
            "dispatcher_driver_rider_isolated_views": True,
            "event_ordering_monotonic": True,
            "event_count": len(timeline),
        },
    }


@router.get("/operations/map-preview")
def get_command_center_map_preview(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 17 provider-agnostic geospatial foundation preview."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    overview = build_operational_workflow_overview(db, organization_id=effective_org_id)
    geospatial = build_geospatial_foundation(effective_org_id)
    return {
        "organization_id": effective_org_id,
        "map_preview": geospatial,
        "command_center_summary": {
            "active_workflow_cards": (((overview.get("live_operational_telemetry_panels", {}) or {}).get("active_workflow_cards", 0))),
            "driver_states": overview.get("driver_state_registry", {}).get("states", {}),
            "provider_states": overview.get("provider_state_registry", {}).get("states", {}),
        },
        "safety": {
            "preview_only": True,
            "execution_disabled": True,
            "supervision_gated": True,
            "provider_agnostic": True,
            "routing_engine_enabled": False,
        },
    }


@router.get("/operations/alerts")
def get_command_center_alerts(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Phase 17 operational alerts view (read-only, audit-compatible)."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    overview = build_operational_workflow_overview(db, organization_id=effective_org_id)
    alerts = dict(((overview.get("live_operational_telemetry_panels", {}) or {}).get("operational_alerts", {}) or {}))
    alerts.update(
        {
            "audit_chain_compatible": True,
            "replay_protection": True,
            "websocket_safe": True,
            "preview_only": True,
            "execution_disabled": True,
        }
    )
    return {
        "organization_id": effective_org_id,
        "alerts": alerts,
        "supervision": {
            "status": "attached" if bool((overview.get("governance_integrity", {}) or {}).get("supervision_classifications_attached", True)) else "missing",
            "protected": True,
        },
        "safety": {
            "preview_only": True,
            "execution_disabled": True,
            "supervision_gated": True,
            "deny_by_default": True,
        },
    }


@router.get("/operations/runtime-state")
def get_phase52_runtime_state(
    organization_id: str | None = Query(None),
    include_timeline: bool = Query(True),
    limit: int = Query(120, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
):
    """Phase 52 shared runtime state registry snapshot."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    snapshot = get_live_transport_runtime_manager().runtime_snapshot(
        effective_org_id,
        include_timeline=include_timeline,
        limit=limit,
    )
    snapshot["safety"] = {
        "deterministic_event_ordering": True,
        "reconnect_replay_support": True,
        "append_only_timeline": True,
    }
    return snapshot


@router.get("/operations/runtime-replay")
def get_phase52_runtime_replay(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    user: UserContext = Depends(get_current_user_context),
):
    """Phase 52 deterministic replay stream for lifecycle viewer and reconnect restoration."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return _normalize_runtime_replay_payload(get_live_transport_runtime_manager().replay(
        effective_org_id,
        after_sequence=after_sequence,
        limit=limit,
    ))


@router.get("/operations/preview-runtime-status")
def get_phase54_preview_runtime_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Phase 54 additive preview/runtime visibility snapshot for live developer verification."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    broadcaster = get_broadcaster()
    runtime_manager = get_live_transport_runtime_manager()

    runtime_state = runtime_manager.runtime_snapshot(
        effective_org_id,
        include_timeline=False,
        limit=10,
    )
    replay_probe = runtime_manager.replay(
        effective_org_id,
        after_sequence=max(0, int(runtime_state.get("sequence", 0) or 0) - 25),
        limit=25,
    )
    websocket = broadcaster.get_websocket_health_stats(organization_id=effective_org_id)
    dispatch_queue = service.get_dispatch_queue(db, organization_id=effective_org_id, limit=300)
    active_assignments = service.get_dispatch_active_assignments(db, organization_id=effective_org_id, limit=300)
    active_locks = ConcurrentAssignmentService.list_active_assignment_locks(
        db,
        organization_id=effective_org_id,
        limit=300,
    )
    queue_stats = RetryQueueService.get_queue_stats(db, organization_id=effective_org_id)

    stale_assignments = [
        row for row in dispatch_queue
        if row.get("offer_expires_at") and _as_utc_datetime(row.get("offer_expires_at")) <= _as_utc_datetime(now())
    ]
    reconnect_pressure = int(websocket.get("disconnects_last_5m", 0) or 0) + int(websocket.get("reconnects_last_5m", 0) or 0)
    replay_safe = bool(replay_probe.get("replay_safe", True)) and bool(runtime_state.get("deterministic_event_ordering", True))
    from app.modules.health_isf import notifications as notify

    sms_ready = notify.sms_provider_configured()
    health_score = max(
        0,
        100
        - min(35, reconnect_pressure * 2)
        - min(30, len(stale_assignments) * 3)
        - min(20, int(queue_stats.get("failed", 0) or 0) * 4)
        - (15 if not replay_safe else 0),
    )

    return {
        "organization_id": effective_org_id,
        "generated_at": now(),
        "preview_mode": True,
        "transportation_first": True,
        "runtime": {
            "websocket": websocket,
            "hydration": {
                "last_reconciliation_at": runtime_state.get("last_reconciliation_at"),
                "deterministic_event_ordering": bool(runtime_state.get("deterministic_event_ordering", True)),
                "reconnect_replay_support": bool(runtime_state.get("reconnect_replay_support", True)),
            },
            "replay": {
                "replay_safe": bool(replay_probe.get("replay_safe", True)),
                "sequence_monotonic": bool(replay_probe.get("sequence_monotonic", True)),
                "latest_sequence": int(replay_probe.get("latest_sequence", 0) or 0),
                "sample_events": len(list(replay_probe.get("events") or [])),
            },
            "api_connectivity": {
                "ready": True,
                "tenant_scoped": True,
                "route": "/api/health-isf/operations/preview-runtime-status",
            },
        },
        "sessions": {
            "dispatcher_active": int(websocket.get("dispatcher_connections", 0) or 0),
            "driver_active": int(websocket.get("driver_connections", 0) or 0),
            "provider_registry": len(list(runtime_state.get("provider_coordination_registry") or [])),
            "dispatcher_locks": len(active_locks),
        },
        "dispatch": {
            "queue_depth": len(dispatch_queue),
            "active_assignment_count": len(active_assignments),
            "stale_assignment_count": len(stale_assignments),
            "active_locks": active_locks,
            "queue_stats": queue_stats,
            "health_score": int(health_score),
            "health_state": "stable" if health_score >= 85 else ("watch" if health_score >= 65 else "degraded"),
        },
        "safety": {
            "no_pharmacy_workflows": True,
            "no_medication_delivery": True,
            "deterministic_runtime": True,
            "replay_consistent": replay_safe,
        },
        "contact": {
            "sms_configured": sms_ready,
            "sms_status_message": "SMS ready" if sms_ready else "SMS/contact provider not configured yet",
        },
    }


@router.get("/operations/service-categories")
def get_phase53_service_categories(
    user: UserContext = Depends(get_current_user_context),
):
    """PHASE 53 service category compatibility status for command-center hydration."""
    _ = user  # Auth-gated endpoint; explicit read keeps behavior role-scoped.
    return {
        "categories": service_category_status(),
        "transportation_first": True,
        "future_execution_disabled": True,
    }


@router.post("/operations/runtime-reconcile")
def reconcile_phase52_runtime(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Reconcile in-memory runtime registry against persisted ride/driver/provider state."""
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rides = [row for row in service.get_all_rides(db, skip=0, limit=500) if row.organization_id == effective_org_id]
    drivers = [row for row in service.get_all_drivers(db, skip=0, limit=500) if row.organization_id == effective_org_id]
    providers = [row for row in service.get_all_providers(db, skip=0, limit=500) if row.organization_id == effective_org_id]
    return get_live_transport_runtime_manager().reconcile(
        effective_org_id,
        rides=rides,
        drivers=drivers,
        providers=providers,
    )


@router.get("/operations/assignment-state-audit")
def assignment_state_audit(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Report stale active rides and assignments without mutating records."""
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.audit_organization_assignment_state(db, organization_id=effective_org_id)


@router.post("/operations/assignment-state-reconcile")
def assignment_state_reconcile(
    organization_id: str | None = Query(None),
    dry_run: bool = Query(True),
    ride_id: list[str] | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Repair inconsistent ride/assignment rows. Defaults to report-only dry_run=true."""
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.repair_organization_assignment_state(
        db,
        organization_id=effective_org_id,
        dry_run=dry_run,
        ride_ids=ride_id,
        actor_user_id=user.user_id,
    )


@router.post("/operations/dispatch-recovery")
async def execute_phase52_dispatch_recovery(
    ride_id: str = Query(..., min_length=1),
    strategy: str = Query("auto_assign", pattern="^(auto_assign|reassign)$"),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Admin recovery tool for stale or failed dispatch assignment paths."""
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ride = service.get_ride_by_id(db, ride_id)
    if not ride or ride.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Ride not found")
    try:
        ensure_active_service_category(getattr(ride, "service_type", None))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        if strategy == "reassign":
            recovery_result = service.reassign_expired_request(
                db,
                ride_id=ride_id,
                offer_timeout_seconds=120,
                reason="phase52_dispatch_recovery",
                actor_user_id=user.user_id,
            )
        else:
            recovery_result = service.auto_assign_request(
                db,
                ride_id=ride_id,
                offer_timeout_seconds=120,
                actor_user_id=user.user_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    ride = recovery_result.get("ride") if isinstance(recovery_result, dict) else None
    if not ride:
        raise HTTPException(status_code=400, detail="Dispatch recovery could not update ride")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride.id,
        event_name="admin_override",
        actor_user_id=user.user_id,
        details={
            "ride_id": ride.id,
            "strategy": strategy,
            "source": "phase52_dispatch_recovery",
        },
        request_id=f"phase52_recovery_{ride.id}",
        driver_id=ride.driver_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason="phase52_dispatch_recovery",
        assignment_transition_source="admin_command_center",
    )
    return {
        "organization_id": effective_org_id,
        "ride": RideResponse.model_validate(ride).model_dump(),
        "strategy": strategy,
        "message": "Dispatch recovery executed.",
    }


@router.post("/operations/lifecycle-action")
async def execute_phase52_lifecycle_action(
    action: str = Query(..., pattern="^(create_ride|approve_ride|assign_driver|accept_assignment|driver_arrived|rider_picked_up|ride_in_progress|ride_completed|ride_cancelled|escalation_requested)$"),
    ride_id: str | None = Query(None),
    driver_id: str | None = Query(None),
    provider_id: str | None = Query(None),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Phase 52 lifecycle engine endpoint with deterministic runtime mutation and propagation."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    resulting_ride = None

    if action == "create_ride":
        provider = None
        if provider_id:
            provider = service.get_provider_by_id(db, provider_id)
        if provider is None:
            provider = next((row for row in service.get_all_providers(db, skip=0, limit=50) if row.organization_id == effective_org_id), None)
        if provider is None:
            raise HTTPException(status_code=400, detail="No provider available for lifecycle create_ride")
        resulting_ride = service.create_ride(
            db=db,
            organization_id=effective_org_id,
            passenger_name=f"Phase52 Rider {str(now().timestamp()).replace('.', '')[-6:]}",
            passenger_phone=f"212-555-{str(now().timestamp()).replace('.', '')[-4:]}",
            pickup_address="100 Phase52 Runtime Way",
            dropoff_address="200 Phase52 Runtime Way",
            service_type=serialize_service_category("healthcare"),
            provider_id=provider.id,
            actor_user_id=user.user_id,
        )
        ride_id = resulting_ride.id
    else:
        if not ride_id:
            raise HTTPException(status_code=400, detail="ride_id is required for this lifecycle action")
        resulting_ride = service.get_ride_by_id(db, ride_id)
        if not resulting_ride or resulting_ride.organization_id != effective_org_id:
            raise HTTPException(status_code=404, detail="Ride not found")
        try:
            ensure_active_service_category(getattr(resulting_ride, "service_type", None))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        if action == "approve_ride":
            resulting_ride = service.update_ride_status(db, ride_id=ride_id, status=RideStatus.QUEUED.value, actor_user_id=user.user_id)
        elif action == "assign_driver":
            if not driver_id:
                driver = next((row for row in service.get_all_drivers(db, skip=0, limit=80) if row.organization_id == effective_org_id and str(row.status).lower() == DriverStatus.AVAILABLE.value), None)
                driver_id = str(driver.id) if driver else None
            if not driver_id:
                raise HTTPException(status_code=400, detail="No available driver found for assign_driver")
            resulting_ride = service.assign_driver_to_ride(db, ride_id=ride_id, driver_id=driver_id, actor_user_id=user.user_id)
        elif action == "accept_assignment":
            if not driver_id:
                driver_id = str(getattr(resulting_ride, "driver_id", "") or "")
            if not driver_id:
                raise HTTPException(status_code=400, detail="driver_id required for accept_assignment")
            resulting_ride = service.accept_driver_ride(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=user.user_id)
        elif action == "driver_arrived":
            if not driver_id:
                driver_id = str(getattr(resulting_ride, "driver_id", "") or "")
            resulting_ride = service.driver_arrived_pickup(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=user.user_id)
        elif action == "rider_picked_up":
            if not driver_id:
                driver_id = str(getattr(resulting_ride, "driver_id", "") or "")
            resulting_ride = service.driver_pickup_complete(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=user.user_id)
        elif action == "ride_in_progress":
            if not driver_id:
                driver_id = str(getattr(resulting_ride, "driver_id", "") or "")
            resulting_ride = service.driver_start_trip(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=user.user_id)
        elif action == "ride_completed":
            if not driver_id:
                driver_id = str(getattr(resulting_ride, "driver_id", "") or "")
            current_state = RideLifecycleManager.normalize_state(getattr(resulting_ride, "lifecycle_state", None) or getattr(resulting_ride, "status", None))
            if current_state == RideStatus.IN_PROGRESS.value:
                resulting_ride = service.driver_arrived_destination(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=user.user_id)
            resulting_ride = service.driver_dropoff_complete(db, driver_id=driver_id, ride_id=ride_id, actor_user_id=user.user_id)
        elif action == "ride_cancelled":
            resulting_ride = service.update_ride_status(db, ride_id=ride_id, status=RideStatus.CANCELLED.value, actor_user_id=user.user_id)
        elif action == "escalation_requested":
            resulting_ride = service.update_ride_status(db, ride_id=ride_id, status=RideStatus.ESCALATED.value, actor_user_id=user.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if resulting_ride is None:
        raise HTTPException(status_code=400, detail=f"Lifecycle action {action} could not be completed")

    event_map = {
        "create_ride": "ride_created",
        "approve_ride": "ride_approved",
        "assign_driver": "driver_assigned",
        "accept_assignment": "assignment_accepted",
        "driver_arrived": "driver_arrived",
        "rider_picked_up": "pickup_completed",
        "ride_in_progress": "ride_started",
        "ride_completed": "ride_completed",
        "ride_cancelled": "ride_cancelled",
        "escalation_requested": "escalation_created",
    }

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=resulting_ride.id,
        event_name=event_map[action],
        actor_user_id=user.user_id,
        details={
            "ride_id": resulting_ride.id,
            "driver_id": getattr(resulting_ride, "driver_id", None),
            "provider_id": getattr(resulting_ride, "provider_id", None),
            "action": action,
            "phase": "phase52",
        },
        request_id=f"phase52_lifecycle_{action}_{resulting_ride.id}",
        driver_id=getattr(resulting_ride, "driver_id", None),
        lifecycle_state=str(getattr(resulting_ride, "lifecycle_state", None) or resulting_ride.status),
        transition_reason=f"phase52_{action}",
        assignment_transition_source="phase52_lifecycle_engine",
    )

    return {
        "organization_id": effective_org_id,
        "action": action,
        "ride": RideResponse.model_validate(resulting_ride).model_dump(),
        "runtime": get_live_transport_runtime_manager().runtime_snapshot(effective_org_id, include_timeline=True, limit=20),
    }


# ── Real-Time WebSocket Endpoint ──────────────────────────────────────────────

@websocket_router.websocket("/ws/live/{organization_id}/{user_id}")
async def websocket_live_updates(
    websocket: WebSocket,
    organization_id: str,
    user_id: str,
    role: str = Query(...),
    token: str = Query(...),
    last_sequence: int = Query(0),
    restore_subscriptions: str | None = Query(None),
    restore_ride_ids: str | None = Query(None),
    client_session_id: str | None = Query(None),
):
    """WebSocket endpoint for live dispatch updates."""
    db = SessionLocal()
    token_payload: dict = {}
    token_user_id: str | None = None
    token_role: str | None = None
    token_org_id: str | None = None
    authority_snapshot: dict[str, Any] = {}
    connection_id = f"{user_id}_{now().timestamp()}"
    restored_subscriptions: list[str] = []
    restored_ride_subscriptions: list[str] = []
    connection = WebSocketConnection(
        connection_id=connection_id,
        user_id=user_id,
        role=str(role or ROLE_DISPATCHER),
    )

    metrics = get_operational_metrics_registry()
    broadcaster = get_broadcaster()

    def _normalize_runtime_error(code: str, detail: str, *, recoverable: bool = True) -> dict[str, Any]:
        return {
            "type": "error",
            "code": str(code or "runtime_error"),
            "detail": str(detail or "unknown runtime error"),
            "recoverable": bool(recoverable),
            "degraded_reasons": broadcaster.get_websocket_health_stats(organization_id).get("degraded_reasons", []),
            "timestamp": now().isoformat(),
        }

    try:
        token_payload = decode_access_token(token)
        token_user_id = token_payload.get("sub")
        token_role = token_payload.get("role")
        token_org_id = token_payload.get("organization_id")

        if token_user_id != user_id and token_role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
            SuspiciousActivityService.log_activity(
                db,
                activity_type="websocket_token_user_mismatch",
                organization_id=organization_id,
                user_id=token_user_id,
                details={"path_user_id": user_id},
            )
            await websocket.close(code=1008, reason="Token user mismatch")
            return

        if token_role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT} and token_org_id != organization_id:
            SuspiciousActivityService.log_activity(
                db,
                activity_type="websocket_cross_tenant_attempt",
                organization_id=token_org_id,
                user_id=token_user_id,
                details={"requested_org_id": organization_id},
            )
            await websocket.close(code=1008, reason="Cross-tenant websocket access denied")
            return

        connection.role = str(token_role or role)
        authority_snapshot = _build_session_authority(
            UserContext(
                user_id=user_id,
                email=str(token_payload.get("email") or "unknown"),
                role=connection.role,
                organization_id=token_org_id,
            ),
            token_payload,
        )
    except HTTPException as exc:
        metrics.increment("websocket.auth.errors")
        logger.warning(
            "WebSocket auth failed during setup",
            extra={"organization_id": organization_id, "user_id": user_id, "detail": str(exc.detail)},
        )
        await websocket.close(code=1008, reason="Authentication failed")
        return

    try:
        await websocket.accept()
        await broadcaster.register_connection(connection, organization_id)
        runtime_manager = get_live_transport_runtime_manager()
        runtime_manager.register_websocket_connection(
            organization_id=organization_id,
            connection_id=connection_id,
            user_id=user_id,
            role=str(connection.role or role or ROLE_DISPATCHER),
        )
        metrics.record_event_ts("websocket.connects")
        try:
            cognitive_snapshot = OperationalCognitionEngine.build_snapshot(
                db,
                organization_id=organization_id,
                role=str(connection.role or role or ROLE_DISPATCHER),
            )
        except Exception as cognitive_exc:
            logger.warning(
                "WebSocket cognitive snapshot degraded",
                extra={"organization_id": organization_id, "error": str(cognitive_exc)},
            )
            cognitive_snapshot = {"cognitive_diagnostics": {}}
        log_operational_event(
            "websocket.connected",
            connection_id=connection_id,
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        logger.info(f"WebSocket connected: {connection_id} for org {organization_id}")
        
        # Send initial connection confirmation
        init_msg = {
            "type": "connected",
            "connection_id": connection_id,
            "timestamp": now().isoformat(),
            "authority": authority_snapshot,
            "replay_sequence": broadcaster.get_latest_sequence(organization_id),
            "replay_source": "persistent_lifecycle_stream",
            "client_session_id": client_session_id,
            "ride_subscriptions": list(connection.ride_subscriptions),
            "workflow_coordination": broadcaster.get_workflow_coordination_contract(organization_id),
            "distributed_governance": broadcaster.get_runtime_reliability_diagnostics(organization_id).get("distributed_governance", {}),
            "cognitive_diagnostics": cognitive_snapshot.get("cognitive_diagnostics", {}),
        }
        await websocket.send_json(init_msg)

        if restore_subscriptions:
            requested_subscriptions = [
                item.strip()
                for item in str(restore_subscriptions).split(",")
                if item and item.strip()
            ]
            user_ctx = UserContext(
                user_id=user_id,
                email=str(token_payload.get("email") or "unknown"),
                role=str(token_role or role),
                organization_id=token_org_id,
            )
            for requested in requested_subscriptions[:10]:
                try:
                    canonical_subscription = authorize_subscription(user_ctx, requested)
                except HTTPException:
                    continue
                connection.subscribe(canonical_subscription)
                restored_subscriptions.append(canonical_subscription)
            runtime_manager.set_websocket_subscriptions(
                organization_id=organization_id,
                connection_id=connection_id,
                subscriptions=list(connection.subscriptions),
            )

        if restore_ride_ids:
            requested_ride_ids = [
                item.strip()
                for item in str(restore_ride_ids).split(",")
                if item and item.strip()
            ]
            for requested_ride_id in requested_ride_ids[:50]:
                ride = service.get_ride_by_id(db, requested_ride_id)
                if not ride or str(ride.organization_id) != str(organization_id):
                    continue
                connection.subscribe_ride(requested_ride_id)
                restored_ride_subscriptions.append(requested_ride_id)

        if int(last_sequence or 0) > 0:
            replay_snapshot = OperationalReplayService.replay(
                organization_id=organization_id,
                after_sequence=int(last_sequence or 0),
                role=str(connection.role or role or ROLE_DISPATCHER),
                limit=400,
            )
            replay_events = _filter_operational_replay_for_connection(
                replay_events=list(replay_snapshot.get("events") or []),
                connection=connection,
            )
            await websocket.send_json(
                {
                    "type": "sync",
                    "requested_sequence": int(last_sequence or 0),
                    "latest_sequence": int((replay_snapshot.get("cursor") or {}).get("last_sequence", 0) or 0),
                    "events": replay_events,
                    "source": "persistent_lifecycle_stream",
                    "timestamp": now().isoformat(),
                    "workflow_coordination": broadcaster.get_workflow_coordination_contract(organization_id),
                    "distributed_governance": broadcaster.get_runtime_reliability_diagnostics(organization_id).get("distributed_governance", {}),
                    "cognitive_diagnostics": cognitive_snapshot.get("cognitive_diagnostics", {}),
                    "recovery": {
                        "continuity_restored": True,
                        "restored_subscriptions": restored_subscriptions,
                        "restored_ride_subscriptions": restored_ride_subscriptions,
                    },
                }
            )
            broadcaster.record_recovery_attempt(organization_id, success=True)
            OperationalSynchronizationEngine.publish_event(
                organization_id=organization_id,
                event_type=OperationalEventType.WEBSOCKET_RECONNECT,
                payload={
                    "user_id": user_id,
                    "connection_id": connection_id,
                    "requested_sequence": int(last_sequence or 0),
                    "latest_sequence": int((replay_snapshot.get("cursor") or {}).get("last_sequence", 0) or 0),
                    "restored_subscriptions": list(restored_subscriptions),
                    "restored_ride_subscriptions": list(restored_ride_subscriptions),
                    "actor_user_id": user_id,
                    "correlation_id": f"ws-reconnect:{organization_id}:{connection_id}",
                },
                role_scope=["dispatcher", "driver", "rider", "operations", "admin"],
                source_nonce=f"ws_reconnect:{organization_id}:{connection_id}:{int(last_sequence or 0)}",
            )
            runtime_manager.record_runtime_reconnected(
                organization_id=organization_id,
                user_id=user_id,
                connection_id=connection_id,
                requested_sequence=int(last_sequence or 0),
                latest_sequence=broadcaster.get_latest_sequence(organization_id),
            )
        
        # Create background task for sending queued messages
        async def send_queued_messages():
            while True:
                try:
                    message = await asyncio.wait_for(
                        connection.send_queue.get(),
                        timeout=1.0
                    )
                    await websocket.send_text(message)
                except asyncio.TimeoutError:
                    continue
                except Exception as e:
                    logger.error(f"Error sending message: {e}")
                    break
        
        send_task = asyncio.create_task(send_queued_messages())
        
        # Handle incoming messages
        while True:
            try:
                data = await websocket.receive_json()
                if not connection.register_message(max_messages_per_minute=240):
                    SuspiciousActivityService.log_activity(
                        db,
                        activity_type="websocket_rate_limited",
                        organization_id=organization_id,
                        user_id=user_id,
                        details={"connection_id": connection_id},
                    )
                    await websocket.send_json({"type": "error", "detail": "WebSocket rate limit exceeded"})
                    await websocket.close(code=1013)
                    break

                msg_type = data.get("type")
                
                if msg_type == "subscribe":
                    subscription_type = data.get("subscription_type")
                    if subscription_type:
                        user_ctx = UserContext(
                            user_id=user_id,
                            email=str(token_payload.get("email") or "unknown"),
                            role=str(token_role or role),
                            organization_id=token_org_id,
                        )
                        try:
                            canonical_subscription = authorize_subscription(user_ctx, subscription_type)
                        except HTTPException as exc:
                            SuspiciousActivityService.log_activity(
                                db,
                                activity_type="websocket_subscription_denied",
                                organization_id=organization_id,
                                user_id=user_id,
                                details={"subscription_type": subscription_type, "role": user_ctx.role},
                            )
                            await websocket.send_json(
                                {
                                    "type": "error",
                                    "detail": str(exc.detail),
                                    "subscription_type": str(subscription_type),
                                    "timestamp": now().isoformat(),
                                }
                            )
                            continue
                        connection.subscribe(canonical_subscription)
                        runtime_manager.set_websocket_subscriptions(
                            organization_id=organization_id,
                            connection_id=connection_id,
                            subscriptions=list(connection.subscriptions),
                        )
                        if canonical_subscription not in restored_subscriptions:
                            restored_subscriptions.append(canonical_subscription)
                        await websocket.send_json(
                            {
                                "type": "subscribed",
                                "subscription_type": canonical_subscription,
                                "timestamp": now().isoformat(),
                            }
                        )
                        log_operational_event(
                            "websocket.subscribed",
                            connection_id=connection_id,
                            subscription_type=canonical_subscription,
                            organization_id=organization_id,
                        )
                        logger.info(f"Subscribed {connection_id} to {canonical_subscription}")
                
                elif msg_type == "unsubscribe":
                    subscription_type = data.get("subscription_type")
                    if subscription_type:
                        connection.unsubscribe(subscription_type)
                        runtime_manager.set_websocket_subscriptions(
                            organization_id=organization_id,
                            connection_id=connection_id,
                            subscriptions=list(connection.subscriptions),
                        )
                        await websocket.send_json(
                            {
                                "type": "unsubscribed",
                                "subscription_type": subscription_type,
                                "timestamp": now().isoformat(),
                            }
                        )
                        log_operational_event(
                            "websocket.unsubscribed",
                            connection_id=connection_id,
                            subscription_type=subscription_type,
                            organization_id=organization_id,
                        )
                        logger.info(f"Unsubscribed {connection_id} from {subscription_type}")

                elif msg_type == "subscribe_ride":
                    requested_ride_id = str(data.get("ride_id") or "").strip()
                    if not requested_ride_id:
                        await websocket.send_json(
                            _normalize_runtime_error(
                                "ride_subscription_required",
                                "ride_id is required for subscribe_ride",
                                recoverable=True,
                            )
                        )
                        continue
                    ride = service.get_ride_by_id(db, requested_ride_id)
                    if not ride or str(ride.organization_id) != str(organization_id):
                        await websocket.send_json(
                            _normalize_runtime_error(
                                "ride_subscription_invalid",
                                "ride_id is not available in this organization",
                                recoverable=True,
                            )
                        )
                        continue
                    connection.subscribe_ride(requested_ride_id)
                    if requested_ride_id not in restored_ride_subscriptions:
                        restored_ride_subscriptions.append(requested_ride_id)
                    await websocket.send_json(
                        {
                            "type": "ride_subscribed",
                            "ride_id": requested_ride_id,
                            "timestamp": now().isoformat(),
                        }
                    )

                elif msg_type == "unsubscribe_ride":
                    requested_ride_id = str(data.get("ride_id") or "").strip()
                    if not requested_ride_id:
                        continue
                    connection.unsubscribe_ride(requested_ride_id)
                    restored_ride_subscriptions = [rid for rid in restored_ride_subscriptions if rid != requested_ride_id]
                    await websocket.send_json(
                        {
                            "type": "ride_unsubscribed",
                            "ride_id": requested_ride_id,
                            "timestamp": now().isoformat(),
                        }
                    )
                
                elif msg_type == "ping":
                    connection.update_heartbeat()
                    pong_msg = {"type": "pong", "timestamp": now().isoformat()}
                    await websocket.send_json(pong_msg)
                    metrics.increment("websocket.pings")

                elif msg_type == "sync":
                    requested_sequence = int(data.get("last_sequence") or 0)
                    replay_integrity = OperationalReplayService.replay_integrity(organization_id)
                    latest_persisted_sequence = int(replay_integrity.get("latest_sequence", 0) or 0)
                    if requested_sequence > latest_persisted_sequence:
                        broadcaster.record_recovery_attempt(organization_id, success=False)
                        await websocket.send_json(
                            _normalize_runtime_error(
                                "sync_out_of_order",
                                "Requested sequence is ahead of server sequence.",
                                recoverable=True,
                            )
                        )
                        continue

                    replay_snapshot = OperationalReplayService.replay(
                        organization_id=organization_id,
                        after_sequence=requested_sequence,
                        role=str(connection.role or role or ROLE_DISPATCHER),
                        limit=400,
                    )
                    replay_events = _filter_operational_replay_for_connection(
                        replay_events=list(replay_snapshot.get("events") or []),
                        connection=connection,
                    )

                    broadcaster.record_recovery_attempt(organization_id, success=True)
                    runtime_manager.record_runtime_reconnected(
                        organization_id=organization_id,
                        user_id=user_id,
                        connection_id=connection_id,
                        requested_sequence=requested_sequence,
                        latest_sequence=broadcaster.get_latest_sequence(organization_id),
                    )
                    await websocket.send_json(
                        {
                            "type": "sync",
                            "requested_sequence": requested_sequence,
                            "latest_sequence": int((replay_snapshot.get("cursor") or {}).get("last_sequence", 0) or 0),
                            "events": replay_events,
                            "source": "persistent_lifecycle_stream",
                            "timestamp": now().isoformat(),
                            "workflow_coordination": broadcaster.get_workflow_coordination_contract(organization_id),
                            "recovery": {
                                "continuity_restored": True,
                                "restored_subscriptions": restored_subscriptions,
                                "restored_ride_subscriptions": restored_ride_subscriptions,
                            },
                        }
                    )

                elif msg_type == "sync_persistent":
                    requested_sequence = int(data.get("last_sequence") or 0)
                    replay_snapshot = OperationalReplayService.replay(
                        organization_id=organization_id,
                        after_sequence=requested_sequence,
                        role=str(connection.role or role or ROLE_DISPATCHER),
                        limit=400,
                    )
                    replay_events = _filter_operational_replay_for_connection(
                        replay_events=list(replay_snapshot.get("events") or []),
                        connection=connection,
                    )
                    await websocket.send_json(
                        {
                            "type": "sync",
                            "requested_sequence": requested_sequence,
                            "latest_sequence": int((replay_snapshot.get("cursor") or {}).get("last_sequence", 0) or 0),
                            "events": replay_events,
                            "source": "persistent_lifecycle_stream",
                            "timestamp": now().isoformat(),
                        }
                    )

                elif msg_type == "claim_assignment_lock":
                    target_ride_id = str(data.get("ride_id") or "").strip()
                    expected_version = data.get("expected_version")
                    if not target_ride_id:
                        await websocket.send_json(_normalize_runtime_error("ride_required", "ride_id required", recoverable=True))
                        continue

                    ride = service.get_ride_by_id(db, target_ride_id)
                    if not ride or str(ride.organization_id) != str(organization_id):
                        await websocket.send_json(_normalize_runtime_error("ride_not_found", "ride not found", recoverable=True))
                        continue

                    if expected_version is not None and not ConcurrentAssignmentService.validate_ride_version(
                        db,
                        ride_id=target_ride_id,
                        expected_version=int(expected_version),
                    ):
                        await websocket.send_json(
                            _normalize_runtime_error(
                                "optimistic_concurrency_conflict",
                                "Ride version mismatch; refresh before retrying lock claim.",
                                recoverable=True,
                            )
                        )
                        continue

                    lock = ConcurrentAssignmentService.claim_or_refresh_assignment_lock(
                        db,
                        ride_id=target_ride_id,
                        user_id=user_id,
                        lock_duration_seconds=90,
                        force=False,
                    )
                    if not lock:
                        await websocket.send_json(
                            _normalize_runtime_error(
                                "assignment_lock_conflict",
                                "Ride is currently locked by another dispatcher.",
                                recoverable=True,
                            )
                        )
                        continue

                    await websocket.send_json(
                        {
                            "type": "assignment_lock_claimed",
                            "ride_id": target_ride_id,
                            "lock_id": lock.id,
                            "expires_at": lock.expires_at.isoformat() if getattr(lock, "expires_at", None) else None,
                            "timestamp": now().isoformat(),
                        }
                    )

                elif msg_type == "release_assignment_lock":
                    target_ride_id = str(data.get("ride_id") or "").strip()
                    if not target_ride_id:
                        continue
                    ConcurrentAssignmentService.release_assignment_lock(db, ride_id=target_ride_id)
                    await websocket.send_json(
                        {
                            "type": "assignment_lock_released",
                            "ride_id": target_ride_id,
                            "timestamp": now().isoformat(),
                        }
                    )

                elif msg_type == "workflow_timeline":
                    requested_chain_id = str(data.get("chain_id") or "").strip()
                    if not requested_chain_id:
                        await websocket.send_json(
                            _normalize_runtime_error(
                                "workflow_chain_required",
                                "chain_id is required for workflow timeline fetch",
                                recoverable=True,
                            )
                        )
                        continue
                    timeline_payload: dict[str, Any] = {"chain": {}, "checkpoints": [], "queued_tasks": []}
                    try:
                        from app.modules.health_isf.runtime_governor import get_runtime_governor

                        timeline_payload = get_runtime_governor().get_execution_chain_timeline(requested_chain_id)
                    except Exception:
                        timeline_payload = {"chain": {}, "checkpoints": [], "queued_tasks": []}
                    await websocket.send_json(
                        {
                            "type": "workflow_timeline",
                            "chain_id": requested_chain_id,
                            "timestamp": now().isoformat(),
                            "timeline": timeline_payload,
                        }
                    )

                elif msg_type == "auth_refresh":
                    refreshed_token = str(data.get("token") or "").strip()
                    if not refreshed_token:
                        await websocket.send_json(
                            {
                                "type": "auth_refresh_result",
                                "ok": False,
                                "detail": "token required",
                                "timestamp": now().isoformat(),
                            }
                        )
                        continue

                    try:
                        refreshed_payload = decode_access_token(refreshed_token)
                        refreshed_user_id = str(refreshed_payload.get("sub") or "")
                        refreshed_role = str(refreshed_payload.get("role") or "")
                        refreshed_org = str(refreshed_payload.get("organization_id") or "")

                        if refreshed_user_id != user_id and refreshed_role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
                            SuspiciousActivityService.log_activity(
                                db,
                                activity_type="websocket_auth_refresh_mismatch",
                                organization_id=organization_id,
                                user_id=refreshed_user_id or user_id,
                                details={"path_user_id": user_id, "connection_id": connection_id},
                            )
                            await websocket.send_json(
                                {
                                    "type": "auth_refresh_result",
                                    "ok": False,
                                    "detail": "token user mismatch",
                                    "timestamp": now().isoformat(),
                                }
                            )
                            continue

                        if refreshed_role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT} and refreshed_org != organization_id:
                            SuspiciousActivityService.log_activity(
                                db,
                                activity_type="websocket_auth_refresh_cross_tenant",
                                organization_id=refreshed_org or organization_id,
                                user_id=refreshed_user_id or user_id,
                                details={"requested_org_id": organization_id, "connection_id": connection_id},
                            )
                            await websocket.send_json(
                                {
                                    "type": "auth_refresh_result",
                                    "ok": False,
                                    "detail": "cross-tenant refresh denied",
                                    "timestamp": now().isoformat(),
                                }
                            )
                            continue

                        token_payload = refreshed_payload
                        token_user_id = refreshed_user_id
                        token_role = refreshed_role
                        token_org_id = refreshed_org
                        connection.role = refreshed_role or connection.role
                        authority_snapshot = _build_session_authority(
                            UserContext(
                                user_id=user_id,
                                email=str(token_payload.get("email") or "unknown"),
                                role=connection.role,
                                organization_id=token_org_id,
                            ),
                            token_payload,
                        )
                        SecurityAuditService.log_action(
                            db,
                            organization_id=organization_id,
                            action_type="websocket_auth_refresh",
                            actor_user_id=user_id,
                            details={"connection_id": connection_id, "role": connection.role},
                        )
                        metrics.increment("websocket.auth.refresh.success")
                        await websocket.send_json(
                            {
                                "type": "auth_refresh_result",
                                "ok": True,
                                "authority": authority_snapshot,
                                "timestamp": now().isoformat(),
                            }
                        )
                    except HTTPException as exc:
                        metrics.increment("websocket.auth.refresh.failed")
                        SuspiciousActivityService.log_activity(
                            db,
                            activity_type="websocket_auth_refresh_failed",
                            organization_id=organization_id,
                            user_id=user_id,
                            details={"detail": str(exc.detail), "connection_id": connection_id},
                        )
                        await websocket.send_json(
                            {
                                "type": "auth_refresh_result",
                                "ok": False,
                                "detail": str(exc.detail),
                                "timestamp": now().isoformat(),
                            }
                        )
                
            except WebSocketDisconnect:
                metrics.record_event_ts("websocket.disconnects")
                logger.info(f"WebSocket disconnected: {connection_id}")
                break
            except Exception as e:
                metrics.increment("websocket.errors")
                broadcaster.record_recovery_attempt(organization_id, success=False)
                logger.error(f"WebSocket error: {e}")
                break
        
        send_task.cancel()
    except ValueError as exc:
        metrics.increment("websocket.connection.throttled")
        await websocket.send_json(_normalize_runtime_error("connection_throttled", str(exc), recoverable=True))
        await websocket.close(code=1008)
        log_operational_event(
            "websocket.connection_rejected",
            level=logging.WARNING,
            reason=str(exc),
            organization_id=organization_id,
            user_id=user_id,
        )
    except Exception as e:
        metrics.increment("websocket.errors")
        broadcaster.record_recovery_attempt(organization_id, success=False)
        SuspiciousActivityService.log_activity(
            db,
            activity_type="websocket_error",
            organization_id=organization_id,
            user_id=token_user_id,
            details={"error": str(e)},
        )
        logger.error(f"WebSocket error during setup: {e}")
        try:
            await websocket.close(code=1011, reason="WebSocket setup failed")
        except Exception:
            pass
    finally:
        try:
            await broadcaster.unregister_connection(connection_id)
            get_live_transport_runtime_manager().unregister_websocket_connection(
                organization_id=organization_id,
                connection_id=connection_id,
            )
        except Exception:
            logger.exception("Failed to unregister websocket connection", extra={"connection_id": connection_id})
        db.close()


# ── Activity Feed Endpoint ────────────────────────────────────────────────────

@router.get("/activity-feed", response_model=ActivityFeedResponse)
def get_activity_feed(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve dispatcher activity feed."""
    logger.info(f"Fetching activity feed: skip={skip}, limit={limit}")
    
    organization_id = enforce_tenant_scope(user, None)
    
    activities, total = ActivityLogService.get_activity_feed(
        db,
        organization_id=organization_id,
        limit=limit,
        skip=skip,
    )

    dispatch_query = (
        db.query(HealthISFDispatchLog)
        .join(HealthISFRide, HealthISFRide.id == HealthISFDispatchLog.ride_id)
        .filter(HealthISFRide.organization_id == organization_id)
    )
    dispatch_rows = dispatch_query.order_by(HealthISFDispatchLog.created_at.desc()).offset(skip).limit(limit).all()
    if dispatch_rows:
        activities = list(activities) + list(dispatch_rows)

    normalized_activities = []
    seen_activity_ids: set[str] = set()
    for activity in activities:
        raw_details = getattr(activity, "details", None)
        activity_id = str(getattr(activity, "id", ""))
        if activity_id in seen_activity_ids:
            continue
        seen_activity_ids.add(activity_id)
        raw_action = str(getattr(activity, "action", ""))
        raw_event_name = str(getattr(activity, "emitted_event_name", None) or "")
        normalized_action = raw_event_name or {
            "ride_created": "customer_ride_requested",
            "driver_offer_issued": "assignment-issued",
            "driver_offer_accepted": "assignment-accepted",
            "dropoff_completed": "trip-completed",
            "driver_dropoff_complete": "trip-completed",
            "assignment-completed": "trip-completed",
        }.get(raw_action, raw_action)
        payload = {
            "id": activity_id,
            "organization_id": str(getattr(activity, "organization_id", "")),
            "action": normalized_action,
            "ride_id": getattr(activity, "ride_id", None),
            "driver_id": getattr(activity, "driver_id", None),
            "description": str(
                getattr(activity, "description", None)
                or getattr(activity, "note", None)
                or raw_event_name
                or raw_action
            ),
            "details": raw_details,
            "actor_user_id": getattr(activity, "actor_user_id", None) or getattr(activity, "acted_by_user_id", None),
            "created_at": getattr(activity, "created_at", None),
        }
        if isinstance(raw_details, str):
            try:
                payload["details"] = json.loads(raw_details)
            except json.JSONDecodeError:
                payload["details"] = {"raw": raw_details}
        elif raw_details is None:
            payload["details"] = {
                "request_id": getattr(activity, "request_id", None),
                "assignment_id": getattr(activity, "assignment_id", None),
                "lifecycle_state": getattr(activity, "lifecycle_state", None),
                "transition_reason": getattr(activity, "transition_reason", None),
                "assignment_transition_source": getattr(activity, "assignment_transition_source", None),
                "emitted_event_name": getattr(activity, "emitted_event_name", None),
                "note": getattr(activity, "note", None),
            }
        normalized_activities.append(DispatcherActivityResponse.model_validate(payload))
    normalized_activities.sort(key=lambda item: item.created_at, reverse=True)
    normalized_activities = normalized_activities[:limit]
    total = max(total, len(normalized_activities))
    
    return ActivityFeedResponse(
        activities=normalized_activities,
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/ops/metrics", response_model=OperationalMetricsResponse)
def get_operational_metrics(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Operational metrics snapshot for dispatch observability dashboards."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return OperationalMetricsResponse(**build_operational_metrics(db, organization_id=effective_org_id))


@router.get("/ops/health", response_model=OperationalHealthResponse)
def get_operational_health(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Operational health checks: DB, websocket, queue/events, latency, dependencies."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    broadcaster = get_broadcaster()
    websocket_stats = broadcaster.get_websocket_health_stats(organization_id=effective_org_id)
    queue_stats = RetryQueueService.get_queue_stats(db, organization_id=effective_org_id)

    dependency_health: dict = {"healthy": True, "details": {}}
    try:
        from app.providers.resilience import all_diagnostics  # type: ignore
        dependency_health["details"] = all_diagnostics()
    except Exception as exc:
        dependency_health = {
            "healthy": False,
            "details": {"error": str(exc)},
        }

    payload = build_health_snapshot(
        db,
        websocket_stats=websocket_stats,
        queue_stats=queue_stats,
        dependency_health=dependency_health,
    )
    return OperationalHealthResponse(**payload)


@router.get("/ops/realtime-monitoring")
def get_realtime_operational_monitoring(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Live distributed operational monitoring for synchronization, replay, and dispatch health."""
    effective_org_id = enforce_tenant_scope(user, organization_id)

    broadcaster = get_broadcaster()
    websocket_stats = broadcaster.get_websocket_health_stats(organization_id=effective_org_id)
    queue_stats = RetryQueueService.get_queue_stats(db, organization_id=effective_org_id)
    replay_integrity = OperationalReplayService.replay_integrity(effective_org_id)
    metrics = build_operational_metrics(db, organization_id=effective_org_id)
    timeline = _build_operational_lifecycle_timeline(
        db=db,
        organization_id=effective_org_id,
        ride_id=None,
        limit=800,
    )

    now_ts = _as_utc_datetime(now())
    stale_cutoff = now_ts - timedelta(minutes=20)
    terminal = {RideStatus.COMPLETED.value, RideStatus.CANCELLED.value, RideStatus.FAILED.value}

    rides = db.query(HealthISFRide).filter(HealthISFRide.organization_id == effective_org_id).all()
    drivers = db.query(HealthISFDriver).filter(HealthISFDriver.organization_id == effective_org_id).all()
    assignments = service.get_dispatch_active_assignments(db, organization_id=effective_org_id, limit=500)

    stuck_rides = [
        ride for ride in rides
        if str(getattr(ride, "status", "")) not in terminal
        and _as_utc_datetime(getattr(ride, "updated_at", None) or getattr(ride, "requested_at", None) or now()) <= stale_cutoff
    ]
    orphaned_assignments = [
        row for row in assignments
        if not row.get("driver_id") or str(row.get("assignment_state") or "") in {"expired", "dead_letter"}
    ]
    driver_inactivity = [
        driver for driver in drivers
        if bool(getattr(driver, "is_active", True))
        and _as_utc_datetime(getattr(driver, "last_seen_at", None) or now()) <= now_ts - timedelta(minutes=15)
    ]

    sla_breach_count = 0
    for event in timeline:
        if str(event.get("event_type") or "") == "request_created":
            event_ts = _as_utc_datetime(_parse_iso_timestamp(str(event.get("timestamp") or "")) or now())
            if (now_ts - event_ts).total_seconds() > 20 * 60:
                sla_breach_count += 1

    dispatcher_load_index = float((metrics.get("dispatcher_load") or {}).get("index", 0.0) or 0.0)
    replay_failures = int(websocket_stats.get("recovery_failures_last_5m", 0) or 0)
    replay_lag = max(
        0,
        int(replay_integrity.get("latest_sequence", 0) or 0)
        - int(websocket_stats.get("replay_events_served_total", 0) or 0),
    )

    alerts: list[dict[str, Any]] = []
    if dispatcher_load_index > 1.2:
        alerts.append({"severity": "high", "code": "dispatcher_load_spike", "value": dispatcher_load_index})
    if sla_breach_count > 0:
        alerts.append({"severity": "high", "code": "sla_breach_detected", "value": sla_breach_count})
    if len(stuck_rides) > 0:
        alerts.append({"severity": "high", "code": "stuck_rides", "value": len(stuck_rides)})
    if len(orphaned_assignments) > 0:
        alerts.append({"severity": "medium", "code": "orphaned_assignments", "value": len(orphaned_assignments)})
    if len(driver_inactivity) > 0:
        alerts.append({"severity": "medium", "code": "driver_inactivity", "value": len(driver_inactivity)})
    if replay_lag > 0:
        alerts.append({"severity": "medium", "code": "synchronization_lag", "value": replay_lag})
    if replay_failures > 0:
        alerts.append({"severity": "high", "code": "event_replay_failures", "value": replay_failures})

    return {
        "organization_id": effective_org_id,
        "generated_at": now().isoformat(),
        "operational_monitoring": {
            "dispatcher_load_spikes": dispatcher_load_index > 1.2,
            "sla_breach_detection": sla_breach_count,
            "stuck_rides": len(stuck_rides),
            "orphaned_assignments": len(orphaned_assignments),
            "driver_inactivity": len(driver_inactivity),
            "synchronization_lag": replay_lag,
            "event_replay_failures": replay_failures,
        },
        "websocket": websocket_stats,
        "queue": queue_stats,
        "replay_integrity": replay_integrity,
        "alerts": alerts,
        "distributed_runtime_coordination": True,
        "backend_authoritative": True,
    }


@router.get("/ops/runtime-diagnostics")
def get_runtime_diagnostics(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Structured runtime reliability diagnostics for reconnect/replay/recovery observability."""
    effective_org_id = enforce_tenant_scope(user, organization_id)

    broadcaster = get_broadcaster()
    websocket_stats = broadcaster.get_websocket_health_stats(organization_id=effective_org_id)
    diagnostics = broadcaster.get_runtime_reliability_diagnostics(organization_id=effective_org_id)

    queue_stats = RetryQueueService.get_queue_stats(db, organization_id=effective_org_id)
    health_snapshot = build_health_snapshot(
        db,
        websocket_stats=websocket_stats,
        queue_stats=queue_stats,
    )

    runtime_governor_snapshot: dict[str, Any] = {}
    workflow_coordination: dict[str, Any] = {}
    distributed_governance: dict[str, Any] = {}
    cognitive_diagnostics: dict[str, Any] = {}
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        governor = get_runtime_governor()
        runtime_governor_snapshot = governor.get_health_snapshot() or {}
        workflow_coordination = governor.get_workflow_coordination_diagnostics(effective_org_id) or {}
        distributed_governance = governor.get_distributed_governance_diagnostics(effective_org_id) or {}
        cognitive_diagnostics = OperationalCognitionEngine.build_snapshot(
            db,
            organization_id=effective_org_id,
            role=str(user.role or "dispatcher"),
        )
    except Exception:
        runtime_governor_snapshot = {}
        workflow_coordination = {}
        distributed_governance = {}
        cognitive_diagnostics = {}

    orphan_workflows = int(
        runtime_governor_snapshot.get("orphan_workflows_detected", runtime_governor_snapshot.get("orphan_workflows", 0)) or 0
    )
    stale_cleanups = int(runtime_governor_snapshot.get("cleanup_cycles", 0) or 0)

    degraded_reasons = list(diagnostics.get("degraded_mode", {}).get("reasons", []) or [])
    if health_snapshot.get("status") != "healthy" and "health_snapshot:degraded" not in degraded_reasons:
        degraded_reasons.append("health_snapshot:degraded")

    if len(degraded_reasons) == 0:
        broadcaster.clear_degraded_state(effective_org_id)

    failed_events = int(queue_stats.get("failed", 0) or 0)
    dead_letter_events = int(queue_stats.get("dead_letter", 0) or 0)
    health_state = str(health_snapshot.get("status") or "healthy").lower()
    dispatch_continuity_safe = health_state != "critical"
    ride_operations_active = (failed_events + dead_letter_events) < 200

    orchestration_raw_state: Any = (
        runtime_governor_snapshot.get("resilience_state")
        or workflow_coordination.get("resilience_state")
        or runtime_governor_snapshot.get("health_state")
        or ("healthy" if len(degraded_reasons) == 0 else "degraded")
    )
    compliance_raw_state: Any = "read_only"
    if health_state in {"critical", "unhealthy"}:
        compliance_raw_state = "fallback"
    elif health_state in {"degraded", "watch", "needs_attention"}:
        compliance_raw_state = "degraded"

    overall_raw_state: Any = "healthy"
    if not bool((diagnostics.get("degraded_mode") or {}).get("enabled", False)) and len(degraded_reasons) == 0:
        overall_raw_state = "healthy"
    elif any(reason.startswith("replay") for reason in degraded_reasons):
        overall_raw_state = "replay_repair"
    elif health_state in {"critical", "unhealthy"}:
        overall_raw_state = "critical"
    elif len(degraded_reasons) > 0:
        overall_raw_state = "degraded"

    module_orchestration = _build_continuity_safe_module_summary(
        subsystem="orchestration",
        raw_state=orchestration_raw_state,
        degraded_reasons=degraded_reasons,
        dispatch_continuity_safe=dispatch_continuity_safe,
        ride_operations_active=ride_operations_active,
    )
    module_compliance = _build_continuity_safe_module_summary(
        subsystem="compliance",
        raw_state=compliance_raw_state,
        degraded_reasons=degraded_reasons,
        dispatch_continuity_safe=dispatch_continuity_safe,
        ride_operations_active=ride_operations_active,
    )

    return {
        "organization_id": effective_org_id,
        "generated_at": now().isoformat(),
        "runtime": diagnostics,
        "queue": {
            "dead_letter": int(queue_stats.get("dead_letter", 0) or 0),
            "failed": int(queue_stats.get("failed", 0) or 0),
            "retrying": int(queue_stats.get("retrying", 0) or 0),
            "pending": int(queue_stats.get("pending", 0) or 0),
        },
        "runtime_governor": {
            "active_workflows": int(runtime_governor_snapshot.get("active_workflows", 0) or 0),
            "completed_workflows": int(runtime_governor_snapshot.get("completed_workflows", 0) or 0),
            "orphaned_executions": orphan_workflows,
            "stale_execution_cleanups": stale_cleanups,
            "execution_failures": int(diagnostics.get("execution_failures", 0) or 0),
            "active_runtimes": int(runtime_governor_snapshot.get("active_runtimes", 0) or 0),
            "task_reassignment_count": int(runtime_governor_snapshot.get("task_reassignment_count", 0) or 0),
            "runtime_failover_count": int(runtime_governor_snapshot.get("runtime_failover_count", 0) or 0),
        },
        "workflow_coordination": workflow_coordination,
        "distributed_governance": distributed_governance,
        "cognitive_diagnostics": cognitive_diagnostics,
        "continuity": {
            "assistant_continuity_survives_restart": True,
            "reconnect_continuity": True,
            "replay_continuity": True,
            "degraded_mode_state": "healthy" if len(degraded_reasons) == 0 else "degraded",
            "degraded_mode_reasons": degraded_reasons,
        },
        "operational_state_summary": {
            "state": _normalize_operational_state(overall_raw_state),
            "raw_state": str(overall_raw_state),
            "allowed_states": sorted(list(_ALLOWED_OPERATIONAL_STATES)),
            "modules": {
                "orchestration": module_orchestration,
                "compliance": module_compliance,
            },
            "dispatch_continuity_safe": {
                "value": bool(dispatch_continuity_safe),
                "message": (
                    "Core dispatch continuity is protected."
                    if dispatch_continuity_safe
                    else "Core dispatch continuity is constrained and under active supervision."
                ),
            },
            "ride_operations_active": {
                "value": bool(ride_operations_active),
                "message": (
                    "Ride operations remain active."
                    if ride_operations_active
                    else "Ride operations are active in constrained recovery mode."
                ),
            },
        },
        "health": health_snapshot,
    }


@router.get("/ops/workflow-coordination-diagnostics")
def get_workflow_coordination_diagnostics(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
):
    """Workflow coordination diagnostics for supervised autonomous runtime execution."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    diagnostics: dict[str, Any] = {
        "organization_id": effective_org_id,
        "active_workflow_count": 0,
        "queued_task_count": 0,
        "resumed_workflow_count": 0,
        "retry_attempts": 0,
        "interrupted_execution_recovery_count": 0,
        "workflow_completion_ratio": 0.0,
        "workflow_failure_ratio": 0.0,
        "checkpoint_restore_count": 0,
        "orphan_workflow_cleanup_count": 0,
        "active_chains": [],
    }
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        diagnostics = get_runtime_governor().get_workflow_coordination_diagnostics(effective_org_id)
    except Exception:
        diagnostics = diagnostics
    diagnostics["generated_at"] = now().isoformat()
    diagnostics["supervised_autonomy"] = {
        "bounded_retries": True,
        "recoverable_chains": True,
        "checkpointed": True,
        "replay_safe": True,
    }
    return diagnostics


@router.get("/ops/cognitive-diagnostics")
def get_cognitive_diagnostics(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Structured cognitive diagnostics for supervised operational decisioning."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    diagnostics = OperationalCognitionEngine.build_snapshot(
        db,
        organization_id=effective_org_id,
        role=str(user.role or "dispatcher"),
    )
    diagnostics["generated_at"] = now().isoformat()
    diagnostics["cognition_governance"] = {
        "supervised": True,
        "recommendation_only": True,
        "approval_governed": True,
        "bounded_retries": True,
        "no_self_modification": True,
    }
    return diagnostics


@router.get("/ops/distributed-governance-diagnostics")
def get_distributed_governance_diagnostics(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
):
    """Distributed runtime governance diagnostics for worker ownership and failover."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    diagnostics: dict[str, Any] = {
        "organization_id": effective_org_id,
        "active_runtimes": 0,
        "workflow_ownership_map": [],
        "worker_heartbeat_health": [],
        "distributed_queue_depth": 0,
        "task_reassignment_count": 0,
        "throttled_execution_count": 0,
        "runtime_failover_count": 0,
        "isolation_violation_count": 0,
        "workload_pressure": {"score": 0.0, "warnings": [], "priority_distribution": {}},
        "recovery_failover_ratios": {"completion_ratio": 0.0, "failure_ratio": 0.0},
        "leases": 0,
        "history_depth": 0,
    }
    try:
        from app.modules.health_isf.runtime_governor import get_runtime_governor

        diagnostics = get_runtime_governor().get_distributed_governance_diagnostics(effective_org_id)
    except Exception:
        diagnostics = diagnostics
    diagnostics["generated_at"] = now().isoformat()
    diagnostics["supervised_isolation"] = {
        "ownership_leases": True,
        "worker_heartbeats": True,
        "failover_reassignment": True,
        "priority_routing": True,
    }
    return diagnostics


@router.get("/ops/alerts", response_model=list[OperationalAlertResponse])
def get_operational_alerts(
    organization_id: str | None = Query(None),
    persist: bool = Query(False),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Compute operational alerts and optionally persist them for auditability."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    queue_stats = RetryQueueService.get_queue_stats(db, organization_id=effective_org_id)
    websocket_stats = get_broadcaster().get_websocket_health_stats(organization_id=effective_org_id)
    alerts = evaluate_operational_alerts(
        db,
        queue_stats=queue_stats,
        websocket_stats=websocket_stats,
        organization_id=effective_org_id,
    )

    if persist and effective_org_id:
        ensure_admin_action(user)
        for alert in alerts:
            OperationalAlertService.log_alert(
                db,
                organization_id=effective_org_id,
                alert_type=alert["type"],
                severity=alert["severity"],
                message=alert["message"],
                payload=alert["details"],
            )
            SecurityAuditService.log_action(
                db,
                organization_id=effective_org_id,
                action_type="admin_alert_persist",
                actor_user_id=user.user_id,
                details=alert,
            )

    return [OperationalAlertResponse(**item) for item in alerts]


@router.post("/ops/command-center/incidents/refresh")
def refresh_command_center_incidents(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Refreshes live incident detection and persists/upserts alert pipeline state."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ensure_admin_action(user)
    payload = OperationalCommandCenterService.refresh_alert_pipeline(
        db,
        organization_id=effective_org_id,
        actor_user_id=user.user_id,
    )
    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="command_center_incident_refresh",
        actor_user_id=user.user_id,
        details={"incident_count": payload.get("incident_count"), "persisted_alert_count": payload.get("persisted_alert_count")},
    )
    return payload


@router.get("/ops/command-center/runtime")
def get_command_center_runtime(
    organization_id: str | None = Query(None),
    auto_refresh_incidents: bool = Query(False),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Backend-authoritative command-center runtime snapshot for distributed operations."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if auto_refresh_incidents:
        OperationalCommandCenterService.refresh_alert_pipeline(
            db,
            organization_id=effective_org_id,
            actor_user_id=user.user_id,
        )
    return OperationalCommandCenterService.build_runtime_snapshot(db, organization_id=effective_org_id)


@router.get("/ops/command-center/orchestration")
def get_command_center_orchestration(
    organization_id: str | None = Query(None),
    execute_cycle: bool = Query(False),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Replay-safe automation snapshot sourced from backend orchestration audit truth."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    incidents = OperationalCommandCenterService.detect_live_incidents(db, organization_id=effective_org_id)
    if execute_cycle:
        automation = OperationalOrchestrationResilienceService.execute_automation_cycle(
            db,
            organization_id=effective_org_id,
            incidents=incidents,
            actor_user_id=user.user_id,
        )
    else:
        automation = OperationalOrchestrationResilienceService.latest_automation_projection(
            db,
            organization_id=effective_org_id,
            incidents=incidents,
        )
    return {
        "organization_id": effective_org_id,
        "generated_at": now().isoformat(),
        "incidents": incidents,
        "automation": automation,
        "backend_authoritative": True,
    }


@router.post("/ops/command-center/orchestration/execute")
def execute_command_center_orchestration(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Force an immediate orchestration cycle for escalation, recommendation, and resilience management."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ensure_admin_action(user)
    incidents = OperationalCommandCenterService.detect_live_incidents(db, organization_id=effective_org_id)
    automation = OperationalOrchestrationResilienceService.execute_automation_cycle(
        db,
        organization_id=effective_org_id,
        incidents=incidents,
        actor_user_id=user.user_id,
    )

    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="command_center_orchestration_execute",
        actor_user_id=user.user_id,
        details={
            "incident_count": len(incidents),
            "escalations": len(automation.get("automated_incident_escalations") or []),
            "recommendations": len(automation.get("dispatch_recommendations") or []),
            "recovery_operations": len(automation.get("automated_recovery_operations") or []),
            "resilience_state": automation.get("resilience_state_machine", {}).get("state"),
        },
    )
    return {
        "organization_id": effective_org_id,
        "generated_at": now().isoformat(),
        "incidents": incidents,
        "automation": automation,
        "backend_authoritative": True,
        "replay_safe": True,
    }


@router.get("/ops/command-center/alerts/history")
def get_command_center_alert_history(
    organization_id: str | None = Query(None),
    state: str | None = Query(None),
    severity: str | None = Query(None),
    limit: int = Query(200, ge=1, le=1000),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Persistent operational alert history with lifecycle and escalation metadata."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rows = OperationalAlertService.list_alert_history(
        db,
        organization_id=effective_org_id,
        state=state,
        severity=severity,
        limit=limit,
    )
    return {
        "organization_id": effective_org_id,
        "generated_at": now().isoformat(),
        "count": len(rows),
        "alerts": [
            {
                "id": row.id,
                "alert_type": row.alert_type,
                "severity": row.severity,
                "state": row.alert_state,
                "incident_key": row.incident_key,
                "message": row.message,
                "occurrence_count": int(row.occurrence_count or 0),
                "escalation_level": int(row.escalation_level or 0),
                "acknowledged_by_user_id": row.acknowledged_by_user_id,
                "acknowledged_at": row.acknowledged_at.isoformat() if row.acknowledged_at else None,
                "escalated_at": row.escalated_at.isoformat() if row.escalated_at else None,
                "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            }
            for row in rows
        ],
    }


@router.post("/ops/command-center/alerts/{alert_id}/acknowledge")
def acknowledge_command_center_alert(
    alert_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Acknowledge an operational alert while keeping immutable alert history."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    alert = OperationalAlertService.acknowledge_alert(
        db,
        organization_id=effective_org_id,
        alert_id=alert_id,
        acknowledged_by_user_id=user.user_id,
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="command_center_alert_acknowledged",
        actor_user_id=user.user_id,
        details={"alert_id": alert.id, "incident_key": alert.incident_key},
    )
    return {"status": "acknowledged", "alert_id": alert.id, "state": alert.alert_state}


@router.post("/ops/command-center/alerts/{alert_id}/resolve")
def resolve_command_center_alert(
    alert_id: str,
    organization_id: str | None = Query(None),
    note: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Resolve an operational alert and preserve chain-of-custody metadata."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ensure_admin_action(user)
    alert = OperationalAlertService.resolve_alert(
        db,
        organization_id=effective_org_id,
        alert_id=alert_id,
        resolved_by_user_id=user.user_id,
        resolution_note=note,
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="command_center_alert_resolved",
        actor_user_id=user.user_id,
        details={"alert_id": alert.id, "incident_key": alert.incident_key, "note": note},
    )
    return {"status": "resolved", "alert_id": alert.id, "state": alert.alert_state}


@router.post("/ops/command-center/alerts/{alert_id}/escalate")
def escalate_command_center_alert(
    alert_id: str,
    organization_id: str | None = Query(None),
    summary: str | None = Body(default=None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Escalate an alert through command-center escalation chain."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ensure_admin_action(user)
    alert = OperationalAlertService.escalate_alert(
        db,
        organization_id=effective_org_id,
        alert_id=alert_id,
        escalated_by_user_id=user.user_id,
        summary=summary,
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")

    OperationalSynchronizationEngine.publish_event(
        organization_id=effective_org_id,
        event_type=OperationalEventType.ESCALATION,
        payload={
            "alert_id": alert.id,
            "incident_key": alert.incident_key,
            "summary": summary or "command_center_escalation",
            "escalation_level": int(alert.escalation_level or 0),
            "severity": alert.severity,
        },
        role_scope=["dispatcher", "admin", "staff"],
        source_nonce=f"alert_escalation:{alert.id}:{int(_as_utc_datetime(now()).timestamp())}",
    )

    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="command_center_alert_escalated",
        actor_user_id=user.user_id,
        details={"alert_id": alert.id, "incident_key": alert.incident_key, "escalation_level": alert.escalation_level},
    )
    return {
        "status": "escalated",
        "alert_id": alert.id,
        "state": alert.alert_state,
        "escalation_level": int(alert.escalation_level or 0),
    }


@router.get("/ops/dashboard", response_model=OperationalDashboardResponse)
def get_operational_dashboard(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Live operational dashboard payload for metrics panel and charts."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return OperationalDashboardResponse(**build_operational_dashboard(db, organization_id=effective_org_id))


@router.post("/transport/routes/plan")
async def plan_transport_route(
    payload: RoutePlanRequest,
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, payload.ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    route = ProductionTransportOps.upsert_route_plan(
        db,
        organization_id=ride.organization_id,
        ride_id=payload.ride_id,
        map_provider=payload.map_provider,
        origin_latitude=payload.origin_latitude,
        origin_longitude=payload.origin_longitude,
        destination_latitude=payload.destination_latitude,
        destination_longitude=payload.destination_longitude,
        traffic_mode=payload.traffic_mode,
        deviation_threshold_meters=payload.deviation_threshold_meters,
    )

    await get_emitter().emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="route_plan_updated",
        actor_user_id=_user.id,
        details={
            "ride_id": payload.ride_id,
            "route_reference": route.route_reference,
            "map_provider": route.map_provider,
            "eta_minutes": route.estimated_duration_minutes,
        },
    )

    metrics = get_operational_metrics_registry()
    metrics.increment("phase8b.route_plans.updated")
    metrics.record_event_ts("phase8b_transport")

    return {
        "ride_id": route.ride_id,
        "route_reference": route.route_reference,
        "map_provider": route.map_provider,
        "estimated_distance_miles": route.estimated_distance_miles,
        "estimated_duration_minutes": route.estimated_duration_minutes,
        "traffic_multiplier": route.traffic_multiplier,
        "deviation_threshold_meters": route.deviation_threshold_meters,
    }


@router.post("/transport/location/ingest")
async def ingest_driver_location(
    payload: DriverLocationIngestRequest,
    _user=Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, payload.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)

    if payload.ride_id:
        ride = service.get_ride_by_id(db, payload.ride_id)
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        enforce_entity_tenant(user, ride.organization_id)

    try:
        result = ProductionTransportOps.ingest_driver_location(
            db,
            organization_id=driver.organization_id,
            driver_id=payload.driver_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            heading=payload.heading,
            speed_kph=payload.speed_kph,
            accuracy_meters=payload.accuracy_meters,
            ride_id=payload.ride_id,
            device_id=payload.device_id,
            source=payload.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await get_emitter().emit_dispatch_changed(
        organization_id=driver.organization_id,
        event_name="driver_location_update",
        actor_user_id=_user.id,
        details={
            "driver_id": payload.driver_id,
            "ride_id": payload.ride_id,
            "eta_minutes": result.get("eta_minutes"),
            "is_deviated": result.get("is_deviated"),
        },
    )

    metrics = get_operational_metrics_registry()
    metrics.increment("phase8b.location.ingested")
    metrics.record_event_ts("phase8b_transport")

    return result


@router.get("/transport/rides/{ride_id}/route")
async def get_ride_route_snapshot(
    ride_id: str,
    _user=Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    try:
        return ProductionTransportOps.get_route_snapshot(
            db,
            organization_id=ride.organization_id,
            ride_id=ride_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/mobile/reconnect/snapshot")
async def get_mobile_reconnect_snapshot(
    payload: MobileReconnectRequest,
    _user=Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, payload.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)

    try:
        snapshot = ProductionTransportOps.mobile_reconnect_snapshot(
            db,
            organization_id=driver.organization_id,
            driver_id=payload.driver_id,
            last_ping_id=payload.last_ping_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metrics = get_operational_metrics_registry()
    metrics.increment("phase8b.mobile.reconnect_requests")
    metrics.record_event_ts("phase8b_mobile")
    return snapshot


@router.post("/payments/intents")
async def create_payment_intent(
    payload: PaymentIntentRequest,
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, payload.ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    try:
        tx = ProductionPaymentOps.create_payment_intent(
            db,
            organization_id=ride.organization_id,
            ride_id=payload.ride_id,
            actor_user_id=_user.id,
            amount_usd=payload.amount_usd,
            tip_amount_usd=payload.tip_amount_usd,
            surcharge_usd=payload.surcharge_usd,
            currency=payload.currency,
            invoice_reference=payload.invoice_reference,
            capture_immediately=payload.capture_immediately,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await get_emitter().emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="payment_intent_created",
        actor_user_id=_user.id,
        details={
            "payment_id": tx.id,
            "ride_id": tx.ride_id,
            "status": tx.status,
            "amount_usd": tx.amount_usd,
        },
    )

    metrics = get_operational_metrics_registry()
    metrics.increment("phase8b.payments.intents_created")
    metrics.record_event_ts("phase8b_payments")

    return {
        "id": tx.id,
        "ride_id": tx.ride_id,
        "gateway": tx.gateway,
        "gateway_payment_intent_id": tx.gateway_payment_intent_id,
        "status": tx.status,
        "amount_usd": tx.amount_usd,
        "currency": tx.currency,
        "settlement_status": tx.settlement_status,
        "invoice_reference": tx.invoice_reference,
    }


@router.post("/payments/capture")
async def capture_payment_intent(
    payload: PaymentCaptureRequest,
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    tx = db.query(HealthISFPaymentTransaction).filter(HealthISFPaymentTransaction.id == payload.payment_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Payment transaction not found")
    enforce_entity_tenant(user, tx.organization_id)

    try:
        tx = ProductionPaymentOps.capture_payment(
            db,
            organization_id=tx.organization_id,
            payment_id=payload.payment_id,
            actor_user_id=_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metrics = get_operational_metrics_registry()
    metrics.increment("phase8b.payments.captured")
    metrics.record_event_ts("phase8b_payments")

    return {
        "id": tx.id,
        "status": tx.status,
        "paid_at": tx.paid_at.isoformat() if tx.paid_at else None,
        "settlement_status": tx.settlement_status,
    }


@router.post("/payments/settle")
async def settle_payment(
    payload: PaymentSettlementRequest,
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    tx = db.query(HealthISFPaymentTransaction).filter(HealthISFPaymentTransaction.id == payload.payment_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Payment transaction not found")
    enforce_entity_tenant(user, tx.organization_id)

    try:
        summary = ProductionPaymentOps.settle_payment(
            db,
            organization_id=tx.organization_id,
            payment_id=payload.payment_id,
            driver_ratio=payload.driver_ratio,
            provider_ratio=payload.provider_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    metrics = get_operational_metrics_registry()
    metrics.increment("phase8b.payments.settled")
    metrics.record_event_ts("phase8b_payments")
    return summary


@router.get("/payments/rides/{ride_id}")
async def list_ride_payments(
    ride_id: str,
    _user=Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    rows = (
        db.query(HealthISFPaymentTransaction)
        .filter(
            HealthISFPaymentTransaction.organization_id == ride.organization_id,
            HealthISFPaymentTransaction.ride_id == ride_id,
        )
        .order_by(HealthISFPaymentTransaction.created_at.desc())
        .all()
    )

    return [
        {
            "id": row.id,
            "ride_id": row.ride_id,
            "gateway": row.gateway,
            "status": row.status,
            "amount_usd": row.amount_usd,
            "currency": row.currency,
            "settlement_status": row.settlement_status,
            "invoice_reference": row.invoice_reference,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        }
        for row in rows
    ]


@router.get("/auth/session-authority")
def get_session_authority(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    request: Request = cast(Request, None),
):
    """Resolve effective tenant scope and role authority for enterprise runtime calls."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    auth_header = ""
    if request is not None:
        auth_header = str(request.headers.get("Authorization") or "")

    payload: dict[str, Any] = {}
    if auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            payload = decode_access_token(token)
            runtime_manager = get_live_transport_runtime_manager()

    authority = _build_session_authority(
        UserContext(
            user_id=user.user_id,
            email=user.email,
            role=user.role,
            organization_id=effective_org_id,
        ),
        payload,
    )
    authority["session_valid"] = True
    authority["organization_id"] = effective_org_id
    return authority


@router.get("/intelligence/summary", response_model=IntelligenceSummaryResponse)
def get_intelligence_summary(
    organization_id: str | None = Query(None),
    ride_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Tenant-scoped operational intelligence summary for dispatch leaders."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = OperationalIntelligenceService.summarize(db, effective_org_id, ride_id=ride_id)
    return IntelligenceSummaryResponse(**payload)


@router.get("/intelligence/anomalies", response_model=IntelligenceAnomalyResponse)
def get_intelligence_anomalies(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Tenant-scoped anomaly detection output."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    anomalies = OperationalIntelligenceService.detect_anomalies(db, effective_org_id)
    explanations = [item["message"] for item in anomalies]
    return IntelligenceAnomalyResponse(
        organization_id=effective_org_id,
        generated_at=now().isoformat(),
        anomalies=anomalies,
        explanations=explanations,
    )


@router.get("/intelligence/recommendations", response_model=IntelligenceRecommendationResponse)
def get_intelligence_recommendations(
    organization_id: str | None = Query(None),
    ride_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Tenant-scoped recommendation payloads for dispatchers."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = OperationalIntelligenceService.build_recommendations(db, effective_org_id, ride_id=ride_id)
    return IntelligenceRecommendationResponse(**payload)


@router.get("/intelligence/risk", response_model=IntelligenceRiskResponse)
def get_intelligence_risk(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Tenant-scoped operational risk scoring."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = OperationalIntelligenceService.build_risk_profile(db, effective_org_id)
    return IntelligenceRiskResponse(**payload)


@router.get("/ai-dispatch/snapshot", response_model=AutonomousOperationsSnapshotResponse)
async def get_ai_dispatch_snapshot(
    organization_id: str | None = Query(None),
    ride_id: str | None = Query(None),
    publish: bool = Query(True),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return a composed AI dispatch snapshot for voice, timeline, alerts, and analytics."""
    logger.info("Reached ai-dispatch snapshot route")
    logger.info("Current user role: %s", user.role)
    logger.info("Reached permissions lookup step for ai-dispatch snapshot")
    effective_org_id = enforce_tenant_scope(user, organization_id)
    logger.info("Tenant scope resolved for ai-dispatch snapshot: %s", effective_org_id)
    payload = AIDispatchOrchestrationService.build_operations_snapshot(
        db,
        organization_id=effective_org_id,
        ride_id=ride_id,
    )
    if publish:
        await AIDispatchOrchestrationService.publish_operations_update(
            organization_id=effective_org_id,
            snapshot=payload,
        )
    return AutonomousOperationsSnapshotResponse(**payload)


@router.get("/ai-dispatch/timeline", response_model=list[OperationalTimelineItemResponse])
def get_ai_dispatch_timeline(
    organization_id: str | None = Query(None),
    ride_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return a unified operational timeline for dispatcher replay and auditing."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = AIDispatchOrchestrationService.build_timeline(
        db,
        organization_id=effective_org_id,
        ride_id=ride_id,
        limit=limit,
    )
    return [OperationalTimelineItemResponse(**item) for item in payload]


@router.get("/ai-dispatch/notifications", response_model=list[AIDispatchNotificationResponse])
def get_ai_dispatch_notifications(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return in-app enterprise notifications synthesized from alerts, AI, and websocket health."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    snapshot = AIDispatchOrchestrationService.build_operations_snapshot(db, organization_id=effective_org_id)
    return [AIDispatchNotificationResponse(**item) for item in snapshot["notifications"]]


@router.post("/ai-dispatch/voice/command", response_model=AIDispatchVoiceCommandResponse)
def parse_ai_dispatch_voice_command(
    payload: AIDispatchVoiceCommandRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Parse dispatcher voice transcripts into safe, tenant-scoped operational intents."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    result = AIDispatchOrchestrationService.parse_voice_command(
        db,
        organization_id=effective_org_id,
        transcript=payload.transcript,
        ride_id=payload.ride_id,
    )
    return AIDispatchVoiceCommandResponse(**result)


@router.post("/ai-dispatch/intake/assist", response_model=AIDispatchIntakeAssistResponse)
def assist_ai_dispatch_intake(
    payload: AIDispatchIntakeAssistRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return additive AI intake guidance without mutating ride intake workflows."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    result = AIDispatchOrchestrationService.assist_intake(
        db,
        organization_id=effective_org_id,
        payload=payload.model_dump(),
    )
    return AIDispatchIntakeAssistResponse(**result)


@router.post("/ai-dispatch/resilience/replay", response_model=WorkflowOperationResponse)
async def replay_ai_dispatch_dead_letters(
    payload: WorkflowReplayRequest,
    _user = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Replay dead-letter dispatch events to support resilient dispatcher recovery."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    result = await WorkflowOrchestrationService.replay_dead_letters(
        db,
        organization_id=effective_org_id,
        actor_user_id=user.user_id,
        limit=payload.limit,
    )
    return WorkflowOperationResponse(**result)


@router.post("/intelligence/reanalyze", response_model=IntelligenceReanalyzeResponse)
async def reanalyze_intelligence(
    payload: IntelligenceReanalyzeRequest,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Recompute intelligence outputs and optionally broadcast them to realtime subscribers."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    if payload.thresholds is None:
        thresholds_payload: dict[str, Any] = {}
    else:
        thresholds_payload = payload.thresholds.model_dump()
    thresholds = RuntimeIntelligenceThresholds(**thresholds_payload)

    summary = OperationalIntelligenceService.summarize(db, effective_org_id, ride_id=payload.ride_id, thresholds=thresholds)
    anomalies = OperationalIntelligenceService.detect_anomalies(db, effective_org_id, thresholds=thresholds)
    recommendations = OperationalIntelligenceService.build_recommendations(db, effective_org_id, ride_id=payload.ride_id, thresholds=thresholds)
    risk = OperationalIntelligenceService.build_risk_profile(db, effective_org_id, thresholds=thresholds, anomalies=anomalies)

    OperationalIntelligenceService.persist_reanalysis_audit(
        db,
        organization_id=effective_org_id,
        actor_user_id=user.user_id,
        summary=summary,
        anomalies=anomalies,
        recommendations=recommendations,
        risk=risk,
    )

    if payload.broadcast:
        await OperationalIntelligenceService.broadcast_intelligence_snapshot(
            get_broadcaster(),
            organization_id=effective_org_id,
            summary=summary,
            anomalies=anomalies,
            recommendations=recommendations,
            risk=risk,
        )

    return IntelligenceReanalyzeResponse(
        summary=IntelligenceSummaryResponse(**summary),
        anomalies=IntelligenceAnomalyResponse(
            organization_id=effective_org_id,
            generated_at=now().isoformat(),
            anomalies=anomalies,
            explanations=[item["message"] for item in anomalies],
        ),
        recommendations=IntelligenceRecommendationResponse(**recommendations),
        risk=IntelligenceRiskResponse(**risk),
    )


@router.get("/workflows", response_model=list[WorkflowExecutionResponse])
def list_workflows(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=250),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return workflow execution history for the tenant."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return WorkflowOrchestrationService.list_workflows(db, organization_id=effective_org_id, limit=limit)


@router.get("/workflows/incidents", response_model=list[WorkflowIncidentResponse])
def list_workflow_incidents(
    organization_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=250),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return workflow incidents for the tenant."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return WorkflowOrchestrationService.list_incidents(db, organization_id=effective_org_id, status=status, limit=limit)


@router.get("/workflows/escalations", response_model=list[WorkflowEscalationResponse])
def list_workflow_escalations(
    organization_id: str | None = Query(None),
    status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=250),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return workflow escalations for the tenant."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return WorkflowOrchestrationService.list_escalations(db, organization_id=effective_org_id, status=status, limit=limit)


@router.post("/workflows/recover", response_model=WorkflowOperationResponse)
async def recover_workflows(
    payload: WorkflowRecoverRequest,
    _user=Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Run the automated recovery workflow for stuck or delayed rides."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    response = await WorkflowOrchestrationService.run_recovery(
        db,
        organization_id=effective_org_id,
        ride_id=payload.ride_id,
        actor_user_id=_user.id,
        note=payload.note,
        dry_run=payload.dry_run,
    )
    return WorkflowOperationResponse(**response)


@router.post("/workflows/reassign", response_model=WorkflowOperationResponse)
async def reassign_workflow(
    payload: WorkflowReassignRequest,
    _user=Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Generate or execute a reassignment workflow for a ride."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    response = await WorkflowOrchestrationService.run_reassign(
        db,
        organization_id=effective_org_id,
        ride_id=payload.ride_id,
        actor_user_id=_user.id,
        driver_id=payload.driver_id,
        suggest_only=payload.suggest_only,
        approval_override=payload.approval_override,
    )
    return WorkflowOperationResponse(**response)


@router.post("/workflows/replay", response_model=WorkflowOperationResponse)
async def replay_workflow(
    payload: WorkflowReplayRequest,
    _user=Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Replay dead-letter events through the retry queue."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    response = await WorkflowOrchestrationService.replay_dead_letters(
        db,
        organization_id=effective_org_id,
        actor_user_id=_user.id,
        limit=payload.limit,
    )
    return WorkflowOperationResponse(**response)


@router.post("/workflows/escalate", response_model=WorkflowOperationResponse)
async def escalate_workflow(
    payload: WorkflowEscalateRequest,
    _user=Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Create or route a workflow escalation for an incident or ride."""
    effective_org_id = enforce_tenant_scope(user, payload.organization_id)
    response = await WorkflowOrchestrationService.escalate_incident(
        db,
        organization_id=effective_org_id,
        actor_user_id=_user.id,
        incident_id=payload.incident_id,
        ride_id=payload.ride_id,
        summary=payload.summary,
        severity=payload.severity,
        target_role=payload.target_role,
        escalation_level=payload.escalation_level,
        details=payload.details,
    )
    try:
        SecurityAuditService.log_action(
            db,
            organization_id=effective_org_id,
            action_type="workflow_escalated",
            actor_user_id=_user.id,
            ride_id=payload.ride_id,
            details={
                "incident_id": payload.incident_id,
                "ride_id": payload.ride_id,
                "severity": payload.severity,
                "target_role": payload.target_role,
                "escalation_level": payload.escalation_level,
                "summary": payload.summary,
            },
        )
    except Exception:
        logger.warning("Escalation audit log failed", exc_info=True)
    return WorkflowOperationResponse(**response)


@router.post("/ops/retry/process")
async def process_retry_queue(
    organization_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Process due retry events and route exhausted retries to dead-letter queue."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    emitter = get_emitter()
    due_events = RetryQueueService.get_due_events(db, limit=limit)
    processed = 0
    failed = 0

    for item in due_events:
        if item.organization_id != effective_org_id:
            continue

        payload = {}
        try:
            payload = json.loads(item.payload)
        except Exception:
            payload = {}

        try:
            if item.event_type == EventType.RIDE_STATUS_CHANGED.value:
                await emitter.emit_ride_status_changed(
                    organization_id=item.organization_id,
                    ride_id=item.ride_id or payload.get("ride_id", ""),
                    from_status=payload.get("from_status"),
                    to_status=payload.get("to_status", "unknown"),
                )
            elif item.event_type == EventType.RIDE_ASSIGNED.value:
                await emitter.emit_ride_assigned(
                    organization_id=item.organization_id,
                    ride_id=item.ride_id or payload.get("ride_id", ""),
                    driver_id=item.driver_id or payload.get("driver_id", ""),
                    driver_name=payload.get("driver_name"),
                )
            elif item.event_type == EventType.DRIVER_STATUS_CHANGED.value:
                await emitter.emit_driver_status_changed(
                    organization_id=item.organization_id,
                    driver_id=item.driver_id or payload.get("driver_id", ""),
                    from_status=payload.get("from_status"),
                    to_status=payload.get("to_status", "unknown"),
                )
            else:
                raise ValueError(f"Unsupported retry event type: {item.event_type}")

            RetryQueueService.mark_retry_success(db, item.id)
            processed += 1
        except Exception as exc:
            RetryQueueService.mark_retry_failure(db, item.id, str(exc))
            failed += 1

    log_operational_event(
        "dispatch.retry_queue.processed",
        organization_id=effective_org_id,
        processed=processed,
        failed=failed,
        requested_by=_user.id,
    )
    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="admin_retry_process",
        actor_user_id=user.user_id,
        details={"processed": processed, "failed": failed},
    )
    return {
        "processed": processed,
        "failed": failed,
        "queue_stats": RetryQueueService.get_queue_stats(db, organization_id=effective_org_id),
    }


@router.post("/ops/maintenance/cleanup")
async def run_operational_cleanup(
    organization_id: str | None = Query(None),
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Run maintenance cleanup for stale websocket and expired resilience artifacts."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    broadcaster = get_broadcaster()
    await broadcaster.cleanup_stale_connections(timeout_seconds=300)

    expired_locks = ConcurrentAssignmentService.force_cleanup_expired_locks(db)
    expired_idempotency = IdempotencyService.cleanup_expired_keys(db)

    queue_stats = RetryQueueService.get_queue_stats(db, organization_id=effective_org_id)
    websocket_stats = broadcaster.get_websocket_health_stats(organization_id=effective_org_id)

    log_operational_event(
        "dispatch.maintenance.cleanup",
        organization_id=effective_org_id,
        expired_locks=expired_locks,
        expired_idempotency=expired_idempotency,
        queue=queue_stats,
    )
    SecurityAuditService.log_action(
        db,
        organization_id=effective_org_id,
        action_type="admin_cleanup",
        actor_user_id=user.user_id,
        details={"expired_locks": expired_locks, "expired_idempotency": expired_idempotency},
    )

    return {
        "expired_locks": expired_locks,
        "expired_idempotency": expired_idempotency,
        "queue": queue_stats,
        "websocket": websocket_stats,
    }


# ── Rides Endpoints ───────────────────────────────────────────────────────────

@router.post("/customer-requests", response_model=CustomerRideRequestResponse, status_code=201)
def create_customer_ride_request(
    payload: CustomerRideRequestCreateRequest,
    request: Request,
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    import time

    from app.modules.health_isf.rider_request_timing_log import record_rider_request_timing

    route_started = time.perf_counter()
    organization_id = enforce_tenant_scope(user, user.organization_id)
    auth_started = time.perf_counter()
    auth_decision = evaluate_customer_request_authorization(
        organization_id=organization_id,
        rider_name=payload.rider_name,
        ride_type=payload.ride_type,
        scheduled_time=payload.scheduled_time,
        recurring=payload.recurring,
    )
    record_rider_request_timing(
        stage="authorization_adapter",
        duration_ms=int((time.perf_counter() - auth_started) * 1000),
        organization_id=organization_id,
    )
    if auth_decision.hard_block:
        raise HTTPException(status_code=403, detail=auth_decision.reason)

    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if not idempotency_key:
        client_key = str(payload.client_request_key or "").strip()
        if client_key:
            idempotency_key = client_key[:128]

    if idempotency_key:
        idem_started = time.perf_counter()
        existing_key = IdempotencyService.get_key(db, idempotency_key)
        if existing_key and existing_key.resource_id:
            existing = service.get_customer_ride_request_by_id(db, existing_key.resource_id)
            if existing:
                enforce_entity_tenant(user, existing.organization_id)
                record_rider_request_timing(
                    stage="idempotency_cache_hit",
                    duration_ms=int((time.perf_counter() - idem_started) * 1000),
                    idempotency_key=idempotency_key,
                    ride_id=str(existing.ride_id),
                    request_id=str(existing.id),
                    organization_id=organization_id,
                    http_status=201,
                )
                return _serialize_customer_request(existing)
        if not existing_key:
            reserved = IdempotencyService.reserve_key(
                db,
                idempotency_key=idempotency_key,
                scope="customer_ride_request",
            )
            if not reserved:
                raced_key = IdempotencyService.get_key(db, idempotency_key)
                if raced_key and raced_key.resource_id:
                    existing = service.get_customer_ride_request_by_id(db, raced_key.resource_id)
                    if existing:
                        enforce_entity_tenant(user, existing.organization_id)
                        return _serialize_customer_request(existing)
                raise HTTPException(
                    status_code=409,
                    detail="Identical rider request is already being processed; retry with the same idempotency key shortly",
                )
        record_rider_request_timing(
            stage="idempotency_reserve",
            duration_ms=int((time.perf_counter() - idem_started) * 1000),
            idempotency_key=idempotency_key,
            organization_id=organization_id,
        )

    create_started = time.perf_counter()
    try:
        request_row, ride = service.create_customer_ride_request(
            db,
            organization_id=organization_id,
            rider_name=payload.rider_name,
            rider_phone=payload.rider_phone,
            pickup_address=payload.pickup_address,
            dropoff_address=payload.dropoff_address,
            scheduled_time=payload.scheduled_time,
            ride_type=payload.ride_type,
            recurring=payload.recurring,
            recurring_pattern=payload.recurring_pattern,
            notes=payload.notes,
            submitted_by_user_id=user.user_id,
        )
    except ValueError as exc:
        if idempotency_key:
            IdempotencyService.delete_key(db, idempotency_key)
        record_rider_request_timing(
            stage="create_ride_transaction_failed",
            duration_ms=int((time.perf_counter() - create_started) * 1000),
            idempotency_key=idempotency_key or None,
            organization_id=organization_id,
            error=str(exc),
            http_status=400,
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    record_rider_request_timing(
        stage="create_ride_transaction",
        duration_ms=int((time.perf_counter() - create_started) * 1000),
        idempotency_key=idempotency_key or None,
        ride_id=str(ride.id),
        request_id=str(request_row.id),
        organization_id=organization_id,
    )

    if idempotency_key:
        IdempotencyService.bind_resource(db, idempotency_key, str(request_row.id))

    _schedule_customer_request_side_effects(
        organization_id=organization_id,
        request_id=str(request_row.id),
        ride_id=str(ride.id),
        rider_phone=payload.rider_phone,
        actor_user_id=user.user_id,
        idempotency_key=idempotency_key,
        auth_decision_status=auth_decision.status,
        auth_decision_reason=auth_decision.reason,
        auth_decision_source=auth_decision.decision_source,
        ride_type=request_row.ride_type,
        scheduled_time_iso=request_row.scheduled_time.isoformat() if request_row.scheduled_time else None,
        dispatch_status=request_row.dispatch_status,
        passenger_name=ride.passenger_name,
        priority_score=float(ride.priority_score or 0.0),
        priority_tag=str(ride.priority_tag or "normal"),
        provider_id=str(ride.provider_id) if ride.provider_id else None,
    )

    db.refresh(request_row)
    record_rider_request_timing(
        stage="http_response_ready",
        duration_ms=int((time.perf_counter() - route_started) * 1000),
        idempotency_key=idempotency_key or None,
        ride_id=str(ride.id),
        request_id=str(request_row.id),
        organization_id=organization_id,
        http_status=201,
    )
    return _serialize_customer_request(request_row)


@router.get("/customer-requests/idempotency/{idempotency_key}", response_model=CustomerRideRequestResponse)
def get_customer_ride_request_by_idempotency(
    idempotency_key: str,
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Recover a submitted rider request after client timeout using the idempotency key."""
    key = (idempotency_key or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="idempotency_key is required")
    row = IdempotencyService.get_key(db, key)
    if not row:
        raise HTTPException(status_code=404, detail="No rider request found for idempotency key")
    if not row.resource_id:
        raise HTTPException(status_code=202, detail="Rider request is still being processed")
    existing = service.get_customer_ride_request_by_id(db, row.resource_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Rider request record missing for idempotency key")
    enforce_entity_tenant(user, existing.organization_id)
    return _serialize_customer_request(existing)


@router.get("/customer-requests", response_model=list[CustomerRideRequestResponse])
def list_customer_ride_requests(
    dispatch_status: str | None = Query(None),
    prioritize: bool = Query(True),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=300),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rows = service.list_customer_ride_requests(
        db,
        organization_id=effective_org_id,
        dispatch_status=dispatch_status,
        prioritize=prioritize,
        skip=skip,
        limit=limit,
    )
    return [_serialize_customer_request(row) for row in rows]


@router.get("/customer-requests/metrics", response_model=CustomerRideQueueMetricsResponse)
def get_customer_ride_request_metrics(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.get_customer_ride_queue_metrics(db, organization_id=effective_org_id)


@router.get("/customers/workspace/history")
def get_customer_workspace_history(
    rider_phone: str = Query(..., min_length=7, max_length=20),
    limit: int = Query(25, ge=1, le=100),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rows = service.list_customer_ride_requests_by_phone(
        db,
        organization_id=effective_org_id,
        rider_phone=rider_phone,
        limit=limit,
    )
    history = []
    for row in rows:
        item = _serialize_customer_request(row).model_dump()
        ride_id = str(item.get("ride_id") or "")
        if ride_id:
            ride = service.get_ride_by_id(db, ride_id)
            if ride:
                lifecycle = str(getattr(ride, "lifecycle_state", None) or ride.status or "")
                if lifecycle:
                    item["dispatch_status"] = lifecycle.lower()
        history.append(item)
    seen_ride_ids = {str(item.get("ride_id") or "") for item in history if item.get("ride_id")}
    for ride in service.list_rides_for_passenger_phone(
        db,
        organization_id=effective_org_id,
        rider_phone=rider_phone,
        limit=limit,
    ):
        if ride.id in seen_ride_ids:
            continue
        lifecycle = str(getattr(ride, "lifecycle_state", None) or ride.status or "pending")
        history.append(
            {
                "id": f"ride-{ride.id}",
                "organization_id": effective_org_id,
                "ride_id": ride.id,
                "rider_phone": rider_phone,
                "rider_name": ride.passenger_name,
                "pickup_address": ride.pickup_address,
                "dropoff_address": ride.dropoff_address,
                "ride_type": ride.service_type or "healthcare",
                "dispatch_status": lifecycle.lower(),
                "authorization_status": "approved",
                "created_at": ride.created_at.isoformat() if ride.created_at else None,
                "updated_at": ride.updated_at.isoformat() if ride.updated_at else None,
            }
        )
    history.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    history = history[:limit]
    return {
        "organization_id": effective_org_id,
        "rider_phone": rider_phone,
        "history": history,
    }


@router.get("/customers/workspace/active")
def get_customer_workspace_active_ride(
    rider_phone: str = Query(..., min_length=7, max_length=20),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ride = service.get_customer_active_ride_for_phone(
        db,
        organization_id=effective_org_id,
        rider_phone=rider_phone,
    )
    return {
        "organization_id": effective_org_id,
        "rider_phone": rider_phone,
        "active_ride": _ride_response_with_financials(db, ride).model_dump() if ride else None,
    }


@router.get("/customers/workspace/live-tracking", response_model=RiderLiveTrackingResponse)
def get_customer_workspace_live_tracking(
    rider_phone: str = Query(..., min_length=7, max_length=20),
    limit: int = Query(80, ge=1, le=300),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    ride = service.get_customer_active_ride_for_phone(
        db,
        organization_id=effective_org_id,
        rider_phone=rider_phone,
    )
    feed_rows = service.list_rider_event_feed(
        db,
        organization_id=effective_org_id,
        rider_phone=rider_phone,
        limit=limit,
    )
    return RiderLiveTrackingResponse(
        organization_id=effective_org_id,
        rider_phone=rider_phone,
        active_ride=_ride_response_with_financials(db, ride) if ride else None,
        timeline=[RiderEventFeedItem.model_validate(item) for item in feed_rows],
        eta_minutes=int(ride.estimated_duration_minutes) if ride and ride.estimated_duration_minutes else None,
    )


@router.post("/customers/workspace/{request_id}/cancel", response_model=CustomerRideRequestResponse)
async def cancel_customer_workspace_request(
    request_id: str,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    request_row = service.get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Customer request not found")
    _assert_request_dispatch_authorized(
        request_row,
        allowed_statuses={"approved", "dispatchable", "broadcasted", "accepted", "assigned"},
        operation="Driver assignment",
    )

    if str(request_row.dispatch_status or "").lower() in {"completed", "cancelled"}:
        return _serialize_customer_request(request_row)

    updated = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_row.id,
        dispatch_status="cancelled",
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Customer request not found")

    ride = service.get_ride_by_id(db, updated.ride_id)
    if ride and str(getattr(ride, "status", "")).lower() not in {RideStatus.CANCELLED.value, RideStatus.COMPLETED.value}:
        ride = service.update_ride_status(
            db,
            ride_id=ride.id,
            status=RideStatus.CANCELLED.value,
            actor_user_id=user.user_id,
        )

    emitter = get_emitter()
    await _emit_with_retry_queue(
        db=db,
        organization_id=effective_org_id,
        event_type="customer_request_status_changed",
        event_payload={
            "request_id": updated.id,
            "ride_id": updated.ride_id,
            "dispatch_status": updated.dispatch_status,
        },
        emit_callable=lambda: emitter.emit_ride_status_changed(
            organization_id=effective_org_id,
            ride_id=updated.ride_id,
            from_status="request",
            to_status=updated.dispatch_status,
            actor_user_id=user.user_id,
        ),
        idempotency_key=_event_key("customer_request_cancelled", updated.id, updated.ride_id),
        ride_id=updated.ride_id,
    )

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=updated.ride_id,
        event_name="ride-cancelled",
        actor_user_id=user.user_id,
        details={
            "request_id": updated.id,
            "ride_id": updated.ride_id,
            "dispatch_status": updated.dispatch_status,
        },
        request_id=_resolve_request_id(request),
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", updated.dispatch_status)),
        transition_reason="customer_workspace_cancel",
        assignment_transition_source="customer_workspace",
    )

    return _serialize_customer_request(updated)


@router.get("/providers/{provider_id}/transport-queue")
def get_provider_transport_queue(
    provider_id: str,
    include_completed: bool = Query(False),
    limit: int = Query(100, ge=1, le=300),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    provider = service.get_provider_by_id(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or provider.organization_id)
    queue = service.get_provider_transport_queue(
        db,
        organization_id=effective_org_id,
        provider_id=provider_id,
        include_completed=include_completed,
        limit=limit,
    )
    return {
        "organization_id": effective_org_id,
        "provider_id": provider_id,
        "queue_size": len(queue),
        "items": queue,
    }


@router.patch("/providers/{provider_id}/requests/{request_id}/notes", response_model=CustomerRideRequestResponse)
async def append_provider_request_note(
    provider_id: str,
    request_id: str,
    note: str = Query(..., min_length=1, max_length=1000),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    provider = service.get_provider_by_id(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or provider.organization_id)

    try:
        row = service.append_provider_request_note(
            db,
            organization_id=effective_org_id,
            request_id=request_id,
            note=note,
            actor_user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    emitter = get_emitter()
    await _emit_with_retry_queue(
        db=db,
        organization_id=effective_org_id,
        event_type="provider_request_note",
        event_payload={
            "provider_id": provider_id,
            "request_id": request_id,
            "ride_id": row.ride_id,
            "note": note,
        },
        emit_callable=lambda: emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="provider-note-added",
            actor_user_id=user.user_id,
            details={
                "provider_id": provider_id,
                "request_id": request_id,
                "ride_id": row.ride_id,
                "note": note,
            },
        ),
        idempotency_key=_event_key("provider_request_note", provider_id, request_id, note[:128]),
        ride_id=row.ride_id,
    )
    return _serialize_customer_request(row)


@router.post("/providers/{provider_id}/requests/{request_id}/ready", response_model=CustomerRideRequestResponse)
async def provider_mark_request_ready(
    provider_id: str,
    request_id: str,
    note: str | None = Query(None, max_length=1000),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    provider = service.get_provider_by_id(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or provider.organization_id)

    row = service.append_provider_request_note(
        db,
        organization_id=effective_org_id,
        request_id=request_id,
        note=note or "Facility marked patient ready for pickup",
        actor_user_id=user.user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=row.ride_id,
        event_name="provider-ready",
        actor_user_id=user.user_id,
        details={
            "provider_id": provider_id,
            "request_id": request_id,
            "ride_id": row.ride_id,
            "note": note,
        },
        request_id=f"provider_ready_{request_id}",
        lifecycle_state=row.dispatch_status,
        transition_reason="provider_ready",
        assignment_transition_source="provider_workspace",
    )
    increment_metric("health_isf.provider_ready")
    return _serialize_customer_request(row)


@router.post("/providers/{provider_id}/requests/{request_id}/delay", response_model=CustomerRideRequestResponse)
async def provider_mark_request_delay(
    provider_id: str,
    request_id: str,
    note: str = Query(..., min_length=1, max_length=1000),
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    provider = service.get_provider_by_id(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or provider.organization_id)

    row = service.append_provider_request_note(
        db,
        organization_id=effective_org_id,
        request_id=request_id,
        note=f"Facility delay notice: {note}",
        actor_user_id=user.user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=row.ride_id,
        event_name="provider-delay",
        actor_user_id=user.user_id,
        details={
            "provider_id": provider_id,
            "request_id": request_id,
            "ride_id": row.ride_id,
            "note": note,
        },
        request_id=f"provider_delay_{request_id}",
        lifecycle_state=row.dispatch_status,
        transition_reason="provider_delay",
        assignment_transition_source="provider_workspace",
    )
    increment_metric("health_isf.provider_delay")
    return _serialize_customer_request(row)


@router.get("/drivers/{driver_id}/active-offer")
def get_driver_active_offer(
    driver_id: str,
    organization_id: str | None = Query(None),
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform()),
    db: Session = Depends(get_db),
):
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or driver.organization_id)
    offer = service.get_driver_active_offer(
        db,
        organization_id=effective_org_id,
        driver_id=driver_id,
    )
    if not offer:
        workspace = service.get_driver_live_workspace_data(
            db,
            organization_id=effective_org_id,
            driver_id=driver_id,
        )
        assignment = workspace.get("assignment")
        if assignment and str(getattr(assignment, "assignment_state", "") or "").lower() in {
            DispatchAssignmentState.OFFERED.value,
            DispatchAssignmentState.ASSIGNED.value,
            DispatchAssignmentState.AWAITING_APPROVAL.value,
            DispatchAssignmentState.REASSIGNMENT_PENDING.value,
            DispatchAssignmentState.ACCEPTED.value,
        }:
            ride = workspace.get("ride")
            if ride and not service._is_ai_proof_ride(ride):
                offer = assignment
    offer_payload = _serialize_dispatch_offer(offer).model_dump() if offer else None
    if offer and offer_payload:
        ride = service.get_ride_by_id(db, offer.ride_id)
        if ride:
            offer_payload["passenger_name"] = ride.passenger_name
            offer_payload["passenger_phone"] = ride.passenger_phone
            offer_payload["pickup_address"] = ride.pickup_address
            offer_payload["dropoff_address"] = ride.dropoff_address
            offer_payload["ride_status"] = service._normalize_status_token(ride.lifecycle_state or ride.status)
            offer_payload["requested_at"] = ride.requested_at.isoformat() if ride.requested_at else None
    logger.info(
        "driver_active_offer driver_id=%s offer_ride_id=%s assignment_driver_id=%s assignment_state=%s has_offer=%s",
        driver_id,
        (offer_payload or {}).get("ride_id") if offer_payload else None,
        (offer_payload or {}).get("driver_id") if offer_payload else driver_id,
        (offer_payload or {}).get("assignment_state") if offer_payload else None,
        bool(offer_payload),
    )
    return {
        "organization_id": effective_org_id,
        "driver_id": driver_id,
        "offer": offer_payload,
    }


@router.get("/drivers/{driver_id}/active-ride", response_model=DriverActiveRideResponse)
def get_driver_active_ride(
    driver_id: str,
    request: Request,
    organization_id: str | None = Query(None),
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform()),
    db: Session = Depends(get_db),
):
    """Authoritative active assigned ride for the driver mobile app."""
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    resolved_org_id = service.resolve_driver_organization_id(db, driver, persist_missing=True)
    enforce_entity_tenant(user, resolved_org_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or resolved_org_id)
    try:
        snapshot = service.get_driver_active_ride_data(
            db,
            organization_id=effective_org_id,
            driver_id=driver_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    assignment = snapshot.get("assignment")
    ride = snapshot.get("ride")
    response = DriverActiveRideResponse(
        driver_id=driver_id,
        organization_id=effective_org_id,
        has_active_ride=bool(snapshot.get("has_active_ride")),
        assignment_state=str(snapshot.get("assignment_state") or ""),
        driver_name=str(snapshot.get("driver_name") or ""),
        provider_name=str(snapshot.get("provider_name") or ""),
        eta_minutes=snapshot.get("eta_minutes"),
        active_assignment=_serialize_active_assignment(assignment) if assignment else None,
        ride=_ride_response_with_financials(db, ride) if ride else None,
    )
    record_backend_assignment_sync(
        db,
        request=request,
        event="active_ride_fetch",
        driver_id=driver_id,
        ride_id=str(ride.id) if ride else None,
        assignment_state=response.assignment_state,
        api_response={
            "has_active_ride": response.has_active_ride,
            "assignment_state": response.assignment_state,
            "ride_id": str(ride.id) if ride else None,
        },
    )
    return response


@router.get("/drivers/{driver_id}/live-workspace", response_model=DriverLiveWorkspaceResponse)
def get_driver_live_workspace(
    driver_id: str,
    request: Request,
    organization_id: str | None = Query(None),
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform()),
    db: Session = Depends(get_db),
):
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    resolved_org_id = service.resolve_driver_organization_id(db, driver, persist_missing=True)
    enforce_entity_tenant(user, resolved_org_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or resolved_org_id)
    try:
        snapshot = service.get_driver_live_workspace_data(
            db,
            organization_id=effective_org_id,
            driver_id=driver_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    assignment = snapshot.get("assignment")
    ride = snapshot.get("ride")
    response = DriverLiveWorkspaceResponse(
        driver_id=driver_id,
        organization_id=effective_org_id,
        safety_status=str(snapshot.get("safety_status") or "ok"),
        reconnect_safe=bool(snapshot.get("reconnect_safe")),
        active_assignment=_serialize_active_assignment(assignment) if assignment else None,
        active_ride=RideResponse.model_validate(ride) if ride else None,
        assignment_countdown_seconds=snapshot.get("countdown"),
        eta_minutes=snapshot.get("eta_minutes"),
        timeline_states=list(snapshot.get("timeline_states") or []),
    )
    record_backend_assignment_sync(
        db,
        request=request,
        event="live_workspace_fetch",
        driver_id=driver_id,
        ride_id=str(ride.id) if ride else None,
        assignment_state=str(getattr(assignment, "assignment_state", None) or getattr(assignment, "state", None) or ""),
        api_response={
            "has_active_ride": bool(ride),
            "ride_id": str(ride.id) if ride else None,
            "timeline_states": list(snapshot.get("timeline_states") or [])[:8],
        },
    )
    return response


@router.post("/drivers/{driver_id}/route-progress", response_model=DriverLiveWorkspaceResponse)
async def progress_driver_route(
    driver_id: str,
    payload: DriverRouteProgressRequest,
    request: Request,
    organization_id: str | None = Query(None),
    auth: DriverEndpointAuth = Depends(require_driver_workflow_auth()),
    db: Session = Depends(get_db),
):
    user = auth.user
    actor_user_id = auth.actor_user_id
    effective_driver_id = _effective_driver_id_from_auth(driver_id, auth)
    driver = service.get_driver_by_id(db, effective_driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    effective_org_id = enforce_tenant_scope(user, organization_id or driver.organization_id)

    workspace = service.get_driver_live_workspace_data(
        db,
        organization_id=effective_org_id,
        driver_id=effective_driver_id,
    )
    assignment = workspace.get("assignment")
    ride = workspace.get("ride")
    ride_id = payload.ride_id or (ride.id if ride else None) or (assignment.ride_id if assignment else None)
    if not ride_id:
        raise HTTPException(status_code=400, detail="No active ride found for route progression")

    ride_for_guard = service.get_ride_by_id(db, ride_id)
    if not ride_for_guard:
        raise HTTPException(status_code=404, detail="Ride not found")
    lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride_for_guard, "lifecycle_state", None) or ride_for_guard.status)

    emitter = get_emitter()

    if payload.target_state == "en_route_pickup":
        try:
            ride = _sync_driver_progress_action(
                db,
                ride_id,
                lambda: service.driver_en_route_pickup(db, driver_id=effective_driver_id, ride_id=ride_id, actor_user_id=actor_user_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="assignment-accepted",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
    elif payload.target_state == "arrived_pickup":
        try:
            ride = _sync_driver_progress_action(
                db,
                ride_id,
                lambda: service.driver_arrived_pickup(db, driver_id=effective_driver_id, ride_id=ride_id, actor_user_id=actor_user_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="pickup-arrived",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
    elif payload.target_state == "rider_loaded":
        try:
            ride = _sync_driver_progress_action(
                db,
                ride_id,
                lambda: service.driver_pickup_complete(db, driver_id=effective_driver_id, ride_id=ride_id, actor_user_id=actor_user_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="rider-loaded",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="trip-started",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
    elif payload.target_state == "trip_in_progress":
        try:
            ride = _sync_driver_progress_action(
                db,
                ride_id,
                lambda: service.driver_start_trip(db, driver_id=effective_driver_id, ride_id=ride_id, actor_user_id=actor_user_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="location-updated",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="trip-progress",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
    elif payload.target_state == "arrived_destination":
        try:
            ride = _sync_driver_progress_action(
                db,
                ride_id,
                lambda: service.driver_arrived_destination(db, driver_id=effective_driver_id, ride_id=ride_id, actor_user_id=actor_user_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="location-updated",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
        await emitter.emit_dispatch_changed(
            organization_id=effective_org_id,
            event_name="trip-progress",
            actor_user_id=actor_user_id,
            details={"ride_id": ride_id, "driver_id": effective_driver_id, "target_state": payload.target_state},
        )
    elif payload.target_state == "completed":
        pre_driver = service.get_driver_by_id(db, effective_driver_id)
        previous_driver_status = str(getattr(pre_driver, "status", "") or "") if pre_driver else None
        try:
            ride = _sync_driver_progress_action(
                db,
                ride_id,
                lambda: service.driver_dropoff_complete(db, driver_id=effective_driver_id, ride_id=ride_id, actor_user_id=actor_user_id),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        await _emit_driver_trip_completion_events(
            db=db,
            ride=ride,
            driver_id=effective_driver_id,
            actor_user_id=actor_user_id,
            previous_driver_status=previous_driver_status,
            source="driver_route_progress_complete",
        )
    else:
        ride = service.get_ride_by_id(db, ride_id)
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")

    increment_metric(f"health_isf.route_progress.{payload.target_state}")
    refreshed = service.get_driver_live_workspace_data(
        db,
        organization_id=effective_org_id,
        driver_id=effective_driver_id,
    )
    refreshed_assignment = refreshed.get("assignment")
    refreshed_ride = refreshed.get("ride")
    response = DriverLiveWorkspaceResponse(
        driver_id=effective_driver_id,
        organization_id=effective_org_id,
        safety_status=str(refreshed.get("safety_status") or "ok"),
        reconnect_safe=bool(refreshed.get("reconnect_safe")),
        active_assignment=_serialize_active_assignment(refreshed_assignment) if refreshed_assignment else None,
        active_ride=RideResponse.model_validate(refreshed_ride) if refreshed_ride else None,
        assignment_countdown_seconds=refreshed.get("countdown"),
        eta_minutes=refreshed.get("eta_minutes"),
        timeline_states=list(refreshed.get("timeline_states") or []),
    )
    record_backend_assignment_sync(
        db,
        request=request,
        event="route_progress",
        driver_id=effective_driver_id,
        ride_id=ride_id,
        assignment_state=payload.target_state,
        api_response={
            "target_state": payload.target_state,
            "ride_id": ride_id,
            "requested_driver_id": driver_id,
            "effective_driver_id": effective_driver_id,
            "active_ride_status": str(getattr(refreshed_ride, "lifecycle_state", None) or getattr(refreshed_ride, "status", None) or ""),
        },
    )
    return response


@router.get("/admin/command-center/summary")
def get_admin_command_center_summary(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    summary = service.get_admin_command_center_summary(db, organization_id=effective_org_id)
    websocket = get_broadcaster().get_websocket_health_stats(organization_id=effective_org_id)
    return {
        **summary,
        "websocket": websocket,
        "runtime_validation": {
            "queue_depth": RetryQueueService.get_queue_stats(db, organization_id=effective_org_id),
            "idempotency_integrity": "stable",
            "lifecycle_guardrails": "enabled",
        },
    }


@router.get("/admin/live-operations", response_model=AdminLiveOperationsResponse)
def get_admin_live_operations(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    live_data = service.get_admin_live_operations_data(db, organization_id=effective_org_id)
    websocket = get_broadcaster().get_websocket_health_stats(organization_id=effective_org_id)
    return AdminLiveOperationsResponse(
        organization_id=effective_org_id,
        generated_at=live_data.get("generated_at") or now(),
        active_rides=live_data.get("active_rides") or [],
        awaiting_assignment=live_data.get("awaiting_assignment") or [],
        stale_assignments=live_data.get("stale_assignments") or [],
        driver_availability_board=live_data.get("driver_availability_board") or {},
        provider_coordination_alerts=live_data.get("provider_coordination_alerts") or [],
        websocket_monitor=websocket,
        dispatch_event_counters=live_data.get("dispatch_event_counters") or {},
    )


@router.get("/admin/dispatch-alerts", response_model=AdminDispatchAlertsResponse)
async def get_admin_dispatch_alerts(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    alert_data = service.get_admin_dispatch_alerts_data(db, organization_id=effective_org_id)
    await get_emitter().emit_dispatch_changed(
        organization_id=effective_org_id,
        event_name="dispatch-alert",
        actor_user_id=user.user_id,
        details={
            "alert_count": len(alert_data.get("alerts") or []),
            "counters": alert_data.get("counters") or {},
        },
    )
    increment_metric("health_isf.dispatch_alert_snapshot")
    return AdminDispatchAlertsResponse(
        organization_id=effective_org_id,
        generated_at=alert_data.get("generated_at") or now(),
        alerts=alert_data.get("alerts") or [],
        counters=alert_data.get("counters") or {},
    )


@router.post("/admin/reassign-driver", response_model=AdminDispatchInterventionResponse)
async def admin_reassign_driver(
    payload: AdminReassignDriverRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    try:
        ride = service.admin_reassign_driver(
            db,
            organization_id=effective_org_id,
            ride_id=payload.ride_id,
            driver_id=payload.driver_id,
            reason=payload.reason,
            actor_user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride.id,
        event_name="assignment-issued",
        actor_user_id=user.user_id,
        details={
            "ride_id": ride.id,
            "driver_id": payload.driver_id,
            "reason": payload.reason,
            "source": "admin_reassign_driver",
        },
        request_id=f"admin_reassign_{ride.id}",
        driver_id=payload.driver_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason="admin_reassign_driver",
        assignment_transition_source="admin_command_center",
    )
    increment_metric("health_isf.admin_reassign_driver")
    return AdminDispatchInterventionResponse(
        organization_id=effective_org_id,
        ride=RideResponse.model_validate(ride),
        message="Admin reassignment completed.",
    )


@router.post("/admin/force-expire-assignment", response_model=AdminDispatchInterventionResponse)
async def admin_force_expire_assignment(
    payload: AdminForceExpireAssignmentRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    try:
        offer = service.admin_force_expire_assignment(
            db,
            organization_id=effective_org_id,
            offer_id=payload.offer_id,
            reason=payload.reason,
            actor_user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not offer:
        raise HTTPException(status_code=404, detail="Offer not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=offer.ride_id,
        event_name="assignment-expired",
        actor_user_id=user.user_id,
        details={
            "offer_id": offer.id,
            "ride_id": offer.ride_id,
            "driver_id": offer.driver_id,
            "reason": payload.reason,
        },
        request_id=f"admin_expire_{offer.id}",
        assignment_id=offer.id,
        driver_id=offer.driver_id,
        lifecycle_state=str(offer.assignment_state),
        transition_reason="admin_force_expire_assignment",
        assignment_transition_source="admin_command_center",
    )
    increment_metric("health_isf.admin_force_expire_assignment")
    return AdminDispatchInterventionResponse(
        organization_id=effective_org_id,
        offer=_serialize_dispatch_offer(offer),
        message="Assignment offer expired and returned for reassignment.",
    )


@router.patch("/customer-requests/{request_id}/status", response_model=CustomerRideRequestResponse)
async def patch_customer_ride_request_status(
    request_id: str,
    payload: CustomerRideRequestStatusUpdateRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    row = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_id,
        dispatch_status=payload.dispatch_status,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    ride = service.get_ride_by_id(db, row.ride_id)
    emitter = get_emitter()
    if ride:
        await _emit_with_retry_queue(
            db=db,
            organization_id=effective_org_id,
            event_type="customer_request_status_changed",
            event_payload={
                "request_id": row.id,
                "ride_id": row.ride_id,
                "dispatch_status": row.dispatch_status,
            },
            emit_callable=lambda: emitter.emit_ride_status_changed(
                organization_id=effective_org_id,
                ride_id=row.ride_id,
                from_status="request",
                to_status=row.dispatch_status,
                actor_user_id=user.user_id,
            ),
            idempotency_key=_event_key("customer_request_status", row.id, row.dispatch_status),
            ride_id=row.ride_id,
        )

        status_event_name = {
            "approved": "ride-approved",
            "dispatchable": "ride-dispatchable",
            "in_progress": "ride-in-progress",
            "completed": "ride-completed",
        }.get(str(row.dispatch_status or "").lower())
        if status_event_name:
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=effective_org_id,
                ride_id=row.ride_id,
                event_name=status_event_name,
                actor_user_id=user.user_id,
                details={
                    "request_id": row.id,
                    "ride_id": row.ride_id,
                    "dispatch_status": row.dispatch_status,
                },
                request_id=f"request_status_{row.id}_{row.dispatch_status}",
                lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
                transition_reason="customer_request_status_patch",
                assignment_transition_source="customer_request_status",
            )

    return _serialize_customer_request(row)


@router.post("/dispatcher/customer-requests/{request_id}/approve", response_model=DispatcherCustomerRequestActionResponse)
async def dispatcher_approve_customer_request(
    request_id: str,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    row = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_id,
        dispatch_status="approved",
    )
    if not row:
        raise HTTPException(status_code=404, detail="Customer request not found")
    ride = service.get_ride_by_id(db, row.ride_id)
    if ride:
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=effective_org_id,
            ride_id=ride.id,
            event_name="customer-request-approved",
            actor_user_id=user.user_id,
            details={"request_id": row.id, "ride_id": row.ride_id, "dispatch_status": row.dispatch_status},
            request_id=_resolve_request_id(request),
            lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
            transition_reason="dispatcher_approved",
            assignment_transition_source="dispatcher_request_approve",
        )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=effective_org_id,
            ride_id=ride.id,
            event_name="ride-approved",
            actor_user_id=user.user_id,
            details={"request_id": row.id, "ride_id": ride.id},
            request_id=_resolve_request_id(request),
            lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
            transition_reason="dispatcher_approved",
            assignment_transition_source="dispatcher_request_approve",
        )
    return DispatcherCustomerRequestActionResponse(
        request=_serialize_customer_request(row),
        ride=RideResponse.model_validate(ride) if ride else None,
        message="Customer request approved for dispatch workflow.",
    )


@router.post("/dispatcher/customer-requests/{request_id}/assign-driver", response_model=DispatcherCustomerRequestActionResponse)
async def dispatcher_assign_driver_for_customer_request(
    request_id: str,
    payload: DispatcherCustomerRequestAssignDriverRequest,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    request_row = service.get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Customer request not found")
    _assert_request_dispatch_authorized(
        request_row,
        allowed_statuses={"approved", "dispatchable", "broadcasted", "accepted", "assigned"},
        operation="Driver assignment",
    )

    try:
        ride = service.assign_driver_to_ride(
            db,
            ride_id=request_row.ride_id,
            driver_id=payload.driver_id,
            actor_user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    updated = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_row.id,
        dispatch_status="assigned",
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Customer request not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride.id,
        event_name="assignment-issued",
        actor_user_id=user.user_id,
        details={
            "request_id": updated.id,
            "ride_id": ride.id,
            "driver_id": payload.driver_id,
            "dispatch_status": updated.dispatch_status,
        },
        request_id=_resolve_request_id(request),
        driver_id=payload.driver_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason="dispatcher_manual_assignment",
        assignment_transition_source="dispatcher_request_assign_driver",
    )
    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride.id,
        event_name="driver-offer-issued",
        actor_user_id=user.user_id,
        details={
            "request_id": updated.id,
            "ride_id": ride.id,
            "driver_id": payload.driver_id,
        },
        request_id=_resolve_request_id(request),
        driver_id=payload.driver_id,
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason="dispatcher_manual_assignment",
        assignment_transition_source="dispatcher_request_assign_driver",
    )

    return DispatcherCustomerRequestActionResponse(
        request=_serialize_customer_request(updated),
        ride=RideResponse.model_validate(ride) if ride else None,
        message="Driver assigned from dispatcher customer-request workflow.",
    )


@router.post("/dispatcher/customer-requests/{request_id}/auto-dispatch", response_model=DispatcherCustomerRequestActionResponse)
async def dispatcher_auto_dispatch_customer_request(
    request_id: str,
    payload: DispatcherCustomerRequestAutoDispatchRequest,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    request_row = service.get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Customer request not found")

    _assert_request_dispatch_authorized(
        request_row,
        allowed_statuses={"approved", "dispatchable", "broadcasted"},
        operation="Auto-dispatch",
    )
    request_row = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_row.id,
        dispatch_status="dispatchable",
    )
    if not request_row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    try:
        result = service.auto_assign_request(
            db,
            ride_id=request_row.ride_id,
            actor_user_id=user.user_id,
            offer_timeout_seconds=payload.offer_timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    offer = result.get("offer")
    if offer:
        request_row = service.update_customer_ride_request_status(
            db,
            organization_id=effective_org_id,
            request_id=request_row.id,
            dispatch_status="assigned",
        )
        if not request_row:
            raise HTTPException(status_code=404, detail="Customer request not found")

    ride = service.get_ride_by_id(db, request_row.ride_id)
    if ride:
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=effective_org_id,
            ride_id=ride.id,
            event_name="auto-assignment-completed",
            actor_user_id=user.user_id,
            details={
                "request_id": request_row.id,
                "ride_id": ride.id,
                "offer_id": offer.id if offer else None,
                "driver_id": offer.driver_id if offer else None,
                "dispatch_status": request_row.dispatch_status,
            },
            request_id=_resolve_request_id(request),
            assignment_id=offer.id if offer else None,
            driver_id=offer.driver_id if offer else None,
            lifecycle_state=str(offer.assignment_state) if offer else str(getattr(ride, "lifecycle_state", None) or ride.status),
            transition_reason="dispatcher_auto_dispatch",
            assignment_transition_source="dispatcher_request_auto_dispatch",
        )
        if offer:
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=effective_org_id,
                ride_id=ride.id,
                event_name="driver-offer-issued",
                actor_user_id=user.user_id,
                details={
                    "request_id": request_row.id,
                    "ride_id": ride.id,
                    "offer_id": offer.id,
                    "driver_id": offer.driver_id,
                },
                request_id=_resolve_request_id(request),
                assignment_id=offer.id,
                driver_id=offer.driver_id,
                lifecycle_state=str(offer.assignment_state),
                transition_reason="dispatcher_auto_dispatch",
                assignment_transition_source="dispatcher_request_auto_dispatch",
            )

    return DispatcherCustomerRequestActionResponse(
        request=_serialize_customer_request(request_row),
        ride=RideResponse.model_validate(ride) if ride else None,
        offer=_serialize_dispatch_offer(offer) if offer else None,
        message="Auto-dispatch executed for customer request.",
    )


@router.post("/dispatcher/customer-requests/{request_id}/reassign", response_model=DispatcherCustomerRequestActionResponse)
async def dispatcher_reassign_customer_request(
    request_id: str,
    payload: DispatcherCustomerRequestReassignRequest,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    request_row = service.get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Customer request not found")

    try:
        result = service.reassign_expired_request(
            db,
            ride_id=request_row.ride_id,
            actor_user_id=user.user_id,
            offer_timeout_seconds=payload.offer_timeout_seconds,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    offer = result.get("offer")
    request_row = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_row.id,
        dispatch_status="assigned" if offer else "dispatchable",
    )
    if not request_row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    ride = service.get_ride_by_id(db, request_row.ride_id)
    if ride:
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=effective_org_id,
            ride_id=ride.id,
            event_name="assignment-reassigned",
            actor_user_id=user.user_id,
            details={
                "request_id": request_row.id,
                "ride_id": ride.id,
                "offer_id": offer.id if offer else None,
                "driver_id": offer.driver_id if offer else None,
                "reason": payload.reason,
            },
            request_id=_resolve_request_id(request),
            assignment_id=offer.id if offer else None,
            driver_id=offer.driver_id if offer else None,
            lifecycle_state=str(offer.assignment_state) if offer else str(getattr(ride, "lifecycle_state", None) or ride.status),
            transition_reason=str(payload.reason or "dispatcher_reassign"),
            assignment_transition_source="dispatcher_request_reassign",
        )

    return DispatcherCustomerRequestActionResponse(
        request=_serialize_customer_request(request_row),
        ride=RideResponse.model_validate(ride) if ride else None,
        offer=_serialize_dispatch_offer(offer) if offer else None,
        message="Customer request reassignment completed.",
    )


@router.patch("/dispatcher/customer-requests/{request_id}/cancel", response_model=DispatcherCustomerRequestActionResponse)
async def dispatcher_cancel_customer_request(
    request_id: str,
    payload: DispatcherCustomerRequestReasonRequest,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    request_row = service.get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Customer request not found")

    try:
        ride = service.update_ride_status(
            db,
            ride_id=request_row.ride_id,
            status="cancelled",
            actor_user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    request_row = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_row.id,
        dispatch_status="cancelled",
    )
    if not request_row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride.id,
        event_name="assignment-cancelled",
        actor_user_id=user.user_id,
        details={"request_id": request_row.id, "ride_id": ride.id, "reason": payload.reason},
        request_id=_resolve_request_id(request),
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason=str(payload.reason or "dispatcher_cancelled"),
        assignment_transition_source="dispatcher_request_cancel",
    )

    return DispatcherCustomerRequestActionResponse(
        request=_serialize_customer_request(request_row),
        ride=RideResponse.model_validate(ride) if ride else None,
        message="Customer request cancelled by dispatcher.",
    )


@router.patch("/dispatcher/customer-requests/{request_id}/complete", response_model=DispatcherCustomerRequestActionResponse)
async def dispatcher_complete_customer_request(
    request_id: str,
    payload: DispatcherCustomerRequestReasonRequest,
    request: Request,
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    request_row = service.get_customer_ride_request_by_id(db, request_id)
    if not request_row or request_row.organization_id != effective_org_id:
        raise HTTPException(status_code=404, detail="Customer request not found")

    try:
        ride = service.get_ride_by_id(db, request_row.ride_id)
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")

        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
        if lifecycle_state == RideStatus.RIDER_ONBOARD.value:
            ride = service.update_ride_status(
                db,
                ride_id=request_row.ride_id,
                status=RideStatus.IN_PROGRESS.value,
                actor_user_id=user.user_id,
            )
            if not ride:
                raise HTTPException(status_code=404, detail="Ride not found")
        if lifecycle_state in {RideStatus.RIDER_ONBOARD.value, RideStatus.IN_PROGRESS.value}:
            ride = service.driver_dropoff_complete(
                db,
                driver_id=str(ride.driver_id or ""),
                ride_id=request_row.ride_id,
                actor_user_id=user.user_id,
            )
        else:
            ride = service.update_ride_status(
                db,
                ride_id=request_row.ride_id,
                status="completed",
                actor_user_id=user.user_id,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    request_row = service.update_customer_ride_request_status(
        db,
        organization_id=effective_org_id,
        request_id=request_row.id,
        dispatch_status="completed",
    )
    if not request_row:
        raise HTTPException(status_code=404, detail="Customer request not found")

    await _emit_dispatch_lifecycle_event(
        db=db,
        organization_id=effective_org_id,
        ride_id=ride.id,
        event_name="assignment-completed",
        actor_user_id=user.user_id,
        details={"request_id": request_row.id, "ride_id": ride.id, "reason": payload.reason},
        request_id=_resolve_request_id(request),
        lifecycle_state=str(getattr(ride, "lifecycle_state", None) or ride.status),
        transition_reason=str(payload.reason or "dispatcher_completed"),
        assignment_transition_source="dispatcher_request_complete",
    )

    return DispatcherCustomerRequestActionResponse(
        request=_serialize_customer_request(request_row),
        ride=RideResponse.model_validate(ride) if ride else None,
        message="Customer request marked complete by dispatcher.",
    )

@router.get("/rides", response_model=list[RideResponse])
def list_rides(
    skip: int = 0,
    limit: int = 50,
    organization_id: str | None = Query(None),
    active_only: bool = Query(False, description="Exclude completed/cancelled/failed rides"),
    history_only: bool = Query(False, description="Return only completed/cancelled/failed rides"),
    exclude_test: bool = Query(False, description="Exclude proof/demo/test marker rides"),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve rides (paginated, newest first).

    Operational dashboards should call with active_only=true&exclude_test=true.
    History/Reports should call with history_only=true.
    """
    logger.info(
        "Listing rides: skip=%d, limit=%d active_only=%s history_only=%s exclude_test=%s",
        skip,
        limit,
        active_only,
        history_only,
        exclude_test,
    )
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rides = service.get_all_rides(
        db,
        skip=skip,
        limit=limit,
        organization_id=effective_org_id,
        active_only=active_only,
        history_only=history_only,
        exclude_test=exclude_test,
    )
    return [_ride_response_with_financials(db, ride) for ride in rides]


@router.post("/rides", response_model=RideResponse, status_code=201)
async def create_ride(
    ride_create: RideCreate,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Create a new ride request with enterprise intake protections."""
    logger.info(
        "Creating ride: passenger=%s, from=%s to=%s",
        ride_create.passenger_name,
        ride_create.pickup_address[:30],
        ride_create.dropoff_address[:30],
    )

    provider = service.get_provider_by_id(db, ride_create.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)
    organization_id = enforce_tenant_scope(user, provider.organization_id)

    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if idempotency_key:
        existing_key = IdempotencyService.get_key(db, idempotency_key)
        if existing_key and existing_key.resource_id:
            existing_ride = service.get_ride_by_id(db, existing_key.resource_id)
            if existing_ride:
                enforce_entity_tenant(user, existing_ride.organization_id)
                return existing_ride
        if existing_key and not existing_key.resource_id:
            raise HTTPException(status_code=409, detail="Duplicate intake request in progress")
        IdempotencyService.reserve_key(
            db,
            idempotency_key=idempotency_key,
            scope="ride_intake",
            resource_id=None,
        )

    try:
        try:
            active_service_category = ensure_active_service_category(ride_create.service_type)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        estimated_duration = ride_create.estimated_duration_minutes or calculate_duration_minutes(ride_create.estimated_distance_miles)
        priority_tag = normalize_priority_tag(ride_create.priority_tag)
        is_emergency = bool(ride_create.is_emergency or priority_tag == "emergency")
        priority_score = calculate_priority_score(
            priority_tag=priority_tag,
            service_type=active_service_category.value,
            appointment_time=ride_create.appointment_time,
            distance_miles=ride_create.estimated_distance_miles,
            is_emergency=is_emergency,
        )
        ai_dispatch_context = build_ai_dispatch_context(
            organization_id=organization_id,
            service_type=active_service_category.value,
            priority_tag=priority_tag,
            priority_score=priority_score,
            estimated_distance_miles=ride_create.estimated_distance_miles,
            estimated_duration_minutes=estimated_duration,
            appointment_time=ride_create.appointment_time,
            recurring_trip_pattern=ride_create.recurring_trip_pattern,
            is_emergency=is_emergency,
        )
        if ride_create.ai_dispatch_context:
            ai_dispatch_context.update(ride_create.ai_dispatch_context)

        fingerprint = build_intake_fingerprint(
            organization_id=organization_id,
            passenger_name=ride_create.passenger_name,
            passenger_phone=ride_create.passenger_phone,
            pickup_address=ride_create.pickup_address,
            dropoff_address=ride_create.dropoff_address,
            service_type=active_service_category.value,
            provider_id=ride_create.provider_id,
            appointment_time=ride_create.appointment_time,
        )
        duplicate = service.find_recent_duplicate_ride(
            db,
            organization_id=organization_id,
            intake_fingerprint=fingerprint,
            within_seconds=2,
        )
        if duplicate:
            if idempotency_key:
                IdempotencyService.bind_resource(db, idempotency_key=idempotency_key, resource_id=duplicate.id)
                return duplicate
            raise HTTPException(status_code=409, detail="Duplicate ride submission detected")

        ride = service.create_ride(
            db=db,
            organization_id=organization_id,
            passenger_name=ride_create.passenger_name,
            passenger_phone=ride_create.passenger_phone,
            pickup_address=ride_create.pickup_address,
            dropoff_address=ride_create.dropoff_address,
            service_type=active_service_category.value,
            provider_id=ride_create.provider_id,
            estimated_distance_miles=ride_create.estimated_distance_miles,
            estimated_duration_minutes=estimated_duration,
            priority_score=priority_score,
            priority_tag=priority_tag,
            is_emergency=is_emergency,
            appointment_time=ride_create.appointment_time,
            recurring_trip_pattern=ride_create.recurring_trip_pattern,
            ai_dispatch_context=ai_dispatch_context,
            intake_fingerprint=fingerprint,
            notes=ride_create.notes,
            actor_user_id=_user.id,
        )

        if idempotency_key:
            IdempotencyService.bind_resource(db, idempotency_key=idempotency_key, resource_id=ride.id)

        ActivityLogService.log_activity(
            db,
            organization_id=organization_id,
            action=ActivityAction.RIDE_CREATED,
            description="Ride intake submitted",
            ride_id=ride.id,
            actor_user_id=_user.id,
            details={
                "priority_score": priority_score,
                "priority_tag": priority_tag,
                "appointment_time": ride_create.appointment_time.isoformat() if ride_create.appointment_time else None,
                "recurring": bool(ride_create.recurring_trip_pattern),
            },
        )
        SecurityAuditService.log_action(
            db,
            organization_id=organization_id,
            action_type="ride_intake_created",
            actor_user_id=user.user_id,
            ride_id=ride.id,
            details={
                "priority_score": priority_score,
                "priority_tag": priority_tag,
                "idempotency_key": bool(idempotency_key),
            },
        )
        WorkflowOrchestrationService.record_intake_hook(
            db,
            organization_id=organization_id,
            ride_id=ride.id,
            actor_user_id=_user.id,
            payload={
                "priority_score": priority_score,
                "priority_tag": priority_tag,
                "appointment_time": ride_create.appointment_time.isoformat() if ride_create.appointment_time else None,
                "retry_safe": True,
                "escalation_integration_point": "workflow.escalation.create",
            },
        )

        event_payload = {
            "ride_id": ride.id,
            "status": str(ride.status),
            "lifecycle_state": str(getattr(ride, "lifecycle_state", "requested") or "requested"),
            "priority_score": priority_score,
            "priority_tag": priority_tag,
            "organization_id": organization_id,
        }
        emitter = get_emitter()
        await _emit_with_retry_queue(
            db=db,
            organization_id=organization_id,
            event_type="ride_created",
            event_payload=event_payload,
            emit_callable=lambda: emitter.emit_ride_created(
                organization_id=organization_id,
                ride_id=ride.id,
                passenger_name=ride.passenger_name,
                priority_score=priority_score,
                priority_tag=priority_tag,
                actor_user_id=_user.id,
                details={"organization_id": organization_id},
            ),
            idempotency_key=_event_key("ride_created", ride.id, str(ride.version)),
            ride_id=ride.id,
        )

        log_operational_event(
            "dispatch.ride_intake.created",
            organization_id=organization_id,
            ride_id=ride.id,
            priority_score=priority_score,
            priority_tag=priority_tag,
            has_recurring_pattern=bool(ride_create.recurring_trip_pattern),
            has_appointment_time=bool(ride_create.appointment_time),
            idempotency_key_present=bool(idempotency_key),
        )

        db.refresh(ride)
        latest_assignment = (
            db.query(HealthISFDispatchAssignment)
            .filter(HealthISFDispatchAssignment.ride_id == ride.id)
            .order_by(desc(HealthISFDispatchAssignment.created_at))
            .first()
        )
        if ride.driver_id and latest_assignment and str(latest_assignment.assignment_state) == DispatchAssignmentState.OFFERED.value:
            selected_driver = service.get_driver_by_id(db, ride.driver_id)
            auto_assign_payload = {
                "ride_id": ride.id,
                "assignment_state": str(latest_assignment.assignment_state),
                "selected_driver_id": ride.driver_id,
                "selected_driver_name": getattr(selected_driver, "name", None),
                "selected_score": float(latest_assignment.score) if latest_assignment.score is not None else None,
                "organization_id": organization_id,
                "source": "intake_auto_dispatch",
            }
            await _emit_with_retry_queue(
                db=db,
                organization_id=organization_id,
                event_type="dispatch_intake_auto_assigned",
                event_payload=auto_assign_payload,
                emit_callable=lambda: emitter.emit_dispatch_changed(
                    organization_id=organization_id,
                    event_name="dispatch_intake_auto_assigned",
                    actor_user_id=_user.id,
                    details=auto_assign_payload,
                ),
                idempotency_key=_event_key("dispatch_intake_auto_assigned", ride.id, str(latest_assignment.id)),
                ride_id=ride.id,
            )
            await _emit_with_retry_queue(
                db=db,
                organization_id=organization_id,
                event_type="ride_assigned",
                event_payload={
                    "ride_id": ride.id,
                    "driver_id": ride.driver_id,
                    "driver_name": getattr(selected_driver, "name", None),
                    "organization_id": organization_id,
                    "source": "intake_auto_dispatch",
                },
                emit_callable=lambda: emitter.emit_ride_assigned(
                    organization_id=organization_id,
                    ride_id=ride.id,
                    driver_id=str(ride.driver_id),
                    driver_name=getattr(selected_driver, "name", None),
                    actor_user_id=_user.id,
                    details={"source": "intake_auto_dispatch"},
                ),
                idempotency_key=_event_key("ride_assigned", ride.id, str(ride.driver_id), "intake_auto_dispatch"),
                ride_id=ride.id,
            )
            log_operational_event(
                "dispatch.intake.auto_assigned",
                organization_id=organization_id,
                ride_id=ride.id,
                selected_driver_id=ride.driver_id,
                selected_score=latest_assignment.score,
            )
        elif (
            latest_assignment
            and str(latest_assignment.assignment_state) == DispatchAssignmentState.AWAITING_APPROVAL.value
        ):
            selected_driver = (
                service.get_driver_by_id(db, latest_assignment.driver_id)
                if latest_assignment.driver_id
                else None
            )
            recommendation_payload = {
                "ride_id": ride.id,
                "assignment_state": str(latest_assignment.assignment_state),
                "recommended_driver_id": latest_assignment.driver_id,
                "recommended_driver_name": getattr(selected_driver, "name", None),
                "recommended_score": float(latest_assignment.score) if latest_assignment.score is not None else None,
                "organization_id": organization_id,
            }
            await _emit_with_retry_queue(
                db=db,
                organization_id=organization_id,
                event_type="dispatch_recommendation_created",
                event_payload=recommendation_payload,
                emit_callable=lambda: emitter.emit_dispatch_changed(
                    organization_id=organization_id,
                    event_name="dispatch_recommendation_created",
                    actor_user_id=_user.id,
                    details=recommendation_payload,
                ),
                idempotency_key=_event_key("dispatch_recommendation_created", ride.id, str(latest_assignment.id)),
                ride_id=ride.id,
            )
            log_operational_event(
                "dispatch.recommendation.created",
                organization_id=organization_id,
                ride_id=ride.id,
                recommended_driver_id=latest_assignment.driver_id,
                recommended_score=latest_assignment.score,
            )

        enforce_entity_tenant(user, ride.organization_id)
        return ride
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ride intake failed")
        raise HTTPException(status_code=500, detail="Ride intake failed") from exc


@router.get("/rides/{ride_id}", response_model=RideResponse)
def get_ride(
    ride_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve a specific ride by ID."""
    logger.info("Fetching ride: %s", ride_id)
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    return ride


@router.patch("/rides/{ride_id}/status", response_model=RideResponse)
async def patch_ride_status(
    ride_id: str,
    payload: RideStatusUpdateRequest,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Update ride status with MVP transition validation and real-time events."""
    logger.info("Updating ride status: ride=%s status=%s", ride_id, payload.status)
    
    # Get ride before updating to capture old status
    old_ride = service.get_ride_by_id(db, ride_id)
    if not old_ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, old_ride.organization_id)
    
    old_status = old_ride.status
    old_lifecycle_state = RideLifecycleManager.normalize_state(getattr(old_ride, "lifecycle_state", None) or old_status)
    organization_id = old_ride.organization_id
    
    try:
        ride = service.update_ride_status(
            db,
            ride_id=ride_id,
            status=payload.status,
            actor_user_id=_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    
    # Log activity
    activity_action = ActivityAction.RIDE_CREATED  # default
    if payload.status == "cancelled":
        activity_action = ActivityAction.RIDE_CANCELLED
    elif payload.status == "completed":
        activity_action = ActivityAction.RIDE_COMPLETED
    
    ActivityLogService.log_activity(
        db,
        organization_id=organization_id,
        action=activity_action,
        description=f"Ride status changed to {payload.status}",
        ride_id=ride_id,
        actor_user_id=_user.id,
    )
    if str(payload.status) == "cancelled":
        SecurityAuditService.log_action(
            db,
            organization_id=organization_id,
            action_type="ride_cancelled_sensitive",
            actor_user_id=user.user_id,
            ride_id=ride_id,
            details={"from_status": str(old_status), "to_status": str(payload.status)},
        )
    
    # Emit real-time event (idempotent + retry queue fallback)
    emitter = get_emitter()
    event_payload = {
        "ride_id": ride_id,
        "from_status": str(old_status),
        "to_status": str(payload.status),
        "from_lifecycle_state": old_lifecycle_state,
        "to_lifecycle_state": RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(payload.status)),
    }
    await _emit_with_retry_queue(
        db=db,
        organization_id=organization_id,
        event_type=EventType.RIDE_STATUS_CHANGED.value,
        event_payload=event_payload,
        emit_callable=lambda: emitter.emit_ride_status_changed(
            organization_id=organization_id,
            ride_id=ride_id,
            from_status=str(old_status),
            to_status=str(payload.status),
            actor_user_id=_user.id,
        ),
        idempotency_key=_event_key("ride_status", ride_id, str(payload.status), str(ride.version)),
        ride_id=ride_id,
    )

    metrics = get_operational_metrics_registry()
    metrics.increment("dispatch.status_updates")
    if ride.accepted_at and ride.requested_at:
        metrics.record_sample("dispatch.assignment.seconds", (ride.accepted_at - ride.requested_at).total_seconds())
    if ride.completed_at and ride.accepted_at:
        metrics.record_sample("dispatch.completion.seconds", (ride.completed_at - ride.accepted_at).total_seconds())
    
    # Log event
    RealTimeEventService.log_event(
        db,
        organization_id=organization_id,
        event_type=EventType.RIDE_STATUS_CHANGED,
        payload={
            "ride_id": ride_id,
            "from_status": str(old_status),
            "to_status": str(payload.status),
                "from_lifecycle_state": old_lifecycle_state,
                "to_lifecycle_state": RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or str(payload.status)),
        },
        ride_id=ride_id,
        created_by_user_id=_user.id,
    )
    
    return ride


@router.patch("/rides/{ride_id}/assign-driver", response_model=RideResponse)
async def patch_ride_assign_driver(
    ride_id: str,
    payload: RideAssignDriverRequest,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Assign an available driver to a ride with concurrent assignment protection."""
    logger.info("Assigning driver: ride=%s driver=%s", ride_id, payload.driver_id)
    
    # Check for concurrent assignment locks
    if ConcurrentAssignmentService.has_assignment_lock(db, ride_id):
        logger.warning(f"Ride {ride_id} already locked for assignment")
        raise HTTPException(
            status_code=409,
            detail="Ride is currently being assigned by another dispatcher",
            headers={"X-Error-Code": "CONCURRENT_ASSIGNMENT"},
        )
    
    # Acquire lock
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride_id, _user.id, 30)
    if not lock:
        raise HTTPException(
            status_code=409,
            detail="Could not acquire assignment lock",
            headers={"X-Error-Code": "LOCK_FAILED"},
        )
    
    try:
        pre_ride = service.get_ride_by_id(db, ride_id)
        if not pre_ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        enforce_entity_tenant(user, pre_ride.organization_id)
        previous_driver_id = pre_ride.driver_id

        ride = service.assign_driver_to_ride(
            db,
            ride_id=ride_id,
            driver_id=payload.driver_id,
            actor_user_id=_user.id,
        )
        
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        
        # Get organization_id from ride
        organization_id = ride.organization_id
        
        # Log activity
        ActivityLogService.log_activity(
            db,
            organization_id=organization_id,
            action=ActivityAction.RIDE_ASSIGNED,
            description=f"Ride assigned to driver {payload.driver_id}",
            ride_id=ride_id,
            driver_id=payload.driver_id,
            actor_user_id=_user.id,
        )
        if previous_driver_id and previous_driver_id != payload.driver_id:
            SecurityAuditService.log_action(
                db,
                organization_id=organization_id,
                action_type="ride_reassignment_override",
                actor_user_id=user.user_id,
                ride_id=ride_id,
                details={"from_driver": previous_driver_id, "to_driver": payload.driver_id},
            )
        
        # Emit real-time event (idempotent + retry queue fallback)
        emitter = get_emitter()
        event_payload = {
            "ride_id": ride_id,
            "driver_id": payload.driver_id,
            "driver_name": ride.driver.name if ride.driver else None,
        }
        await _emit_with_retry_queue(
            db=db,
            organization_id=organization_id,
            event_type=EventType.RIDE_ASSIGNED.value,
            event_payload=event_payload,
            emit_callable=lambda: emitter.emit_ride_assigned(
                organization_id=organization_id,
                ride_id=ride_id,
                driver_id=payload.driver_id,
                driver_name=ride.driver.name if ride.driver else None,
                actor_user_id=_user.id,
            ),
            idempotency_key=_event_key("ride_assigned", ride_id, payload.driver_id, str(ride.version)),
            ride_id=ride_id,
            driver_id=payload.driver_id,
        )
        await emitter.emit_dispatch_changed(
            organization_id=organization_id,
            event_name="assignment-issued",
            actor_user_id=_user.id,
            details={"ride_id": ride_id, "driver_id": payload.driver_id},
        )
        await emitter.emit_driver_active_ride_state(
            organization_id=organization_id,
            driver_id=payload.driver_id,
            active_ride_id=ride_id,
            state=RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status),
            actor_user_id=_user.id,
            details={"source": "assign_driver"},
        )

        metrics = get_operational_metrics_registry()
        metrics.increment("dispatch.assignments.total")
        metrics.record_event_ts("dispatch_events")
        if ride.accepted_at and ride.requested_at:
            metrics.record_sample("dispatch.assignment.seconds", (ride.accepted_at - ride.requested_at).total_seconds())
        
        # Log event
        RealTimeEventService.log_event(
            db,
            organization_id=organization_id,
            event_type=EventType.RIDE_ASSIGNED,
            payload={
                "ride_id": ride_id,
                "driver_id": payload.driver_id,
                "driver_name": ride.driver.name if ride.driver else None,
            },
            ride_id=ride_id,
            driver_id=payload.driver_id,
            created_by_user_id=_user.id,
        )
        
        return ride
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        # Release lock
        ConcurrentAssignmentService.release_assignment_lock(db, ride_id)


@router.patch("/rides/{ride_id}/assign-vehicle", response_model=RideResponse)
async def patch_ride_assign_vehicle(
    ride_id: str,
    payload: RideAssignVehicleRequest,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Assign an active organization vehicle to an existing ride."""
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    vehicle = service.get_vehicle_by_id(db, payload.vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    enforce_entity_tenant(user, vehicle.organization_id)

    if str(vehicle.organization_id) != str(ride.organization_id):
        raise HTTPException(status_code=400, detail="Vehicle must belong to the same organization as ride")
    if not vehicle.is_active:
        raise HTTPException(status_code=400, detail="Cannot assign inactive vehicle")

    try:
        updated = service.assign_vehicle_to_ride(
            db,
            ride_id=ride_id,
            vehicle_id=payload.vehicle_id,
            actor_user_id=_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not updated:
        raise HTTPException(status_code=404, detail="Ride not found")
    return updated


@router.get("/rides/{ride_id}/history", response_model=list[RideHistoryEventResponse])
def get_ride_history(
    ride_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return ride status timeline in ascending timestamp order."""
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    return service.get_ride_status_history(db, ride_id)


@router.get("/rides/{ride_id}/workflow-path")
def get_ride_workflow_path(
    ride_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Phase 49 end-to-end workflow proof for customer request -> dispatch -> driver -> completion."""
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    request_row = service.get_customer_request_by_ride_id(db, ride_id)
    history = service.get_ride_status_history(db, ride_id)
    dispatch_history = service.get_ride_dispatch_history(db, ride_id)

    status_sequence = [str(getattr(item, "to_status", "") or "").lower() for item in history]
    dispatch_actions = [str(getattr(item, "action", "") or "").lower() for item in dispatch_history]
    ride_status = str(getattr(ride, "status", "") or "").lower()
    lifecycle_state = str(getattr(ride, "lifecycle_state", "") or ride_status)

    proof = {
        "customer_request_submitted": bool(request_row),
        "admin_dispatch_approved": bool(request_row and str(request_row.dispatch_status or "").lower() in {"approved", "dispatchable", "assigned", "in_progress", "completed"}),
        "driver_offer_issued": any(action in {"driver-offer-issued", "assignment-issued"} for action in dispatch_actions),
        "driver_accepted": ("assignment-accepted" in dispatch_actions) or ("accepted" in status_sequence),
        "driver_rejected": "assignment-rejected" in dispatch_actions,
        "pickup_arrived": any(status in {"arrived", "driver_en_route"} for status in status_sequence),
        "pickup_complete": any(status in {"rider_onboard", "in_progress"} for status in status_sequence),
        "dropoff_complete": any(status in {"completed"} for status in status_sequence),
        "ride_completed": ride_status == "completed",
        "audit_timeline_available": bool(history or dispatch_history),
    }

    timeline: list[dict[str, Any]] = []
    for event in history:
        timeline.append(
            {
                "at": getattr(event, "created_at", None),
                "category": "ride_status",
                "label": str(getattr(event, "to_status", "unknown") or "unknown"),
                "detail": str(getattr(event, "note", "") or "status transition"),
            }
        )
    for event in dispatch_history:
        timeline.append(
            {
                "at": getattr(event, "created_at", None),
                "category": "dispatch_action",
                "label": str(getattr(event, "action", "action") or "action"),
                "detail": str(getattr(event, "note", "") or "dispatch transition"),
            }
        )
    timeline.sort(key=lambda item: str(item.get("at") or ""))

    return {
        "ride_id": ride.id,
        "organization_id": ride.organization_id,
        "customer_request_id": request_row.id if request_row else None,
        "customer_request_status": str(request_row.dispatch_status) if request_row else None,
        "ride_status": ride_status,
        "lifecycle_state": lifecycle_state,
        "proof": proof,
        "timeline": timeline,
        "generated_at": now().isoformat(),
    }


@router.get("/rides/{ride_id}/completion-handoff", response_model=RideCompletionHandoffResponse)
def get_ride_completion_handoff(
    ride_id: str,
    auth: DriverEndpointAuth = Depends(require_ride_mobile_or_platform()),
    db: Session = Depends(get_db),
):
    user = auth.user
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
    completed = lifecycle_state == RideStatus.COMPLETED.value

    completion_artifact = service.get_latest_ride_execution_action(
        db,
        ride_id=ride.id,
        action_types=["dropoff_completed"],
    )
    trip = service.get_latest_trip_for_ride(db, ride_id=ride.id)
    payout = service.get_payout_for_trip(db, trip_id=trip.id) if trip else None
    request_row = service.get_customer_request_by_ride_id(db, ride.id)

    provider_queue_ready = bool(ride.provider_id and request_row and completed)
    billing_queue_ready = bool(trip and payout and str(getattr(payout, "status", "")).lower() == "pending")
    financial = TripFinancialEngine.get_ride_financial_summary(db, ride_id=ride.id) or {}

    return RideCompletionHandoffResponse(
        ride_id=ride.id,
        organization_id=ride.organization_id,
        lifecycle_state=lifecycle_state,
        completed=completed,
        completion_artifact_id=getattr(completion_artifact, "event_id", None),
        completion_artifact_source=getattr(completion_artifact, "source", None),
        completion_artifact_created_at=getattr(completion_artifact, "created_at", None),
        trip_id=getattr(trip, "id", None),
        payout_id=getattr(payout, "id", None) or financial.get("payout_id"),
        provider_queue_ready=provider_queue_ready,
        billing_queue_ready=billing_queue_ready or bool(financial.get("billing_handoff_id")),
        financial_record_id=financial.get("financial_record_id"),
        ride_price_usd=financial.get("ride_price_usd"),
        driver_pay_usd=financial.get("driver_pay_usd"),
        platform_revenue_usd=financial.get("platform_revenue_usd"),
        provider_share_usd=financial.get("provider_share_usd"),
        payment_transaction_id=financial.get("payment_transaction_id"),
        claim_id=financial.get("claim_id"),
        claim_reference=financial.get("claim_reference"),
        billing_handoff_id=financial.get("billing_handoff_id"),
        billing_handoff_status=financial.get("billing_handoff_status"),
        fare_amount=financial.get("fare_amount"),
    )


@router.get("/rides/{ride_id}/financial-summary", response_model=TripFinancialSummaryResponse)
def get_ride_financial_summary(
    ride_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    summary = TripFinancialEngine.get_ride_financial_summary(db, ride_id=ride.id)
    if not summary:
        raise HTTPException(status_code=404, detail="Financial summary not available for this ride")
    return TripFinancialSummaryResponse(**summary)


@router.get("/drivers/{driver_id}/earnings", response_model=DriverEarningsSummaryResponse)
def get_driver_earnings_summary(
    driver_id: str,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    effective_org_id = enforce_tenant_scope(user, organization_id or driver.organization_id)
    enforce_entity_tenant(user, driver.organization_id)
    payload = TripFinancialEngine.get_driver_earnings_summary(
        db,
        driver_id=driver_id,
        organization_id=effective_org_id,
    )
    return DriverEarningsSummaryResponse(**payload)


@router.get("/drivers/{driver_id}/completion-snapshot", response_model=DriverCompletionSnapshotResponse)
def get_driver_completion_snapshot(
    driver_id: str,
    organization_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform()),
    db: Session = Depends(get_db),
):
    """Authoritative completed-trip view for driver earnings, history, and billing."""
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    effective_org_id = enforce_tenant_scope(user, organization_id or driver.organization_id)
    enforce_entity_tenant(user, driver.organization_id)
    snapshot = service.get_driver_completion_snapshot(
        db,
        organization_id=effective_org_id,
        driver_id=driver_id,
        limit=limit,
    )
    return DriverCompletionSnapshotResponse(
        driver_id=driver_id,
        organization_id=effective_org_id,
        earnings=DriverEarningsSummaryResponse(**snapshot["earnings"]),
        completed_ride_count=int(snapshot.get("completed_ride_count") or 0),
        completed_rides=[_ride_response_with_financials(db, ride) for ride in snapshot["completed_rides"]],
        billing_handoffs=[BillingHandoffQueueItemResponse(**row) for row in snapshot["billing_handoffs"]],
        documents=[TripDocumentResponse(**row) for row in snapshot.get("documents", [])],
    )


@router.get("/drivers/{driver_id}/completed-rides", response_model=list[RideResponse])
def get_driver_completed_rides(
    driver_id: str,
    organization_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    effective_org_id = enforce_tenant_scope(user, organization_id or driver.organization_id)
    enforce_entity_tenant(user, driver.organization_id)
    rides = service.list_driver_completed_rides(
        db,
        organization_id=effective_org_id,
        driver_id=driver_id,
        limit=limit,
    )
    return [_ride_response_with_financials(db, ride) for ride in rides]


@router.get("/operations/billing-handoffs", response_model=list[BillingHandoffQueueItemResponse])
def get_billing_handoff_queue(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rows = service.list_billing_handoff_queue(db, organization_id=effective_org_id, limit=limit)
    return [BillingHandoffQueueItemResponse(**row) for row in rows]


@router.get("/operations/admin-revenue", response_model=AdminRevenueSummaryResponse)
def get_admin_revenue_summary(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    payload = TripFinancialEngine.get_admin_revenue_summary(db, organization_id=effective_org_id)
    return AdminRevenueSummaryResponse(**payload)


@router.get("/operations/trip-documents", response_model=list[TripDocumentResponse])
def list_organization_trip_documents(
    organization_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Trip receipts and billing documents generated on ride completion."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rows = TripFinancialEngine.list_trip_documents_for_organization(
        db, organization_id=effective_org_id, limit=limit
    )
    return [TripDocumentResponse(**row) for row in rows]


@router.get("/drivers/{driver_id}/trip-documents", response_model=list[TripDocumentResponse])
def list_driver_trip_documents(
    driver_id: str,
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    effective_org_id = enforce_tenant_scope(user, organization_id or driver.organization_id)
    enforce_entity_tenant(user, driver.organization_id)
    rows = TripFinancialEngine.list_trip_documents_for_driver(
        db,
        driver_id=driver_id,
        organization_id=effective_org_id,
        limit=limit,
    )
    return [TripDocumentResponse(**row) for row in rows]


@router.get("/rides/{ride_id}/trip-documents", response_model=list[TripDocumentResponse])
def list_ride_trip_documents(
    ride_id: str,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    effective_org_id = enforce_tenant_scope(user, organization_id or ride.organization_id)
    enforce_entity_tenant(user, ride.organization_id)
    rows = TripFinancialEngine.list_trip_documents_for_ride(
        db, ride_id=ride_id, organization_id=effective_org_id
    )
    return [TripDocumentResponse(**row) for row in rows]


# ── Drivers Endpoints ─────────────────────────────────────────────────────────

@router.get("/vehicles/active", response_model=list[VehicleResponse])
def list_active_vehicles(
    skip: int = 0,
    limit: int = 100,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve active vehicles available for dispatch assignment."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.get_active_vehicles(db, organization_id=effective_org_id, skip=skip, limit=limit)


@router.post("/vehicles", response_model=VehicleResponse, status_code=201)
async def create_vehicle(
    payload: VehicleCreate,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Create a tenant-scoped vehicle for onboarding workflows."""
    organization_id = enforce_tenant_scope(user, None)
    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if idempotency_key:
        existing_key = IdempotencyService.get_key(db, idempotency_key)
        if existing_key and existing_key.resource_id:
            existing_vehicle = service.get_vehicle_by_id(db, existing_key.resource_id)
            if existing_vehicle:
                enforce_entity_tenant(user, existing_vehicle.organization_id)
                return existing_vehicle
        if existing_key and not existing_key.resource_id:
            raise HTTPException(status_code=409, detail="Duplicate onboarding request in progress")
        IdempotencyService.reserve_key(
            db,
            idempotency_key=idempotency_key,
            scope="vehicle_onboarding",
            resource_id=None,
        )

    try:
        vehicle = service.create_vehicle(
            db,
            organization_id=organization_id,
            vehicle_type=payload.vehicle_type,
            vehicle_plate=payload.vehicle_plate,
            capacity=payload.capacity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if idempotency_key:
        IdempotencyService.bind_resource(db, idempotency_key=idempotency_key, resource_id=vehicle.id)

    await get_emitter().emit_dispatch_changed(
        organization_id=organization_id,
        event_name="vehicle_created",
        actor_user_id=_user.id,
        details={
            "vehicle_id": vehicle.id,
            "vehicle_type": vehicle.vehicle_type,
        },
    )
    SecurityAuditService.log_action(
        db,
        organization_id=organization_id,
        action_type="vehicle_created",
        actor_user_id=user.user_id,
        details={
            "vehicle_id": vehicle.id,
            "vehicle_plate": vehicle.vehicle_plate,
            "idempotency_key": bool(idempotency_key),
        },
    )
    WorkflowOrchestrationService.record_onboarding_hook(
        db,
        organization_id=organization_id,
        entity_type="vehicle",
        entity_id=vehicle.id,
        actor_user_id=_user.id,
        payload={
            "vehicle_plate": vehicle.vehicle_plate,
            "vehicle_type": vehicle.vehicle_type,
        },
    )
    RealTimeEventService.log_event(
        db,
        organization_id=organization_id,
        event_type=EventType.DISPATCH_CHANGED,
        payload={
            "event_name": "vehicle_created",
            "vehicle_id": vehicle.id,
            "vehicle_plate": vehicle.vehicle_plate,
        },
        created_by_user_id=_user.id,
    )
    OperationalSynchronizationEngine.publish_event(
        organization_id=organization_id,
        event_type=OperationalEventType.WORKFLOW_TRANSITION,
        payload={
            "event_type": "vehicle_created",
            "organization_id": organization_id,
            "vehicle_id": vehicle.id,
            "vehicle_plate": vehicle.vehicle_plate,
            "actor_user_id": _user.id,
        },
        role_scope=["dispatcher", "driver", "provider", "staff", "admin"],
        source_nonce=f"onboarding_vehicle:{organization_id}:{vehicle.id}",
        metadata={"source": "onboarding_api"},
    )
    return vehicle

@router.get("/drivers", response_model=list[DriverResponse])
def list_drivers(
    skip: int = 0,
    limit: int = 50,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve all active drivers (paginated)."""
    logger.info("Listing drivers: skip=%d, limit=%d", skip, limit)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    seed_summary = service.ensure_sample_drivers(db, organization_id=effective_org_id)
    drivers = service.get_drivers_for_organization(
        db,
        organization_id=effective_org_id,
        skip=skip,
        limit=limit,
    )
    if not drivers:
        logger.warning(
            "Driver list empty for org=%s after seed attempt: %s",
            effective_org_id,
            seed_summary,
        )
        db.expire_all()
        drivers = service.get_drivers_for_organization(
            db,
            organization_id=effective_org_id,
            skip=skip,
            limit=limit,
        )
    return drivers


@router.get("/driver-operations")
def driver_operations(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return driver roster and pool metrics for the operations feed."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    bootstrap = service.ensure_operational_bootstrap(db, organization_id=effective_org_id)
    drivers = service.get_drivers_for_organization(db, organization_id=effective_org_id, limit=100)
    metrics = service.get_active_driver_pool_metrics(db, organization_id=effective_org_id)
    return {
        "organization_id": effective_org_id,
        "bootstrap": bootstrap,
        "drivers": drivers,
        "metrics": metrics,
        "driver_count": len(drivers),
        "available_driver_count": sum(
            1
            for driver in drivers
            if str(getattr(driver, "availability_state", "")).lower() == "available"
            and str(getattr(driver, "status", "")).lower() == "available"
            and bool(getattr(driver, "is_online", False))
        ),
    }


@router.get("/dispatch/workspace")
def dispatch_workspace(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Return dispatch workspace payload with providers, drivers, and queue state."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    bootstrap = service.ensure_operational_bootstrap(db, organization_id=effective_org_id)
    providers = service.list_providers_for_organization(db, organization_id=effective_org_id, limit=100)
    drivers = service.get_drivers_for_organization(db, organization_id=effective_org_id, limit=100)
    queue = service.get_dispatch_queue(db, organization_id=effective_org_id, limit=200)
    active_assignments = service.get_dispatch_active_assignments(db, organization_id=effective_org_id, limit=200)
    return {
        "organization_id": effective_org_id,
        "bootstrap": bootstrap,
        "providers": providers,
        "drivers": drivers,
        "dispatch_queue": queue,
        "active_assignments": active_assignments,
        "provider_count": len(providers),
        "driver_count": len(drivers),
    }


@router.get("/operations/production-bootstrap-status")
def production_bootstrap_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Report canonical provider/driver bootstrap state for the active tenant."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    bootstrap = service.ensure_operational_bootstrap(db, organization_id=effective_org_id)
    providers = service.list_providers_for_organization(db, organization_id=effective_org_id, limit=100)
    drivers = service.get_drivers_for_organization(db, organization_id=effective_org_id, limit=100)
    dialect = db.bind.dialect.name if db.bind is not None else "unknown"
    database_url = os.getenv("DATABASE_URL", "")
    database_type = "postgresql" if database_url.startswith("postgres") else dialect
    return {
        "organization_id": effective_org_id,
        "database_type": database_type,
        "bootstrap": bootstrap,
        "providers": [{"id": p.id, "name": p.name, "phone": p.phone, "service_type": p.service_type} for p in providers],
        "drivers": [
            {
                "id": d.id,
                "name": d.name,
                "phone": d.phone,
                "status": str(d.status),
                "availability_state": d.availability_state,
                "is_online": d.is_online,
                "vehicle_plate": d.vehicle_plate,
            }
            for d in drivers
        ],
        "provider_count": len(providers),
        "driver_count": len(drivers),
        "available_driver_count": sum(
            1
            for driver in drivers
            if str(getattr(driver, "availability_state", "")).lower() == "available"
            and str(getattr(driver, "status", "")).lower() == "available"
            and bool(getattr(driver, "is_online", False))
        ),
    }


@router.post("/drivers", response_model=DriverResponse, status_code=201)
async def create_driver(
    payload: DriverCreate,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Create a tenant-scoped driver for onboarding workflows."""
    organization_id = enforce_tenant_scope(user, None)
    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if idempotency_key:
        existing_key = IdempotencyService.get_key(db, idempotency_key)
        if existing_key and existing_key.resource_id:
            existing_driver = service.get_driver_by_id(db, existing_key.resource_id)
            if existing_driver:
                enforce_entity_tenant(user, existing_driver.organization_id)
                return existing_driver
        if existing_key and not existing_key.resource_id:
            raise HTTPException(status_code=409, detail="Duplicate onboarding request in progress")
        IdempotencyService.reserve_key(
            db,
            idempotency_key=idempotency_key,
            scope="driver_onboarding",
            resource_id=None,
        )

    try:
        driver = service.create_driver(
            db,
            organization_id=organization_id,
            name=payload.name,
            phone=payload.phone,
            vehicle_type=payload.vehicle_type,
            vehicle_plate=payload.vehicle_plate,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if idempotency_key:
        IdempotencyService.bind_resource(db, idempotency_key=idempotency_key, resource_id=driver.id)

    try:
        await get_emitter().emit_driver_status_changed(
            organization_id=organization_id,
            driver_id=driver.id,
            from_status="offline",
            to_status=str(driver.status),
            actor_user_id=_user.id,
        )
        SecurityAuditService.log_action(
            db,
            organization_id=organization_id,
            action_type="driver_created",
            actor_user_id=user.user_id,
            details={
                "driver_id": driver.id,
                "driver_phone": driver.phone,
                "idempotency_key": bool(idempotency_key),
            },
        )
        WorkflowOrchestrationService.record_onboarding_hook(
            db,
            organization_id=organization_id,
            entity_type="driver",
            entity_id=driver.id,
            actor_user_id=_user.id,
            payload={
                "driver_phone": driver.phone,
                "status": str(driver.status),
            },
        )
        RealTimeEventService.log_event(
            db,
            organization_id=organization_id,
            event_type=EventType.DRIVER_STATUS_CHANGED,
            payload={
                "driver_id": driver.id,
                "status": str(driver.status),
                "operation": "create",
            },
            driver_id=driver.id,
            created_by_user_id=_user.id,
        )
        OperationalSynchronizationEngine.publish_event(
            organization_id=organization_id,
            event_type=OperationalEventType.DRIVER_STATE_CHANGED,
            payload={
                "event_type": "driver_created",
                "organization_id": organization_id,
                "driver_id": driver.id,
                "status": str(driver.status),
                "actor_user_id": _user.id,
            },
            role_scope=["dispatcher", "driver", "staff", "admin"],
            source_nonce=f"onboarding_driver:{organization_id}:{driver.id}",
            metadata={"source": "onboarding_api"},
        )
    except Exception:
        logger.warning(
            "Non-critical driver onboarding side effects failed for driver_id=%s",
            driver.id,
            exc_info=True,
        )
    return driver


@router.get("/drivers/available", response_model=list[DriverResponse])
def list_available_drivers(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve available drivers (status=available)."""
    logger.info("Listing available drivers")
    effective_org_id = enforce_tenant_scope(user, organization_id)
    drivers = service.get_available_drivers(db)
    return [driver for driver in drivers if driver.organization_id == effective_org_id]


@router.get("/drivers/active", response_model=list[DriverResponse])
def list_active_online_drivers(
    available_only: bool = Query(False),
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.get_active_drivers(db, organization_id=effective_org_id, available_only=available_only)


@router.get("/drivers/active/metrics", response_model=DriverActivePoolMetricsResponse)
def get_active_driver_pool_metrics(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.get_active_driver_pool_metrics(db, organization_id=effective_org_id)


@router.get("/drivers/{driver_id}", response_model=DriverResponse)
def get_driver(
    driver_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve a specific driver by ID."""
    logger.info("Fetching driver: %s", driver_id)
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    return driver


@public_router.post("/drivers/mobile-login", response_model=DriverLoginResponse)
async def driver_mobile_login(
    payload: DriverMobileLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Public driver sign-in for the mobile app (phone verification, no platform JWT)."""
    try:
        driver = service.find_driver_by_login_phone(
            db,
            phone=payload.phone,
            driver_id=payload.driver_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found for this phone number")

    try:
        login_result = service.driver_login(
            db,
            driver_id=driver.id,
            phone=payload.phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    driver_obj = login_result["driver"]
    session_obj = login_result["session"]
    session_token = login_result["session_token"]

    emitter = get_emitter()
    await emitter.emit_driver_status_changed(
        organization_id=driver_obj.organization_id,
        driver_id=driver_obj.id,
        from_status="offline",
        to_status=str(driver_obj.availability_state),
        actor_user_id=str(driver_obj.id),
        details={"event_name": "driver-mobile-online"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=driver_obj.organization_id,
        event_name="driver-online",
        actor_user_id=str(driver_obj.id),
        details={"driver_id": driver_obj.id, "availability_state": driver_obj.availability_state, "source": "mobile_login"},
    )

    response = DriverLoginResponse(
        driver_id=driver_obj.id,
        organization_id=service.resolve_driver_organization_id(db, driver_obj, persist_missing=False),
        session_id=str(session_obj.id),
        session_token=session_token,
        session_state=session_obj.session_state,
        auth_state=driver_obj.auth_state,
        availability_state=driver_obj.availability_state,
        is_online=bool(driver_obj.is_online),
        issued_at=session_obj.issued_at,
        expires_at=session_obj.expires_at,
    )
    record_backend_assignment_sync(
        db,
        request=request,
        event="mobile_login",
        driver_id=driver_obj.id,
        assignment_state=str(driver_obj.availability_state or ""),
        api_response={
            "session_id": str(session_obj.id),
            "session_state": session_obj.session_state,
            "auth_state": driver_obj.auth_state,
            "availability_state": driver_obj.availability_state,
        },
    )
    return response


@router.post("/drivers/mobile-assignment-sync-log")
def ingest_driver_mobile_assignment_sync_log(
    payload: DriverMobileAssignmentSyncLogRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Persist frontend Driver Mobile assignment sync diagnostics to the rotating log."""
    driver_id = payload.authenticated_driver_id
    session_id = resolve_driver_session_id(db, driver_id=driver_id, request=request)
    if not session_id:
        session_id = _sync_safe_text(payload.driver_session_id) or None
    record_driver_mobile_assignment_sync(
        source="frontend",
        event=payload.event,
        authenticated_driver_id=driver_id,
        driver_session_id=session_id,
        requested_ride_id=payload.requested_ride_id,
        assignment_state=payload.assignment_state,
        api_response=payload.api_response,
        frontend_state_transition=payload.frontend_state_transition,
        http_status=payload.http_status,
        route=payload.route or request.url.path,
        http_method=request.method,
        extra=payload.extra,
    )
    return {"ok": True}


@router.post("/ops-shell/hydration-diag-log")
def ingest_ops_shell_hydration_diag_log(
    payload: dict[str, Any] = Body(default_factory=dict),
):
    """Persist ops-shell hydration diagnostics to the rotating log."""
    from app.modules.health_isf.ops_shell_hydration_log import record_ops_shell_hydration

    record_ops_shell_hydration(payload or {})
    return {"ok": True}


@router.post("/drivers/login", response_model=DriverLoginResponse)
async def driver_login(
    payload: DriverLoginRequest,
    request: Request,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, payload.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)

    try:
        login_result = service.driver_login(
            db,
            driver_id=payload.driver_id,
            phone=payload.phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    driver_obj = login_result["driver"]
    session_obj = login_result["session"]
    session_token = login_result["session_token"]

    emitter = get_emitter()
    await emitter.emit_driver_status_changed(
        organization_id=driver_obj.organization_id,
        driver_id=driver_obj.id,
        from_status="offline",
        to_status=str(driver_obj.availability_state),
        actor_user_id=user.user_id,
        details={"event_name": "driver-online"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=driver_obj.organization_id,
        event_name="driver-online",
        actor_user_id=user.user_id,
        details={"driver_id": driver_obj.id, "availability_state": driver_obj.availability_state},
    )

    response = DriverLoginResponse(
        driver_id=driver_obj.id,
        organization_id=driver_obj.organization_id,
        session_id=str(session_obj.id),
        session_token=session_token,
        session_state=session_obj.session_state,
        auth_state=driver_obj.auth_state,
        availability_state=driver_obj.availability_state,
        is_online=bool(driver_obj.is_online),
        issued_at=session_obj.issued_at,
        expires_at=session_obj.expires_at,
    )
    record_backend_assignment_sync(
        db,
        request=request,
        event="driver_login",
        driver_id=driver_obj.id,
        assignment_state=str(driver_obj.availability_state or ""),
        api_response={
            "session_id": str(session_obj.id),
            "session_state": session_obj.session_state,
            "auth_state": driver_obj.auth_state,
        },
    )
    return response


@router.post("/drivers/logout")
async def driver_logout(
    payload: DriverLogoutRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, payload.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        logged_out = service.driver_logout(db, driver_id=payload.driver_id, session_token=payload.session_token)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not logged_out:
        raise HTTPException(status_code=404, detail="Driver not found")

    emitter = get_emitter()
    await emitter.emit_driver_status_changed(
        organization_id=logged_out.organization_id,
        driver_id=logged_out.id,
        from_status="online",
        to_status="offline",
        actor_user_id=user.user_id,
        details={"event_name": "driver-offline"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=logged_out.organization_id,
        event_name="driver-offline",
        actor_user_id=user.user_id,
        details={"driver_id": logged_out.id},
    )
    return {"status": "ok", "driver_id": logged_out.id, "session_state": "revoked"}


@router.post("/drivers/availability", response_model=DriverRuntimeStatusResponse)
async def set_driver_availability(
    payload: DriverAvailabilityRequest,
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, payload.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")

    user: UserContext | None = None
    actor_user_id = ""
    if creds:
        try:
            platform_auth = _platform_user_context(creds, db, allowed_roles=HEALTH_ISF_PLATFORM_ROLES)
            if platform_auth:
                user = platform_auth.user
                actor_user_id = platform_auth.actor_user_id
        except HTTPException:
            pass
    session_token = (payload.session_token or "").strip() or None
    if not session_token:
        session_token = request.headers.get("X-Driver-Session-Token") or request.headers.get("x-driver-session-token")
        session_token = str(session_token).strip() if session_token else None
    if not user and session_token:
        driver_auth = _driver_session_context(payload.driver_id, session_token, db)
        if driver_auth:
            user = driver_auth.user
            actor_user_id = driver_auth.actor_user_id
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    enforce_entity_tenant(user, driver.organization_id)
    previous = str(driver.availability_state or driver.status or "offline")
    try:
        updated = service.set_driver_live_availability(
            db,
            driver_id=payload.driver_id,
            availability_state=payload.availability_state,
            session_token=session_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Driver not found")

    emitter = get_emitter()
    await emitter.emit_driver_status_changed(
        organization_id=updated.organization_id,
        driver_id=updated.id,
        from_status=previous,
        to_status=updated.availability_state,
        actor_user_id=actor_user_id,
        details={"event_name": "driver-availability-updated"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=updated.organization_id,
        event_name="driver-availability-updated",
        actor_user_id=actor_user_id,
        details={"driver_id": updated.id, "availability_state": updated.availability_state},
    )

    runtime = service.get_driver_runtime_status(db, driver_id=updated.id, session_token=session_token)
    return DriverRuntimeStatusResponse(
        driver_id=updated.id,
        organization_id=updated.organization_id,
        auth_state=updated.auth_state,
        availability_state=updated.availability_state,
        is_online=bool(updated.is_online),
        last_seen_at=updated.last_seen_at,
        active_session=bool(runtime and runtime.get("session_valid")),
        active_ride_id=runtime.get("active_ride_id") if runtime else None,
    )


@router.post("/drivers/heartbeat", response_model=DriverRuntimeStatusResponse)
async def driver_heartbeat(
    payload: DriverHeartbeatRequest,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, payload.driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        updated = service.driver_heartbeat(
            db,
            driver_id=payload.driver_id,
            session_token=payload.session_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not updated:
        raise HTTPException(status_code=404, detail="Driver not found")

    emitter = get_emitter()
    await emitter.emit_dispatch_changed(
        organization_id=updated.organization_id,
        event_name="driver-heartbeat",
        actor_user_id=user.user_id,
        details={"driver_id": updated.id, "last_seen_at": updated.last_seen_at.isoformat() if updated.last_seen_at else None},
    )
    await emitter.emit_dispatch_changed(
        organization_id=updated.organization_id,
        event_name="driver-location-updated",
        actor_user_id=user.user_id,
        details={
            "driver_id": updated.id,
            "last_seen_at": updated.last_seen_at.isoformat() if updated.last_seen_at else None,
            "source": "driver_heartbeat",
        },
    )

    runtime = service.get_driver_runtime_status(db, driver_id=updated.id, session_token=payload.session_token)
    return DriverRuntimeStatusResponse(
        driver_id=updated.id,
        organization_id=updated.organization_id,
        auth_state=updated.auth_state,
        availability_state=updated.availability_state,
        is_online=bool(updated.is_online),
        last_seen_at=updated.last_seen_at,
        active_session=bool(runtime and runtime.get("session_valid")),
        active_ride_id=runtime.get("active_ride_id") if runtime else None,
    )


@router.get("/drivers/{driver_id}/status", response_model=DriverRuntimeStatusResponse)
def get_driver_runtime_status(
    driver_id: str,
    session_token: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    runtime = service.get_driver_runtime_status(db, driver_id=driver_id, session_token=session_token)
    if not runtime:
        raise HTTPException(status_code=404, detail="Driver not found")
    row = runtime["driver"]
    return DriverRuntimeStatusResponse(
        driver_id=row.id,
        organization_id=row.organization_id,
        auth_state=row.auth_state,
        availability_state=row.availability_state,
        is_online=bool(row.is_online),
        last_seen_at=row.last_seen_at,
        active_session=bool(runtime.get("session_valid")),
        active_ride_id=runtime.get("active_ride_id"),
    )


@router.get("/drivers/{driver_id}/session/validate", response_model=DriverSessionValidationResponse)
def validate_driver_session(
    driver_id: str,
    session_token: str = Query(..., min_length=8, max_length=512),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    runtime = service.get_driver_runtime_status(db, driver_id=driver_id, session_token=session_token)
    if not runtime:
        raise HTTPException(status_code=404, detail="Driver not found")
    return DriverSessionValidationResponse(
        driver_id=driver.id,
        organization_id=driver.organization_id,
        session_valid=bool(runtime.get("session_valid")),
        session_state=str(runtime.get("session_state") or "inactive"),
        expires_at=runtime.get("expires_at"),
    )


@router.get("/drivers/{driver_id}/assigned-rides", response_model=list[RideResponse])
def get_driver_assigned_rides(
    driver_id: str,
    request: Request,
    organization_id: str | None = Query(None),
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform()),
    db: Session = Depends(get_db),
):
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    resolved_org_id = service.resolve_driver_organization_id(db, driver, persist_missing=True)
    effective_org_id = enforce_tenant_scope(user, organization_id or resolved_org_id)
    enforce_entity_tenant(user, resolved_org_id)
    rides = service.list_driver_assigned_rides(db, organization_id=effective_org_id, driver_id=driver_id)
    response = [_ride_response_with_financials(db, ride) for ride in rides]
    record_backend_assignment_sync(
        db,
        request=request,
        event="assigned_rides_fetch",
        driver_id=driver_id,
        ride_id=str(rides[0].id) if rides else None,
        api_response={
            "count": len(rides),
            "ride_ids": [str(ride.id) for ride in rides[:20]],
        },
    )
    return response


@router.patch("/drivers/{driver_id}", response_model=DriverResponse)
def patch_driver(
    driver_id: str,
    payload: DriverUpdate,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Update driver fields with audit persistence."""
    existing = service.get_driver_by_id(db, driver_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, existing.organization_id)
    driver = service.update_driver(db, driver_id=driver_id, actor_user_id=_user.id, **payload.model_dump(exclude_none=True))
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver


@router.post("/drivers/{driver_id}/accept-ride", response_model=RideResponse)
async def driver_accept_ride(
    driver_id: str,
    payload: DriverRideActionRequest,
    request: Request,
    auth: DriverEndpointAuth = Depends(require_driver_accept_auth()),
    db: Session = Depends(get_db),
):
    user = auth.user
    effective_driver_id = driver_id
    if auth.actor_user_id is None:
        effective_driver_id = str(auth.user.user_id)
    driver = service.get_driver_by_id(db, effective_driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        ride = service.accept_driver_ride(
            db,
            driver_id=effective_driver_id,
            ride_id=payload.ride_id,
            actor_user_id=auth.actor_user_id,
        )
    except service.RideLifecycleConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    emitter = get_emitter()
    await emitter.emit_ride_status_changed(
        organization_id=ride.organization_id,
        ride_id=ride.id,
        from_status=RideStatus.ASSIGNED.value,
        to_status=RideStatus.ASSIGNED.value,
        actor_user_id=auth.actor_user_id,
    )
    await emitter.emit_driver_active_ride_state(
        organization_id=ride.organization_id,
        driver_id=effective_driver_id,
        active_ride_id=ride.id,
        state=RideStatus.ASSIGNED.value,
        actor_user_id=auth.actor_user_id,
        details={"source": "driver_accept_route"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="assignment-accepted",
        actor_user_id=auth.actor_user_id,
        details={"ride_id": ride.id, "driver_id": effective_driver_id},
    )
    await emitter.emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="driver-offer-accepted",
        actor_user_id=auth.actor_user_id,
        details={"ride_id": ride.id, "driver_id": effective_driver_id},
    )
    record_backend_assignment_sync(
        db,
        request=request,
        event="accept_ride",
        driver_id=effective_driver_id,
        ride_id=payload.ride_id,
        assignment_state=str(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", None) or "accepted"),
        api_response={
            "ride_id": str(ride.id),
            "status": str(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", None) or ""),
            "requested_driver_id": driver_id,
            "effective_driver_id": effective_driver_id,
        },
    )
    return ride


@router.post("/drivers/{driver_id}/decline-ride", response_model=RideResponse)
async def driver_decline_ride(
    driver_id: str,
    payload: DriverRideActionRequest,
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform(workflow_only=True)),
    db: Session = Depends(get_db),
):
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        ride = service.decline_driver_ride(
            db,
            driver_id=driver_id,
            ride_id=payload.ride_id,
            actor_user_id=auth.actor_user_id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    emitter = get_emitter()
    await emitter.emit_ride_status_changed(
        organization_id=ride.organization_id,
        ride_id=ride.id,
        from_status=RideStatus.ASSIGNED.value,
        to_status=RideStatus.QUEUED.value,
        actor_user_id=auth.actor_user_id,
    )
    await emitter.emit_driver_active_ride_state(
        organization_id=ride.organization_id,
        driver_id=driver_id,
        active_ride_id=None,
        state=RideStatus.QUEUED.value,
        actor_user_id=auth.actor_user_id,
        details={"source": "driver_decline_route"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="assignment-rejected",
        actor_user_id=auth.actor_user_id,
        details={"ride_id": ride.id, "driver_id": driver_id, "note": payload.note},
    )
    await emitter.emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="driver-offer-rejected",
        actor_user_id=auth.actor_user_id,
        details={"ride_id": ride.id, "driver_id": driver_id, "note": payload.note},
    )
    return ride


@router.post("/drivers/{driver_id}/no-show", response_model=RideResponse)
async def driver_no_show(
    driver_id: str,
    payload: DriverRideActionRequest,
    _user = Depends(require_driver_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        ride = service.driver_no_show(
            db,
            driver_id=driver_id,
            ride_id=payload.ride_id,
            actor_user_id=_user.id,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    emitter = get_emitter()
    await emitter.emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="rider-no-show",
        actor_user_id=_user.id,
        details={"ride_id": ride.id, "driver_id": driver_id, "note": payload.note},
    )
    return ride


@router.post("/drivers/{driver_id}/contact-rider", response_model=DriverContactRiderResponse)
async def driver_contact_rider(
    driver_id: str,
    payload: DriverContactRiderRequest,
    _user = Depends(require_driver_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        result = service.driver_contact_rider(
            db,
            driver_id=driver_id,
            ride_id=payload.ride_id,
            channel=payload.channel,
            message=payload.message,
            actor_user_id=_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DriverContactRiderResponse(**result)


@router.post("/drivers/{driver_id}/arrived-pickup", response_model=RideResponse)
def driver_arrived_pickup(
    driver_id: str,
    payload: DriverRideActionRequest,
    _user = Depends(require_driver_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        ride = service.driver_arrived_pickup(db, driver_id=driver_id, ride_id=payload.ride_id, actor_user_id=_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    return ride


@router.get("/rides/{ride_id}/arrival-status", response_model=RideArrivalStatusResponse)
def get_ride_arrival_status(
    ride_id: str,
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
    arrived = lifecycle_state in {
        RideStatus.ARRIVED.value,
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.COMPLETED.value,
    } or bool(getattr(ride, "arrived_at", None))

    evidence = service.get_latest_ride_execution_action(
        db,
        ride_id=ride.id,
        action_types=["driver_arrived_pickup"],
    )
    evidence_payload = _safe_json_load(getattr(evidence, "payload", None), {}) if evidence else {}

    return RideArrivalStatusResponse(
        ride_id=ride.id,
        organization_id=ride.organization_id,
        lifecycle_state=lifecycle_state,
        arrived=bool(arrived),
        arrived_at=getattr(ride, "arrived_at", None) or getattr(evidence, "created_at", None),
        evidence_event_id=getattr(evidence, "event_id", None),
        evidence_source=getattr(evidence, "source", None),
        evidence_captured_at=getattr(evidence, "created_at", None),
        driver_id=str((evidence_payload or {}).get("driver_id") or getattr(ride, "driver_id", None) or "") or None,
    )


@router.post("/drivers/{driver_id}/pickup-complete", response_model=RideResponse)
async def driver_pickup_complete(
    driver_id: str,
    payload: DriverRideActionRequest,
    _user = Depends(require_driver_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    try:
        ride = service.driver_pickup_complete(db, driver_id=driver_id, ride_id=payload.ride_id, actor_user_id=_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    emitter = get_emitter()
    await emitter.emit_ride_status_changed(
        organization_id=ride.organization_id,
        ride_id=ride.id,
        from_status=RideStatus.ARRIVED.value,
        to_status=RideStatus.IN_PROGRESS.value,
        actor_user_id=_user.id,
    )
    await emitter.emit_driver_active_ride_state(
        organization_id=ride.organization_id,
        driver_id=driver_id,
        active_ride_id=ride.id,
        state=RideStatus.IN_PROGRESS.value,
        actor_user_id=_user.id,
        details={"source": "driver_pickup_route"},
    )
    await emitter.emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="ride-in-progress",
        actor_user_id=_user.id,
        details={"ride_id": ride.id, "driver_id": driver_id},
    )
    return ride


@router.get("/rides/{ride_id}/pickup-status", response_model=RidePickupStatusResponse)
def get_ride_pickup_status(
    ride_id: str,
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
    picked_up = lifecycle_state in {
        RideStatus.RIDER_ONBOARD.value,
        RideStatus.IN_PROGRESS.value,
        RideStatus.COMPLETED.value,
    } or bool(getattr(ride, "picked_up_at", None))
    in_progress = lifecycle_state in {RideStatus.IN_PROGRESS.value, RideStatus.COMPLETED.value}

    evidence = service.get_latest_ride_execution_action(
        db,
        ride_id=ride.id,
        action_types=["pickup_completed", "transport_started"],
    )
    evidence_payload = _safe_json_load(getattr(evidence, "payload", None), {}) if evidence else {}

    return RidePickupStatusResponse(
        ride_id=ride.id,
        organization_id=ride.organization_id,
        lifecycle_state=lifecycle_state,
        picked_up=bool(picked_up),
        in_progress=bool(in_progress),
        picked_up_at=getattr(ride, "picked_up_at", None)
        or getattr(ride, "transporting_at", None)
        or getattr(evidence, "created_at", None),
        evidence_event_id=getattr(evidence, "event_id", None),
        evidence_source=getattr(evidence, "source", None),
        evidence_captured_at=getattr(evidence, "created_at", None),
        driver_id=str((evidence_payload or {}).get("driver_id") or getattr(ride, "driver_id", None) or "") or None,
    )


@router.post("/drivers/{driver_id}/dropoff-complete", response_model=RideResponse)
async def driver_dropoff_complete(
    driver_id: str,
    payload: DriverRideActionRequest,
    auth: DriverEndpointAuth = Depends(require_driver_mobile_or_platform(workflow_only=True)),
    db: Session = Depends(get_db),
):
    user = auth.user
    driver = service.get_driver_by_id(db, driver_id)
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, driver.organization_id)
    previous_driver_status = str(getattr(driver, "status", "") or "")
    try:
        ride = service.driver_dropoff_complete(db, driver_id=driver_id, ride_id=payload.ride_id, actor_user_id=auth.actor_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    await _emit_driver_trip_completion_events(
        db=db,
        ride=ride,
        driver_id=driver_id,
        actor_user_id=auth.actor_user_id,
        previous_driver_status=previous_driver_status,
        source="driver_dropoff_route",
    )
    return ride


@router.post("/drivers/{driver_id}/set-status", response_model=DriverResponse)
async def driver_set_status(
    driver_id: str,
    payload: DriverStatusUpdateRequest,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Update driver operational status with real-time events."""
    # Get old status first
    old_driver = service.get_driver_by_id(db, driver_id)
    if not old_driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    enforce_entity_tenant(user, old_driver.organization_id)
    
    old_status = old_driver.status
    organization_id = old_driver.organization_id
    
    try:
        driver = service.set_driver_operational_status(
            db,
            driver_id=driver_id,
            status=payload.status,
            actor_user_id=_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    
    # Log activity
    ActivityLogService.log_activity(
        db,
        organization_id=organization_id,
        action=ActivityAction.DRIVER_STATUS_CHANGED,
        description=f"Driver status changed to {payload.status}",
        driver_id=driver_id,
        actor_user_id=_user.id,
    )
    
    # Emit real-time event (idempotent + retry queue fallback)
    emitter = get_emitter()
    event_payload = {
        "driver_id": driver_id,
        "from_status": str(old_status),
        "to_status": str(payload.status),
        "driver_name": driver.name,
    }
    await _emit_with_retry_queue(
        db=db,
        organization_id=organization_id,
        event_type=EventType.DRIVER_STATUS_CHANGED.value,
        event_payload=event_payload,
        emit_callable=lambda: emitter.emit_driver_status_changed(
            organization_id=organization_id,
            driver_id=driver_id,
            from_status=str(old_status),
            to_status=str(payload.status),
            actor_user_id=_user.id,
        ),
        idempotency_key=_event_key("driver_status", driver_id, str(payload.status), str(driver.version)),
        driver_id=driver_id,
    )

    metrics = get_operational_metrics_registry()
    metrics.increment("dispatch.driver_status_updates")
    
    # Log event
    RealTimeEventService.log_event(
        db,
        organization_id=organization_id,
        event_type=EventType.DRIVER_STATUS_CHANGED,
        payload={
            "driver_id": driver_id,
            "from_status": str(old_status),
            "to_status": str(payload.status),
            "driver_name": driver.name,
        },
        driver_id=driver_id,
        created_by_user_id=_user.id,
    )
    
    return driver


# ── Providers Endpoints ───────────────────────────────────────────────────────

@router.get("/providers", response_model=list[ProviderResponse])
def list_providers(
    skip: int = 0,
    limit: int = 50,
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve all active providers (paginated)."""
    logger.info("Listing providers: skip=%d, limit=%d", skip, limit)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    seed_summary = service.ensure_sample_providers(db, organization_id=effective_org_id)
    providers = service.list_providers_for_organization(
        db,
        organization_id=effective_org_id,
        skip=skip,
        limit=limit,
    )
    if not providers:
        logger.warning(
            "Provider list empty for org=%s after seed attempt: %s",
            effective_org_id,
            seed_summary,
        )
        db.expire_all()
        providers = service.list_providers_for_organization(
            db,
            organization_id=effective_org_id,
            skip=skip,
            limit=limit,
        )
    return providers


@router.post("/providers", response_model=ProviderResponse, status_code=201)
async def create_provider(
    payload: ProviderCreate,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Create a tenant-scoped provider for onboarding workflows."""
    organization_id = enforce_tenant_scope(user, None)
    idempotency_key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if idempotency_key:
        existing_key = IdempotencyService.get_key(db, idempotency_key)
        if existing_key and existing_key.resource_id:
            existing_provider = service.get_provider_by_id(db, existing_key.resource_id)
            if existing_provider:
                enforce_entity_tenant(user, existing_provider.organization_id)
                return existing_provider
        if existing_key and not existing_key.resource_id:
            raise HTTPException(status_code=409, detail="Duplicate onboarding request in progress")
        IdempotencyService.reserve_key(
            db,
            idempotency_key=idempotency_key,
            scope="provider_onboarding",
            resource_id=None,
        )

    try:
        provider = service.create_provider(
            db,
            organization_id=organization_id,
            name=payload.name,
            address=payload.address,
            phone=payload.phone,
            service_type=payload.service_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if idempotency_key:
        IdempotencyService.bind_resource(db, idempotency_key=idempotency_key, resource_id=provider.id)

    await get_emitter().emit_provider_updated(
        organization_id=organization_id,
        provider_id=provider.id,
        actor_user_id=_user.id,
        details={"operation": "create", "name": provider.name},
    )
    SecurityAuditService.log_action(
        db,
        organization_id=organization_id,
        action_type="provider_created",
        actor_user_id=user.user_id,
        details={
            "provider_id": provider.id,
            "provider_phone": provider.phone,
            "idempotency_key": bool(idempotency_key),
        },
    )
    WorkflowOrchestrationService.record_onboarding_hook(
        db,
        organization_id=organization_id,
        entity_type="provider",
        entity_id=provider.id,
        actor_user_id=_user.id,
        payload={
            "provider_phone": provider.phone,
            "service_type": provider.service_type,
        },
    )
    RealTimeEventService.log_event(
        db,
        organization_id=organization_id,
        event_type=EventType.PROVIDER_UPDATED,
        payload={
            "provider_id": provider.id,
            "operation": "create",
            "service_type": provider.service_type,
        },
        created_by_user_id=_user.id,
    )
    OperationalSynchronizationEngine.publish_event(
        organization_id=organization_id,
        event_type=OperationalEventType.PROVIDER_STATE_CHANGED,
        payload={
            "event_type": "provider_created",
            "organization_id": organization_id,
            "provider_id": provider.id,
            "service_type": provider.service_type,
            "actor_user_id": _user.id,
        },
        role_scope=["dispatcher", "provider", "staff", "admin"],
        source_nonce=f"onboarding_provider:{organization_id}:{provider.id}",
        metadata={"source": "onboarding_api"},
    )
    return provider


@router.get("/providers/{provider_id}", response_model=ProviderResponse)
def get_provider(
    provider_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve a specific provider by ID."""
    logger.info("Fetching provider: %s", provider_id)
    provider = service.get_provider_by_id(db, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)
    return provider


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
async def patch_provider(
    provider_id: str,
    payload: ProviderUpdate,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Update provider fields with audit persistence."""
    current = service.get_provider_by_id(db, provider_id)
    if not current:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, current.organization_id)
    provider = service.update_provider(db, provider_id=provider_id, actor_user_id=_user.id, **payload.model_dump(exclude_none=True))
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    await get_emitter().emit_provider_updated(
        organization_id=provider.organization_id,
        provider_id=provider.id,
        actor_user_id=_user.id,
        details={"fields": sorted(list(payload.model_dump(exclude_none=True).keys()))},
    )
    RealTimeEventService.log_event(
        db,
        organization_id=provider.organization_id,
        event_type=EventType.PROVIDER_UPDATED,
        payload={
            "provider_id": provider.id,
            "fields": sorted(list(payload.model_dump(exclude_none=True).keys())),
        },
        created_by_user_id=_user.id,
    )
    return provider


# ── DISPATCHER COMMAND CENTER ENDPOINTS ───────────────────────────────────────

@router.patch("/dispatcher/rides/{ride_id}/reassign-driver", response_model=RideResponse)
async def dispatcher_reassign_driver(
    ride_id: str,
    payload: RideAssignDriverRequest,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Reassign a ride to a different driver (dispatcher action with audit logging)."""
    logger.info("Dispatcher reassigning ride: ride=%s from_driver=%s to_driver=%s", 
                ride_id, _user.id, payload.driver_id)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    # Acquire assignment lock
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride_id, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire reassignment lock")
    
    try:
        previous_driver_id = ride.driver_id
        ride = service.assign_driver_to_ride(
            db,
            ride_id=ride_id,
            driver_id=payload.driver_id,
            actor_user_id=_user.id,
            allow_reassignment=True,
        )
        
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        
        # Log dispatcher reassignment action
        ActivityLogService.log_activity(
            db,
            organization_id=ride.organization_id,
            action=ActivityAction.RIDE_ASSIGNED,
            description=f"Ride reassigned by dispatcher from {previous_driver_id} to {payload.driver_id}",
            ride_id=ride_id,
            driver_id=payload.driver_id,
            actor_user_id=_user.id,
        )
        
        # Security audit for reassignment
        SecurityAuditService.log_action(
            db,
            organization_id=ride.organization_id,
            action_type="dispatcher_ride_reassignment",
            actor_user_id=user.user_id,
            ride_id=ride_id,
            details={"from_driver": previous_driver_id, "to_driver": payload.driver_id},
        )
        
        # Emit real-time event
        emitter = get_emitter()
        await emitter.emit_ride_reassigned(
            organization_id=ride.organization_id,
            ride_id=ride_id,
            from_driver_id=previous_driver_id,
            to_driver_id=payload.driver_id,
            driver_name=ride.driver.name if ride.driver else None,
            actor_user_id=_user.id,
        )
        await emitter.emit_driver_active_ride_state(
            organization_id=ride.organization_id,
            driver_id=payload.driver_id,
            active_ride_id=ride_id,
            state=RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status),
            actor_user_id=_user.id,
            details={"source": "reassign_driver", "from_driver_id": previous_driver_id},
        )
        
        metrics = get_operational_metrics_registry()
        metrics.increment("dispatcher.reassignments.total")
        metrics.record_event_ts("dispatcher_actions")
        
        return ride
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride_id)


# ── Phase 46 Dispatch Intelligence Endpoints ────────────────────────────────

@router.post("/dispatch/auto-assign", response_model=DispatchAutoAssignResponse)
async def dispatch_auto_assign(
    payload: DispatchAutoAssignRequest,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, payload.ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    request_id = _resolve_request_id(request)
    if ConcurrentAssignmentService.has_assignment_lock(db, ride.id):
        raise HTTPException(status_code=409, detail="Ride is currently undergoing assignment mutation")
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride.id, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire assignment lock")

    try:
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="dispatch-search-started",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "request_id": request_id},
            request_id=request_id,
            lifecycle_state="searching",
            transition_reason="auto_assign_started",
            assignment_transition_source="dispatch_auto_assign",
        )

        expired_rows = service.expire_stale_dispatch_offers(db, organization_id=ride.organization_id, ride_id=ride.id)
        for row in expired_rows:
            details = {"ride_id": row.ride_id, "offer_id": row.id, "driver_id": row.driver_id, "request_id": request_id}
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=row.ride_id,
                event_name="driver-offer-expired",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=row.id,
                driver_id=row.driver_id,
                lifecycle_state="reassignment_pending",
                transition_reason="offer_timeout",
                assignment_transition_source="dispatch_auto_assign",
            )
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=row.ride_id,
                event_name="assignment-expired",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=row.id,
                driver_id=row.driver_id,
                lifecycle_state="reassignment_pending",
                transition_reason="offer_timeout",
                assignment_transition_source="dispatch_auto_assign",
            )

        result = service.auto_assign_request(
            db,
            ride_id=ride.id,
            actor_user_id=_user.id,
            offer_timeout_seconds=payload.offer_timeout_seconds,
        )
        offer = result.get("offer")
        selected_driver_id = None
        selected_score = None
        assignment_state = "pending_assignment"
        if offer:
            selected_driver_id = offer.driver_id
            selected_score = float(offer.score) if offer.score is not None else None
            assignment_state = str(offer.assignment_state)
            details = {
                "ride_id": ride.id,
                "offer_id": offer.id,
                "driver_id": offer.driver_id,
                "offer_expires_at": offer.offer_expires_at.isoformat() if offer.offer_expires_at else None,
                "request_id": request_id,
            }
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="driver-offer-issued",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=offer.id,
                driver_id=offer.driver_id,
                lifecycle_state=str(offer.assignment_state),
                transition_reason="offer_issued",
                assignment_transition_source="dispatch_auto_assign",
            )
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="assignment-issued",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=offer.id,
                driver_id=offer.driver_id,
                lifecycle_state=str(offer.assignment_state),
                transition_reason="offer_issued",
                assignment_transition_source="dispatch_auto_assign",
            )

        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="auto-assignment-completed",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "offer_id": offer.id if offer else None, "driver_id": selected_driver_id, "request_id": request_id},
            request_id=request_id,
            assignment_id=offer.id if offer else None,
            driver_id=selected_driver_id,
            lifecycle_state=assignment_state,
            transition_reason="auto_assign_completed",
            assignment_transition_source="dispatch_auto_assign",
        )

        return DispatchAutoAssignResponse(
            ride_id=ride.id,
            assignment_state=assignment_state,
            selected_driver_id=selected_driver_id,
            selected_score=selected_score,
            offer=_serialize_dispatch_offer(offer) if offer else None,
            candidate_count=len(result.get("candidates") or []),
            candidate_scores=list(result.get("candidate_snapshot") or result.get("candidates") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride.id)


@router.post("/dispatch/assign-newest-queue", response_model=DispatchAutoAssignResponse)
async def dispatch_assign_newest_queue(
    offer_timeout_seconds: int = Query(90, ge=10, le=600),
    request: Request = cast(Request, None),
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Assign the newest unassigned dispatch-queue ride to the best eligible driver."""
    effective_org_id = enforce_tenant_scope(user, user.organization_id)
    request_id = _resolve_request_id(request)
    resolved = service.get_newest_unassigned_queue_ride(db, organization_id=effective_org_id)
    if not resolved:
        raise HTTPException(status_code=404, detail="No assignable rides in dispatch queue")
    ride, _queue_row = resolved

    if ConcurrentAssignmentService.has_assignment_lock(db, ride.id):
        raise HTTPException(status_code=409, detail="Ride is currently undergoing assignment mutation")
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride.id, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire assignment lock")

    try:
        result = service.assign_newest_queue_ride(
            db,
            organization_id=effective_org_id,
            actor_user_id=_user.id,
            offer_timeout_seconds=offer_timeout_seconds,
        )
        offer = result.get("offer")
        selected_driver = result.get("selected_driver")
        selected_driver_id = str(getattr(selected_driver, "id", None) or getattr(offer, "driver_id", None) or "")
        selected_score = float(getattr(offer, "score", None)) if offer and offer.score is not None else None
        assignment_state = str(getattr(offer, "assignment_state", None) or "pending_assignment")
        if offer:
            details = {
                "ride_id": ride.id,
                "offer_id": offer.id,
                "driver_id": offer.driver_id,
                "offer_expires_at": offer.offer_expires_at.isoformat() if offer.offer_expires_at else None,
                "request_id": request_id,
            }
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="driver-offer-issued",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=offer.id,
                driver_id=offer.driver_id,
                lifecycle_state=str(offer.assignment_state),
                transition_reason="offer_issued",
                assignment_transition_source="dispatch_assign_newest_queue",
            )
        return DispatchAutoAssignResponse(
            ride_id=ride.id,
            assignment_state=assignment_state,
            selected_driver_id=selected_driver_id or None,
            selected_score=selected_score,
            offer=_serialize_dispatch_offer(offer) if offer else None,
            candidate_count=len(result.get("candidates") or []),
            candidate_scores=list(result.get("candidate_snapshot") or result.get("candidates") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride.id)


@router.post("/dispatch/recommendations/generate", response_model=DispatchRecommendationResponse)
async def dispatch_generate_recommendation(
    payload: DispatchRecommendationGenerateRequest,
    _user=Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Generate or refresh an AI dispatch recommendation for a queued ride."""
    ride = service.get_ride_by_id(db, payload.ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    result = service.recommend_driver_for_ride(
        db,
        ride_id=ride.id,
        actor_user_id=_user.id,
    )
    recommendation = result.get("recommendation")
    selected_driver = result.get("selected_driver")
    if not recommendation:
        return DispatchRecommendationResponse(
            ride_id=ride.id,
            assignment_state="pending_assignment",
            recommended_driver_id=None,
            recommended_score=None,
            dispatcher_message="No dispatch-ready drivers available",
            offer=None,
        )
    return DispatchRecommendationResponse(
        ride_id=ride.id,
        assignment_state=str(recommendation.assignment_state),
        recommended_driver_id=str(recommendation.driver_id) if recommendation.driver_id else None,
        recommended_score=float(recommendation.score) if recommendation.score is not None else None,
        dispatcher_message=(
            f"AI recommended {getattr(selected_driver, 'name', 'driver')} — awaiting dispatcher approval"
            if selected_driver
            else "AI dispatch recommendation awaiting dispatcher approval"
        ),
        offer=None,
    )


@router.post("/dispatch/recommendations/approve", response_model=DispatchRecommendationResponse)
async def dispatch_approve_recommendation(
    payload: DispatchRecommendationApproveRequest,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Approve an AI dispatch recommendation and issue the final driver assignment offer."""
    ride = service.get_ride_by_id(db, payload.ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    request_id = _resolve_request_id(request)
    if ConcurrentAssignmentService.has_assignment_lock(db, ride.id):
        raise HTTPException(status_code=409, detail="Ride is currently undergoing assignment mutation")
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride.id, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire assignment lock")

    try:
        result = service.approve_dispatch_recommendation(
            db,
            ride_id=ride.id,
            actor_user_id=_user.id,
            driver_id=payload.driver_id,
            offer_timeout_seconds=payload.offer_timeout_seconds,
        )
        offer = result.get("offer")
        selected_driver_id = offer.driver_id if offer else None
        assignment_state = str(offer.assignment_state) if offer else "offered"
        details = {
            "ride_id": ride.id,
            "offer_id": offer.id if offer else None,
            "driver_id": selected_driver_id,
            "request_id": request_id,
            "source": "dispatch_recommendation_approve",
        }
        if offer:
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="driver-offer-issued",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=offer.id,
                driver_id=selected_driver_id,
                lifecycle_state=assignment_state,
                transition_reason="recommendation_approved",
                assignment_transition_source="dispatch_approve_recommendation",
            )
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="assignment-issued",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=offer.id,
                driver_id=selected_driver_id,
                lifecycle_state=assignment_state,
                transition_reason="recommendation_approved",
                assignment_transition_source="dispatch_approve_recommendation",
            )
        return DispatchRecommendationResponse(
            ride_id=ride.id,
            assignment_state=assignment_state,
            recommended_driver_id=selected_driver_id,
            recommended_score=float(offer.score) if offer and offer.score is not None else None,
            dispatcher_message="AI recommendation approved and driver offer issued",
            offer=_serialize_dispatch_offer(offer) if offer else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride.id)


@router.post("/dispatch/reassign", response_model=DispatchAutoAssignResponse)
async def dispatch_reassign(
    payload: DispatchReassignRequest,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, payload.ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    request_id = _resolve_request_id(request)
    if ConcurrentAssignmentService.has_assignment_lock(db, ride.id):
        raise HTTPException(status_code=409, detail="Ride is currently undergoing assignment mutation")
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride.id, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire reassignment lock")

    try:
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="reassignment-started",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "reason": payload.reason, "request_id": request_id},
            request_id=request_id,
            lifecycle_state="reassignment_pending",
            transition_reason=str(payload.reason or "reassign_requested"),
            assignment_transition_source="dispatch_reassign",
        )
        result = service.reassign_expired_request(
            db,
            ride_id=ride.id,
            actor_user_id=_user.id,
            offer_timeout_seconds=payload.offer_timeout_seconds,
            reason=payload.reason,
        )
        offer = result.get("offer")
        details = {
            "ride_id": ride.id,
            "offer_id": offer.id if offer else None,
            "driver_id": offer.driver_id if offer else None,
            "reason": payload.reason,
            "request_id": request_id,
        }
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="reassignment-completed",
            actor_user_id=_user.id,
            details=details,
            request_id=request_id,
            assignment_id=offer.id if offer else None,
            driver_id=offer.driver_id if offer else None,
            lifecycle_state=str(offer.assignment_state) if offer else "reassignment_pending",
            transition_reason=str(payload.reason or "reassign_requested"),
            assignment_transition_source="dispatch_reassign",
        )
        if offer:
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="assignment-reassigned",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=offer.id,
                driver_id=offer.driver_id,
                lifecycle_state=str(offer.assignment_state),
                transition_reason=str(payload.reason or "reassign_requested"),
                assignment_transition_source="dispatch_reassign",
            )

        return DispatchAutoAssignResponse(
            ride_id=ride.id,
            assignment_state=str(offer.assignment_state) if offer else "reassignment_pending",
            selected_driver_id=offer.driver_id if offer else None,
            selected_score=float(offer.score) if offer and offer.score is not None else None,
            offer=_serialize_dispatch_offer(offer) if offer else None,
            candidate_count=len(result.get("candidates") or []),
            candidate_scores=list(result.get("candidate_snapshot") or result.get("candidates") or []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride.id)


@router.post("/dispatch/offers/{offer_id}/accept", response_model=DispatchOfferResponse)
async def dispatch_accept_offer(
    offer_id: str,
    request: Request,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    existing_offer = service.get_dispatch_offer_by_id(db, offer_id)
    if not existing_offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    ride_id_for_lock = existing_offer.ride_id
    request_id = _resolve_request_id(request)
    if ConcurrentAssignmentService.has_assignment_lock(db, ride_id_for_lock):
        raise HTTPException(status_code=409, detail="Ride is currently undergoing assignment mutation")
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride_id_for_lock, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire assignment lock")
    try:
        accepted = service.accept_assignment_offer(db, offer_id=offer_id, actor_user_id=_user.id)
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride_id_for_lock)

    ride = service.get_ride_by_id(db, accepted.ride_id)
    if ride:
        enforce_entity_tenant(user, ride.organization_id)
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="assignment-accepted",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "offer_id": accepted.id, "driver_id": accepted.driver_id, "request_id": request_id},
            request_id=request_id,
            assignment_id=accepted.id,
            driver_id=accepted.driver_id,
            lifecycle_state=str(accepted.assignment_state),
            transition_reason="offer_accepted",
            assignment_transition_source="dispatch_accept_offer",
        )
    return _serialize_dispatch_offer(accepted)


@router.post("/dispatch/offers/{offer_id}/reject", response_model=DispatchOfferResponse)
async def dispatch_reject_offer(
    offer_id: str,
    reason: str | None = Query(None, max_length=512),
    request: Request = cast(Request, None),
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    existing_offer = service.get_dispatch_offer_by_id(db, offer_id)
    if not existing_offer:
        raise HTTPException(status_code=404, detail="Offer not found")
    ride_id_for_lock = existing_offer.ride_id
    request_id = _resolve_request_id(request)
    if ConcurrentAssignmentService.has_assignment_lock(db, ride_id_for_lock):
        raise HTTPException(status_code=409, detail="Ride is currently undergoing assignment mutation")
    lock = ConcurrentAssignmentService.acquire_assignment_lock(db, ride_id_for_lock, _user.id, 30)
    if not lock:
        raise HTTPException(status_code=409, detail="Could not acquire assignment lock")
    try:
        rejected = service.reject_assignment_offer(
            db,
            offer_id=offer_id,
            actor_user_id=_user.id,
            reason=reason,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=400, detail=message) from exc
    finally:
        ConcurrentAssignmentService.release_assignment_lock(db, ride_id_for_lock)

    ride = service.get_ride_by_id(db, rejected.ride_id)
    if ride:
        enforce_entity_tenant(user, ride.organization_id)
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="driver-offer-expired",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "offer_id": rejected.id, "driver_id": rejected.driver_id, "reason": "rejected", "request_id": request_id},
            request_id=request_id,
            assignment_id=rejected.id,
            driver_id=rejected.driver_id,
            lifecycle_state=str(rejected.assignment_state),
            transition_reason="rejected",
            assignment_transition_source="dispatch_reject_offer",
        )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="assignment-rejected",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "offer_id": rejected.id, "driver_id": rejected.driver_id, "reason": reason, "request_id": request_id},
            request_id=request_id,
            assignment_id=rejected.id,
            driver_id=rejected.driver_id,
            lifecycle_state=str(rejected.assignment_state),
            transition_reason=str(reason or "rejected"),
            assignment_transition_source="dispatch_reject_offer",
        )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="reassignment-started",
            actor_user_id=_user.id,
            details={"ride_id": ride.id, "source_offer_id": rejected.id, "request_id": request_id},
            request_id=request_id,
            assignment_id=rejected.id,
            driver_id=rejected.driver_id,
            lifecycle_state=str(rejected.assignment_state),
            transition_reason=str(reason or "rejected"),
            assignment_transition_source="dispatch_reject_offer",
        )
        reassign_result = service.reassign_expired_request(
            db,
            ride_id=ride.id,
            actor_user_id=_user.id,
            offer_timeout_seconds=int(rejected.timeout_seconds or 90),
            reason=reason,
        )
        new_offer = reassign_result.get("offer")
        details = {
            "ride_id": ride.id,
            "source_offer_id": rejected.id,
            "offer_id": new_offer.id if new_offer else None,
            "driver_id": new_offer.driver_id if new_offer else None,
            "request_id": request_id,
        }
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride.id,
            event_name="reassignment-completed",
            actor_user_id=_user.id,
            details=details,
            request_id=request_id,
            assignment_id=new_offer.id if new_offer else None,
            driver_id=new_offer.driver_id if new_offer else None,
            lifecycle_state=str(new_offer.assignment_state) if new_offer else "reassignment_pending",
            transition_reason=str(reason or "rejected"),
            assignment_transition_source="dispatch_reject_offer",
        )
        if new_offer:
            await _emit_dispatch_lifecycle_event(
                db=db,
                organization_id=ride.organization_id,
                ride_id=ride.id,
                event_name="assignment-reassigned",
                actor_user_id=_user.id,
                details=details,
                request_id=request_id,
                assignment_id=new_offer.id,
                driver_id=new_offer.driver_id,
                lifecycle_state=str(new_offer.assignment_state),
                transition_reason=str(reason or "rejected"),
                assignment_transition_source="dispatch_reject_offer",
            )
    return _serialize_dispatch_offer(rejected)


@router.get("/dispatch/queue", response_model=list[DispatchQueueItemResponse])
def dispatch_queue(
    organization_id: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    service.expire_stale_dispatch_offers(db, organization_id=effective_org_id)
    return [
        DispatchQueueItemResponse(**row)
        for row in service.get_dispatch_queue(db, organization_id=effective_org_id, limit=limit)
    ]


@router.get("/dispatch/active-assignments", response_model=list[DispatchActiveAssignmentItemResponse])
def dispatch_active_assignments(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    service.expire_stale_dispatch_offers(db, organization_id=effective_org_id)
    rows = service.get_dispatch_active_assignments(db, organization_id=effective_org_id)
    current_user_id = str(user.user_id or "")
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        owner_id = str(row.get("ownership_locked_by_user_id") or "")
        normalized_rows.append(
            {
                **row,
                "ownership_is_current_user": bool(owner_id and current_user_id and owner_id == current_user_id),
            }
        )
    return [DispatchActiveAssignmentItemResponse(**row) for row in normalized_rows]


@router.get("/dispatcher/coordination/locks")
def dispatcher_coordination_locks(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ensure_admin_action(user)
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return {
        "organization_id": effective_org_id,
        "generated_at": now(),
        "locks": ConcurrentAssignmentService.list_active_assignment_locks(
            db,
            organization_id=effective_org_id,
            limit=300,
        ),
    }


@router.post("/dispatcher/rides/{ride_id}/claim-ownership")
async def dispatcher_claim_ownership(
    ride_id: str,
    lease_seconds: int = Query(120, ge=15, le=900),
    force: bool = Query(False),
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    effective_org_id = enforce_tenant_scope(user, organization_id)
    enforce_entity_tenant(user, ride.organization_id)
    if ride.organization_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Ride does not belong to requested organization")

    lock = ConcurrentAssignmentService.claim_or_refresh_assignment_lock(
        db,
        ride_id=ride_id,
        user_id=user.user_id,
        lock_duration_seconds=lease_seconds,
        force=force,
    )
    if not lock:
        active = ConcurrentAssignmentService.get_assignment_lock_details(db, ride_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ride ownership is currently held by another dispatcher",
                "active_lock": active,
            },
        )

    ActivityLogService.log_activity(
        db,
        organization_id=effective_org_id,
        action=ActivityAction.RIDE_ASSIGNED,
        description="Dispatcher claimed ride ownership lock",
        ride_id=ride_id,
        actor_user_id=user.user_id,
        details={"lease_seconds": lease_seconds, "force": force},
    )
    await get_emitter().emit_dispatch_changed(
        organization_id=effective_org_id,
        event_name="ownership-claimed",
        actor_user_id=user.user_id,
        details={
            "ride_id": ride_id,
            "locked_by_user_id": lock.locked_by_user_id,
            "expires_at": lock.expires_at.isoformat() if lock.expires_at else None,
        },
    )
    return {
        "ride_id": ride_id,
        "locked": True,
        "locked_by_user_id": lock.locked_by_user_id,
        "locked_at": lock.locked_at,
        "expires_at": lock.expires_at,
    }


@router.post("/dispatcher/rides/{ride_id}/handoff-ownership")
async def dispatcher_handoff_ownership(
    ride_id: str,
    to_user_id: str = Query(..., min_length=1),
    reason: str = Query("manual_handoff", min_length=1, max_length=256),
    lease_seconds: int = Query(180, ge=15, le=1200),
    force: bool = Query(False),
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    effective_org_id = enforce_tenant_scope(user, organization_id)
    enforce_entity_tenant(user, ride.organization_id)
    if ride.organization_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Ride does not belong to requested organization")

    lock = ConcurrentAssignmentService.handoff_assignment_lock(
        db,
        ride_id=ride_id,
        from_user_id=user.user_id,
        to_user_id=to_user_id,
        lock_duration_seconds=lease_seconds,
        force=force,
    )
    if not lock:
        active = ConcurrentAssignmentService.get_assignment_lock_details(db, ride_id)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Ownership handoff blocked by active lock",
                "active_lock": active,
            },
        )

    ActivityLogService.log_activity(
        db,
        organization_id=effective_org_id,
        action=ActivityAction.RIDE_REASSIGNED,
        description="Dispatcher ownership handoff executed",
        ride_id=ride_id,
        actor_user_id=user.user_id,
        details={"to_user_id": to_user_id, "reason": reason, "lease_seconds": lease_seconds, "force": force},
    )
    await get_emitter().emit_dispatch_changed(
        organization_id=effective_org_id,
        event_name="ownership-handoff",
        actor_user_id=user.user_id,
        details={
            "ride_id": ride_id,
            "to_user_id": to_user_id,
            "reason": reason,
            "expires_at": lock.expires_at.isoformat() if lock.expires_at else None,
        },
    )
    return {
        "ride_id": ride_id,
        "handoff": "completed",
        "to_user_id": to_user_id,
        "reason": reason,
        "expires_at": lock.expires_at,
    }


@router.post("/dispatcher/rides/{ride_id}/supervisor-escalation-hook")
async def dispatcher_supervisor_escalation_hook(
    ride_id: str,
    summary: str = Query("Dispatcher requested supervisor assist", min_length=1, max_length=512),
    severity: str = Query("high", pattern="^(warn|high|critical)$"),
    organization_id: str | None = Query(None),
    _: None = Depends(require_dispatcher_workflow_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    effective_org_id = enforce_tenant_scope(user, organization_id)
    enforce_entity_tenant(user, ride.organization_id)
    if ride.organization_id != effective_org_id:
        raise HTTPException(status_code=403, detail="Ride does not belong to requested organization")

    ActivityLogService.log_activity(
        db,
        organization_id=effective_org_id,
        action=ActivityAction.RIDE_ESCALATED,
        description="Supervisor escalation hook emitted from dispatcher command center",
        ride_id=ride_id,
        actor_user_id=user.user_id,
        details={"severity": severity, "summary": summary},
    )
    await get_emitter().emit_dispatch_changed(
        organization_id=effective_org_id,
        event_name="supervisor-escalation-hook",
        actor_user_id=user.user_id,
        details={"ride_id": ride_id, "severity": severity, "summary": summary},
    )
    return {
        "ride_id": ride_id,
        "escalated": True,
        "severity": severity,
        "summary": summary,
        "generated_at": now(),
    }


@router.get("/dispatcher/intelligence/overview")
def dispatcher_intelligence_overview(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    websocket = get_broadcaster().get_websocket_health_stats(organization_id=effective_org_id)
    runtime_state = get_live_transport_runtime_manager().runtime_snapshot(
        effective_org_id,
        include_timeline=False,
        limit=25,
    )
    replay = get_live_transport_runtime_manager().replay(
        effective_org_id,
        after_sequence=max(0, int(runtime_state.get("sequence", 0) or 0) - 25),
        limit=25,
    )
    queue = service.get_dispatch_queue(db, organization_id=effective_org_id, limit=300)
    active = service.get_dispatch_active_assignments(db, organization_id=effective_org_id, limit=300)
    locks = ConcurrentAssignmentService.list_active_assignment_locks(db, organization_id=effective_org_id, limit=300)

    now_ts = _as_utc_datetime(now())
    stale_assignments = [
        row for row in queue
        if row.get("offer_expires_at") and _as_utc_datetime(row.get("offer_expires_at")) <= now_ts
    ]
    delayed_queue = [
        row for row in queue
        if row.get("requested_at") and (now_ts - _as_utc_datetime(row.get("requested_at"))).total_seconds() >= 900
    ]
    lock_conflicts = len([row for row in locks if row.get("locked_by_user_id")])
    replay_safe = bool(replay.get("replay_safe", True)) and bool(replay.get("sequence_monotonic", True))

    return {
        "organization_id": effective_org_id,
        "generated_at": now(),
        "dispatch_health": {
            "queue_depth": len(queue),
            "active_assignments": len(active),
            "stale_assignments": len(stale_assignments),
            "delayed_queue_items": len(delayed_queue),
            "lock_conflicts": lock_conflicts,
            "health_state": "stable" if len(stale_assignments) == 0 and len(delayed_queue) < 3 else "watch",
        },
        "runtime_visibility": {
            "websocket_state": websocket,
            "hydration": {
                "last_reconciliation_at": runtime_state.get("last_reconciliation_at"),
                "deterministic_event_ordering": bool(runtime_state.get("deterministic_event_ordering", True)),
            },
            "replay": {
                "replay_safe": replay_safe,
                "latest_sequence": int(replay.get("latest_sequence", 0) or 0),
                "sample_events": len(list(replay.get("events") or [])),
            },
        },
        "sessions": {
            "dispatcher_active": int(websocket.get("dispatcher_connections", 0) or 0),
            "driver_active": int(websocket.get("driver_connections", 0) or 0),
            "provider_registry": len(list(runtime_state.get("provider_coordination_registry") or [])),
        },
        "coordination": {
            "active_locks": locks,
            "stale_assignments": stale_assignments[:25],
            "delayed_queue": delayed_queue[:25],
        },
        "transportation_first": True,
    }


@router.post("/dispatcher/rides/{ride_id}/auto-assign", response_model=RideResponse)
async def dispatcher_auto_assign_driver(
    ride_id: str,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Auto-assign best available driver using orchestration priorities and overload protection."""
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)

    overload = DispatchOrchestrationEngine.evaluate_overload(db, ride.organization_id)
    if overload.get("overloaded") and int(overload.get("available_drivers") or 0) == 0:
        try:
            service.update_ride_status(
                db,
                ride_id=ride.id,
                status=RideStatus.ESCALATED.value,
                actor_user_id=_user.id,
            )
        except ValueError:
            pass
        ActivityLogService.log_activity(
            db,
            organization_id=ride.organization_id,
            action=ActivityAction.RIDE_ESCALATED,
            description="Auto-assignment escalated due to overload and no available drivers",
            ride_id=ride.id,
            actor_user_id=_user.id,
            details=overload,
        )
        raise HTTPException(status_code=409, detail="Dispatch overload: ride escalated and awaiting manual intervention")

    suggested_driver = DispatchOrchestrationEngine.select_best_driver(
        db,
        organization_id=ride.organization_id,
        ride=ride,
        exclude_driver_ids={str(ride.driver_id)} if ride.driver_id else set(),
    )
    if not suggested_driver:
        raise HTTPException(status_code=409, detail="No available drivers for auto-assignment")

    assigned = service.assign_driver_to_ride(
        db,
        ride_id=ride.id,
        driver_id=suggested_driver.id,
        actor_user_id=_user.id,
    )
    if not assigned:
        raise HTTPException(status_code=404, detail="Ride not found")

    await get_emitter().emit_dispatch_changed(
        organization_id=ride.organization_id,
        event_name="auto_assignment_executed",
        actor_user_id=_user.id,
        details={
            "ride_id": ride.id,
            "driver_id": suggested_driver.id,
            "overload": overload,
        },
    )
    await get_emitter().emit_driver_active_ride_state(
        organization_id=ride.organization_id,
        driver_id=suggested_driver.id,
        active_ride_id=ride.id,
        state=RideLifecycleManager.normalize_state(getattr(assigned, "lifecycle_state", None) or assigned.status),
        actor_user_id=_user.id,
        details={"source": "auto_assign"},
    )
    ActivityLogService.log_activity(
        db,
        organization_id=ride.organization_id,
        action=ActivityAction.RIDE_ASSIGNED,
        description="Auto-assignment executed",
        ride_id=ride.id,
        driver_id=suggested_driver.id,
        actor_user_id=_user.id,
        details={"overload": overload},
    )
    return assigned


@router.patch("/dispatcher/rides/{ride_id}/cancel", response_model=RideResponse)
async def dispatcher_cancel_ride(
    ride_id: str,
    reason: str = Query(..., min_length=1, max_length=512),
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Cancel a ride with dispatcher audit logging."""
    logger.info("Dispatcher cancelling ride: ride=%s reason=%s", ride_id, reason)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    previous_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
    try:
        ride = service.cancel_ride(
            db,
            ride_id=ride_id,
            actor_user_id=_user.id,
            reason=reason,
        )
        
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        
        # Log dispatcher cancellation
        ActivityLogService.log_activity(
            db,
            organization_id=ride.organization_id,
            action=ActivityAction.RIDE_CANCELLED,
            description=f"Ride cancelled by dispatcher: {reason}",
            ride_id=ride_id,
            actor_user_id=_user.id,
        )
        
        # Security audit
        SecurityAuditService.log_action(
            db,
            organization_id=ride.organization_id,
            action_type="dispatcher_ride_cancellation",
            actor_user_id=user.user_id,
            ride_id=ride_id,
            details={"reason": reason, "driver_id": ride.driver_id},
        )
        
        # Emit real-time event
        emitter = get_emitter()
        await emitter.emit_ride_status_changed(
            organization_id=ride.organization_id,
            ride_id=ride_id,
            from_status=previous_state,
            to_status=RideStatus.CANCELLED.value,
            reason=reason,
            actor_user_id=_user.id,
        )
        if ride.driver_id:
            await emitter.emit_driver_active_ride_state(
                organization_id=ride.organization_id,
                driver_id=ride.driver_id,
                active_ride_id=None,
                state=RideStatus.CANCELLED.value,
                actor_user_id=_user.id,
                details={"source": "dispatcher_cancel"},
            )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride_id,
            event_name="assignment-cancelled",
            actor_user_id=_user.id,
            details={"ride_id": ride_id, "driver_id": ride.driver_id, "reason": reason},
            request_id=f"dispatcher_cancel_{ride_id}",
            driver_id=ride.driver_id,
            lifecycle_state=RideStatus.CANCELLED.value,
            transition_reason=reason,
            assignment_transition_source="dispatcher_cancel_ride",
        )
        
        metrics = get_operational_metrics_registry()
        metrics.increment("dispatcher.cancellations.total")
        
        return ride
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/dispatcher/rides/{ride_id}/mark-arrived", response_model=RideResponse)
async def dispatcher_mark_arrived(
    ride_id: str,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Mark ride as in-transit (driver arrived/picking up) with dispatcher audit."""
    logger.info("Dispatcher marking ride arrived: ride=%s", ride_id)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    previous_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
    try:
        ride = service.update_ride_status(
            db,
            ride_id=ride_id,
            status=RideStatus.ARRIVED.value,
            actor_user_id=_user.id,
        )
        
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        
        # Log dispatcher action
        ActivityLogService.log_activity(
            db,
            organization_id=ride.organization_id,
            action=ActivityAction.PICKUP_COMPLETED,
            description="Ride marked as in-transit by dispatcher",
            ride_id=ride_id,
            driver_id=ride.driver_id,
            actor_user_id=_user.id,
        )
        
        # Emit real-time event
        emitter = get_emitter()
        await emitter.emit_ride_status_changed(
            organization_id=ride.organization_id,
            ride_id=ride_id,
            from_status=previous_state,
            to_status=RideStatus.ARRIVED.value,
            actor_user_id=_user.id,
        )
        if ride.driver_id:
            await emitter.emit_driver_active_ride_state(
                organization_id=ride.organization_id,
                driver_id=ride.driver_id,
                active_ride_id=ride_id,
                state=RideStatus.ARRIVED.value,
                actor_user_id=_user.id,
                details={"source": "dispatcher_mark_arrived"},
            )
        
        metrics = get_operational_metrics_registry()
        metrics.record_event_ts("dispatcher_actions")
        
        return ride
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/dispatcher/rides/{ride_id}/mark-onboard", response_model=RideResponse)
async def dispatcher_mark_onboard(
    ride_id: str,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Mark ride as onboard (passenger picked up) with dispatcher audit."""
    logger.info("Dispatcher marking ride onboard: ride=%s", ride_id)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
    if lifecycle_state != RideStatus.ARRIVED.value:
        raise HTTPException(status_code=400, detail="Ride must be in arrived state to mark onboard")

    ride = service.update_ride_status(
        db,
        ride_id=ride_id,
        status=RideStatus.RIDER_ONBOARD.value,
        actor_user_id=_user.id,
    )
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    
    # Log dispatcher action (same status but mark event)
    ActivityLogService.log_activity(
        db,
        organization_id=ride.organization_id,
        action=ActivityAction.RIDE_COMPLETED,
        description="Ride marked as onboard by dispatcher",
        ride_id=ride_id,
        driver_id=ride.driver_id,
        actor_user_id=_user.id,
    )
    
    # Emit event
    emitter = get_emitter()
    await emitter.emit_pickup_completed(
        organization_id=ride.organization_id,
        ride_id=ride_id,
        driver_id=ride.driver_id or "",
        actor_user_id=_user.id,
    )
    
    return ride


@router.patch("/dispatcher/rides/{ride_id}/complete", response_model=RideResponse)
async def dispatcher_complete_ride(
    ride_id: str,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Complete a ride with dispatcher audit logging."""
    logger.info("Dispatcher completing ride: ride=%s", ride_id)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    try:
        ride = service.update_ride_status(
            db,
            ride_id=ride_id,
            status=RideStatus.COMPLETED.value,
            actor_user_id=_user.id,
        )
        
        if not ride:
            raise HTTPException(status_code=404, detail="Ride not found")
        
        # Log dispatcher completion
        ActivityLogService.log_activity(
            db,
            organization_id=ride.organization_id,
            action=ActivityAction.RIDE_COMPLETED,
            description="Ride completed by dispatcher",
            ride_id=ride_id,
            driver_id=ride.driver_id,
            actor_user_id=_user.id,
        )
        
        # Emit real-time event
        emitter = get_emitter()
        await emitter.emit_ride_completed(
            organization_id=ride.organization_id,
            ride_id=ride_id,
            driver_id=ride.driver_id or "",
            actor_user_id=_user.id,
        )
        if ride.driver_id:
            await emitter.emit_driver_active_ride_state(
                organization_id=ride.organization_id,
                driver_id=ride.driver_id,
                active_ride_id=None,
                state=RideStatus.COMPLETED.value,
                actor_user_id=_user.id,
                details={"source": "dispatcher_complete"},
            )
        await _emit_dispatch_lifecycle_event(
            db=db,
            organization_id=ride.organization_id,
            ride_id=ride_id,
            event_name="assignment-completed",
            actor_user_id=_user.id,
            details={"ride_id": ride_id, "driver_id": ride.driver_id, "source": "dispatcher_complete"},
            request_id=f"dispatcher_complete_{ride_id}",
            driver_id=ride.driver_id,
            lifecycle_state=RideStatus.COMPLETED.value,
            transition_reason="dispatcher_completed",
            assignment_transition_source="dispatcher_mark_completed",
        )
        
        metrics = get_operational_metrics_registry()
        metrics.increment("dispatcher.completions.total")
        
        return ride
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/dispatcher/rides/{ride_id}/escalate", response_model=RideResponse)
async def dispatcher_escalate_issue(
    ride_id: str,
    issue_type: str = Query(..., min_length=1, max_length=64),
    description: str = Query(..., min_length=1, max_length=1024),
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Escalate an operational issue for a ride."""
    logger.info("Dispatcher escalating ride issue: ride=%s issue_type=%s", ride_id, issue_type)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    # Log escalation
    ActivityLogService.log_activity(
        db,
        organization_id=ride.organization_id,
        action=ActivityAction.RIDE_ESCALATED,
        description=f"Operational escalation - {issue_type}: {description}",
        ride_id=ride_id,
        actor_user_id=_user.id,
    )
    
    # Security audit for escalation
    SecurityAuditService.log_action(
        db,
        organization_id=ride.organization_id,
        action_type="dispatcher_ride_escalation",
        actor_user_id=user.user_id,
        ride_id=ride_id,
        details={"issue_type": issue_type, "description": description, "driver_id": ride.driver_id},
    )
    
    # Emit escalation event
    emitter = get_emitter()
    await emitter.emit_ride_escalated(
        organization_id=ride.organization_id,
        ride_id=ride_id,
        issue_type=issue_type,
        description=description,
        actor_user_id=_user.id,
    )
    
    # Alert operational team
    OperationalAlertService.log_alert(
        db,
        organization_id=ride.organization_id,
        alert_type="ride_escalation",
        severity="high",
        message=f"Ride {ride_id} escalated: {issue_type}",
        payload={"ride_id": ride_id, "issue": issue_type, "description": description},
    )
    
    metrics = get_operational_metrics_registry()
    metrics.increment("dispatcher.escalations.total")
    
    return ride


@router.post("/dispatcher/rides/{ride_id}/retry", response_model=RideResponse)
async def dispatcher_retry_workflow(
    ride_id: str,
    _user = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retry a failed workflow for a ride."""
    logger.info("Dispatcher retrying ride workflow: ride=%s", ride_id)
    
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    
    # Log retry action
    ActivityLogService.log_activity(
        db,
        organization_id=ride.organization_id,
        action=ActivityAction.RIDE_WORKFLOW_RETRIED,
        description="Ride workflow retry initiated by dispatcher",
        ride_id=ride_id,
        actor_user_id=_user.id,
    )
    
    # Add to retry queue
    RetryQueueService.enqueue_retry(
        db,
        ride_id=ride_id,
        organization_id=ride.organization_id,
        operation_type="ride_workflow",
        max_retries=3,
    )
    
    # Emit retry event
    emitter = get_emitter()
    await emitter.emit_ride_retry(
        organization_id=ride.organization_id,
        ride_id=ride_id,
        actor_user_id=_user.id,
    )
    
    metrics = get_operational_metrics_registry()
    metrics.increment("dispatcher.retries.total")
    
    return ride


# ── Dispatcher Board & Queue Endpoints ────────────────────────────────────────

@router.get("/dispatcher/board", response_model=OperationalDashboardResponse)
def get_dispatcher_board(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get real-time dispatcher command center board state with queues, metrics, and driver availability."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    
    # Require dispatcher or admin role
    if user.role not in {ROLE_DISPATCHER, ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise HTTPException(status_code=403, detail="Dispatcher access required")
    
    logger.info("Fetching dispatcher board: org=%s", effective_org_id)
    
    # Build comprehensive dispatcher dashboard
    board_state = build_operational_dashboard(
        db,
        organization_id=effective_org_id,
        include_queue_details=True,
        include_driver_availability=True,
    )
    
    return OperationalDashboardResponse(**board_state)


@router.get("/dispatcher/queues", response_model=dict)
def get_dispatcher_queues(
    organization_id: str | None = Query(None),
    filter_status: str | None = Query(None),
    filter_provider: str | None = Query(None),
    filter_priority: str | None = Query(None),
    search_query: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get organized dispatcher ride queues with filtering and search."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    
    if user.role not in {ROLE_DISPATCHER, ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise HTTPException(status_code=403, detail="Dispatcher access required")
    
    logger.info("Fetching dispatcher queues: org=%s status=%s provider=%s priority=%s search=%s",
                effective_org_id, filter_status, filter_provider, filter_priority, search_query)
    
    # Query rides with filters
    from app.modules.health_isf.models import HealthISFRide as Ride
    query = db.query(Ride).filter(Ride.organization_id == effective_org_id)
    
    # Apply filters
    if filter_status:
        query = query.filter(Ride.status == filter_status)
    if filter_provider:
        query = query.filter(Ride.provider_id == filter_provider)
    if filter_priority:
        query = query.filter(Ride.priority_tag == filter_priority)
    if search_query:
        query = query.filter(
            (Ride.passenger_name.ilike(f"%{search_query}%")) |
            (Ride.id.ilike(f"%{search_query}%"))
        )
    
    rides = query.order_by(
        Ride.priority_score.desc().nullslast(),
        Ride.requested_at.asc()
    ).all()
    
    # Organize into queues
    queues = {
        "active": [],
        "pending": [],
        "delayed": [],
        "completed": [],
    }
    
    for ride in rides:
        ride_dict = {
            "id": ride.id,
            "passenger_name": ride.passenger_name,
            "pickup_address": ride.pickup_address,
            "dropoff_address": ride.dropoff_address,
            "status": ride.status,
            "lifecycle_state": getattr(ride, "lifecycle_state", None),
            "priority_tag": ride.priority_tag,
            "priority_score": ride.priority_score,
            "is_emergency": ride.is_emergency,
            "driver_id": ride.driver_id,
            "driver_name": ride.driver.name if ride.driver else None,
            "provider_id": ride.provider_id,
            "provider_name": ride.provider.name if ride.provider else None,
            "scheduled_time": ride.appointment_time.isoformat() if ride.appointment_time else None,
            "estimated_duration_minutes": ride.estimated_duration_minutes,
            "requested_at": ride.requested_at.isoformat(),
        }
        
        lifecycle_state = RideLifecycleManager.normalize_state(getattr(ride, "lifecycle_state", None) or ride.status)
        if lifecycle_state == RideStatus.COMPLETED.value:
            queues["completed"].append(ride_dict)
        elif lifecycle_state in {
            RideStatus.ASSIGNED.value,
            RideStatus.DRIVER_EN_ROUTE.value,
            RideStatus.ARRIVED.value,
            RideStatus.RIDER_ONBOARD.value,
            RideStatus.IN_PROGRESS.value,
        }:
            queues["active"].append(ride_dict)
        elif lifecycle_state in {RideStatus.CANCELLED.value, RideStatus.FAILED.value, RideStatus.ESCALATED.value}:
            queues["delayed"].append(ride_dict)
        else:
            queues["pending"].append(ride_dict)
    
    return {
        "organization_id": effective_org_id,
        "queues": queues,
        "priority_queue": DispatchOrchestrationEngine.prioritized_queue(
            db,
            organization_id=effective_org_id,
            limit=150,
        ),
        "overload": DispatchOrchestrationEngine.evaluate_overload(
            db,
            organization_id=effective_org_id,
        ),
        "timestamp": now().isoformat(),
    }


@router.get("/dispatcher/audit-log", response_model=ActivityFeedResponse)
def get_dispatcher_audit_log(
    organization_id: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    ride_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get dispatcher action audit log with filtering by ride."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    
    if user.role not in {ROLE_DISPATCHER, ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise HTTPException(status_code=403, detail="Dispatcher access required")
    
    logger.info("Fetching dispatcher audit log: org=%s ride_id=%s skip=%d limit=%d",
                effective_org_id, ride_id, skip, limit)
    
    # Get activity feed (filtered by ride if provided)
    activities, total = ActivityLogService.get_activity_feed(
        db,
        organization_id=effective_org_id,
        limit=limit,
        skip=skip,
        ride_id=ride_id,
    )

    serialized: list[DispatcherActivityResponse] = []
    for activity in activities:
        raw_details = getattr(activity, "details", None)
        details = raw_details
        if isinstance(raw_details, str):
            try:
                details = json.loads(raw_details)
            except json.JSONDecodeError:
                details = {"raw": raw_details}
        serialized.append(
            DispatcherActivityResponse.model_validate(
                {
                    "id": str(activity.id),
                    "organization_id": str(activity.organization_id),
                    "action": str(activity.action),
                    "ride_id": activity.ride_id,
                    "driver_id": activity.driver_id,
                    "description": str(activity.description or ""),
                    "details": details,
                    "actor_user_id": activity.actor_user_id,
                    "created_at": activity.created_at,
                }
            )
        )

    return ActivityFeedResponse(
        activities=serialized,
        total=total,
        skip=skip,
        limit=limit,
    )


# ── Dispatch History Endpoint ────────────────────────────────────────────────

@router.get("/rides/{ride_id}/dispatch-history", response_model=list[DispatchLogResponse])
def get_ride_dispatch_history(
    ride_id: str,
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve dispatch action log for a ride."""
    logger.info("Fetching dispatch history for ride: %s", ride_id)
    ride = service.get_ride_by_id(db, ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    enforce_entity_tenant(user, ride.organization_id)
    return service.get_ride_dispatch_history(db, ride_id)


@router.get("/driver-applications", response_model=list[DriverApplicationResponse])
def list_driver_applications(
    organization_id: str | None = Query(None),
    onboarding_status: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=300),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    apps = service.list_driver_applications(
        db,
        organization_id=effective_org_id,
        onboarding_status=onboarding_status,
        skip=skip,
        limit=limit,
    )
    return [_serialize_driver_application(item) for item in apps]


@router.post("/driver-applications", response_model=DriverApplicationResponse, status_code=201)
def create_driver_application(
    payload: DriverApplicationCreateRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    app = service.create_driver_application(
        db,
        organization_id=effective_org_id,
        applicant_name=payload.applicant_name,
        applicant_phone=payload.applicant_phone,
        applicant_email=payload.applicant_email,
        license_number=payload.license_number,
        insurance_policy_number=payload.insurance_policy_number,
        vehicle_make=payload.vehicle_make,
        vehicle_model=payload.vehicle_model,
        vehicle_year=payload.vehicle_year,
        vehicle_plate=payload.vehicle_plate,
        vehicle_color=payload.vehicle_color,
        availability_summary=payload.availability_summary,
        availability=payload.availability,
        preferred_service_categories=payload.preferred_service_categories,
        background_check_authorized=payload.background_check_authorized,
        license_document_ref=payload.license_document_ref,
        insurance_document_ref=payload.insurance_document_ref,
        registration_document_ref=payload.registration_document_ref,
        notes=payload.notes,
    )
    return _serialize_driver_application(app)


@router.patch("/driver-applications/{application_id}/status", response_model=DriverApplicationResponse)
def review_driver_application(
    application_id: str,
    payload: DriverApplicationStatusUpdateRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    updated = service.update_driver_application_status(
        db,
        organization_id=effective_org_id,
        application_id=application_id,
        onboarding_status=payload.onboarding_status,
        review_notes=payload.review_notes,
        reviewed_by_user_id=user.user_id,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Driver application not found")
    return _serialize_driver_application(updated)


@router.get("/recurring/templates", response_model=list[RecurringRideTemplateResponse])
def get_recurring_ride_templates(
    organization_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.get_recurring_ride_templates(db, organization_id=effective_org_id, limit=limit)


@router.post("/recurring/schedules", response_model=RecurringScheduleResponse, status_code=201)
def create_recurring_schedule(
    payload: RecurringScheduleCreateRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    provider = service.get_provider_by_id(db, payload.provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    enforce_entity_tenant(user, provider.organization_id)

    try:
        schedule = service.create_recurring_ride_schedule(
            db,
            organization_id=effective_org_id,
            provider_id=payload.provider_id,
            passenger_name=payload.passenger_name,
            passenger_phone=payload.passenger_phone,
            pickup_address=payload.pickup_address,
            dropoff_address=payload.dropoff_address,
            service_type=payload.service_type,
            pickup_time_local=payload.pickup_time_local,
            frequency=payload.frequency,
            interval_count=payload.interval_count,
            weekdays=payload.weekdays,
            start_date=payload.start_date,
            end_date=payload.end_date,
            actor_user_id=user.user_id,
        )
        generated = service.generate_recurring_rides_for_schedule(
            db,
            schedule=schedule,
            horizon_days=payload.horizon_days,
            actor_user_id=user.user_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _serialize_recurring_schedule(schedule, generated_ride_count=len(generated))


@router.get("/recurring/schedules", response_model=list[RecurringScheduleResponse])
def list_recurring_schedules(
    organization_id: str | None = Query(None),
    active_only: bool = Query(False),
    limit: int = Query(200, ge=1, le=500),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    schedules = service.list_recurring_ride_schedules(
        db,
        organization_id=effective_org_id,
        active_only=active_only,
        limit=limit,
    )
    rows: list[RecurringScheduleResponse] = []
    for schedule in schedules:
        generated_rides = service.list_generated_rides_for_schedule(
            db,
            organization_id=effective_org_id,
            schedule_id=schedule.id,
            limit=1_000,
        )
        rows.append(_serialize_recurring_schedule(schedule, generated_ride_count=len(generated_rides)))
    return rows


@router.get("/recurring/schedules/{schedule_id}/rides", response_model=list[RideResponse])
def list_generated_schedule_rides(
    schedule_id: str,
    organization_id: str | None = Query(None),
    limit: int = Query(500, ge=1, le=1000),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    schedule = service.get_recurring_ride_schedule_by_id(db, schedule_id=schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Recurring schedule not found")
    enforce_entity_tenant(user, schedule.organization_id)
    rides = service.list_generated_rides_for_schedule(
        db,
        organization_id=effective_org_id,
        schedule_id=schedule_id,
        limit=limit,
    )
    return rides


@router.patch("/recurring/schedules/{schedule_id}/status", response_model=RecurringScheduleResponse)
def update_recurring_schedule_status(
    schedule_id: str,
    payload: RecurringScheduleStatusUpdateRequest,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    schedule = service.get_recurring_ride_schedule_by_id(db, schedule_id=schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="Recurring schedule not found")
    enforce_entity_tenant(user, schedule.organization_id)

    updated = service.set_recurring_ride_schedule_active(
        db,
        schedule_id=schedule_id,
        is_active=payload.is_active,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Recurring schedule not found")

    generated_count = len(
        service.list_generated_rides_for_schedule(
            db,
            organization_id=effective_org_id,
            schedule_id=schedule_id,
            limit=1_000,
        )
    )
    if updated.is_active:
        newly_created = service.generate_recurring_rides_for_schedule(
            db,
            schedule=updated,
            horizon_days=payload.horizon_days,
            actor_user_id=user.user_id,
        )
        generated_count += len(newly_created)

    return _serialize_recurring_schedule(updated, generated_ride_count=generated_count)


@router.patch("/recurring/schedules/{schedule_id}/pause", response_model=RecurringScheduleResponse)
def pause_recurring_schedule(
    schedule_id: str,
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return update_recurring_schedule_status(
        schedule_id=schedule_id,
        payload=RecurringScheduleStatusUpdateRequest(is_active=False),
        organization_id=organization_id,
        _=_,
        user=user,
        db=db,
    )


@router.patch("/recurring/schedules/{schedule_id}/resume", response_model=RecurringScheduleResponse)
def resume_recurring_schedule(
    schedule_id: str,
    organization_id: str | None = Query(None),
    horizon_days: int = Query(30, ge=1, le=180),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    return update_recurring_schedule_status(
        schedule_id=schedule_id,
        payload=RecurringScheduleStatusUpdateRequest(is_active=True, horizon_days=horizon_days),
        organization_id=organization_id,
        _=_,
        user=user,
        db=db,
    )


@router.get("/grant-proof/snapshot", response_model=GrantProofSnapshotResponse)
def get_grant_proof_snapshot(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    rides = [ride for ride in service.get_all_rides(db, skip=0, limit=500) if ride.organization_id == effective_org_id]
    applications = service.list_driver_applications(db, organization_id=effective_org_id, limit=500)
    recurring = service.get_recurring_ride_templates(db, organization_id=effective_org_id, limit=250)
    dashboard = _build_enterprise_dashboard_payload(db, effective_org_id)

    active_rides = sum(1 for ride in rides if str(ride.status).lower() in {"accepted", "in_transit"})
    delayed = dashboard.get("dispatch_overview", {}).get("delayed_rides", 0)
    approved_apps = sum(1 for app in applications if str(app.onboarding_status).lower() in {"approved", "active"})
    pending_apps = sum(1 for app in applications if str(app.onboarding_status).lower() in {"applied", "pending_review"})

    return GrantProofSnapshotResponse(
        generated_at=now().isoformat(),
        transportation_mvp_status="ready" if rides else "needs_data",
        onboarding_mvp_status="ready" if applications else "needs_data",
        recurring_mvp_status="ready" if recurring else "needs_data",
        dashboard_mvp_status="ready" if dashboard else "needs_data",
        screenshot_inventory=[
            {"id": "dispatch_live_queue", "label": "Dispatch Live Queue", "status": "ready"},
            {"id": "driver_onboarding_review", "label": "Driver Onboarding Review", "status": "ready" if applications else "needs_data"},
            {"id": "recurring_transportation", "label": "Recurring Transportation Templates", "status": "ready" if recurring else "needs_data"},
            {"id": "grant_metrics_overview", "label": "Grant Metrics Overview", "status": "ready"},
        ],
        metrics={
            "total_rides": len(rides),
            "active_rides": active_rides,
            "delayed_rides": delayed,
            "driver_applications_total": len(applications),
            "driver_applications_pending": pending_apps,
            "driver_applications_approved": approved_apps,
            "recurring_templates": len(recurring),
            "target_date": "2025-06-15",
            "target_program": "Rural transportation grant readiness",
        },
        sample_entities={
            "rides_preview": [
                {
                    "id": ride.id,
                    "passenger_name": ride.passenger_name,
                    "service_type": ride.service_type,
                    "status": str(ride.status),
                }
                for ride in rides[:5]
            ],
            "driver_applications_preview": [
                {
                    "id": app.id,
                    "applicant_name": app.applicant_name,
                    "status": str(app.onboarding_status),
                }
                for app in applications[:5]
            ],
            "recurring_preview": recurring[:5],
        },
    )


@router.post("/ops/seed-phase43")
def seed_phase43_data(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.seed_phase43_mvp(db, organization_id=effective_org_id)


@router.post("/ops/seed-production-demo")
def seed_production_demo_data(
    organization_id: str | None = Query(None),
    force: bool = Query(False),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Seed 50+ drivers, 100+ patients, and 200+ trips for pilot/demo operations."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.seed_production_demo_data(db, organization_id=effective_org_id, force=force)


@router.post("/ops/reset-pilot-environment")
def reset_pilot_environment(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Clear ride/trip history and restore canonical driver availability for pilot operations."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    try:
        return service.reset_pilot_environment(db, organization_id=effective_org_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/ops/purge-test-artifacts")
def purge_test_operational_artifacts(
    organization_id: str | None = Query(None),
    _: None = Depends(require_health_isf_write_access),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Safe cleanup: remove test/proof rides and billing artifacts only.

    Keeps seeded drivers, providers, vehicles, and users.
    """
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.purge_test_operational_artifacts(db, organization_id=effective_org_id)


@router.get("/ops/platform-reset-status")
def get_platform_reset_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Expose live platform emptiness and reset epoch for browser cache invalidation."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    return service.get_platform_reset_status(db, organization_id=effective_org_id)


# ── Dashboard Endpoint ────────────────────────────────────────────────────────

@router.get("/dashboard", response_model=DashboardMetrics)
def get_dashboard(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Retrieve dashboard metrics and KPIs."""
    logger.info("Fetching dashboard metrics")
    effective_org_id = enforce_tenant_scope(user, organization_id)
    metrics = service.get_dashboard_metrics(db, organization_id=effective_org_id)
    return metrics


@router.get("/enterprise/dashboard")
def get_enterprise_dashboard(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
):
    """Get the live enterprise dashboard payload for the operational UI."""
    effective_org_id = enforce_tenant_scope(user, organization_id)
    if user.role not in {ROLE_DISPATCHER, ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, ROLE_ANALYTICS_READONLY, ROLE_STAFF}:
        raise HTTPException(status_code=403, detail="Enterprise dashboard access required")

    logger.info("Fetching enterprise dashboard: org=%s", effective_org_id)
    return _build_enterprise_dashboard_payload(db, effective_org_id)


# ── Health ISF Module Initialization (internal use) ───────────────────────────

def init_module(db: Session):
    """Initialize Health ISF module with sample data."""
    logger.info("Initializing Health ISF module…")
    summary = service.init_sample_data(db)
    logger.info("Health ISF module initialized: %s", summary)
    return summary
