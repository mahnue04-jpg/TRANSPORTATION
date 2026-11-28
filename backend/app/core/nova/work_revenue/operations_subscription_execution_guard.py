"""Internal authorization for an existing subscription CSV binding.

No execution, delivery, quota consumption, or commit is performed here.
Callers must retain the approval lock until their authorization transaction ends.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .operations_commercial_mode import resolve_operations_mode
from .operations_package_usage_ledger import AllowanceBlocked, require_staging, reservations
from .operations_subscription_approvals import approvals, require_saved_owner_scope_approval
from .operations_subscription_csv_binding import bindings, request_key_for_task
from .operations_subscription_entitlement import (
    SubscriptionNotEntitled, from_reconciled_test_subscription,
)


def subscription_execution_mode() -> str | None:
    return resolve_operations_mode(
        staging_flags=(
            "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_STAGING_ENABLED",
            "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_STAGING_ENABLED",
        ),
        live_flags=(
            "NOVA_OPERATIONS_SUBSCRIPTION_EXECUTION_LIVE_ENABLED",
            "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED",
            "NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED",
        ),
    )


def require_current_bound_subscription(
    db: Session, *, organization_id: str, owner_user_id: str,
    engagement_id: str, task_id: str, input_sha256: str, now: datetime,
) -> dict:
    """Recheck exact saved task, approval, reservation and current Stripe payment.

    Only a trusted server caller may supply scope obtained from authenticated
    owner/job records. This is not a standalone customer authorization endpoint.
    """
    mode = subscription_execution_mode()
    if mode is None:
        raise AllowanceBlocked("subscription_execution_disabled")
    live = mode == "live"
    require_staging(db, expected_livemode=live)
    if not all((organization_id, owner_user_id, engagement_id, task_id)):
        raise AllowanceBlocked("subscription_execution_scope_missing")
    if not sa.inspect(db.get_bind()).has_table(bindings.name):
        raise AllowanceBlocked("csv_binding_migration_required")
    scope = dict(organization_id=organization_id, owner_user_id=owner_user_id,
                 engagement_id=engagement_id, task_id=task_id)
    row = db.execute(sa.select(bindings).where(
        *(bindings.c[k] == v for k, v in scope.items()),
        bindings.c.input_sha256 == input_sha256,
    )).mappings().one_or_none()
    if row is None:
        raise AllowanceBlocked("exact_csv_binding_required")
    approval_scope = dict(**scope, lead_id=row["lead_id"])
    require_saved_owner_scope_approval(
        db, **approval_scope, task_fingerprint=input_sha256, expected_livemode=live,
    )
    decision = db.execute(sa.select(approvals.c.decision).where(
        *(approvals.c[k] == v for k, v in approval_scope.items()),
        approvals.c.task_fingerprint == input_sha256,
    ).with_for_update()).scalar_one_or_none()
    if decision != "APPROVED":
        raise AllowanceBlocked("explicit_owner_approval_missing")
    key = request_key_for_task(**approval_scope)
    reservation = db.execute(sa.select(reservations.c.id).where(
        reservations.c.id == row["reservation_id"],
        reservations.c.customer_id == row["customer_id"],
        reservations.c.plan == row["plan"],
        reservations.c.entitlement_id == row["subscription_id"],
        reservations.c.period_key == row["period_key"],
        reservations.c.request_key == key,
        reservations.c.task_fingerprint == input_sha256,
    )).scalar_one_or_none()
    if reservation is None:
        raise AllowanceBlocked("exact_csv_reservation_required")

    from app.modules.marketing.models import MarketingWebsiteLead
    from app.modules.marketing.operations_billing import (
        agent_checkout_mode, get_agent_stripe_client, subscription_test_price,
    )
    lead = db.get(MarketingWebsiteLead, row["lead_id"], populate_existing=True)
    email = str(lead.work_email or "") if lead is not None else ""
    if (
        lead is None or lead.lead_type != "anonymous_operations"
        or lead.service_plan != row["plan"] or lead.payment_status != "paid"
        or lead.stripe_customer_id != row["customer_id"]
        or lead.stripe_subscription_id != row["subscription_id"]
    ):
        raise AllowanceBlocked("synthetic_paid_lead_required")
    if live:
        # Import only on the live path so staging CI never loads billing.__init__.
        from app.core.nova.billing.operations_catalog import LIVE_OPERATIONS_PRICES
        if agent_checkout_mode() != "live" or email.lower().endswith(".invalid"):
            raise AllowanceBlocked("live_paid_lead_required")
        price = LIVE_OPERATIONS_PRICES.get(row["plan"], "")
    else:
        if not email.endswith(".invalid") or agent_checkout_mode() != "test":
            raise AllowanceBlocked("synthetic_paid_lead_required")
        price = subscription_test_price(row["plan"])
    if not price or not price.startswith("price_"):
        raise AllowanceBlocked("test_price_not_configured" if not live else "live_price_mismatch")
    try:
        stripe = get_agent_stripe_client()
        subscription = stripe.retrieve_subscription(row["subscription_id"])
        if stripe.verify_subscription_payment(plan=row["plan"],
                customer_id=row["customer_id"], subscription=subscription) is not True:
            raise AllowanceBlocked("subscription_payment_reversed_or_unverified")
        entitlement = from_reconciled_test_subscription(
            plan=row["plan"], lead_id=row["lead_id"],
            saved_customer_id=row["customer_id"],
            saved_subscription_id=row["subscription_id"],
            saved_payment_status=lead.payment_status,
            test_price_id=price, subscription=subscription, now=now,
            require_current_invoice=live or os.getenv("NOVA_OPERATIONS_STRICT_INVOICE_STAGING") == "true",
            expected_livemode=live,
        )
    except SubscriptionNotEntitled as exc:
        raise AllowanceBlocked("subscription_not_currently_entitled") from exc
    except AllowanceBlocked:
        raise
    except Exception as exc:
        raise AllowanceBlocked("stripe_subscription_unavailable") from exc
    # Conservative policy: do not execute or release a task reserved in a
    # previous billing period. Rollover needs an explicit product policy.
    if entitlement.period_start.astimezone(timezone.utc).isoformat() != row["period_key"]:
        raise AllowanceBlocked("reservation_period_changed")
    return {"reservation_id": reservation, "lead_id": row["lead_id"],
            "plan": row["plan"], "authorized": True, "mode": mode}
