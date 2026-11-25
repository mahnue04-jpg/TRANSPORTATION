"""Server-side staging owner + Stripe TEST subscription quota adapter.

Internal integration candidate only. Not routed, deployed, or authorized for
customer processing. The caller MUST be a trusted server component that receives
UserContext from get_current_user_context, not from a request JSON body.
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .operations_package_usage_ledger import AllowanceBlocked
from .operations_subscription_task_bridge import reserve_verified_subscription_task


def reserve_owner_approved_test_subscription_task(
    db: Session, *,
    authenticated_user,
    organization_id: str,
    engagement_id: str,
    task_id: str,
    lead_id: str,
    request_key: str,
    task_fingerprint: str,
    now: datetime,
) -> dict:
    """Read trusted database scope and Stripe TEST subscription before quota use.

    This reserves quota only. It does NOT execute work or release any artifact.
    """
    if (
        os.getenv("NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED") != "true"
        or os.getenv("NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED") != "true"
        or os.getenv("APP_ENV") != "staging"
        or os.getenv("AMICOR_ENVIRONMENT") != "staging"
        or os.getenv("NOVA_STRIPE_LIVE_ENABLED", "").lower() == "true"
        or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED", "").lower() == "true"
    ):
        raise AllowanceBlocked("owner_subscription_adapter_disabled")

    # The user object MUST originate from authenticated session dependency.
    user_id = str(getattr(authenticated_user, "user_id", "") or "")
    user_org = str(getattr(authenticated_user, "organization_id", "") or "")
    role = str(getattr(authenticated_user, "role", "") or "").lower()
    if (not user_id or not organization_id or user_org != organization_id
            or role not in {"admin", "super_admin_support"}):
        raise AllowanceBlocked("authenticated_owner_required")

    from app.core.nova.work_revenue.models import NovaWorkEngagement, NovaWorkTask
    from app.modules.marketing.models import MarketingWebsiteLead
    from app.modules.marketing.operations_billing import (
        agent_checkout_mode, get_agent_stripe_client, subscription_test_price,
    )

    engagement = db.execute(select(NovaWorkEngagement).where(
        NovaWorkEngagement.engagement_id == engagement_id,
        NovaWorkEngagement.organization_id == organization_id,
        NovaWorkEngagement.owner_user_id == user_id,
    )).scalar_one_or_none()
    task = db.execute(select(NovaWorkTask).where(
        NovaWorkTask.task_id == task_id,
        NovaWorkTask.engagement_id == engagement_id,
        NovaWorkTask.organization_id == organization_id,
        NovaWorkTask.owner_user_id == user_id,
    )).scalar_one_or_none()
    if not engagement or not task or task.review_required is not True:
        raise AllowanceBlocked("saved_owner_task_scope_required")

    # A task status or notes cannot authorize billable work. The exact
    # synthetic request fingerprint must have a recorded owner decision.
    from .operations_subscription_approvals import require_saved_owner_scope_approval
    require_saved_owner_scope_approval(
        db, organization_id=organization_id, owner_user_id=user_id,
        engagement_id=engagement_id, task_id=task_id,
        lead_id=lead_id, task_fingerprint=task_fingerprint,
    )

    lead = db.get(MarketingWebsiteLead, lead_id)
    if (lead is None or lead.lead_type != "anonymous_operations"
            or lead.service_plan not in {"launch_99", "business_299"}
            or lead.payment_status != "paid"
            or not lead.stripe_customer_id or not lead.stripe_subscription_id
            or not str(lead.work_email or "").endswith(".invalid")):
        raise AllowanceBlocked("synthetic_paid_lead_required")
    if agent_checkout_mode() != "test":
        raise AllowanceBlocked("test_stripe_only")
    test_price = subscription_test_price(lead.service_plan)
    if not test_price or not test_price.startswith("price_"):
        raise AllowanceBlocked("test_price_not_configured")

    try:
        subscription = get_agent_stripe_client().retrieve_subscription(lead.stripe_subscription_id)
    except Exception as exc:
        raise AllowanceBlocked("stripe_subscription_unavailable") from exc

    return reserve_verified_subscription_task(
        db, owner_scope_approved=True,
        plan=lead.service_plan,
        lead_id=lead.id,
        saved_customer_id=lead.stripe_customer_id,
        saved_subscription_id=lead.stripe_subscription_id,
        saved_payment_status=lead.payment_status,
        test_price_id=test_price,
        retrieved_test_subscription=subscription,
        request_key=request_key,
        task_fingerprint=task_fingerprint,
        now=now,
    )
