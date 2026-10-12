"""Inactive privacy-safe casting audit event formatter.

No event persistence or external logging is enabled. Inputs must come from
verified server-side actions. Never include applicant names, videos, notes,
storage locations, emails, or access tokens in an audit record.
"""
from __future__ import annotations
from datetime import datetime, timezone

ALLOWED_ACTIONS = frozenset({
    "campaign.created", "application.submitted", "application.withdrawn",
    "review.updated", "callback.proposed", "media.quarantined", "media.approved",
})


def casting_audit_event(*, actor_id: str, organization_id: str, action: str,
                        object_id: str, occurred_at: str | None = None) -> dict[str, str]:
    if not all(isinstance(x, str) and x.strip() for x in (actor_id, organization_id, object_id)):
        raise ValueError("Verified actor, organization and object identifiers required")
    if action not in ALLOWED_ACTIONS:
        raise ValueError("Unsupported casting audit action")
    return {
        "actor_id": actor_id,
        "organization_id": organization_id,
        "action": action,
        "object_id": object_id,
        "occurred_at": occurred_at or datetime.now(timezone.utc).isoformat(),
    }
