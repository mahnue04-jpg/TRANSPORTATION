from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.core.nova.growth_agent.commercial import UNIT_COST_MODEL
from app.core.nova.growth_agent.flags import REAL_SMS_SEND
from app.core.nova.growth_agent.providers.base import DeliveryResult


class MockSmsAdapter:
    name = "mock_sms"
    live = False

    def send(self, *, channel: str, payload: dict[str, Any]) -> DeliveryResult:
        if REAL_SMS_SEND or payload.get("live"):
            return DeliveryResult(
                status="suppressed",
                provider=self.name,
                error_code="LIVE_SMS_DISABLED",
                meta={"reason": "Real SMS send is hard-off"},
            )
        body = str(payload.get("body") or "")
        return DeliveryResult(
            status="sent_mock",
            provider=self.name,
            cost_estimate_usd=float(UNIT_COST_MODEL["sms_mock"]),
            external_id=f"mock-sms-{uuid4().hex[:12]}",
            meta={"body_len": len(body), "to": "[REDACTED]"},
        )
