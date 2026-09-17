"""Nova subscription plan keys and TEST-mode configuration. No dollar amounts here."""
from __future__ import annotations

import os

PLAN_STARTER = "starter"
PLAN_PROFESSIONAL = "professional"
PLAN_BUSINESS = "business"
PLAN_KEYS = (PLAN_STARTER, PLAN_PROFESSIONAL, PLAN_BUSINESS)

PRICE_ENV = {
    PLAN_STARTER: "NOVA_STRIPE_PRICE_STARTER",
    PLAN_PROFESSIONAL: "NOVA_STRIPE_PRICE_PROFESSIONAL",
    PLAN_BUSINESS: "NOVA_STRIPE_PRICE_BUSINESS",
}

DEFAULT_TRIAL_DAYS = 7
BILLING_ROLES = ("admin", "super_admin_support")

STATUS_TRIALING = "trialing"
STATUS_ACTIVE = "active"
STATUS_PAST_DUE = "past_due"
STATUS_CANCELLED = "cancelled"
STATUS_EXPIRED = "expired"
STATUS_INCOMPLETE = "incomplete"

ACCESS_STATUSES = (STATUS_TRIALING, STATUS_ACTIVE)
STRIPE_STATUS_MAP = {
    "trialing": STATUS_TRIALING,
    "active": STATUS_ACTIVE,
    "past_due": STATUS_PAST_DUE,
    "unpaid": STATUS_PAST_DUE,
    "canceled": STATUS_CANCELLED,
    "cancelled": STATUS_CANCELLED,
    "incomplete": STATUS_INCOMPLETE,
    "incomplete_expired": STATUS_EXPIRED,
    "paused": STATUS_PAST_DUE,
}


def _truthy(raw: str | None) -> bool:
    return str(raw or "").strip().lower() in {"1", "true", "yes", "on"}


def nova_free_trial_days() -> int:
    raw = os.getenv("NOVA_FREE_TRIAL_DAYS", str(DEFAULT_TRIAL_DAYS)).strip() or str(DEFAULT_TRIAL_DAYS)
    try:
        days = int(raw)
    except ValueError:
        return DEFAULT_TRIAL_DAYS
    return days if days > 0 else DEFAULT_TRIAL_DAYS


def nova_subscription_enforcement_enabled() -> bool:
    return _truthy(os.getenv("NOVA_SUBSCRIPTION_ENFORCEMENT", "false"))


def nova_past_due_has_access() -> bool:
    return _truthy(os.getenv("NOVA_SUBSCRIPTION_PAST_DUE_ACCESS", "false"))


def price_id_for_plan(plan_key: str) -> str:
    env_name = PRICE_ENV.get(str(plan_key or "").strip().lower())
    if not env_name:
        return ""
    return os.getenv(env_name, "").strip()


def public_success_url() -> str:
    base = (os.getenv("AMICOR_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")
    return os.getenv("NOVA_BILLING_SUCCESS_URL", f"{base}/nova/today?billing=success").strip()


def public_cancel_url() -> str:
    base = (os.getenv("AMICOR_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")
    return os.getenv("NOVA_BILLING_CANCEL_URL", f"{base}/nova/today?billing=cancelled").strip()


def public_portal_return_url() -> str:
    base = (os.getenv("AMICOR_PUBLIC_URL") or "http://127.0.0.1:8000").rstrip("/")
    return os.getenv("NOVA_BILLING_PORTAL_RETURN_URL", f"{base}/nova/today").strip()
