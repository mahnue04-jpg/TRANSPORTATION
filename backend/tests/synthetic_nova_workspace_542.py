"""Read-only synthetic Workspace projection for acceptance tests, not an API.

Accepts only disposable replay-ledger state. Does not access customer, CRM,
backend databases, external APIs, or enable task execution.
"""
from __future__ import annotations

from dataclasses import dataclass

from synthetic_nova_replay_542 import SyntheticReplayLedger


STAGES = (
    ("qualified", "growth", "work_revenue"),
    ("pending_approval", "work_revenue", "owner"),
    ("approved", "owner", "operations"),
    ("completed", "operations", "owner"),
)


@dataclass(frozen=True)
class JourneyView:
    correlation_id: str
    status: str
    assigned_agent: str
    events: tuple[tuple[str, str, str], ...]
    pending_owner_approval: bool


def read_synthetic_journey(
    ledger: SyntheticReplayLedger, *, organization_id: str,
    correlation_id: str, viewer_organization: str, viewer_role: str,
) -> JourneyView:
    """Fail closed for non-owner/non-tenant readers; return metadata only."""
    if (not organization_id or not correlation_id or
            viewer_role != "owner" or viewer_organization != organization_id):
        raise PermissionError("owner organization authorization required")
    stages = ledger.steps(organization_id, correlation_id)
    if not stages:
        return JourneyView(correlation_id, "not_found", "none", (), False)
    if stages != tuple(range(len(stages))) or len(stages) > len(STAGES):
        raise ValueError("invalid synthetic journey stage sequence")
    events = tuple(STAGES[step] for step in stages)
    status = events[-1][0]
    assigned_agent = events[-1][2]
    return JourneyView(
        correlation_id=correlation_id,
        status=status,
        assigned_agent=assigned_agent,
        events=events,
        pending_owner_approval=(status == "pending_approval"),
    )
