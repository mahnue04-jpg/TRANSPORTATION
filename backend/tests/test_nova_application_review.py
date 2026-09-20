"""Tests for Nova capability proof and package readiness."""
from app.core.nova.v3.application_review import review_application_package
from app.core.nova.v3.capability_proof import build_capability_proof
from app.core.nova.work_revenue.materials import generate_drafts


def _automation_opp():
    return {
        "opportunity_title": "AI workflow automation project",
        "company_name": "Example Client",
        "description": "B2B AI workflow automation using Zapier and API integration.",
        "requirements": "Deliver workflow map, tested automation, and documentation.",
    }


def test_capability_proof_is_truthful_demo_not_prior_client_claim():
    proof = build_capability_proof(_automation_opp())
    assert proof["proof_ready"] is True
    assert proof["primary_capability_id"] == "ai_workflow_automation"
    assert "newly created capability demonstration" in proof["disclosure"]
    assert "not represented as prior paid client work" in proof["disclosure"]
    assert proof["external_publish"] is False
    assert proof["external_submission"] is False


def test_package_review_scores_completeness_not_hiring_probability():
    opp = _automation_opp()
    materials = generate_drafts(opp)
    review = review_application_package(opp, materials)
    assert 0 <= review["readiness_score"] <= 100
    assert "does not predict selection" in review["note"]
    assert review["coverage_checks"]["capability_match"] is True
    assert review["coverage_checks"]["execution_plan"] is True
    assert review["coverage_checks"]["proof_plan"] is True
    assert review["external_submission"] is False
    assert review["financial_execution"] is False


def test_package_review_flags_owner_input_without_inventing_facts():
    opp = _automation_opp()
    materials = generate_drafts(opp)
    review = review_application_package(opp, materials)
    assert review["owner_input_markers"] > 0
    assert review["status"] == "OWNER_INPUT_REQUIRED"
    assert "owner_input_required" in review["blockers"]


def test_package_review_detects_missing_required_material():
    opp = _automation_opp()
    materials = [
        item for item in generate_drafts(opp)
        if item["kind"] != "resume"
    ]
    review = review_application_package(opp, materials)
    assert "resume" in review["missing_materials"]
    assert "required_materials_missing" in review["blockers"]


def test_unsupported_work_does_not_get_capability_proof():
    opp = {
        "opportunity_title": "On-site field role",
        "description": "Must personally perform in-person field work.",
    }
    proof = build_capability_proof(opp)
    assert proof["proof_ready"] is False
    assert proof["external_submission"] is False
