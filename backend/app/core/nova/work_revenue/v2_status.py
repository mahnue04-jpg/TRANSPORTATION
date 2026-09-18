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
from app.core.nova.work_revenue.service import _ensure_v2, _owner_filter
from app.core.nova.work_revenue.managed import reconciliation as v1_reconciliation
from app.core.nova.work_revenue.v2_revenue import revenue_preparation
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
    _ensure_v2()
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
    pending = [row for row in actions if row.status == "DRAFT"]
    waiting_review = [row for row in actions if row.status == "READY_FOR_REVIEW"]
    expired = [row for row in actions if row.approval_status == "EXPIRED"]
    failed = [row for row in actions if row.status == "FAILED"]
    approved_waiting = [row for row in actions if row.status in {"OWNER_APPROVED", "QUEUED"}]
    pending_ages = [_age_seconds(row.created_at) for row in pending]
    oldest = max(pending_ages) if pending_ages else 0
    caps = capabilities_surface()
    recon = v1_reconciliation(db, organization_id=organization_id, user=user)
    prep = revenue_preparation(db, organization_id=organization_id, user=user, reconciliation=recon)
    return {
        "version": "v2",
        "pending_actions": len(pending),
        "oldest_pending_age_seconds": oldest,
        "waiting_owner_review": len(waiting_review),
        "approved_waiting": len(approved_waiting),
        "prepared_jobs": len([row for row in jobs if row.status == "PREPARED"]),
        "skipped_jobs": len([row for row in jobs if row.status == "SKIPPED"]),
        "retryable_failures": 0,
        "final_failures": len(failed),
        "duplicate_suppression": len([row for row in events if row.duplicate]),
        "approval_expirations": len(expired),
        "partial_payment_count": len([row for row in entries if row.stage == "PARTIALLY_PAID"]),
        "historical_correction_count": len(corrections),
        "archived_historical_totals": prep.get("archived_historical_revenue") or 0,
        "active_received": prep.get("amicor_received") or 0,
        "adapter_state": "DISABLED",
        "live_execution_state": "DISABLED",
        "scheduler_state": "PREPARE_ONLY",
        "continuous_worker": False,
        "adapters": adapter_inventory(),
        "live_capabilities": LIVE_DISABLED,
        "core_readiness": caps.get("core_readiness") or {},
        "secrets_exposed": False,
        "live_execution_implemented": False,
        "schema_strategy": "alembic_canonical_production",
        "lazy_v2_schema_in_production": False,
    }
