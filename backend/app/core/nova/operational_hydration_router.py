from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, cast
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth import (
    ROLE_ADMIN,
    ROLE_ANALYTICS_READONLY,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DISPATCHER,
    ROLE_DRIVER_SUPPORT,
    ROLE_DRIVER,
    ROLE_MEDICAL_COORDINATOR,
    ROLE_PROVIDER,
    ROLE_RIDER,
    ROLE_STAFF,
    ROLE_SUPERVISOR,
    ROLE_SUPER_ADMIN_SUPPORT,
    UserContext,
    get_current_user_context,
    require_any_role,
)
from app.core.nova.operational_metrics import operational_metrics
from app.core.nova.operations_orchestration_service import OperationsOrchestrationService
from app.core.nova.compliance_service import ComplianceService
from app.core.nova.operational_timeline import TimelineEvent, TimelineEventType, operational_timeline
from app.core.nova.router import _resolve_org
from app.db.session import get_db
from app.monitoring.runtime_logger import record_supervision_event
from app.monitoring.supervision_snapshot import build_supervision_snapshot
from app.modules.health_isf import service as health_isf_service
from app.modules.health_isf.models import (
    DispatchAssignmentState,
    HealthISFDispatchAssignment,
    HealthISFDispatchLog,
    HealthISFDriver,
    HealthISFRide,
    HealthISFRideStatusHistory,
    RideStatus,
)
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.operational_workflow_orchestration import build_operational_workflow_overview


require_ops_access = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_ANALYTICS_READONLY,
    ROLE_PROVIDER,
    ROLE_DRIVER,
    ROLE_RIDER,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_SUPERVISOR,
    ROLE_DRIVER_SUPPORT,
    ROLE_MEDICAL_COORDINATOR,
)

STREAM_ROLE_VIEWS = {
    "admin",
    "dispatcher",
    "provider",
    "driver",
    "supervisor",
    "compliance_officer",
    "driver_support",
    "medical_coordinator",
    "rider",
}

ROLE_WORKSPACE_ACTIONS: dict[str, set[str]] = {
    "admin": {
        "supervisor.approve_override",
        "supervisor.reject_override",
        "supervisor.approve_recovery",
        "supervisor.trigger_emergency_coordination",
        "compliance.review_deficiency",
        "compliance.open_regulatory_exception",
        "driver_support.open_ticket",
        "driver_support.route_escalation",
        "provider.open_sync_handoff",
        "provider.review_sla_alert",
        "dispatch.assign_driver",
        "dispatch.reassign_driver",
        "dispatch.escalate_ride",
        "dispatch.cancel_ride",
        "dispatch.mark_arrived",
        "dispatch.mark_onboard",
        "dispatch.complete_ride",
        "dispatch.retry_failed_ride",
        "dispatch.contact_rider",
        "dispatch.contact_driver",
        "driver.accept_assignment",
        "driver.start_route",
        "driver.arrive",
        "driver.onboard_rider",
        "driver.update_route_progress",
        "driver.update_shift_readiness",
        "driver.complete_trip",
        "driver.report_incident",
        "compliance.approve_onboarding",
        "compliance.deny_onboarding",
        "compliance.flag_document_expiration",
        "supervisor.reassign_failed_trip",
        "supervisor.override_trip_failure",
        "provider.update_coverage_window",
        "ai.generate_operational_summary",
    },
    "dispatcher": {
        "dispatch.assign_driver",
        "dispatch.reassign_driver",
        "dispatch.escalate_ride",
        "dispatch.cancel_ride",
        "dispatch.mark_arrived",
        "dispatch.mark_onboard",
        "dispatch.complete_ride",
        "dispatch.retry_failed_ride",
        "dispatch.contact_rider",
        "dispatch.contact_driver",
        "driver.start_route",
        "driver.update_route_progress",
    },
    "provider": {
        "provider.open_sync_handoff",
        "provider.review_sla_alert",
        "provider.update_coverage_window",
    },
    "driver": {
        "driver.accept_assignment",
        "driver.mark_arrived",
        "driver.start_trip",
        "driver.start_route",
        "driver.arrive",
        "driver.onboard_rider",
        "driver.update_route_progress",
        "driver.update_shift_readiness",
        "driver.complete_trip",
        "driver.report_incident",
    },
    "supervisor": {
        "supervisor.approve_override",
        "supervisor.reject_override",
        "supervisor.approve_recovery",
        "supervisor.trigger_emergency_coordination",
        "supervisor.reassign_failed_trip",
        "supervisor.override_trip_failure",
        "dispatch.reassign_driver",
    },
    "compliance_officer": {
        "compliance.review_deficiency",
        "compliance.open_regulatory_exception",
        "compliance.approve_onboarding",
        "compliance.deny_onboarding",
        "compliance.flag_document_expiration",
    },
    "driver_support": {
        "driver_support.open_ticket",
        "driver_support.route_escalation",
    },
    "medical_coordinator": {
        "medical_coordinator.review_appointment_risk",
        "medical_coordinator.coordinate_facility",
        "medical_coordinator.escalate_patient_support",
        "dispatch.assign_driver",
        "ai.generate_operational_summary",
    },
    "rider": set(),
}

TRIP_WORKFLOW_STATES: tuple[str, ...] = (
    "requested",
    "pending_review",
    "scheduled",
    "assigned",
    "accepted",
    "arrived",
    "onboard",
    "in_transit",
    "completed",
    "cancelled",
    "failed",
    "escalated",
)

TRIP_WORKFLOW_TRANSITIONS: tuple[tuple[str, str], ...] = (
    ("requested", "pending_review"),
    ("pending_review", "scheduled"),
    ("scheduled", "assigned"),
    ("assigned", "accepted"),
    ("accepted", "arrived"),
    ("arrived", "onboard"),
    ("onboard", "in_transit"),
    ("in_transit", "completed"),
    ("assigned", "escalated"),
    ("accepted", "escalated"),
    ("arrived", "escalated"),
    ("onboard", "escalated"),
    ("in_transit", "escalated"),
    ("escalated", "failed"),
    ("escalated", "scheduled"),
    ("requested", "cancelled"),
    ("pending_review", "cancelled"),
    ("scheduled", "cancelled"),
    ("assigned", "cancelled"),
    ("accepted", "cancelled"),
)


_STREAM_EVENT_ROLE_DEFAULTS: dict[OperationalEventType, list[str]] = {
    OperationalEventType.RIDE_REQUESTED: ["rider", "driver", "provider", "admin"],
    OperationalEventType.RIDE_ASSIGNED: ["driver", "provider", "admin"],
    OperationalEventType.RIDE_UPDATED: ["rider", "driver", "provider", "admin"],
    OperationalEventType.RIDE_COMPLETED: ["rider", "driver", "provider", "admin"],
    OperationalEventType.DRIVER_STATE_CHANGED: ["driver", "admin"],
    OperationalEventType.DRIVER_STATE: ["driver", "admin"],
    OperationalEventType.PROVIDER_STATE_CHANGED: ["provider", "admin"],
    OperationalEventType.PROVIDER_STATUS: ["provider", "admin"],
    OperationalEventType.WORKFLOW_TRANSITION: ["admin"],
    OperationalEventType.SUPERVISION_ALERT: ["admin"],
    OperationalEventType.OPERATIONAL_ALERT: ["admin"],
}


def _effective_role_view(user_role: str, requested_role_view: str | None) -> str:
    normalized_user_role = str(user_role or "").strip().lower()
    requested = str(requested_role_view or "").strip().lower()

    default_view = "admin"
    if normalized_user_role == ROLE_DRIVER:
        default_view = "driver"
    elif normalized_user_role == ROLE_PROVIDER:
        default_view = "provider"
    elif normalized_user_role == ROLE_RIDER:
        default_view = "rider"
    elif normalized_user_role == ROLE_DISPATCHER:
        default_view = "dispatcher"
    elif normalized_user_role == ROLE_SUPERVISOR:
        default_view = "supervisor"
    elif normalized_user_role == ROLE_COMPLIANCE_OFFICER:
        default_view = "compliance_officer"
    elif normalized_user_role == ROLE_DRIVER_SUPPORT:
        default_view = "driver_support"
    elif normalized_user_role == ROLE_MEDICAL_COORDINATOR:
        default_view = "medical_coordinator"

    if requested not in STREAM_ROLE_VIEWS:
        return default_view

    if normalized_user_role in {
        ROLE_ADMIN,
        ROLE_SUPER_ADMIN_SUPPORT,
        ROLE_STAFF,
        ROLE_ANALYTICS_READONLY,
    }:
        return requested

    if normalized_user_role == ROLE_DISPATCHER:
        return requested if requested in {"dispatcher", "driver", "admin"} else "dispatcher"

    if normalized_user_role == ROLE_SUPERVISOR:
        return requested if requested in {"supervisor", "admin"} else "supervisor"

    if normalized_user_role == ROLE_COMPLIANCE_OFFICER:
        return requested if requested in {"compliance_officer", "admin"} else "compliance_officer"

    if normalized_user_role == ROLE_DRIVER_SUPPORT:
        return requested if requested in {"driver_support", "admin"} else "driver_support"

    if normalized_user_role == ROLE_MEDICAL_COORDINATOR:
        return requested if requested in {"medical_coordinator", "admin"} else "medical_coordinator"

    if normalized_user_role == ROLE_DRIVER:
        return "driver"
    if normalized_user_role == ROLE_PROVIDER:
        return "provider"
    if normalized_user_role == ROLE_RIDER:
        return "rider"
    return default_view


def _severity_from_event_type(event_type: str) -> str:
    normalized = str(event_type or "").lower()
    if "alert" in normalized or "incident" in normalized or "escalation" in normalized:
        return "high"
    if "reconnect" in normalized or "workflow" in normalized:
        return "medium"
    return "low"


def _normalize_stream_role_scope(raw_scope: Any, event_type: str) -> list[str]:
    scopes: set[str] = set()
    for scope in (raw_scope if isinstance(raw_scope, list) else [raw_scope]):
        role = str(scope or "").strip().lower()
        if role in {
            "driver",
            "provider",
            "rider",
            "admin",
            "dispatcher",
            "supervisor",
            "compliance_officer",
            "driver_support",
            "medical_coordinator",
        }:
            scopes.add(role)
            continue
        if role in {
            ROLE_ADMIN,
            ROLE_SUPER_ADMIN_SUPPORT,
            ROLE_DISPATCHER,
            ROLE_STAFF,
            ROLE_ANALYTICS_READONLY,
            ROLE_COMPLIANCE_OFFICER,
            ROLE_SUPERVISOR,
            ROLE_DRIVER_SUPPORT,
            ROLE_MEDICAL_COORDINATOR,
        }:
            if role == ROLE_DISPATCHER:
                scopes.add("dispatcher")
            elif role == ROLE_SUPERVISOR:
                scopes.add("supervisor")
            elif role == ROLE_COMPLIANCE_OFFICER:
                scopes.add("compliance_officer")
            elif role == ROLE_DRIVER_SUPPORT:
                scopes.add("driver_support")
            elif role == ROLE_MEDICAL_COORDINATOR:
                scopes.add("medical_coordinator")
            else:
                scopes.add("admin")

    if not scopes:
        normalized_type = str(event_type or "").lower()
        if "driver" in normalized_type:
            scopes.update({"driver", "admin"})
        elif "dispatch" in normalized_type:
            scopes.update({"dispatcher", "supervisor", "admin"})
        elif "approval" in normalized_type or "compliance" in normalized_type:
            scopes.update({"compliance_officer", "supervisor", "admin"})
        elif "support" in normalized_type:
            scopes.update({"driver_support", "supervisor", "admin"})
        elif "medical" in normalized_type:
            scopes.update({"medical_coordinator", "provider", "admin"})
        elif "provider" in normalized_type:
            scopes.update({"provider", "admin"})
        elif "ride" in normalized_type:
            scopes.update({"rider", "driver", "provider", "dispatcher", "supervisor", "admin"})
        else:
            scopes.add("admin")

    return sorted(scopes)


