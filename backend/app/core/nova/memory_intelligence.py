"""
PHASE 7B: Memory Intelligence Fabric
Upgrade memory system from storage into operational intelligence fabric.
Provides execution replay, cross-session restoration, incident memory, operator decision tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any
import json


class MemoryType(Enum):
    """Memory classification"""
    EXECUTION_MEMORY = "execution_memory"
    INCIDENT_MEMORY = "incident_memory"
    OPERATOR_DECISION = "operator_decision"
    RECOMMENDATION_CONTEXT = "recommendation_context"
    DEPLOYMENT_HISTORY = "deployment_history"
    STAFFING_PATTERN = "staffing_pattern"
    DISPATCH_ANOMALY = "dispatch_anomaly"
    EVENT_CORRELATION = "event_correlation"


@dataclass
class ExecutionMemory:
    """Memory of action execution"""
    execution_id: str
    organization_id: str
    action_id: str
    action_type: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str = "pending"  # pending, completed, failed, rolled_back
    evidence: Dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0
    timeline_events: List[str] = field(default_factory=list)  # References to timeline event IDs
    recovery_actions: List[str] = field(default_factory=list)
    context_snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class IncidentMemory:
    """Memory of operational incident"""
    incident_id: str
    organization_id: str
    timestamp: datetime
    incident_type: str
    severity: str  # critical, high, medium, low
    root_cause: Optional[str] = None
    description: str = ""
    affected_executions: List[str] = field(default_factory=list)
    resolution_actions: List[str] = field(default_factory=list)
    lessons_learned: List[str] = field(default_factory=list)
    recovery_evidence: Dict[str, Any] = field(default_factory=dict)
    similar_incidents: List[str] = field(default_factory=list)


@dataclass
class OperatorDecisionRecord:
    """Memory of operator decision"""
    decision_id: str
    organization_id: str
    operator_identity: str
    timestamp: datetime
    decision_type: str  # approval, rejection, recovery, escalation
    target_action_id: Optional[str] = None
    decision_reason: str = ""
    outcome: str = "pending"  # pending, success, failed
    context_facts: List[str] = field(default_factory=list)
    evidence_cited: List[str] = field(default_factory=list)
    related_decisions: List[str] = field(default_factory=list)


@dataclass
class MemoryReplayContext:
    """Context for replaying a session"""
    organization_id: str
    session_id: str
    start_time: datetime
    end_time: datetime
    execution_memories: List[ExecutionMemory] = field(default_factory=list)
    incident_memories: List[IncidentMemory] = field(default_factory=list)
    operator_decisions: List[OperatorDecisionRecord] = field(default_factory=list)
    timeline_events: List[Dict[str, Any]] = field(default_factory=list)
    state_snapshots: Dict[str, Any] = field(default_factory=dict)


class MemoryIntelligenceFabric:
    """Upgrade memory system into operational intelligence fabric"""
    
    def __init__(self):
        """Initialize memory intelligence fabric"""
        self._execution_memories: Dict[str, List[ExecutionMemory]] = {}
        self._incident_memories: Dict[str, List[IncidentMemory]] = {}
        self._operator_decisions: Dict[str, List[OperatorDecisionRecord]] = {}
        self._memory_index: Dict[str, Dict[str, List[str]]] = {}  # org_id -> memory_type -> ids
        self._cross_session_index: Dict[str, Dict[str, Any]] = {}  # org_id -> session_data
    
    def record_execution_memory(
        self,
        organization_id: str,
        action_id: str,
        action_type: str,
        start_time: datetime,
    ) -> ExecutionMemory:
        """Record execution memory"""
        try:
            execution_id = f"exec_{action_id}_{int(start_time.timestamp())}"
            
            memory = ExecutionMemory(
                execution_id=execution_id,
                organization_id=organization_id,
                action_id=action_id,
                action_type=action_type,
                start_time=start_time,
            )
            
            if organization_id not in self._execution_memories:
                self._execution_memories[organization_id] = []
            
            self._execution_memories[organization_id].append(memory)
            self._index_memory(organization_id, MemoryType.EXECUTION_MEMORY.value, execution_id)
            
            return memory
        except Exception:
            return ExecutionMemory(
                execution_id="",
                organization_id=organization_id,
                action_id=action_id,
                action_type=action_type,
                start_time=start_time,
            )
    
    def complete_execution_memory(
        self,
        organization_id: str,
        execution_id: str,
        end_time: datetime,
        status: str,
        evidence: Dict[str, Any],
    ) -> bool:
        """Complete an execution memory record"""
        try:
            memories = self._execution_memories.get(organization_id, [])
            for mem in memories:
                if mem.execution_id == execution_id:
                    mem.end_time = end_time
                    mem.status = status
                    mem.evidence = evidence
                    mem.duration_ms = int((end_time - mem.start_time).total_seconds() * 1000)
                    return True
            return False
        except Exception:
            return False
    
    def record_incident_memory(
        self,
        organization_id: str,
        incident_type: str,
        severity: str,
        description: str,
    ) -> IncidentMemory:
        """Record incident memory"""
        try:
            import uuid
            incident_id = f"incident_{uuid.uuid4().hex[:12]}"
            
            memory = IncidentMemory(
                incident_id=incident_id,
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                incident_type=incident_type,
                severity=severity,
                description=description,
            )
            
            if organization_id not in self._incident_memories:
                self._incident_memories[organization_id] = []
            
            self._incident_memories[organization_id].append(memory)
            self._index_memory(organization_id, MemoryType.INCIDENT_MEMORY.value, incident_id)
            
            return memory
        except Exception:
            return IncidentMemory(
                incident_id="",
                organization_id=organization_id,
                timestamp=datetime.utcnow(),
                incident_type=incident_type,
                severity=severity,
            )
    
    def record_operator_decision(
        self,
        organization_id: str,
        operator_identity: str,
        decision_type: str,
        decision_reason: str = "",
        target_action_id: Optional[str] = None,
    ) -> OperatorDecisionRecord:
        """Record operator decision"""
        try:
            import uuid
            decision_id = f"decision_{uuid.uuid4().hex[:12]}"
            
            decision = OperatorDecisionRecord(
                decision_id=decision_id,
                organization_id=organization_id,
                operator_identity=operator_identity,
                timestamp=datetime.utcnow(),
                decision_type=decision_type,
                decision_reason=decision_reason,
                target_action_id=target_action_id,
            )
            
            if organization_id not in self._operator_decisions:
                self._operator_decisions[organization_id] = []
            
            self._operator_decisions[organization_id].append(decision)
            self._index_memory(organization_id, MemoryType.OPERATOR_DECISION.value, decision_id)
            
            return decision
        except Exception:
            return OperatorDecisionRecord(
                decision_id="",
                organization_id=organization_id,
                operator_identity=operator_identity,
                timestamp=datetime.utcnow(),
                decision_type=decision_type,
            )
    
    def replay_session(
        self,
        organization_id: str,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> MemoryReplayContext:
        """Replay a session from memory"""
        try:
            context = MemoryReplayContext(
                organization_id=organization_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
            )
            
            # Gather execution memories in time range
            exec_mems = self._execution_memories.get(organization_id, [])
            context.execution_memories = [
                m for m in exec_mems
                if start_time <= m.start_time <= end_time
            ]
            
            # Gather incident memories in time range
            inc_mems = self._incident_memories.get(organization_id, [])
            context.incident_memories = [
                m for m in inc_mems
                if start_time <= m.timestamp <= end_time
            ]
            
            # Gather operator decisions in time range
            op_decs = self._operator_decisions.get(organization_id, [])
            context.operator_decisions = [
                d for d in op_decs
                if start_time <= d.timestamp <= end_time
            ]
            
            return context
        except Exception:
            return MemoryReplayContext(
                organization_id=organization_id,
                session_id=session_id,
                start_time=start_time,
                end_time=end_time,
            )
    
    def restore_cross_session(
        self,
        organization_id: str,
    ) -> Dict[str, Any]:
        """Restore cross-session state for organization"""
        try:
            # Aggregate all memories
            all_exec = self._execution_memories.get(organization_id, [])
            all_inc = self._incident_memories.get(organization_id, [])
            all_op_dec = self._operator_decisions.get(organization_id, [])
            
            return {
                "organization_id": organization_id,
                "total_executions": len(all_exec),
                "total_incidents": len(all_inc),
                "total_decisions": len(all_op_dec),
                "last_execution": all_exec[-1].__dict__ if all_exec else None,
                "last_incident": all_inc[-1].__dict__ if all_inc else None,
                "last_decision": all_op_dec[-1].__dict__ if all_op_dec else None,
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Failed to restore cross-session state",
            }
    
    def get_incident_memory(self, organization_id: str, incident_id: str) -> Optional[IncidentMemory]:
        """Get incident memory"""
        try:
            memories = self._incident_memories.get(organization_id, [])
            for mem in memories:
                if mem.incident_id == incident_id:
                    return mem
            return None
        except Exception:
            return None
    
    def get_operator_decisions(
        self,
        organization_id: str,
        operator_identity: Optional[str] = None,
        decision_type: Optional[str] = None,
    ) -> List[OperatorDecisionRecord]:
        """Get operator decisions"""
        try:
            decisions = self._operator_decisions.get(organization_id, [])
            
            if operator_identity:
                decisions = [d for d in decisions if d.operator_identity == operator_identity]
            
            if decision_type:
                decisions = [d for d in decisions if d.decision_type == decision_type]
            
            return decisions
        except Exception:
            return []
    
    def get_execution_memories(self, organization_id: str) -> List[ExecutionMemory]:
        """Get execution memories"""
        return self._execution_memories.get(organization_id, [])
    
    def get_incident_memories(self, organization_id: str) -> List[IncidentMemory]:
        """Get incident memories"""
        return self._incident_memories.get(organization_id, [])
    
    def link_to_timeline(
        self,
        organization_id: str,
        memory_id: str,
        timeline_event_ids: List[str],
    ) -> bool:
        """Link memory record to timeline events"""
        try:
            # Link execution memory
            exec_mems = self._execution_memories.get(organization_id, [])
            for mem in exec_mems:
                if mem.execution_id == memory_id:
                    mem.timeline_events = timeline_event_ids
                    return True
            
            return False
        except Exception:
            return False
    
    def build_memory_snapshot(self, organization_id: str) -> Dict[str, Any]:
        """Build complete memory snapshot"""
        try:
            exec_mems = self._execution_memories.get(organization_id, [])
            inc_mems = self._incident_memories.get(organization_id, [])
            op_decs = self._operator_decisions.get(organization_id, [])
            
            # Calculate statistics
            completed_exec = [m for m in exec_mems if m.status == "completed"]
            failed_exec = [m for m in exec_mems if m.status == "failed"]
            
            avg_duration = sum(m.duration_ms for m in completed_exec) / len(completed_exec) if completed_exec else 0
            success_rate = len(completed_exec) / len(exec_mems) if exec_mems else 0
            
            return {
                "organization_id": organization_id,
                "timestamp": datetime.utcnow().isoformat(),
                "execution_memories": len(exec_mems),
                "incident_memories": len(inc_mems),
                "operator_decisions": len(op_decs),
                "execution_success_rate": success_rate,
                "average_execution_duration_ms": int(avg_duration),
                "critical_incidents": len([i for i in inc_mems if i.severity == "critical"]),
                "recent_executions": [
                    {
                        "execution_id": m.execution_id,
                        "status": m.status,
                        "duration_ms": m.duration_ms,
                    }
                    for m in exec_mems[-5:]
                ],
            }
        except Exception:
            return {
                "organization_id": organization_id,
                "error": "Failed to build memory snapshot",
            }
    
    def _index_memory(self, organization_id: str, memory_type: str, memory_id: str) -> None:
        """Index memory for fast lookup"""
        try:
            if organization_id not in self._memory_index:
                self._memory_index[organization_id] = {}
            if memory_type not in self._memory_index[organization_id]:
                self._memory_index[organization_id][memory_type] = []
            
            self._memory_index[organization_id][memory_type].append(memory_id)
        except Exception:
            pass


# Singleton instance
memory_intelligence_fabric = MemoryIntelligenceFabric()
