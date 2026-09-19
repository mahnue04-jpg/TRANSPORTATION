"""Nova founding-customer signup, TEST checkout, webhook activation, and tenant provision."""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import (
    _EMAIL_RE,
    _MAX_PASSWORD_LEN,
    _MIN_PASSWORD_LEN,
    _validate_email,
    _validate_password,
    hash_password,
)
from app.core.nova.signup.isolation import is_nova_saas_customer_org
from app.core.nova.signup.models import (
    ACTIVATED_STATUSES,
    HOLD_FOUNDING_STATUSES,
    STATUS_ACTIVE,
    STATUS_CANCELED,
    STATUS_CHECKOUT_OPEN,
    STATUS_EXPIRED,
    STATUS_FAILED,
    STATUS_PAST_DUE,
    STATUS_PENDING,
    STATUS_TRIALING,
    NovaCustomerTenant,
    NovaSignupAccount,
    NovaSignupWebhookEvent,
)
from app.core.nova.signup.offer import (
    FOUNDING_CAP,
    billing_plan,
    expected_unit_amount,
    intro_end_at,
    public_offer,
)
from app.core.nova.signup.schema_ensure import ensure_nova_signup_schema
from app.core.nova.signup.stripe_client import (
    get_nova_saas_stripe_client,
    get_nova_saas_stripe_override,
    nova_saas_webhook_secret,
    sanitize_stripe_error,
)
from app.core.nova.tenants.provision import TenantProvisionError, provision_isolated_nova_tenant
from app.helpers import now

logger = logging.getLogger("amicor.nova.signup")

SUCCESS_PAYMENT_STATUSES = frozenset({"paid", "no_payment_required"})


class SignupError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


def _norm(value: str | None, *, field: str, min_len: int, max_len: int) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) < min_len:
        raise SignupError(f"{field} is required", status_code=422)
    if len(cleaned) > max_len:
        raise SignupError(f"{field} is too long", status_code=422)
    return cleaned


def founding_occupied_count(db: Session) -> int:
    ensure_nova_signup_schema()
    reserved = (
        db.query(func.count(NovaSignupAccount.id))
        .filter(NovaSignupAccount.founding_reserved == True)  # noqa: E712
        .filter(NovaSignupAccount.status.in_(HOLD_FOUNDING_STATUSES))
        .scalar()
        or 0
    )
    return int(reserved)


def offer_payload(db: Session) -> dict[str, Any]:
    return public_offer(occupied=founding_occupied_count(db))


def _next_founding_slot(db: Session) -> int | None:
    used = {
        int(row.founding_slot)
        for row in db.query(NovaSignupAccount.founding_slot)
        .filter(NovaSignupAccount.founding_slot.isnot(None))
        .filter(NovaSignupAccount.status.in_(HOLD_FOUNDING_STATUSES))
        .all()
        if row.founding_slot is not None
    }
    for slot in range(1, FOUNDING_CAP + 1):
        if slot not in used:
            return slot
    return None


