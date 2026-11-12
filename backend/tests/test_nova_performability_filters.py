"""FIXTURE regression for performability filters.

These records are labeled fixtures. They are not live leads and they are not
verified matches.
"""
from __future__ import annotations

from app.core.nova.v3.live_qualification import qualify_and_rank_live_jobs
from app.core.nova.v3.multi_source_discovery import _query_relevant
from app.core.nova.work_revenue.capability_first_discovery import (
    remote_digital_performability_blockers,
    score_discovery_candidate,
    unverified_experience_required,
    upfront_fee_required,
)


def _fixture(**overrides) -> dict:
    row = {
        "record_class": "FIXTURE",
        "provider_id": "remotive",
        "provider_type": "remote_contract_feed",
        "company_name": "Fixture Co",
        "source_url": "https://example.invalid/fixture",
        "geography": "United States",
        "remote_status": "remote",
        "job_type": "contract",
        "compensation_text": "$40/hr",
        "source_attribution": "Remotive",
        "publication_date": "2026-10-01T00:00:00+00:00",
    }
    row.update(overrides)
    return row


def _kept(query: str, job: dict) -> dict:
    ranked = qualify_and_rank_live_jobs(query, [job])[0]
    qual = ranked["live_qualification"]
    return {
        "relevant": _query_relevant(job, query),
        "band": score_discovery_candidate(job, query=query)["discovery_band"],
        "status": qual["qualification_status"],
        "blockers": list(qual.get("blockers") or []),
        "work_type": qual.get("work_type"),
        "fee": upfront_fee_required(job),
        "experience": unverified_experience_required(job),
        "performability": remote_digital_performability_blockers(job, query),
    }


