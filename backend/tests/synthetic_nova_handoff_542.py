"""Synthetic-only Nova handoff acceptance harness. Not an application dispatcher.

Isolated in tests: no database, network, provider, real customer, or production route.
It proves policy decisions for a representative flow; real adapters must be separately
reviewed for authenticated identities, durable audit, restart safety and RBAC.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping

# Import the event envelope without importing Nova's backend package or conftest.
import importlib.util
from pathlib import Path
import sys

_EVENT_PATH = Path(__file__).resolve().parents[1] / "app/core/nova/agent_events.py"
_spec = importlib.util.spec_from_file_location("nova_handoff_events_542", _EVENT_PATH)
_module = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _module
_spec.loader.exec_module(_module)
Agent, EventType, AgentEvent, SCHEMA_VERSION = (
    _module.Agent, _module.EventType, _module.AgentEvent, _module.SCHEMA_VERSION
)


@dataclass(frozen=True)
class Principal:
    identity: str
    organization_id: str
    role: str
    agent: Agent | None = None


@dataclass(frozen=True)
class Consent:
    reference: str
    organization_id: str
    subject_id: str
    valid_until: datetime
    revoked: bool = False


@dataclass(frozen=True)
class Approval:
    reference: str
    organization_id: str
    subject_id: str
    action: str
    owner_id: str
    valid_until: datetime
    revoked: bool = False


class SyntheticHandoff:
    """In-memory, deterministic review harness with no executable side effects."""

    def __init__(self, organization_id: str, now: datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        self.organization_id = organization_id
        self.now = now
        self.consent: dict[str, Consent] = {}
        self.approvals: dict[str, Approval] = {}
        self.audit: list[tuple[str, str]] = []
        self._seen: dict[str, AgentEvent] = {}
        self._journeys: dict[str, str] = {}
        self._subjects: dict[str, str] = {}
        self._payloads: set[str] = set()
        self._used_approvals: set[str] = set()

    def register_payload(self, reference: str):
        if not reference.startswith("synthetic:"):
            raise ValueError("only synthetic payload references allowed")
        self._payloads.add(reference)

    def stage_consent(self, item: Consent):
        if item.organization_id != self.organization_id:
            raise PermissionError("wrong organization")
        self.consent[item.reference] = item

    def stage_approval(self, item: Approval, owner: Principal):
        if owner.role != "owner" or owner.organization_id != self.organization_id:
            raise PermissionError("owner role required")
        if item.owner_id != owner.identity or item.organization_id != self.organization_id:
            raise PermissionError("approval owner or organization mismatch")
        self.approvals[item.reference] = item

    def handle(self, event: AgentEvent, caller: Principal) -> str:
        if type(event.synthetic) is not bool or not event.synthetic:
            raise PermissionError("live events forbidden")
        if caller.organization_id != self.organization_id or event.organization_id != self.organization_id:
            raise PermissionError("cross-tenant event denied")
        if (event.source_agent == Agent.OWNER and
                (caller.role != "owner" or caller.agent is not None)):
            raise PermissionError("owner identity required")
        if (event.source_agent != Agent.OWNER and
                (caller.role != "agent" or caller.agent != event.source_agent)):
            raise PermissionError("authenticated source mismatch")
        if event.occurred_at > self.now or (self.now - event.occurred_at).total_seconds() > 300:
            raise PermissionError("stale or future event")
        if event.payload_reference not in self._payloads:
            raise PermissionError("unauthorized payload reference")
        if event.idempotency_key in self._seen:
            if self._seen[event.idempotency_key] != event:
                raise PermissionError("idempotency collision")
            return "duplicate"
        if event.correlation_id in self._subjects and self._subjects[event.correlation_id] != event.subject_id:
            raise PermissionError("journey subject mismatch")

        expected = {
            EventType.LEAD_QUALIFIED: (None, "qualified"),
            EventType.OPPORTUNITY_REVIEW: ("qualified", "pending_approval"),
            EventType.TASK_APPROVED: ("pending_approval", "approved"),
            EventType.TASK_COMPLETED: ("approved", "completed"),
        }
        if event.event_type not in expected:
            raise PermissionError("handoff outside synthetic acceptance scope")
        required, next_state = expected[event.event_type]
        if self._journeys.get(event.correlation_id) != required:
            raise PermissionError("out-of-order handoff")
        if event.event_type == EventType.LEAD_QUALIFIED:
            c = self.consent.get(event.consent_reference or "")
            if (not c or c.revoked or c.organization_id != self.organization_id or
                    c.subject_id != event.subject_id or c.valid_until <= self.now):
                raise PermissionError("missing, revoked, expired or mismatched consent")
        if event.event_type == EventType.TASK_APPROVED:
            a = self.approvals.get(event.approval_reference or "")
            if (not a or a.revoked or a.organization_id != self.organization_id or
                    a.subject_id != event.subject_id or a.action != "execute_mock_task" or
                    a.owner_id != caller.identity or a.valid_until <= self.now or
                    a.reference in self._used_approvals):
                raise PermissionError("missing, replayed or mismatched approval")
            self._used_approvals.add(a.reference)

        self._subjects[event.correlation_id] = event.subject_id
        self._seen[event.idempotency_key] = event
        self._journeys[event.correlation_id] = next_state
        self.audit.append((event.correlation_id, next_state))
        return next_state

    def journey(self, correlation_id: str, viewer: Principal) -> tuple[str, ...]:
        if viewer.role != "owner" or viewer.organization_id != self.organization_id:
            raise PermissionError("owner organization access required")
        return tuple(state for key, state in self.audit if key == correlation_id)
