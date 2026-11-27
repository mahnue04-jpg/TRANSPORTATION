from __future__ import annotations

from typing import Any

from app.core.nova.growth_agent.commercial import UNIT_COST_MODEL
from app.core.nova.growth_agent.faq_engine import answer_from_faqs
from app.core.nova.growth_agent.providers.base import DeliveryResult


class MockAIAdapter:
    """Provider-neutral AI boundary. Caps tokens; grounds on FAQ only."""

    name = "mock_ai"
    live = False
    max_tokens_per_turn = 512
    max_concurrent = 2

    def complete(
        self,
        *,
        question: str,
        faqs: list[dict[str, Any]] | None,
        business_name: str,
        usage_tokens: int = 0,
        token_cap: int = 100_000,
    ) -> dict[str, Any]:
        if usage_tokens >= token_cap:
            return {
                "answer": (
                    "AI usage cap reached for this period. "
                    "Falling back to human escalation."
                ),
                "grounded": False,
                "escalate": True,
                "tokens_used": 0,
                "provider": self.name,
            }
        result = answer_from_faqs(question, faqs, business_name=business_name)
        # Rough token estimate for instrumentation only.
        tokens = min(self.max_tokens_per_turn, max(8, len(question.split()) + len(str(result.get("answer")).split())))
        result["tokens_used"] = tokens
        result["provider"] = self.name
        result["unit_cost_usd"] = tokens * float(UNIT_COST_MODEL["ai_token_estimate_usd"])
        return result

    def send(self, *, channel: str, payload: dict[str, Any]) -> DeliveryResult:
        out = self.complete(
            question=str(payload.get("question") or ""),
            faqs=payload.get("faqs") or [],
            business_name=str(payload.get("business_name") or "this business"),
        )
        return DeliveryResult(
            status="sent_mock",
            provider=self.name,
            cost_estimate_usd=float(out.get("unit_cost_usd") or 0),
            meta={"grounded": out.get("grounded"), "tokens_used": out.get("tokens_used")},
        )
