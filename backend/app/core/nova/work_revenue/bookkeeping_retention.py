"""Dry-run retention and orphan-risk inventory for Nova accounting review files.

Never deletes objects, exposes storage keys to callers, writes to the DB, or
turns review approval into delivery. The output is deliberately aggregated.
A separately approved, audited retention implementation is required before
customer records may be processed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Session

from . import operations_customer_csv_jobs as base

TERMINAL = frozenset({"FAILED", "REJECTED", "APPROVED_FOR_DOWNLOAD"})
MANUAL_HOLD = frozenset({"PROCESSING", "AWAITING_REVIEW"})
MAX_BATCH = 500


class RetentionInspectionBlocked(ValueError):
    pass


def plan_bookkeeping_retention(
    db: Session, *,
    organization_id: str,
    owner_user_id: str,
    older_than_days: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a private summary requiring explicit operator retention review.

    Does not query S3 because unreferenced/orphaned objects cannot be safely
    inferred from job rows. Never marks any artifact safe for auto-deletion.
    """
    if not all(
        isinstance(x, str) and x.strip() and x.strip().lower() != "global"
        and 0 < len(x) <= 120 for x in (organization_id, owner_user_id)
    ):
        raise RetentionInspectionBlocked("Exact organization and owner scope required")
    if type(older_than_days) is not int or not 1 <= older_than_days <= 3650:
        raise RetentionInspectionBlocked("Retention age must be 1 to 3650 days")
    anchor = now or datetime.now(timezone.utc)
    if not isinstance(anchor, datetime) or anchor.tzinfo is None:
        raise RetentionInspectionBlocked("Timezone-aware date required")
    if db.get_bind().dialect.name not in {"postgresql", "sqlite"}:
        raise RetentionInspectionBlocked("Unsupported audit database")
    cutoff = anchor - timedelta(days=older_than_days)
    rows = db.execute(sa.select(
        base.jobs.c.status, base.jobs.c.output_ref, base.jobs.c.output_sha256,
        base.jobs.c.updated_at,
    ).where(
        base.jobs.c.organization_id == organization_id,
        base.jobs.c.owner_user_id == owner_user_id,
        base.jobs.c.request_key.like("bookkeeping:%"),
        base.jobs.c.updated_at < cutoff,
    ).order_by(base.jobs.c.updated_at).limit(MAX_BATCH + 1)).mappings().all()
    if len(rows) > MAX_BATCH:
        raise RetentionInspectionBlocked("More than 500 records; narrow the audit scope")

    counts = {"terminal_review": 0, "active_review_hold": 0,
              "inconsistent_metadata": 0, "unknown_status": 0,
              "no_private_reference": 0}
    for row in rows:
        status = str(row["status"])
        ref = row["output_ref"]
        sha = row["output_sha256"]
        if status in MANUAL_HOLD:
            counts["active_review_hold"] += 1
        elif status in TERMINAL:
            counts["terminal_review"] += 1
        else:
            counts["unknown_status"] += 1
        if bool(ref) != bool(sha):
            counts["inconsistent_metadata"] += 1
        if not ref:
            counts["no_private_reference"] += 1
    blockers = [
        reason for reason, count in counts.items()
        if reason != "terminal_review" and count > 0
    ]
    # The retention decision always needs a legal/contract and storage
    # lifecycle policy. A clean terminal job is NOT permission to delete.
    blockers.append("independent_retention_and_client_consent_review")
    blockers.append("real_s3_object_inventory_not_performed")
    return {
        "mode": "DRY_RUN_INSPECTION_ONLY",
        "organization_scoped": True,
        "owner_scoped": True,
        "older_than_days": older_than_days,
        "examined_count": len(rows),
        "counts": counts,
        "blockers": blockers,
        "objects_deleted": 0,
        "database_rows_changed": 0,
        "deletion_authorized": False,
        "customer_delivery_authorized": False,
    }
