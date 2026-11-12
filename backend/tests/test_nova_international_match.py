"""Country-specific eligibility for worldwide Work and Revenue matches.

A populated residency, citizenship, or permit field is not a match. The
verified place has to be the country or region the listing requires.
"""
from __future__ import annotations

from app.core.nova.work_revenue.capability_first_discovery import non_us_location_required
from app.core.nova.work_revenue.international_match import (
    AI_ASSISTED_TRANSLATION_LABEL,
    assess_country_eligibility,
    assess_international_match,
    international_blockers,
)

_US_PROFILE = {
    "residency": "United States",
    "citizenship": "United States",
    "work_permits": ["United States"],
}
_POPULATED_PROFILE = {
    "residency": True,
    "citizenship": "yes",
    "work_permits": ["populated"],
    "visas": "on file",
}


def _job(description: str, **extra: object) -> dict:
    job = {
        "title": "Remote Operations Assistant",
        "description": description,
        "geography": "Worldwide",
        "remote_status": "remote",
    }
    job.update(extra)
    return job


def test_us_resident_does_not_match_uae_only_role() -> None:
    description = "Remote B2B CRM support. Must reside in the UAE. Work from anywhere."
    blockers = international_blockers(_job(description), facts=_US_PROFILE)
    assert "residency_required" in blockers
    eligibility = assess_country_eligibility(description, _US_PROFILE)
    assert eligibility["residency"]["required"] is True
    assert eligibility["residency"]["met"] is False
    assert eligibility["residency"]["unverifiable"] is False
    assert eligibility["residency"]["alternatives"] == [["AE"]]

    matched = international_blockers(
        _job(description),
        facts={"residency": "United Arab Emirates"},
    )
    assert "residency_required" not in matched


def test_populated_field_does_not_satisfy_a_different_or_unknown_place() -> None:
    uae = "Remote administrative support. UAE residents only."
    citizen = "Remote administrative support. US citizenship required."
    permit = "Remote CRM support. Work permit for Germany required."
    visa = "Remote CRM support. Must hold a valid visa."
    for description in (uae, citizen, permit, visa):
        blockers = international_blockers(_job(description), facts=_POPULATED_PROFILE)
        assert blockers, description
    assert "residency_required" in international_blockers(_job(uae), facts=_POPULATED_PROFILE)
    assert "citizenship_required" in international_blockers(_job(citizen), facts=_POPULATED_PROFILE)
    assert "permit_required" in international_blockers(_job(permit), facts=_POPULATED_PROFILE)
    assert "permit_required" in international_blockers(_job(visa), facts=_POPULATED_PROFILE)
    assert assess_country_eligibility(visa, _POPULATED_PROFILE)["permit"]["unverifiable"] is True

    canada_citizen = international_blockers(
        _job(citizen),
        facts={"citizenship": "Canada"},
    )
    assert "citizenship_required" in canada_citizen
    us_citizen = international_blockers(_job(citizen), facts={"citizenship": "United States"})
    assert "citizenship_required" not in us_citizen

    us_permit = international_blockers(_job(permit), facts={"work_permits": ["United States"]})
    assert "permit_required" in us_permit
    german_permit = international_blockers(_job(permit), facts={"work_permits": ["Germany"]})
    assert "permit_required" not in german_permit


def test_missing_eligibility_fails_closed() -> None:
    description = "Remote CRM support. Must reside in the United States, Canada, or the United Kingdom."
    blockers = international_blockers(_job(description), facts={})
    assert "residency_required" in blockers
    eligibility = assess_country_eligibility(description, {})
    assert eligibility["residency"]["met"] is False
    assert set(eligibility["residency"]["alternatives"][0]) == {"US", "CA", "GB"}

    unnamed = "Remote CRM support. Residency required. Citizenship required. Work permit required."
    unnamed_blockers = international_blockers(_job(unnamed), facts=_US_PROFILE)
    assert "residency_required" in unnamed_blockers
    assert "citizenship_required" in unnamed_blockers
    assert "permit_required" in unnamed_blockers
    unnamed_eligibility = assess_country_eligibility(unnamed, _US_PROFILE)
    assert unnamed_eligibility["residency"]["unverifiable"] is True
    assert unnamed_eligibility["citizenship"]["unverifiable"] is True
    assert unnamed_eligibility["permit"]["unverifiable"] is True


