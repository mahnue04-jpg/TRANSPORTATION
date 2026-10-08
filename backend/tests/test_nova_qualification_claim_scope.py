"""Requirement modifiers must stay attached to the qualification they govern."""
from __future__ import annotations

import pytest

from app.core.nova.work_revenue.capability_first_discovery import (
    certification_or_license_required,
    unverified_experience_required,
    score_discovery_candidate,
)
from app.core.nova.v3.live_qualification import qualify_and_rank_live_jobs
from app.core.nova.v3.multi_source_discovery import _query_relevant


QUERY = "Remote 1099 administrative support, research, and AI operations contractor"


def job(description: str) -> dict:
    return {
        "provider_id": "remotive",
        "title": "Remote Operations Assistant",
        "description": "Remote 1099 administrative support, CRM and research. " + description,
        "job_type": "contract",
        "remote_status": "remote",
        "geography": "United States",
        "source_url": "https://example.com/contract",
    }


@pytest.mark.parametrize("description", [
    "PMP certification is not required.",
    "PMP not required.",
    "CPA is not mandatory.",
    "No PMP certification required.",
    "No professional certification required.",
    "PMP preferred; Excel required.",
    "CPA preferred, Excel required.",
    "CPA experience helpful; must have Excel skills.",
    "Excel required; collaborate with a CPA.",
    "Must have Excel skills and support the CPA.",
])
def test_credentials_are_not_inferred_from_negation_or_unrelated_skills(description):
    assert certification_or_license_required(job(description)) is False


@pytest.mark.parametrize("description", [
    "PMP certification required.",
    "CPA required.",
    "CAPM certification is mandatory.",
    "Must have PMP certification.",
    "Must hold a current professional license.",
    "Must be a CPA.",
    "Required to possess a valid license.",
    "Required: CISSP certification.",
    "Required PMP certification.",
    "Requires PMP certification.",
    "PMP: required.",
    "PMP certification is a must.",
    "CPA license must be current.",
    "PMP or CAPM required.",
    "PMP, CAPM, or CPA required.",
    "Must be certified.",
    "No PMP required; CPA required.",
    "CPA preferred, PMP required.",
    "Preferred: PMP certification required.",
    "PMP certification required; experience is not required.",
])
def test_genuine_credential_requirements_stay_blocked(description):
    assert certification_or_license_required(job(description)) is True


@pytest.mark.parametrize("description", [
    "Preferred: 5+ years of experience.",
    "Preferred - 5+ years of experience.",
    "Optional: minimum 5 years of experience.",
    "Nice to have: 3-5 years of experience.",
    "5+ years of experience preferred.",
    "5+ years of experience is not required.",
    "No minimum 5 years of experience required.",
])
def test_preferred_or_negated_experience_is_not_mandatory(description):
    assert unverified_experience_required(job(description)) is False


@pytest.mark.parametrize("description", [
    "Minimum 5 years of experience required.",
    "Must have 5 years of experience.",
    "Requires 5 years of experience.",
    "5 years of experience is required.",
    "5+ years of experience.",
    "3-5 years of experience.",
    "Preferred: 5+ years of experience; must have 7 years of experience.",
    "Preferred: 5+ years of experience. Minimum 7 years of experience required.",
    "Preferred: must have 5 years of experience.",
    "Preferred: 5+ years of experience required.",
])
def test_genuine_experience_requirements_stay_blocked(description):
    assert unverified_experience_required(job(description)) is True


@pytest.mark.parametrize("description, credential, experience", [
    ("PMP certification is not required. Preferred: 5+ years of experience.", False, False),
    ("CPA preferred, Excel required. Preferred: 5+ years of experience.", False, False),
    ("No PMP required; CPA required. Preferred: 5+ years of experience.", True, False),
    ("PMP not required. Must have 5 years of experience.", False, True),
])
def test_discovery_and_live_qualification_use_the_correct_requirement_scope(description, credential, experience):
    listing = job(description)
    scored = score_discovery_candidate(listing, query=QUERY)
    assert scored["certification_or_license_blocked"] is credential
    assert scored["unverified_experience_blocked"] is experience
    assert _query_relevant(listing, "administrative support contractor remote") is not (credential or experience)
    qualified = qualify_and_rank_live_jobs(QUERY, [listing])[0]["live_qualification"]
    assert ("certification_or_license_required" in qualified["blockers"]) is credential
    assert ("unverified_experience_required" in qualified["blockers"]) is experience
    if credential or experience:
        assert scored["discovery_band"] == "REJECT"
        assert qualified["auto_prepare_allowed"] is False
