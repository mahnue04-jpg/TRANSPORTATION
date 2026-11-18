"""Fictional Creative Studio -> Growth bridge for the first Nova business demo.

Pure test-only code. Never imports a service, connects to a CRM, sends an ad,
reads media, contacts a customer, or executes an agent task.
"""
from __future__ import annotations

from datetime import datetime

from synthetic_nova_handoff_542 import Agent, AgentEvent, EventType, Principal


class SyntheticCampaignBridge:
    """Require a legitimate mock Creative Studio asset before Growth lead intake."""

    def __init__(self, organization_id: str, now: datetime):
        self.organization_id = organization_id
        self.now = now
        self._campaigns: dict[str, AgentEvent] = {}
        self._ids: dict[str, AgentEvent] = {}

    def accept_asset(self, event: AgentEvent, caller: Principal) -> str:
        if (event.event_type != EventType.ASSET_READY
                or event.source_agent != Agent.CREATIVE_STUDIO
                or event.target_agent != Agent.GROWTH
                or type(event.synthetic) is not bool or not event.synthetic):
            raise PermissionError("only fictional Creative Studio assets are accepted")
        if (caller.role != "agent" or caller.agent != Agent.CREATIVE_STUDIO
                or caller.organization_id != self.organization_id
                or event.organization_id != self.organization_id):
            raise PermissionError("Creative Studio principal and tenant required")
        if (event.subject_kind != "campaign"
                or not event.payload_reference.startswith("synthetic:")
                or event.occurred_at > self.now
                or (self.now - event.occurred_at).total_seconds() > 300):
            raise PermissionError("invalid fictional campaign asset")
        existing = self._campaigns.get(event.correlation_id)
        collision = self._ids.get(event.event_id)
        if collision is not None and collision != event:
            raise PermissionError("campaign event id collision")
        if existing is not None:
            if existing == event:
                return "duplicate"
            raise PermissionError("campaign correlation collision")
        self._campaigns[event.correlation_id] = event
        self._ids[event.event_id] = event
        return "asset_ready"

    def require_asset_for_lead(self, event: AgentEvent) -> None:
        asset = self._campaigns.get(event.correlation_id)
        if (asset is None or event.event_type != EventType.LEAD_QUALIFIED
                or event.source_agent != Agent.GROWTH
                or event.target_agent != Agent.WORK_REVENUE
                or not event.synthetic
                or event.organization_id != self.organization_id
                or asset.organization_id != event.organization_id):
            raise PermissionError("Growth lead requires prior fictional campaign asset")
