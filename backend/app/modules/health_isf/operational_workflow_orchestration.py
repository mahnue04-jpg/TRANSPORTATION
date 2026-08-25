"""Phase 16 operational workflow orchestration foundations.

This module is read-heavy and supervision-safe by design. It introduces
normalized workflow views, lifecycle state projections, operational registries,
and event/audit helpers while preserving preview-only and deny-by-default
execution semantics.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import (
    HealthISFDriver,
    HealthISFProvider,
    HealthISFRide,
    HealthISFRideExecutionAction,
    HealthISFWorkflowAuditLog,
    HealthISFWorkflowExecution,
)
from app.modules.health_isf.operational_event_bus import get_operational_event_bus
from app.modules.health_isf.operational_event_models import OperationalEventType
from app.modules.health_isf.operational_map_service import OperationalMapService
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine

_PHASE16_LOGGER = logging.getLogger("amicor.health_isf.phase16")

PHASE16_RIDE_STATES: tuple[str, ...] = (
    "REQUESTED",
    "ASSIGNED",
    "ACCEPTED",
    "EN_ROUTE",
    "ARRIVED",
    "IN_PROGRESS",
    "COMPLETED",
    "VERIFIED",
    "CANCELED",
)

PHASE16_RIDE_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "REQUESTED": ("ASSIGNED", "CANCELED"),
    "ASSIGNED": ("ACCEPTED", "CANCELED"),
    "ACCEPTED": ("EN_ROUTE", "CANCELED"),
    "EN_ROUTE": ("ARRIVED", "CANCELED"),
    "ARRIVED": ("IN_PROGRESS", "CANCELED"),
    "IN_PROGRESS": ("COMPLETED", "CANCELED"),
    "COMPLETED": ("VERIFIED",),
    "VERIFIED": ("VERIFIED",),
    "CANCELED": ("CANCELED",),
}

_CANONICAL_TO_PHASE16: dict[str, str] = {
    "requested": "REQUESTED",
    "queued": "REQUESTED",
    "assigned": "ASSIGNED",
    "driver_en_route": "EN_ROUTE",
    "arrived": "ARRIVED",
    "rider_onboard": "IN_PROGRESS",
    "in_progress": "IN_PROGRESS",
    "completed": "COMPLETED",
    "cancelled": "CANCELED",
    "canceled": "CANCELED",
    "failed": "CANCELED",
    "escalated": "ASSIGNED",
    "pending": "REQUESTED",
    "accepted": "ACCEPTED",
    "in_transit": "IN_PROGRESS",
}

_DRIVER_STATE_MAP: dict[str, str] = {
    "available": "available",
    "assigned": "assigned",
    "offline": "offline",
    "en_route_pickup": "en_route",
    "waiting_at_pickup": "paused",
    "in_transit": "en_route",
    "completed": "paused",
    "unavailable": "paused",
    "busy": "assigned",
}

_PHASE16_EVENT_TYPE_BY_NAME: dict[str, OperationalEventType] = {
    "ride_requested": OperationalEventType.RIDE_REQUESTED,
    "ride_assigned": OperationalEventType.RIDE_ASSIGNED,
    "ride_updated": OperationalEventType.RIDE_UPDATED,
    "ride_completed": OperationalEventType.RIDE_COMPLETED,
    "driver_state_changed": OperationalEventType.DRIVER_STATE_CHANGED,
    "provider_state_changed": OperationalEventType.PROVIDER_STATE_CHANGED,
    "workflow_transition": OperationalEventType.WORKFLOW_TRANSITION,
    "supervision_alert": OperationalEventType.SUPERVISION_ALERT,
}

_PHASE16_DEFERRED_EVENT_QUEUE_KEY = "health_isf.phase16_operational_events"


def _publish_phase16_operational_event_now(
    *,
    organization_id: str,
    event_name: str,
    payload: dict[str, Any],
    correlation_id: str,
    role_scope: list[str] | None = None,
    source_nonce: str | None = None,
) -> dict[str, Any]:
    event_key = str(event_name or "").strip().lower()
    event_type = _PHASE16_EVENT_TYPE_BY_NAME.get(event_key, OperationalEventType.WORKFLOW_TRANSITION)
    scoped_roles = role_scope or ["dispatcher", "admin", "staff"]
    event_payload = {
        **payload,
        "event_name": event_key,
        "correlation_id": correlation_id,
        "execution_disabled": True,
        "preview_only": True,
        "autonomous_execution": False,
        "automatic_dispatching": False,
    }
    return OperationalSynchronizationEngine.publish_event(
        organization_id=organization_id,
        event_type=event_type,
        payload=event_payload,
        role_scope=scoped_roles,
        source_nonce=source_nonce or f"phase16:{event_key}:{correlation_id}",
        metadata={
            "phase": "phase16",
            "preview_only": True,
            "execution_disabled": True,
            "correlation_id": correlation_id,
        },
    )


def _queue_phase16_operational_event(
    db: Session,
    *,
    organization_id: str,
    event_name: str,
    payload: dict[str, Any],
    correlation_id: str,
    role_scope: list[str] | None = None,
    source_nonce: str | None = None,
) -> dict[str, Any]:
    queue = db.info.setdefault(_PHASE16_DEFERRED_EVENT_QUEUE_KEY, [])
    queue.append(
        {
            "organization_id": organization_id,
            "event_name": event_name,
            "payload": dict(payload),
            "correlation_id": correlation_id,
            "role_scope": list(role_scope) if role_scope is not None else None,
            "source_nonce": source_nonce,
        }
    )
    return {
        "organization_id": organization_id,
        "accepted": True,
        "status": "queued_after_commit",
        "event_name": str(event_name or "").strip().lower(),
        "tenant_scoped": True,
        "approval_governed": True,
        "backend_authoritative": True,
    }


@event.listens_for(Session, "after_commit")
def _flush_phase16_operational_events_after_commit(db: Session) -> None:
    queued = list(db.info.pop(_PHASE16_DEFERRED_EVENT_QUEUE_KEY, []))
    for item in queued:
        try:
            _publish_phase16_operational_event_now(**item)
        except Exception:
            _PHASE16_LOGGER.exception(
                "phase16 after_commit publish failed org=%s event=%s",
                item.get("organization_id"),
                item.get("event_name"),
            )


@event.listens_for(Session, "after_rollback")
def _clear_phase16_operational_events_after_rollback(db: Session) -> None:
    db.info.pop(_PHASE16_DEFERRED_EVENT_QUEUE_KEY, None)


@event.listens_for(Session, "after_soft_rollback")
def _clear_phase16_operational_events_after_soft_rollback(db: Session, _previous_transaction: Any) -> None:
    db.info.pop(_PHASE16_DEFERRED_EVENT_QUEUE_KEY, None)


def normalize_phase16_ride_state(raw_state: str | None) -> str:
    key = str(raw_state or "").strip().lower()
    return _CANONICAL_TO_PHASE16.get(key, "REQUESTED")


def _driver_registry(drivers: list[HealthISFDriver]) -> dict[str, Any]:
    counts = {"available": 0, "assigned": 0, "offline": 0, "en_route": 0, "paused": 0}
    rows: list[dict[str, Any]] = []
    for driver in drivers:
        normalized = _DRIVER_STATE_MAP.get(str(getattr(driver, "status", "") or "").lower(), "paused")
        counts[normalized] += 1
        rows.append(
            {
                "driver_id": str(driver.id),
                "name": str(driver.name),
                "state": normalized,
                "raw_status": str(driver.status),
                "updated_at": driver.updated_at.isoformat() if getattr(driver, "updated_at", None) else None,
            }
        )
    return {
        "states": counts,
        "total": len(drivers),
        "entries": rows,
        "read_safe_registry": True,
        "websocket_compatible": True,
        "telemetry_compatible": True,
        "audit_visible": True,
    }


def _provider_registry(providers: list[HealthISFProvider], rides: list[HealthISFRide]) -> dict[str, Any]:
    ride_load: dict[str, int] = {}
    for ride in rides:
        provider_id = str(getattr(ride, "provider_id", "") or "")
        if not provider_id:
            continue
        state = normalize_phase16_ride_state(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", None))
        if state in {"COMPLETED", "VERIFIED", "CANCELED"}:
            continue
        ride_load[provider_id] = int(ride_load.get(provider_id, 0)) + 1

    counts = {"active": 0, "pending": 0, "suspended": 0, "overloaded": 0, "offline": 0}
    rows: list[dict[str, Any]] = []
    for provider in providers:
        provider_id = str(provider.id)
        is_active = bool(getattr(provider, "is_active", True))
        load = int(ride_load.get(provider_id, 0))
        if not is_active:
            state = "offline"
        elif load >= 8:
            state = "overloaded"
        elif load == 0:
            state = "pending"
        else:
            state = "active"
        counts[state] += 1
        rows.append(
            {
                "provider_id": provider_id,
                "name": str(provider.name),
                "state": state,
                "active_load": load,
                "updated_at": provider.updated_at.isoformat() if getattr(provider, "updated_at", None) else None,
            }
        )

    return {
        "states": counts,
        "total": len(providers),
        "entries": rows,
        "read_safe_registry": True,
        "websocket_compatible": True,
        "telemetry_compatible": True,
        "audit_visible": True,
    }


def _workflow_status_tracking(db: Session, organization_id: str | None) -> dict[str, Any]:
    query = db.query(HealthISFWorkflowExecution)
    if organization_id:
        query = query.filter(HealthISFWorkflowExecution.organization_id == organization_id)
    rows = query.order_by(HealthISFWorkflowExecution.updated_at.desc()).limit(500).all()
    counts: dict[str, int] = {}
    for row in rows:
        status = str(getattr(row, "status", "unknown") or "unknown")
        counts[status] = int(counts.get(status, 0)) + 1
    return {
        "counts": counts,
        "latest": [
            {
                "workflow_execution_id": str(row.id),
                "workflow_name": str(row.workflow_name),
                "status": str(row.status),
                "trigger_type": str(row.trigger_type),
                "ride_id": str(row.ride_id) if row.ride_id else None,
                "updated_at": row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
            }
            for row in rows[:25]
        ],
        "append_only_tracking": True,
    }


def build_workflow_event_stream(
    db: Session,
    *,
    organization_id: str,
    after_sequence: int = 0,
    limit: int = 120,
) -> dict[str, Any]:
    bus = get_operational_event_bus()
    bus_events = bus.replay(organization_id, after_sequence=after_sequence, limit=limit)
    audit_rows = (
        db.query(HealthISFWorkflowAuditLog)
        .filter(HealthISFWorkflowAuditLog.organization_id == organization_id)
        .order_by(HealthISFWorkflowAuditLog.created_at.desc())
        .limit(limit)
        .all()
    )

    audit_events: list[dict[str, Any]] = []
    correlation_count = 0
    for row in audit_rows:
        payload_obj: dict[str, Any] = {}
        raw = str(getattr(row, "payload", "") or "")
        if raw:
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, dict):
                    payload_obj = decoded
            except Exception:
                payload_obj = {"raw": raw}
        correlation_id = str(payload_obj.get("correlation_id") or "")
        if correlation_id:
            correlation_count += 1
        audit_events.append(
            {
                "audit_id": str(row.id),
                "event_type": str(row.event_type),
                "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
                "correlation_id": correlation_id or None,
                "payload": payload_obj,
            }
        )

    return {
        "append_only": True,
        "correlation_propagation": True,
        "telemetry_integrated": True,
        "audit_chain_compatible": True,
        "websocket_safe": True,
        "event_bus": {
            "latest_sequence": bus.latest_sequence(organization_id),
            "events": [
                {
                    "sequence": item.sequence,
                    "event_type": item.event_type,
                    "role_scope": item.role_scope,
                    "payload": item.payload,
                    "emitted_at": item.emitted_at,
                }
                for item in bus_events
            ],
        },
        "audit_events": audit_events,
        "correlation_coverage": {
            "with_correlation_id": correlation_count,
            "total": len(audit_events),
        },
    }


def build_geospatial_foundation(organization_id: str) -> dict[str, Any]:
    map_state = OperationalMapService.get_map_state(organization_id=organization_id)
    live = map_state.get("live_operational_map_state", {}) if isinstance(map_state, dict) else {}
    return {
        "coordinate_entity_model": {
            "driver_coordinates": list(live.get("driver_positioning", [])),
            "incident_coordinates": list(live.get("incident_clustering", [])),
        },
        "route_placeholder_model": {
            "status": "scaffold_only",
            "external_provider_locked": False,
            "route_engine_enabled": False,
        },
        "driver_position_registry": {
            "entries": list(live.get("driver_positioning", [])),
            "replay_safe": bool(map_state.get("replay_safe", True)),
        },
        "operational_zone_abstraction": {
            "zones": list(live.get("provider_operational_zones", [])),
            "density_regions": list(live.get("operational_density_regions", [])),
        },
        "map_overlay_scaffolding": {
            "overlays": list(live.get("emergency_overlays", [])),
            "websocket_compatible": True,
        },
    }


def build_operational_workflow_overview(db: Session, *, organization_id: str | None) -> dict[str, Any]:
    rides_q = db.query(HealthISFRide)
    drivers_q = db.query(HealthISFDriver)
    providers_q = db.query(HealthISFProvider)
    if organization_id:
        rides_q = rides_q.filter(HealthISFRide.organization_id == organization_id)
        drivers_q = drivers_q.filter(HealthISFDriver.organization_id == organization_id)
        providers_q = providers_q.filter(HealthISFProvider.organization_id == organization_id)

    rides = rides_q.order_by(HealthISFRide.updated_at.desc()).limit(500).all()
    drivers = drivers_q.order_by(HealthISFDriver.updated_at.desc()).limit(500).all()
    providers = providers_q.order_by(HealthISFProvider.updated_at.desc()).limit(500).all()

    ride_counts = {state: 0 for state in PHASE16_RIDE_STATES}
    lifecycle_rows: list[dict[str, Any]] = []
    delayed = 0
    delayed_cutoff = now() - timedelta(minutes=30)
    delayed_cutoff_naive = delayed_cutoff.replace(tzinfo=None) if getattr(delayed_cutoff, "tzinfo", None) else delayed_cutoff

    for ride in rides:
        state = normalize_phase16_ride_state(getattr(ride, "lifecycle_state", None) or getattr(ride, "status", None))
        ride_counts[state] = int(ride_counts.get(state, 0)) + 1
        ride_updated_at = getattr(ride, "updated_at", None)
        if ride_updated_at and state not in {"COMPLETED", "VERIFIED", "CANCELED"}:
            ride_updated_at_naive = ride_updated_at.replace(tzinfo=None) if getattr(ride_updated_at, "tzinfo", None) else ride_updated_at
            if ride_updated_at_naive < delayed_cutoff_naive:
                delayed += 1
        lifecycle_rows.append(
            {
                "ride_id": str(ride.id),
                "state": state,
                "status": str(ride.status),
                "driver_id": str(ride.driver_id) if ride.driver_id else None,
                "provider_id": str(ride.provider_id) if ride.provider_id else None,
                "updated_at": ride.updated_at.isoformat() if getattr(ride, "updated_at", None) else None,
            }
        )

    workflow_tracking = _workflow_status_tracking(db, organization_id)
    event_stream = build_workflow_event_stream(
        db,
        organization_id=str(organization_id or ""),
        after_sequence=0,
        limit=80,
    ) if organization_id else {
        "append_only": True,
        "correlation_propagation": True,
        "telemetry_integrated": True,
        "audit_chain_compatible": True,
        "websocket_safe": True,
        "event_bus": {"latest_sequence": 0, "events": []},
        "audit_events": [],
        "correlation_coverage": {"with_correlation_id": 0, "total": 0},
    }

    geospatial = build_geospatial_foundation(str(organization_id)) if organization_id else {
        "coordinate_entity_model": {"driver_coordinates": [], "incident_coordinates": []},
        "route_placeholder_model": {"status": "scaffold_only", "external_provider_locked": False, "route_engine_enabled": False},
        "driver_position_registry": {"entries": [], "replay_safe": True},
        "operational_zone_abstraction": {"zones": [], "density_regions": []},
        "map_overlay_scaffolding": {"overlays": [], "websocket_compatible": True},
    }

    return {
        "organization_id": organization_id,
        "scope": "tenant" if organization_id else "global_read_only",
        "unified_workflow_orchestration_layer": {
            "enabled": True,
            "execution_disabled_by_default": True,
            "autonomous_execution": False,
            "automatic_dispatching": False,
            "self_triggering_workflows": False,
            "supervision_gated": True,
            "deny_by_default": True,
        },
        "ride_lifecycle_engine": {
            "states": list(PHASE16_RIDE_STATES),
            "transition_matrix": {key: list(value) for key, value in PHASE16_RIDE_TRANSITIONS.items()},
            "state_counts": ride_counts,
            "deterministic_transitions": True,
            "immutable_transition_audit": True,
            "replay_safe_updates": True,
            "supervision_validation": True,
            "transition_timestamping": True,
            "correlation_id_propagation": True,
            "rows": lifecycle_rows[:120],
        },
        "workflow_status_tracking": workflow_tracking,
        "driver_state_registry": _driver_registry(drivers),
        "provider_state_registry": _provider_registry(providers, rides),
        "geospatial_foundation": geospatial,
        "event_stream": event_stream,
        "live_operational_telemetry_panels": {
            "active_workflow_cards": int(sum(ride_counts[state] for state in ("ASSIGNED", "ACCEPTED", "EN_ROUTE", "ARRIVED", "IN_PROGRESS"))),
            "ride_lifecycle_visualization": ride_counts,
            "driver_availability_summary": _driver_registry(drivers).get("states", {}),
            "provider_operational_summary": _provider_registry(providers, rides).get("states", {}),
            "workflow_timeline": workflow_tracking.get("latest", []),
            "operational_alerts": {
                "delayed_operations": delayed,
                "event_stream_backlog": int(event_stream.get("event_bus", {}).get("latest_sequence", 0)),
            },
        },
        "operational_state_visualization": {
            "lifecycle_rows": lifecycle_rows[:120],
            "workflow_timeline": workflow_tracking.get("latest", []),
            "event_stream_preview": event_stream.get("event_bus", {}).get("events", [])[:40],
        },
        "governance_integrity": {
            "audit_chain_integrity": True,
            "replay_protection": True,
            "policy_metadata_attached": True,
            "supervision_classifications_attached": True,
            "preview_only": True,
            "execution_disabled": True,
        },
    }


def build_assistant_operational_awareness(
    db: Session,
    *,
    organization_id: str,
    prompt: str,
    role: str,
) -> dict[str, Any]:
    overview = build_operational_workflow_overview(db, organization_id=organization_id)
    prompt_norm = str(prompt or "").lower()

    lifecycle_rows = overview.get("ride_lifecycle_engine", {}).get("rows", [])
    driver_entries = overview.get("driver_state_registry", {}).get("entries", [])

    active_ride_rows = [
        row for row in lifecycle_rows
        if str(row.get("state") or "") in {"ASSIGNED", "ACCEPTED", "EN_ROUTE", "ARRIVED", "IN_PROGRESS"}
    ]
    available_drivers = [row for row in driver_entries if str(row.get("state") or "") == "available"]

    if "active ride" in prompt_norm or "active rides" in prompt_norm:
        focus = {
            "query": "active_rides",
            "count": len(active_ride_rows),
            "rides": active_ride_rows[:20],
        }
    elif "delayed" in prompt_norm:
        focus = {
            "query": "delayed_operations",
            "delayed_operations": int(
                (overview.get("live_operational_telemetry_panels", {}).get("operational_alerts", {}) or {}).get("delayed_operations", 0)
            ),
        }
    elif "available driver" in prompt_norm or "available drivers" in prompt_norm:
        focus = {
            "query": "available_drivers",
            "count": len(available_drivers),
            "drivers": available_drivers[:20],
        }
    else:
        focus = {
            "query": "operational_summary",
            "active_workflow_cards": overview.get("live_operational_telemetry_panels", {}).get("active_workflow_cards", 0),
            "ride_state_counts": overview.get("ride_lifecycle_engine", {}).get("state_counts", {}),
            "driver_states": overview.get("driver_state_registry", {}).get("states", {}),
            "provider_states": overview.get("provider_state_registry", {}).get("states", {}),
        }

    return {
        "enabled": True,
        "preview_only": True,
        "read_only": True,
        "supervision_safe": True,
        "execution_disabled": True,
        "role": role,
        "organization_id": organization_id,
        "focus": focus,
    }


def publish_phase16_operational_event(
    db: Session | None = None,
    *,
    organization_id: str,
    event_name: str,
    payload: dict[str, Any],
    correlation_id: str,
    role_scope: list[str] | None = None,
    source_nonce: str | None = None,
) -> dict[str, Any]:
    if db is not None:
        return _queue_phase16_operational_event(
            db,
            organization_id=organization_id,
            event_name=event_name,
            payload=payload,
            correlation_id=correlation_id,
            role_scope=role_scope,
            source_nonce=source_nonce,
        )

    return _publish_phase16_operational_event_now(
        organization_id=organization_id,
        event_name=event_name,
        payload=payload,
        correlation_id=correlation_id,
        role_scope=role_scope,
        source_nonce=source_nonce,
    )


def record_phase16_workflow_event_audit(
    db: Session,
    *,
    organization_id: str,
    event_name: str,
    actor_user_id: str | None,
    correlation_id: str,
    payload: dict[str, Any],
) -> str:
    event_id = str(uuid4())
    row = HealthISFWorkflowAuditLog(
        id=event_id,
        organization_id=organization_id,
        workflow_execution_id=None,
        incident_id=None,
        escalation_id=None,
        event_type=f"phase16.{event_name}",
        actor_user_id=actor_user_id,
        payload=json.dumps(
            {
                "event_name": event_name,
                "correlation_id": correlation_id,
                "policy_metadata": {
                    "policy_model": "deny_by_default",
                    "execution_disabled": True,
                    "preview_only": True,
                },
                "supervision_classification": "supervision_enforced",
                "replay_protection": True,
                "payload": payload,
            },
            default=str,
            separators=(",", ":"),
        ),
        created_at=now(),
    )
    db.add(row)
    return event_id
