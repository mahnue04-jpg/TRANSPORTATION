"""
Grant Command Center builders for the existing Health ISF Grants page.

Keeps grant-facing metrics conservative: known demo/seed/test rows are labeled
and excluded from verified grant evidence. Sensitive federal registration
identifiers are only surfaced when provided via server environment configuration.
"""
from __future__ import annotations

import os
from typing import Any

from app.modules.health_isf.service import (
    DEMO_SEED_PASSENGER_NAMES,
    SAMPLE_DRIVERS,
    SAMPLE_PROVIDERS,
    _is_ai_proof_ride,
    _is_test_ride_row,
    is_operational_excluded_ride,
)

INTEGRITY_VERIFIED = "VERIFIED LIVE DATA"
INTEGRITY_DEMO = "DEMO / TEST / SEEDED DATA"
INTEGRITY_PENDING = "PENDING VERIFICATION"

FINANCIAL_ACTUAL = "ACTUAL"
FINANCIAL_PROJECTED = "PROJECTED"
FINANCIAL_GRANT_REQUEST = "GRANT REQUEST"

# Explicit opt-in only. Platform rows alone are not treated as commercial proof.
_COMMERCIAL_VERIFIED_MARKERS = (
    "grant_verified_commercial",
    "commercial_verified_for_grant",
)

_SAMPLE_DRIVER_PHONES = {
    "".join(ch for ch in str(item.get("phone") or "") if ch.isdigit())
    for item in SAMPLE_DRIVERS
}
_SAMPLE_DRIVER_NAMES = {str(item.get("name") or "").strip().lower() for item in SAMPLE_DRIVERS}
_SAMPLE_PROVIDER_PHONES = {
    "".join(ch for ch in str(item.get("phone") or "") if ch.isdigit())
    for item in SAMPLE_PROVIDERS
}
_SAMPLE_PROVIDER_NAMES = {str(item.get("name") or "").strip().lower() for item in SAMPLE_PROVIDERS}

_PRODUCTION_DEMO_PROVIDER_NAMES = {
    "lincoln medical center",
    "queens dialysis facility",
    "manhattan health hub",
    "brooklyn community clinic",
    "bronx care network",
    "staten island rehab center",
    "harlem wellness center",
    "jamaica nemt hub",
    "flushing medical plaza",
    "yonkers senior care",
}


