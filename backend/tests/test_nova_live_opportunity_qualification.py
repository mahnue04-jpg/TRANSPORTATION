"""Regression tests for Nova live-opportunity risk/fit qualification.

Uses fixtures only — no external scrape, submit, pay, or account creation.
"""
from __future__ import annotations

import pytest

from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    apply_qualification,
    qualify_and_rank_live_jobs,
    qualify_live_job,
)


def _coalition_office_assistant() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "coalition-roa",
        "title": "Remote Office Assistant",
        "company_name": "Coalition Technologies",
        "description": (
            "Full-time staff position. Join our team as an employee with benefits package "
            "and 401k. W-2 employment. Office assistant duties, schedules, and reporting."
        ),
        "source_url": "https://remotive.com/remote-jobs/coalition-remote-office-assistant",
        "geography": "USA",
        "remote_status": "remote",
        "compensation_text": "$40,000 - $50,000",
        "job_type": "full_time",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-18T00:00:00",
    }


def _iapwe_freelance_writer() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "iapwe-writer",
        "title": "Freelance Writer",
        "company_name": "IAPWE",
        "description": (
            "Freelance writing opportunities for members. Paid membership required to access "
            "assignments. Become a member and pay annual dues before submitting work. "
            "AI writing tools policy is not clearly stated."
        ),
        "source_url": "https://remotive.com/remote-jobs/iapwe-freelance-writer",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": None,
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-19T00:00:00",
    }


def _iapwe_production_payment_access() -> dict:
    """Production-shaped IAPWE listing that previously auto-qualified incorrectly."""
    return {
        "provider_id": "remotive",
        "provider_identifier": "1185979",
        "title": "Freelance Writer",
        "company_name": "IAPWE",
        "description": (
            "Our organization is seeking content writers to create articles and blog posts on a "
            "variety of topics. The rate of pay is $20 per 100 words (this comes out to approximately "
            "$100 per article or $50 per hour). Requirements: Microsoft Word or Open Office, reliable "
            "internet, meet deadlines. Note: Applicants to this job signaled that accessing some "
            "writing tasks may require payment."
        ),
        "source_url": "https://remotive.com/remote-jobs/writing/freelance-writer-1185979",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$50-$75 /hour",
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-04T16:53:29",
    }


def _ateam_individual_specialist() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "1919266",
        "title": "Senior Independent AI Engineer / Architect",
        "company_name": "A.Team",
        "description": (
            "A.Team is an invite-only network of senior AI engineers, ML engineers, and AI architects "
            "building production AI systems. People who have already shipped. Tell us what you've built. "
            "Typical rates: $120-$170/hr. You keep 100% of your rate. Apply at build.a.team/apply-ai. "
            "No membership fee."
        ),
        "source_url": (
            "https://remotive.com/remote-jobs/software-development/"
            "senior-independent-ai-engineer-architect-1919266"
        ),
        "geography": "Americas, Europe, Israel",
        "remote_status": "remote",
        "compensation_text": "$120 - $170 /hour",
        "job_type": "contract",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-16T10:10:53",
    }


def _imerit_human_evaluator() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "2091126",
        "title": "AI Response Evaluator",
        "company_name": "iMerit Technology",
        "description": (
            "iMerit is looking for detail oriented analysts to evaluate and rank AI generated responses "
            "to image based prompts. You will judge answers on accuracy, relevance, clarity, and safety, "
            "then explain your reasoning in writing. Rate and rank responses against defined quality "
            "criteria. Compare multiple answers and explain why one wins. Independent contractor "
            "engagement. No membership fee."
        ),
        "source_url": (
            "https://remotive.com/remote-jobs/artificial-intelligence/ai-response-evaluator-2091126"
        ),
        "geography": "France, Japan, Turkey, Vietnam, Mexico, Norway",
        "remote_status": "remote",
        "compensation_text": "$10K-$20K",
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-11T06:49:00",
    }


