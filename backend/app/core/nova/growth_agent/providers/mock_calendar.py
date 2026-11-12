from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.nova.growth_agent.flags import REAL_CALENDAR_WRITE
from app.core.nova.growth_agent.providers.base import DeliveryResult


class MockCalendarAdapter:
    """Boundary adapter for Google/Microsoft. Live writes remain off."""

    name = "mock_calendar"
    live = False

    def send(self, *, channel: str, payload: dict[str, Any]) -> DeliveryResult:
        return self.write_event(payload)

    def write_event(self, payload: dict[str, Any]) -> DeliveryResult:
        if REAL_CALENDAR_WRITE or payload.get("live"):
            return DeliveryResult(
                status="suppressed",
                provider=self.name,
                error_code="LIVE_CALENDAR_DISABLED",
                meta={"reason": "External calendar OAuth/write is default-off"},
            )
        return DeliveryResult(
            status="sent_mock",
            provider=self.name,
            external_id=f"mock-cal-{uuid4().hex[:12]}",
            meta={"action": payload.get("action") or "create", "provider_target": "none"},
        )
