"""Internal Starter access adapter; never accepts billing evidence from HTTP input."""
from datetime import datetime, timezone
import os

from .starter_self_service import FEATURES
from .starter_subscription_evidence import verify_starter_feature


def authenticated_starter_access(db, *, authenticated_user, feature: str) -> bool:
    """User must originate from the server's authenticated session dependency.

    No schema creation, write, checkout or public route. A missing record,
    unavailable Stripe read or incomplete evidence denies access.
    """
    if (feature not in FEATURES
            or os.getenv("APP_ENV") != "staging"
            or os.getenv("AMICOR_ENVIRONMENT") != "staging"
            or os.getenv("NOVA_STARTER_SELF_SERVICE_STAGING_ENABLED") != "true"
            or os.getenv("NOVA_STRIPE_LIVE_ENABLED") != "false"
            or os.getenv("NOVA_OPERATIONS_CUSTOMER_SALES_ENABLED") != "false"):
        return False
    tenant_id = getattr(authenticated_user, "organization_id", None)
    user_id = getattr(authenticated_user, "user_id", None)
    email = getattr(authenticated_user, "email", None)
    if (not isinstance(tenant_id, str) or not tenant_id
            or not isinstance(user_id, str) or not user_id
            or not isinstance(email, str) or not email.lower().endswith(".invalid")):
        return False
    try:
        from sqlalchemy import select
        from .models import NovaTenantSubscription
        from app.core.nova.signup.stripe_client import stripe_secret_key
        from .stripe_client import LiveNovaBillingStripeClient

        row = db.execute(select(NovaTenantSubscription).where(
            NovaTenantSubscription.tenant_id == tenant_id,
        )).scalar_one_or_none()
        if (row is None or row.plan_key != "starter"
                or row.subscription_status != "active"
                or not row.stripe_subscription_id
                or not row.stripe_subscription_id.startswith("sub_")
                or not str(row.stripe_customer_id or "").startswith("cus_")):
            return False
        key = stripe_secret_key()
        if not isinstance(key, str) or not key.startswith(("sk_test_", "rk_test_")):
            return False
        client = LiveNovaBillingStripeClient(api_key=key)._build_client()
        result = client.v1.subscriptions.retrieve(
            row.stripe_subscription_id, {"expand": ["latest_invoice"]})
        subscription = result.to_dict_recursive() if hasattr(result, "to_dict_recursive") else result
        if not isinstance(subscription, dict):
            return False
        return verify_starter_feature(feature=feature, tenant_id=tenant_id,
            row=row, subscription=subscription, now=datetime.now(timezone.utc))
    except Exception:
        # Do not leak payment identifiers, credentials or provider errors.
        return False
