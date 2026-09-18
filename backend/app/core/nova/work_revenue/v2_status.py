"""Internal Work & Revenue V2 status / monitoring snapshot. No secrets."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.auth import UserContext
from app.core.nova.work_revenue.adapters.registry import adapter_inventory
from app.core.nova.work_revenue.config import capabilities_surface
from app.core.nova.work_revenue.models import (
    NovaWorkHistoricalCorrection,
    NovaWorkPaymentEvent,
    NovaWorkRevenueEntry,
    NovaWorkSchedulerJob,
    NovaWorkSupervisedAction,
)
from app.core.nova.work_revenue.service import _ensure, _owner_filter
from app.helpers import now

LIVE_DISABLED = {
    "LIVE_DISCOVERY": "DISABLED",
    "EXTERNAL_SUBMISSION": "DISABLED",
    "CLIENT_CONTACT": "DISABLED",
    "REPORT_SEND": "DISABLED",
    "INVOICE_SEND": "DISABLED",
    "FINANCIAL_EXECUTION": "DISABLED",
    "BACKGROUND_WORKER": "DISABLED",
    "LIVE_CONNECTORS": "DISABLED",
}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _age_seconds(stamp: datetime | None) -> int | None:
    when = _aware(stamp)
    if when is None:
        return None
    return max(0, int((now() - when).total_seconds()))


def monitoring_snapshot(db: Session, *, organization_id: str, user: UserContext) -> dict[str, Any]:
    _ensure()
    actions = _owner_filter(
        db.query(NovaWorkSupervisedAction).filter(NovaWorkSupervisedAction.organization_id == organization_id),
        NovaWorkSupervisedAction,
        user,
    ).all()
    jobs = _owner_filter(
        db.query(NovaWorkSchedulerJob).filter(NovaWorkSchedulerJob.organization_id == organization_id),
        NovaWorkSchedulerJob,
        user,
    ).all()
    events = _owner_filter(
        db.query(NovaWorkPaymentEvent).filter(NovaWorkPaymentEvent.organization_id == organization_id),
        NovaWorkPaymentEvent,
        user,
    ).all()
    entries = _owner_filter(
        db.query(NovaWorkRevenueEntry).filter(NovaWorkRevenueEntry.organization_id == organization_id),
        NovaWorkRevenueEntry,
        user,
    ).all()
    corrections = _owner_filter(
        db.query(NovaWorkHistoricalCorrection).filter(
            NovaWorkHistoricalCorrection.organization_id == organization_id
        ),
        NovaWorkHistoricalCorrection,
        user,
    ).all()
    pending = [row for row in actions if row.status in {"DRAFT", "READY_FOR_REVIEW"}]
    waiting = [row for row in actions if row.status in {"OWNER_APPROVED", "QUEUED"}]
    expired = [row for row in actions if row.approval_status == "EXPIRED"]
    failed = [row for row in actions if row.status == "FAILED"]
    pending_ages = [_age_seconds(row.created_at) for row in pending]
    oldest = max(pending_ages) if pending_ages else 0
    caps = capabilities_surface()
    return {
        "version": "v2",
        "pending_actions": len(pending),
        "oldest_pending_age_seconds": oldest,
        "waiting_owner_review": len(pending),
        "approved_waiting": len(waiting),
        "prepared_jobs": len([row for row in jobs if row.status == "PREPARED"]),
        "skipped_jobs": len([row for row in jobs if row.status == "SKIPPED"]),
        "retryable_failures": 0,
        "final_failures": len(failed),
        "duplicate_suppression": len([row for row in events if row.duplicate]),
        "approval_expirations": len(expired),
        "partial_payment_count": len([row for row in entries if row.stage == "PARTIALLY_PAID"]),
        "historical_correction_count": len(corrections),
        "adapter_state": "DISABLED",
        "live_execution_state": "DISABLED",
        "scheduler_state": "PREPARE_ONLY",
        "continuous_worker": False,
        "adapters": adapter_inventory(),
        "live_capabilities": LIVE_DISABLED,
        "core_readiness": caps.get("core_readiness") or {},
        "secrets_exposed": False,
        "live_execution_implemented": False,
    }