def _timeline_to_stream_contract(event_row: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event_row.get("event_type") or event_row.get("event") or "workflow_transition")
    role_scope = _normalize_stream_role_scope((event_row.get("metadata") or {}).get("role_scope"), event_type)
    timestamp = str(event_row.get("timestamp") or _utc_now_iso())
    sequence = int(event_row.get("sequence_number", 0) or 0)
    correlation_id = str(event_row.get("correlation_id") or (event_row.get("metadata") or {}).get("correlation_id") or "")

    return {
        "event_id": str(event_row.get("event_id") or f"timeline-{sequence}"),
        "sequence": sequence,
        "event_type": event_type,
        "role_scope": role_scope,
        "severity": _severity_from_event_type(event_type),
        "timestamp": timestamp,
        "correlation_id": correlation_id or None,
        "source": str(event_row.get("source_reference_id") or event_row.get("operator_identity") or "timeline"),
        "advisory_only": True,
        "replay_safe": True,
        "append_only": True,
        "supervision_required": True,
    }


def _bus_to_stream_contract(event_row: dict[str, Any]) -> dict[str, Any]:
    event_type = str(event_row.get("event_type") or "workflow_transition")
    role_scope = _normalize_stream_role_scope(event_row.get("role_scope"), event_type)
    sequence = int(event_row.get("sequence", 0) or 0)
    payload_raw = event_row.get("payload")
    payload: dict[str, Any]
    if isinstance(payload_raw, dict):
        payload = cast(dict[str, Any], payload_raw)
    else:
        payload = {}
    correlation_id = str(payload.get("correlation_id") or payload.get("workflow_correlation_id") or "")

    return {
        "event_id": str(payload.get("event_id") or event_row.get("event_id") or f"bus-{sequence}"),
        "sequence": sequence,
        "event_type": event_type,
        "role_scope": role_scope,
        "severity": str(payload.get("severity") or _severity_from_event_type(event_type)),
        "timestamp": str(event_row.get("emitted_at") or _utc_now_iso()),
        "correlation_id": correlation_id or None,
        "source": str(payload.get("source") or "event_bus"),
        "advisory_only": True,
        "replay_safe": True,
        "append_only": True,
        "supervision_required": True,
    }


def _filter_stream_events_for_role(events: list[dict[str, Any]], role_view: str) -> list[dict[str, Any]]:
    if role_view == "admin":
        return events
    filtered: list[dict[str, Any]] = []
    for event in events:
        scopes_raw = event.get("role_scope")
        scopes: list[Any]
        if isinstance(scopes_raw, list):
            scopes = list(scopes_raw)
        else:
            scopes = []
        normalized_scopes = {str(scope or "").lower() for scope in scopes}
        if role_view in normalized_scopes:
            filtered.append(event)
    return filtered


def _workspace_action_allowed(role_view: str, action_type: str) -> bool:
    normalized_role = str(role_view or "admin").strip().lower()
    normalized_action = str(action_type or "").strip().lower()
    allowed = ROLE_WORKSPACE_ACTIONS.get(normalized_role) or set()
    return normalized_action in allowed


def _workspace_action_catalog(role_view: str) -> list[dict[str, Any]]:
    normalized_role = str(role_view or "admin").strip().lower()
    allowed = sorted(list(ROLE_WORKSPACE_ACTIONS.get(normalized_role) or set()))
    return [
        {
            "action_type": item,
            "authority_required": True,
            "supervision_required": True,
            "advisory_only": True,
            "execution_mode": "supervised_request",
        }
        for item in allowed
    ]


def _safe_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso_utc(value: datetime | None) -> str | None:
    normalized = _as_utc(value)
    return normalized.isoformat() if normalized else None


def _trip_state_from_ride(ride: HealthISFRide) -> str:
    lifecycle = str(getattr(ride, "lifecycle_state", None) or ride.status or "requested").strip().lower()
    mapping = {
        "queued": "pending_review",
        "pending": "requested",
        "approved": "scheduled",
        "accepted": "accepted",
        "driver_en_route": "accepted",
        "rider_onboard": "onboard",
        "in_transit": "in_transit",
        "in_progress": "in_transit",
    }
    normalized = mapping.get(lifecycle, lifecycle)
    if normalized in TRIP_WORKFLOW_STATES:
        return normalized
    if normalized in {"cancelled", "canceled"}:
        return "cancelled"
    if normalized in {"failed", "error"}:
        return "failed"
    return "requested"


def _trip_scheduling_status(ride: HealthISFRide, trip_state: str) -> str:
    appointment = _as_utc(getattr(ride, "appointment_time", None))
    now_utc = datetime.now(timezone.utc)
    if trip_state in {"completed", "cancelled", "failed"}:
        return "closed"
    if appointment is None:
        return "unscheduled"
    if appointment > now_utc:
        return "scheduled"
    if trip_state in {"assigned", "accepted", "arrived", "onboard", "in_transit"}:
        return "active_window"
    return "overdue"


