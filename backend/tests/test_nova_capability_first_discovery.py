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
    is_remote_digital_search_intent,
    score_discovery_candidate,
    search_family_catalog,
    resolve_requested_family,
    resolve_requested_families,
    targeted_queries_for_request,
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



def test_owner_request_resolves_to_specific_capability_family() -> None:
    assert resolve_requested_family("find a bookkeeping job") == "bookkeeping_support"
    assert resolve_requested_family("find writing work") == "document_writing"
    assert resolve_requested_family("find AI operations work") == "ai_automation"
    assert resolve_requested_family("find spreadsheet cleanup work") == "data_spreadsheet"


def test_targeted_queries_do_not_drift_across_families() -> None:
    rows = targeted_queries_for_request("find a bookkeeping job", max_queries=5)
    assert rows
    assert all(row["search_family"] == "bookkeeping_support" for row in rows)
    assert all("bookkeep" in row["query"].lower() or row["query"] == "find a bookkeeping job" or any(
        term in row["query"].lower()
        for term in ("transaction", "expense", "invoice", "accounts", "reconciliation", "financial")
    ) for row in rows)


def test_nova_anonymous_request_routes_to_client_acquisition_family() -> None:
    assert resolve_requested_family("Nova Today, find a client for AMICOR Nova Anonymous Operations Agent") == "nova_anonymous_clients"
    assert resolve_requested_family("find clients for Nova Anonymous") == "nova_anonymous_clients"


def test_nova_anonymous_client_queries_are_buyer_intent_and_capability_backed() -> None:
    rows = targeted_queries_for_request(
        "find clients for Nova Anonymous operations agent",
        max_queries=5,
    )
    assert rows
    assert all(row["search_family"] == "nova_anonymous_clients" for row in rows)
    generated = [row["query"].lower() for row in rows[1:]]
    assert generated
    assert any("automation" in query or "operations support" in query for query in generated)
    assert all(not is_banned_query(query) for query in generated)



def test_compound_owner_request_spreads_search_budget_across_requested_families() -> None:
    rows = targeted_queries_for_request(
        "remote administrative support, spreadsheet analysis, research, AI operations, bookkeeping support",
        max_queries=5,
    )
    families = {row["search_family"] for row in rows}
    assert families == {
        "administrative_operations",
        "data_spreadsheet",
        "research_analysis",
        "ai_automation",
        "bookkeeping_support",
    }
    assert len(rows) == 5
    assert all("remote" in row["query"].lower() or "freelance" in row["query"].lower() or "contractor" in row["query"].lower() for row in rows)



