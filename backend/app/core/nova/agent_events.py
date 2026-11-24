"""Pure, side-effect-free Nova cross-agent event contract (draft v0.1).

This module does not dispatch jobs, read customer data, contact anyone, or authorize
actions. It intentionally does not modify the existing NovaAction/Core V1 schema.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Mapping


SCHEMA_VERSION = "nova.agent-event.v0.1"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class Agent(str, Enum):
    CREATIVE_STUDIO = "creative_studio"
    GROWTH = "growth"
    WORK_REVENUE = "work_revenue"
    OPERATIONS = "operations"
    HR = "hr"
    OWNER = "owner"


class EventType(str, Enum):
    ASSET_READY = "asset_ready"
    LEAD_CONSENTED = "lead_consented"
    LEAD_QUALIFIED = "lead_qualified"
    OPPORTUNITY_REVIEW = "opportunity_review"
    TASK_APPROVED = "task_approved"
    TASK_COMPLETED = "task_completed"
    HUMAN_ASSIGNMENT_NEEDED = "human_assignment_needed"
    FAILED = "failed"


# Narrow route permissions. A new route requires an explicit code review.
_ALLOWED_ROUTES = {
    EventType.ASSET_READY: {(Agent.CREATIVE_STUDIO, Agent.GROWTH)},
    EventType.LEAD_CONSENTED: {(Agent.GROWTH, Agent.WORK_REVENUE)},
    EventType.LEAD_QUALIFIED: {(Agent.GROWTH, Agent.WORK_REVENUE)},
    EventType.OPPORTUNITY_REVIEW: {(Agent.WORK_REVENUE, Agent.OWNER)},
    EventType.TASK_APPROVED: {(Agent.OWNER, Agent.OPERATIONS)},
    EventType.TASK_COMPLETED: {(Agent.OPERATIONS, Agent.OWNER)},
    EventType.HUMAN_ASSIGNMENT_NEEDED: {(Agent.OPERATIONS, Agent.HR)},
    EventType.FAILED: {
        (Agent.CREATIVE_STUDIO, Agent.OWNER),
        (Agent.GROWTH, Agent.OWNER),
        (Agent.WORK_REVENUE, Agent.OWNER),
        (Agent.OPERATIONS, Agent.OWNER),
        (Agent.HR, Agent.OWNER),
    },
}
_CONSENT_REQUIRED = {EventType.LEAD_CONSENTED, EventType.LEAD_QUALIFIED}
_APPROVAL_REQUIRED = {EventType.TASK_APPROVED}


def _identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{label} must be a nonempty opaque identifier (max 128)")


@dataclass(frozen=True)
class AgentEvent:
    schema_version: str
    event_id: str
    correlation_id: str
    organization_id: str
    source_agent: Agent
    target_agent: Agent
    event_type: EventType
    subject_kind: str
    subject_id: str
    synthetic: bool
    occurred_at: datetime
    idempotency_key: str
    payload_reference: str
    consent_reference: str | None = None
    approval_reference: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError("unsupported event schema version")
        for label in ("event_id", "correlation_id", "organization_id",
                      "subject_kind", "subject_id", "idempotency_key",
                      "payload_reference"):
            _identifier(getattr(self, label), label)
        if type(self.synthetic) is not bool:
            raise ValueError("synthetic must be boolean")
        if not isinstance(self.source_agent, Agent) or not isinstance(self.target_agent, Agent):
            raise ValueError("source_agent and target_agent must be Agent values")
        if not isinstance(self.event_type, EventType):
            raise ValueError("event_type must be a recognized EventType")
        if (self.source_agent, self.target_agent) not in _ALLOWED_ROUTES[self.event_type]:
            raise ValueError("cross-agent route not permitted")
        if not isinstance(self.occurred_at, datetime) or self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must have valid timezone offset")
        if self.event_type in _CONSENT_REQUIRED and not self.consent_reference:
            raise ValueError("lead handoff requires a consent reference")
        if self.event_type in _APPROVAL_REQUIRED and not self.approval_reference:
            raise ValueError("approved task handoff requires an approval reference")
        for label in ("consent_reference", "approval_reference"):
            value = getattr(self, label)
            if value is not None:
                _identifier(value, label)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> "AgentEvent":
        """Reject extra keys and freeform payload fields (including PII)."""
        if not isinstance(data, Mapping):
            raise ValueError("event must be a mapping")
        allowed = set(cls.__dataclass_fields__)
        unexpected = set(data) - allowed
        if unexpected:
            raise ValueError("unexpected event fields: " + ", ".join(sorted(unexpected)))
        try:
            raw_time = data["occurred_at"]
            if not isinstance(raw_time, str):
                raise ValueError("occurred_at must be RFC3339 text")
            date = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
            return cls(
                schema_version=data["schema_version"],
                event_id=data["event_id"],
                correlation_id=data["correlation_id"],
                organization_id=data["organization_id"],
                source_agent=Agent(data["source_agent"]),
                target_agent=Agent(data["target_agent"]),
                event_type=EventType(data["event_type"]),
                subject_kind=data["subject_kind"],
                subject_id=data["subject_id"],
                synthetic=data["synthetic"],
                occurred_at=date,
                idempotency_key=data["idempotency_key"],
                payload_reference=data["payload_reference"],
                consent_reference=data.get("consent_reference"),
                approval_reference=data.get("approval_reference"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid agent event: {exc}") from exc

    def to_mapping(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "organization_id": self.organization_id,
            "source_agent": self.source_agent.value,
            "target_agent": self.target_agent.value,
            "event_type": self.event_type.value,
            "subject_kind": self.subject_kind,
            "subject_id": self.subject_id,
            "synthetic": self.synthetic,
            "occurred_at": self.occurred_at.astimezone(timezone.utc).isoformat(),
            "idempotency_key": self.idempotency_key,
            "payload_reference": self.payload_reference,
            "consent_reference": self.consent_reference,
            "approval_reference": self.approval_reference,
        }


class SyntheticEventLedger:
    """In-memory rehearsal only; no authorization, dispatch or durable storage.

    Scope one instance to a single synthetic organization and journey.
    Exact replays return False; conflicting identifiers fail closed.
    Not safe for concurrent callers or production execution.
    """

    def __init__(self, organization_id: str, correlation_id: str) -> None:
        _identifier(organization_id, "organization_id")
        _identifier(correlation_id, "correlation_id")
        self._organization_id = organization_id
        self._correlation_id = correlation_id
        self._keys: dict[str, AgentEvent] = {}
        self._ids: dict[str, AgentEvent] = {}

    def record(self, item: AgentEvent) -> bool:
        if not isinstance(item, AgentEvent) or not item.synthetic:
            raise ValueError("synthetic event required")
        if (item.organization_id != self._organization_id
                or item.correlation_id != self._correlation_id):
            raise ValueError("event outside rehearsal scope")
        previous_key = self._keys.get(item.idempotency_key)
        previous_id = self._ids.get(item.event_id)
        if previous_key is not None or previous_id is not None:
            if previous_key == item and previous_id == item:
                return False
            raise ValueError("conflicting event replay")
        self._keys[item.idempotency_key] = item
        self._ids[item.event_id] = item
        return True
