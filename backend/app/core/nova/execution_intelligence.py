"""Nova execution intelligence integration for Health ISF AI operations diagnostics."""

from __future__ import annotations

from typing import Any

from app.core.nova.actions import execution_orchestrator
from app.core.nova.action_models import ExecutionStatus


class NovaExecutionIntelligence:
    """Integration layer exposing Nova execution state to AI operations."""
    
    @classmethod
    async def build_execution_status_snapshot(
        cls,
        organization_id: str,
    ) -> dict[str, Any]:
        """Build comprehensive execution status snapshot for diagnostics."""
        try:
            pending = await execution_orchestrator.query_pending_actions(organization_id, limit=100)
            executing = await execution_orchestrator.query_executing_actions(organization_id)
            failed = await execution_orchestrator.query_failed_actions(organization_id)
            rollbacks = await execution_orchestrator.query_recent_rollbacks(organization_id)
            latency_stats = await execution_orchestrator.get_execution_latency_stats(organization_id)
        except Exception:
            # Graceful degradation - actions are optional diagnostics
            pending = []
            executing = []
            failed = []
            rollbacks = []
            latency_stats = {}
        
        # Count by status
        status_counts = {
            "proposed": len([a for a in pending if a.execution_status == ExecutionStatus.PROPOSED]),
            "awaiting_approval": len([a for a in pending if a.execution_status == ExecutionStatus.AWAITING_APPROVAL]),
            "approved": len([a for a in pending if a.execution_status == ExecutionStatus.APPROVED]),
            "executing": len(executing),
            "completed": 0,
            "failed": len(failed),
            "rolled_back": len(rollbacks),
        }
        
        return {
            "organization_id": organization_id,
            "approval_queue": {
                "awaiting_approval_count": status_counts["awaiting_approval"],
                "oldest_pending_action": None,
            },
            "execution": {
                "executing_count": status_counts["executing"],
                "average_latency_ms": latency_stats.get("average_ms", 0.0),
                "failed_count": status_counts["failed"],
                "recent_failures": [
                    {
                        "action_id": a.action_id,
                        "title": a.title,
                        "failure_reason": a.execution_evidence.get("error") or "Unknown",
                    }
                    for a in failed[:5]
                ],
            },
            "recovery": {
                "rollback_count": status_counts["rolled_back"],
                "recent_rollbacks": [
                    {
                        "action_id": a.action_id,
                        "title": a.title,
                        "recovery_attempts": len(a.recovery_attempts),
                    }
                    for a in rollbacks[:5]
                ],
            },
            "status_summary": status_counts,
            "approval_required_default": True,
            "no_uncontrolled_automation": True,
            "human_approval_mandatory": True,
        }
    
    @classmethod
    async def get_pending_approval_actions(
        cls,
        organization_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Get actions awaiting operator approval."""
        try:
            actions = await execution_orchestrator.query_pending_actions(
                organization_id,
                status=ExecutionStatus.AWAITING_APPROVAL,
                limit=limit,
            )
            
            return [
                {
                    "action_id": a.action_id,
                    "title": a.title,
                    "reason": a.reason,
                    "urgency": a.urgency,
                    "confidence": a.confidence,
                    "suggested_execution": a.suggested_execution,
                    "rollback_strategy": a.rollback_strategy,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in actions
            ]
        except Exception:
            return []
    
    @classmethod
    async def get_execution_evidence(
        cls,
        organization_id: str,
        action_id: str,
    ) -> dict[str, Any] | None:
        """Get execution evidence for a completed action."""
        try:
            actions = await execution_orchestrator.query_pending_actions(organization_id, limit=1000)
            for action in actions:
                if action.action_id == action_id:
                    return {
                        "action_id": action.action_id,
                        "status": str(action.execution_status),
                        "evidence": action.execution_evidence,
                        "executed_at": action.executed_at.isoformat() if action.executed_at else None,
                        "completed_at": action.completed_at.isoformat() if action.completed_at else None,
                    }
            return None
        except Exception:
            return None
