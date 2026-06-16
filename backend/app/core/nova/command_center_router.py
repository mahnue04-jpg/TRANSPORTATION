"""
PHASE 7A: Operational Command Center Router
REST API endpoints for live operational command center.
"""

from fastapi import APIRouter, Query, HTTPException, Depends
from typing import Optional, Dict, Any
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

from app.core.nova.operational_dashboard import (
    operational_dashboard,
    OperationalCategory,
    OperationalSeverity,
    DashboardEvent,
)
from app.core.nova.execution_command import (
    execution_command_manager,
    CommandType,
    OperatorCommand,
)
from app.core.nova.operational_timeline import (
    operational_timeline,
    TimelineEventType,
    TimelineEvent,
)
from app.core.nova.health_monitoring import health_monitor
from app.core.nova.event_priority import event_priority_engine
from app.core.nova.operational_metrics import operational_metrics
from app.core.nova.router import _resolve_org


require_nova_actions = require_any_role(
    ROLE_ADMIN,
    ROLE_SUPER_ADMIN_SUPPORT,
    ROLE_DISPATCHER,
    ROLE_STAFF,
    ROLE_ANALYTICS_READONLY,
)

router = APIRouter(
    prefix="/api/nova/command-center",
    tags=["nova-command-center"],
)


# ============================================================================
# OPERATIONAL DASHBOARD ENDPOINTS
# ============================================================================


