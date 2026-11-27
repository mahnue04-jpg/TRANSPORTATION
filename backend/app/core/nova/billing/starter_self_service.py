"""Approved $9.99 Starter self-service policy, disabled outside staging.

Internal policy only. Trusted callers must independently reconcile the exact
tenant, Stripe test subscription, and paid invoice before granting access.
No managed task, delivery grant, premium tool or trial is included.
"""
from datetime import datetime
import os

from .paid_access_policy import allows_paid_plan

LIVE_STARTER_PRICE = "price_1UfWpDBCDlIbm4gm7kY4yIva"

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
    # A configured checkout price must agree with the staging access price.
    # Never grant access when checkout and entitlement configuration diverge.
    checkout_price = os.getenv("NOVA_STRIPE_PRICE_STARTER", "").strip()
    if checkout_price and checkout_price != expected_price:
        return False
    return allows_paid_plan(required_plan="starter", recorded_plan=recorded_plan,
        status=status, expected_price=expected_price, recorded_price=recorded_price,
        verified_subscription=verified_subscription,
        current_period_end=current_period_end, now=now)


def allows_live_starter_feature(*, feature: str, tenant_id: str,
                                verified_tenant_id: str, recorded_plan: str,
                                status: str, recorded_price: str,
                                verified_subscription: bool, verified_paid_invoice: bool,
                                stripe_livemode: bool, current_period_end: datetime,
                                now: datetime) -> bool:
    """Unwired production policy: callers must independently verify fresh payment evidence."""
    if (
        os.getenv("APP_ENV") != "production"
        or os.getenv("AMICOR_ENVIRONMENT") != "production"
        or os.getenv("NOVA_STARTER_SELF_SERVICE_PRODUCTION_ENABLED") != "true"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED") != "true"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") != "true"
        or os.getenv("NOVA_STRIPE_PRICE_STARTER") != LIVE_STARTER_PRICE
        or os.getenv("NOVA_BILLING_CHECKOUT_TRIAL_ENABLED") != "false"
    ):
        return False
    if (feature not in FEATURES or not tenant_id
            or tenant_id != verified_tenant_id or stripe_livemode is not True
            or verified_paid_invoice is not True):
        return False
    return allows_paid_plan(required_plan="starter", recorded_plan=recorded_plan,
        status=status, expected_price=LIVE_STARTER_PRICE, recorded_price=recorded_price,
        verified_subscription=verified_subscription,
        current_period_end=current_period_end, now=now)
