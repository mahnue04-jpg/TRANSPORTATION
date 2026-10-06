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
