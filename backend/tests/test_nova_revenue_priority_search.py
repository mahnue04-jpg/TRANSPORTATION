from app.core.nova.work_revenue.capability_first_discovery import (
    PRIMARY_REVENUE_FAMILIES,
    generate_capability_first_queries,
    resolve_requested_families,
    score_discovery_candidate,
)


def test_primary_revenue_families_are_searched_first() -> None:
    rows = generate_capability_first_queries()
    seen = []
    for row in rows:
        family = row["search_family"]
        if family not in seen:
            seen.append(family)
        if len(seen) == len(PRIMARY_REVENUE_FAMILIES):
            break
    assert tuple(seen) == PRIMARY_REVENUE_FAMILIES


def test_owner_request_resolves_new_primary_revenue_lanes() -> None:
    families = resolve_requested_families(
        "Find lead generation, podcast transcription, workflow automation, and API integration contracts"
    )
    assert "lead_generation_public_data" in families
    assert "content_media_processing" in families
    assert "b2b_workflow_automation" in families
    assert "api_micro_saas" in families


def test_primary_lane_bonus_requires_duty_evidence() -> None:
    job = {
        "title": "Public business lead list research",
        "description": "Build a B2B lead list from public business directories and organize results in a spreadsheet.",
        "requirements": "Research and spreadsheet cleanup",
        "job_type": "fixed-price freelance contract",
        "remote_status": "remote",
        "physical_presence_required": "false",
        "compensation_text": "$500 fixed price",
        "search_family": "lead_generation_public_data",
        "search_family_candidates": ["lead_generation_public_data"],
        "search_family_label": "Lead generation / permitted public-data research",
    }
    scored = score_discovery_candidate(job)
    assert scored["planned_family_duty_match"] is True
    assert scored["discovery_score"] >= 80
    assert scored["discovery_band"] == "STRONG_FIT"


def test_primary_lane_bonus_updates_owner_review_band() -> None:
    job = {
        "title": "Remote public data cleanup",
        "description": "Research public records and organize the results in a spreadsheet.",
        "requirements": "Research and reporting",
        "job_type": "contract",
        "remote_status": "remote",
        "physical_presence_required": "false",
        "search_family": "lead_generation_public_data",
        "search_family_candidates": ["lead_generation_public_data"],
    }
    scored = score_discovery_candidate(job)
    assert scored["planned_family_duty_match"] is True
    assert scored["discovery_score"] >= 60
    assert scored["discovery_band"] in {"OWNER_REVIEW", "STRONG_FIT"}


def test_lead_generation_proposal_does_not_use_job_listing_as_target() -> None:
    from app.core.nova.work_revenue.materials import generate_drafts

    drafts = generate_drafts(
        {
            "opportunity_title": "Lead list build",
            "company_name": "Example Buyer",
            "description": "Build a public-data lead list.",
            "search_family": "lead_generation_public_data",
            "source_name": "Example Job Board",
            "source_url": "https://jobs.example.com/posting/123",
        }
    )
    proposal = next(item["body"] for item in drafts if item["kind"] == "proposal")
    assert "https://jobs.example.com/posting/123" not in proposal
    assert "Example Job Board" not in proposal
    assert "[TARGET WEBSITE / DIRECTORY]" in proposal


def test_search_family_survives_persisted_opportunity_payload() -> None:
    from types import SimpleNamespace
    from app.core.nova.work_revenue.service import _opportunity_payload

    row = SimpleNamespace(
        opportunity_title="Lead list build",
        description="Build public business leads.",
        requirements="Public sources only.",
        location="Remote",
        skills_required="[]",
        credentials_required="[]",
        physical_presence_required="false",
        compensation_type="fixed",
        compensation_amount=500,
        compensation_period="project",
        company_name="Example Buyer",
        engagement_type="contract",
        remote_status="remote",
        tags_json='["live_discovery","search_family:lead_generation_public_data"]',
    )
    payload = _opportunity_payload(row)
    assert payload["search_family"] == "lead_generation_public_data"