def test_bookkeeping_family_rejects_unrelated_ai_trainer() -> None:
    ranked = qualify_and_rank_live_jobs(
        "remote administrative support, spreadsheet analysis, research, AI operations, bookkeeping support",
        [{
            "provider_id": "remotive",
            "provider_identifier": "trainer-1",
            "title": "AI Trainer Image QA Evaluator",
            "company_name": "Example",
            "description": "Evaluate images and rate model responses for quality.",
            "source_url": "https://example.com/jobs/trainer-1",
            "remote_status": "remote",
            "job_type": "contract",
            "search_family": "bookkeeping_support",
            "search_family_label": "Bookkeeping / financial admin support",
        }],
    )
    assert ranked[0]["discovery_band"] == "REJECT"
    assert ranked[0]["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert ranked[0]["live_qualification"]["auto_prepare_allowed"] is False


def test_bookkeeping_family_keeps_actual_bookkeeping_duties() -> None:
    scored = score_discovery_candidate(
        {
            "title": "Remote bookkeeping support contractor",
            "description": (
                "Remote contractor providing bookkeeping support, financial spreadsheet "
                "preparation, reconciliation support, and invoice tracking."
            ),
            "remote_status": "remote",
            "job_type": "contract",
            "search_family": "bookkeeping_support",
            "search_family_label": "Bookkeeping / financial admin support",
        },
        query="bookkeeping support contractor remote no CPA",
    )
    assert scored["planned_family_duty_match"] is True
    assert scored["discovery_band"] != "REJECT"

def test_sparse_listing_without_family_evidence_is_rejected() -> None:
    scored = score_discovery_candidate(
        {
            "title": "Remote support opportunity",
            "description": "Remote contract opportunity; see source for complete scope.",
            "remote_status": "remote",
            "job_type": "contract",
            "search_family": "bookkeeping_support",
            "search_family_label": "Bookkeeping / financial admin support",
        },
        query="bookkeeping support contractor remote",
    )
    assert scored["planned_family_duty_match"] is False
    assert scored["discovery_band"] == "REJECT"


def test_sparse_listing_with_family_text_evidence_can_survive() -> None:
    scored = score_discovery_candidate(
        {
            "title": "Remote bookkeeping support",
            "description": "Remote contract opportunity for invoice tracking and reconciliation support.",
            "remote_status": "remote",
            "job_type": "contract",
            "search_family": "bookkeeping_support",
            "search_family_label": "Bookkeeping / financial admin support",
        },
        query="bookkeeping support contractor remote",
    )
    assert scored["planned_family_duty_match"] is True
    assert scored["discovery_band"] != "REJECT"

def test_listing_discovered_by_multiple_families_accepts_any_matching_family() -> None:
    scored = score_discovery_candidate(
        {
            "title": "Remote research support contractor",
            "description": "Research and reporting support for a remote client project.",
            "remote_status": "remote",
            "job_type": "contract",
            "search_family": "bookkeeping_support",
            "search_family_candidates": ["bookkeeping_support", "research_analysis"],
        },
        query="remote research and bookkeeping support",
    )
    assert scored["planned_family_duty_match"] is True
    assert "research_analysis" in scored["search_family_candidates"]
    assert scored["discovery_band"] != "REJECT"

def test_generic_family_evidence_gate_blocks_cross_family_drift() -> None:
    cases = [
        ("research_analysis", "Digital Asset Operations Analyst", "Support digital asset operations and internal workflows."),
        ("data_spreadsheet", "Customer Success Specialist", "Handle customer relationships and account coordination."),
        ("document_writing", "Sales Operations Associate", "Coordinate sales operations and pipeline follow-up."),
        ("administrative_operations", "Blockchain Analyst", "Monitor digital asset market operations."),
    ]
    for family_id, title, description in cases:
        scored = score_discovery_candidate(
            {
                "title": title,
                "description": description,
                "remote_status": "remote",
                "job_type": "contract",
                "search_family": family_id,
            },
            query="remote contractor",
        )
        assert scored["planned_family_duty_match"] is False
        assert scored["discovery_band"] == "REJECT"

def test_compound_owner_search_covers_all_requested_families() -> None:
    query = (
        "Remote administrative support, bookkeeping, spreadsheet/data cleanup, "
        "research, AI operations, document preparation, virtual assistant, and "
        "project support contracts that Nova can perform remotely in the United States."
    )
    requested = resolve_requested_families(query)
    rows = targeted_queries_for_request(query, max_queries=min(10, max(5, len(requested) + 2)))
    covered = {row.get("search_family") for row in rows}
    assert set(requested).issubset(covered)
    assert "administrative_operations" in covered
    assert "bookkeeping_support" in covered
    assert "data_spreadsheet" in covered
    assert "research_analysis" in covered
    assert "ai_automation" in covered
    assert "document_writing" in covered


_DIGITAL_CONTRACTOR_QUERY = "remote research data reporting freelance contract"


def _wastewater_operator_job() -> dict:
    return {
        "provider_id": "mn_osp",
        "provider_identifier": "mcf-togo-wastewater",
        "title": "MN DOC/MCF-Togo Class D Wastewater Operator",
        "company_name": "Minnesota Department of Corrections",
        "description": "Solicitation for facility services. Response due via Supplier Portal.",
        "source_url": "https://osp.admin.mn.gov/PT-auto",
        "geography": "Minnesota vendor opportunity",
        "remote_status": "unknown",
        "job_type": "contract",
        "source_attribution": "Minnesota OSP",
    }


def _remote_digital_contractor_job() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "va-remote-1",
        "title": "Remote Virtual Assistant",
        "company_name": "Northwind Digital",
        "description": (
            "Remote 1099 freelance independent contractor for AI operations, admin support, "
            "research, CRM data organization, weekly reporting, project coordination, "
            "content operations, automation support, data cleanup, and virtual assistance. "
            "Vendor / B2B project-based work. AI tools allowed. No membership fee. No on-site work."
        ),
        "source_url": "https://remotive.com/remote-jobs/virtual-assistant-contractor",
        "geography": "United States",
        "remote_status": "remote",
        "job_type": "contract",
        "compensation_text": "$45/hr",
        "source_attribution": "Remotive",
    }


