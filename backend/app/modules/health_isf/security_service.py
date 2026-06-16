"""Security services for enterprise audit and suspicious activity tracking."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.helpers import now, uuid4
from app.modules.health_isf.models import SecurityAuditAction, SecuritySuspiciousActivity


class SecurityAuditService:
    @staticmethod
    def log_action(
        db: Session,
        organization_id: str,
        action_type: str,
        actor_user_id: Optional[str] = None,
        target_user_id: Optional[str] = None,
        ride_id: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> SecurityAuditAction:
        record = SecurityAuditAction(
            id=uuid4(),
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            action_type=action_type,
            target_user_id=target_user_id,
            ride_id=ride_id,
            details=json.dumps(details) if details else None,
            created_at=now(),
        )
        db.add(record)
        db.commit()
        return record


class SuspiciousActivityService:
    @staticmethod
    def log_activity(
        db: Session,
        activity_type: str,
        organization_id: Optional[str] = None,
        user_id: Optional[str] = None,
        source_ip: Optional[str] = None,
        details: Optional[dict] = None,
    ) -> SecuritySuspiciousActivity:
        record = SecuritySuspiciousActivity(
            id=uuid4(),
            organization_id=organization_id,
            user_id=user_id,
            activity_type=activity_type,
            source_ip=source_ip,
            details=json.dumps(details) if details else None,
            created_at=now(),
        )
        db.add(record)
        db.commit()
        return record
