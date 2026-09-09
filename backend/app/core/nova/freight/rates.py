"""Nova Freight V1 rate constants and suggested-quote engine.

Tax is not configured in V1 — tax_amount is always 0.00.
Fuel surcharge is a placeholder and defaults to 0.00.
No paid mapping API is used; dispatcher supplies estimated miles when needed.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal

from app.core.nova.freight.money import ZERO, money

RATE_ENGINE_VERSION = "nova_freight_v1"
DEFAULT_CURRENCY = "USD"
CARRIER_COST_RATIO = Decimal("0.70")
WEIGHT_STEP_LB = Decimal("10000")
WEIGHT_STEP_AMOUNT = Decimal("25.00")
PALLET_AMOUNT = Decimal("8.00")
HAZARDOUS_SURCHARGE = Decimal("75.00")
TEMPERATURE_SURCHARGE = Decimal("45.00")
FRAGILE_SURCHARGE = Decimal("20.00")
FUEL_SURCHARGE = Decimal("0.00")
HOURLY_AMOUNT = Decimal("0.00")

BASE_RATES: dict[str, Decimal] = {
    "van": Decimal("85.00"),
    "cargo_van": Decimal("95.00"),
    "box_truck": Decimal("145.00"),
    "straight_truck": Decimal("175.00"),
    "dry_van": Decimal("220.00"),
    "reefer": Decimal("260.00"),
    "flatbed": Decimal("240.00"),
    "other": Decimal("120.00"),
}

PER_MILE_RATES: dict[str, Decimal] = {
    "van": Decimal("1.85"),
    "cargo_van": Decimal("2.05"),
    "box_truck": Decimal("2.55"),
    "straight_truck": Decimal("2.75"),
    "dry_van": Decimal("2.95"),
    "reefer": Decimal("3.25"),
    "flatbed": Decimal("3.10"),
    "other": Decimal("2.25"),
}


def suggested_quote(
    *,
    equipment_type: str,
    estimated_miles: object = None,
    estimated_hours: object = None,
    weight: object = None,
    pallet_count: object = None,
    hazardous: bool = False,
    temperature_controlled: bool = False,
    fragile: bool = False,
    other_surcharge: object = None,
    discount_amount: object = None,
) -> dict[str, Decimal | str]:
    equipment = str(equipment_type or "cargo_van").strip() or "cargo_van"
    base_rate = money(BASE_RATES.get(equipment, BASE_RATES["other"]))
    miles = money(estimated_miles) if estimated_miles not in (None, "") else ZERO
    hours = money(estimated_hours) if estimated_hours not in (None, "") else ZERO
    mileage_amount = money(miles * PER_MILE_RATES.get(equipment, PER_MILE_RATES["other"]))
    time_amount = money(hours * HOURLY_AMOUNT)
    equipment_surcharge = ZERO
    special = ZERO
    if hazardous:
        special += HAZARDOUS_SURCHARGE
    if temperature_controlled:
        special += TEMPERATURE_SURCHARGE
    if fragile:
        special += FRAGILE_SURCHARGE
    special_handling_surcharge = money(special)
    fuel_surcharge = money(FUEL_SURCHARGE)
    other = money(other_surcharge)
    discount = money(discount_amount)
    if discount < ZERO:
        discount = ZERO
    weight_amount = ZERO
    weight_value = money(weight) if weight not in (None, "") else ZERO
    if weight_value > WEIGHT_STEP_LB:
        extra_steps = ((weight_value - WEIGHT_STEP_LB) / WEIGHT_STEP_LB).to_integral_value(rounding=ROUND_CEILING)
        weight_amount = money(Decimal(int(extra_steps)) * WEIGHT_STEP_AMOUNT)
    pallet_amount = ZERO
    if pallet_count not in (None, ""):
        pallet_amount = money(Decimal(int(pallet_count)) * PALLET_AMOUNT)
    tax_amount = ZERO
    subtotal = money(
        base_rate
        + mileage_amount
        + time_amount
        + equipment_surcharge
        + special_handling_surcharge
        + fuel_surcharge
        + other
        + weight_amount
        + pallet_amount
    )
    total = money(subtotal - discount + tax_amount)
    if total < ZERO:
        total = ZERO
    estimated_carrier_cost = money(total * CARRIER_COST_RATIO)
    estimated_amicor_margin = money(total - estimated_carrier_cost)
    return {
        "pricing_method": "rate_engine",
        "rate_engine_version": RATE_ENGINE_VERSION,
        "currency": DEFAULT_CURRENCY,
        "base_rate": base_rate,
        "mileage_amount": mileage_amount,
        "time_amount": time_amount,
        "equipment_surcharge": equipment_surcharge,
        "special_handling_surcharge": special_handling_surcharge,
        "fuel_surcharge": fuel_surcharge,
        "other_surcharge": other,
        "weight_amount": weight_amount,
        "pallet_amount": pallet_amount,
        "discount_amount": discount,
        "tax_amount": tax_amount,
        "suggested_amount": total,
        "total_customer_amount": total,
        "estimated_carrier_cost": estimated_carrier_cost,
        "estimated_amicor_margin": estimated_amicor_margin,
    }
