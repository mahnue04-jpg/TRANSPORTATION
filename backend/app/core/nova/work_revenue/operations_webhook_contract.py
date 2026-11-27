"""Exact Operations Stripe webhook routes and the events each one must receive.

Marketing confirms the $49, $99, and $299 packages. SaaS billing confirms the
authenticated $9.99 Starter subscription. These are not the Ride/Deliver
customer-payment webhook, the founding-signup webhook, or the ledger-only
payment-intake receiver.
"""

from __future__ import annotations

import os

MARKETING_WEBHOOK_PATH = "/api/marketing/nova-agent/stripe/webhook"
MARKETING_WEBHOOK_SECRET_ENV = "STRIPE_NOVA_AGENT_WEBHOOK_SECRET"

SAAS_WEBHOOK_PATH = "/api/nova/billing/webhook"
SAAS_WEBHOOK_SECRET_ENV = "STRIPE_NOVA_BILLING_WEBHOOK_SECRET"

# Ledger-only. It records event identity and does not fulfill a package.
PAYMENT_INTAKE_WEBHOOK_PATH = "/payments/stripe/webhook"
PAYMENT_INTAKE_SECRET_ENV = "NOVA_OPERATIONS_LIVE_WEBHOOK_SECRET"

# Separate products. Do not register Operations package events here.
EXCLUDED_WEBHOOK_PATHS = (
    "/api/payments/stripe/webhook",
    "/api/nova/signup/stripe/webhook",
    "/api/platform-ops/driver-onboarding/stripe/webhook",
)

# Events that change paid confirmation or entitlement for Starter Task,
# Launch Operations, and Business Operations.
MARKETING_REQUIRED_EVENTS = (
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "checkout.session.async_payment_failed",
    "checkout.session.expired",
    "invoice.paid",
    "invoice.payment_failed",
    "charge.refunded",
    "charge.dispute.created",
    "charge.dispute.funds_withdrawn",
)

# Events that change the authenticated Nova billing subscription.
SAAS_REQUIRED_EVENTS = (
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
    "charge.refunded",
)


def _secret_configured(value: str) -> bool:
    token = str(value or "").strip()
    return token.startswith("whsec_") and "\n" not in token and len(token) <= 256


def operations_webhook_contract() -> dict:
    """Non-secret route and event contract for Dashboard registration."""
    from app.core.nova.billing.stripe_client import nova_billing_webhook_secret
    from app.modules.marketing.operations_billing import agent_webhook_secret

    return {
        "marketing": {
            "method": "POST",
            "path": MARKETING_WEBHOOK_PATH,
            "secret_env": MARKETING_WEBHOOK_SECRET_ENV,
            "secret_configured": _secret_configured(agent_webhook_secret()),
            "packages": ["starter_49", "launch_99", "business_299"],
            "required_events": list(MARKETING_REQUIRED_EVENTS),
            "fulfills_package": False,
        },
        "saas": {
            "method": "POST",
            "path": SAAS_WEBHOOK_PATH,
            "secret_env": SAAS_WEBHOOK_SECRET_ENV,
            "secret_configured": _secret_configured(nova_billing_webhook_secret()),
            "packages": ["starter"],
            "required_events": list(SAAS_REQUIRED_EVENTS),
            "fulfills_package": False,
        },
        "payment_intake_not_fulfillment": {
            "method": "POST",
            "path": PAYMENT_INTAKE_WEBHOOK_PATH,
            "secret_env": PAYMENT_INTAKE_SECRET_ENV,
            "secret_configured": _secret_configured(os.getenv(PAYMENT_INTAKE_SECRET_ENV, "")),
            "records_ledger_only": True,
            "fulfills_package": False,
        },
        "not_fulfillment_routes": list(EXCLUDED_WEBHOOK_PATHS)
        + [PAYMENT_INTAKE_WEBHOOK_PATH],
    }
