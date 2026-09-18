"""Nova tenant subscription checkout, portal, webhooks, and access foundation."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.auth import ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT, UserContext, normalize_role
from app.core.nova.billing.models import NovaBillingWebhookEvent, NovaTenantSubscription
from app.core.nova.billing.plans import (
    ACCESS_STATUSES,
    BILLING_ROLES,
    PLAN_KEYS,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
    STATUS_EXPIRED,
    STATUS_INCOMPLETE,
    STATUS_PAST_DUE,
    STATUS_TRIALING,
    STRIPE_STATUS_MAP,
    nova_free_trial_days,
    nova_past_due_has_access,
    nova_subscription_enforcement_enabled,
    price_id_for_plan,
    public_cancel_url,
    public_portal_return_url,
    public_success_url,
)
from app.core.nova.billing.schema_ensure import ensure_nova_billing_schema
from app.core.nova.billing.stripe_client import (
    get_nova_billing_stripe_client,
    nova_billing_webhook_secret,
    sanitize_stripe_error,
)
from app.core.nova.signup.stripe_client import (
    is_live_stripe_key,
    nova_live_stripe_enabled,
    stripe_secret_key,
)
from app.helpers import now

logger = logging.getLogger("amicor.nova.billing")


class BillingError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def nova_subscription_has_access(
    status: str | None,
    *,
    enforcement: bool | None = None,
    past_due_access: bool | None = None,
) -> bool:
    """Phase 1 foundation only. Default enforcement is OFF so existing Nova access stays open."""
    if enforcement is None:
        enforcement = nova_subscription_enforcement_enabled()
    if not enforcement:
        return True
    normalized = str(status or "").strip().lower()
    if normalized in ACCESS_STATUSES:
        return True
    if normalized == STATUS_PAST_DUE:
        if past_due_access is None:
            past_due_access = nova_past_due_has_access()
        return bool(past_due_access)
    return False


def _require_billing_role(user: UserContext) -> None:
    role = normalize_role(user.role)
    if role not in BILLING_ROLES and role not in {ROLE_ADMIN, ROLE_SUPER_ADMIN_SUPPORT}:
        raise BillingError("Owner or admin role required", status_code=403)


def _tenant_id(user: UserContext, requested: str | None = None) -> str:
    tenant_id = str(user.organization_id or "").strip()
    if not tenant_id:
        raise BillingError("Tenant is required", status_code=403)
    if requested and str(requested).strip() and str(requested).strip() != tenant_id:
        raise BillingError("Cross-tenant billing is not allowed", status_code=403)
    return tenant_id


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _dt(value: Any) -> datetime | None:
    if value in (None, "", 0):
        return None
    if isinstance(value, datetime):
        return _aware(value)
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _map_status(raw: str | None, *, deleted: bool = False) -> str:
    if deleted:
        return STATUS_CANCELLED
    mapped = STRIPE_STATUS_MAP.get(str(raw or "").strip().lower())
    return mapped or STATUS_INCOMPLETE


def _get_or_create_row(db: Session, tenant_id: str) -> NovaTenantSubscription:
    row = (
        db.query(NovaTenantSubscription)
        .filter(NovaTenantSubscription.tenant_id == tenant_id)
        .first()
    )
    if row is not None:
        return row
    row = NovaTenantSubscription(tenant_id=tenant_id, subscription_status=STATUS_INCOMPLETE)
    db.add(row)
    db.flush()
    return row


def _trial_eligible(row: NovaTenantSubscription) -> bool:
    if row.trial_used:
        return False
    if row.trial_started_at is not None:
        return False
    if row.subscription_status in {STATUS_TRIALING, STATUS_ACTIVE, STATUS_PAST_DUE, STATUS_CANCELLED, STATUS_EXPIRED}:
        return False
    return True


def _require_stripe_mode() -> None:
    """Require Stripe config while keeping live mode fail-closed by default."""
    from app.core.nova.billing.stripe_client import get_nova_billing_stripe_override

    if get_nova_billing_stripe_override() is not None:
        return
    secret = stripe_secret_key()
    if not secret:
        raise BillingError("Stripe key is not configured for Nova billing", status_code=503)
    if is_live_stripe_key(secret) and not nova_live_stripe_enabled():
        raise BillingError(
            "Live Stripe key detected but NOVA_STRIPE_LIVE_ENABLED is not explicitly enabled",
            status_code=503,
        )


def start_checkout(
    db: Session,
    *,
    user: UserContext,
    plan_key: str,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    ensure_nova_billing_schema()
    _require_billing_role(user)
    tenant = _tenant_id(user, tenant_id)
    plan = str(plan_key or "").strip().lower()
    if plan not in PLAN_KEYS:
        raise BillingError("Unknown plan", status_code=422)
    price_id = price_id_for_plan(plan)
    if not price_id:
        raise BillingError("Stripe price is not configured for this plan", status_code=503)
    _require_stripe_mode()

    row = _get_or_create_row(db, tenant)
    if row.subscription_status in {STATUS_TRIALING, STATUS_ACTIVE} and row.stripe_subscription_id:
        raise BillingError("Tenant already has an active subscription", status_code=409)
    if (
        row.stripe_checkout_session_id
        and row.checkout_url
        and row.plan_key == plan
        and row.subscription_status == STATUS_INCOMPLETE
        and not row.stripe_subscription_id
    ):
        db.commit()
        return {
            "checkout_url": row.checkout_url,
            "checkout_session_id": row.stripe_checkout_session_id,
            "plan": plan,
            "status": row.subscription_status,
            "trial_applied": bool(row.trial_used and row.trial_started_at),
        }

    client = get_nova_billing_stripe_client()
    if not row.stripe_customer_id:
        customer = client.create_customer(
            payload={
                "email": user.email,
                "metadata": {
                    "nova_product": "nova_saas",
                    "nova_tenant_id": tenant,
                    "nova_user_id": user.user_id,
                },
            },
            idempotency_key=f"nova-billing-customer:{tenant}",
        )
        customer_id = str(customer.get("id") or "").strip()
        if not customer_id:
            raise BillingError("Stripe customer could not be created", status_code=502)
        conflict = (
            db.query(NovaTenantSubscription)
            .filter(NovaTenantSubscription.stripe_customer_id == customer_id)
            .filter(NovaTenantSubscription.tenant_id != tenant)
            .first()
        )
        if conflict is not None:
            raise BillingError("Stripe customer already belongs to another tenant", status_code=409)
        row.stripe_customer_id = customer_id

    trial_days = nova_free_trial_days()
    apply_trial = _trial_eligible(row)
    subscription_data: dict[str, Any] = {
        "metadata": {
            "nova_product": "nova_saas",
            "nova_tenant_id": tenant,
            "nova_plan_key": plan,
            "nova_user_id": user.user_id,
        }
    }
    if apply_trial:
        subscription_data["trial_period_days"] = trial_days

    session = client.create_checkout_session(
        payload={
            "mode": "subscription",
            "customer": row.stripe_customer_id,
            "client_reference_id": tenant,
            "success_url": public_success_url(),
            "cancel_url": public_cancel_url(),
            "line_items": [{"price": price_id, "quantity": 1}],
            "metadata": {
                "nova_product": "nova_saas",
                "nova_tenant_id": tenant,
                "nova_plan_key": plan,
                "nova_user_id": user.user_id,
            },
            "subscription_data": subscription_data,
        },
        idempotency_key=f"nova-billing-checkout:{tenant}:{plan}:{int(row.trial_used)}:{row.subscription_status}",
    )
    session_id = str(session.get("id") or "").strip()
    checkout_url = str(session.get("url") or "").strip()
    if not session_id or not checkout_url:
        raise BillingError("Stripe Checkout session could not be created", status_code=502)

    row.plan_key = plan
    row.stripe_price_id = price_id
    row.stripe_checkout_session_id = session_id
    row.checkout_url = checkout_url
    row.subscription_status = STATUS_INCOMPLETE
    if apply_trial:
        started = now()
        row.trial_used = True
        row.trial_started_at = started
        row.trial_ends_at = started + timedelta(days=trial_days)
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    logger.info(
        "Nova billing checkout opened tenant_id=%s plan=%s trial_applied=%s",
        tenant,
        plan,
        apply_trial,
    )
    return {
        "checkout_url": checkout_url,
        "checkout_session_id": session_id,
        "plan": plan,
        "status": row.subscription_status,
        "trial_applied": apply_trial,
        "trial_ends_at": row.trial_ends_at.isoformat() if row.trial_ends_at else None,
    }


def start_portal(db: Session, *, user: UserContext, tenant_id: str | None = None) -> dict[str, Any]:
    ensure_nova_billing_schema()
    _require_billing_role(user)
    tenant = _tenant_id(user, tenant_id)
    _require_stripe_mode()
    row = (
        db.query(NovaTenantSubscription)
        .filter(NovaTenantSubscription.tenant_id == tenant)
        .first()
    )
    if row is None or not row.stripe_customer_id:
        raise BillingError("No Stripe customer exists for this tenant", status_code=404)
    client = get_nova_billing_stripe_client()
    session = client.create_billing_portal_session(
        payload={"customer": row.stripe_customer_id, "return_url": public_portal_return_url()},
        idempotency_key=f"nova-billing-portal:{tenant}:{row.stripe_customer_id}",
    )
    url = str(session.get("url") or "").strip()
    if not url:
        raise BillingError("Billing portal session could not be created", status_code=502)
    logger.info("Nova billing portal opened tenant_id=%s", tenant)
    return {"portal_url": url}


def subscription_status(db: Session, *, user: UserContext, tenant_id: str | None = None) -> dict[str, Any]:
    ensure_nova_billing_schema()
    _require_billing_role(user)
    tenant = _tenant_id(user, tenant_id)
    row = (
        db.query(NovaTenantSubscription)
        .filter(NovaTenantSubscription.tenant_id == tenant)
        .first()
    )
    if row is None:
        return {
            "plan": None,
            "status": None,
            "trial_ends_at": None,
            "current_period_end": None,
            "cancel_at_period_end": False,
            "has_access": nova_subscription_has_access(None),
            "enforcement": nova_subscription_enforcement_enabled(),
        }
    body = {
        "plan": row.plan_key,
        "status": row.subscription_status,
        "trial_ends_at": row.trial_ends_at.isoformat() if row.trial_ends_at else None,
        "current_period_end": row.current_period_end.isoformat() if row.current_period_end else None,
        "cancel_at_period_end": bool(row.cancel_at_period_end),
        "has_access": nova_subscription_has_access(row.subscription_status),
        "enforcement": nova_subscription_enforcement_enabled(),
    }
    serialized = json.dumps(body)
    if "sk_" in serialized or "whsec_" in serialized or "rk_" in serialized:
        raise BillingError("Subscription payload refused", status_code=500)
    return body


def verify_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    secret = nova_billing_webhook_secret()
    if not secret:
        raise BillingError("Nova billing webhook secret is not configured", status_code=503)
    if not signature:
        raise BillingError("Missing Stripe-Signature header", status_code=400)
    import stripe

    try:
        stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise BillingError("Invalid webhook.", status_code=400) from exc
    parsed = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload))
    if not isinstance(parsed, dict):
        raise BillingError("Invalid webhook payload", status_code=400)
    return parsed


def _event_object(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data, dict) else None
    return obj if isinstance(obj, dict) else {}


def _tenant_from_obj(obj: dict[str, Any]) -> str | None:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    value = metadata.get("nova_tenant_id") or obj.get("client_reference_id")
    return str(value).strip() if value else None


def _row_for_event(db: Session, obj: dict[str, Any]) -> NovaTenantSubscription | None:
    tenant_id = _tenant_from_obj(obj)
    if tenant_id:
        row = (
            db.query(NovaTenantSubscription)
            .filter(NovaTenantSubscription.tenant_id == tenant_id)
            .first()
        )
        if row is not None:
            return row
    customer_id = obj.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    if customer_id:
        row = (
            db.query(NovaTenantSubscription)
            .filter(NovaTenantSubscription.stripe_customer_id == str(customer_id))
            .first()
        )
        if row is not None:
            return row
    subscription_id = obj.get("subscription") or obj.get("id")
    if isinstance(subscription_id, dict):
        subscription_id = subscription_id.get("id")
    if subscription_id and str(subscription_id).startswith("sub_"):
        return (
            db.query(NovaTenantSubscription)
            .filter(NovaTenantSubscription.stripe_subscription_id == str(subscription_id))
            .first()
        )
    return None


def _apply_subscription_object(row: NovaTenantSubscription, obj: dict[str, Any], *, deleted: bool = False) -> None:
    status = _map_status(str(obj.get("status") or ""), deleted=deleted)
    row.subscription_status = status
    sub_id = obj.get("id") if str(obj.get("object") or "") == "subscription" else obj.get("subscription")
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id")
    if sub_id and str(sub_id).startswith("sub_"):
        row.stripe_subscription_id = str(sub_id)
    customer_id = obj.get("customer")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    if customer_id:
        row.stripe_customer_id = str(customer_id)
    items = obj.get("items") if isinstance(obj.get("items"), dict) else {}
    data = items.get("data") if isinstance(items, dict) else None
    if data:
        first = data[0] if isinstance(data[0], dict) else {}
        price = first.get("price") if isinstance(first.get("price"), dict) else {}
        price_id = price.get("id") or first.get("price")
        if price_id:
            row.stripe_price_id = str(price_id)
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    plan = str(metadata.get("nova_plan_key") or row.plan_key or "").strip().lower()
    if plan:
        row.plan_key = plan
    row.cancel_at_period_end = bool(obj.get("cancel_at_period_end"))
    row.current_period_start = _dt(obj.get("current_period_start")) or row.current_period_start
    row.current_period_end = _dt(obj.get("current_period_end")) or row.current_period_end
    trial_start = _dt(obj.get("trial_start"))
    trial_end = _dt(obj.get("trial_end"))
    if trial_start:
        row.trial_used = True
        row.trial_started_at = row.trial_started_at or trial_start
    if trial_end:
        row.trial_ends_at = trial_end
    if status == STATUS_TRIALING:
        row.trial_used = True
    row.updated_at = now()


def process_webhook(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    ensure_nova_billing_schema()
    event_id = str(event.get("id") or "").strip()
    event_type = str(event.get("type") or "")
    if not event_id:
        raise BillingError("Webhook event id is required", status_code=400)
    existing = (
        db.query(NovaBillingWebhookEvent)
        .filter(NovaBillingWebhookEvent.stripe_event_id == event_id)
        .first()
    )
    if existing is not None:
        logger.info("Nova billing webhook duplicate ignored event_id=%s type=%s", event_id, event_type)
        return {"duplicate": True, "result": "ignored"}

    obj = _event_object(event)
    row = _row_for_event(db, obj)
    result = "ignored"
    if row is None:
        result = "unmatched"
    elif event_type == "checkout.session.completed":
        customer_id = obj.get("customer")
        if isinstance(customer_id, dict):
            customer_id = customer_id.get("id")
        subscription_id = obj.get("subscription")
        if isinstance(subscription_id, dict):
            subscription_id = subscription_id.get("id")
        if customer_id:
            row.stripe_customer_id = str(customer_id)
        if subscription_id:
            row.stripe_subscription_id = str(subscription_id)
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        plan = str(metadata.get("nova_plan_key") or row.plan_key or "").strip().lower()
        if plan:
            row.plan_key = plan
        if row.trial_used and _aware(row.trial_ends_at) and _aware(row.trial_ends_at) > now():
            row.subscription_status = STATUS_TRIALING
        else:
            row.subscription_status = STATUS_ACTIVE if obj.get("payment_status") in {"paid", "no_payment_required"} else STATUS_INCOMPLETE
        row.updated_at = now()
        result = "checkout_completed"
    elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
        _apply_subscription_object(row, obj)
        result = "subscription_synced"
    elif event_type == "customer.subscription.deleted":
        _apply_subscription_object(row, obj, deleted=True)
        if row.current_period_end and _aware(row.current_period_end) <= now():
            row.subscription_status = STATUS_EXPIRED
        result = "subscription_deleted"
    elif event_type == "invoice.paid":
        if row.subscription_status != STATUS_TRIALING:
            row.subscription_status = STATUS_ACTIVE
        subscription_id = obj.get("subscription")
        if isinstance(subscription_id, dict):
            subscription_id = subscription_id.get("id")
        if subscription_id:
            row.stripe_subscription_id = str(subscription_id)
        row.updated_at = now()
        result = "invoice_paid"
    elif event_type == "invoice.payment_failed":
        row.subscription_status = STATUS_PAST_DUE
        row.updated_at = now()
        result = "invoice_failed"

    db.add(
        NovaBillingWebhookEvent(
            stripe_event_id=event_id,
            event_type=event_type or "unknown",
            tenant_id=row.tenant_id if row is not None else _tenant_from_obj(obj),
            processing_result=result,
        )
    )
    db.commit()
    logger.info(
        "Nova billing webhook processed event_type=%s result=%s tenant_id=%s",
        event_type,
        result,
        row.tenant_id if row is not None else None,
    )
    return {"duplicate": False, "result": result}


def safe_error_detail(exc: Exception) -> str:
    return sanitize_stripe_error(str(exc))
