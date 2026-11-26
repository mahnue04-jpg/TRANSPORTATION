"""Staging-only immutable link between a subscription reservation and a CSV task.

Internal server boundary, not a route. No execution or delivery is authorized
by the existence of this record alone. A current entitlement and approval must
be rechecked before execution or release.
"""
from __future__ import annotations

import hashlib
import json
import os

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .operations_package_usage_ledger import AllowanceBlocked, reservations, require_staging
from .operations_subscription_approvals import approvals, require_saved_owner_scope_approval

metadata = sa.MetaData()
bindings = sa.Table(
    "nova_operations_subscription_csv_bindings", metadata,
    sa.Column("reservation_id", sa.String(64), primary_key=True),
    sa.Column("organization_id", sa.String(36), nullable=False),
    sa.Column("owner_user_id", sa.String(36), nullable=False),
    sa.Column("engagement_id", sa.String(32), nullable=False),
    sa.Column("task_id", sa.String(32), nullable=False),
    sa.Column("lead_id", sa.String(36), nullable=False),
    sa.Column("customer_id", sa.String(128), nullable=False),
    sa.Column("subscription_id", sa.String(128), nullable=False),
    sa.Column("plan", sa.String(32), nullable=False),
    sa.Column("period_key", sa.String(64), nullable=False),
    sa.Column("input_sha256", sa.String(64), nullable=False),
    sa.UniqueConstraint("organization_id", "owner_user_id", "engagement_id", "task_id",
                        name="uq_nova_ops_subscription_csv_task"),
)


def request_key_for_task(*, organization_id: str, owner_user_id: str,
                         engagement_id: str, task_id: str, lead_id: str) -> str:
    """Stable server-derived key, independent of retry or billing period."""
    values = [organization_id, owner_user_id, engagement_id, task_id, lead_id]
    if not all(isinstance(v, str) and v.strip() for v in values):
        raise AllowanceBlocked("csv_binding_scope_missing")
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def bind_reserved_csv_task(
    db: Session, *, reservation_id: str, organization_id: str, owner_user_id: str,
    engagement_id: str, task_id: str, lead_id: str, customer_id: str,
    subscription_id: str, plan: str, period_key: str, input_sha256: str,
) -> dict:
    """Bind exact reservation and approval inside caller's transaction.

    Caller must already have authenticated owner and verified Stripe test
    subscription. This helper never commits; it can be used in the same
    transaction as the allowance reservation. No public caller is permitted.
    """
    require_staging(db)
    if (os.getenv("NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_STAGING_ENABLED") != "true"
            or os.getenv("NOVA_STRIPE_LIVE_ENABLED") != "false"
            or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") != "false"):
        raise AllowanceBlocked("subscription_csv_binding_disabled")
    if not sa.inspect(db.get_bind()).has_table(bindings.name):
        raise AllowanceBlocked("csv_binding_migration_required")
    if plan not in {"launch_99", "business_299"} or not subscription_id.startswith("sub_"):
        raise AllowanceBlocked("csv_binding_subscription_required")
    scope = dict(organization_id=organization_id, owner_user_id=owner_user_id,
                 engagement_id=engagement_id, task_id=task_id, lead_id=lead_id)
    key = request_key_for_task(**scope)
    require_saved_owner_scope_approval(db, **scope, task_fingerprint=input_sha256)
    # Lock the exact approval row so a concurrent revoke cannot overtake binding.
    decision = db.execute(sa.select(approvals.c.decision).where(
        *(approvals.c[k] == v for k, v in scope.items()),
        approvals.c.task_fingerprint == input_sha256,
    ).with_for_update()).scalar_one_or_none()
    if decision != "APPROVED":
        raise AllowanceBlocked("explicit_owner_approval_missing")
    row = db.execute(sa.select(reservations).where(
        reservations.c.id == reservation_id,
        reservations.c.customer_id == customer_id,
        reservations.c.plan == plan,
        reservations.c.entitlement_id == subscription_id,
        reservations.c.period_key == period_key,
        reservations.c.request_key == key,
        reservations.c.task_fingerprint == input_sha256,
    )).mappings().one_or_none()
    if row is None:
        raise AllowanceBlocked("exact_csv_reservation_required")
    values = dict(reservation_id=reservation_id, **scope, customer_id=customer_id,
                  subscription_id=subscription_id, plan=plan, period_key=period_key,
                  input_sha256=input_sha256)
    from sqlalchemy.dialects.postgresql import insert
    inserted = db.execute(insert(bindings).values(**values).on_conflict_do_nothing()
                          .returning(bindings.c.reservation_id)).scalar_one_or_none()
    existing = db.execute(sa.select(bindings).where(
        bindings.c.organization_id == organization_id,
        bindings.c.owner_user_id == owner_user_id,
        bindings.c.engagement_id == engagement_id,
        bindings.c.task_id == task_id,
    )).mappings().one_or_none()
    if existing is None or any(existing[k] != v for k, v in values.items()):
        raise AllowanceBlocked("csv_task_already_bound_to_different_reservation")
    return {"reservation_id": reservation_id, "replayed": inserted is None,
            "executed": False, "delivered": False}
