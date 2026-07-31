"""Throttled organization-wide dispatch maintenance (not for driver read polling)."""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_MAINTENANCE_LOCK = threading.Lock()
_LAST_RUN_MONOTONIC: dict[str, float] = {}
_DEFAULT_INTERVAL_SECONDS = int(os.getenv("HEALTH_ISF_DISPATCH_MAINTENANCE_INTERVAL_SECONDS", "120"))


def maybe_run_organization_dispatch_maintenance(
    db: Session,
    *,
    organization_id: str,
    actor_user_id: Optional[str] = None,
    force: bool = False,
    interval_seconds: int | None = None,
) -> dict[str, Any]:
    """Run org-wide dispatch maintenance at most once per interval per organization."""
    from app.modules.health_isf import service

    interval = max(30, int(interval_seconds or _DEFAULT_INTERVAL_SECONDS))
    now_mono = time.monotonic()
    with _MAINTENANCE_LOCK:
        last = _LAST_RUN_MONOTONIC.get(organization_id, 0.0)
        if not force and (now_mono - last) < interval:
            return {
                "skipped": True,
                "reason": "throttled",
                "organization_id": organization_id,
                "interval_seconds": interval,
            }
        _LAST_RUN_MONOTONIC[organization_id] = now_mono

    report: dict[str, Any] = {
        "skipped": False,
        "organization_id": organization_id,
        "interval_seconds": interval,
    }
    try:
        expired = service.expire_stale_dispatch_offers(
            db,
            organization_id=organization_id,
            auto_reassign_immediate=True,
            actor_user_id=actor_user_id,
        )
        report["expired_offers"] = len(expired)
    except Exception:
        logger.warning("expire_stale_dispatch_offers failed org=%s", organization_id, exc_info=True)
        report["expired_offers_error"] = True

    try:
        sweep = service._sweep_stale_assignment_rows_for_organization(db, organization_id=organization_id)
        report["assignment_sweep"] = sweep
    except Exception:
        logger.warning("assignment sweep failed org=%s", organization_id, exc_info=True)
        report["assignment_sweep_error"] = True

    try:
        promoted = service.promote_pending_immediate_customer_requests(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            limit=10,
        )
        report["promoted_immediate_requests"] = len(promoted)
    except Exception:
        logger.warning("promote_pending_immediate failed org=%s", organization_id, exc_info=True)
        report["promote_error"] = True

    try:
        from app.modules.health_isf.scheduling import promote_dispatch_eligible_rides

        promote_dispatch_eligible_rides(db, organization_id=organization_id)
        report["promoted_dispatch_eligible_rides"] = True
    except Exception:
        logger.warning("promote_dispatch_eligible_rides failed org=%s", organization_id, exc_info=True)
        report["promote_dispatch_eligible_error"] = True

    try:
        from app.modules.health_isf.advance_scheduling import (
            promote_scheduled_reservations,
            reconcile_same_driver_return_reservations,
            reconcile_scheduled_reservation_ownership,
            send_scheduled_reminders,
            sweep_pending_advance_scheduling,
        )

        report["same_driver_return_reservations"] = reconcile_same_driver_return_reservations(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        report["scheduled_ownership_reconciled"] = reconcile_scheduled_reservation_ownership(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        report["advance_scheduling_sweep"] = sweep_pending_advance_scheduling(
            db,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
        )
        report["scheduled_reservations_activated"] = []
        report["scheduled_reminders_sent"] = send_scheduled_reminders(
            db,
            organization_id=organization_id,
        )
    except Exception:
        logger.warning("advance scheduling maintenance failed org=%s", organization_id, exc_info=True)
        report["advance_scheduling_error"] = True

    return report