def create_signup(
    db: Session,
    *,
    business_name: str,
    contact_name: str,
    email: str,
    phone: str,
    industry: str,
    password: str,
    terms_accepted: bool,
) -> NovaSignupAccount:
    ensure_nova_signup_schema()
    if not terms_accepted:
        raise SignupError("Terms must be accepted", status_code=422)
    business_name = _norm(business_name, field="Business name", min_len=3, max_len=128)
    contact_name = _norm(contact_name, field="Contact name", min_len=2, max_len=128)
    industry = _norm(industry, field="Industry", min_len=2, max_len=128)
    phone = _norm(phone, field="Phone", min_len=7, max_len=40)
    try:
        email = _validate_email(email)
        _validate_password(password)
    except HTTPException as exc:
        raise SignupError(str(exc.detail), status_code=int(exc.status_code or 422)) from exc
    if not _EMAIL_RE.match(email):
        raise SignupError("Invalid email address", status_code=422)
    if len(password) < _MIN_PASSWORD_LEN or len(password) > _MAX_PASSWORD_LEN:
        raise SignupError("Password does not meet requirements", status_code=422)

    existing = db.query(NovaSignupAccount).filter(func.lower(NovaSignupAccount.email) == email).first()
    if existing is not None:
        if existing.status in ACTIVATED_STATUSES:
            raise SignupError("Email already registered", status_code=409)
        if existing.status in {STATUS_PENDING, STATUS_CHECKOUT_OPEN, STATUS_FAILED, STATUS_EXPIRED}:
            existing.business_name = business_name
            existing.contact_name = contact_name
            existing.phone = phone
            existing.industry = industry
            existing.password_hash = hash_password(password)
            existing.terms_accepted_at = now()
            existing.status = STATUS_PENDING
            existing.last_error = None
            existing.updated_at = now()
            db.commit()
            db.refresh(existing)
            return existing
        raise SignupError("Email already registered", status_code=409)

    from app.db.models import User as UserModel

    if db.query(UserModel).filter(func.lower(UserModel.email) == email).first() is not None:
        raise SignupError("Email already registered", status_code=409)

    row = NovaSignupAccount(
        business_name=business_name,
        contact_name=contact_name,
        email=email,
        phone=phone,
        industry=industry,
        password_hash=hash_password(password),
        terms_accepted_at=now(),
        status=STATUS_PENDING,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("Nova signup created signup_id=%s", row.id)
    return row


def _public_base_url() -> str:
    return (
        os.getenv("NOVA_SIGNUP_PUBLIC_BASE_URL")
        or os.getenv("PUBLIC_BASE_URL")
        or "https://amicor-health-isf-py.onrender.com"
    ).rstrip("/")


def start_checkout(db: Session, *, signup_id: str) -> dict[str, Any]:
    ensure_nova_signup_schema()
    row = db.get(NovaSignupAccount, signup_id)
    if row is None:
        raise SignupError("Signup not found", status_code=404)
    if row.status in ACTIVATED_STATUSES:
        raise SignupError("Signup already activated", status_code=409)

    occupied = founding_occupied_count(db)
    if row.founding_reserved and row.founding_slot:
        occupied = max(0, occupied - 1)
    founding_eligible = occupied < FOUNDING_CAP
    slot = _next_founding_slot(db) if founding_eligible else None
    if founding_eligible and slot is None:
        founding_eligible = False
    plan = billing_plan(founding_eligible=founding_eligible)

    try:
        client = get_nova_saas_stripe_client()
        session = client.create_checkout_session(
            payload={
                "mode": "subscription",
                "success_url": f"{_public_base_url()}/nova/signup/success?signup_id={row.id}&session_id={{CHECKOUT_SESSION_ID}}",
                "cancel_url": f"{_public_base_url()}/nova/signup?signup_id={row.id}",
                "client_reference_id": row.id,
                "customer_email": row.email,
                "metadata": {
                    "nova_signup_id": row.id,
                    "nova_product": "nova_saas",
                    "nova_tier": plan["tier"],
                },
                "subscription_data": {
                    "trial_period_days": plan["trial_period_days"],
                    "metadata": {
                        "nova_signup_id": row.id,
                        "nova_product": "nova_saas",
                        "nova_tier": plan["tier"],
                    },
                },
                "line_items": [{"price_lookup": plan["phases"][0]["price_lookup"], "quantity": 1}],
            }
        )
    except ValueError as exc:
        raise SignupError(str(exc), status_code=503) from exc
    except Exception as exc:
        raise SignupError(f"Stripe checkout is unavailable: {sanitize_stripe_error(exc)}", status_code=503) from exc

    row.status = STATUS_CHECKOUT_OPEN
    row.founding_reserved = bool(founding_eligible and slot is not None)
    row.founding_slot = slot if row.founding_reserved else None
    row.stripe_checkout_session_id = str(session.get("id") or "") or None
    row.checkout_url = str(session.get("url") or "") or None
    row.updated_at = now()
    db.commit()
    db.refresh(row)
    return checkout_view(db, row, plan=plan, session=session)


def checkout_view(
    db: Session,
    row: NovaSignupAccount,
    *,
    plan: dict[str, Any] | None = None,
    session: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = plan or billing_plan(founding_eligible=bool(row.founding_reserved))
    return {
        "signup_id": row.id,
        "status": row.status,
        "email": row.email,
        "business_name": row.business_name,
        "founding_eligible": bool(row.founding_reserved),
        "founding_slot": row.founding_slot,
        "offer": offer_payload(db),
        "plan": plan,
        "checkout_url": row.checkout_url,
        "checkout_session_id": row.stripe_checkout_session_id,
        "stripe_session": {"id": (session or {}).get("id"), "status": (session or {}).get("status")} if session else None,
        "login_ready": row.status in ACTIVATED_STATUSES,
        "intro_ends_at": row.intro_ends_at.isoformat() if row.intro_ends_at else None,
        "organization_id": row.organization_id,
    }


def signup_status(db: Session, signup_id: str) -> dict[str, Any]:
    ensure_nova_signup_schema()
    row = db.get(NovaSignupAccount, signup_id)
    if row is None:
        raise SignupError("Signup not found", status_code=404)
    return checkout_view(db, row)


def customer_access(db: Session, *, organization_id: str | None, user_id: str | None) -> dict[str, Any]:
    ensure_nova_signup_schema()
    saas = is_nova_saas_customer_org(db, organization_id)
    tenant = None
    if organization_id:
        tenant = (
            db.query(NovaCustomerTenant)
            .filter(NovaCustomerTenant.organization_id == str(organization_id))
            .first()
        )
    return {
        "nova_saas_customer": saas,
        "product_scope": "nova" if saas else "internal",
        "allowed_surfaces": ["nova_today", "nova_command_center", "nova_workspace", "nova_login"],
        "blocked_surfaces": (
            ["health", "delivery", "freight", "lifesaver", "driver001", "admin", "internal"]
            if saas
            else []
        ),
        "founding_member": bool(tenant.founding_member) if tenant is not None else False,
        "subscription_status": tenant.subscription_status if tenant is not None else None,
        "owner_user_id": tenant.owner_user_id if tenant is not None else user_id,
    }


def verify_webhook(payload: bytes, signature: str | None) -> dict[str, Any]:
    override = get_nova_saas_stripe_override()
    if override is not None and not signature:
        parsed = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload))
        if not isinstance(parsed, dict):
            raise SignupError("Invalid webhook payload", status_code=400)
        return parsed
    secret = nova_saas_webhook_secret()
    if not secret:
        raise SignupError("Nova SaaS webhook secret is not configured", status_code=503)
    if not signature:
        raise SignupError("Missing Stripe-Signature header", status_code=400)
    import stripe

    try:
        stripe.Webhook.construct_event(payload, signature, secret)
    except Exception as exc:
        raise SignupError("Invalid webhook.", status_code=400) from exc
    parsed = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload))
    if not isinstance(parsed, dict):
        raise SignupError("Invalid webhook payload", status_code=400)
    return parsed


