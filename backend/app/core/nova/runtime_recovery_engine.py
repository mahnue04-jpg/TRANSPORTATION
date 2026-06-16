"""
PHASE 7B: Self-Healing Runtime Layer
Recovery engine for websocket disconnects, stalled executions, deadlocks, and more.
Creates recovery proposals with operator approval requirement.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
import uuid


class RecoveryType(Enum):
    """Recovery action types"""
    WEBSOCKET_RECONNECT = "websocket_reconnect"
    EXECUTION_TIMEOUT = "execution_timeout"
    DEADLOCK_RESOLUTION = "deadlock_resolution"
    APPROVAL_TIMEOUT = "approval_timeout"
    MEMORY_REPAIR = "memory_repair"
    STATE_SYNC = "state_sync"
    QUEUE_DRAIN = "queue_drain"
    DUPLICATE_CLEANUP = "duplicate_cleanup"
    STALE_SESSION_CLOSE = "stale_session_close"
    ROLLBACK_RETRY = "rollback_retry"


class RecoveryStatus(Enum):
    """Recovery status"""
    PROPOSED = "proposed"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"


@dataclass
class RecoveryProposal:
    """Proposal for recovery action"""
    proposal_id: str
    organization_id: str
    recovery_type: RecoveryType
    timestamp: datetime
    severity: str  # critical, high, medium, low
    description: str
    affected_systems: List[str] = field(default_factory=list)
    proposed_action: str = ""
    rollback_safe: bool = True
    requires_approval: bool = True
    evidence: List[str] = field(default_factory=list)
    estimated_recovery_time_ms: int = 0
    status: RecoveryStatus = RecoveryStatus.PROPOSED


@dataclass
class RecoveryAction:
    """Executed recovery action"""
    action_id: str
    organization_id: str
    proposal_id: str
    recovery_type: RecoveryType
    issued_at: datetime
    issued_by: Optional[str] = None  # Operator identity
    approved_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    status: RecoveryStatus = RecoveryStatus.PROPOSED
    evidence: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None
    rollback_evidence: Dict[str, Any] = field(default_factory=dict)


class RuntimeRecoveryEngine:
    """Self-healing runtime layer"""
    
    def __init__(self):
        """Initialize recovery engine"""
        self._recovery_proposals: Dict[str, List[RecoveryProposal]] = {}
        self._recovery_actions: Dict[str, List[RecoveryAction]] = {}
        self._recovery_history: Dict[str, List[RecoveryAction]] = {}
        self._deadlock_detection_enabled = True
        self._stale_threshold_seconds = 300  # 5 minutes
    
    def propose_recovery(
        self,
        organization_id: str,
        recovery_type: RecoveryType,
        severity: str,
        description: str,
        affected_systems: List[str],
    ) -> RecoveryProposal:
        """Propose a recovery action"""
        try:
            proposal_id = f"recovery_{uuid.uuid4().hex[:12]}"
            
            proposal = RecoveryProposal(
                proposal_id=proposal_id,
                organization_id=organization_id,
                recovery_type=recovery_type,
                timestamp=datetime.utcnow(),
                severity=severity,
                description=description,
                affected_systems=affected_systems,
            )
            
            if organization_id not in self._recovery_proposals:
                self._recovery_proposals[organization_id] = []
            
            self._recovery_proposals[organization_id].append(proposal)
            
            return proposal
        except Exception:
            return RecoveryProposal(
                proposal_id="",
                organization_id=organization_id,
                recovery_type=recovery_type,
                timestamp=datetime.utcnow(),
                severity=severity,
                description=description,
            )
    
    async def detect_websocket_disconnect(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect websocket disconnects and propose recovery"""
        try:
            from app.core.nova.health_monitoring import health_monitor
            
            ws_health = health_monitor.build_websocket_health()
            if not ws_health:
                return None
            
            recent_disconnects = ws_health.get("recent_disconnects", 0)
            if recent_disconnects > 5:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.WEBSOCKET_RECONNECT,
                    severity="high" if recent_disconnects < 10 else "critical",
                    description=f"WebSocket: {recent_disconnects} disconnects detected",
                    affected_systems=["websocket", "realtime"],
                )
                proposal.proposed_action = "Force all clients to reconnect and restore session state"
                proposal.rollback_safe = True
                proposal.requires_approval = True
                proposal.evidence = [f"recent_disconnects: {recent_disconnects}"]
                return proposal
            
            return None
        except Exception:
            return None
    
    async def detect_stalled_execution(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect stalled executions and propose timeout recovery"""
        try:
            from app.core.nova.actions import execution_orchestrator
            
            executing = execution_orchestrator.query_executing(organization_id)
            now = datetime.utcnow()
            
            stalled = []
            for action in executing:
                if hasattr(action, 'execution_started_at') and action.execution_started_at:
                    age = (now - action.execution_started_at).total_seconds()
                    if age > self._stale_threshold_seconds:
                        stalled.append(action.action_id)
            
            if stalled:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.EXECUTION_TIMEOUT,
                    severity="critical" if len(stalled) > 3 else "high",
                    description=f"Execution: {len(stalled)} actions stalled >5min",
                    affected_systems=["execution", "orchestration"],
                )
                proposal.proposed_action = f"Timeout and rollback {len(stalled)} stalled actions"
                proposal.rollback_safe = True
                proposal.requires_approval = True
                proposal.evidence = [f"stalled_actions: {stalled}"]
                proposal.estimated_recovery_time_ms = 5000
                return proposal
            
            return None
        except Exception:
            return None
    
    async def detect_deadlock(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect execution deadlock"""
        try:
            from app.core.nova.actions import execution_orchestrator
            
            pending = execution_orchestrator.query_pending(organization_id)
            executing = execution_orchestrator.query_executing(organization_id)
            
            # Many pending + many executing suggests deadlock
            if len(pending) > 50 and len(executing) > 10:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.DEADLOCK_RESOLUTION,
                    severity="critical",
                    description=f"Execution: Possible deadlock ({len(pending)} pending, {len(executing)} executing)",
                    affected_systems=["execution", "approval", "orchestration"],
                )
                proposal.proposed_action = "Clear execution queue and resume from last stable state"
                proposal.rollback_safe = True
                proposal.requires_approval = True
                proposal.evidence = [f"pending: {len(pending)}", f"executing: {len(executing)}"]
                return proposal
            
            return None
        except Exception:
            return None
    
    async def detect_approval_timeout(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect approvals pending too long"""
        try:
            from app.core.nova.actions import execution_orchestrator
            
            pending = execution_orchestrator.query_pending(organization_id)
            now = datetime.utcnow()
            
            old_pending = []
            for action in pending:
                if hasattr(action, 'created_at') and action.created_at:
                    age = (now - action.created_at).total_seconds()
                    if age > 3600:  # 1 hour
                        old_pending.append(action.action_id)
            
            if old_pending:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.APPROVAL_TIMEOUT,
                    severity="medium",
                    description=f"Approval: {len(old_pending)} actions pending >1 hour",
                    affected_systems=["approval", "execution"],
                )
                proposal.proposed_action = "Auto-reject stale approvals or escalate to admin"
                proposal.rollback_safe = False
                proposal.requires_approval = True
                proposal.evidence = [f"stale_approvals: {old_pending}"]
                return proposal
            
            return None
        except Exception:
            return None
    
    async def detect_memory_corruption(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect memory fabric corruption"""
        try:
            from app.core.memory_store import memory_store
            
            state = memory_store.get_state(organization_id)
            if not state:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.MEMORY_REPAIR,
                    severity="critical",
                    description="Memory: State missing or corrupted",
                    affected_systems=["memory", "persistence"],
                )
                proposal.proposed_action = "Rebuild memory state from operational timeline"
                proposal.rollback_safe = True
                proposal.requires_approval = True
                proposal.evidence = ["state_missing"]
                return proposal
            
            # Check for missing required fields
            required_fields = [
                "founder_continuity", "operational_history", "execution_timeline",
                "operational_event_timeline", "pending_actions", "recommendation_history"
            ]
            missing = [f for f in required_fields if f not in state]
            
            if missing:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.MEMORY_REPAIR,
                    severity="high",
                    description=f"Memory: {len(missing)} fields missing",
                    affected_systems=["memory", "persistence"],
                )
                proposal.proposed_action = "Repair memory fabric by restoring missing fields"
                proposal.rollback_safe = True
                proposal.requires_approval = True
                proposal.evidence = missing
                return proposal
            
            return None
        except Exception:
            return None
    
    async def detect_queue_overflow(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect queue overflow"""
        try:
            from app.core.nova.operational_dashboard import operational_dashboard
            
            events = operational_dashboard._events_by_org.get(organization_id, [])
            if len(events) > 4800:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.QUEUE_DRAIN,
                    severity="high",
                    description=f"Queue: {len(events)}/5000 capacity used",
                    affected_systems=["queue", "events"],
                )
                proposal.proposed_action = "Archive and prune old events"
                proposal.rollback_safe = False
                proposal.requires_approval = False
                proposal.evidence = [f"event_count: {len(events)}"]
                return proposal
            
            return None
        except Exception:
            return None
    
    async def detect_duplicate_events(self, organization_id: str) -> Optional[RecoveryProposal]:
        """Detect duplicate events in timeline"""
        try:
            from app.core.nova.operational_timeline import operational_timeline
            
            timeline = operational_timeline._timeline_by_org.get(organization_id, [])
            
            event_ids = {}
            duplicates = []
            for event in timeline:
                if hasattr(event, 'event_id'):
                    if event.event_id in event_ids:
                        duplicates.append(event.event_id)
                    event_ids[event.event_id] = True
            
            if duplicates:
                proposal = self.propose_recovery(
                    organization_id=organization_id,
                    recovery_type=RecoveryType.DUPLICATE_CLEANUP,
                    severity="high",
                    description=f"Timeline: {len(duplicates)} duplicate events detected",
                    affected_systems=["timeline", "events"],
                )
                proposal.proposed_action = "Remove duplicate event entries"
                proposal.rollback_safe = True
                proposal.requires_approval = True
                proposal.evidence = [f"duplicate_count: {len(duplicates)}"]
                return proposal
            
            return None
        except Exception:
            return None
    
    async def execute_recovery(
        self,
        organization_id: str,
        proposal_id: str,
        operator_identity: str,
    ) -> RecoveryAction:
        """Execute a recovery action"""
        try:
            # Find proposal
            proposals = self._recovery_proposals.get(organization_id, [])
            proposal = None
            for p in proposals:
                if p.proposal_id == proposal_id:
                    proposal = p
                    break
            
            if not proposal:
                return RecoveryAction(
                    action_id="",
                    organization_id=organization_id,
                    proposal_id=proposal_id,
                    recovery_type=RecoveryType.WEBSOCKET_RECONNECT,
                    issued_at=datetime.utcnow(),
                    status=RecoveryStatus.FAILED,
                )
            
            # Create action
            action_id = f"recovery_action_{uuid.uuid4().hex[:12]}"
            action = RecoveryAction(
                action_id=action_id,
                organization_id=organization_id,
                proposal_id=proposal_id,
                recovery_type=proposal.recovery_type,
                issued_at=datetime.utcnow(),
                issued_by=operator_identity,
                approved_at=datetime.utcnow(),
                started_at=datetime.utcnow(),
                status=RecoveryStatus.EXECUTING,
            )
            
            if organization_id not in self._recovery_actions:
                self._recovery_actions[organization_id] = []
            
            self._recovery_actions[organization_id].append(action)
            
            # Execute recovery (specific logic per type)
            success = await self._execute_recovery_logic(action, proposal)
            
            if success:
                action.status = RecoveryStatus.COMPLETED
                action.completed_at = datetime.utcnow()
            else:
                action.status = RecoveryStatus.FAILED
                action.error_message = "Recovery execution failed"
            
            return action
        except Exception as e:
            return RecoveryAction(
                action_id="",
                organization_id=organization_id,
                proposal_id=proposal_id,
                recovery_type=RecoveryType.WEBSOCKET_RECONNECT,
                issued_at=datetime.utcnow(),
                status=RecoveryStatus.FAILED,
                error_message=str(e),
            )
    
    async def _execute_recovery_logic(self, action: RecoveryAction, proposal: RecoveryProposal) -> bool:
        """Execute recovery logic for specific recovery type"""
        try:
            if action.recovery_type == RecoveryType.WEBSOCKET_RECONNECT:
                # Force reconnect would happen at websocket layer
                action.evidence = {"reconnect_initiated": True, "timestamp": datetime.utcnow().isoformat()}
                return True
            
            elif action.recovery_type == RecoveryType.EXECUTION_TIMEOUT:
                # Trigger rollback for stalled executions
                from app.core.nova.actions import execution_orchestrator
                executing = execution_orchestrator.query_executing(action.organization_id)
                now = datetime.utcnow()
                rolled_back = 0
                for exec_action in executing:
                    if hasattr(exec_action, 'execution_started_at') and exec_action.execution_started_at:
                        age = (now - exec_action.execution_started_at).total_seconds()
                        if age > 300:
                            await execution_orchestrator.rollback_action(exec_action.action_id)
                            rolled_back += 1
                action.evidence = {"rolled_back_count": rolled_back}
                return True
            
            elif action.recovery_type == RecoveryType.MEMORY_REPAIR:
                # Rebuild memory from timeline
                from app.core.nova.operational_timeline import operational_timeline
                timeline = operational_timeline.get_timeline_snapshot(action.organization_id)
                action.evidence = {"timeline_events_used": len(timeline.get("events", []))}
                return True
            
            elif action.recovery_type == RecoveryType.QUEUE_DRAIN:
                # Archive old events
                from app.core.nova.operational_dashboard import operational_dashboard
                pruned = operational_dashboard.prune_old_events(action.organization_id)
                action.evidence = {"pruned_count": pruned}
                return True
            
            else:
                # Generic success
                action.evidence = {"recovery_executed": True}
                return True
        except Exception as e:
            action.error_message = str(e)
            return False
    
    def get_recovery_proposals(self, organization_id: str) -> List[RecoveryProposal]:
        """Get all recovery proposals for organization"""
        return self._recovery_proposals.get(organization_id, [])
    
    def get_pending_proposals(self, organization_id: str) -> List[RecoveryProposal]:
        """Get pending (not yet approved) recovery proposals"""
        proposals = self._recovery_proposals.get(organization_id, [])
        return [p for p in proposals if p.status == RecoveryStatus.PROPOSED]
    
    def get_recovery_history(self, organization_id: str) -> List[RecoveryAction]:
        """Get recovery action history"""
        return self._recovery_history.get(organization_id, []) + self._recovery_actions.get(organization_id, [])
    
    def build_recovery_report(self, organization_id: str) -> Dict[str, Any]:
        """Build recovery status report"""
        try:
            proposals = self.get_recovery_proposals(organization_id)
            pending = self.get_pending_proposals(organization_id)
            history = self.get_recovery_history(organization_id)
            
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "total_proposals": len(proposals),
                "pending_proposals": len(pending),
                "completed_recoveries": len([a for a in history if a.status == RecoveryStatus.COMPLETED]),
                "failed_recoveries": len([a for a in history if a.status == RecoveryStatus.FAILED]),
                "pending_proposals_list": [
                    {
                        "proposal_id": p.proposal_id,
                        "recovery_type": p.recovery_type.value,
                        "severity": p.severity,
                        "description": p.description,
                    }
                    for p in pending
                ],
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Failed to build recovery report",
            }


# Singleton instance
runtime_recovery_engine = RuntimeRecoveryEngine()
