"""Shared Amicor Ride + Deliver customer-payment webhooks.

Isolated from Stripe Connect driver-onboarding (account.updated).
Does not create connected accounts or send live payouts.
"""

from app.modules.payments.models import ensure_payments_schema

__all__ = ["ensure_payments_schema"]