def _event_object(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data, dict) else None
    return obj if isinstance(obj, dict) else {}


def _signup_id_from_event(obj: dict[str, Any]) -> str | None:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    value = metadata.get("nova_signup_id") or obj.get("client_reference_id")
    if value:
        return str(value).strip()

    subscription_details = obj.get("subscription_details")
    if isinstance(subscription_details, dict):
        details_meta = subscription_details.get("metadata")
        if isinstance(details_meta, dict) and details_meta.get("nova_signup_id"):
            return str(details_meta.get("nova_signup_id")).strip()

    parent = obj.get("parent")
    if isinstance(parent, dict):
        parent_details = parent.get("subscription_details")
        if isinstance(parent_details, dict):
            parent_meta = parent_details.get("metadata")
            if isinstance(parent_meta, dict) and parent_meta.get("nova_signup_id"):
                return str(parent_meta.get("nova_signup_id")).strip()
    return None


def _subscription_id_from_event(obj: dict[str, Any]) -> str | None:
    raw = obj.get("subscription")
    if isinstance(raw, dict):
        raw = raw.get("id")
    if raw:
        return str(raw).strip()

    subscription_details = obj.get("subscription_details")
    if isinstance(subscription_details, dict):
        raw = subscription_details.get("subscription")
        if isinstance(raw, dict):
            raw = raw.get("id")
        if raw:
            return str(raw).strip()

    parent = obj.get("parent")
    if isinstance(parent, dict):
        parent_details = parent.get("subscription_details")
        if isinstance(parent_details, dict):
            raw = parent_details.get("subscription")
            if isinstance(raw, dict):
                raw = raw.get("id")
            if raw:
                return str(raw).strip()
    return None


def _signup_id_from_subscription(db: Session, subscription_id: str | None) -> str | None:
    if not subscription_id:
        return None
    row = (
        db.query(NovaSignupAccount)
        .filter(NovaSignupAccount.stripe_subscription_id == str(subscription_id))
        .first()
    )
    return row.id if row is not None else None


def _event_seen(db: Session, event: dict[str, Any]) -> bool:
    event_id = str(event.get("id") or "").strip()
    if not event_id:
        raise SignupError("Webhook event id is required", status_code=400)
    existing = (
        db.query(NovaSignupWebhookEvent)
        .filter(NovaSignupWebhookEvent.stripe_event_id == event_id)
        .first()
    )
    return existing is not None


def _store_event(db: Session, event: dict[str, Any], *, signup_id: str | None, result: str) -> None:
    db.add(
        NovaSignupWebhookEvent(
            stripe_event_id=str(event.get("id") or "").strip(),
            event_type=str(event.get("type") or "unknown"),
            signup_id=signup_id,
            processing_result=result,
        )
    )


