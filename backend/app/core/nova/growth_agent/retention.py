"""Tenant-scoped retention cleanup — dry-run by default, delete gated off.

Respects documented retention exceptions (consent records are retained).
Audits record counts only — never personal data.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.flags import retention_delete_enabled
from app.core.nova.growth_agent.models import (
    GaAuditEvent,
    GaConversationMessage,
    GaDeliveryAttempt,
    GaLeadEvent,
    GaRateLimitCounter,
    GaUsageEvent,
)

DEFAULT_RETENTION_DAYS = {
    "conversation_messages": 365,
    "delivery_attempts": 365,
    "usage_events": 365,
    "lead_events": 365,
    "audit_events": 730,
    "rate_limit_counters": 7,
}

# Legal / policy exceptions — never auto-deleted by this job.
RETAIN_ALWAYS = (
    "consent_records",
    "business_profiles",
    "contacts",
    "contact_identities",
    "appointments",  # scheduling history kept unless owner wipe
)


def _env_days(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return max(1, min(int(raw), 3650))
    except ValueError:
        return default


def effective_retention_days() -> dict[str, int]:
    return {
        "conversation_messages": _env_days(
            "NOVA_GROWTH_AGENT_RETENTION_MESSAGES_DAYS",
            DEFAULT_RETENTION_DAYS["conversation_messages"],
        ),
        "delivery_attempts": _env_days(
            "NOVA_GROWTH_AGENT_RETENTION_DELIVERY_DAYS",
            DEFAULT_RETENTION_DAYS["delivery_attempts"],
        ),
        "usage_events": _env_days(
            "NOVA_GROWTH_AGENT_RETENTION_USAGE_DAYS",
            DEFAULT_RETENTION_DAYS["usage_events"],
        ),
        "lead_events": _env_days(
            "NOVA_GROWTH_AGENT_RETENTION_LEAD_EVENTS_DAYS",
            DEFAULT_RETENTION_DAYS["lead_events"],
        ),
        "audit_events": _env_days(
            "NOVA_GROWTH_AGENT_RETENTION_AUDIT_DAYS",
            DEFAULT_RETENTION_DAYS["audit_events"],
        ),
        "rate_limit_counters": _env_days(
            "NOVA_GROWTH_AGENT_RETENTION_RATE_LIMIT_DAYS",
            DEFAULT_RETENTION_DAYS["rate_limit_counters"],
        ),
    }


def _cutoff(days: int) -> datetime:
    return datetime.utcnow() - timedelta(days=int(days))


def preview_retention(
    db: Session,
    organization_id: str,
    *,
    batch_limit: int = 500,
) -> dict[str, Any]:
    """Count eligible rows per category without deleting."""
    org = (organization_id or "").strip()
    if not org:
        raise GrowthAgentError("TENANT_REQUIRED", "organization_id required", http_status=403)
    days = effective_retention_days()
    limit = max(1, min(int(batch_limit), 2000))
    categories: dict[str, Any] = {}

    msg_cut = _cutoff(days["conversation_messages"])
    msg_q = db.query(GaConversationMessage).filter(
        GaConversationMessage.organization_id == org,
        GaConversationMessage.created_at < msg_cut,
    )
    categories["conversation_messages"] = {
        "retention_days": days["conversation_messages"],
        "eligible_count": msg_q.count(),
        "batch_limit": limit,
        "would_delete": min(msg_q.count(), limit),
    }

    del_cut = _cutoff(days["delivery_attempts"])
    del_q = db.query(GaDeliveryAttempt).filter(
        GaDeliveryAttempt.organization_id == org,
        GaDeliveryAttempt.created_at < del_cut,
        GaDeliveryAttempt.status.in_(["sent_mock", "failed", "suppressed"]),
    )
    categories["delivery_attempts"] = {
        "retention_days": days["delivery_attempts"],
        "eligible_count": del_q.count(),
        "batch_limit": limit,
        "would_delete": min(del_q.count(), limit),
    }

    usage_cut = _cutoff(days["usage_events"])
    usage_q = db.query(GaUsageEvent).filter(
        GaUsageEvent.organization_id == org,
        GaUsageEvent.created_at < usage_cut,
    )
    categories["usage_events"] = {
        "retention_days": days["usage_events"],
        "eligible_count": usage_q.count(),
        "batch_limit": limit,
        "would_delete": min(usage_q.count(), limit),
    }

    lead_cut = _cutoff(days["lead_events"])
    lead_q = db.query(GaLeadEvent).filter(
        GaLeadEvent.organization_id == org,
        GaLeadEvent.created_at < lead_cut,
    )
    categories["lead_events"] = {
        "retention_days": days["lead_events"],
        "eligible_count": lead_q.count(),
        "batch_limit": limit,
        "would_delete": min(lead_q.count(), limit),
    }

    audit_cut = _cutoff(days["audit_events"])
    audit_q = db.query(GaAuditEvent).filter(
        GaAuditEvent.organization_id == org,
        GaAuditEvent.created_at < audit_cut,
    )
    categories["audit_events"] = {
        "retention_days": days["audit_events"],
        "eligible_count": audit_q.count(),
        "batch_limit": limit,
        "would_delete": min(audit_q.count(), limit),
    }

    rate_cut = _cutoff(days["rate_limit_counters"])
    # window_start is epoch seconds
    rate_floor = int(rate_cut.timestamp())
    rate_q = db.query(GaRateLimitCounter).filter(
        GaRateLimitCounter.organization_id == org,
        GaRateLimitCounter.window_start < rate_floor,
    )
    categories["rate_limit_counters"] = {
        "retention_days": days["rate_limit_counters"],
        "eligible_count": rate_q.count(),
        "batch_limit": limit,
        "would_delete": min(rate_q.count(), limit),
    }

    return {
        "organization_id": org,
        "dry_run": True,
        "delete_enabled": retention_delete_enabled(),
        "retain_always": list(RETAIN_ALWAYS),
        "categories": categories,
        "total_would_delete": sum(int(c["would_delete"]) for c in categories.values()),
        "note": "Preview only. Consent/contacts/appointments are retained. No PII in this payload.",
    }


def execute_retention(
    db: Session,
    organization_id: str,
    *,
    batch_limit: int = 500,
    actor_user_id: str | None = None,
    force_enabled: bool = False,
) -> dict[str, Any]:
    """Delete a bounded batch of expired rows when explicitly enabled."""
    if not (retention_delete_enabled() or force_enabled):
        raise GrowthAgentError(
            "RETENTION_DELETE_DISABLED",
            "Set NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED=true to allow deletion",
            http_status=403,
        )
    preview = preview_retention(db, organization_id, batch_limit=batch_limit)
    org = organization_id
    days = effective_retention_days()
    limit = max(1, min(int(batch_limit), 2000))
    deleted: dict[str, int] = {}

    def _delete_ids(model, ids: list[str]) -> int:
        if not ids:
            return 0
        return (
            db.query(model)
            .filter(model.organization_id == org, model.id.in_(ids))
            .delete(synchronize_session=False)
        )

    msg_cut = _cutoff(days["conversation_messages"])
    msg_ids = [
        r[0]
        for r in db.query(GaConversationMessage.id)
        .filter(
            GaConversationMessage.organization_id == org,
            GaConversationMessage.created_at < msg_cut,
        )
        .order_by(GaConversationMessage.created_at.asc())
        .limit(limit)
        .all()
    ]
    deleted["conversation_messages"] = _delete_ids(GaConversationMessage, msg_ids)

    del_cut = _cutoff(days["delivery_attempts"])
    del_ids = [
        r[0]
        for r in db.query(GaDeliveryAttempt.id)
        .filter(
            GaDeliveryAttempt.organization_id == org,
            GaDeliveryAttempt.created_at < del_cut,
            GaDeliveryAttempt.status.in_(["sent_mock", "failed", "suppressed"]),
        )
        .order_by(GaDeliveryAttempt.created_at.asc())
        .limit(limit)
        .all()
    ]
    deleted["delivery_attempts"] = _delete_ids(GaDeliveryAttempt, del_ids)

    usage_cut = _cutoff(days["usage_events"])
    usage_ids = [
        r[0]
        for r in db.query(GaUsageEvent.id)
        .filter(GaUsageEvent.organization_id == org, GaUsageEvent.created_at < usage_cut)
        .order_by(GaUsageEvent.created_at.asc())
        .limit(limit)
        .all()
    ]
    deleted["usage_events"] = _delete_ids(GaUsageEvent, usage_ids)

    lead_cut = _cutoff(days["lead_events"])
    lead_ids = [
        r[0]
        for r in db.query(GaLeadEvent.id)
        .filter(GaLeadEvent.organization_id == org, GaLeadEvent.created_at < lead_cut)
        .order_by(GaLeadEvent.created_at.asc())
        .limit(limit)
        .all()
    ]
    deleted["lead_events"] = _delete_ids(GaLeadEvent, lead_ids)

    audit_cut = _cutoff(days["audit_events"])
    audit_ids = [
        r[0]
        for r in db.query(GaAuditEvent.id)
        .filter(GaAuditEvent.organization_id == org, GaAuditEvent.created_at < audit_cut)
        .order_by(GaAuditEvent.created_at.asc())
        .limit(limit)
        .all()
    ]
    deleted["audit_events"] = _delete_ids(GaAuditEvent, audit_ids)

    rate_floor = int(_cutoff(days["rate_limit_counters"]).timestamp())
    rate_ids = [
        r[0]
        for r in db.query(GaRateLimitCounter.id)
        .filter(
            GaRateLimitCounter.organization_id == org,
            GaRateLimitCounter.window_start < rate_floor,
        )
        .order_by(GaRateLimitCounter.window_start.asc())
        .limit(limit)
        .all()
    ]
    deleted["rate_limit_counters"] = _delete_ids(GaRateLimitCounter, rate_ids)

    # Audit without personal data — counts only.
    audit = GaAuditEvent(
        id=__import__("uuid").uuid4().hex,
        organization_id=org,
        actor_user_id=actor_user_id,
        action="retention.execute",
        entity_type="retention",
        entity_id=None,
        summary=f"Retention cleanup deleted {sum(deleted.values())} rows (batched)",
        payload_redacted_json={
            "deleted_counts": deleted,
            "batch_limit": limit,
            "retain_always": list(RETAIN_ALWAYS),
            "preview_total_would_delete": preview.get("total_would_delete"),
        },
    )
    db.add(audit)
    db.commit()
    return {
        "organization_id": org,
        "dry_run": False,
        "delete_enabled": True,
        "deleted_counts": deleted,
        "total_deleted": sum(deleted.values()),
        "retain_always": list(RETAIN_ALWAYS),
        "batch_limit": limit,
        "note": "Deletion counts only. Consent/contacts/appointments retained. No PII in audit payload.",
    }