def test_fixture_batch_keeps_performable_remote_work_and_hard_blocks():
    """A realistic public-style batch must not score zero for work Nova can do."""
    cases = {
        "ai_automation": (
            "AI workflow automation contractor",
            _fixture(
                title="AI Workflow Automation Contractor",
                description=(
                    "Remote independent contractor. Build AI workflow automation with n8n and "
                    "Dify for intake routing. AI tools allowed. No certification required. "
                    "Preferred: 3 years of automation experience. No application fee. "
                    "Vendors welcome. $4,000 per project."
                ),
            ),
        ),
        "fastapi": (
            "API integration contractor remote",
            _fixture(
                title="FastAPI API Integration Contractor",
                description=(
                    "Remote 1099 contractor to build a FastAPI API integration and webhook. "
                    "No license required. No upfront fee. Agencies welcome. $5,000 per project."
                ),
            ),
        ),
        "api_developer_title": (
            "API integration contractor remote",
            _fixture(
                title="API Integration Developer",
                description=(
                    "Remote contractor FastAPI API integration and workflow automation. "
                    "Independent contractor. No certification. No fee to apply. Vendors welcome. "
                    "$6,000 fixed price."
                ),
            ),
        ),
        "operational_support": (
            "operations support contractor remote",
            _fixture(
                title="Operational Support Specialist",
                description=(
                    "Remote contractor for operational support, CRM notes, document preparation, "
                    "and reporting. Independent contractor. A subsidized gym membership is available. "
                    "No application fee. $35/hr."
                ),
            ),
        ),
        "virtual_assistant": (
            "virtual assistant",
            _fixture(
                title="Virtual Assistant",
                description=(
                    "Remote virtual assistant contractor for administrative support, scheduling, "
                    "and CRM data entry. Full-time hours. Independent contractor. "
                    "A subsidized gym membership is available. No application fee. "
                    "No certification required. Preferred: 2 years of VA experience. Vendors welcome."
                ),
            ),
        ),
        "commitment": (
            "virtual assistant",
            _fixture(
                title="Virtual Assistant",
                description=(
                    "Remote contractor virtual assistant. 12-month commitment. "
                    "Company founded 8 years ago. Administrative support and CRM. "
                    "No certification required. No application fee. Vendors welcome. $28/hr."
                ),
            ),
        ),
        "business_process": (
            "business process contractor remote",
            _fixture(
                title="Business Process Specialist",
                description=(
                    "Remote contractor to document business processes, draft SOPs, and prepare "
                    "workflow documentation. No certification. No fee. Vendors welcome. "
                    "$3,500 per project."
                ),
            ),
        ),
        "rfp": (
            "procurement rfp administrative support",
            _fixture(
                provider_id="mn_osp",
                provider_type="public_rfp_feed",
                title="Request for Proposals: Business Process and Administrative Support Services",
                company_name="Fixture County",
                description=(
                    "The agency seeks a remote vendor for administrative support, document "
                    "preparation, reporting, and workflow documentation. No application fee. "
                    "No license required."
                ),
                compensation_text="$25,000",
                geography="Minnesota",
            ),
        ),
    }
    kept = []
    for name, (query, job) in cases.items():
        view = _kept(query, job)
        assert view["relevant"] is True, name
        assert view["fee"] is False, name
        assert view["experience"] is False, name
        assert view["band"] != "REJECT", name
        assert view["status"] != "NOT_QUALIFIED", name
        assert "employee_w2_staff_role" not in view["blockers"], name
        assert "unverified_experience_required" not in view["blockers"], name
        assert "upfront_fee_required" not in view["performability"], name
        kept.append(name)
    assert len(kept) == 8

    hard = {
        "fee": _fixture(
            title="Virtual Assistant",
            description="Remote contractor. You must pay an application fee before you can apply.",
        ),
        "license": _fixture(
            title="Virtual Assistant",
            description="Remote contractor administrative support. CPA license required. Must be licensed.",
        ),
        "onsite": _fixture(
            title="Office Assistant",
            description="Administrative support. Must be on-site daily. Physical presence required.",
            remote_status="on-site",
        ),
        "years": _fixture(
            title="Virtual Assistant",
            description="Remote contractor. Minimum 5 years of experience required. Administrative support.",
        ),
        "connects": _fixture(
            provider_id="upwork",
            title="Virtual Assistant",
            description="Remote contractor CRM and admin. Upwork paid connects are required to submit.",
            source_url="https://www.upwork.com/jobs/fixture",
        ),
        "employee": _fixture(
            title="Virtual Assistant",
            description="Full-time staff position. Join our team as a W-2 employee with benefits package and 401k.",
            job_type="full_time",
        ),
    }
    for name, job in hard.items():
        view = _kept("virtual assistant", job)
        assert view["relevant"] is False, name
        assert view["status"] == "NOT_QUALIFIED", name


def test_full_time_hours_do_not_override_an_explicit_contractor():
    job = _fixture(
        title="Virtual Assistant",
        description=(
            "Full-time hours as a 1099 independent contractor for administrative support "
            "and CRM data entry. No benefits package. No application fee. Vendors welcome. $30/hr."
        ),
        job_type="full_time",
    )
    view = _kept("virtual assistant", job)
    assert view["work_type"] != "employee"
    assert view["relevant"] is True
    assert view["status"] != "NOT_QUALIFIED"
    assert "employee_w2_staff_role" not in view["blockers"]


def test_not_remote_status_does_not_count_as_remote():
    job = _fixture(
        title="Operations Assistant",
        description="Office operations support. Remote work is not offered.",
        geography="India",
        remote_status="not_remote",
    )
    scored = score_discovery_candidate(job, query="operations support contractor remote")
    assert scored["remote_eligibility"] == "NO"
    assert "non_us_location_required" in scored["remote_digital_blockers"]


def test_data_entry_hyphen_title_stays_in_the_data_entry_lane():
    from app.core.nova.work_revenue.capability_first_discovery import single_lane_title_match

    job = _fixture(
        title="Data-Entry Specialist",
        description="Remote data-entry contractor. Spreadsheet cleanup. No upfront fee.",
    )
    assert single_lane_title_match(job, "Remote 1099 data-entry contractor") is True
    assert single_lane_title_match(job, "Remote 1099 administrative support work") is False
