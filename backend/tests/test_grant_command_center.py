"""Unit tests for Grant Command Center builders and integrity labeling."""
from types import SimpleNamespace

from app.modules.health_isf.grant_command_center import (
    FINANCIAL_GRANT_REQUEST,
    FINANCIAL_PROJECTED,
    INTEGRITY_DEMO,
    INTEGRITY_PENDING,
    INTEGRITY_VERIFIED,
    NIH_SBIR_BUDGET_PLACEHOLDER,
    PENDING_MANAGEMENT_VERIFICATION,
    assumptions_are_complete,
    build_command_center_payload,
    build_federal_registration,
    build_financial_projections,
    build_master_budget,
    build_master_pipeline,
    build_nih_sbir_grant1_package,
    calculate_projection_from_assumptions,
    classify_driver_integrity,
    classify_provider_integrity,
    classify_ride_integrity,
)


def test_demo_seed_and_unproven_rides_are_not_verified_grant_evidence():
    rides = [
        SimpleNamespace(
            passenger_name="Patricia Johnson",
            passenger_phone="646-555-2001",
            pickup_address="1000 Park Ave, New York, NY 10028",
            dropoff_address="456 Care Ave, Queens, NY 11375",
            notes="seed ride",
            status="completed",
        ),
        SimpleNamespace(
            passenger_name="Production Demo Rider",
            passenger_phone="646-555-6123",
            pickup_address="125 Main St, New York, NY 1005",
            dropoff_address="250 Health Ave, Brooklyn, NY 1125",
            notes="",
            status="completed",
        ),
        SimpleNamespace(
            passenger_name="Unproven Platform Rider",
            passenger_phone="612-401-7788",
            pickup_address="12 Main St, Minneapolis, MN",
            dropoff_address="88 Clinic Rd, Minneapolis, MN",
            notes="live operational ride",
            status="accepted",
        ),
        SimpleNamespace(
            passenger_name="Commercial Verified Rider",
            passenger_phone="612-401-9000",
            pickup_address="12 Main St, Minneapolis, MN",
            dropoff_address="88 Clinic Rd, Minneapolis, MN",
            notes="grant_verified_commercial completed trip",
            status="completed",
            priority_tag=None,
        ),
    ]
    drivers = [
        SimpleNamespace(name="James Smith", phone="917-555-1001", vehicle_plate="NYC-1001"),
        SimpleNamespace(name="Live Driver", phone="612-401-7788", vehicle_plate="MN-7788"),
    ]
    providers = [
        SimpleNamespace(name="Fairview Hospital", phone="612-555-0100", address="2450 Riverside Ave"),
        SimpleNamespace(name="Lincoln Medical Center", phone="212-555-3100", address="100 Care Blvd, New York, NY 1000"),
        SimpleNamespace(name="Community Care Partners", phone="651-401-2200", address="Minneapolis, MN"),
    ]
    applications = [
        SimpleNamespace(
            applicant_name="Caleb Morgan",
            applicant_email="caleb.morgan@pilot.example",
            applicant_phone="917-555-0100",
            review_notes="Phase 43 onboarding seed",
            onboarding_status="approved",
        ),
        SimpleNamespace(
            applicant_name="Alex Rivera",
            applicant_email="alex.rivera@communitycare.org",
            applicant_phone="612-401-3344",
            review_notes="live applicant",
            onboarding_status="pending_review",
        ),
    ]
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
    assert classify_ride_integrity(rides[1]) == INTEGRITY_DEMO
    assert classify_ride_integrity(rides[2]) == INTEGRITY_PENDING
    assert classify_ride_integrity(rides[3]) == INTEGRITY_VERIFIED
    assert classify_driver_integrity(drivers[0]) == INTEGRITY_DEMO
    assert classify_driver_integrity(drivers[1]) == INTEGRITY_PENDING
    assert classify_provider_integrity(providers[0]) == INTEGRITY_DEMO
    assert classify_provider_integrity(providers[1]) == INTEGRITY_DEMO
    assert classify_provider_integrity(providers[2]) == INTEGRITY_PENDING

    metrics = payload["metrics"]
    assert metrics["total_rides"] == 1
    assert metrics["total_rides_verified"] == 1
    assert metrics["total_rides_demo_test_seeded"] == 2
    assert metrics["total_rides_pending_verification"] == 1
    assert metrics["total_rides_all_sources"] == 4
    assert metrics["drivers_verified"] == 0
    assert metrics["providers_verified"] == 0
    assert metrics["driver_applications_total"] == 0
    assert metrics["legacy_june15_proof_pack"] == "replaced"
    assert metrics["target_date"] is None

    budget = payload["budget"]
    assert budget["total_usd"] == 35000
    assert budget["financial_classification"] == FINANCIAL_GRANT_REQUEST
    assert budget["not_operating_revenue"] is True

    projections = payload["financial_projections"]
    assert projections["financial_classification"] == FINANCIAL_PROJECTED
    assert "NOT HISTORICAL" in projections["banner"]
    assert projections["uses_demo_seed_rides_as_history"] is False
    assert projections["grant_request_separate"] is True
    assert "conservative" in projections["scenarios"]
    assert "base_case" in projections["scenarios"]
    assert "growth_case" in projections["scenarios"]
    assert "PROJECTED / ASSUMPTION" in projections["management_assumption_guide"]
    assert any("payment processing" in str(field.get("label") or "").lower() for field in projections["input_fields"])
    assert projections["derived_fields"][0]["id"] == "projected_monthly_rides"

    checklist = {item["id"]: item for item in payload["readiness_checklist"]}
    assert checklist["financial_projections"]["status"] == "IN PROGRESS"
    assert checklist["founder_bio"]["status"] == "READY"
    assert "Minnesota-based healthcare technology startup" in payload["narrative"]["founder_company_bio"]