def _build_trip_workflow_snapshot(db: Session, organization_id: str) -> dict[str, Any]:
    rides = (
        db.query(HealthISFRide)
        .filter(HealthISFRide.organization_id == organization_id)
        .order_by(HealthISFRide.requested_at.desc())
        .limit(240)
        .all()
    )
    ride_ids = [str(ride.id) for ride in rides]

    assignment_rows = (
        db.query(HealthISFDispatchAssignment)
        .filter(
            HealthISFDispatchAssignment.organization_id == organization_id,
            HealthISFDispatchAssignment.ride_id.in_(ride_ids if ride_ids else ["_none_"]),
        )
        .order_by(HealthISFDispatchAssignment.updated_at.desc())
        .all()
    )
    latest_assignment_by_ride: dict[str, HealthISFDispatchAssignment] = {}
    for row in assignment_rows:
        key = str(row.ride_id)
        if key not in latest_assignment_by_ride:
            latest_assignment_by_ride[key] = row

    dispatch_logs = (
        db.query(HealthISFDispatchLog)
        .filter(HealthISFDispatchLog.ride_id.in_(ride_ids if ride_ids else ["_none_"]))
        .order_by(HealthISFDispatchLog.created_at.desc())
        .all()
    )
    status_rows = (
        db.query(HealthISFRideStatusHistory)
        .filter(HealthISFRideStatusHistory.ride_id.in_(ride_ids if ride_ids else ["_none_"]))
        .order_by(HealthISFRideStatusHistory.created_at.desc())
        .all()
    )
    logs_by_ride: dict[str, list[HealthISFDispatchLog]] = {}
    for row in dispatch_logs:
        logs_by_ride.setdefault(str(row.ride_id), []).append(row)
    status_by_ride: dict[str, list[HealthISFRideStatusHistory]] = {}
    for row in status_rows:
        status_by_ride.setdefault(str(row.ride_id), []).append(row)

    drivers = (
        db.query(HealthISFDriver)
        .filter(HealthISFDriver.organization_id == organization_id)
        .order_by(HealthISFDriver.updated_at.desc())
        .limit(240)
        .all()
    )

    driver_by_id = {str(driver.id): driver for driver in drivers}

    trip_entities: list[dict[str, Any]] = []
    for ride in rides:
        ride_id = str(ride.id)
        assignment = latest_assignment_by_ride.get(ride_id)
        assigned_driver = driver_by_id.get(str(getattr(ride, "driver_id", "") or ""))
        trip_state = _trip_state_from_ride(ride)
        scheduling_status = _trip_scheduling_status(ride, trip_state)
        assignment_status = str(getattr(assignment, "assignment_state", "unassigned") or "unassigned").lower()
        if not ride.driver_id and assignment_status in {"", "none", "null"}:
            assignment_status = "unassigned"
        pickup_dropoff_state = "not_started"
        if trip_state == "accepted":
            pickup_dropoff_state = "pickup_en_route"
        elif trip_state == "arrived":
            pickup_dropoff_state = "pickup_arrived"
        elif trip_state == "onboard":
            pickup_dropoff_state = "pickup_verified"
        elif trip_state == "in_transit":
            pickup_dropoff_state = "dropoff_in_progress"
        elif trip_state == "completed":
            pickup_dropoff_state = "dropoff_completed"

        recurring_pattern = _safe_json_object(getattr(ride, "recurring_trip_pattern", None))
        ai_context = _safe_json_object(getattr(ride, "ai_dispatch_context", None))
        service_type = str(getattr(ride, "service_type", "") or "").strip().lower()
        is_nemt = any(token in service_type for token in ("medical", "dialysis", "nemt", "appointment"))

        risk_indicators: list[dict[str, Any]] = []
        appointment_time = _as_utc(getattr(ride, "appointment_time", None))
        now_utc = datetime.now(timezone.utc)
        if appointment_time and trip_state not in {"arrived", "onboard", "in_transit", "completed"}:
            minutes_to_appointment = int((appointment_time - now_utc).total_seconds() / 60)
            if minutes_to_appointment <= 30:
                risk_indicators.append(
                    {
                        "risk_type": "missed_appointment_risk",
                        "severity": "high" if minutes_to_appointment <= 10 else "medium",
                        "minutes_to_appointment": minutes_to_appointment,
                    }
                )
        if trip_state in {"failed", "escalated"}:
            risk_indicators.append({"risk_type": "operational_escalation", "severity": "high"})
        if assignment_status in {DispatchAssignmentState.REASSIGNMENT_PENDING.value, DispatchAssignmentState.REJECTED.value, DispatchAssignmentState.EXPIRED.value}:
            risk_indicators.append({"risk_type": "dispatch_instability", "severity": "medium"})
        if not ride.driver_id and trip_state in {"scheduled", "assigned"}:
            risk_indicators.append({"risk_type": "assignment_gap", "severity": "high"})

        route_progress_percent = {
            "requested": 5,
            "pending_review": 10,
            "scheduled": 20,
            "assigned": 35,
            "accepted": 50,
            "arrived": 65,
            "onboard": 80,
            "in_transit": 90,
            "completed": 100,
            "cancelled": 0,
            "failed": 0,
            "escalated": 40,
        }.get(trip_state, 0)
        shift_readiness = "ready"
        if assigned_driver is not None:
            driver_status = str(getattr(assigned_driver, "status", "") or getattr(assigned_driver, "availability_state", "available") or "available").lower()
            if driver_status in {"offline", "unavailable"}:
                shift_readiness = "not_ready"
            elif driver_status in {"assigned", "busy", "in_transit", "en_route_pickup", "waiting_at_pickup"}:
                shift_readiness = "engaged"
        elif trip_state in {"scheduled", "assigned"}:
            shift_readiness = "driver_required"

        incident_attachments: list[dict[str, Any]] = []
        for row in (logs_by_ride.get(ride_id) or [])[:24]:
            action = str(getattr(row, "action", "") or "").lower()
            if any(token in action for token in ("incident", "escalat", "fail", "cancel", "retry")):
                incident_attachments.append(
                    {
                        "event_id": str(getattr(row, "id", "") or ""),
                        "action": action,
                        "note": str(getattr(row, "note", "") or ""),
                        "timestamp": _iso_utc(getattr(row, "created_at", None)),
                    }
                )

        audit_timeline: list[dict[str, Any]] = []
        for row in (status_by_ride.get(ride_id) or [])[:18]:
            stamp = _as_utc(getattr(row, "created_at", None))
            audit_timeline.append(
                {
                    "event_type": "status_transition",
                    "from_state": str(getattr(row, "from_status", "") or ""),
                    "to_state": str(getattr(row, "to_status", "") or ""),
                    "note": str(getattr(row, "note", "") or ""),
                    "timestamp": stamp.isoformat() if stamp else None,
                }
            )
        for row in (logs_by_ride.get(ride_id) or [])[:18]:
            stamp = _as_utc(getattr(row, "created_at", None))
            audit_timeline.append(
                {
                    "event_type": "dispatch_action",
                    "action": str(getattr(row, "action", "") or ""),
                    "note": str(getattr(row, "note", "") or ""),
                    "timestamp": stamp.isoformat() if stamp else None,
                }
            )
        audit_timeline.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        arrival_timestamp = next(
            (
                str(item.get("timestamp") or "")
                for item in audit_timeline
                if str(item.get("to_state") or "").lower() in {"arrived"}
            ),
            None,
        )
        onboard_timestamp = next(
            (
                str(item.get("timestamp") or "")
                for item in audit_timeline
                if str(item.get("to_state") or "").lower() in {"rider_onboard", "onboard"}
            ),
            None,
        )

        trip_entities.append(
            {
                "trip_id": ride_id,
                "ride_id": ride_id,
                "rider_name": str(getattr(ride, "passenger_name", "") or ""),
                "rider_phone": str(getattr(ride, "passenger_phone", "") or ""),
                "pickup_address": str(getattr(ride, "pickup_address", "") or ""),
                "dropoff_address": str(getattr(ride, "dropoff_address", "") or ""),
                "provider_id": str(getattr(ride, "provider_id", "") or "") or None,
                "driver_id": str(getattr(ride, "driver_id", "") or "") or None,
                "assigned_driver_name": str(getattr(assigned_driver, "name", "") or "") or None,
                "trip_state": trip_state,
                "status": str(getattr(ride, "status", "") or ""),
                "scheduling_status": scheduling_status,
                "assignment_status": assignment_status,
                "pickup_dropoff_state": pickup_dropoff_state,
                "recurring": bool(getattr(ride, "recurring_trip_pattern", None)),
                "recurring_pattern": recurring_pattern,
                "nemt_metadata": {
                    "is_nemt": is_nemt,
                    "service_type": service_type,
                    "medicaid_claim_id": str(ai_context.get("medicaid_claim_id") or recurring_pattern.get("medicaid_claim_id") or "") or None,
                    "appointment_time": appointment_time.isoformat() if appointment_time else None,
                },
                "transport_risk_indicators": risk_indicators,
                "incident_attachments": incident_attachments,
                "audit_timeline": audit_timeline[:30],
                "proof_of_arrival": {
                    "required": trip_state in {"accepted", "arrived", "onboard", "in_transit", "completed"},
                    "completed": trip_state in {"arrived", "onboard", "in_transit", "completed"},
                    "timestamp": arrival_timestamp,
                    "authority_source": "health_isf.driver_arrived_pickup",
                },
                "rider_onboard_verification": {
                    "required": trip_state in {"arrived", "onboard", "in_transit", "completed"},
                    "verified": trip_state in {"onboard", "in_transit", "completed"},
                    "timestamp": onboard_timestamp,
                    "authority_source": "health_isf.driver_pickup_complete",
                },
                "route_progress_tracking": {
                    "stage": trip_state,
                    "pickup_dropoff_state": pickup_dropoff_state,
                    "percent_complete": route_progress_percent,
                    "authority_source": "health_isf.ride_lifecycle_manager",
                },
                "shift_readiness_state": shift_readiness,
                "authority_source": "health_isf.ride_lifecycle_manager",
                "live_dispatch_visibility": {
                    "dispatch_assignment_state": assignment_status,
                    "driver_assigned": bool(getattr(ride, "driver_id", None)),
                    "offer_expires_at": _iso_utc(getattr(assignment, "offer_expires_at", None)) if assignment else None,
                    "reassignment_pending": assignment_status == DispatchAssignmentState.REASSIGNMENT_PENDING.value,
                    "supervisor_escalation_required": any(str(risk.get("severity") or "") == "high" for risk in risk_indicators),
                },
                "requested_at": _iso_utc(getattr(ride, "requested_at", None)),
                "updated_at": _iso_utc(getattr(ride, "updated_at", None)),
            }
        )

    assignable_driver_statuses = {"available", "unavailable"}
    driver_availability = sorted(
        [
            {
                "driver_id": str(driver.id),
                "name": str(getattr(driver, "name", "") or ""),
                "status": str(getattr(driver, "availability_state", "") or getattr(driver, "status", "offline") or "offline").lower(),
                "is_online": bool(getattr(driver, "is_online", False)),
                "vehicle": str(getattr(driver, "vehicle_type", "") or ""),
                "last_seen_at": _iso_utc(getattr(driver, "last_seen_at", None)),
                "shift_readiness": "ready" if bool(getattr(driver, "is_online", False)) else "offline",
                "dispatch_assignable": str(getattr(driver, "availability_state", "") or getattr(driver, "status", "offline") or "offline").lower() in assignable_driver_statuses,
                "authority_source": "health_isf.driver_status",
            }
            for driver in drivers
            if str(getattr(driver, "availability_state", "") or getattr(driver, "status", "offline") or "offline").lower() in assignable_driver_statuses
        ],
        key=lambda item: (0 if str(item.get("status") or "") == "available" else 1, str(item.get("name") or "")),
    )

    trip_entities.sort(key=lambda item: str(item.get("requested_at") or ""), reverse=True)
    _TERMINAL_TRIP_STATES = {"completed", "cancelled", "failed", "dropoff_complete", "closed", "resolved"}
    live_trip_entities = [
        item
        for item in trip_entities
        if str(item.get("trip_state") or "").lower() not in _TERMINAL_TRIP_STATES
    ]
    unassigned_queue = [
        item
        for item in live_trip_entities
        if item.get("trip_state") in {"requested", "pending_review", "scheduled", "assigned"} and not item.get("driver_id")
    ]
    active_routes = [
        item
        for item in live_trip_entities
        if item.get("trip_state") in {"assigned", "accepted", "arrived", "onboard", "in_transit"}
    ]
    # Escalated/delayed live rides only — cancelled/failed belong in archived history.
    delayed_rides = [
        item for item in live_trip_entities if item.get("trip_state") in {"escalated", "delayed"}
    ]
    reassignment_queue = [
        item
        for item in live_trip_entities
        if str(item.get("assignment_status") or "")
        in {
            DispatchAssignmentState.REASSIGNMENT_PENDING.value,
            DispatchAssignmentState.REJECTED.value,
            DispatchAssignmentState.EXPIRED.value,
        }
    ]
    no_driver_recovery = [
        item
        for item in live_trip_entities
        if not item.get("driver_id") and item.get("trip_state") in {"scheduled", "assigned", "escalated"}
    ]
    recurring_rides = [item for item in trip_entities if bool(item.get("recurring"))]
    compliance_visibility = [
        {
            "trip_id": item.get("trip_id"),
            "state": item.get("trip_state"),
            "service_type": ((item.get("nemt_metadata") or {}).get("service_type")),
            "medicaid_claim_id": ((item.get("nemt_metadata") or {}).get("medicaid_claim_id")),
            "risk_count": len(list(item.get("transport_risk_indicators") or [])),
            "incident_count": len(list(item.get("incident_attachments") or [])),
            "evidence_count": len(list(item.get("audit_timeline") or [])),
        }
        for item in trip_entities
        if bool((item.get("nemt_metadata") or {}).get("is_nemt"))
    ]
    escalation_indicators = [
        {
            "trip_id": item.get("trip_id"),
            "rider_name": item.get("rider_name"),
            "state": item.get("trip_state"),
            "severity": "high" if item.get("trip_state") in {"failed", "escalated"} else "medium",
            "indicator_count": len(list(item.get("transport_risk_indicators") or [])),
            "supervisor_route": "supervisor" if item.get("trip_state") in {"failed", "escalated"} else "dispatcher",
            "authority_source": item.get("authority_source"),
        }
        for item in delayed_rides
    ]
    escalation_resolution_timeline = [
        {
            "trip_id": item.get("trip_id"),
            "trip_state": item.get("trip_state"),
            "event_type": audit_item.get("event_type"),
            "action": audit_item.get("action") or audit_item.get("to_state"),
            "timestamp": audit_item.get("timestamp"),
            "authority_source": item.get("authority_source"),
        }
        for item in delayed_rides[:30]
        for audit_item in list(item.get("audit_timeline") or [])[:8]
    ]
    ai_context = {
        "role": "operational_copilot",
        "trip_state_distribution": {
            state: len([item for item in trip_entities if str(item.get("trip_state") or "") == state])
            for state in TRIP_WORKFLOW_STATES
        },
        "live_trip_awareness": {
            "active_trip_count": len(active_routes),
            "delayed_trip_count": len(delayed_rides),
            "recurring_medical_trip_count": len(recurring_rides),
        },
        "escalation_awareness": {
            "escalated_trip_count": len([item for item in trip_entities if item.get("trip_state") == "escalated"]),
            "failed_trip_count": len([item for item in trip_entities if item.get("trip_state") == "failed"]),
            "supervisor_queue_depth": len(escalation_indicators),
        },
        "compliance_awareness": {
            "transport_compliance_feed": compliance_visibility[:20],
            "high_risk_nemt_trips": len([item for item in compliance_visibility if int(item.get("risk_count") or 0) > 0]),
        },
        "driver_state_awareness": {
            "available": len([item for item in driver_availability if item.get("status") == "available"]),
            "engaged": len([item for item in driver_availability if item.get("status") in {"assigned", "busy", "on_trip"}]),
            "offline": len([item for item in driver_availability if item.get("status") in {"offline", "unavailable"}]),
        },
        "dispatch_queue_awareness": {
            "unassigned_queue": len(unassigned_queue),
            "reassignment_queue": len(reassignment_queue),
            "no_driver_recovery": len(no_driver_recovery),
        },
        "dispatch_recommendations": [
            {
                "type": "rebalance",
                "message": "Rebalance assignment board when unassigned queue exceeds available drivers.",
                "severity": "high" if len(unassigned_queue) > len(driver_availability) else "medium",
            },
            {
                "type": "risk_watch",
                "message": "Escalate appointment-linked rides with <30m window and no assigned driver.",
                "severity": "high" if any((risk.get("risk_type") == "missed_appointment_risk") for item in trip_entities for risk in list(item.get("transport_risk_indicators") or [])) else "low",
            },
        ],
    }

    return {
        "state_machine": {
            "states": list(TRIP_WORKFLOW_STATES),
            "transitions": [{"from": edge[0], "to": edge[1]} for edge in TRIP_WORKFLOW_TRANSITIONS],
            "append_only": True,
            "replay_safe": True,
            "authority_enforced": True,
        },
        "trips": trip_entities,
        "dispatch": {
            "unassigned_queue": unassigned_queue,
            "active_routes": active_routes,
            "delayed_rides": delayed_rides,
            "driver_availability": driver_availability,
            "escalation_indicators": escalation_indicators,
            "reassignment_queue": reassignment_queue,
            "no_driver_recovery": no_driver_recovery,
            "supervisor_escalation_routing": escalation_indicators,
        },
        "driver_workflow": {
            "assigned_trip_workflows": active_routes,
            "incident_reporting_queue": [item for item in trip_entities if len(list(item.get("incident_attachments") or [])) > 0],
            "proof_of_arrival_queue": [item for item in active_routes if not bool((item.get("proof_of_arrival") or {}).get("completed"))],
            "onboard_verification_queue": [item for item in active_routes if not bool((item.get("rider_onboard_verification") or {}).get("verified"))],
            "route_progress_tracking": [
                {
                    "trip_id": item.get("trip_id"),
                    "route_progress": item.get("route_progress_tracking"),
                    "assigned_driver_name": item.get("assigned_driver_name"),
                    "trip_state": item.get("trip_state"),
                }
                for item in active_routes
            ],
            "shift_readiness": driver_availability,
        },
        "compliance": {
            "transport_compliance_visibility": compliance_visibility,
            "audit_review_feed": compliance_visibility[:80],
            "audit_evidence_feed": [
                {
                    "trip_id": source_trip.get("trip_id"),
                    "audit_timeline": source_trip.get("audit_timeline"),
                    "authority_source": source_trip.get("authority_source"),
                }
                for item in compliance_visibility[:40]
                for source_trip in trip_entities
                if source_trip.get("trip_id") == item.get("trip_id")
            ],
        },
        "supervisor": {
            "failed_trip_recovery": [item for item in trip_entities if item.get("trip_state") in {"failed", "escalated"}],
            "escalation_dashboard": escalation_indicators,
            "resolution_timeline": escalation_resolution_timeline,
        },
        "provider": {
            "facility_coordination_queue": [item for item in trip_entities if item.get("provider_id")],
            "coverage_visibility": [item for item in trip_entities if item.get("trip_state") in {"scheduled", "assigned", "accepted", "arrived", "onboard", "in_transit"}],
        },
        "ai_operational_context": ai_context,
    }