def _ambiguous_fee_or_vendor_policy() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "ambiguous-fee-1",
        "title": "Remote Research Documentation Project",
        "company_name": "Harbor Ops LLC",
        "description": (
            "Freelance research and documentation support. Possible membership options may apply "
            "depending on platform access. Compensation $40/hr. ChatGPT and AI-assisted drafting "
            "may be discussed with the editor."
        ),
        "source_url": "https://remotive.com/remote-jobs/harbor-ops-research",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$40/hr",
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-18T00:00:00",
    }


def _clean_b2b_project() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "b2b-data-1",
        "title": "B2B Data Reporting Project",
        "company_name": "Northwind Analytics LLC",
        "description": (
            "Vendor / B2B project-based engagement. Independent contractor or business vendor "
            "welcome. Deliverables: research, data analysis, and reporting documentation. "
            "AI tools allowed for drafting and analysis. Clear statement of work. "
            "No membership fee. No upfront fee."
        ),
        "source_url": "https://remotive.com/remote-jobs/northwind-b2b-reporting",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$2,500 per project",
        "job_type": "contract",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-19T12:00:00",
    }


def _freelance_unclear_ai() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "freelance-ai-unclear",
        "title": "Freelance Content Writer",
        "company_name": "Content Studio",
        "description": (
            "Freelance independent contractor writing role. ChatGPT and AI-assisted drafting "
            "may be discussed with the editor. Rate $45/hr. No membership fee."
        ),
        "source_url": "https://remotive.com/remote-jobs/content-studio-writer",
        "geography": "USA",
        "remote_status": "remote",
        "compensation_text": "$45/hr",
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-17T00:00:00",
    }


def _ai_prohibited_writer() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "no-ai-writer",
        "title": "Freelance Technical Writer",
        "company_name": "Pure Prose Co",
        "description": (
            "Freelance contractor. Documentation and content writing. "
            "AI-assisted work is not allowed. Do not use AI or ChatGPT. "
            "Compensation $60/hr. No fees."
        ),
        "source_url": "https://remotive.com/remote-jobs/pure-prose-writer",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$60/hr",
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-16T00:00:00",
    }


def _missing_comp_unclear_source() -> dict:
    return {
        "provider_id": "unknown_board",
        "provider_identifier": "shady-1",
        "title": "Mystery Gig",
        "company_name": "Mystery LLC",
        "description": "Do some work somehow.",
        "source_url": "ftp://not-https.example/listing",
        "geography": "Remote",
        "remote_status": "remote",
        "compensation_text": None,
        "job_type": None,
        "source_attribution": "unknown",
        "publication_date": "2026-09-15T00:00:00",
    }


def test_coalition_style_employee_job_not_qualified():
    qual = qualify_live_job(_coalition_office_assistant())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert qual["work_type"] == "employee"
    assert qual["risk_level"] == "HIGH"
    assert "employee_w2_staff_role" in qual["blockers"]
    assert qual["auto_prepare_allowed"] is False
    assert qual["external_submission"] is False
    assert qual["financial_execution"] is False


def test_iapwe_style_paid_membership_not_qualified():
    qual = qualify_live_job(_iapwe_freelance_writer())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert qual["fee_required"] == "yes"
    assert "upfront_fee_or_paid_membership" in qual["blockers"]
    assert qual["auto_prepare_allowed"] is False


def test_iapwe_production_payment_access_not_qualified():
    qual = qualify_live_job(_iapwe_production_payment_access())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert qual["fee_required"] == "yes"
    assert "upfront_fee_or_paid_membership" in qual["blockers"]
    assert qual["auto_prepare_allowed"] is False


def test_ateam_individual_specialist_not_qualified():
    qual = qualify_live_job(_ateam_individual_specialist())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "individual_specialist_or_talent_network" in qual["blockers"]
    assert qual["auto_prepare_allowed"] is False


def test_imerit_human_evaluator_not_qualified():
    qual = qualify_live_job(_imerit_human_evaluator())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "human_evaluator_or_annotation_role" in qual["blockers"]
    assert qual["auto_prepare_allowed"] is False


