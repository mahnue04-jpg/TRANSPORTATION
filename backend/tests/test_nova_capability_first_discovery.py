"""Capability-first nationwide discovery planner tests."""
from __future__ import annotations

from app.core.nova.v3.capability_catalog import capability_search_queries
from app.core.nova.v3.live_qualification import qualify_and_rank_live_jobs, qualify_live_job
from app.core.nova.work_revenue.capability_classification import (
    CANNOT_PERFORM,
    CAN_PERFORM,
    INSUFFICIENT_INFORMATION,
)
from app.core.nova.work_revenue.capability_first_discovery import (
    SEARCH_FAMILIES,
    assert_no_banned_generated_queries,
    capability_first_search_queries,
    generate_capability_first_queries,
    is_banned_query,
    score_discovery_candidate,
    search_family_catalog,
)
from app.core.nova.work_revenue.flags import EXTERNAL_SUBMISSION_ENABLED, FINANCIAL_ACTIONS_ENABLED


def test_banned_generic_queries_are_not_generated() -> None:
    queries = capability_first_search_queries()
    blob = "\n".join(queries).lower()
    assert "delivery driver" not in blob
    assert "warehouse associate" not in blob
    assert "registered nurse" not in blob
    assert "warehouse jobs" not in blob
    assert "jobs near me" not in blob
    assert_no_banned_generated_queries(queries)
    assert is_banned_query("delivery driver jobs")
    assert is_banned_query("warehouse associate")
    assert is_banned_query("Registered Nurse")


def test_required_capability_first_queries_are_generated() -> None:
    queries = [q.lower() for q in capability_first_search_queries()]
    assert any("inventory" in q and "contractor" in q for q in queries)
    assert any("dispatch" in q or "logistics" in q or "shipment tracking" in q for q in queries)
    assert any("administrative support" in q for q in queries)
    assert any("bookkeeping" in q for q in queries)
    assert any("research" in q for q in queries)
    assert any("spreadsheet" in q or "excel" in q or "csv" in q for q in queries)
    assert any("healthcare" in q and "administrative" in q for q in queries)
    assert any("ai" in q and ("workflow" in q or "operations" in q or "automation" in q) for q in queries)


def test_all_search_families_are_ready() -> None:
    catalog = {row["family_id"]: row for row in search_family_catalog()}
    required = {
        "administrative_operations",
        "bookkeeping_support",
        "data_spreadsheet",
        "research_analysis",
        "document_writing",
        "customer_support_operations",
        "web_software",
        "logistics_digital",
        "transportation_digital",
        "healthcare_non_clinical",
        "ai_automation",
    }
    assert required.issubset(catalog.keys())
    assert all(catalog[key]["supported"] for key in required)
    assert all(catalog[key]["query_count"] > 0 for key in required)


def test_web_software_queries_limited_to_verified_capabilities() -> None:
    planned = generate_capability_first_queries(families=["web_software"])
    assert planned
    for row in planned:
        assert row["search_family"] == "web_software"
        assert row["capability_registry_matches"]


def test_nationwide_remote_geography_is_default() -> None:
    planned = generate_capability_first_queries()
    assert planned
    assert all("nationwide" in row["geography"].lower() or "remote" in row["geography"].lower() for row in planned)
    assert all("remote" in row["query"].lower() or "freelance" in row["query"].lower() or "contractor" in row["query"].lower() for row in planned)


def test_state_restricted_opportunity_is_flagged() -> None:
    scored = score_discovery_candidate(
        {
            "title": "Remote research contractor",
            "description": "Business research freelance project. Candidates must reside in California only.",
            "remote_status": "remote",
            "job_type": "contract",
            "compensation_text": "$40/hr",
        },
        query="business research freelance project",
    )
    assert scored["state_restriction_detected"] is True
    assert scored["nationwide_remote_allowed"] is True


def test_physical_w2_and_licensed_work_are_rejected() -> None:
    physical = score_discovery_candidate(
        {
            "title": "Warehouse associate",
            "description": "Lift boxes, pack orders, operate forklift on-site every shift.",
            "physical_presence_required": "true",
            "job_type": "contract",
        }
    )
    employee = score_discovery_candidate(
        {
            "title": "Remote admin",
            "description": "Spreadsheet reporting as a W-2 full-time employee.",
            "job_type": "full_time",
            "remote_status": "remote",
        }
    )
    licensed = score_discovery_candidate(
        {
            "title": "Clinic support",
            "description": "Registered nurse patient care and clinical judgment required.",
            "physical_presence_required": "true",
            "job_type": "contract",
        }
    )
    assert physical["capability_classification"] == CANNOT_PERFORM
    assert physical["discovery_band"] == "REJECT"
    assert employee["capability_classification"] == CANNOT_PERFORM
    assert licensed["capability_classification"] == CANNOT_PERFORM