def _env_value(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _is_fake_555_phone(phone_digits: str) -> bool:
    """NANP 555 exchange numbers are reserved/fictional and used by Amicor seeders."""
    digits = str(phone_digits or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) < 10:
        return False
    return digits[-7:-4] == "555"


def _looks_like_production_demo_ride(ride: Any) -> bool:
    """Detect seed_production_demo_data rows (notes are often empty; markers live in phones/addresses)."""
    phone = _digits(getattr(ride, "passenger_phone", ""))
    pickup = str(getattr(ride, "pickup_address", "") or "").lower()
    dropoff = str(getattr(ride, "dropoff_address", "") or "").lower()
    if _is_fake_555_phone(phone):
        return True
    if phone.startswith("646555") or phone.startswith("917555"):
        return True
    if "main st, new york, ny" in pickup and "health ave" in dropoff:
        return True
    if "new york, ny" in pickup and "brooklyn, ny" in dropoff and "health ave" in dropoff:
        return True
    return False


def _has_commercial_verification_marker(*parts: Any) -> bool:
    blob = " ".join(str(part or "") for part in parts).lower()
    return any(marker in blob for marker in _COMMERCIAL_VERIFIED_MARKERS)


def classify_ride_integrity(ride: Any) -> str:
    """Classify ride evidence for grant use.

    Production demo seed creates hundreds of synthetic NYC/555 rides without notes
    markers. Those must never appear as VERIFIED grant evidence. Unproven platform
    rows default to PENDING VERIFICATION rather than commercial verification.
    """
    if not ride:
        return INTEGRITY_PENDING
    passenger = str(getattr(ride, "passenger_name", "") or "").strip().lower()
    notes = str(getattr(ride, "notes", "") or "").lower()
    if (
        is_operational_excluded_ride(ride)
        or _is_ai_proof_ride(ride)
        or _is_test_ride_row(ride)
        or passenger in DEMO_SEED_PASSENGER_NAMES
        or "phase 43" in notes
        or "seed" in notes
        or "demo" in notes
        or _looks_like_production_demo_ride(ride)
    ):
        return INTEGRITY_DEMO
    if _has_commercial_verification_marker(notes, getattr(ride, "priority_tag", None)):
        return INTEGRITY_VERIFIED
    return INTEGRITY_PENDING


def classify_driver_integrity(driver: Any) -> str:
    if not driver:
        return INTEGRITY_PENDING
    name = str(getattr(driver, "name", "") or "").strip().lower()
    phone = _digits(getattr(driver, "phone", ""))
    plate = str(getattr(driver, "vehicle_plate", "") or "").strip().upper()
    if (
        name in _SAMPLE_DRIVER_NAMES
        or phone in _SAMPLE_DRIVER_PHONES
        or name.startswith("test driver")
        or plate.startswith("NYC-")
        or phone.startswith("917555")
        or _is_fake_555_phone(phone)
    ):
        return INTEGRITY_DEMO
    if _has_commercial_verification_marker(name, getattr(driver, "auth_state", None)):
        return INTEGRITY_VERIFIED
    return INTEGRITY_PENDING


def classify_provider_integrity(provider: Any) -> str:
    if not provider:
        return INTEGRITY_PENDING
    name = str(getattr(provider, "name", "") or "").strip().lower()
    phone = _digits(getattr(provider, "phone", ""))
    address = str(getattr(provider, "address", "") or "").lower()
    if (
        name in _SAMPLE_PROVIDER_NAMES
        or name in _PRODUCTION_DEMO_PROVIDER_NAMES
        or phone in _SAMPLE_PROVIDER_PHONES
        or "test clinic" in name
        or "demo" in name
        or phone.startswith("612555")
        or phone.startswith("212555")
        or _is_fake_555_phone(phone)
        or "care blvd, new york, ny" in address
    ):
        return INTEGRITY_DEMO
    if _has_commercial_verification_marker(name, address):
        return INTEGRITY_VERIFIED
    return INTEGRITY_PENDING


def classify_application_integrity(application: Any) -> str:
    if not application:
        return INTEGRITY_PENDING
    email = str(getattr(application, "applicant_email", "") or "").strip().lower()
    name = str(getattr(application, "applicant_name", "") or "").strip().lower()
    notes = str(getattr(application, "review_notes", "") or "").lower()
    phone = _digits(getattr(application, "applicant_phone", ""))
    if (
        email.endswith("@pilot.example")
        or email.endswith("@example.com")
        or email.endswith("@example.org")
        or "phase 43" in notes
        or "seed" in notes
        or "demo" in name
        or "test" in name
        or _is_fake_555_phone(phone)
    ):
        return INTEGRITY_DEMO
    if _has_commercial_verification_marker(notes, email):
        return INTEGRITY_VERIFIED
    return INTEGRITY_PENDING


def classify_recurring_integrity(template: Any) -> str:
    if not template:
        return INTEGRITY_PENDING
    if isinstance(template, dict):
        notes = str(template.get("notes") or "").lower()
        rider = str(template.get("rider_name") or template.get("passenger_name") or "").lower()
    else:
        notes = str(getattr(template, "notes", "") or "").lower()
        rider = str(
            getattr(template, "rider_name", None)
            or getattr(template, "passenger_name", None)
            or ""
        ).lower()
    if "phase 43" in notes or "seed" in notes or "demo" in notes or "test" in rider:
        return INTEGRITY_DEMO
    return INTEGRITY_PENDING


def build_federal_registration() -> dict[str, Any]:
    uei = _env_value("AMICOR_ENTITY_UEI", "AMICOR_SAM_UEI")
    cage = _env_value("AMICOR_ENTITY_CAGE", "AMICOR_SAM_CAGE")
    return {
        "sam_gov_registration": "ACTIVE",
        "entity": "AMICOR HEALTH ISF LLC",
        "registration_purpose": "Federal Assistance Awards",
        "status": "Active / Verified",
        "sam_activation_evidence": "Available",
        "uei_configured": bool(uei),
        "uei_display": uei if uei else "Pending configuration",
        "cage_configured": bool(cage),
        "cage_display": cage if cage else "Verify / Pending Data",
        "sensitive_fields_excluded": True,
        "privacy_note": (
            "Private banking, tax, personal phone, personal email, and other sensitive "
            "registration details are intentionally excluded from this workspace view."
        ),
    }


def build_master_pipeline() -> list[dict[str, Any]]:
    return [
        {
            "grant_name": "Launch Minnesota Innovation Grant",
            "funding_agency": "Minnesota DEED",
            "funding_type": "State innovation / commercialization support",
            "maximum_award": "Up to $35,000 (subject to the active solicitation)",
            "eligibility": "Verify against the active Launch Minnesota solicitation",
            "application_open_date": "Verify next open round",
            "deadline": "Not claimed open — verify next open round",
            "current_status": "WATCHLIST / VERIFY NEXT OPEN ROUND",
            "priority": "HIGH",
            "required_documents": [
                "Master grant narrative",
                "Master proposed budget",
                "Entity / SAM evidence",
                "Platform / commercialization evidence",
            ],
            "next_action": "Confirm the next open Launch Minnesota round and eligible-cost rules",
            "submission_date": "",
            "decision_result": "",
            "notes": (
                "Tracked opportunity only. Do not treat as currently open. "
                "Target request up to $35,000 subject to the active solicitation."
            ),
            "target_request_usd": 35000,
        }
    ]


FOUNDER_COMPANY_BIO = (
    "Amicor Health ISF LLC is a Minnesota-based healthcare technology startup founded to "
    "improve the coordination and management of non-emergency medical transportation.\n\n"
    "The company is developing an AI-enabled transportation operations platform designed to "
    "help healthcare providers, transportation operations teams, and drivers coordinate "
    "healthcare-related transportation through a centralized digital environment.\n\n"
    "Amicor's platform is being developed to support provider transportation requests, "
    "scheduling, dispatch, driver workflows, operational visibility, recurring transportation "
    "needs, onboarding, reporting, and administrative processes associated with healthcare "
    "transportation.\n\n"
    "The company's initial commercialization strategy focuses on Minnesota, where Amicor "
    "intends to develop provider relationships, establish a qualified transportation network, "
    "conduct market validation, and progress toward initial operating partnerships and revenue.\n\n"
    "Amicor Health ISF LLC is an early-stage company. Its current priorities include completing "
    "operational readiness, recruiting qualified drivers, developing provider partnerships, "
    "validating the platform with real-world users, and securing non-dilutive capital to "
    "support commercialization."
)


def build_master_narrative() -> dict[str, str]:
    return {
        "founder_company_bio": FOUNDER_COMPANY_BIO,
        "company_overview": (
            "Amicor Health ISF LLC is a Minnesota-based healthcare technology company "
            "developing an AI-enabled non-emergency medical transportation coordination "
            "and operations platform."
        ),
        "problem": (
            "Healthcare providers, transportation operators, drivers, and administrative "
            "teams often rely on fragmented scheduling, communication, and operational "
            "tools when coordinating non-emergency medical transportation."
        ),
        "amicor_solution": (
            "Amicor is building a coordinated digital environment intended to connect "
            "healthcare providers, transportation operations, drivers, and administrative "
            "teams for non-emergency medical transportation coordination and operations."
        ),
        "innovation": (
            "The platform combines operational workflows, dispatch coordination, driver "
            "and provider readiness tooling, and AI-assisted operational support into one "
            "Minnesota-based healthcare technology product environment."
        ),
        "target_market": (
            "Healthcare providers, transportation operations teams, independent drivers, "
            "and administrative users involved in non-emergency medical transportation "
            "coordination in Minnesota and similar service markets."
        ),
        "current_stage": (
            "Product development, platform readiness, and commercialization preparation. "
            "Grant-facing metrics distinguish verified live platform records from "
            "demo/test/seeded data."
        ),
        "minnesota_impact": (
            "As a Minnesota-based company, Amicor is focused on improving coordination "
            "tools for healthcare-related transportation operations and supporting "
            "provider, driver, and administrative readiness in the state."
        ),
        "use_of_funds": (
            "Proposed funds would support platform development/testing/commercialization, "
            "security and technical infrastructure, driver and provider onboarding systems, "
            "cloud/software services, launch equipment/supplies, market validation, and "
            "professional/technical assistance, subject to each grant's eligible-cost rules."
        ),
        "commercialization_milestones": (
            "1) Stabilize core coordination workflows. "
            "2) Complete grant-ready evidence packaging with verified-only metrics. "
            "3) Advance provider and driver readiness for pilot implementation. "
            "4) Prepare solicitation-specific application packages. "
            "5) Validate market outreach and commercialization readiness."
        ),
        "long_term_vision": (
            "Build a durable Minnesota healthcare technology platform that helps "
            "providers, transportation operations, drivers, and administrative teams "
            "coordinate non-emergency medical transportation more effectively over time."
        ),
    }


def build_master_budget() -> dict[str, Any]:
    line_items = [
        {"id": "platform_dev", "label": "Platform development/testing/commercialization", "amount_usd": 10000},
        {"id": "security_infra", "label": "Security/compliance/technical infrastructure", "amount_usd": 6000},
        {"id": "driver_onboarding", "label": "Driver recruitment/onboarding systems", "amount_usd": 4500},
        {"id": "provider_pilot", "label": "Provider onboarding/pilot implementation", "amount_usd": 4500},
        {"id": "cloud_services", "label": "Cloud/software/technical services", "amount_usd": 3500},
        {"id": "launch_equipment", "label": "Business launch equipment/supplies", "amount_usd": 3000},
        {"id": "market_validation", "label": "Market validation/provider outreach", "amount_usd": 2000},
        {"id": "professional_assist", "label": "Professional/technical assistance", "amount_usd": 1500},
    ]
    total = sum(int(item["amount_usd"]) for item in line_items)
    return {
        "label": "MASTER PROPOSED BUDGET — subject to each grant's eligible-cost rules.",
        "currency": "USD",
        "editable": True,
        "financial_classification": FINANCIAL_GRANT_REQUEST,
        "not_operating_revenue": True,
        "line_items": line_items,
        "total_usd": total,
        "target_total_usd": 35000,
        "disclaimer": (
            "GRANT REQUEST only. Proposed grant funding and uses of funds. "
            "This amount is never counted as customer/operating revenue."
        ),
    }


def _scenario_assumptions() -> dict[str, dict[str, float]]:
    """Conservative editable placeholders until management approves planning assumptions."""
    return {
        "conservative": {
            "active_providers": 1,
            "rides_per_provider_per_day": 1.0,
            "operating_days_per_month": 18,
            "avg_net_revenue_per_ride": 22.0,
            "driver_cost_per_ride": 16.0,
            "monthly_tech_cloud": 350,
            "monthly_insurance": 250,
            "monthly_marketing": 150,
            "monthly_compliance_legal": 150,
            "monthly_admin_ops": 400,
            "monthly_other_opex": 100,
        },
        "base_case": {
            "active_providers": 2,
            "rides_per_provider_per_day": 1.5,
            "operating_days_per_month": 20,
            "avg_net_revenue_per_ride": 25.0,
            "driver_cost_per_ride": 18.0,
            "monthly_tech_cloud": 450,
            "monthly_insurance": 300,
            "monthly_marketing": 250,
            "monthly_compliance_legal": 200,
            "monthly_admin_ops": 500,
            "monthly_other_opex": 150,
        },
        "growth_case": {
            "active_providers": 3,
            "rides_per_provider_per_day": 2.0,
            "operating_days_per_month": 22,
            "avg_net_revenue_per_ride": 28.0,
            "driver_cost_per_ride": 19.0,
            "monthly_tech_cloud": 550,
            "monthly_insurance": 350,
            "monthly_marketing": 350,
            "monthly_compliance_legal": 250,
            "monthly_admin_ops": 650,
            "monthly_other_opex": 200,
        },
    }


def calculate_projection_from_assumptions(assumptions: dict[str, Any]) -> dict[str, Any]:
    providers = float(assumptions.get("active_providers") or 0)
    rides_per_day = float(assumptions.get("rides_per_provider_per_day") or 0)
    days = float(assumptions.get("operating_days_per_month") or 0)
    revenue_per_ride = float(assumptions.get("avg_net_revenue_per_ride") or 0)
    driver_cost = float(assumptions.get("driver_cost_per_ride") or 0)
    fixed_opex = sum(
        float(assumptions.get(key) or 0)
        for key in (
            "monthly_tech_cloud",
            "monthly_insurance",
            "monthly_marketing",
            "monthly_compliance_legal",
            "monthly_admin_ops",
            "monthly_other_opex",
        )
    )
    monthly_rides = providers * rides_per_day * days
    monthly_gross_revenue = monthly_rides * revenue_per_ride
    monthly_driver_costs = monthly_rides * driver_cost
    monthly_operating_expenses = monthly_driver_costs + fixed_opex
    monthly_net = monthly_gross_revenue - monthly_operating_expenses
    return {
        "financial_classification": FINANCIAL_PROJECTED,
        "projected_monthly_rides": round(monthly_rides, 2),
        "projected_monthly_gross_revenue": round(monthly_gross_revenue, 2),
        "projected_monthly_transportation_driver_costs": round(monthly_driver_costs, 2),
        "projected_monthly_operating_expenses": round(monthly_operating_expenses, 2),
        "projected_monthly_net_operating_result": round(monthly_net, 2),
        "projected_12_month_rides": round(monthly_rides * 12, 2),
        "projected_12_month_gross_revenue": round(monthly_gross_revenue * 12, 2),
        "projected_12_month_transportation_driver_costs": round(monthly_driver_costs * 12, 2),
        "projected_12_month_operating_expenses": round(monthly_operating_expenses * 12, 2),
        "projected_12_month_net_operating_result": round(monthly_net * 12, 2),
    }


def assumptions_are_complete(assumptions: dict[str, Any] | None) -> bool:
    if not assumptions or not isinstance(assumptions, dict):
        return False
    required = (
        "active_providers",
        "rides_per_provider_per_day",
        "operating_days_per_month",
        "avg_net_revenue_per_ride",
        "driver_cost_per_ride",
        "monthly_tech_cloud",
        "monthly_insurance",
        "monthly_marketing",
        "monthly_compliance_legal",
        "monthly_admin_ops",
        "monthly_other_opex",
    )
    for key in required:
        if key not in assumptions:
            return False
        try:
            value = float(assumptions[key])
        except (TypeError, ValueError):
            return False
        if value < 0 or value != value:  # NaN check
            return False
    return True


def build_financial_projections() -> dict[str, Any]:
    scenarios: dict[str, Any] = {}
    for key, assumptions in _scenario_assumptions().items():
        scenarios[key] = {
            "label": {
                "conservative": "CONSERVATIVE",
                "base_case": "BASE CASE",
                "growth_case": "GROWTH CASE",
            }[key],
            "assumptions": assumptions,
            "results": calculate_projection_from_assumptions(assumptions),
            "assumptions_complete": assumptions_are_complete(assumptions),
            "placeholder_until_management_approval": True,
        }
    return {
        "banner": "PROJECTION — NOT HISTORICAL PERFORMANCE",
        "financial_classification": FINANCIAL_PROJECTED,
        "classifications": {
            "ACTUAL": "Supported by real accounting/operational records.",
            "PROJECTED": "Planning assumptions and forecasts only.",
            "GRANT REQUEST": "Proposed grant funding and proposed uses of funds.",
        },
        "policy": (
            "Projected amounts are planning assumptions only and are never represented as "
            "actual company revenue. Grant request amounts are kept completely separate from "
            "operating revenue. Demo/test/seeded rides are never used as historical financial evidence."
        ),
        "uses_demo_seed_rides_as_history": False,
        "actual_operating_revenue_usd": None,
        "actual_operating_revenue_status": "No verified actual operating revenue loaded in Grant Command Center.",
        "grant_request_separate": True,
        "default_scenario": "conservative",
        "editable": True,
        "scenarios": scenarios,
        "input_fields": [
            {"id": "active_providers", "label": "Number of active providers"},
            {"id": "rides_per_provider_per_day", "label": "Estimated rides per provider per day"},
            {"id": "operating_days_per_month", "label": "Operating days per month"},
            {"id": "avg_net_revenue_per_ride", "label": "Estimated average net revenue per completed ride"},
            {"id": "driver_cost_per_ride", "label": "Estimated transportation/driver cost per ride"},
            {"id": "monthly_tech_cloud", "label": "Monthly technology/cloud costs"},
            {"id": "monthly_insurance", "label": "Monthly insurance costs"},
            {"id": "monthly_marketing", "label": "Monthly marketing/provider outreach"},
            {"id": "monthly_compliance_legal", "label": "Monthly compliance/accounting/legal costs"},
            {"id": "monthly_admin_ops", "label": "Monthly administrative/operating costs"},
            {"id": "monthly_other_opex", "label": "Other documented operating expenses"},
        ],
    }


def build_readiness_checklist(
    *,
    federal: dict[str, Any],
    verified_providers: int,
    verified_drivers: int,
    verified_applications: int,
    financial_projections_status: str = "IN PROGRESS",
) -> list[dict[str, Any]]:
    def item(item_id: str, label: str, status: str, note: str = "") -> dict[str, Any]:
        return {"id": item_id, "label": label, "status": status, "note": note}

    uei_status = "READY" if federal.get("uei_configured") else "IN PROGRESS"
    cage_status = "READY" if federal.get("cage_configured") else "IN PROGRESS"
    provider_status = "READY" if verified_providers > 0 else "MISSING"
    driver_status = "READY" if (verified_drivers > 0 or verified_applications > 0) else "MISSING"
    projections_status = financial_projections_status if financial_projections_status in {
        "READY", "IN PROGRESS", "MISSING", "NOT REQUIRED"
    } else "IN PROGRESS"

    return [
        item("sam_active", "SAM.gov active", "READY", "Entity registration reported Active / Verified"),
        item("uei_available", "UEI available", uei_status, "Loaded from server entity configuration when present"),
        item("cage_verified", "CAGE verified if applicable", cage_status, "Shown only from configured data"),
        item("mn_entity_docs", "Minnesota entity documentation", "IN PROGRESS"),
        item("w9", "W-9", "MISSING", "Not displayed in this workspace for privacy"),
        item("business_bank", "Business bank account", "MISSING", "Sensitive banking details are not stored here"),
        item("master_narrative", "Master grant narrative", "READY"),
        item("master_budget", "Master grant budget", "READY", "Classified as GRANT REQUEST, not operating revenue"),
        item("founder_bio", "Founder/company bio", "READY", "Approved reusable company bio included in narrative"),
        item("platform_screenshots", "Platform screenshots", "IN PROGRESS"),
        item("provider_pilot", "Provider pilot evidence", provider_status, "Verified providers only"),
        item("driver_readiness", "Driver readiness evidence", driver_status, "Verified drivers/applications only"),
        item("letters_of_support", "Letters of support", "MISSING"),
        item(
            "financial_projections",
            "Financial projections",
            projections_status,
            "READY only after complete assumptions are saved; otherwise IN PROGRESS",
        ),
        item("grant_attachments", "Grant-specific attachments", "MISSING"),
    ]


def build_evidence_pack(
    *,
    federal: dict[str, Any],
    screenshot_inventory: list[dict[str, str]],
    verified_rides: int,
    demo_rides: int,
    verified_providers: int,
    demo_providers: int,
    verified_drivers: int,
    demo_drivers: int,
    verified_applications: int,
    demo_applications: int,
    verified_recurring: int,
    demo_recurring: int,
) -> dict[str, Any]:
    def status_for(ready: bool, pending: bool = False) -> str:
        if ready:
            return "READY"
        if pending:
            return "IN PROGRESS"
        return "NEEDS_EVIDENCE"

    return {
        "categories": [
            {
                "id": "corporate_entity",
                "label": "Corporate/Entity Evidence",
                "status": "READY",
                "items": [
                    "Legal entity name: AMICOR HEALTH ISF LLC",
                    "Minnesota-based healthcare technology company positioning",
                ],
            },
            {
                "id": "federal_registration",
                "label": "Federal Registration Evidence",
                "status": "READY" if federal.get("sam_gov_registration") == "ACTIVE" else "IN PROGRESS",
                "items": [
                    "SAM.gov registration: ACTIVE",
                    f"UEI: {federal.get('uei_display')}",
                    f"CAGE: {federal.get('cage_display')}",
                    "Sensitive banking/tax/personal contacts excluded",
                ],
            },
            {
                "id": "platform_product",
                "label": "Platform/Product Evidence",
                "status": status_for(bool(screenshot_inventory), pending=True),
                "items": [item.get("label") or item.get("id") or "Capture" for item in screenshot_inventory]
                or ["Platform screenshot inventory pending"],
            },
            {
                "id": "provider_readiness",
                "label": "Provider Readiness",
                "status": status_for(verified_providers > 0),
                "items": [
                    f"Verified providers: {verified_providers}",
                    f"Demo/test/seeded providers (excluded from verified evidence): {demo_providers}",
                ],
            },
            {
                "id": "driver_readiness",
                "label": "Driver Readiness",
                "status": status_for(verified_drivers > 0 or verified_applications > 0),
                "items": [
                    f"Verified drivers: {verified_drivers}",
                    f"Verified driver applications: {verified_applications}",
                    f"Demo/test/seeded drivers (excluded): {demo_drivers}",
                    f"Demo/test/seeded applications (excluded): {demo_applications}",
                ],
            },
            {
                "id": "operational_readiness",
                "label": "Operational Readiness",
                "status": status_for(verified_rides > 0, pending=demo_rides > 0),
                "items": [
                    f"Verified live rides: {verified_rides}",
                    f"Demo/test/seeded rides (excluded from verified grant evidence): {demo_rides}",
                    f"Verified recurring templates: {verified_recurring}",
                    f"Demo/test/seeded recurring templates (excluded): {demo_recurring}",
                ],
            },
            {
                "id": "commercialization",
                "label": "Commercialization Evidence",
                "status": "IN PROGRESS",
                "items": [
                    "Master grant narrative prepared",
                    "Master proposed $35,000 budget prepared",
                    "Launch Minnesota Innovation Grant on watchlist",
                ],
            },
            {
                "id": "application_documents",
                "label": "Application Documents",
                "status": "IN PROGRESS",
                "items": [
                    "Master narrative",
                    "Master budget",
                    "Federal registration readiness summary",
                    "Solicitation-specific attachments still required per opportunity",
                ],
            },
        ]
    }


def build_grant_metrics(
    *,
    rides: list[Any],
    drivers: list[Any],
    providers: list[Any],
    applications: list[Any],
    recurring: list[Any],
    delayed_rides: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ride_classes = [classify_ride_integrity(ride) for ride in rides]
    driver_classes = [classify_driver_integrity(driver) for driver in drivers]
    provider_classes = [classify_provider_integrity(provider) for provider in providers]
    app_classes = [classify_application_integrity(app) for app in applications]
    recurring_classes = [classify_recurring_integrity(item) for item in recurring]

    verified_rides = sum(1 for c in ride_classes if c == INTEGRITY_VERIFIED)
    demo_rides = sum(1 for c in ride_classes if c == INTEGRITY_DEMO)
    pending_rides = sum(1 for c in ride_classes if c == INTEGRITY_PENDING)
    verified_drivers = sum(1 for c in driver_classes if c == INTEGRITY_VERIFIED)
    demo_drivers = sum(1 for c in driver_classes if c == INTEGRITY_DEMO)
    pending_drivers = sum(1 for c in driver_classes if c == INTEGRITY_PENDING)
    verified_providers = sum(1 for c in provider_classes if c == INTEGRITY_VERIFIED)
    demo_providers = sum(1 for c in provider_classes if c == INTEGRITY_DEMO)
    pending_providers = sum(1 for c in provider_classes if c == INTEGRITY_PENDING)
    verified_apps = sum(1 for c in app_classes if c == INTEGRITY_VERIFIED)
    demo_apps = sum(1 for c in app_classes if c == INTEGRITY_DEMO)
    pending_apps = sum(1 for c in app_classes if c == INTEGRITY_PENDING)
    verified_recurring = sum(1 for c in recurring_classes if c == INTEGRITY_VERIFIED)
    demo_recurring = sum(1 for c in recurring_classes if c == INTEGRITY_DEMO)
    pending_recurring = sum(1 for c in recurring_classes if c == INTEGRITY_PENDING)

    verified_active_rides = sum(
        1
        for ride, classification in zip(rides, ride_classes)
        if classification == INTEGRITY_VERIFIED
        and str(getattr(ride, "status", "")).lower() in {"accepted", "in_transit"}
    )
    verified_approved_apps = sum(
        1
        for app, classification in zip(applications, app_classes)
        if classification == INTEGRITY_VERIFIED
        and str(getattr(app, "onboarding_status", "")).lower() in {"approved", "active"}
    )
    verified_pending_apps = sum(
        1
        for app, classification in zip(applications, app_classes)
        if classification == INTEGRITY_VERIFIED
        and str(getattr(app, "onboarding_status", "")).lower() in {"applied", "pending_review"}
    )

    metrics = {
        "grant_metrics_default": INTEGRITY_VERIFIED,
        "total_rides_all_sources": len(rides),
        "total_rides_verified": verified_rides,
        "total_rides_demo_test_seeded": demo_rides,
        "total_rides_pending_verification": pending_rides,
        "active_rides_verified": verified_active_rides,
        "delayed_rides_reported": int(delayed_rides or 0),
        "delayed_rides_integrity": INTEGRITY_PENDING,
        "driver_applications_total_verified": verified_apps,
        "driver_applications_total_demo_test_seeded": demo_apps,
        "driver_applications_total_pending_verification": pending_apps,
        "driver_applications_pending_verified": verified_pending_apps,
        "driver_applications_approved_verified": verified_approved_apps,
        "drivers_verified": verified_drivers,
        "drivers_demo_test_seeded": demo_drivers,
        "drivers_pending_verification": pending_drivers,
        "providers_verified": verified_providers,
        "providers_demo_test_seeded": demo_providers,
        "providers_pending_verification": pending_providers,
        "recurring_templates_verified": verified_recurring,
        "recurring_templates_demo_test_seeded": demo_recurring,
        "recurring_templates_pending_verification": pending_recurring,
        # Backward-compatible keys intentionally map to verified-only grant evidence.
        "total_rides": verified_rides,
        "active_rides": verified_active_rides,
        "delayed_rides": int(delayed_rides or 0),
        "driver_applications_total": verified_apps,
        "driver_applications_pending": verified_pending_apps,
        "driver_applications_approved": verified_approved_apps,
        "recurring_templates": verified_recurring,
        "target_program": "Grant Command Center / Master Grant Readiness",
        "target_date": None,
        "legacy_june15_proof_pack": "replaced",
    }

    data_integrity = {
        "legend": [INTEGRITY_VERIFIED, INTEGRITY_DEMO, INTEGRITY_PENDING],
        "policy": (
            "Grant-facing metrics default to VERIFIED LIVE DATA only. "
            "Demo/test/seeded rides (including production demo seed patterns such as 555 phones "
            "and synthetic NYC seed addresses) are labeled DEMO/TEST/SEEDED and excluded. "
            "Platform rows that cannot be proven as completed commercial activity remain "
            "PENDING VERIFICATION and are also excluded from verified grant evidence."
        ),
        "counts": {
            "rides": {
                "verified": verified_rides,
                "demo_test_seeded": demo_rides,
                "pending_verification": pending_rides,
            },
            "drivers": {
                "verified": verified_drivers,
                "demo_test_seeded": demo_drivers,
                "pending_verification": pending_drivers,
            },
            "providers": {
                "verified": verified_providers,
                "demo_test_seeded": demo_providers,
                "pending_verification": pending_providers,
            },
            "driver_applications": {
                "verified": verified_apps,
                "demo_test_seeded": demo_apps,
                "pending_verification": pending_apps,
            },
            "recurring_templates": {
                "verified": verified_recurring,
                "demo_test_seeded": demo_recurring,
                "pending_verification": pending_recurring,
            },
        },
        "notes": [
            "Large historical ride counts from production demo seeding are classified DEMO/TEST/SEEDED, not verified commercial activity.",
            "Financial projections never use demo/test/seeded rides as historical evidence.",
            "Delayed-ride dashboard values remain pending verification for grant use.",
        ],
    }
    return metrics, data_integrity


def build_command_center_payload(
    *,
    rides: list[Any],
    drivers: list[Any],
    providers: list[Any],
    applications: list[Any],
    recurring: list[Any],
    delayed_rides: int,
    screenshot_inventory: list[dict[str, str]],
    transportation_mvp_status: str,
    onboarding_mvp_status: str,
    recurring_mvp_status: str,
    dashboard_mvp_status: str,
) -> dict[str, Any]:
    federal = build_federal_registration()
    metrics, data_integrity = build_grant_metrics(
        rides=rides,
        drivers=drivers,
        providers=providers,
        applications=applications,
        recurring=recurring,
        delayed_rides=delayed_rides,
    )
    financial_projections = build_financial_projections()
    # Module ships with complete placeholder assumptions → IN PROGRESS until locally saved/approved.
    checklist = build_readiness_checklist(
        federal=federal,
        verified_providers=int(metrics["providers_verified"]),
        verified_drivers=int(metrics["drivers_verified"]),
        verified_applications=int(metrics["driver_applications_total_verified"]),
        financial_projections_status="IN PROGRESS",
    )
    evidence = build_evidence_pack(
        federal=federal,
        screenshot_inventory=screenshot_inventory,
        verified_rides=int(metrics["total_rides_verified"]),
        demo_rides=int(metrics["total_rides_demo_test_seeded"]),
        verified_providers=int(metrics["providers_verified"]),
        demo_providers=int(metrics["providers_demo_test_seeded"]),
        verified_drivers=int(metrics["drivers_verified"]),
        demo_drivers=int(metrics["drivers_demo_test_seeded"]),
        verified_applications=int(metrics["driver_applications_total_verified"]),
        demo_applications=int(metrics["driver_applications_total_demo_test_seeded"]),
        verified_recurring=int(metrics["recurring_templates_verified"]),
        demo_recurring=int(metrics["recurring_templates_demo_test_seeded"]),
    )
    return {
        "command_center_title": "Grant Command Center",
        "federal_registration": federal,
        "pipeline": build_master_pipeline(),
        "narrative": build_master_narrative(),
        "budget": build_master_budget(),
        "financial_projections": financial_projections,
        "evidence_pack": evidence,
        "readiness_checklist": checklist,
        "data_integrity": data_integrity,
        "metrics": metrics,
        "transportation_mvp_status": transportation_mvp_status,
        "onboarding_mvp_status": onboarding_mvp_status,
        "recurring_mvp_status": recurring_mvp_status,
        "dashboard_mvp_status": dashboard_mvp_status,
    }