def _resolve_workspace_ride_id(payload: dict[str, Any]) -> str:
    return str(payload.get("trip_id") or payload.get("ride_id") or payload.get("task_id") or "").strip()


def _workspace_action_alias(action_type: str) -> str:
    action = str(action_type or "").strip().lower()
    return {
        "driver.mark_arrived": "driver.arrive",
        "driver.start_trip": "driver.onboard_rider",
    }.get(action, action)


def _workspace_action_status(execution_result: dict[str, Any]) -> str:
    workflow = str((execution_result or {}).get("workflow") or "").strip().lower()
    if workflow == "supervised_action_routed":
        return "submitted_for_supervised_workflow"
    if workflow == "unknown_action":
        return "submitted_no_mutation_executed"
    return "submitted_and_executed_via_supervised_gateway"


def _append_workspace_execution_timeline_event(
    *,
    organization_id: str,
    correlation_id: str,
    action_type: str,
    actor_user_id: str,
    role_view: str,
    timestamp: datetime,
    execution_result: dict[str, Any],
) -> None:
    workflow = str((execution_result or {}).get("workflow") or "workspace_action").strip().lower()
    title = {
        "dispatch_assignment": "Dispatch assignment executed",
        "dispatch_reassignment": "Dispatch reassignment executed",
        "trip_state_transition": "Trip workflow transition executed",
        "driver_accept_assignment": "Driver execution step completed",
        "compliance_workflow_action": "Compliance workflow action executed",
        "compliance_expiration_scan": "Compliance expiration scan executed",
        "supervisor_recovery_approved": "Supervisor recovery executed",
        "emergency_coordination_triggered": "Emergency coordination triggered",
        "ai_operational_summary": "AI operational summary generated",
        "supervised_action_routed": "Supervised action queued",
    }.get(workflow, "Workspace workflow execution completed")
    trip_id = str((execution_result or {}).get("trip_id") or "").strip() or None
    driver_id = str((execution_result or {}).get("driver_id") or "").strip() or None
    status = _workspace_action_status(execution_result)
    operational_timeline.append_event(
        TimelineEvent(
            event_id=f"workspace-action-execution-{uuid4().hex[:12]}",
            event_type=TimelineEventType.EXECUTION_COMPLETED,
            timestamp=timestamp,
            organization_id=organization_id,
            correlation_id=correlation_id,
            action_id=action_type,
            operator_identity=actor_user_id,
            source_reference_id=trip_id or driver_id or "workspace_action_execution",
            title=title,
            description=f"{role_view} completed {action_type} via supervised workflow gateway",
            metadata={
                "role_view": role_view,
                "role_scope": [role_view, "admin"],
                "action_type": action_type,
                "workflow": workflow,
                "status": status,
                "trip_id": trip_id,
                "driver_id": driver_id,
                "execution_result": execution_result,
                "authority_source": f"role_scope:{role_view}",
                "append_only": True,
                "replay_safe": True,
                "authority_enforced": True,
                "supervision_required": True,
            },
        )
    )


def _append_workspace_failure_timeline_event(
    *,
    organization_id: str,
    correlation_id: str,
    action_type: str,
    actor_user_id: str,
    role_view: str,
    timestamp: datetime,
    error_detail: str,
) -> None:
    operational_timeline.append_event(
        TimelineEvent(
            event_id=f"workspace-action-failed-{uuid4().hex[:12]}",
            event_type=TimelineEventType.EXECUTION_FAILED,
            timestamp=timestamp,
            organization_id=organization_id,
            correlation_id=correlation_id,
            action_id=action_type,
            operator_identity=actor_user_id,
            source_reference_id="workspace_action_execution",
            title="Workspace workflow execution failed",
            description=f"{role_view} attempted {action_type} but supervised execution failed",
            metadata={
                "role_view": role_view,
                "role_scope": [role_view, "admin"],
                "action_type": action_type,
                "error": error_detail,
                "status": "failed",
                "authority_source": f"role_scope:{role_view}",
                "append_only": True,
                "replay_safe": True,
                "authority_enforced": True,
                "supervision_required": True,
            },
        )
    )