def test_arabic_mena_role_is_not_cleared_by_language_or_us_residence() -> None:
    description = (
        "Remote Arabic customer email. MENA residency required. Must reside in the UAE. "
        "No upfront fee."
    )
    assessed = assess_international_match(_job(description), facts=_US_PROFILE)
    assert "residency_required" in assessed["blockers"]
    assert "untested_language_required" not in assessed["blockers"]
    assert "native_fluency_required" not in assessed["blockers"]
    assert assessed["language_support"] == "ai_assisted_translation"
    assert assessed["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert assessed["tested_language_codes"] == ["ar"]
    assert assessed["native_fluency_claimed"] is False
    assert assessed["native_speaker_capability"] is False
    assert assessed["ai_translation_is_native_fluency"] is False
    assert assessed["tested_languages"][0]["label"] == "AI-assisted translation"
    assert "native speaker" not in assessed["language_support_label"].lower()

    mena_region_only = assess_country_eligibility(description, {"residency": "MENA"})
    assert mena_region_only["residency"]["met"] is False

    uae_resident = assess_international_match(
        _job(description),
        facts={"residency": "Dubai"},
    )
    assert "residency_required" not in uae_resident["blockers"]
    assert uae_resident["language_support_label"] == "AI-assisted translation"
    assert uae_resident["native_speaker_capability"] is False


def test_multiple_allowed_countries_match_only_a_listed_place() -> None:
    description = (
        "Remote B2B administrative support. "
        "Must reside in the United States, Canada, or the United Kingdom."
    )
    assert "residency_required" not in international_blockers(_job(description), facts=_US_PROFILE)
    assert "residency_required" not in international_blockers(
        _job(description),
        facts={"residency": "Canada"},
    )
    france = international_blockers(_job(description), facts={"residency": "France"})
    assert "residency_required" in france
    assert "residency_required" in international_blockers(_job(description), facts=_POPULATED_PROFILE)
    assert "residency_required" in international_blockers(_job(description), facts={})


def test_location_preference_is_not_mandatory_residence() -> None:
    preferred = (
        "Remote Arabic customer email. Location preference: United Arab Emirates. "
        "Prefer candidates based in the UAE. UAE residency preferred. "
        "No residency requirement. No upfront fee."
    )
    preferred_blockers = international_blockers(_job(preferred), facts=_US_PROFILE)
    assert "residency_required" not in preferred_blockers
    assessed = assess_international_match(_job(preferred), facts=_US_PROFILE)
    assert assessed["language_support_label"] == "AI-assisted translation"
    assert assessed["native_fluency_claimed"] is False

    mandatory = "Remote Arabic customer email. Must reside in the United Arab Emirates."
    assert "residency_required" in international_blockers(_job(mandatory), facts=_US_PROFILE)


def test_remote_client_country_is_not_worker_location() -> None:
    description = (
        "Remote B2B administrative support for a company based in Germany. "
        "Customers located in Dubai. Support for clients in France. "
        "English customer email. Visa sponsorship available. No residency requirement."
    )
    job = _job(description)
    assert non_us_location_required(job) is False
    blockers = international_blockers(job, facts=_US_PROFILE)
    assert "residency_required" not in blockers
    assert "permit_required" not in blockers
    assessed = assess_international_match(job, facts={})
    assert assessed["language_support_label"] == "AI-assisted translation"
    assert assessed["native_speaker_capability"] is False
    assert assessed["eligibility"]["residency"]["required"] is False
    assert assessed["eligibility"]["permit"]["required"] is False
    company = _job(
        "Remote contractor for a Philippines-based company. No residency requirement.",
        geography="Remote",
    )
    assert "residency_required" not in international_blockers(company, facts=_US_PROFILE)


def test_worker_location_still_blocks_when_it_is_mandatory() -> None:
    india = _job("Research assistants based in India.", geography="Remote")
    assert non_us_location_required(india) is True
    assert "residency_required" in international_blockers(india, facts=_US_PROFILE)
    korea = _job(
        "English-speaking Image Quality Evaluators based in South Korea.",
        geography="Remote",
    )
    assert non_us_location_required(korea) is True
    assert "residency_required" in international_blockers(korea, facts=_POPULATED_PROFILE)
    hyphenated = _job(
        "Looking for Philippines-based candidates. Independent contractor. Remote.",
        geography="Remote",
    )
    assert "residency_required" in international_blockers(hyphenated, facts=_US_PROFILE)
    trailing = _job(
        "Contractors who are Philippines-based. Remote administrative support.",
        geography="Remote",
    )
    assert "residency_required" in international_blockers(trailing, facts=_US_PROFILE)


def test_visa_and_permit_kinds_do_not_substitute_for_each_other() -> None:
    visa = "Remote CRM support. Must hold a valid UAE visa."
    work = "Remote CRM support. Work permit for Germany required."
    assert "permit_required" in international_blockers(
        _job(visa),
        facts={"work_permits": ["United Arab Emirates"]},
    )
    assert "permit_required" not in international_blockers(
        _job(visa),
        facts={"visas": ["UAE"]},
    )
    assert "permit_required" in international_blockers(
        _job(work),
        facts={"visas": [{"country": "Germany", "kind": "visa"}]},
    )
    assert "permit_required" not in international_blockers(
        _job(work),
        facts={"work_permits": [{"country": "Germany", "kind": "work"}]},
    )


def test_audience_native_speakers_are_not_a_worker_requirement() -> None:
    audience = (
        "Remote contractor CRM email support for native English speakers. "
        "No upfront fee. Work from anywhere."
    )
    assert "native_fluency_required" not in international_blockers(_job(audience), facts=_US_PROFILE)
    worker = "Remote contractor. Native English speaker required. No upfront fee."
    assert "native_fluency_required" in international_blockers(_job(worker), facts=_US_PROFILE)
    plural = "Remote contractor. Native English speakers required."
    assert "native_fluency_required" in international_blockers(_job(plural), facts=_US_PROFILE)


def test_native_fluency_is_never_claimed_for_a_tested_language() -> None:
    assessed = assess_international_match(
        _job("Remote B2B CRM support. Native French speaker required. Work from anywhere."),
        facts=_US_PROFILE,
    )
    assert "native_fluency_required" in assessed["blockers"]
    assert assessed["language_support"] == "not_native_fluency"
    assert assessed["language_support_label"] == ""
    assert assessed["native_fluency_claimed"] is False
    assert assessed["native_speaker_capability"] is False
    assert assessed["ai_translation_is_native_fluency"] is False
    assert assessed["tested_languages"][0]["label"] == "AI-assisted translation"
    assert "native speaker" not in assessed["tested_languages"][0]["label"].lower()
