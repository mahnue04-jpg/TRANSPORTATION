"""Atomic Creative Studio spending reservations (no provider calls).

Only the database-backed reservation path is concurrency safe. Callers must
reserve prior to any paid provider submission and reconcile afterward.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.nova.creative_studio.db_models import (
    NovaCreativeProject, NovaCreativeSpendReservation,
)
from app.core.nova.creative_studio.spending_policy import SpendingEntry, can_reserve


def reserve_project_spend(
    db: Session, *, owner_id: str, project_id: str, provider: str,
    request_key: str, estimate_cents: int, cap_cents: int,
) -> bool:
    """Reserve once under a project-row lock, atomically with the ledger insert.

    Return False for duplicate keys or insufficient headroom. Do not use an
    unlocked in-memory store to authorize a paid generation request.
    """
    if not all((owner_id, project_id, provider, request_key)):
        return False
    if estimate_cents <= 0 or cap_cents < 0:
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        with db.begin():
            project = db.execute(
                select(NovaCreativeProject)
                .where(NovaCreativeProject.id == project_id,
                       NovaCreativeProject.owner_id == owner_id)
                .with_for_update()
            ).scalar_one_or_none()
            if project is None:
                return False
            rows = db.execute(
                select(NovaCreativeSpendReservation).where(
                    NovaCreativeSpendReservation.owner_id == owner_id,
                    NovaCreativeSpendReservation.project_id == project_id
                )
            ).scalars().all()
            entries = [
                SpendingEntry(row.request_key, row.reserved_cents,
                              row.actual_cents, row.status) for row in rows
            ]
            if not can_reserve(cap_cents=cap_cents, estimate_cents=estimate_cents,
                               request_key=request_key, entries=entries):
                return False
            db.add(NovaCreativeSpendReservation(
                request_key=request_key, owner_id=owner_id, project_id=project_id,
                provider=provider, reserved_cents=estimate_cents, actual_cents=0,
                status="reserved", created_at=now, updated_at=now
            ))
        return True
    except Exception:
        db.rollback()
        raise