def test_ambiguous_fee_or_vendor_policy_needs_owner_review():
    qual = qualify_live_job(_ambiguous_fee_or_vendor_policy())
    assert qual["qualification_status"] == OUTCOME_NEEDS_OWNER_REVIEW
    assert qual["auto_prepare_allowed"] is False
    assert qual["fee_required"] in {"unclear", "yes"} or "unclear" in (qual.get("owner_review_reason") or "").lower() or "vendor" in (qual.get("owner_review_reason") or "").lower() or "ai" in (qual.get("owner_review_reason") or "").lower()


def test_freelance_unclear_ai_needs_owner_review():
    qual = qualify_live_job(_freelance_unclear_ai())
    assert qual["qualification_status"] == OUTCOME_NEEDS_OWNER_REVIEW
    assert qual["ai_policy"] == "unclear"
    assert qual["fee_required"] == "no"
    assert qual["auto_prepare_allowed"] is False


def test_clean_b2b_project_qualified():
    qual = qualify_live_job(_clean_b2b_project())
    assert qual["qualification_status"] == OUTCOME_QUALIFIED
    assert qual["work_type"] == "B2B"
    assert qual["fee_required"] == "no"
    assert qual["ai_policy"] == "allowed"
    assert qual["risk_level"] == "LOW"
    assert qual["auto_prepare_allowed"] is True


def test_missing_compensation_unclear_source_not_qualified():
    qual = qualify_live_job(_missing_comp_unclear_source())
    assert qual["qualification_status"] in {OUTCOME_NOT_QUALIFIED, OUTCOME_NEEDS_OWNER_REVIEW}
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "source_legitimacy_low" in qual["blockers"]


def test_explicit_ai_prohibition_not_qualified():
    qual = qualify_live_job(_ai_prohibited_writer())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert qual["ai_policy"] == "prohibited"
    assert "ai_assisted_work_prohibited" in qual["blockers"]


def test_ranking_prioritizes_b2b_over_employee_and_fees():
    ranked = qualify_and_rank_live_jobs(
        "data reporting freelance project",
        [
            _coalition_office_assistant(),
            _iapwe_freelance_writer(),
            _clean_b2b_project(),
            _freelance_unclear_ai(),
        ],
    )
    assert ranked[0]["title"] == "B2B Data Reporting Project"
    assert ranked[0]["qualification_status"] == OUTCOME_QUALIFIED
    statuses = [row["qualification_status"] for row in ranked]
    assert OUTCOME_NOT_QUALIFIED in statuses


