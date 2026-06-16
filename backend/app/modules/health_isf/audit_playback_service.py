"""Audit playback helpers for supervisory review."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.modules.health_isf.ai_governance_engine import AIGovernanceEngine


class AuditPlaybackService:
    @staticmethod
    def build(db: Session, *, organization_id: str, limit: int = 25) -> dict[str, Any]:
        audits = AIGovernanceEngine.audit_snapshot(db, organization_id=organization_id, limit=limit)
        return {
            "enabled": True,
            "entries": audits,
            "count": len(audits),
            "replay_safe": True,
            "tenant_scoped": True,
        }
