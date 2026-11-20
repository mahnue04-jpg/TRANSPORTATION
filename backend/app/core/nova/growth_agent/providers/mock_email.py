from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.nova.growth_agent.commercial import UNIT_COST_MODEL
from app.core.nova.growth_agent.flags import REAL_EMAIL_SEND
from app.core.nova.growth_agent.providers.base import DeliveryResult
from app.core.nova.growth_agent.redact import redact_mapping


class MockEmailAdapter:
    name = "mock_email"
    live = False

    def send(self, *, channel: str, payload: dict[str, Any]) -> DeliveryResult:
        if REAL_EMAIL_SEND or payload.get("live"):
            return DeliveryResult(
                status="suppressed",
                provider=self.name,
                error_code="LIVE_EMAIL_DISABLED",
                meta={"reason": "Real email send is hard-off"},
            )
        return DeliveryResult(
            status="sent_mock",
            provider=self.name,
            cost_estimate_usd=float(UNIT_COST_MODEL["email_mock"]),
            external_id=f"mock-email-{uuid4().hex[:12]}",
            meta={"preview": redact_mapping({"subject": payload.get("subject"), "to": "[REDACTED]"})},
        )