def process_webhook(db: Session, event: dict[str, Any]) -> dict[str, Any]:
    ensure_nova_signup_schema()
    obj = _event_object(event)
    signup_id = _signup_id_from_event(obj)
    event_type = str(event.get("type") or "")
    if signup_id is None and event_type.startswith("invoice."):
        signup_id = _signup_id_from_subscription(db, _subscription_id_from_event(obj))
    if _event_seen(db, event):
        return {"duplicate": True, "result": "ignored"}

    if event_type == "checkout.session.completed":
        result = _activate_from_checkout(db, obj)
    elif event_type in {"checkout.session.async_payment_failed", "invoice.payment_failed"}:
        result = _mark_payment_failed(db, obj, signup_id=signup_id)
    elif event_type == "checkout.session.expired":
        result = _expire_checkout(db, signup_id)
    elif event_type in {"customer.subscription.deleted", "customer.subscription.updated"}:
        result = _sync_subscription(db, obj, signup_id=signup_id)
    elif event_type == "invoice.paid":
        result = _record_paid_invoice(db, obj, signup_id=signup_id)
    else:
        result = {"handled": False, "result": "ignored"}
    _store_event(db, event, signup_id=signup_id or result.get("signup_id"), result=str(result.get("result") or "ok"))
    db.commit()
    return {"duplicate": False, **result}


def _expire_checkout(db: Session, signup_id: str | None) -> dict[str, Any]:
    if not signup_id:
        return {"handled": True, "result": "unrelated"}
    row = db.get(NovaSignupAccount, signup_id)
    if row is None or row.status in ACTIVATED_STATUSES:
        return {"handled": True, "result": "ignored"}
    row.status = STATUS_EXPIRED
    row.founding_reserved = False
    row.founding_slot = None
    row.updated_at = now()
    return {"handled": True, "result": "expired", "signup_id": row.id}


def _mark_payment_failed(db: Session, obj: dict[str, Any], *, signup_id: str | None) -> dict[str, Any]:
    row = db.get(NovaSignupAccount, signup_id) if signup_id else None
    if row is None:
        return {"handled": True, "result": "unrelated", "activated": False}
    if row.status in ACTIVATED_STATUSES:
        row.status = STATUS_PAST_DUE
        row.last_error = "payment_failed"
        row.updated_at = now()
        tenant = db.query(NovaCustomerTenant).filter(NovaCustomerTenant.signup_id == row.id).first()
        if tenant is not None:
            tenant.subscription_status = STATUS_PAST_DUE
        return {"handled": True, "result": "past_due", "activated": True, "paid_activated": False, "signup_id": row.id}
    row.status = STATUS_FAILED
    row.founding_reserved = False
    row.founding_slot = None
    row.last_error = "payment_failed"
    row.updated_at = now()
    return {"handled": True, "result": "failed", "activated": False, "paid_activated": False, "signup_id": row.id}


def _sync_subscription(db: Session, obj: dict[str, Any], *, signup_id: str | None) -> dict[str, Any]:
    status = str(obj.get("status") or "")
    row = db.get(NovaSignupAccount, signup_id) if signup_id else None
    if row is None:
        return {"handled": True, "result": "unrelated"}
    tenant = db.query(NovaCustomerTenant).filter(NovaCustomerTenant.signup_id == row.id).first()
    if status in {"canceled", "unpaid", "incomplete_expired"}:
        row.status = STATUS_CANCELED
        if tenant is not None:
            tenant.subscription_status = STATUS_CANCELED
        row.updated_at = now()
        return {"handled": True, "result": "canceled", "signup_id": row.id}
    if status == "past_due":
        row.status = STATUS_PAST_DUE
        if tenant is not None:
            tenant.subscription_status = STATUS_PAST_DUE
        row.updated_at = now()
        return {"handled": True, "result": "past_due", "signup_id": row.id}
    if status == "active" and row.status in ACTIVATED_STATUSES:
        row.status = STATUS_ACTIVE
        if tenant is not None:
            tenant.subscription_status = STATUS_ACTIVE
        row.updated_at = now()
        return {"handled": True, "result": "active", "signup_id": row.id}
    return {"handled": True, "result": "ignored", "signup_id": row.id}


