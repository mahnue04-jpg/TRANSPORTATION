"""Operational memory fabric contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class OperationalMemorySnapshot:
    organization_id: str
    generated_at: str
    backend_authoritative: bool
    tenant_scoped: bool
    replay_safe: bool
    auditable: bool
    explainable_memory_references: bool
    incident_history_memory: list[dict[str, Any]]
    escalation_pattern_memory: list[dict[str, Any]]
    provider_continuity_history: list[dict[str, Any]]
    driver_operational_trend_memory: list[dict[str, Any]]
    operational_congestion_history: list[dict[str, Any]]
    regional_operational_learning: list[dict[str, Any]]
    pattern_summary: dict[str, Any]
    recall_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "generated_at": self.generated_at,
            "backend_authoritative": bool(self.backend_authoritative),
            "tenant_scoped": bool(self.tenant_scoped),
            "replay_safe": bool(self.replay_safe),
            "auditable": bool(self.auditable),
            "explainable_memory_references": bool(self.explainable_memory_references),
            "incident_history_memory": self.incident_history_memory,
            "escalation_pattern_memory": self.escalation_pattern_memory,
            "provider_continuity_history": self.provider_continuity_history,
            "driver_operational_trend_memory": self.driver_operational_trend_memory,
            "operational_congestion_history": self.operational_congestion_history,
            "regional_operational_learning": self.regional_operational_learning,
            "pattern_summary": self.pattern_summary,
            "recall_summary": self.recall_summary,
        }
