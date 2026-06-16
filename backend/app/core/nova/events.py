from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.nova.event_models import NovaOperationalEvent, utc_now_iso
from app.core.nova.schemas import NovaContextResponse


def _to_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(fallback)


def _to_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


def _event(
    *,
    event_type: str,
    severity: str,
    source: str,
    correlation_id: str,
    operational_context: dict[str, Any],
    recommended_action: str,
    recovery_hint: str,
) -> NovaOperationalEvent:
    return NovaOperationalEvent(
        event_id=f"{event_type}:{correlation_id}",
        event_type=event_type,
        severity=severity,  # type: ignore[arg-type]
        source=source,
        timestamp=utc_now_iso(),
        correlation_id=correlation_id,
        operational_context=operational_context,
        recommended_action=recommended_action,
        recovery_hint=recovery_hint,
        replay_safe=True,
        websocket_compatible=True,
    )


def build_operational_events(context: NovaContextResponse, fabric: dict[str, Any]) -> list[NovaOperationalEvent]:
    hs = context.health_isf_summary
    health = dict(context.operational_health or {})
    health_meta = dict(health.get("health") or {})
    websocket = dict(health_meta.get("websocket") or {})
    queue_stats = dict(health_meta.get("event_queue") or {})
    metrics = dict(health.get("metrics") or {})

    events: list[NovaOperationalEvent] = []

    pending = _to_int(hs.rides_pending)
    rides_total = max(1, _to_int(hs.rides_total))
    pending_ratio = pending / rides_total

    drivers_available = _to_int(hs.drivers_available)
    providers_total = max(1, _to_int(hs.providers_total))
    provider_online = _to_int(metrics.get("providers_online"), providers_total)

    cancelled_rides = _to_int(metrics.get("cancelled_rides"), 0)
    cancellation_rate = _to_float(metrics.get("cancellation_rate"), 0.0)
    disconnects = _to_int(websocket.get("disconnects_last_5m"), 0)
    dead_letter = _to_int(queue_stats.get("dead_letter"), 0)

    correlation_prefix = str(context.organization_id)

    if providers_total > 0 and provider_online <= max(1, providers_total // 3):
        events.append(_event(
            event_type="provider_shortage",
            severity="high",
            source="nova.detector.providers",
            correlation_id=f"{correlation_prefix}:provider_shortage",
            operational_context={"providers_total": providers_total, "providers_online": provider_online},
            recommended_action="Escalate provider coverage and rebalance dispatch allocation to online providers.",
            recovery_hint="Activate standby provider roster for low-latency zones.",
        ))

    if pending >= 12 or pending_ratio >= 0.5:
        events.append(_event(
            event_type="ride_spike",
            severity="high" if pending >= 20 else "medium",
            source="nova.detector.dispatch",
            correlation_id=f"{correlation_prefix}:ride_spike",
            operational_context={"rides_pending": pending, "rides_total": rides_total, "pending_ratio": round(pending_ratio, 3)},
            recommended_action="Throttle new queue intake and prioritize stale rides by SLA urgency.",
            recovery_hint="Temporarily expand dispatcher lane for backlog triage.",
        ))

    if cancelled_rides >= 5 or cancellation_rate >= 0.25:
        events.append(_event(
            event_type="cancellation_spike",
            severity="high" if cancellation_rate >= 0.35 else "medium",
            source="nova.detector.revenue",
            correlation_id=f"{correlation_prefix}:cancellation_spike",
            operational_context={"cancelled_rides": cancelled_rides, "cancellation_rate": cancellation_rate},
            recommended_action="Investigate top cancellation segments and deploy retention countermeasures.",
            recovery_hint="Enable cancellation-reason capture and targeted provider/driver follow-up.",
        ))

    if disconnects >= 3:
        events.append(_event(
            event_type="websocket_instability",
            severity="high" if disconnects >= 8 else "medium",
            source="nova.detector.websocket",
            correlation_id=f"{correlation_prefix}:websocket_instability",
            operational_context={"disconnects_last_5m": disconnects, "websocket": websocket},
            recommended_action="Stabilize websocket sessions and reduce reconnect churn on active operator clients.",
            recovery_hint="Inspect connection quotas and retry bursts before broad reconnect.",
        ))

    session_stability = dict(fabric.get("session_stability") or {})
    last_status = str(session_stability.get("last_status") or "").lower()
    last_hb = str(session_stability.get("last_heartbeat_at") or "")
    if last_status == "busy" and last_hb:
        try:
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(last_hb)).total_seconds()
        except Exception:
            age = 0.0
        if age >= 150:
            events.append(_event(
                event_type="stale_busy_state",
                severity="high",
                source="nova.detector.session",
                correlation_id=f"{correlation_prefix}:stale_busy_state",
                operational_context={"last_status": last_status, "last_heartbeat_at": last_hb, "age_seconds": round(age, 2)},
                recommended_action="Release stale busy lock and rehydrate Nova runtime action state.",
                recovery_hint="Issue controlled heartbeat recovery and verify action completion markers.",
            ))

    timeline = list(fabric.get("execution_timeline") or [])[:40]
    recent_failures = [item for item in timeline if str(item.get("failure_reason") or "").strip()]
    if len(recent_failures) >= 3:
        events.append(_event(
            event_type="repeated_execution_failure",
            severity="high",
            source="nova.detector.execution",
            correlation_id=f"{correlation_prefix}:repeated_execution_failure",
            operational_context={"failure_count": len(recent_failures), "latest_failure": recent_failures[0]},
            recommended_action="Pause repeated failing action paths and route through approval-safe recovery playbook.",
            recovery_hint="Apply rollback-safe fallback for the highest-frequency failure pattern.",
        ))

    health_status = str(health_meta.get("status") or "healthy").lower()
    if health_status not in {"healthy", "ok"} or dead_letter >= 20:
        events.append(_event(
            event_type="api_degradation",
            severity="high" if dead_letter >= 50 else "medium",
            source="nova.detector.runtime",
            correlation_id=f"{correlation_prefix}:api_degradation",
            operational_context={"health_status": health_status, "dead_letter": dead_letter, "queue_stats": queue_stats},
            recommended_action="Reduce high-cost runtime calls and prioritize degraded endpoint stabilization.",
            recovery_hint="Scale down non-critical refresh pressure until request latency normalizes.",
        ))

    workflow_open = _to_int(hs.workflow_open_incidents)
    if workflow_open >= 8 or pending >= 15:
        events.append(_event(
            event_type="dispatch_bottleneck",
            severity="high" if workflow_open >= 12 else "medium",
            source="nova.detector.dispatch",
            correlation_id=f"{correlation_prefix}:dispatch_bottleneck",
            operational_context={"workflow_open_incidents": workflow_open, "rides_pending": pending},
            recommended_action="Escalate dispatch bottleneck queue and rebalance assignment ownership.",
            recovery_hint="Prioritize unresolved workflow incidents with active SLA impact.",
        ))

    inactive_clusters = _to_int(metrics.get("inactive_provider_clusters"), 0)
    if inactive_clusters >= 1:
        events.append(_event(
            event_type="inactive_provider_clusters",
            severity="medium" if inactive_clusters == 1 else "high",
            source="nova.detector.providers",
            correlation_id=f"{correlation_prefix}:inactive_provider_clusters",
            operational_context={"inactive_provider_clusters": inactive_clusters},
            recommended_action="Target inactive provider clusters with dispatch incentives and operational outreach.",
            recovery_hint="Re-route demand from inactive zones to nearest healthy cluster.",
        ))

    return events