def test_production_demo_phone_patterns_cannot_become_verified():
    ride = SimpleNamespace(
        passenger_name="Any Name",
        passenger_phone="646-555-6001",
        pickup_address="500 Main St, New York, NY 1001",
        dropoff_address="300 Health Ave, Brooklyn, NY 1121",
        notes="grant_verified_commercial",  # must not override demo seed pattern
        status="completed",
    )
    assert classify_ride_integrity(ride) == INTEGRITY_DEMO


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
    assert budget["financial_classification"] == FINANCIAL_GRANT_REQUEST


def test_financial_projection_math_and_classification():
    assumptions = {
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
    }
    assert assumptions_are_complete(assumptions) is True
    results = calculate_projection_from_assumptions(assumptions)
    assert results["financial_classification"] == FINANCIAL_PROJECTED
    assert results["projected_monthly_rides"] == 60.0
    assert results["projected_monthly_gross_revenue"] == 1500.0
    assert results["projected_monthly_transportation_driver_costs"] == 1080.0
    assert results["projected_12_month_gross_revenue"] == 18000.0

    projections = build_financial_projections()
    grant_budget = build_master_budget()
    # Grant request must remain separate from projected operating revenue.
    assert grant_budget["total_usd"] == 35000
    assert grant_budget["financial_classification"] == FINANCIAL_GRANT_REQUEST
    assert projections["scenarios"]["conservative"]["results"]["projected_12_month_gross_revenue"] != 35000
    assert projections["scenarios"]["conservative"]["results"]["financial_classification"] == FINANCIAL_PROJECTED


def test_conservative_placeholders_match_management_planning_targets():
    projections = build_financial_projections()
    conservative = projections["scenarios"]["conservative"]["assumptions"]
    assert conservative == {
        "active_providers": 1,
        "rides_per_provider_per_day": 3.0,
        "operating_days_per_month": 20,
        "avg_net_revenue_per_ride": 30.0,
        "driver_cost_per_ride": 20.0,
        "monthly_tech_cloud": 300,
        "monthly_insurance": 500,
        "monthly_marketing": 300,
        "monthly_compliance_legal": 250,
        "monthly_admin_ops": 500,
        "monthly_other_opex": 150,
    }
    results = projections["scenarios"]["conservative"]["results"]
    assert results["projected_monthly_rides"] == 60.0
    assert results["projected_monthly_gross_revenue"] == 1800.0
    assert results["projected_monthly_transportation_driver_costs"] == 1200.0
    # fixed opex = 300+500+300+250+500+150 = 2000; total opex = 1200+2000 = 3200; net = 1800-3200
    assert results["projected_monthly_operating_expenses"] == 3200.0
    assert results["projected_monthly_net_operating_result"] == -1400.0
    assert results["financial_classification"] == FINANCIAL_PROJECTED
    assert build_master_budget()["total_usd"] == 35000
    assert results["projected_monthly_gross_revenue"] != 35000


