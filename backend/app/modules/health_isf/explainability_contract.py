"""Explainability contract required for AI recommendations and predictions."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AIExplainabilityContract(BaseModel):
    reason: str
    evidence: list[dict] = Field(default_factory=list)
    confidence: float
    affected_systems: list[str] = Field(default_factory=list)
    operational_impact: str
    recommended_action: str
    rollback_impact: str
    tenant_scope: str
    reasoning_trace: list[str] = Field(default_factory=list)


def build_explainability(
    *,
    reason: str,
    evidence: list[dict],
    confidence: float,
    affected_systems: list[str],
    operational_impact: str,
    recommended_action: str,
    rollback_impact: str,
    tenant_scope: str,
    reasoning_trace: list[str],
) -> dict:
    contract = AIExplainabilityContract(
        reason=reason,
        evidence=evidence,
        confidence=max(0.0, min(1.0, float(confidence))),
        affected_systems=affected_systems,
        operational_impact=operational_impact,
        recommended_action=recommended_action,
        rollback_impact=rollback_impact,
        tenant_scope=tenant_scope,
        reasoning_trace=reasoning_trace,
    )
    return contract.model_dump()
