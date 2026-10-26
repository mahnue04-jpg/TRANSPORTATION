"""Stay360 slice constants. Synthetic fixtures and in-process providers only."""

from __future__ import annotations

PRODUCT_NAME = "AMICOR Nova Stay360"
DESCRIPTOR = "Intelligent Hospitality Operations"
SLICE_ID = "guest-prearrival-room-readiness"

FIXTURE_DATE = "2026-10-26"
FIXTURE_TIMEZONE = "America/Chicago"

BLUEPRINT_NOTE = (
    "Hospitality & Travel Master Blueprint v1.1 (26 sections) is not in the repo, "
    "so later sections (parking, concierge, guest services, inventory safeguards, "
    "family/events, marketing, itinerary) are NOT implemented."
)

NOT_IMPLEMENTED = (
    "parking",
    "concierge",
    "guest_services",
    "inventory_safeguards",
    "family_events",
    "marketing",
    "itinerary",
)

HOTEL_ROLES = frozenset({"admin", "staff", "super_admin_support"})
ADMIN_ROLES = frozenset({"admin", "super_admin_support"})
GUEST_ROLE = "rider"

SENSITIVE_FIELDS = (
    "legal_name",
    "date_of_birth",
    "email",
    "phone",
    "government_id",
    "passport_number",
    "home_address",
    "payment_instrument_token",
    "loyalty_number",
)

FORBIDDEN_PUBLIC_KEYS = frozenset(
    set(SENSITIVE_FIELDS)
    | {
        "door_code",
        "lock_id",
        "mobile_key",
        "card_number",
        "payment_intent",
        "payment_method",
        "stripe_id",
        "access_code",
    }
)

ALLOWED_LIST_QUERY = frozenset({"reservation_reference"})

HOUSEKEEPING_STATUSES = ("dirty", "in_progress", "inspected", "out_of_order")
STAFF_TRANSITIONS = {
    "dirty": frozenset({"in_progress"}),
    "in_progress": frozenset({"inspected", "dirty"}),
    "inspected": frozenset({"dirty"}),
    "out_of_order": frozenset(),
}
ADMIN_TRANSITIONS = {
    "dirty": frozenset({"in_progress"}),
    "in_progress": frozenset({"inspected", "dirty"}),
    "inspected": frozenset({"dirty", "out_of_order"}),
    "out_of_order": frozenset({"dirty"}),
}

SUPPORTED_LOCALES = ("en", "es", "fr")