def _record_paid_invoice(db: Session, obj: dict[str, Any], *, signup_id: str | None) -> dict[str, Any]:
    row = db.get(NovaSignupAccount, signup_id) if signup_id else None
    if row is None or row.status not in ACTIVATED_STATUSES:
        return {"handled": True, "result": "ignored", "paid_activated": False}
    billing_reason = str(obj.get("billing_reason") or "")
    amount_paid = int(obj.get("amount_paid") or 0)
    if billing_reason in {"subscription_create", "subscription_cycle", "subscription_update"} and amount_paid > 0:
        row.paid_month_index = int(row.paid_month_index or 0) + 1
        row.current_unit_amount = amount_paid
        row.status = STATUS_ACTIVE
        tenant = db.query(NovaCustomerTenant).filter(NovaCustomerTenant.signup_id == row.id).first()
        if tenant is not None:
            tenant.subscription_status = STATUS_ACTIVE
        expected = expected_unit_amount(founding=bool(row.founding_reserved), paid_month_index=row.paid_month_index)
        row.updated_at = now()
        return {
            "handled": True,
            "result": "paid",
            "paid_activated": True,
            "paid_month_index": row.paid_month_index,
            "unit_amount": amount_paid,
            "expected_unit_amount": expected,
            "signup_id": row.id,
        }
    return {"handled": True, "result": "trial_or_zero", "paid_activated": False, "signup_id": row.id}


def _activate_from_checkout(db: Session, session_obj: dict[str, Any]) -> dict[str, Any]:
    signup_id = _signup_id_from_event(session_obj)
    if not signup_id:
        return {"handled": True, "result": "unrelated", "activated": False}
    metadata = session_obj.get("metadata") if isinstance(session_obj.get("metadata"), dict) else {}
    if str(metadata.get("nova_product") or "") != "nova_saas":
        return {"handled": True, "result": "unrelated", "activated": False}
    payment_status = str(session_obj.get("payment_status") or "")
    if payment_status not in SUCCESS_PAYMENT_STATUSES:
        return _mark_payment_failed(db, session_obj, signup_id=signup_id)

    row = db.get(NovaSignupAccount, signup_id)
    if row is None:
        return {"handled": True, "result": "missing_signup", "activated": False}
    if row.status in ACTIVATED_STATUSES and row.organization_id:
        return {"handled": True, "result": "already_activated", "activated": True, "signup_id": row.id}

    subscription_id = str(session_obj.get("subscription") or "") or None
    customer_id = str(session_obj.get("customer") or "") or None
    if not subscription_id:
        return _mark_payment_failed(db, session_obj, signup_id=signup_id)

    plan = billing_plan(founding_eligible=bool(row.founding_reserved and row.founding_slot))
    try:
        schedule = get_nova_saas_stripe_client().apply_subscription_schedule(
            subscription_id=subscription_id,
            plan=plan,
        )
    except Exception as exc:
        logger.exception("Nova SaaS schedule apply failed signup_id=%s", row.id)
        raise SignupError(f"Subscription schedule failed: {sanitize_stripe_error(exc)}", status_code=503) from exc

    try:
        tenant = provision_isolated_nova_tenant(
            db,
            organization_name=row.business_name,
            owner_email=row.email,
            owner_display_name=row.contact_name,
            hashed_password=row.password_hash,
            actor_user_id="nova-signup-webhook",
        )
    except TenantProvisionError as exc:
        raise SignupError(str(exc), status_code=exc.status_code) from exc

    stamp = now()
    row.status = STATUS_TRIALING
    row.stripe_customer_id = customer_id
    row.stripe_subscription_id = subscription_id
    row.stripe_schedule_id = str(schedule.get("id") or "") or None
    row.organization_id = tenant.organization_id
    row.owner_user_id = tenant.owner_user_id
    row.intro_started_at = stamp
    row.intro_ends_at = intro_end_at(stamp)
    row.paid_month_index = 0
    row.current_unit_amount = 0
    row.updated_at = stamp

    existing_tenant = (
        db.query(NovaCustomerTenant).filter(NovaCustomerTenant.signup_id == row.id).first()
    )
    if existing_tenant is None:
        db.add(
            NovaCustomerTenant(
                signup_id=row.id,
                organization_id=tenant.organization_id,
                owner_user_id=tenant.owner_user_id,
                founding_member=bool(row.founding_reserved),
                founding_slot=row.founding_slot,
                subscription_status=STATUS_TRIALING,
                product_scope="nova",
                stripe_customer_id=customer_id,
                stripe_subscription_id=subscription_id,
            )
        )
    return {
        "handled": True,
        "result": "activated",
        "activated": True,
        "paid_activated": False,
        "intro": True,
        "founding": bool(row.founding_reserved),
        "organization_id": tenant.organization_id,
        "owner_user_id": tenant.owner_user_id,
        "signup_id": row.id,
        "plan": plan,
        "schedule_id": row.stripe_schedule_id,
    }
