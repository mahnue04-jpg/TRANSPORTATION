"""Decimal money helpers for Nova freight. Never use float for amounts."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value: object) -> Decimal:
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        amount = value
    else:
        amount = Decimal(str(value))
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


def to_minor_units(value: object) -> int:
    amount = money(value)
    return int((amount * Decimal(100)).to_integral_value(rounding=ROUND_HALF_UP))


def from_minor_units(cents: int) -> Decimal:
    return money(Decimal(int(cents)) / Decimal(100))
