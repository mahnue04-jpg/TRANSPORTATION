"""
PHASE 7A: Execution Command Panel
Operator control actions and execution state management.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class CommandType(str, Enum):
    """Operator command types."""
    APPROVE_EXECUTION = "approve_execution"
    REJECT_EXECUTION = "reject_execution"
    TRIGGER_ROLLBACK = "trigger_rollback"
    RETRY_FAILED_ACTION = "retry_failed_action"
    PAUSE_EXECUTION_QUEUE = "pause_execution_queue"
    RESUME_EXECUTION_QUEUE = "resume_execution_queue"
    ACKNOWLEDGE_ALERT = "acknowledge_alert"
    ESCALATE_INCIDENT = "escalate_incident"


class CommandStatus(str, Enum):
    """Command execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionCommandState(str, Enum):
    """Extended execution command states."""
    PROPOSED = "proposed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ROLLBACK_REQUESTED = "rollback_requested"
    ROLLED_BACK = "rolled_back"
    FAILED = "failed"
    RECOVERED = "recovered"


@dataclass
class OperatorCommand:
    """Single operator command with full audit trail."""
    command_id: str
    command_type: CommandType
    organization_id: str
    operator_identity: str
    target_action_id: Optional[str] = None  # action being controlled
    target_alert_id: Optional[str] = None  # alert being acknowledged
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    issued_at: datetime = field(default_factory=datetime.utcnow)
    executed_at: Optional[datetime] = None
    command_status: CommandStatus = CommandStatus.PENDING
    evidence: Dict[str, Any] = field(default_factory=dict)  # Results
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with datetime serialization."""
        d = asdict(self)
        d["issued_at"] = self.issued_at.isoformat()
        d["executed_at"] = self.executed_at.isoformat() if self.executed_at else None
        d["command_type"] = self.command_type.value
        d["command_status"] = self.command_status.value
        return d


@dataclass
class ExecutionCommandPanel:
    """Execution command state for an action."""
    action_id: str
    organization_id: str
    action_type: str
    current_state: ExecutionCommandState
    execution_status: str  # From action_models.py ExecutionStatus
    title: str
    description: str
    created_at: datetime
    proposed_by: str  # AI/Nova
    approved_by: Optional[str] = None  # Operator identity
    approval_reason: Optional[str] = None
    executed_at: Optional[datetime] = None
    executed_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    rollback_requested_by: Optional[str] = None
    rollback_requested_at: Optional[datetime] = None
    rolled_back_at: Optional[datetime] = None
    rolled_back_by: Optional[str] = None
    failed_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    recovery_attempts: List[Dict[str, Any]] = field(default_factory=list)
    execution_evidence: Dict[str, Any] = field(default_factory=dict)
    rollback_availability: bool = True
    operator_commands: List[str] = field(default_factory=list)  # command_ids

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict with datetime serialization."""
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        approved_at = getattr(self, "approved_at", None)
        d["approved_at"] = approved_at.isoformat() if approved_at else None
        d["executed_at"] = self.executed_at.isoformat() if self.executed_at else None
        d["completed_at"] = (
            self.completed_at.isoformat() if self.completed_at else None
        )
        d["rollback_requested_at"] = (
            self.rollback_requested_at.isoformat()
            if self.rollback_requested_at
            else None
        )
        d["rolled_back_at"] = (
            self.rolled_back_at.isoformat() if self.rolled_back_at else None
        )
        d["failed_at"] = self.failed_at.isoformat() if self.failed_at else None
        d["current_state"] = self.current_state.value
        return d


class ExecutionCommandManager:
    """Manages operator commands and execution control state."""

    def __init__(self):
        """Initialize command manager."""
        self._commands: Dict[str, OperatorCommand] = {}  # command_id → command
        self._action_commands: Dict[str, List[str]] = {}  # action_id → [command_ids]
        self._org_commands: Dict[str, List[str]] = {}  # org_id → [command_ids]
        self._command_counter = 0

    def issue_command(self, command: OperatorCommand) -> OperatorCommand:
        """Issue a new operator command."""
        self._commands[command.command_id] = command

        # Index by action
        if command.target_action_id:
            if command.target_action_id not in self._action_commands:
                self._action_commands[command.target_action_id] = []
            self._action_commands[command.target_action_id].append(command.command_id)

        # Index by organization
        if command.organization_id not in self._org_commands:
            self._org_commands[command.organization_id] = []
        self._org_commands[command.organization_id].append(command.command_id)

        return command

    def get_action_commands(self, action_id: str) -> List[OperatorCommand]:
        """Get all commands issued for an action."""
        command_ids = self._action_commands.get(action_id, [])
        return [
            self._commands[cid] for cid in command_ids if cid in self._commands
        ]

    def get_command_by_id(self, command_id: str) -> Optional[OperatorCommand]:
        """Get command by ID."""
        return self._commands.get(command_id)

    def update_command_status(
        self,
        command_id: str,
        status: CommandStatus,
        executed_at: Optional[datetime] = None,
        evidence: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> Optional[OperatorCommand]:
        """Update command execution status."""
        if command_id not in self._commands:
            return None

        command = self._commands[command_id]
        command.command_status = status
        if executed_at:
            command.executed_at = executed_at
        if evidence:
            command.evidence.update(evidence)
        if error_message:
            command.error_message = error_message

        return command

    def get_pending_commands(self, organization_id: str) -> List[OperatorCommand]:
        """Get all pending commands for organization."""
        org_command_ids = self._org_commands.get(organization_id, [])
        return [
            self._commands[cid]
            for cid in org_command_ids
            if cid in self._commands and self._commands[cid].command_status in {
                CommandStatus.PENDING,
                CommandStatus.EXECUTING,
            }
        ]

    def get_command_audit_trail(
        self, organization_id: str, limit: int = 100
    ) -> List[OperatorCommand]:
        """Get audit trail of all commands for organization."""
        org_command_ids = self._org_commands.get(organization_id, [])
        commands = [self._commands[cid] for cid in org_command_ids if cid in self._commands]
        # Sort by issued_at descending (newest first)
        commands.sort(key=lambda c: c.issued_at, reverse=True)
        return commands[:limit]


# Singleton instance
execution_command_manager = ExecutionCommandManager()