def test_direct_physical_trade_query_is_not_digital_intent() -> None:
    assert is_remote_digital_search_intent("Class D Wastewater Operator") is False
    assert is_remote_digital_search_intent("truck driver CDL") is False
    assert is_remote_digital_search_intent(_DIGITAL_CONTRACTOR_QUERY) is True


def test_wastewater_operator_is_rejected_for_remote_digital_search() -> None:
    scored = score_discovery_candidate(
        _wastewater_operator_job(),
        query=_DIGITAL_CONTRACTOR_QUERY,
    )
    assert scored["physical_licensed_onsite_blocked"] is True
    assert scored["discovery_band"] == "REJECT"
    assert scored["discovery_score"] <= 15
    assert scored["title_used_for_decision"] is False
    assert scored["digital_contractor_rank_boost"] is False


def test_remote_digital_contractor_ranks_above_wastewater_operator() -> None:
    digital = score_discovery_candidate(
        _remote_digital_contractor_job(),
        query=_DIGITAL_CONTRACTOR_QUERY,
    )
    wastewater = score_discovery_candidate(
        _wastewater_operator_job(),
        query=_DIGITAL_CONTRACTOR_QUERY,
    )
    assert digital["physical_licensed_onsite_blocked"] is False
    assert digital["digital_contractor_rank_boost"] is True
    assert digital["discovery_band"] != "REJECT"
    assert digital["discovery_score"] > wastewater["discovery_score"]
    assert digital["title_used_for_decision"] is False

    ranked = qualify_and_rank_live_jobs(
        _DIGITAL_CONTRACTOR_QUERY,
        [_wastewater_operator_job(), _remote_digital_contractor_job()],
    )
    by_title = {row["title"]: row for row in ranked}
    bad = by_title["MN DOC/MCF-Togo Class D Wastewater Operator"]
    good = by_title["Remote Virtual Assistant"]
    assert bad["discovery_band"] == "REJECT"
    assert bad["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert bad["live_qualification"]["auto_prepare_allowed"] is False
    assert "physical_licensed_or_onsite_role" in bad["live_qualification"]["blockers"]
    assert bad["live_qualification"]["external_submission"] is False
    assert bad["live_qualification"]["financial_execution"] is False
    assert good["qualification_status"] != "NOT_QUALIFIED"
    assert good["discovery_band"] != "REJECT"
    assert good["relevance_score"] > bad["relevance_score"]
    assert good["live_qualification"]["external_submission"] is False
    assert good["live_qualification"]["financial_execution"] is False


def test_physical_licensed_onsite_roles_are_blocked_for_digital_intent() -> None:
    cases = [
        ("CDL Delivery Driver", "Commercial driver's license required. Local driving route."),
        ("Registered Nurse", "Active nursing license and in-person patient care."),
        ("Licensed Attorney", "Bar admission and law license required for court appearances."),
        ("Professional Engineer", "PE license and engineering license required on the job site."),
        ("Warehouse Associate", "Warehouse labor, forklift, and manual labor each shift."),
        ("On-site Security Officer", "Security clearance required. Must be on-site."),
        ("Journeyman Electrician", "Construction crew. Licensed electrician. Fully on-site."),
    ]
    for title, description in cases:
        scored = score_discovery_candidate(
            {
                "title": title,
                "description": description,
                "job_type": "contract",
                "remote_status": "unknown",
                "company_name": "Example Agency",
                "source_url": "https://example.com/jobs/physical",
            },
            query=_DIGITAL_CONTRACTOR_QUERY,
        )
        assert scored["discovery_band"] == "REJECT", title
        assert scored["physical_licensed_onsite_blocked"] is True, title


_OWNER_1099_QUERY = (
    "Remote 1099 contractor work for AI operations, administrative support, "
    "project coordination, research, data entry, CRM, reporting, content operations, "
    "virtual assistance, automation support, and digital business operations. "
    "Prioritize jobs Nova can perform remotely without professional licenses, "
    "certifications, upfront fees, or fabricated experience."
)


def _listed_job(title: str, description: str, **extra) -> dict:
    job = {
        "provider_id": "remotive",
        "provider_identifier": title.lower().replace(" ", "-"),
        "title": title,
        "company_name": "Example Buyer",
        "description": description,
        "source_url": "https://remotive.com/remote-jobs/example",
        "geography": "United States",
        "remote_status": "remote",
        "job_type": "contract",
        "compensation_text": "$40/hr",
    }
    job.update(extra)
    return job


def test_owner_1099_query_is_remote_digital_intent() -> None:
    assert is_remote_digital_search_intent(_OWNER_1099_QUERY) is True
    assert len(_OWNER_1099_QUERY) > 220


def test_owner_1099_search_rejects_license_cert_fee_and_experience_history() -> None:
    wastewater = score_discovery_candidate(_wastewater_operator_job(), query=_OWNER_1099_QUERY)
    certified = score_discovery_candidate(
        _listed_job(
            "Remote Project Coordinator",
            "Remote contract project coordination. PMP certification required. Must hold an active certification.",
        ),
        query=_OWNER_1099_QUERY,
    )
    paid_access = score_discovery_candidate(
        _listed_job(
            "Remote Data Entry Contractor",
            "Remote 1099 data entry and CRM cleanup. Application fee required. Pay to apply before tasks are visible.",
        ),
        query=_OWNER_1099_QUERY,
    )
    seasoned = score_discovery_candidate(
        _listed_job(
            "Senior CRM Specialist",
            "Remote CRM reporting and data entry. Minimum 7 years of experience required.",
        ),
        query=_OWNER_1099_QUERY,
    )
    preferred = score_discovery_candidate(
        _listed_job(
            "Remote Operations Assistant",
            "Remote 1099 contractor for administrative support, CRM, reporting, and virtual assistance. "
            "Experience with spreadsheets preferred. No certification required. No upfront fee. No on-site work.",
        ),
        query=_OWNER_1099_QUERY,
    )

    assert wastewater["discovery_band"] == "REJECT"
    assert wastewater["physical_licensed_onsite_blocked"] is True
    assert certified["discovery_band"] == "REJECT"
    assert certified["certification_or_license_blocked"] is True
    assert certified["digital_contractor_rank_boost"] is False
    assert paid_access["discovery_band"] == "REJECT"
    assert paid_access["upfront_fee_blocked"] is True
    assert seasoned["discovery_band"] == "REJECT"
    assert seasoned["unverified_experience_blocked"] is True
    assert preferred["certification_or_license_blocked"] is False
    assert preferred["upfront_fee_blocked"] is False
    assert preferred["unverified_experience_blocked"] is False
    assert preferred["discovery_band"] != "REJECT"
    assert preferred["digital_contractor_rank_boost"] is True
    assert preferred["discovery_score"] > max(
        wastewater["discovery_score"],
        certified["discovery_score"],
        paid_access["discovery_score"],
        seasoned["discovery_score"],
    )

    ranked = qualify_and_rank_live_jobs(
        _OWNER_1099_QUERY,
        [
            _wastewater_operator_job(),
            _listed_job(
                "Remote Project Coordinator",
                "Remote contract project coordination. PMP certification required. Must hold an active certification.",
            ),
            _listed_job(
                "Remote Data Entry Contractor",
                "Remote 1099 data entry and CRM cleanup. Application fee required. Pay to apply before tasks are visible.",
            ),
            _listed_job(
                "Senior CRM Specialist",
                "Remote CRM reporting and data entry. Minimum 7 years of experience required.",
            ),
            _remote_digital_contractor_job(),
        ],
    )
    by_title = {row["title"]: row for row in ranked}
    good = by_title["Remote Virtual Assistant"]
    assert good["discovery_band"] != "REJECT"
    assert good["qualification_status"] != "NOT_QUALIFIED"
    assert good["live_qualification"]["external_submission"] is False
    assert good["live_qualification"]["financial_execution"] is False
    for title, blocker in (
        ("MN DOC/MCF-Togo Class D Wastewater Operator", "physical_licensed_or_onsite_role"),
        ("Remote Project Coordinator", "certification_or_license_required"),
        ("Remote Data Entry Contractor", "upfront_fee_required"),
        ("Senior CRM Specialist", "unverified_experience_required"),
    ):
        row = by_title[title]
        assert row["discovery_band"] == "REJECT", title
        assert row["live_qualification"]["qualification_status"] == "NOT_QUALIFIED", title
        assert row["live_qualification"]["auto_prepare_allowed"] is False, title
        assert blocker in row["live_qualification"]["blockers"], title
        assert row["live_qualification"]["external_submission"] is False
        assert row["live_qualification"]["financial_execution"] is False
        assert good["relevance_score"] > row["relevance_score"]


def test_direct_certification_search_is_not_rewritten() -> None:
    job = _listed_job(
        "PMP Project Manager",
        "PMP certification required for this on-site project management role.",
        remote_status="on-site",
    )
    assert is_remote_digital_search_intent("PMP certification required") is False
    scored = score_discovery_candidate(job, query="PMP certification required")
    assert scored["certification_or_license_blocked"] is False
    assert scored["remote_digital_blockers"] == []


def test_owner_1099_query_does_not_route_content_operations_to_writing() -> None:
    families = resolve_requested_families(_OWNER_1099_QUERY)
    assert "document_writing" not in families
    assert "administrative_operations" in families
    assert "research_analysis" in families
    assert "data_spreadsheet" in families
    assert "ai_automation" in families


def test_owner_1099_search_drops_copywriter_manager_and_ai_trainer() -> None:
    copywriter = _listed_job(
        "Freelance Copywriter",
        "Freelance project-based SEO copywriting. The ideal candidate has experience writing content.",
        search_family="document_writing",
        geography="Worldwide",
        job_type="freelance",
    )
    manager = _listed_job(
        "Project Manager",
        "Lead client projects and coordinate a research team. Worldwide remote.",
        search_family="research_analysis",
        geography="Worldwide",
    )
    trainer = _listed_job(
        "AI Trainer Image QA Evaluator",
        "English-speaking Image Quality Evaluators based in South Korea. Freelance project.",
        geography="Remote",
        search_family="ai_automation",
    )
    product_lead = _listed_job(
        "Technical Product Lead AI Finance App",
        "Lead the AI finance product from Seoul.",
        geography="Seoul",
        search_family="ai_automation",
    )
    assistant = _listed_job(
        "Remote Virtual Assistant",
        "Remote 1099 contractor for inbox, calendar, data entry, and CRM updates. No certification required.",
        search_family="administrative_operations",
    )
    ranked = qualify_and_rank_live_jobs(
        _OWNER_1099_QUERY,
        [copywriter, manager, trainer, product_lead, assistant],
    )
    by_title = {row["title"]: row for row in ranked}
    assert by_title["Freelance Copywriter"]["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert "work_lane_mismatch" in by_title["Freelance Copywriter"]["live_qualification"]["blockers"]
    assert by_title["Project Manager"]["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert by_title["AI Trainer Image QA Evaluator"]["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert "non_us_location_required" in by_title["AI Trainer Image QA Evaluator"]["live_qualification"]["blockers"]
    assert by_title["Technical Product Lead AI Finance App"]["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"
    assert by_title["Remote Virtual Assistant"]["live_qualification"]["qualification_status"] != "NOT_QUALIFIED"
    assert by_title["Remote Virtual Assistant"]["live_qualification"]["external_submission"] is False
    assert by_title["Remote Virtual Assistant"]["live_qualification"]["financial_execution"] is False

