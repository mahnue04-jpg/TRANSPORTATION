"""Server-side authenticated owner + Stripe subscription quota adapter.

Internal integration candidate only. Not a public route. The caller MUST be a
trusted server component that receives UserContext from get_current_user_context,
not from a request JSON body. Live mode stays disabled unless every commercial
gate is explicitly enabled.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .operations_commercial_mode import resolve_operations_mode
from .operations_package_usage_ledger import AllowanceBlocked
from .operations_subscription_task_bridge import reserve_verified_subscription_task


def subscription_adapter_mode() -> str | None:
    return resolve_operations_mode(
        staging_flags=(
            "NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_STAGING_ENABLED",
            "NOVA_OPERATIONS_PACKAGE_LEDGER_STAGING_ENABLED",
        ),
        live_flags=(
            "NOVA_OPERATIONS_SUBSCRIPTION_BRIDGE_LIVE_ENABLED",
            "NOVA_OPERATIONS_PACKAGE_LEDGER_LIVE_ENABLED",
            "NOVA_OPERATIONS_SUBSCRIPTION_CSV_BINDING_LIVE_ENABLED",
        ),
    )


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
    """Read trusted database scope and Stripe subscription before quota use.

    This reserves quota only. It does NOT execute work or release any artifact.
    """
    mode = subscription_adapter_mode()
    if mode is None:
        raise AllowanceBlocked("owner_subscription_adapter_disabled")
    live = mode == "live"

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
    # request fingerprint must have a recorded owner decision.
    from .operations_subscription_approvals import require_saved_owner_scope_approval
    require_saved_owner_scope_approval(
        db, organization_id=organization_id, owner_user_id=user_id,
        engagement_id=engagement_id, task_id=task_id,
        lead_id=lead_id, task_fingerprint=task_fingerprint,
        expected_livemode=live,
    )

    lead = db.get(MarketingWebsiteLead, lead_id)
    if (lead is None or lead.lead_type != "anonymous_operations"
            or lead.service_plan not in {"launch_99", "business_299"}
            or lead.payment_status != "paid"
            or not lead.stripe_customer_id or not lead.stripe_subscription_id):
        raise AllowanceBlocked("synthetic_paid_lead_required")
    email = str(lead.work_email or "")
    if live:
        # Import only on the live path so staging CI never loads billing.__init__.
        from app.core.nova.billing.operations_catalog import LIVE_OPERATIONS_PRICES
        if agent_checkout_mode() != "live" or email.lower().endswith(".invalid"):
            raise AllowanceBlocked("live_paid_lead_required")
        price = LIVE_OPERATIONS_PRICES.get(lead.service_plan, "")
        if not price:
            raise AllowanceBlocked("live_price_mismatch")
    else:
        if not email.endswith(".invalid"):
            raise AllowanceBlocked("synthetic_paid_lead_required")
        if agent_checkout_mode() != "test":
            raise AllowanceBlocked("test_stripe_only")
        price = subscription_test_price(lead.service_plan)
        if not price or not price.startswith("price_"):
            raise AllowanceBlocked("test_price_not_configured")

    try:
        stripe = get_agent_stripe_client()
        subscription = stripe.retrieve_subscription(lead.stripe_subscription_id)
        if stripe.verify_subscription_payment(plan=lead.service_plan,
                customer_id=lead.stripe_customer_id, subscription=subscription) is not True:
            raise AllowanceBlocked("subscription_payment_reversed_or_unverified")
    except AllowanceBlocked:
        raise
    except Exception as exc:
        raise AllowanceBlocked("stripe_subscription_unavailable") from exc

    from .operations_subscription_csv_binding import bind_reserved_csv_task, request_key_for_task
    scope = dict(organization_id=organization_id, owner_user_id=user_id,
                 engagement_id=engagement_id, task_id=task_id, lead_id=lead.id)
    if request_key != request_key_for_task(**scope):
        raise AllowanceBlocked("exact_csv_request_key_required")

    def bind(reservation_id, entitlement):
        bind_reserved_csv_task(
            db, reservation_id=reservation_id, **scope,
            customer_id=entitlement.customer_id,
            subscription_id=entitlement.subscription_id,
            plan=entitlement.plan,
            period_key=entitlement.period_start.astimezone(timezone.utc).isoformat(),
            input_sha256=task_fingerprint,
            expected_livemode=live,
        )

    return reserve_verified_subscription_task(
        db, owner_scope_approved=True,
        plan=lead.service_plan,
        lead_id=lead.id,
        saved_customer_id=lead.stripe_customer_id,
        saved_subscription_id=lead.stripe_subscription_id,
        saved_payment_status=lead.payment_status,
        test_price_id=price,
        retrieved_test_subscription=subscription,
        request_key=request_key,
        task_fingerprint=task_fingerprint,
        now=now, bind_reservation=bind,
        expected_livemode=live,
    )
