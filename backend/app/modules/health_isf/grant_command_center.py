"""
Grant Command Center builders for the existing Health ISF Grants page.

Keeps grant-facing metrics conservative: known demo/seed/test rows are labeled
and excluded from verified grant evidence. Sensitive federal registration
identifiers are only surfaced when provided via server environment configuration.
"""
from __future__ import annotations

import os
from typing import Any, Optional

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


def _env_value(*names: str) -> str:
    for name in names:
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
    return ""


def _digits(value: Any) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def classify_ride_integrity(ride: Any) -> str:
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
    ):
        return INTEGRITY_DEMO
    return INTEGRITY_VERIFIED


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
    ):
        return INTEGRITY_DEMO
    return INTEGRITY_VERIFIED


def classify_provider_integrity(provider: Any) -> str:
    if not provider:
        return INTEGRITY_PENDING
    name = str(getattr(provider, "name", "") or "").strip().lower()
    phone = _digits(getattr(provider, "phone", ""))
    if (
        name in _SAMPLE_PROVIDER_NAMES
        or phone in _SAMPLE_PROVIDER_PHONES
        or "test clinic" in name
        or "demo" in name
        or phone.startswith("612555")
        or phone.startswith("212555")
    ):
        return INTEGRITY_DEMO
    return INTEGRITY_VERIFIED


def classify_application_integrity(application: Any) -> str:
    if not application:
        return INTEGRITY_PENDING
    email = str(getattr(application, "applicant_email", "") or "").strip().lower()
    name = str(getattr(application, "applicant_name", "") or "").strip().lower()
    notes = str(getattr(application, "review_notes", "") or "").lower()
    if (
        email.endswith("@pilot.example")
        or email.endswith("@example.com")
        or email.endswith("@example.org")
        or "phase 43" in notes
        or "seed" in notes
        or "demo" in name
        or "test" in name
    ):
        return INTEGRITY_DEMO
    return INTEGRITY_VERIFIED


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


def build_master_narrative() -> dict[str, str]:
    return {
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
        "line_items": line_items,
        "total_usd": total,
        "target_total_usd": 35000,
    }


def build_readiness_checklist(
    *,
    federal: dict[str, Any],
    verified_providers: int,
    verified_drivers: int,
    verified_applications: int,
) -> list[dict[str, Any]]:
    def item(item_id: str, label: str, status: str, note: str = "") -> dict[str, Any]:
        return {"id": item_id, "label": label, "status": status, "note": note}

    uei_status = "READY" if federal.get("uei_configured") else "IN PROGRESS"
    cage_status = "READY" if federal.get("cage_configured") else "IN PROGRESS"
    provider_status = "READY" if verified_providers > 0 else "MISSING"
    driver_status = "READY" if (verified_drivers > 0 or verified_applications > 0) else "MISSING"

    return [
        item("sam_active", "SAM.gov active", "READY", "Entity registration reported Active / Verified"),
        item("uei_available", "UEI available", uei_status, "Loaded from server entity configuration when present"),
        item("cage_verified", "CAGE verified if applicable", cage_status, "Shown only from configured data"),
        item("mn_entity_docs", "Minnesota entity documentation", "IN PROGRESS"),
        item("w9", "W-9", "MISSING", "Not displayed in this workspace for privacy"),
        item("business_bank", "Business bank account", "MISSING", "Sensitive banking details are not stored here"),
        item("master_narrative", "Master grant narrative", "READY"),
        item("master_budget", "Master grant budget", "READY"),
        item("founder_bio", "Founder/company bio", "IN PROGRESS"),
        item("platform_screenshots", "Platform screenshots", "IN PROGRESS"),
        item("provider_pilot", "Provider pilot evidence", provider_status, "Verified providers only"),
        item("driver_readiness", "Driver readiness evidence", driver_status, "Verified drivers/applications only"),
        item("letters_of_support", "Letters of support", "MISSING"),
        item("financial_projections", "Financial projections", "MISSING"),
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
    verified_drivers = sum(1 for c in driver_classes if c == INTEGRITY_VERIFIED)
    demo_drivers = sum(1 for c in driver_classes if c == INTEGRITY_DEMO)
    verified_providers = sum(1 for c in provider_classes if c == INTEGRITY_VERIFIED)
    demo_providers = sum(1 for c in provider_classes if c == INTEGRITY_DEMO)
    verified_apps = sum(1 for c in app_classes if c == INTEGRITY_VERIFIED)
    demo_apps = sum(1 for c in app_classes if c == INTEGRITY_DEMO)
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
        "active_rides_verified": verified_active_rides,
        "delayed_rides_reported": int(delayed_rides or 0),
        "delayed_rides_integrity": INTEGRITY_PENDING,
        "driver_applications_total_verified": verified_apps,
        "driver_applications_total_demo_test_seeded": demo_apps,
        "driver_applications_pending_verified": verified_pending_apps,
        "driver_applications_approved_verified": verified_approved_apps,
        "drivers_verified": verified_drivers,
        "drivers_demo_test_seeded": demo_drivers,
        "providers_verified": verified_providers,
        "providers_demo_test_seeded": demo_providers,
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
            "Demo/test/seeded rides, demonstration providers/drivers, test applications, "
            "and simulated metrics are labeled and excluded from verified grant evidence."
        ),
        "counts": {
            "rides": {"verified": verified_rides, "demo_test_seeded": demo_rides},
            "drivers": {"verified": verified_drivers, "demo_test_seeded": demo_drivers},
            "providers": {"verified": verified_providers, "demo_test_seeded": demo_providers},
            "driver_applications": {"verified": verified_apps, "demo_test_seeded": demo_apps},
            "recurring_templates": {
                "verified": verified_recurring,
                "demo_test_seeded": demo_recurring,
                "pending_verification": pending_recurring,
            },
        },
        "notes": [
            "If a large historical ride count came from demo/seed/test data, it is labeled DEMO/TEST DATA here.",
            "Delayed-ride dashboard values are shown as reported operational signals and remain pending verification for grant use.",
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
    checklist = build_readiness_checklist(
        federal=federal,
        verified_providers=int(metrics["providers_verified"]),
        verified_drivers=int(metrics["drivers_verified"]),
        verified_applications=int(metrics["driver_applications_total_verified"]),
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
        "evidence_pack": evidence,
        "readiness_checklist": checklist,
        "data_integrity": data_integrity,
        "metrics": metrics,
        "transportation_mvp_status": transportation_mvp_status,
        "onboarding_mvp_status": onboarding_mvp_status,
        "recurring_mvp_status": recurring_mvp_status,
        "dashboard_mvp_status": dashboard_mvp_status,
    }
