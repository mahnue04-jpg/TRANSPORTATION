"""Approved $9.99 Starter self-service policy, disabled outside staging.

Internal policy only. Trusted callers must independently reconcile the exact
tenant, Stripe test subscription, and paid invoice before granting access.
No managed task, delivery grant, premium tool or trial is included.
"""
from datetime import datetime
import os

from .paid_access_policy import allows_paid_plan

FEATURES = frozenset({"basic_workspace", "task_planning", "templates", "self_service_assistance"})
MANAGED_TASKS_INCLUDED = 0


def allows_starter_feature(*, feature: str, tenant_id: str,
                           verified_tenant_id: str, recorded_plan: str,
                           status: str, recorded_price: str,
                           verified_subscription: bool, verified_paid_invoice: bool,
                           stripe_livemode: bool, current_period_end: datetime,
                           now: datetime) -> bool:
    if (
        os.getenv("APP_ENV") != "staging"
        or os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED") != "true"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED") != "false"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") != "false"
    ):
        return False
    if (feature not in FEATURES or not tenant_id
            or tenant_id != verified_tenant_id or stripe_livemode is not False
            or verified_paid_invoice is not True):
        return False
    expected_price = os.getenv("NOVA_STARTER_SELF_SERVICE_TEST_PRICE_ID", "").strip()
    if not expected_price.startswith("price_"):
        return False
    return allows_paid_plan(required_plan="starter", recorded_plan=recorded_plan,
        status=status, expected_price=expected_price, recorded_price=recorded_price,
        verified_subscription=verified_subscription,
        current_period_end=current_period_end, now=now)