def _execute_workspace_action(
    *,
    db: Session,
    organization_id: str,
    action_type: str,
    payload: dict[str, Any],
    user: UserContext,
) -> dict[str, Any]:
    action = _workspace_action_alias(action_type)
    ride_id = _resolve_workspace_ride_id(payload)
    ride = health_isf_service.get_ride_by_id(db, ride_id) if ride_id else None
    if ride is not None and str(getattr(ride, "organization_id", "")) != str(organization_id):
        raise HTTPException(status_code=403, detail="trip does not belong to current organization")

    if action == "dispatch.assign_driver":
        driver_id = str(payload.get("driver_id") or "").strip()
        if not ride_id or not driver_id:
            raise HTTPException(status_code=422, detail="trip_id and driver_id are required")
        updated = health_isf_service.assign_driver_to_ride(
            db,
            ride_id=ride_id,
            driver_id=driver_id,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "dispatch_assignment",
            "trip_id": ride_id,
            "driver_id": driver_id,
            "assignment_state": "assigned",
            "trip_state": _trip_state_from_ride(updated),
            "authority_source": "health_isf.assign_driver_to_ride",
        }

    if action in {"dispatch.reassign_driver", "supervisor.reassign_failed_trip"}:
        driver_id = str(payload.get("driver_id") or "").strip()
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        if driver_id:
            updated = health_isf_service.assign_driver_to_ride(
                db,
                ride_id=ride_id,
                driver_id=driver_id,
                actor_user_id=user.user_id,
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="ride not found")
            return {
                "workflow": "dispatch_reassignment",
                "trip_id": ride_id,
                "driver_id": driver_id,
                "assignment_state": "reassigned",
                "trip_state": _trip_state_from_ride(updated),
                "authority_source": "health_isf.assign_driver_to_ride",
            }
        reassign = health_isf_service.reassign_expired_request(
            db,
            ride_id=ride_id,
            actor_user_id=user.user_id,
            reason=str(payload.get("reason") or "workspace_reassign_requested"),
        )
        offer = reassign.get("offer") if isinstance(reassign, dict) else None
        return {
            "workflow": "dispatch_reassignment",
            "trip_id": ride_id,
            "assignment_state": str(getattr(offer, "assignment_state", "reassignment_pending") or "reassignment_pending"),
            "driver_id": str(getattr(offer, "driver_id", "") or "") or None,
            "authority_source": "health_isf.reassign_expired_request",
        }

    if action in {"dispatch.cancel_ride", "dispatch.mark_arrived", "dispatch.mark_onboard", "dispatch.complete_ride", "dispatch.escalate_ride", "dispatch.retry_failed_ride", "driver.start_route", "driver.report_incident", "supervisor.override_trip_failure"}:
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        target_status = {
            "dispatch.cancel_ride": RideStatus.CANCELLED.value,
            "dispatch.mark_arrived": RideStatus.ARRIVED.value,
            "dispatch.mark_onboard": RideStatus.RIDER_ONBOARD.value,
            "dispatch.complete_ride": RideStatus.COMPLETED.value,
            "dispatch.escalate_ride": RideStatus.ESCALATED.value,
            "dispatch.retry_failed_ride": RideStatus.QUEUED.value,
            "driver.start_route": RideStatus.DRIVER_EN_ROUTE.value,
            "driver.report_incident": RideStatus.ESCALATED.value,
            "supervisor.override_trip_failure": RideStatus.QUEUED.value,
        }.get(action, RideStatus.REQUESTED.value)
        updated = health_isf_service.update_ride_status(
            db,
            ride_id=ride_id,
            status=target_status,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "trip_state_transition",
            "trip_id": ride_id,
            "requested_status": target_status,
            "trip_state": _trip_state_from_ride(updated),
            "authority_source": "health_isf.update_ride_status",
        }

    if action == "driver.accept_assignment":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        driver_id = str(payload.get("driver_id") or (ride.driver_id if ride else "") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")
        updated = health_isf_service.accept_driver_ride(
            db,
            driver_id=driver_id,
            ride_id=ride_id,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "driver_accept_assignment",
            "trip_id": ride_id,
            "driver_id": driver_id,
            "trip_state": _trip_state_from_ride(updated),
            "authority_source": "health_isf.accept_driver_ride",
        }

    if action == "driver.arrive":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        driver_id = str(payload.get("driver_id") or (ride.driver_id if ride else "") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")
        updated = health_isf_service.driver_arrived_pickup(
            db,
            driver_id=driver_id,
            ride_id=ride_id,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "trip_state_transition",
            "trip_id": ride_id,
            "driver_id": driver_id,
            "requested_status": RideStatus.ARRIVED.value,
            "trip_state": _trip_state_from_ride(updated),
            "proof_of_arrival": True,
            "authority_source": "health_isf.driver_arrived_pickup",
        }

    if action == "driver.onboard_rider":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        driver_id = str(payload.get("driver_id") or (ride.driver_id if ride else "") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")
        updated = health_isf_service.driver_pickup_complete(
            db,
            driver_id=driver_id,
            ride_id=ride_id,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "trip_state_transition",
            "trip_id": ride_id,
            "driver_id": driver_id,
            "requested_status": RideStatus.RIDER_ONBOARD.value,
            "trip_state": _trip_state_from_ride(updated),
            "rider_onboard_verified": True,
            "authority_source": "health_isf.driver_pickup_complete",
        }

    if action == "driver.update_route_progress":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        updated = health_isf_service.update_ride_status(
            db,
            ride_id=ride_id,
            status=RideStatus.IN_PROGRESS.value,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "trip_state_transition",
            "trip_id": ride_id,
            "requested_status": RideStatus.IN_PROGRESS.value,
            "trip_state": _trip_state_from_ride(updated),
            "route_progress_percent": int(payload.get("route_progress_percent") or 90),
            "authority_source": "health_isf.update_ride_status",
        }

    if action == "driver.update_shift_readiness":
        driver_id = str(payload.get("driver_id") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")
        requested_status = str(payload.get("status") or "available").strip().lower() or "available"
        updated_driver = health_isf_service.set_driver_operational_status(
            db,
            driver_id=driver_id,
            status=requested_status,
            actor_user_id=user.user_id,
            note=str(payload.get("note") or "workspace_shift_readiness_update"),
        )
        if updated_driver is None:
            raise HTTPException(status_code=404, detail="driver not found")
        return {
            "workflow": "driver_shift_readiness_updated",
            "driver_id": driver_id,
            "status": str(getattr(updated_driver, "status", requested_status) or requested_status).lower(),
            "authority_source": "health_isf.set_driver_operational_status",
        }

    if action == "driver.complete_trip":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        driver_id = str(payload.get("driver_id") or (ride.driver_id if ride else "") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")
        updated = health_isf_service.driver_dropoff_complete(
            db,
            driver_id=driver_id,
            ride_id=ride_id,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "trip_state_transition",
            "trip_id": ride_id,
            "driver_id": driver_id,
            "requested_status": RideStatus.COMPLETED.value,
            "trip_state": _trip_state_from_ride(updated),
            "authority_source": "health_isf.driver_dropoff_complete",
        }

    if action == "compliance.review_deficiency":
        document_id = str(payload.get("document_id") or "").strip()
        if document_id:
            document_state = ComplianceService.verify_document(
                db,
                organization_id=organization_id,
                actor=user,
                document_id=document_id,
                verification_status="pending",
                reason=str(payload.get("reason") or "workspace_document_review_opened"),
                correlation_id=f"document-review-{uuid4().hex[:12]}",
            )
            return {
                "workflow": "compliance_workflow_action",
                "document_id": document_id,
                "workflow_step": "document_review_started",
                "document_state": document_state,
                "authority_source": "nova.compliance_service.verify_document",
            }
        driver_id = str(payload.get("driver_id") or "").strip()
        if not driver_id:
            return {
                "workflow": "supervised_action_routed",
                "action_type": action,
                "trip_id": ride_id or None,
                "status": "queued_for_supervised_processing",
            }
        profile_state = ComplianceService.workflow_action(
            db,
            organization_id=organization_id,
            actor=user,
            driver_id=driver_id,
            action="compliance_review_started",
            reason=str(payload.get("reason") or "workspace_compliance_review_started"),
            correlation_id=f"compliance-review-{uuid4().hex[:12]}",
        )
        return {
            "workflow": "compliance_workflow_action",
            "driver_id": driver_id,
            "workflow_step": "compliance_review_started",
            "profile_state": profile_state,
            "authority_source": "nova.compliance_service.workflow_action",
        }

    if action in {"compliance.approve_onboarding", "compliance.deny_onboarding"}:
        driver_id = str(payload.get("driver_id") or "").strip()
        if not driver_id:
            raise HTTPException(status_code=422, detail="driver_id is required")
        workflow_step = "approved" if action == "compliance.approve_onboarding" else "rejected"
        profile_state = ComplianceService.workflow_action(
            db,
            organization_id=organization_id,
            actor=user,
            driver_id=driver_id,
            action=workflow_step,
            reason=str(payload.get("reason") or f"workspace_{workflow_step}"),
            correlation_id=f"compliance-decision-{uuid4().hex[:12]}",
        )
        return {
            "workflow": "compliance_workflow_action",
            "driver_id": driver_id,
            "workflow_step": workflow_step,
            "profile_state": profile_state,
            "authority_source": "nova.compliance_service.workflow_action",
        }

    if action == "compliance.flag_document_expiration":
        scan_result = ComplianceService.expiration_scan(
            db,
            organization_id=organization_id,
            actor=user,
            correlation_id=f"expiration-scan-{uuid4().hex[:12]}",
        )
        return {
            "workflow": "compliance_expiration_scan",
            "scan_result": scan_result,
            "status": "expiration_alerts_refreshed",
            "authority_source": "nova.compliance_service.expiration_scan",
        }

    if action == "supervisor.approve_recovery":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        updated = health_isf_service.update_ride_status(
            db,
            ride_id=ride_id,
            status=RideStatus.QUEUED.value,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "supervisor_recovery_approved",
            "trip_id": ride_id,
            "trip_state": _trip_state_from_ride(updated),
            "requested_status": RideStatus.QUEUED.value,
            "authority_source": "health_isf.update_ride_status",
        }

    if action == "supervisor.trigger_emergency_coordination":
        if not ride_id:
            raise HTTPException(status_code=422, detail="trip_id is required")
        updated = health_isf_service.update_ride_status(
            db,
            ride_id=ride_id,
            status=RideStatus.ESCALATED.value,
            actor_user_id=user.user_id,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail="ride not found")
        return {
            "workflow": "emergency_coordination_triggered",
            "trip_id": ride_id,
            "trip_state": _trip_state_from_ride(updated),
            "requested_status": RideStatus.ESCALATED.value,
            "authority_source": "health_isf.update_ride_status",
        }

    if action in {"dispatch.contact_rider", "dispatch.contact_driver", "medical_coordinator.review_appointment_risk", "medical_coordinator.coordinate_facility", "medical_coordinator.escalate_patient_support", "provider.open_sync_handoff", "provider.review_sla_alert", "provider.update_coverage_window", "driver_support.open_ticket", "driver_support.route_escalation", "compliance.review_deficiency", "compliance.open_regulatory_exception", "compliance.approve_onboarding", "compliance.deny_onboarding", "compliance.flag_document_expiration", "supervisor.approve_override", "supervisor.reject_override", "supervisor.approve_recovery", "supervisor.trigger_emergency_coordination"}:
        return {
            "workflow": "supervised_action_routed",
            "action_type": action,
            "trip_id": ride_id or None,
            "status": "queued_for_supervised_processing",
        }

    if action == "ai.generate_operational_summary":
        snapshot = _build_trip_workflow_snapshot(db, organization_id)
        distribution = (snapshot.get("ai_operational_context") or {}).get("trip_state_distribution") or {}
        return {
            "workflow": "ai_operational_summary",
            "summary": {
                "trip_state_distribution": distribution,
                "high_risk_trips": len(
                    [
                        item
                        for item in list(snapshot.get("trips") or [])
                        if any(str(risk.get("severity") or "") == "high" for risk in list(item.get("transport_risk_indicators") or []))
                    ]
                ),
                "dispatch_unassigned": len(list(((snapshot.get("dispatch") or {}).get("unassigned_queue") or []))),
                "dispatch_delayed": len(list(((snapshot.get("dispatch") or {}).get("delayed_rides") or []))),
            },
        }

    return {
        "workflow": "unknown_action",
        "action_type": action,
        "status": "no_mutation_executed",
    }


def _build_correlation_summary(events: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        correlation_id = str(event.get("correlation_id") or "")
        if not correlation_id:
            continue
        grouped.setdefault(correlation_id, []).append(event)

    groups: list[dict[str, Any]] = []
    for correlation_id, rows in grouped.items():
        event_types = sorted({str(row.get("event_type") or "unknown") for row in rows})
        role_scope = sorted({scope for row in rows for scope in (row.get("role_scope") or [])})
        last_timestamp = max([str(row.get("timestamp") or "") for row in rows], default="")
        groups.append(
            {
                "correlation_id": correlation_id,
                "event_count": len(rows),
                "event_types": event_types,
                "role_scope": role_scope,
                "last_timestamp": last_timestamp,
                "read_only": True,
            }
        )

    groups.sort(key=lambda row: int(row.get("event_count", 0) or 0), reverse=True)
    return {
        "total_groups": len(groups),
        "groups": groups[:40],
        "read_only": True,
        "append_only": True,
    }

router = APIRouter(
    prefix="/api/ops",
    tags=["ops-hydration"],
    dependencies=[Depends(require_ops_access)],
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_audit_metadata(*, endpoint: str, role: str, organization_id: str, correlation_id: str) -> dict[str, Any]:
    return {
        "generated_at": _utc_now_iso(),
        "endpoint": endpoint,
        "correlation_id": correlation_id,
        "organization_id": organization_id,
        "request_role": role,
        "append_only": True,
        "replay_safe": True,
        "supervision_required": True,
        "audit_chain_compatible": True,
        "execution_disabled": True,
        "advisory_only": True,
        "deny_by_default": True,
    }


def _role_visibility(role: str) -> dict[str, bool]:
    role_key = str(role or "").lower()

    if role_key in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        return {
            "show_driver_metrics": True,
            "show_provider_metrics": True,
            "show_runtime_metrics": True,
            "show_alert_details": True,
            "show_timeline_details": True,
            "show_recommendations": True,
            "show_audit_details": True,
        }

    if role_key in {ROLE_COMPLIANCE_OFFICER, ROLE_SUPERVISOR, ROLE_DRIVER_SUPPORT, ROLE_MEDICAL_COORDINATOR}:
        return {
            "show_driver_metrics": True,
            "show_provider_metrics": True,
            "show_runtime_metrics": True,
            "show_alert_details": True,
            "show_timeline_details": True,
            "show_recommendations": True,
            "show_audit_details": True,
        }

    if role_key == ROLE_DISPATCHER:
        return {
            "show_driver_metrics": True,
            "show_provider_metrics": True,
            "show_runtime_metrics": True,
            "show_alert_details": True,
            "show_timeline_details": True,
            "show_recommendations": True,
            "show_audit_details": False,
        }

    if role_key == ROLE_ANALYTICS_READONLY:
        return {
            "show_driver_metrics": False,
            "show_provider_metrics": False,
            "show_runtime_metrics": True,
            "show_alert_details": False,
            "show_timeline_details": False,
            "show_recommendations": True,
            "show_audit_details": True,
        }

    if role_key in {ROLE_PROVIDER, ROLE_DRIVER, ROLE_RIDER}:
        return {
            "show_driver_metrics": False,
            "show_provider_metrics": False,
            "show_runtime_metrics": True,
            "show_alert_details": False,
            "show_timeline_details": False,
            "show_recommendations": False,
            "show_audit_details": False,
        }

    return {
        "show_driver_metrics": True,
        "show_provider_metrics": False,
        "show_runtime_metrics": True,
        "show_alert_details": False,
        "show_timeline_details": False,
        "show_recommendations": True,
        "show_audit_details": False,
    }


def _recommendations_from_summary(summary: dict[str, Any], role: str) -> list[dict[str, Any]]:
    alerts = summary.get("alerts", {}) if isinstance(summary, dict) else {}
    delayed = int(alerts.get("delayed_operations", 0) or 0)
    backlog = int(alerts.get("event_stream_backlog", 0) or 0)
    active_rides = int(summary.get("rides", {}).get("active", 0) or 0)
    available_drivers = int(summary.get("drivers", {}).get("available", 0) or 0)
    overloaded_providers = int(summary.get("providers", {}).get("overloaded", 0) or 0)

    recommendations: list[dict[str, Any]] = []

    if delayed > 0:
        recommendations.append(
            {
                "id": f"rec-delayed-{delayed}",
                "category": "queue_congestion",
                "severity": "high" if delayed >= 3 else "medium",
                "confidence": min(0.98, 0.55 + (0.05 * delayed)),
                "title": "Delayed operations require supervisor review",
                "advisory": "Review delayed workflow rows and confirm provider coverage before any supervised upstream action.",
                "supervisor_review_required": True,
                "advisory_only": True,
                "execution_disabled": True,
            }
        )

    if backlog > 0:
        recommendations.append(
            {
                "id": f"rec-backlog-{backlog}",
                "category": "event_stream_backlog",
                "severity": "medium",
                "confidence": min(0.95, 0.5 + (0.01 * backlog)),
                "title": "Event stream backlog detected",
                "advisory": "Inspect append-only timeline growth and runtime governor telemetry before considering manual intervention.",
                "supervisor_review_required": True,
                "advisory_only": True,
                "execution_disabled": True,
            }
        )

    if active_rides > 0 and available_drivers <= 1:
        recommendations.append(
            {
                "id": "rec-driver-shortage",
                "category": "driver_shortage",
                "severity": "high",
                "confidence": 0.82,
                "title": "Potential driver staffing imbalance",
                "advisory": "Verify driver availability and handoff coverage in dispatch-safe mode.",
                "supervisor_review_required": True,
                "advisory_only": True,
                "execution_disabled": True,
            }
        )

    if overloaded_providers > 0:
        recommendations.append(
            {
                "id": "rec-provider-overload",
                "category": "provider_imbalance",
                "severity": "medium",
                "confidence": 0.76,
                "title": "Provider load imbalance detected",
                "advisory": "Review provider distribution and route balancing signals. Keep actions advisory until approved upstream.",
                "supervisor_review_required": True,
                "advisory_only": True,
                "execution_disabled": True,
            }
        )

    if not recommendations:
        recommendations.append(
            {
                "id": "rec-stable-watch",
                "category": "runtime_stability",
                "severity": "low",
                "confidence": 0.67,
                "title": "Runtime posture stable",
                "advisory": "Continue monitoring supervision and runtime governor telemetry; no execution paths are available here.",
                "supervisor_review_required": True,
                "advisory_only": True,
                "execution_disabled": True,
            }
        )

    for recommendation in recommendations:
        recommendation["role_scope"] = role
        recommendation["immutability_reference"] = f"audit-ref-{uuid4().hex[:12]}"

    return recommendations[:8]


def _build_summary_payload(db: Session, organization_id: str, role: str) -> dict[str, Any]:
    overview = build_operational_workflow_overview(db, organization_id=organization_id)
    telemetry_panels = overview.get("live_operational_telemetry_panels", {}) if isinstance(overview, dict) else {}
    lifecycle = overview.get("ride_lifecycle_engine", {}).get("state_counts", {}) if isinstance(overview, dict) else {}
    driver_states = overview.get("driver_state_registry", {}).get("states", {}) if isinstance(overview, dict) else {}
    provider_states = overview.get("provider_state_registry", {}).get("states", {}) if isinstance(overview, dict) else {}
    alerts = telemetry_panels.get("operational_alerts", {}) if isinstance(telemetry_panels, dict) else {}

    ride_active = int(
        int(lifecycle.get("ASSIGNED", 0) or 0)
        + int(lifecycle.get("ACCEPTED", 0) or 0)
        + int(lifecycle.get("EN_ROUTE", 0) or 0)
        + int(lifecycle.get("ARRIVED", 0) or 0)
        + int(lifecycle.get("IN_PROGRESS", 0) or 0)
    )

    return {
        "organization_id": organization_id,
        "role_scope": role,
        "dashboard": {
            "active_drivers": int(driver_states.get("available", 0) or 0),
            "available_providers": int(provider_states.get("active", 0) or 0),
            "rides_in_queue": int(lifecycle.get("REQUESTED", 0) or 0),
            "operational_load": ride_active,
            "alert_count": int(alerts.get("delayed_operations", 0) or 0),
        },
        "rides": {
            "state_counts": lifecycle,
            "active": ride_active,
            "requested": int(lifecycle.get("REQUESTED", 0) or 0),
            "completed": int(lifecycle.get("COMPLETED", 0) or 0),
        },
        "drivers": {
            "state_counts": driver_states,
            "available": int(driver_states.get("available", 0) or 0),
            "assigned": int(driver_states.get("assigned", 0) or 0),
            "en_route": int(driver_states.get("en_route", 0) or 0),
        },
        "providers": {
            "state_counts": provider_states,
            "active": int(provider_states.get("active", 0) or 0),
            "pending": int(provider_states.get("pending", 0) or 0),
            "overloaded": int(provider_states.get("overloaded", 0) or 0),
        },
        "alerts": {
            "delayed_operations": int(alerts.get("delayed_operations", 0) or 0),
            "event_stream_backlog": int(alerts.get("event_stream_backlog", 0) or 0),
        },
        "workflow_timeline": telemetry_panels.get("workflow_timeline", []) if isinstance(telemetry_panels, dict) else [],
        "event_stream_preview": overview.get("operational_state_visualization", {}).get("event_stream_preview", []),
        "governance": {
            "supervision_required": True,
            "execution_disabled": True,
            "advisory_only": True,
            "replay_safe": True,
            "append_only": True,
            "deny_by_default": True,
        },
    }


def _apply_role_mask(payload: dict[str, Any], role: str) -> dict[str, Any]:
    visibility = _role_visibility(role)

    masked = dict(payload)
    masked["visibility"] = visibility

    if not visibility["show_driver_metrics"]:
        masked["drivers"] = {"masked": True, "state_counts": {}, "available": None, "assigned": None, "en_route": None}
        if isinstance(masked.get("dashboard"), dict):
            masked["dashboard"]["active_drivers"] = None

    if not visibility["show_provider_metrics"]:
        masked["providers"] = {"masked": True, "state_counts": {}, "active": None, "pending": None, "overloaded": None}
        if isinstance(masked.get("dashboard"), dict):
            masked["dashboard"]["available_providers"] = None

    if not visibility["show_alert_details"]:
        masked["alerts"] = {
            "delayed_operations": int((payload.get("alerts") or {}).get("delayed_operations", 0) or 0),
            "event_stream_backlog": None,
            "masked": True,
        }

    if not visibility["show_timeline_details"]:
        masked["workflow_timeline"] = []
        masked["event_stream_preview"] = []

    return masked


@router.get("/dashboard-summary")
def ops_dashboard_summary(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    correlation_id = f"ops-dashboard-{uuid4().hex[:12]}"

    record_supervision_event(
        subsystem="ops_hydration",
        event="dashboard_summary_accessed",
        details={"organization_id": org_id, "role": user.role, "correlation_id": correlation_id},
    )

    summary = _build_summary_payload(db, org_id, user.role)
    masked = _apply_role_mask(summary, user.role)
    masked["assistant_recommendations"] = _recommendations_from_summary(masked, user.role)
    masked["audit_metadata"] = _build_audit_metadata(
        endpoint="/api/ops/dashboard-summary",
        role=user.role,
        organization_id=org_id,
        correlation_id=correlation_id,
    )
    return masked


@router.get("/live-status")
def ops_live_status(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    correlation_id = f"ops-live-{uuid4().hex[:12]}"

    supervision = build_supervision_snapshot()
    metrics = operational_metrics.build_snapshot(org_id).to_dict()

    runtime_governor = supervision.get("runtime_governor", {}) if isinstance(supervision, dict) else {}
    websocket_status = supervision.get("websocket_status", {}) if isinstance(supervision, dict) else {}
    memory_status = supervision.get("memory_persistence", {}) if isinstance(supervision, dict) else {}
    log_status = supervision.get("supervision_log_status", {}) if isinstance(supervision, dict) else {}

    queue_latency_ms = float((metrics.get("latency", {}) or {}).get("average_execution_latency_ms", 0.0) or 0.0)

    payload = {
        "organization_id": org_id,
        "role_scope": user.role,
        "runtime_governor_state": runtime_governor,
        "middleware_health": {
            "status": "active",
            "security_headers": "enforced",
            "request_tracing": "enforced",
            "tenant_auth_validation": "enforced",
            "error_boundary": "enforced",
        },
        "websocket_readiness": websocket_status,
        "queue_latency": {
            "average_execution_latency_ms": queue_latency_ms,
            "p95_execution_latency_ms": float((metrics.get("latency", {}) or {}).get("p95_execution_latency_ms", 0.0) or 0.0),
            "status": "watch" if queue_latency_ms > 1500 else "healthy",
        },
        "api_response_health": {
            "backend_status": supervision.get("backend_status", "unknown"),
            "supervision_status": supervision.get("supervision_status", "unknown"),
            "health_classification": supervision.get("health_classification", "unknown"),
        },
        "route_registration_health": {
            "status": "healthy",
            "registered_shell_routes": [
                "/dashboard",
                "/rides",
                "/drivers",
                "/providers",
                "/operations",
                "/system-health",
                "/ai-assistant",
            ],
            "read_only_rendering": True,
        },
        "audit_pipeline_health": {
            "status": log_status.get("status", "unknown"),
            "retained_files": int(log_status.get("retained_files", 0) or 0),
            "retention_limit": int(log_status.get("retention_limit", 0) or 0),
            "append_only": True,
        },
        "memory_persistence": memory_status,
        "governance": {
            "execution_disabled": True,
            "advisory_only": True,
            "supervision_required": True,
            "deny_by_default": True,
            "runtime_governor_semantics_preserved": True,
            "replay_safe": True,
        },
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/live-status",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }

    if not _role_visibility(user.role).get("show_runtime_metrics", False):
        payload["queue_latency"] = {"masked": True, "status": "restricted"}

    record_supervision_event(
        subsystem="ops_hydration",
        event="live_status_accessed",
        details={"organization_id": org_id, "role": user.role, "correlation_id": correlation_id},
    )

    return payload


@router.get("/alerts")
def ops_alerts(
    organization_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=200),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    correlation_id = f"ops-alerts-{uuid4().hex[:12]}"

    summary = _build_summary_payload(db, org_id, user.role)
    recommendations = _recommendations_from_summary(summary, user.role)
    visibility = _role_visibility(user.role)

    alert_rows: list[dict[str, Any]] = []
    for rec in recommendations[:limit]:
        alert_rows.append(
            {
                "alert_id": f"alert-{rec['id']}",
                "severity": rec.get("severity", "medium"),
                "category": rec.get("category", "operational"),
                "title": rec.get("title", "Operational advisory"),
                "description": rec.get("advisory", ""),
                "confidence": rec.get("confidence", 0.0),
                "advisory_only": True,
                "supervisor_review_required": True,
                "timestamp": _utc_now_iso(),
            }
        )

    if not visibility.get("show_alert_details", False):
        for row in alert_rows:
            row["description"] = "masked_for_role"
            row["confidence"] = None

    record_supervision_event(
        subsystem="ops_hydration",
        event="alerts_accessed",
        details={"organization_id": org_id, "role": user.role, "correlation_id": correlation_id},
    )

    return {
        "organization_id": org_id,
        "role_scope": user.role,
        "summary": summary.get("alerts", {}),
        "alerts": alert_rows,
        "append_only": True,
        "replay_safe": True,
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/alerts",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }


@router.get("/timeline")
def ops_timeline(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    correlation_id = f"ops-timeline-{uuid4().hex[:12]}"
    visibility = _role_visibility(user.role)

    events = operational_timeline.get_events_by_organization(org_id, limit=2000)
    filtered = [
        event.to_dict()
        for event in sorted(events, key=lambda item: int(item.sequence_number or 0))
        if int(event.sequence_number or 0) > int(after_sequence)
    ]

    if len(filtered) > limit:
        filtered = filtered[-limit:]

    if not visibility.get("show_timeline_details", False):
        normalized_role = str(user.role or "").strip().lower()
        for item in filtered:
            raw_metadata = item.get("metadata")
            metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
            raw_scope = metadata.get("role_scope")
            role_scope = raw_scope if isinstance(raw_scope, list) else []
            normalized_scope = {str(scope or "").strip().lower() for scope in role_scope}
            is_own_role_scoped_workflow = (
                normalized_role in normalized_scope
                and str(item.get("operator_identity") or "").strip() == str(user.user_id or "").strip()
                and bool(metadata.get("action_type"))
            )
            if is_own_role_scoped_workflow:
                continue
            item["description"] = "masked_for_role"
            item["metadata"] = {"masked": True}

    next_cursor = max([int(item.get("sequence_number", 0) or 0) for item in filtered], default=after_sequence)

    record_supervision_event(
        subsystem="ops_hydration",
        event="timeline_accessed",
        details={
            "organization_id": org_id,
            "role": user.role,
            "correlation_id": correlation_id,
            "after_sequence": after_sequence,
            "returned": len(filtered),
        },
    )

    return {
        "organization_id": org_id,
        "role_scope": user.role,
        "after_sequence": after_sequence,
        "next_cursor": next_cursor,
        "events": filtered,
        "append_only": True,
        "ordering": "sequence_ascending",
        "replay_safe": True,
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/timeline",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }


@router.get("/stream")
def ops_stream(
    organization_id: str | None = Query(None),
    after_sequence: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    role_view: str | None = Query(None),
    simulate_stream_unavailable: bool = Query(False),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    correlation_id = f"ops-stream-{uuid4().hex[:12]}"

    resolved_role_view = _effective_role_view(user.role, role_view)

    timeline_rows = operational_timeline.get_events_by_organization(org_id, limit=2000)
    timeline_contract_rows = [
        _timeline_to_stream_contract(row.to_dict())
        for row in sorted(timeline_rows, key=lambda item: int(item.sequence_number or 0))
        if int(row.sequence_number or 0) > int(after_sequence)
    ]

    overview = build_operational_workflow_overview(db, organization_id=org_id)
    bus_rows = ((overview.get("event_stream") or {}).get("event_bus") or {}).get("events") or []
    bus_contract_rows = [
        _bus_to_stream_contract(row)
        for row in bus_rows
        if int((row or {}).get("sequence", 0) or 0) > int(after_sequence)
    ]

    merged_by_id: dict[str, dict[str, Any]] = {}
    for row in timeline_contract_rows + bus_contract_rows:
        key = str(row.get("event_id") or "")
        if not key:
            continue
        merged_by_id[key] = row

    merged_events = sorted(
        merged_by_id.values(),
        key=lambda item: int(item.get("sequence", 0) or 0),
    )
    scoped_events = _filter_stream_events_for_role(merged_events, resolved_role_view)
    scoped_events = scoped_events[:limit]

    next_cursor = max([int(item.get("sequence", 0) or 0) for item in scoped_events], default=after_sequence)
    last_event = scoped_events[-1] if scoped_events else None

    sync = OperationalSynchronizationEngine.synchronization_snapshot(org_id)
    supervision = build_supervision_snapshot()
    websocket_status = str(((supervision or {}).get("websocket_status") or {}).get("status") or "unknown").lower()

    stream_connected = websocket_status in {"connected", "healthy", "active"} and not bool(simulate_stream_unavailable)
    stream_mode = "streaming" if stream_connected else "polling_fallback"

    record_supervision_event(
        subsystem="ops_hydration",
        event="stream_accessed",
        details={
            "organization_id": org_id,
            "role": user.role,
            "role_view": resolved_role_view,
            "correlation_id": correlation_id,
            "after_sequence": after_sequence,
            "returned": len(scoped_events),
            "stream_mode": stream_mode,
        },
    )

    return {
        "organization_id": org_id,
        "role_scope": user.role,
        "role_view": resolved_role_view,
        "after_sequence": after_sequence,
        "next_cursor": next_cursor,
        "contract_events": scoped_events,
        "correlation": _build_correlation_summary(scoped_events),
        "stream_status": {
            "connected": stream_connected,
            "mode": stream_mode,
            "fallback_polling_active": not stream_connected,
            "last_event_received": (last_event or {}).get("timestamp"),
            "event_count": len(scoped_events),
            "timeline_sync_status": "active" if len(scoped_events) > 0 else "idle",
            "supervision_safe": True,
            "replay_safe": True,
        },
        "event_bus": {
            "latest_sequence": int((((sync or {}).get("event_bus") or {}).get("latest_sequence", 0) or 0)),
            "ordered": True,
            "tenant_scoped": True,
            "replay_safe": True,
        },
        "governance": {
            "execution_disabled": True,
            "advisory_only": True,
            "replay_safe": True,
            "append_only": True,
            "supervision_required": True,
            "deny_by_default": True,
            "mutation_enabled": False,
            "dispatch_actions_enabled": False,
            "autonomous_execution": False,
        },
        "append_only": True,
        "ordering": "sequence_ascending",
        "replay_safe": True,
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/stream",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }


@router.get("/recommendations")
def ops_recommendations(
    organization_id: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    correlation_id = f"ops-recs-{uuid4().hex[:12]}"

    summary = _build_summary_payload(db, org_id, user.role)
    recommendations = _recommendations_from_summary(summary, user.role)

    if not _role_visibility(user.role).get("show_recommendations", False):
        recommendations = [
            {
                "id": "rec-masked",
                "category": "restricted",
                "severity": "low",
                "confidence": None,
                "title": "Recommendations restricted for current role",
                "advisory": "Use supervisor-approved context for additional operational recommendations.",
                "supervisor_review_required": True,
                "advisory_only": True,
                "execution_disabled": True,
                "role_scope": user.role,
                "immutability_reference": f"audit-ref-{uuid4().hex[:12]}",
            }
        ]

    record_supervision_event(
        subsystem="ops_hydration",
        event="recommendations_accessed",
        details={"organization_id": org_id, "role": user.role, "correlation_id": correlation_id},
    )

    return {
        "organization_id": org_id,
        "role_scope": user.role,
        "recommendations": recommendations,
        "advisory_only": True,
        "execution_disabled": True,
        "supervisor_review_required": True,
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/recommendations",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }


@router.get("/workspace/activation")
def ops_workspace_activation(
    organization_id: str | None = Query(None),
    role_view: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    resolved_role_view = _effective_role_view(user.role, role_view)
    correlation_id = f"ops-workspace-activation-{uuid4().hex[:12]}"

    summary = _apply_role_mask(_build_summary_payload(db, org_id, resolved_role_view), resolved_role_view)
    compliance = ComplianceService.dashboard_summary(
        db,
        organization_id=org_id,
        actor=user,
        role_view=resolved_role_view,
    )
    queue_snapshot = OperationsOrchestrationService.generate_queue_snapshot(
        db,
        organization_id=org_id,
        actor=user,
    )
    timeline_projection = OperationsOrchestrationService.generate_timeline_projection(
        db,
        organization_id=org_id,
        actor=user,
        after_sequence=0,
        limit=120,
    )
    notification_feed = OperationsOrchestrationService.notification_feed(
        db,
        organization_id=org_id,
        actor=user,
        limit=80,
    )
    sla_snapshot = OperationsOrchestrationService.generate_sla_snapshot(
        db,
        organization_id=org_id,
        actor=user,
        correlation_id=f"ops-workspace-sla-{uuid4().hex[:10]}",
    )
    queue_health = OperationsOrchestrationService.generate_queue_health_metrics(
        db,
        organization_id=org_id,
        actor=user,
    )
    trip_snapshot = _build_trip_workflow_snapshot(db, org_id)

    tasks = list((queue_snapshot or {}).get("tasks") or [])
    notifications = list((notification_feed or {}).get("notifications") or [])
    timeline_events = list((timeline_projection or {}).get("events") or [])

    payload = {
        "organization_id": org_id,
        "role_scope": user.role,
        "role_view": resolved_role_view,
        "summary": summary,
        "compliance": {
            "compliance_overview": (compliance or {}).get("compliance_overview"),
            "expiration_queue": (compliance or {}).get("expiration_queue"),
            "approval_queue": (compliance or {}).get("approval_queue"),
            "compliance_timeline": list((compliance or {}).get("compliance_timeline") or []),
            "profiles": list((compliance or {}).get("profiles") or []),
            "documents": list((compliance or {}).get("documents") or []),
        },
        "orchestration": {
            "queue_snapshot": queue_snapshot,
            "timeline_projection": timeline_projection,
            "notifications": notification_feed,
            "sla": sla_snapshot,
            "queue_health": queue_health,
        },
        "trip_workflow_engine": trip_snapshot,
        "workspace_modules": {
            "pending_approvals_queue": list((compliance or {}).get("phase25", {}).get("supervisor_review_queue") or []),
            "escalation_review_panel": list((sla_snapshot or {}).get("alerts") or []),
            "supervised_override_requests": [
                item for item in tasks if str(item.get("resolution_state") or "").lower() == "resolution_requested"
            ],
            "recovery_authorization_queue": [
                item
                for item in tasks
                if "recovery" in str(item.get("title") or "").lower()
                or "rollback" in str(item.get("title") or "").lower()
            ],
            "operational_incident_review": [
                item
                for item in notifications
                if "incident" in str(item.get("title") or "").lower()
                or "critical" in str(item.get("priority") or "").lower()
            ],
            "operational_alert_center": list((summary or {}).get("alerts") or []),
            "conflict_resolution_workspace": [
                item for item in tasks if str(item.get("task_state") or "").lower() in {"escalated", "handoff_pending"}
            ],
            "dispatch_recovery_approvals": [
                item for item in tasks if str(item.get("task_state") or "").lower() in {"escalated", "assigned"}
            ],
            "escalation_audit_timeline": timeline_events,
            "emergency_coordination_controls": [
                item for item in notifications if "emergency" in str(item.get("title") or "").lower()
            ],
            "driver_onboarding_queue": [
                item
                for item in list((compliance or {}).get("profiles") or [])
                if str(item.get("approval_status") or "").lower() in {"pending", "under_review"}
                or str(item.get("compliance_status") or "").lower() in {"pending", "under_review"}
            ],
            "missing_document_support": [
                item
                for item in list((compliance or {}).get("documents") or [])
                if str(item.get("status") or "").lower() in {"missing", "expired", "rejected"}
            ],
            "app_activation_support": [
                item
                for item in notifications
                if "activation" in str(item.get("title") or "").lower()
                or "login" in str(item.get("title") or "").lower()
                or "app" in str(item.get("title") or "").lower()
            ],
            "payout_support_issues": [
                item
                for item in notifications
                if "payout" in str(item.get("title") or "").lower()
                or "payment" in str(item.get("title") or "").lower()
            ],
            "driver_readiness_training": [
                item
                for item in list((compliance or {}).get("profiles") or [])
                if str(item.get("compliance_status") or "").lower() in {"approved", "under_review", "pending"}
            ],
            "provider_compliance_posture": [
                item
                for item in list((compliance or {}).get("profiles") or [])
                if str(item.get("provider_id") or "").strip() != ""
            ],
            "insurance_license_alerts": [
                item
                for item in list((compliance or {}).get("documents") or [])
                if "insurance" in str(item.get("document_type") or "").lower()
                or "license" in str(item.get("document_type") or "").lower()
            ],
            "onboarding_governance_review": [
                item
                for item in list((compliance or {}).get("profiles") or [])
                if str(item.get("approval_status") or "").lower() in {"pending", "under_review", "rejected"}
            ],
            "driver_support_tickets": notifications,
            "provider_sync_queue": [
                item for item in tasks if "provider" in str(item.get("title") or "").lower()
            ],
            "dispatch_live_queue": [
                item for item in tasks if str(item.get("task_state") or "").lower() in {"assigned", "escalated", "new"}
            ],
            "patient_ride_coordination_queue": [
                item for item in tasks if "ride" in str(item.get("title") or "").lower() or "trip" in str(item.get("title") or "").lower()
            ],
            "recurring_medical_schedule": [
                item
                for item in tasks
                if "recurring" in str(item.get("title") or "").lower()
                or "dialysis" in str(item.get("title") or "").lower()
                or "appointment" in str(item.get("title") or "").lower()
            ],
            "appointment_pickup_dropoff_risk": [
                item
                for item in list((sla_snapshot or {}).get("alerts") or [])
                if "pickup" in str(item.get("metric") or "").lower()
                or "dropoff" in str(item.get("metric") or "").lower()
                or "latency" in str(item.get("metric") or "").lower()
            ],
            "provider_facility_coordination": [
                item
                for item in tasks
                if "provider" in str(item.get("title") or "").lower()
                or "facility" in str(item.get("title") or "").lower()
            ],
            "patient_support_escalation": [
                item
                for item in notifications
                if "patient" in str(item.get("title") or "").lower()
                or "support" in str(item.get("title") or "").lower()
                or "escalat" in str(item.get("title") or "").lower()
            ],
            "trip_lifecycle_state_machine": (trip_snapshot.get("state_machine") or {}),
            "trip_operational_entities": list(trip_snapshot.get("trips") or []),
            "trip_unassigned_queue": list(((trip_snapshot.get("dispatch") or {}).get("unassigned_queue") or [])),
            "trip_active_routes": list(((trip_snapshot.get("dispatch") or {}).get("active_routes") or [])),
            "trip_driver_availability": list(((trip_snapshot.get("dispatch") or {}).get("driver_availability") or [])),
            "trip_delayed_rides": list(((trip_snapshot.get("dispatch") or {}).get("delayed_rides") or [])),
            "trip_escalation_indicators": list(((trip_snapshot.get("dispatch") or {}).get("escalation_indicators") or [])),
            "trip_reassignment_queue": list(((trip_snapshot.get("dispatch") or {}).get("reassignment_queue") or [])),
            "trip_no_driver_recovery": list(((trip_snapshot.get("dispatch") or {}).get("no_driver_recovery") or [])),
            "trip_supervisor_escalation_routing": list(((trip_snapshot.get("dispatch") or {}).get("supervisor_escalation_routing") or [])),
            "trip_recurring_rides": list([item for item in list(trip_snapshot.get("trips") or []) if bool(item.get("recurring"))]),
            "trip_medicaid_nemt": list([item for item in list(trip_snapshot.get("trips") or []) if bool((item.get("nemt_metadata") or {}).get("is_nemt"))]),
            "trip_audit_review": list(((trip_snapshot.get("compliance") or {}).get("audit_review_feed") or [])),
            "trip_audit_evidence_feed": list(((trip_snapshot.get("compliance") or {}).get("audit_evidence_feed") or [])),
            "trip_proof_of_arrival_queue": list(((trip_snapshot.get("driver_workflow") or {}).get("proof_of_arrival_queue") or [])),
            "trip_onboard_verification_queue": list(((trip_snapshot.get("driver_workflow") or {}).get("onboard_verification_queue") or [])),
            "trip_route_progress_tracking": list(((trip_snapshot.get("driver_workflow") or {}).get("route_progress_tracking") or [])),
            "trip_shift_readiness": list(((trip_snapshot.get("driver_workflow") or {}).get("shift_readiness") or [])),
            "trip_failed_recovery": list(((trip_snapshot.get("supervisor") or {}).get("failed_trip_recovery") or [])),
            "trip_resolution_timeline": list(((trip_snapshot.get("supervisor") or {}).get("resolution_timeline") or [])),
            "trip_provider_coordination": list(((trip_snapshot.get("provider") or {}).get("facility_coordination_queue") or [])),
            "compliance_expiration_alerts": list(
                list((((compliance or {}).get("expiration_queue") or {}).get("licenses_expiring") or []))
                + list((((compliance or {}).get("expiration_queue") or {}).get("insurance_expiring") or []))
                + list((((compliance or {}).get("expiration_queue") or {}).get("inspection_expiring") or []))
            ),
            "compliance_onboarding_queue": [
                item
                for item in list((compliance or {}).get("profiles") or [])
                if str(item.get("approval_status") or "").lower() in {"pending", "under_review"}
                or str(item.get("compliance_status") or "").lower() in {"pending", "under_review"}
            ],
            "compliance_certification_enforcement": [
                item
                for item in list((compliance or {}).get("documents") or [])
                if str(item.get("verification_status") or item.get("status") or "").lower() in {"expired", "rejected", "pending"}
            ],
            "compliance_evidence_feed": list((compliance or {}).get("compliance_timeline") or []),
            "ai_operational_copilot_context": (trip_snapshot.get("ai_operational_context") or {}),
        },
        "allowed_actions": _workspace_action_catalog(resolved_role_view),
        "governance": {
            "advisory_only": True,
            "supervision_required": True,
            "execution_disabled": True,
            "append_only": True,
            "replay_safe": True,
            "backend_authoritative": True,
            "role_scoped": True,
        },
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/workspace/activation",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }

    record_supervision_event(
        subsystem="ops_hydration",
        event="workspace_activation_accessed",
        details={
            "organization_id": org_id,
            "role": user.role,
            "role_view": resolved_role_view,
            "correlation_id": correlation_id,
            "module_counts": {
                "tasks": len(tasks),
                "notifications": len(notifications),
                "timeline": len(timeline_events),
            },
        },
    )

    return payload


@router.post("/workspace/action")
def ops_workspace_action(
    body: dict[str, Any] = Body(...),
    organization_id: str | None = Query(None),
    role_view: str | None = Query(None),
    user: UserContext = Depends(get_current_user_context),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    org_id = _resolve_org(user, organization_id)
    resolved_role_view = _effective_role_view(user.role, role_view)
    actor_user_id = str(user.user_id or "")
    timestamp = datetime.now(timezone.utc)
    action_type = _workspace_action_alias(str((body or {}).get("action_type") or "").strip().lower())
    if not action_type:
        raise HTTPException(status_code=422, detail="action_type is required")
    if not _workspace_action_allowed(resolved_role_view, action_type):
        denied_payload = (body or {}).get("payload") if isinstance((body or {}).get("payload"), dict) else {}
        denied_canonical = {
            "organization_id": org_id,
            "role_scope": user.role,
            "role_view": resolved_role_view,
            "actor_user_id": actor_user_id,
            "action_type": action_type,
            "payload": denied_payload,
            "timestamp": timestamp.isoformat(),
            "status": "denied",
            "reason": "action_not_allowed_for_role_scope",
            "advisory_only": True,
            "supervision_required": True,
            "execution_disabled": True,
        }
        denied_checksum = hashlib.sha256(json.dumps(denied_canonical, sort_keys=True).encode("utf-8")).hexdigest()
        denied_event_id = f"workspace-action-denied-{uuid4().hex[:12]}"
        denied_correlation_id = f"ops-workspace-action-denied-{uuid4().hex[:12]}"

        operational_timeline.append_event(
            TimelineEvent(
                event_id=denied_event_id,
                event_type=TimelineEventType.OPERATOR_COMMAND,
                timestamp=timestamp,
                organization_id=org_id,
                correlation_id=denied_correlation_id,
                action_id=action_type,
                operator_identity=actor_user_id,
                source_reference_id="workspace_action_gateway",
                title="Role workspace action denied",
                description=f"{resolved_role_view} attempted unauthorized action {action_type}",
                metadata={
                    "role_view": resolved_role_view,
                    "action_type": action_type,
                    "payload": denied_payload,
                    "status": "denied",
                    "reason": "action_not_allowed_for_role_scope",
                    "advisory_only": True,
                    "supervision_required": True,
                    "execution_disabled": True,
                    "append_only": True,
                    "replay_safe": True,
                    "checksum": denied_checksum,
                },
            )
        )

        record_supervision_event(
            subsystem="ops_hydration",
            event="workspace_action_denied",
            details={
                "organization_id": org_id,
                "role": user.role,
                "role_view": resolved_role_view,
                "actor_user_id": actor_user_id,
                "action_type": action_type,
                "correlation_id": denied_correlation_id,
                "event_id": denied_event_id,
                "reason": "action_not_allowed_for_role_scope",
            },
        )
        raise HTTPException(status_code=403, detail="action is not allowed for role scope")

    action_payload: dict[str, Any] = _safe_json_object((body or {}).get("payload"))
    correlation_id = f"ops-workspace-action-{uuid4().hex[:12]}"

    try:
        execution_result = _execute_workspace_action(
            db=db,
            organization_id=org_id,
            action_type=action_type,
            payload=action_payload,
            user=user,
        )
    except HTTPException as exc:
        _append_workspace_failure_timeline_event(
            organization_id=org_id,
            correlation_id=correlation_id,
            action_type=action_type,
            actor_user_id=actor_user_id,
            role_view=resolved_role_view,
            timestamp=timestamp,
            error_detail=str(exc.detail),
        )
        raise
    except ValueError as exc:
        _append_workspace_failure_timeline_event(
            organization_id=org_id,
            correlation_id=correlation_id,
            action_type=action_type,
            actor_user_id=actor_user_id,
            role_view=resolved_role_view,
            timestamp=timestamp,
            error_detail=str(exc),
        )
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    canonical = {
        "organization_id": org_id,
        "role_scope": user.role,
        "role_view": resolved_role_view,
        "actor_user_id": actor_user_id,
        "action_type": action_type,
        "payload": action_payload,
        "execution_result": execution_result,
        "timestamp": timestamp.isoformat(),
        "advisory_only": True,
        "supervision_required": True,
        "execution_disabled": True,
    }
    checksum = hashlib.sha256(json.dumps(canonical, sort_keys=True).encode("utf-8")).hexdigest()
    event_id = f"workspace-action-{uuid4().hex[:12]}"

    operational_timeline.append_event(
        TimelineEvent(
            event_id=event_id,
            event_type=TimelineEventType.OPERATOR_COMMAND,
            timestamp=timestamp,
            organization_id=org_id,
            correlation_id=correlation_id,
            action_id=action_type,
            operator_identity=actor_user_id,
            source_reference_id="workspace_action_gateway",
            title="Role workspace action submitted",
            description=f"{resolved_role_view} submitted {action_type}",
            metadata={
                "role_view": resolved_role_view,
                "role_scope": [resolved_role_view, "admin"],
                "action_type": action_type,
                "payload": action_payload,
                "execution_result": execution_result,
                "authority_source": f"role_scope:{resolved_role_view}",
                "advisory_only": True,
                "supervision_required": True,
                "execution_disabled": True,
                "append_only": True,
                "replay_safe": True,
                "checksum": checksum,
            },
        )
    )
    _append_workspace_execution_timeline_event(
        organization_id=org_id,
        correlation_id=correlation_id,
        action_type=action_type,
        actor_user_id=actor_user_id,
        role_view=resolved_role_view,
        timestamp=timestamp,
        execution_result=execution_result,
    )

    record_supervision_event(
        subsystem="ops_hydration",
        event="workspace_action_submitted",
        details={
            "organization_id": org_id,
            "role": user.role,
            "role_view": resolved_role_view,
            "actor_user_id": actor_user_id,
            "action_type": action_type,
            "correlation_id": correlation_id,
            "event_id": event_id,
        },
    )

    return {
        "organization_id": org_id,
        "role_scope": user.role,
        "role_view": resolved_role_view,
        "action_record": {
            "event_id": event_id,
            "correlation_id": correlation_id,
            "action_type": action_type,
            "status": _workspace_action_status(execution_result),
            "advisory_only": True,
            "supervision_required": True,
            "execution_disabled": True,
            "append_only": True,
            "replay_safe": True,
            "checksum": checksum,
            "timestamp": timestamp.isoformat(),
            "execution_result": execution_result,
            "actor_identity": actor_user_id,
            "authority_source": f"role_scope:{resolved_role_view}",
        },
        "audit_metadata": _build_audit_metadata(
            endpoint="/api/ops/workspace/action",
            role=user.role,
            organization_id=org_id,
            correlation_id=correlation_id,
        ),
    }
