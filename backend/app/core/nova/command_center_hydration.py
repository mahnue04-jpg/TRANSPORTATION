"""
PHASE 7B: Command Center UI Hydration Layer
Real-time frontend component state for live incident cards, execution stream, approval inbox, etc.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Any, Optional


@dataclass
class UIComponentState:
    """State of a UI component"""
    component_id: str
    component_type: str  # incident_card, execution_stream, approval_inbox, etc.
    data: Dict[str, Any] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=datetime.utcnow)
    needs_refresh: bool = False
    error_message: Optional[str] = None


class CommandCenterHydration:
    """Frontend hydration for command center"""
    
    def __init__(self):
        """Initialize hydration layer"""
        self._component_state: Dict[str, Dict[str, UIComponentState]] = {}
    
    def hydrate_incident_cards(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate incident cards"""
        try:
            from app.core.nova.operational_dashboard import operational_dashboard
            
            snapshot = operational_dashboard.build_snapshot(organization_id)
            incidents = snapshot.active_incidents[:10]
            
            return {
                "incidents": [
                    {
                        "id": e.event_id,
                        "category": e.category.value,
                        "severity": e.severity.value,
                        "title": e.title,
                        "timestamp": e.timestamp.isoformat(),
                    }
                    for e in incidents
                ],
                "total": snapshot.total_active_incidents,
            }
        except Exception:
            return {"incidents": [], "total": 0}
    
    def hydrate_execution_stream(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate real-time execution stream"""
        try:
            from app.core.nova.memory import memory_store

            fabric = memory_store.read_fabric(organization_id)
            actions = list(fabric.get("pending_actions") or [])
            executing = [
                a for a in actions
                if str(a.get("execution_status") or "").lower() == "executing"
            ]
            
            return {
                "executions": [
                    {
                        "action_id": str(a.get("action_id") or ""),
                        "action_type": str(a.get("action_type") or ""),
                        "status": str(a.get("execution_status") or ""),
                        "started_at": a.get("executed_at"),
                    }
                    for a in executing[:10]
                ],
                "total_executing": len(executing),
            }
        except Exception:
            return {"executions": [], "total_executing": 0}
    
    def hydrate_approval_inbox(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate approval inbox"""
        try:
            from app.core.nova.memory import memory_store

            fabric = memory_store.read_fabric(organization_id)
            actions = list(fabric.get("pending_actions") or [])
            pending = [
                a for a in actions
                if str(a.get("execution_status") or "").lower() in {"proposed", "awaiting_approval", "approved"}
            ]
            
            return {
                "pending_approvals": [
                    {
                        "action_id": str(a.get("action_id") or ""),
                        "action_type": str(a.get("action_type") or ""),
                        "created_at": a.get("created_at"),
                        "priority": "high" if str(a.get("urgency") or "").lower() in {"high", "critical"} else "normal",
                    }
                    for a in pending[:20]
                ],
                "total_pending": len(pending),
            }
        except Exception:
            return {"pending_approvals": [], "total_pending": 0}
    
    def hydrate_rollback_controls(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate rollback control panel"""
        try:
            from app.core.nova.memory import memory_store

            fabric = memory_store.read_fabric(organization_id)
            actions = list(fabric.get("pending_actions") or [])
            failed = [
                a for a in actions
                if str(a.get("execution_status") or "").lower() == "failed"
            ]
            
            return {
                "rollback_available": [
                    {
                        "action_id": str(a.get("action_id") or ""),
                        "action_type": str(a.get("action_type") or ""),
                        "failure_reason": str(a.get("rejection_reason") or "execution_failed"),
                    }
                    for a in failed[:10]
                ],
                "total_available": len(failed),
            }
        except Exception:
            return {"rollback_available": [], "total_available": 0}
    
    def hydrate_health_panel(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate health diagnostics panel"""
        try:
            from app.core.nova.health_monitoring import health_monitor
            
            snapshot = health_monitor.build_snapshot(organization_id)
            
            return {
                "status": snapshot.overall_status.value,
                "components": [
                    {
                        "name": "websocket",
                        "status": str(snapshot.websocket_health.get("status", "unknown")),
                    },
                    {
                        "name": "execution",
                        "status": str(snapshot.execution_health.get("status", "unknown")),
                    },
                ],
            }
        except Exception:
            return {"status": "unknown", "components": []}
    
    def hydrate_severity_badges(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate severity indicator badges"""
        try:
            from app.core.nova.operational_dashboard import operational_dashboard
            
            snapshot = operational_dashboard.build_snapshot(organization_id)
            
            return {
                "critical": snapshot.critical_count,
                "high": snapshot.high_count,
                "medium": snapshot.medium_count,
                "low": snapshot.low_count,
            }
        except Exception:
            return {}
    
    def hydrate_runtime_counters(self, organization_id: str) -> Dict[str, Any]:
        """Hydrate runtime counters"""
        try:
            from app.core.nova.operational_metrics import operational_metrics
            
            snapshot = operational_metrics.build_snapshot(organization_id)
            return {
                "executions_started": snapshot.total_executions_started,
                "executions_completed": snapshot.total_executions_completed,
                "approvals_pending": max(snapshot.total_approvals - snapshot.recommendations_approved, 0),
                "incidents_active": snapshot.total_incidents,
            }
        except Exception:
            return {}
    
    def build_full_hydration(self, organization_id: str) -> Dict[str, Any]:
        """Build complete hydration snapshot"""
        try:
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "components": {
                    "incident_cards": self.hydrate_incident_cards(organization_id),
                    "execution_stream": self.hydrate_execution_stream(organization_id),
                    "approval_inbox": self.hydrate_approval_inbox(organization_id),
                    "rollback_controls": self.hydrate_rollback_controls(organization_id),
                    "health_panel": self.hydrate_health_panel(organization_id),
                    "severity_badges": self.hydrate_severity_badges(organization_id),
                    "runtime_counters": self.hydrate_runtime_counters(organization_id),
                },
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Hydration failed",
            }


# Singleton instance
from typing import Optional
command_center_hydration = CommandCenterHydration()