@router.get("/dashboard/snapshot")
async def get_dashboard_snapshot(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get complete operational dashboard snapshot.
    
    Returns:
        - Active incidents
        - Execution queue
        - Pending approvals
        - Failed actions
        - Rollback events
        - Staffing alerts
        - Deployment warnings
        - Provider disruptions
        - Dispatch escalations
        - Health summary
    """
    org_id = _resolve_org(user, organization_id)

    # Build health context
    health_snapshot = health_monitor.build_snapshot(org_id)

    # Build dashboard snapshot
    dashboard_snapshot = operational_dashboard.build_snapshot(
        org_id,
        include_health={
            "websocket": health_snapshot.websocket_health,
            "runtime": health_snapshot.runtime_health,
            "memory": health_snapshot.memory_health,
        },
    )

    return dashboard_snapshot.to_dict()


@router.get("/dashboard/events")
async def get_dashboard_events(
    organization_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get filtered dashboard events.
    
    Query parameters:
        - category: Filter by category (e.g., "active_incident")
        - severity: Filter by severity (e.g., "critical")
        - limit: Max events to return
    """
    org_id = _resolve_org(user, organization_id)

    events = []

    if category:
        try:
            cat = OperationalCategory(category)
            events = operational_dashboard.get_events_by_category(org_id, cat)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid category: {category}")

    elif severity:
        try:
            sev = OperationalSeverity(severity)
            events = operational_dashboard.get_events_by_severity(org_id, sev)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid severity: {severity}")
    else:
        # Get unacknowledged events requiring attention
        events = operational_dashboard.get_unacknowledged_events(org_id)

    return {
        "organization_id": org_id,
        "total_events": len(events),
        "events": [e.to_dict() for e in events[:limit]],
    }


@router.post("/dashboard/acknowledge/{event_id}")
async def acknowledge_dashboard_event(
    event_id: str,
    organization_id: Optional[str] = Query(None),
    reason: str = Query(""),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Acknowledge dashboard event as operator."""
    org_id = _resolve_org(user, organization_id)
    operator_identity = f"{user.user_id}:{user.role}"

    event = operational_dashboard.acknowledge_event(event_id, operator_identity)

    if not event:
        raise HTTPException(status_code=404, detail="Event not found")

    return {
        "status": "acknowledged",
        "event": event.to_dict(),
    }


# ============================================================================
# EXECUTION COMMAND PANEL ENDPOINTS
# ============================================================================


@router.get("/execution/{action_id}")
async def get_execution_command_panel(
    action_id: str,
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get execution command panel for action."""
    org_id = _resolve_org(user, organization_id)

    # Get commands issued for this action
    commands = execution_command_manager.get_action_commands(action_id)

    return {
        "action_id": action_id,
        "organization_id": org_id,
        "commands": [c.to_dict() for c in commands],
    }


@router.post("/commands/issue")
async def issue_operator_command(
    command_data: Dict[str, Any],
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Issue operator command.
    
    Body parameters:
        - command_type: Type of command (approve_execution, reject_execution, etc.)
        - target_action_id: Action being controlled
        - reason: Command reason
        - metadata: Additional context
    """
    org_id = _resolve_org(user, organization_id)
    operator_identity = f"{user.user_id}:{user.role}"

    try:
        command_type = CommandType(command_data.get("command_type", ""))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid command_type: {command_data.get('command_type')}",
        )

    # Create command
    import uuid
    command = OperatorCommand(
        command_id=str(uuid.uuid4()),
        command_type=command_type,
        organization_id=org_id,
        operator_identity=operator_identity,
        target_action_id=command_data.get("target_action_id"),
        target_alert_id=command_data.get("target_alert_id"),
        reason=command_data.get("reason", ""),
        metadata=command_data.get("metadata", {}),
    )

    # Issue command
    execution_command_manager.issue_command(command)

    return {
        "status": "issued",
        "command": command.to_dict(),
    }


@router.get("/commands/audit-trail")
async def get_command_audit_trail(
    organization_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get operator command audit trail."""
    org_id = _resolve_org(user, organization_id)

    commands = execution_command_manager.get_command_audit_trail(org_id, limit=limit)

    return {
        "organization_id": org_id,
        "total_commands": len(commands),
        "commands": [c.to_dict() for c in commands],
    }


# ============================================================================
# OPERATIONAL TIMELINE ENDPOINTS
# ============================================================================


@router.get("/timeline/snapshot")
async def get_operational_timeline_snapshot(
    organization_id: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get operational timeline snapshot."""
    org_id = _resolve_org(user, organization_id)

    return operational_timeline.get_timeline_snapshot(org_id, limit=limit)


@router.get("/timeline/by-type")
async def get_timeline_by_type(
    organization_id: Optional[str] = Query(None),
    event_type: str = Query(...),
    limit: int = Query(100, ge=1, le=500),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get timeline events by type."""
    org_id = _resolve_org(user, organization_id)

    try:
        timeline_type = TimelineEventType(event_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid event_type: {event_type}")

    events = operational_timeline.get_events_by_organization_and_type(
        org_id, timeline_type, limit=limit
    )

    return {
        "organization_id": org_id,
        "event_type": event_type,
        "total_events": len(events),
        "events": [e.to_dict() for e in events],
    }


@router.get("/timeline/statistics")
async def get_timeline_statistics(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get timeline event statistics."""
    org_id = _resolve_org(user, organization_id)

    counts = operational_timeline.count_events_by_type(org_id)

    return {
        "organization_id": org_id,
        "event_type_counts": counts,
        "sequence_counter": operational_timeline._sequence_counter,
    }


# ============================================================================
# HEALTH MONITORING ENDPOINTS
# ============================================================================


@router.get("/health/snapshot")
async def get_health_snapshot(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get runtime health snapshot."""
    org_id = _resolve_org(user, organization_id)

    snapshot = health_monitor.build_snapshot(org_id)
    return snapshot.to_dict()


@router.get("/health/metrics/{metric_name}")
async def get_health_metric_history(
    metric_name: str,
    organization_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get history of specific health metric."""
    org_id = _resolve_org(user, organization_id)

    history = health_monitor.get_metric_history(org_id, metric_name)

    return {
        "organization_id": org_id,
        "metric_name": metric_name,
        "total_values": len(history),
        "values": [m.to_dict() for m in history[-limit:]],
    }


# ============================================================================
# EVENT PRIORITY ENDPOINTS
# ============================================================================


@router.post("/priority/evaluate")
async def evaluate_event_priority(
    event_data: Dict[str, Any],
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Evaluate priority of event based on type and context.
    
    Body parameters:
        - event_type: Type of event
        - context: Additional context (optional)
    """
    org_id = _resolve_org(user, organization_id)

    event_type = event_data.get("event_type", "")
    context = event_data.get("context", {})

    priority = event_priority_engine.get_event_priority(event_type, context)

    return {
        "organization_id": org_id,
        "event_type": event_type,
        "priority": priority.value,
        "should_trigger_recommendation": (
            event_priority_engine.should_trigger_recommendation(event_type, context)
        ),
        "should_surface_in_dashboard": (
            event_priority_engine.should_surface_in_dashboard(event_type, context)
        ),
        "should_require_operator_action": (
            event_priority_engine.should_require_operator_action(event_type, context)
        ),
    }


@router.get("/priority/breakdown")
async def get_priority_breakdown(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get breakdown of all event types by priority."""
    org_id = _resolve_org(user, organization_id)

    breakdown = event_priority_engine.get_priority_breakdown()

    return {
        "organization_id": org_id,
        "breakdown": {k.value: v for k, v in breakdown.items()},
    }


# ============================================================================
# OPERATIONAL METRICS ENDPOINTS
# ============================================================================


@router.get("/metrics/snapshot")
async def get_operational_metrics_snapshot(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get operational metrics snapshot."""
    org_id = _resolve_org(user, organization_id)

    snapshot = operational_metrics.build_snapshot(org_id)
    return snapshot.to_dict()


@router.post("/metrics/record-execution-latency")
async def record_execution_latency(
    latency_data: Dict[str, Any],
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Record execution latency metric.
    
    Body parameters:
        - latency_ms: Latency in milliseconds
    """
    org_id = _resolve_org(user, organization_id)

    latency_ms = latency_data.get("latency_ms", 0)
    operational_metrics.record_execution_latency(org_id, latency_ms)

    return {
        "status": "recorded",
        "organization_id": org_id,
        "latency_ms": latency_ms,
    }


@router.post("/metrics/record-approval-latency")
async def record_approval_latency(
    latency_data: Dict[str, Any],
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Record approval latency metric.
    
    Body parameters:
        - latency_seconds: Latency in seconds
    """
    org_id = _resolve_org(user, organization_id)

    latency_seconds = latency_data.get("latency_seconds", 0)
    operational_metrics.record_approval_latency(org_id, latency_seconds)

    return {
        "status": "recorded",
        "organization_id": org_id,
        "latency_seconds": latency_seconds,
    }


# ============================================================================
# COMMAND CENTER SUMMARY ENDPOINT
# ============================================================================


@router.get("/summary")
async def get_command_center_summary(
    organization_id: Optional[str] = Query(None),
    user: UserContext = Depends(get_current_user_context),
) -> Dict[str, Any]:
    """Get complete command center summary."""
    org_id = _resolve_org(user, organization_id)

    # Gather all summaries
    dashboard = operational_dashboard.build_snapshot(org_id)
    health = health_monitor.build_snapshot(org_id)
    metrics = operational_metrics.build_snapshot(org_id)
    timeline = operational_timeline.get_timeline_snapshot(org_id, limit=100)
    pending_commands = execution_command_manager.get_pending_commands(org_id)

    return {
        "organization_id": org_id,
        "timestamp": datetime.utcnow().isoformat(),
        "dashboard": {
            "total_incidents": dashboard.total_active_incidents,
            "total_pending_approvals": dashboard.total_pending_approvals,
            "total_failed_actions": dashboard.total_failed_actions,
            "severity_breakdown": {
                "critical": dashboard.critical_count,
                "high": dashboard.high_count,
                "medium": dashboard.medium_count,
                "low": dashboard.low_count,
            },
        },
        "health": {
            "overall_status": health.overall_status.value,
            "websocket": health.websocket_health,
            "execution": health.execution_health,
            "memory": health.memory_health,
        },
        "metrics": {
            "executions_per_hour": metrics.executions_per_hour,
            "approvals_per_hour": metrics.approvals_per_hour,
            "execution_success_rate": metrics.execution_success_rate,
            "approval_acceptance_rate": metrics.approval_acceptance_rate,
        },
        "timeline": {
            "total_events": timeline.get("total_events", 0),
            "recent_events": timeline.get("events", [])[:10],
        },
        "pending_commands": len(pending_commands),
        "command_audit_trail": [c.to_dict() for c in pending_commands[:5]],
    }
