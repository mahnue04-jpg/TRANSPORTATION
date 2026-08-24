"""Shared Amicor Ride + Deliver customer-payment webhooks.

Isolated from Stripe Connect driver-onboarding (account.updated).
Does not create connected accounts or send live payouts.
Production schema is applied only by Alembic.
"""

from app.modules.payments.models import (
    PAYMENT_TABLE_NAMES,
    ensure_payments_test_schema,
    payments_autocreate_allowed,
)

__all__ = [
    "PAYMENT_TABLE_NAMES",
    "ensure_payments_test_schema",
    "payments_autocreate_allowed",
]
