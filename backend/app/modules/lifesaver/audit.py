"""Lifesaver audit trail. Metadata must never include PHI or secrets."""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.helpers import now
from app.modules.lifesaver.models import LifesaverAuditEvent

logger = logging.getLogger("amicor.lifesaver.audit")

_BLOCKED_METADATA_KEYS = frozenset({
    "body",
    "note",
    "notes",
    "message",
    "instructions",
    "value",
    "value_primary",
    "value_secondary",
    "reading",
    "journal",
    "content",
    "password",
    "token",
    "secret",
    "email",
    "phone",
    "name",
    "title",
    "webhook",
    "access_token",
    "refresh_token",
    "result",
    "result_text",
    "diagnosis",
    "specimen",
    "lab_value",
    "measurement",
    "serial",
    "device_token",
})


def _safe_metadata(metadata: dict[str, Any] | None) -> str:
    clean: dict[str, Any] = {}
    for key, value in (metadata or {}).items():
        if key in _BLOCKED_METADATA_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            clean[key] = value[:20]
    return json.dumps(clean, ensure_ascii=True)


def write_audit(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: str,
    actor_profile_id: str | None,
    action: str,
    resource_type: str,
    resource_id: str | None,
    outcome: str,
    metadata: dict[str, Any] | None = None,
) -> LifesaverAuditEvent:
    event = LifesaverAuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        actor_profile_id=actor_profile_id,
        action=action[:64],
        resource_type=resource_type[:64],
        resource_id=resource_id,
        outcome=outcome[:16],
        metadata_json=_safe_metadata(metadata),
        created_at=now(),
    )
    db.add(event)
    logger.info(
        "lifesaver_audit action=%s resource_type=%s outcome=%s",
        action,
        resource_type,
        outcome,
    )
    return event
