"""Nova execution orchestrator - async-safe, replay-safe, dedupe-safe action orchestration."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Awaitable, Callable
from uuid import uuid4

from app.core.nova.action_models import (
    ActionCategory,
    ActionType,
    ApprovalRequest,
    ExecutionResult,
    ExecutionStatus,
    NovaAction,
    ProposedAction,
    ActionTimeline,
)
from app.core.nova.memory import memory_store


class ExecutionOrchestrator:
    """Async-safe action orchestration with stage/queue/validate/execute/rollback lifecycle."""
    
    def __init__(self):
        self._executing_actions: dict[str, asyncio.Task[Any]] = {}
        self._replay_seen: dict[str, set[str]] = {}  # org_id -> seen correlation_ids
        self._dedup_lock = asyncio.Lock()
        self._correlations: dict[str, str] = {}  # correlation_id -> action_id
    
    async def propose_action(
        self,
        organization_id: str,
        proposal: ProposedAction,
        *,
        source_event_ids: list[str] | None = None,
        correlation_id: str | None = None,
    ) -> NovaAction:
        """Stage a proposed action - no execution yet."""
        correlation_id = correlation_id or str(uuid4())
        action_id = str(uuid4())
        now = datetime.now(timezone.utc)
        
        async with self._dedup_lock:
            org_seen = self._replay_seen.setdefault(organization_id, set())
            if correlation_id in org_seen:
                stored_action_id = self._correlations.get(correlation_id)
                if stored_action_id:
                    # Replay detected - return cached action
                    actions = await self._query_actions(organization_id, limit=1000)
                    for action in actions:
                        if action.action_id == stored_action_id:
                            return action
            org_seen.add(correlation_id)
            self._correlations[correlation_id] = action_id
        
        action = NovaAction(
            action_id=action_id,
            correlation_id=correlation_id,
            action_type=proposal.action_type,
            category=proposal.category,
            title=proposal.title,
            reason=proposal.reason,
            impact=proposal.impact,
            urgency=proposal.urgency,
            confidence=proposal.confidence,
            suggested_execution=proposal.suggested_execution,
            rollback_strategy=proposal.rollback_strategy,
            approval_required=proposal.approval_required,
            execution_timeout_seconds=proposal.execution_timeout_seconds,
            source_event_ids=source_event_ids or [],
            execution_status=ExecutionStatus.PROPOSED,
            created_at=now,
            organization_id=organization_id,
        )
        
        # Persist to memory
        await self._persist_action(organization_id, action)
        
        # Record timeline
        await self._record_timeline_event(
            organization_id,
            action_id,
            "proposed",
            f"Action proposed: {action.title}",
            metadata={
                "urgency": action.urgency,
                "confidence": action.confidence,
                "requires_approval": action.approval_required,
            },
        )
        
        return action
    
    async def validate_execution_feasibility(
        self,
        organization_id: str,
        action: NovaAction,
        *,
        state_validator: Callable[[str, NovaAction], bool] | None = None,
    ) -> tuple[bool, str]:
        """Validate that action can execute in current runtime state."""
        if action.execution_status not in {ExecutionStatus.APPROVED, ExecutionStatus.AWAITING_APPROVAL}:
            return False, f"Cannot execute action in {action.execution_status} state"
        
        if action.expires_at and datetime.now(timezone.utc) > action.expires_at:
            return False, "Action has expired"
        
        # Custom state validator if provided
        if state_validator:
            if not state_validator(organization_id, action):
                return False, "Current runtime state cannot satisfy action requirements"
        
        return True, "Ready to execute"
    
    async def simulate_execution(
        self,
        organization_id: str,
        action: NovaAction,
    ) -> dict[str, Any]:
        """Dry-run simulation without actual execution."""
        simulation = {
            "action_id": action.action_id,
            "simulation_only": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "estimated_impact": action.impact,
            "rollback_plan": action.rollback_strategy,
            "warnings": [],
        }
        
        # Add type-specific simulation
        if action.action_type == ActionType.DISPATCH_ESCALATION:
            simulation["warnings"].append("Escalation will notify dispatch team")
        elif action.action_type == ActionType.RUNTIME_RECONNECT_RECOVERY:
            simulation["warnings"].append("Recovery will temporarily interrupt websocket connections")
        
        return simulation
    
    async def handle_approval(
        self,
        organization_id: str,
        approval: ApprovalRequest,
        *,
        operator_identity: str | None = None,
    ) -> NovaAction:
        """Process operator approval/rejection decision."""
        actions = await self._query_actions(organization_id, limit=1000)
        action = None
        for a in actions:
            if a.action_id == approval.action_id:
                action = a
                break
        
        if not action:
            raise ValueError(f"Action {approval.action_id} not found")
        
        now = datetime.now(timezone.utc)
        
        if approval.approved:
            action.execution_status = ExecutionStatus.APPROVED
            action.approval_metadata = approval.approval_metadata
            action.operator_identity = operator_identity
            action.approval_timestamp = now
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "approved",
                f"Operator approved: {approval.approval_reason or 'Approved'}",
                metadata={"operator": operator_identity, "reason": approval.approval_reason},
            )
        else:
            action.execution_status = ExecutionStatus.REJECTED
            action.rejection_reason = approval.rejection_reason
            action.operator_identity = operator_identity
            action.approval_timestamp = now
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "rejected",
                f"Operator rejected: {approval.rejection_reason or 'Rejected'}",
                metadata={"operator": operator_identity, "reason": approval.rejection_reason},
            )
        
        await self._persist_action(organization_id, action)
        return action
    
    async def execute_action(
        self,
        organization_id: str,
        action: NovaAction,
        *,
        executor: Callable[[NovaAction], Awaitable[dict[str, Any]]] | None = None,
    ) -> ExecutionResult:
        """Execute an approved action with timeout and rollback safety."""
        if action.execution_status != ExecutionStatus.APPROVED:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                error_message=f"Cannot execute action in {action.execution_status} state",
            )
        
        # Check for duplicate execution
        if action.action_id in self._executing_actions:
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.EXECUTING,
                evidence={"duplicate_execution_prevented": True},
            )
        
        action.execution_status = ExecutionStatus.EXECUTING
        action.executed_at = datetime.now(timezone.utc)
        await self._persist_action(organization_id, action)
        
        await self._record_timeline_event(
            organization_id,
            action.action_id,
            "executing",
            f"Execution started: {action.title}",
        )
        
        try:
            # Create timeout task
            if executor:
                result = await asyncio.wait_for(
                    executor(action),
                    timeout=float(action.execution_timeout_seconds),
                )
            else:
                result = {"status": "no_executor_provided"}
            
            # Mark complete
            action.execution_status = ExecutionStatus.COMPLETED
            action.completed_at = datetime.now(timezone.utc)
            action.execution_evidence = result
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "completed",
                f"Execution completed: {action.title}",
                metadata={"evidence": result},
            )
            
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.COMPLETED,
                evidence=result,
            )
        
        except asyncio.TimeoutError:
            action.execution_status = ExecutionStatus.FAILED
            action.completed_at = datetime.now(timezone.utc)
            error_msg = f"Execution timeout after {action.execution_timeout_seconds}s"
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "failed",
                error_msg,
                metadata={"failure_reason": "timeout"},
            )
            
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                error_message=error_msg,
            )
        
        except Exception as exc:
            action.execution_status = ExecutionStatus.FAILED
            action.completed_at = datetime.now(timezone.utc)
            error_msg = f"Execution failed: {str(exc)}"
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "failed",
                error_msg,
                metadata={"failure_reason": str(exc)},
            )
            
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                error_message=error_msg,
            )
        
        finally:
            await self._persist_action(organization_id, action)
            self._executing_actions.pop(action.action_id, None)
    
    async def rollback_action(
        self,
        organization_id: str,
        action: NovaAction,
        *,
        rollback_executor: Callable[[NovaAction], Awaitable[dict[str, Any]]] | None = None,
    ) -> ExecutionResult:
        """Rollback a failed or approved action."""
        action.execution_status = ExecutionStatus.ROLLED_BACK
        action.completed_at = datetime.now(timezone.utc)
        
        try:
            if rollback_executor:
                result = await asyncio.wait_for(
                    rollback_executor(action),
                    timeout=float(action.execution_timeout_seconds),
                )
            else:
                result = {"rollback": "manual_rollback_required"}
            
            action.recovery_attempts.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "rollback",
                "result": result,
            })
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "rolled_back",
                f"Rollback completed for: {action.title}",
                metadata={"result": result},
            )
            
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.ROLLED_BACK,
                evidence=result,
                recovery_successful=True,
            )
        
        except Exception as exc:
            error_msg = f"Rollback failed: {str(exc)}"
            action.recovery_attempts.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "rollback",
                "error": error_msg,
            })
            
            await self._record_timeline_event(
                organization_id,
                action.action_id,
                "rollback_failed",
                error_msg,
                metadata={"error": str(exc)},
            )
            
            return ExecutionResult(
                action_id=action.action_id,
                status=ExecutionStatus.FAILED,
                error_message=error_msg,
                recovery_successful=False,
            )
        
        finally:
            await self._persist_action(organization_id, action)
    
    async def query_pending_actions(
        self,
        organization_id: str,
        *,
        status: ExecutionStatus | None = None,
        limit: int = 50,
    ) -> list[NovaAction]:
        """Query pending actions."""
        actions = await self._query_actions(organization_id, limit=limit * 2)
        pending = [
            a for a in actions
            if a.execution_status in {
                ExecutionStatus.PROPOSED,
                ExecutionStatus.AWAITING_APPROVAL,
                ExecutionStatus.APPROVED,
            }
        ]
        if status:
            pending = [a for a in pending if a.execution_status == status]
        return pending[:limit]
    
    async def query_executing_actions(self, organization_id: str) -> list[NovaAction]:
        """Query currently executing actions."""
        actions = await self._query_actions(organization_id, limit=1000)
        return [a for a in actions if a.execution_status == ExecutionStatus.EXECUTING]
    
    async def query_failed_actions(self, organization_id: str, limit: int = 20) -> list[NovaAction]:
        """Query failed actions."""
        actions = await self._query_actions(organization_id, limit=limit * 2)
        return [a for a in actions if a.execution_status == ExecutionStatus.FAILED][:limit]
    
    async def query_recent_rollbacks(self, organization_id: str, limit: int = 20) -> list[NovaAction]:
        """Query recent rollbacks."""
        actions = await self._query_actions(organization_id, limit=limit * 2)
        return [a for a in actions if a.execution_status == ExecutionStatus.ROLLED_BACK][:limit]
    
    async def get_execution_latency_stats(
        self,
        organization_id: str,
    ) -> dict[str, float]:
        """Calculate execution latency statistics."""
        actions = await self._query_actions(organization_id, limit=1000)
        latencies = []
        
        for action in actions:
            if action.executed_at and action.completed_at:
                delta = (action.completed_at - action.executed_at).total_seconds() * 1000
                latencies.append(delta)
        
        if not latencies:
            return {"count": 0, "average_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0}
        
        return {
            "count": len(latencies),
            "average_ms": sum(latencies) / len(latencies),
            "min_ms": min(latencies),
            "max_ms": max(latencies),
        }
    
    async def expire_stale_actions(
        self,
        organization_id: str,
        *,
        age_seconds: int = 3600,
    ) -> int:
        """Expire actions older than age threshold."""
        actions = await self._query_actions(organization_id, limit=1000)
        now = datetime.now(timezone.utc)
        expired_count = 0
        
        for action in actions:
            if action.execution_status in {ExecutionStatus.PROPOSED, ExecutionStatus.AWAITING_APPROVAL}:
                if (now - action.created_at).total_seconds() > age_seconds:
                    action.execution_status = ExecutionStatus.EXPIRED
                    action.expires_at = now
                    await self._persist_action(organization_id, action)
                    expired_count += 1
        
        return expired_count
    
    # Private helpers
    
    async def _persist_action(self, organization_id: str, action: NovaAction) -> None:
        """Persist action to memory store."""
        fabric = memory_store.read_fabric(organization_id)
        actions = fabric.get("pending_actions", [])
        
        # Replace or append
        found = False
        for i, a in enumerate(actions):
            if a.get("action_id") == action.action_id:
                actions[i] = action.model_dump(mode="json")
                found = True
                break
        
        if not found:
            actions.append(action.model_dump(mode="json"))
        
        fabric["pending_actions"] = actions[:500]
        state = memory_store.read(organization_id)
        state["memory_fabric"] = fabric
        memory_store.write(organization_id, {"memory_fabric": fabric})
    
    async def _query_actions(
        self,
        organization_id: str,
        limit: int = 1000,
    ) -> list[NovaAction]:
        """Query actions from memory store."""
        fabric = memory_store.read_fabric(organization_id)
        actions_data = fabric.get("pending_actions", [])
        
        actions = []
        for data in actions_data[:limit]:
            try:
                action = NovaAction(**data)
                actions.append(action)
            except Exception:
                continue
        
        return actions
    
    async def _record_timeline_event(
        self,
        organization_id: str,
        action_id: str,
        event_type: str,
        summary: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record action timeline event."""
        memory_store.append_event(
            organization_id,
            "operational_history",
            {
                "event_type": f"action_{event_type}",
                "summary": summary,
                "source": "nova_orchestrator",
                "tags": ["action", "execution", event_type],
                "metadata": {
                    "action_id": action_id,
                    **(metadata or {}),
                },
                "correlation_id": action_id,
            },
        )


# Singleton instance
execution_orchestrator = ExecutionOrchestrator()
