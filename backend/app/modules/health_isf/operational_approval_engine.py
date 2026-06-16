"""Human oversight snapshot over governance approvals and recommendation review."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.ai_governance_engine import AIGovernanceEngine
from app.modules.health_isf.supervisory_control_models import SupervisoryControlSnapshot


class OperationalApprovalEngine:
    @staticmethod
    def build_snapshot(db: Session, *, organization_id: str, coordination: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        approvals = AIGovernanceEngine.approval_snapshot(db, organization_id=organization_id, limit=25)
        review_interfaces = [
            {
                "recommendation_id": item.get("recommendation_id"),
                "review_required": True,
                "approval_required": bool(item.get("approval_required")),
                "confidence": item.get("confidence"),
            }
            for item in (coordination.get("recommendations") or [])[:10]
        ]
        checkpoints = [
            {
                "stage": "escalation_review",
                "approval_required": True,
                "replay_safe": True,
            },
            {
                "stage": "override_review",
                "approval_required": True,
                "replay_safe": True,
            },
        ]
        overrides = [
            {
                "override_mode": "manual_only",
                "automatic_execution": False,
                "auditable": True,
            }
        ]
        snapshot = SupervisoryControlSnapshot(
            organization_id=organization_id,
            generated_at=datetime.utcnow().isoformat(),
            approval_governed=True,
            recommendation_only=True,
            replay_safe=True,
            auditable=True,
            no_automatic_execution=True,
            approval_workflows=approvals,
            recommendation_review_interfaces=review_interfaces,
            escalation_approval_checkpoints=checkpoints,
            operational_override_controls=overrides,
            reasoning_inspection={
                "decision_reasoning_count": len([item for item in (decision.get("recommendations") or []) if item.get("reasoning_chain")]),
                "coordination_reasoning_count": len([item for item in (coordination.get("recommendations") or []) if item.get("reasoning_chain")]),
            },
            audit_playback={
                "enabled": True,
                "approval_count": len(approvals),
                "replay_safe": True,
            },
            explainability_timelines=[
                {
                    "timeline": "recommendation_review",
                    "explainable": True,
                    "auditable": True,
                }
            ],
        )
        return snapshot.to_dict()