def test_valid_remote_b2b_digital_work_scores_strong() -> None:
    scored = score_discovery_candidate(
        {
            "title": "Remote inventory reconciliation contractor",
            "description": (
                "Vendor / B2B remote contractor. Analyze inventory spreadsheets, clean data, "
                "prepare reports. AI tools allowed. No membership fee."
            ),
            "remote_status": "remote",
            "job_type": "contract",
            "compensation_text": "$55/hr",
        },
        query="remote inventory analyst contractor",
    )
    assert scored["capability_classification"] == CAN_PERFORM
    assert scored["discovery_score"] >= 60
    assert scored["remote_eligibility"] == "YES"
    assert scored["search_family"] == "logistics_digital"


def test_ai_contractor_query_respects_ai_policy_rules() -> None:
    allowed = qualify_live_job(
        {
            "title": "AI workflow support contractor",
            "description": (
                "Remote vendor AI workflow support. AI tools allowed. Independent contractor. "
                "No membership fee. Deliver automation documentation."
            ),
            "source_url": "https://remotive.com/remote-jobs/ai-workflow-ok",
            "compensation_text": "$60/hr",
            "job_type": "contract",
            "source_attribution": "Remotive",
            "remote_status": "remote",
        }
    )
    banned = score_discovery_candidate(
        {
            "title": "AI content operations",
            "description": "Remote AI content operations. AI-assisted work is not allowed. Do not use AI.",
            "job_type": "contract",
            "remote_status": "remote",
            "ai_policy": "prohibited",
        },
        query="AI content operations remote contractor",
    )
    assert allowed["external_submission"] is False
    assert allowed["financial_execution"] is False
    assert banned["capability_classification"] == CANNOT_PERFORM or banned["discovery_band"] in {"REJECT", "OWNER_REVIEW"}


def test_catalog_search_queries_use_capability_first_planner() -> None:
    queries = capability_search_queries()
    assert queries == capability_first_search_queries()
    assert any("inventory" in q.lower() for q in queries)


def test_qualify_and_rank_attaches_discovery_metadata() -> None:
    ranked = qualify_and_rank_live_jobs(
        "remote inventory analyst contractor",
        [
            {
                "provider_id": "remotive",
                "provider_identifier": "inv-1",
                "title": "Remote inventory analyst contractor",
                "company_name": "Logistics Co",
                "description": (
                    "Vendor / B2B remote contractor. Inventory spreadsheet analysis and reporting. "
                    "AI tools allowed. No membership fee."
                ),
                "source_url": "https://remotive.com/remote-jobs/inventory-analyst",
                "geography": "Worldwide",
                "remote_status": "remote",
                "compensation_text": "$50/hr",
                "job_type": "contract",
                "source_attribution": "Remotive",
                "publication_date": "2026-09-20T00:00:00",
            }
        ],
    )
    assert ranked
    row = ranked[0]
    assert row["search_family"] == "logistics_digital"
    assert row["why_searched"]
    assert row["discovery_score"] >= 60
    assert row["live_qualification"]["nationwide_remote_allowed"] is True
    assert row["live_qualification"]["external_submission"] is False
    assert row["live_qualification"]["financial_execution"] is False


def test_insufficient_duties_band() -> None:
    scored = score_discovery_candidate(
        {"title": "Role not described", "description": "", "job_type": "contract"}
    )
    assert scored["capability_classification"] == INSUFFICIENT_INFORMATION
    assert scored["discovery_band"] == "INSUFFICIENT_INFORMATION"


def test_search_family_never_generate_lists() -> None:
    assert "warehouse associate" in SEARCH_FAMILIES["logistics_digital"]["never_generate"]
    assert "delivery driver" in SEARCH_FAMILIES["transportation_digital"]["never_generate"]
    assert "registered nurse" in SEARCH_FAMILIES["healthcare_non_clinical"]["never_generate"]


def test_external_and_financial_remain_off() -> None:
    assert EXTERNAL_SUBMISSION_ENABLED is False
    assert FINANCIAL_ACTIONS_ENABLED is False
