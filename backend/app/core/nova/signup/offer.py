"""Approved AMICOR Nova founding-customer offer. $29 is not part of this path."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

INTRO_DAYS = 7
FOUNDING_CAP = 10
FOUNDING_PAID_MONTHS = 3
FOUNDING_UNIT_AMOUNT = 5900
STANDARD_UNIT_AMOUNT = 9900
CURRENCY = "usd"
INTERVAL = "month"
REJECTED_UNIT_AMOUNTS = (2900,)

FOUNDING_PRICE_LOOKUP = "nova_saas_founding_monthly"
STANDARD_PRICE_LOOKUP = "nova_saas_standard_monthly"
FOUNDING_PRODUCT_NAME = "AMICOR Nova Founding Customer"
STANDARD_PRODUCT_NAME = "AMICOR Nova"
PRODUCT_METADATA = {"nova_product": "nova_saas"}

FOUNDING_COPY = (
    "First 10 paying businesses: 7 days introductory access, "
    "then $59/month for the first 3 paid months, then $99/month."
)
STANDARD_COPY = "7 days introductory access, then $99/month."


def founding_remaining(occupied: int) -> int:
    return max(0, FOUNDING_CAP - max(0, int(occupied)))


def founding_available(occupied: int) -> bool:
    return founding_remaining(occupied) > 0


def public_offer(*, occupied: int) -> dict[str, Any]:
    remaining = founding_remaining(occupied)
    available = remaining > 0
    return {
        "product": "AMICOR Nova",
        "intro_days": INTRO_DAYS,
        "founding_cap": FOUNDING_CAP,
        "founding_slots_remaining": remaining,
        "founding_available": available,
        "founding_amount_usd": 59,
        "founding_paid_months": FOUNDING_PAID_MONTHS,
        "standard_amount_usd": 99,
        "rejected_prices_usd": [29],
        "copy": FOUNDING_COPY if available else STANDARD_COPY,
        "terms_url": "/terms",
    }


def intro_end_at(started_at: datetime) -> datetime:
    return started_at + timedelta(days=INTRO_DAYS)


def billing_plan(*, founding_eligible: bool) -> dict[str, Any]:
    """Canonical Stripe schedule intent. Trial never counts as a paid month."""
    if founding_eligible:
        return {
            "tier": "founding",
            "trial_period_days": INTRO_DAYS,
            "currency": CURRENCY,
            "interval": INTERVAL,
            "phases": [
                {
                    "price_lookup": FOUNDING_PRICE_LOOKUP,
                    "product_name": FOUNDING_PRODUCT_NAME,
                    "unit_amount": FOUNDING_UNIT_AMOUNT,
                    "iterations": FOUNDING_PAID_MONTHS,
                    "duration": {"interval": INTERVAL, "interval_count": FOUNDING_PAID_MONTHS},
                    "trial_period_days": INTRO_DAYS,
                },
                {
                    "price_lookup": STANDARD_PRICE_LOOKUP,
                    "product_name": STANDARD_PRODUCT_NAME,
                    "unit_amount": STANDARD_UNIT_AMOUNT,
                    "iterations": None,
                    "trial_period_days": 0,
                },
            ],
        }
    return {
        "tier": "standard",
        "trial_period_days": INTRO_DAYS,
        "currency": CURRENCY,
        "interval": INTERVAL,
        "phases": [
            {
                "price_lookup": STANDARD_PRICE_LOOKUP,
                "product_name": STANDARD_PRODUCT_NAME,
                "unit_amount": STANDARD_UNIT_AMOUNT,
                "iterations": None,
                "trial_period_days": INTRO_DAYS,
            }
        ],
    }


def expected_unit_amount(*, founding: bool, paid_month_index: int) -> int:
    """paid_month_index is 0 during intro, 1–3 founding paid months, 4+ standard."""
    if int(paid_month_index) <= 0:
        return 0
    if founding and int(paid_month_index) <= FOUNDING_PAID_MONTHS:
        return FOUNDING_UNIT_AMOUNT
    return STANDARD_UNIT_AMOUNT


def assert_no_rejected_prices(plan: dict[str, Any]) -> None:
    amounts = [int(phase["unit_amount"]) for phase in plan.get("phases") or []]
    for banned in REJECTED_UNIT_AMOUNTS:
        if banned in amounts:
            raise ValueError("Rejected $29 Nova pricing is not allowed on this path")