def test_grant1_nih_sbir_pipeline_and_readiness_package():
    pipeline = build_master_pipeline()
    grant1 = next(item for item in pipeline if item.get("grant_number") == 1)
    assert grant1["grant_name"] == "NIH SBIR Parent — PA-27-100"
    assert grant1["current_status"] == "APPLICATION PREPARATION / VERIFY NIH INSTITUTE FIT"
    assert grant1["target_date"] == "September 5, 2026"
    assert grant1["priority"] == "HIGH"
    assert grant1["nofo"] == "PA-27-100"
    assert any(item.get("grant_name") == "Launch Minnesota Innovation Grant" for item in pipeline)

    package = build_nih_sbir_grant1_package()
    assert package["external_submission"] is False
    assert package["nofo"] == "PA-27-100"
    assert package["target_receipt_date"] == "September 5, 2026"
    assert package["status"] == "APPLICATION PREPARATION / VERIFY NIH INSTITUTE FIT"
    assert len(package["project_title_options"]) >= 3
    assert package["one_page_project_summary"]
    assert package["problem_unmet_need"]
    assert package["technical_innovation"]
    assert len(package["phase_i_rd_objectives"]) == 3
    assert len(package["technical_work_plan_and_milestones"]) >= 4
    assert package["commercialization_potential"]
    assert package["minnesota_healthcare_impact"]
    assert "Minnesota-based healthcare technology startup" in package["founder_company_capability_summary"]
    budget = package["phase_i_budget_draft"]
    assert budget["financial_classification"] == NIH_SBIR_BUDGET_PLACEHOLDER
    assert "NOT APPROVED REQUEST" in budget["financial_classification"]
    assert "PA-27-100" in budget["financial_classification"]
    assert budget["not_operating_revenue"] is True
    assert budget["not_approved_request"] is True
    assert budget["total_usd"] == 275000
    assert "PLANNING PLACEHOLDER" in budget["disclaimer"]
    assert "NOT an approved Amicor request" in budget["disclaimer"]
    assert all(item["classification"] == NIH_SBIR_BUDGET_PLACEHOLDER for item in budget["line_items"])
    assert any(item["id"] == "institute_fit" for item in package["nih_sbir_application_checklist"])
    blocking = [item for item in package["missing_information_for_management"] if item.get("blocking")]
    assert len(blocking) == 7
    assert all(item["status"] == PENDING_MANAGEMENT_VERIFICATION for item in blocking)
    for required_id in (
        "nih_institute",
        "pi_designation",
        "aims_lock",
        "title_lock",
        "budget_authority",
        "era_commons",
        "human_subjects_call",
    ):
        assert any(item["id"] == required_id for item in blocking)
    # Integrity: package must not invent commercial traction claims.
    banned = ("signed customer contract", "verified clinical outcome", "fda approval", "$1,000,000 revenue")
    blob = " ".join(
        [
            package["one_page_project_summary"],
            package["commercialization_potential"],
            package["minnesota_healthcare_impact"],
        ]
    ).lower()
    for phrase in banned:
        assert phrase not in blob

    payload = build_command_center_payload(
        rides=[],
        drivers=[],
        providers=[],
        applications=[],
        recurring=[],
        delayed_rides=0,
        screenshot_inventory=[],
        transportation_mvp_status="needs_data",
        onboarding_mvp_status="needs_data",
        recurring_mvp_status="needs_data",
        dashboard_mvp_status="needs_data",
    )
    assert payload["nih_sbir_grant1"]["nofo"] == "PA-27-100"
    checklist = {item["id"]: item for item in payload["readiness_checklist"]}
    assert checklist["nih_sbir_grant1_package"]["status"] == "IN PROGRESS"
    assert checklist["nih_institute_fit"]["status"] == PENDING_MANAGEMENT_VERIFICATION
    assert payload["data_integrity"]["legend"] == [
        INTEGRITY_VERIFIED,
        INTEGRITY_DEMO,
        INTEGRITY_PENDING,
    ]
