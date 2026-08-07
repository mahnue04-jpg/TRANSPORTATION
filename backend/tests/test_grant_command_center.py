"""Unit tests for Grant Command Center builders and integrity labeling."""
from types import SimpleNamespace

from app.modules.health_isf.grant_command_center import (
    INTEGRITY_DEMO,
    INTEGRITY_VERIFIED,
    build_command_center_payload,
    build_federal_registration,
    build_master_budget,
    classify_driver_integrity,
    classify_provider_integrity,
    classify_ride_integrity,
)


def test_demo_seed_rides_are_excluded_from_verified_metrics():
    rides = [
        SimpleNamespace(
            passenger_name="Patricia Johnson",
            pickup_address="1000 Park Ave",
            dropoff_address="456 Care Ave",
            notes="seed ride",
            status="completed",
        ),
        SimpleNamespace(
            passenger_name="Verified Rider One",
            pickup_address="12 Main St, Minneapolis, MN",
            dropoff_address="88 Clinic Rd, Minneapolis, MN",
            notes="live operational ride",
            status="accepted",
        ),
    ]
    drivers = [
        SimpleNamespace(name="James Smith", phone="917-555-1001", vehicle_plate="NYC-1001"),
        SimpleNamespace(name="Live Driver", phone="612-555-9999", vehicle_plate="MN-7788"),
    ]
    # 612-555-9999 still matches demo phone prefix classifier; use non-555 verified phone
    drivers[1] = SimpleNamespace(name="Live Driver", phone="612-401-7788", vehicle_plate="MN-7788")
    providers = [
        SimpleNamespace(name="Fairview Hospital", phone="612-555-0100"),
        SimpleNamespace(name="Community Care Partners", phone="651-401-2200"),
    ]
    applications = [
        SimpleNamespace(
            applicant_name="Caleb Morgan",
            applicant_email="caleb.morgan@pilot.example",
            review_notes="Phase 43 onboarding seed",
            onboarding_status="approved",
        ),
        SimpleNamespace(
            applicant_name="Alex Rivera",
            applicant_email="alex.rivera@example-live.org",
            review_notes="live applicant",
            onboarding_status="pending_review",
        ),
    ]
    # example-live.org still ends with neither @example.com nor @pilot.example — good
    payload = build_command_center_payload(
        rides=rides,
        drivers=drivers,
        providers=providers,
        applications=applications,
        recurring=[{"rider_name": "Seed Rider", "notes": "Phase 43 recurring transportation seed"}],
        delayed_rides=2,
        screenshot_inventory=[{"id": "grant_command_center", "label": "Grant Command Center", "status": "ready"}],
        transportation_mvp_status="ready",
        onboarding_mvp_status="ready",
        recurring_mvp_status="ready",
        dashboard_mvp_status="ready",
    )

    assert classify_ride_integrity(rides[0]) == INTEGRITY_DEMO
    assert classify_ride_integrity(rides[1]) == INTEGRITY_VERIFIED
    assert classify_driver_integrity(drivers[0]) == INTEGRITY_DEMO
    assert classify_driver_integrity(drivers[1]) == INTEGRITY_VERIFIED
    assert classify_provider_integrity(providers[0]) == INTEGRITY_DEMO
    assert classify_provider_integrity(providers[1]) == INTEGRITY_VERIFIED

    metrics = payload["metrics"]
    assert metrics["total_rides"] == 1
    assert metrics["total_rides_verified"] == 1
    assert metrics["total_rides_demo_test_seeded"] == 1
    assert metrics["total_rides_all_sources"] == 2
    assert metrics["drivers_verified"] == 1
    assert metrics["providers_verified"] == 1
    assert metrics["driver_applications_total"] == 1
    assert metrics["legacy_june15_proof_pack"] == "replaced"
    assert metrics["target_date"] is None

    budget = payload["budget"]
    assert budget["total_usd"] == 35000
    assert "subject to each grant" in budget["label"].lower()

    pipeline = payload["pipeline"]
    assert pipeline[0]["grant_name"] == "Launch Minnesota Innovation Grant"
    assert "WATCHLIST" in pipeline[0]["current_status"]
    assert "verify next open round" in pipeline[0]["deadline"].lower()

    federal = payload["federal_registration"]
    assert federal["sam_gov_registration"] == "ACTIVE"
    assert federal["entity"] == "AMICOR HEALTH ISF LLC"
    assert federal["sensitive_fields_excluded"] is True


def test_federal_registration_reads_uei_cage_from_env(monkeypatch):
    monkeypatch.setenv("AMICOR_ENTITY_UEI", "TESTUEI123456")
    monkeypatch.setenv("AMICOR_ENTITY_CAGE", "1ABC2")
    federal = build_federal_registration()
    assert federal["uei_configured"] is True
    assert federal["uei_display"] == "TESTUEI123456"
    assert federal["cage_configured"] is True
    assert federal["cage_display"] == "1ABC2"


def test_master_budget_totals_thirty_five_thousand():
    budget = build_master_budget()
    assert budget["total_usd"] == 35000
    assert budget["target_total_usd"] == 35000
    assert len(budget["line_items"]) == 8
