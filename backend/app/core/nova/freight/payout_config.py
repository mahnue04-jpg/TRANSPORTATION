"""Nova freight V1 carrier payout share.

TEST DEFAULT ONLY. The 70% carrier share is a temporary placeholder for
current testing. It is not permanent business policy and must be changed
only in this file.
"""
from __future__ import annotations

from decimal import Decimal

from app.core.nova.freight.money import money

PAYOUT_POLICY_VERSION = "nova_freight_payout_v1_placeholder"
CARRIER_PAYOUT_RATIO = Decimal("0.70")
PAYOUT_METHOD_SIMULATED = "simulated_test"
DEFAULT_CURRENCY = "USD"


def split_customer_amount(customer_amount: object) -> tuple:
    customer = money(customer_amount)
    carrier = money(customer * CARRIER_PAYOUT_RATIO)
    margin = money(customer - carrier)
    if customer != money(carrier + margin):
        margin = money(customer - carrier)
    return customer, carrier, margin
