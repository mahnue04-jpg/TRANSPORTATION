"""Disabled-by-default, PostgreSQL-only Operations usage reservations.

Caller must supply a VerifiedEntitlement populated from independently verified,
signed Stripe records and approved customer scope. Neither this module nor the
pure allowance policy validates Stripe signatures. Do not expose this as an
HTTP endpoint or enable it for real customer processing until the entire
checkout-to-fulfillment pipeline is reviewed.

The table deliberately is not enrolled in application startup create_all.
Migrate explicitly in the isolated staging DB after review.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .operations_package_allowances import VerifiedEntitlement, can_accept_task

metadata = sa.MetaData()
reservations = sa.Table(
    "nova_operations_package_task_reservations", metadata,
    sa.Column("id", sa.String(64), primary_key=True),
    sa.Column("customer_id", sa.String(128), nullable=False),
    sa.Column("plan", sa.String(32), nullable=False),
    sa.Column("entitlement_id", sa.String(128), nullable=False),
    sa.Column("period_key", sa.String(64), nullable=False),
    sa.Column("request_key", sa.String(128), nullable=False),
    sa.Column("task_fingerprint", sa.String(64), nullable=False),
    sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
    sa.UniqueConstraint(
        "customer_id", "plan", "entitlement_id", "period_key", "request_key",
        name="uq_nova_operations_entitlement_task",
    ),
)


class AllowanceBlocked(ValueError):
    """Fail-closed reason; not a customer-facing billing confirmation."""


def require_staging(db: Session) -> None:
    if (
        os.getenv("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED") != "true"
        or os.getenv("APP_ENV") != "staging"
        or os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").lower() == "true"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").lower() == "true"
        or db.get_bind().dialect.name != "postgresql"
    ):
        raise AllowanceBlocked("staging_postgres_only")
    if not sa.inspect(db.get_bind()).has_table(reservations.name):
        raise AllowanceBlocked("reviewed_migration_required")


def _identity(entitlement: VerifiedEntitlement) -> tuple[str, str]:
    if entitlement.plan in {"launch_99", "business_299"}:
        # Period boundaries and subscription ID are verified upstream.
        if not entitlement.subscription_id or not entitlement.period_start:
            raise AllowanceBlocked("subscription_period_unverified")
        start = entitlement.period_start
        if start.tzinfo is None:
            raise AllowanceBlocked("timezone_required")
        return entitlement.subscription_id, start.astimezone(timezone.utc).isoformat()
    if entitlement.plan == "starter_49" and entitlement.payment_id:
        return entitlement.payment_id, "one_time"
    raise AllowanceBlocked("entitlement_unverified")


def reserve_staging_task(
    db: Session, *,
    entitlement: VerifiedEntitlement,
    customer_id: str,
    request_key: str,
    task_fingerprint: str,
    now: datetime,
) -> dict:
    """Serialize and reserve one unique task, or return a safe replay.

    Uses a transaction-scoped Postgres advisory lock on customer+entitlement+
    period. The caller must ensure no unrelated session transaction is in flight:
    the function commits its own reservation. This is a quota reservation, *not*
    approval or execution of the task.
    """
    require_staging(db)
    if not isinstance(task_fingerprint, str) or len(task_fingerprint) != 64 or any(
        c not in "0123456789abcdef" for c in task_fingerprint
    ):
        raise AllowanceBlocked("invalid_task_fingerprint")
    entitlement_id, period_key = _identity(entitlement)
    if not request_key or len(request_key) > 128 or not request_key.isascii():
        raise AllowanceBlocked("invalid_request_key")

    scope = (customer_id, entitlement.plan, entitlement_id, period_key)
    canonical = "\x1f".join(scope)
    lock_id = int.from_bytes(
        hashlib.sha256(canonical.encode("utf-8")).digest()[:8],
        byteorder="big", signed=True,
    )
    row_id = hashlib.sha256((canonical + "\x1f" + request_key).encode("utf-8")).hexdigest()
    try:
        # Do not use a stale identity map or permit two simultaneous first jobs.
        db.execute(sa.text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})
        rows = db.execute(sa.select(
            reservations.c.request_key, reservations.c.task_fingerprint,
        ).where(
            reservations.c.customer_id == customer_id,
            reservations.c.plan == entitlement.plan,
            reservations.c.entitlement_id == entitlement_id,
            reservations.c.period_key == period_key,
        )).all()
        seen = {r.request_key: r.task_fingerprint for r in rows}
        if request_key in seen and seen[request_key] != task_fingerprint:
            raise AllowanceBlocked("request_key_reused_for_different_task")
        allowed, reason = can_accept_task(
            entitlement, customer_id=customer_id, now=now,
            accepted_unique_tasks=frozenset(seen), request_key=request_key,
        )
        if not allowed:
            raise AllowanceBlocked(reason)
        if reason == "existing_task_idempotent":
            db.commit()
            return {"reservation_id": row_id, "replayed": True, "consumed": False}
        db.execute(sa.insert(reservations).values(
            id=row_id, customer_id=customer_id, plan=entitlement.plan,
            entitlement_id=entitlement_id, period_key=period_key,
            request_key=request_key, task_fingerprint=task_fingerprint,
            reserved_at=now,
        ))
        db.commit()
        return {"reservation_id": row_id, "replayed": False, "consumed": True}
    except Exception:
        db.rollback()
        raise
