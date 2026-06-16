"""Supervisory oversight data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class SupervisoryControlSnapshot:
    organization_id: str
    generated_at: str
    approval_governed: bool
    recommendation_only: bool
    replay_safe: bool
    auditable: bool
    no_automatic_execution: bool
    approval_workflows: list[dict[str, Any]]
    recommendation_review_interfaces: list[dict[str, Any]]
    escalation_approval_checkpoints: list[dict[str, Any]]
    operational_override_controls: list[dict[str, Any]]
    reasoning_inspection: dict[str, Any]
    audit_playback: dict[str, Any]
    explainability_timelines: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "generated_at": self.generated_at,
            "approval_governed": bool(self.approval_governed),
            "recommendation_only": bool(self.recommendation_only),
            "replay_safe": bool(self.replay_safe),
            "auditable": bool(self.auditable),
            "no_automatic_execution": bool(self.no_automatic_execution),
            "approval_workflows": self.approval_workflows,
            "recommendation_review_interfaces": self.recommendation_review_interfaces,
            "escalation_approval_checkpoints": self.escalation_approval_checkpoints,
            "operational_override_controls": self.operational_override_controls,
            "reasoning_inspection": self.reasoning_inspection,
            "audit_playback": self.audit_playback,
            "explainability_timelines": self.explainability_timelines,
        }
