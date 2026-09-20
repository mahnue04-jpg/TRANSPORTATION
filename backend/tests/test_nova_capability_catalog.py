"""Focused tests for Nova Capability & Work Execution Engine V1."""
from app.core.nova.v3.capability_catalog import (
    capability_catalog,
    capability_fit,
    capability_search_queries,
)


def test_catalog_contains_core_sellable_service_families():
    ids = {row["capability_id"] for row in capability_catalog()}
    assert {
        "business_research",
        "administrative_operations",
        "data_spreadsheet",
        "ai_workflow_automation",
        "bookkeeping_support",
        "content_documentation",
        "web_software",
        "customer_support_operations",
        "proposal_rfp",
        "document_intelligence",
    }.issubset(ids)


def test_ai_automation_project_matches_concrete_capability():
    result = capability_fit(
        "B2B vendor wanted for AI workflow automation using Zapier and API integration. "
        "Deliver workflow map, tested automation, and documentation."
    )
    assert result["fit"] is True
    assert result["score"] >= 55
    assert result["capabilities"][0]["capability_id"] == "ai_workflow_automation"


def test_research_and_spreadsheet_project_can_match_multiple_capabilities():
    result = capability_fit(
        "Vendor research project: competitor research, data cleaning, Excel spreadsheet, "
        "comparison table and reporting."
    )
    ids = {row["capability_id"] for row in result["capabilities"]}
    assert result["fit"] is True
    assert "business_research" in ids
    assert "data_spreadsheet" in ids


def test_bookkeeping_support_does_not_claim_cpa_work():
    safe = capability_fit(
        "Bookkeeping support project for receipt organization, transaction categorization "
        "and reconciliation preparation."
    )
    regulated = capability_fit(
        "Bookkeeping support and financial spreadsheet work. CPA required."
    )
    assert safe["fit"] is True
    assert regulated["fit"] is False
    assert "regulated_or_credentialed_work" in regulated["blockers"]


def test_human_only_work_is_not_a_nova_capability():
    result = capability_fit(
        "Administrative support contract but the contractor must personally perform "
        "in-person field work."
    )
    assert result["fit"] is False
    assert "human_only_work" in result["blockers"]


def test_capability_search_queries_are_targeted_and_deduplicated():
    queries = capability_search_queries()
    assert len(queries) == len({q.lower() for q in queries})
    assert any("AI workflow automation" in q for q in queries)
    assert any("spreadsheet" in q.lower() for q in queries)
    assert any("RFP" in q for q in queries)
