"""Staging-only subscription -> allowance reservation boundary.

Not a public API, Stripe webhook handler, or task execution pathway.
The caller must independently authenticate the owner, authorize the saved
engagement/task and retrieve the subscription using the Stripe test API.
No customer fulfillment occurs here. Both gates default to disabled.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Mapping, Callable

from sqlalchemy.orm import Session

from .operations_package_usage_ledger import AllowanceBlocked, reserve_staging_task
from .operations_subscription_entitlement import from_reconciled_test_subscription


def reserve_verified_subscription_task(
    db: Session, *,
    owner_scope_approved: bool,
    plan: str,
    lead_id: str,
    saved_customer_id: str,
    saved_subscription_id: str,
    saved_payment_status: str,
    test_price_id: str,
    retrieved_test_subscription: Mapping[str, Any],
    request_key: str,
    task_fingerprint: str,
    now: datetime,
    bind_reservation: Callable[[str, Any], None] | None = None,
) -> dict:
    """Reserve quota only after owner approval and exact paid subscription checks.

    This does not certify the provenance of the subscription object; the caller
    must use authenticated Stripe retrieval and independently verify identity.
    Owner scope must be authenticated in a future integration (not caller input).
    """
    if (
        os.getenv("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED") != "true"
        or os.getenv("APP_ENV") != "staging"
        or os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").lower() == "true"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").lower() == "true"
    ):
        raise AllowanceBlocked("subscription_bridge_disabled")
    if owner_scope_approved is not True:
        raise AllowanceBlocked("owner_scope_approval_required")
    entitlement = from_reconciled_test_subscription(
        plan=plan, lead_id=lead_id,
        saved_customer_id=saved_customer_id,
        saved_subscription_id=saved_subscription_id,
        saved_payment_status=saved_payment_status,
        test_price_id=test_price_id,
        subscription=retrieved_test_subscription,
        now=now,
    )
    options = {}
    if bind_reservation is not None:
        options["before_commit"] = lambda reservation_id: bind_reservation(reservation_id, entitlement)
    return reserve_staging_task(
        db, entitlement=entitlement, customer_id=saved_customer_id,
        request_key=request_key, task_fingerprint=task_fingerprint, now=now, **options,
    )