def test_prepare_auto_only_qualified_retains_not_qualified(monkeypatch):
    from app.core.nova.v3.kernel import NovaV3Kernel
    from app.core.nova.v3 import live_discovery

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "jobs": [
                    {
                        "id": "coalition",
                        "url": _coalition_office_assistant()["source_url"],
                        "title": _coalition_office_assistant()["title"],
                        "company_name": _coalition_office_assistant()["company_name"],
                        "description": _coalition_office_assistant()["description"],
                        "candidate_required_location": "USA",
                        "salary": "$40,000 - $50,000",
                        "job_type": "full_time",
                        "publication_date": "2026-09-18T00:00:00",
                    },
                    {
                        "id": "iapwe",
                        "url": _iapwe_freelance_writer()["source_url"],
                        "title": _iapwe_freelance_writer()["title"],
                        "company_name": _iapwe_freelance_writer()["company_name"],
                        "description": _iapwe_freelance_writer()["description"],
                        "candidate_required_location": "Worldwide",
                        "salary": None,
                        "job_type": "freelance",
                        "publication_date": "2026-09-19T00:00:00",
                    },
                    {
                        "id": "b2b",
                        "url": _clean_b2b_project()["source_url"],
                        "title": _clean_b2b_project()["title"],
                        "company_name": _clean_b2b_project()["company_name"],
                        "description": _clean_b2b_project()["description"],
                        "candidate_required_location": "Worldwide",
                        "salary": "$2,500 per project",
                        "job_type": "contract",
                        "publication_date": "2026-09-19T12:00:00",
                    },
                ]
            }

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return _Resp()

    live_discovery._cache.clear()
    monkeypatch.setattr(live_discovery, "live_flags", lambda: {"LIVE_DISCOVERY_ENABLED": True})
    monkeypatch.setattr(live_discovery.httpx, "Client", _Client)

    kernel = NovaV3Kernel()
    monkeypatch.setattr(
        "app.core.nova.v3.kernel.live_flags",
        lambda: {
            "LIVE_DISCOVERY_ENABLED": True,
            "EXTERNAL_SUBMISSION_ENABLED": False,
        },
    )

    raw = live_discovery.search_remote_jobs("reporting freelance project", limit=10)
    ranked = qualify_and_rank_live_jobs("reporting freelance project", raw)
    saved = kernel.ingest_live_jobs(ranked, organization_id="org-owner", owner_user_id="owner-1")

    prepared_ids = []
    skipped = []
    held = []
    for opportunity in saved["created"]:
        status = opportunity.get("qualification_status")
        if status == OUTCOME_NOT_QUALIFIED:
            skipped.append(opportunity["opportunity_id"])
            continue
        if status == OUTCOME_NEEDS_OWNER_REVIEW:
            held.append(opportunity["opportunity_id"])
            continue
        if status == OUTCOME_QUALIFIED:
            proposal = kernel.prepare_proposal(
                opportunity["opportunity_id"],
                organization_id="org-owner",
                owner_user_id="owner-1",
            )
            prepared_ids.append(proposal.proposal_id)

    assert len(prepared_ids) == 1
    assert len(skipped) >= 2  # Coalition + IAPWE retained but not prepared
    assert all(row.get("live_discovery") for row in saved["created"])
    not_qualified_rows = [
        row for row in saved["created"] if row.get("qualification_status") == OUTCOME_NOT_QUALIFIED
    ]
    assert len(not_qualified_rows) >= 2
    with pytest.raises(Exception) as exc:
        kernel.prepare_proposal(
            not_qualified_rows[0]["opportunity_id"],
            organization_id="org-owner",
            owner_user_id="owner-1",
        )
    assert getattr(exc.value, "code", None) == "NOT_QUALIFIED"


def test_no_external_submission_or_payment_on_qualification(monkeypatch):
    from app.core.nova.v3.kernel import NovaV3Kernel
    from app.core.nova.v3.errors import V3Error

    kernel = NovaV3Kernel()
    monkeypatch.setattr(
        "app.core.nova.v3.kernel.live_flags",
        lambda: {
            "LIVE_DISCOVERY_ENABLED": True,
            "EXTERNAL_SUBMISSION_ENABLED": False,
        },
    )
    job = apply_qualification(_clean_b2b_project())
    saved = kernel.ingest_live_jobs([job], organization_id="org-owner", owner_user_id="owner-1")
    opp = saved["created"][0]
    assert opp["live_qualification"]["external_submission"] is False
    assert opp["live_qualification"]["financial_execution"] is False
    proposal = kernel.prepare_proposal(
        opp["opportunity_id"], organization_id="org-owner", owner_user_id="owner-1"
    )
    with pytest.raises(V3Error) as exc:
        kernel.live_submit(
            proposal.proposal_id,
            organization_id="org-owner",
            owner_user_id="owner-1",
            approval_id="none",
        )
    assert exc.value.code == "LIVE_DISABLED"


def test_simulated_records_remain_separate_from_live(monkeypatch):
    from app.core.nova.v3.kernel import NovaV3Kernel

    kernel = NovaV3Kernel()
    monkeypatch.setattr(
        "app.core.nova.v3.kernel.live_flags",
        lambda: {"LIVE_DISCOVERY_ENABLED": True},
    )
    synthetic = kernel.ingest("synthetic_job_board", organization_id="org-owner", owner_user_id="owner-1")
    live = kernel.ingest_live_jobs(
        [apply_qualification(_clean_b2b_project())],
        organization_id="org-owner",
        owner_user_id="owner-1",
    )
    assert synthetic["created"]
    assert all(row["provenance"].get("synthetic") is True for row in synthetic["created"])
    assert all(row["live_discovery"] is False for row in synthetic["created"])
    assert live["created"][0]["live_discovery"] is True
    assert live["created"][0]["provenance"]["synthetic"] is False
    assert live["created"][0]["qualification_status"] == OUTCOME_QUALIFIED
