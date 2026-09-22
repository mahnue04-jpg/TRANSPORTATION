"""Discovery precision: no weak-token false positives; keep safe QUALIFIED paths."""
from __future__ import annotations

from app.core.nova.v3.capability_catalog import capability_fit, capability_matches
from app.core.nova.v3.live_qualification import (
    OUTCOME_NEEDS_OWNER_REVIEW,
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    qualify_live_job,
)


def _highlevel_product_designer() -> dict:
    return {
        "provider_id": "remoteok",
        "provider_identifier": "1136841",
        "title": "Lead Product Designer",
        "company_name": "HighLevel",
        "description": (
            "HighLevel is an AI-powered business operating system. Design product experiences, "
            "collaborate with engineers, and document SOP handoffs for design systems. "
            "Remote role. Compensation competitive. No membership fee."
        ),
        "source_url": "https://remoteOK.com/remote-jobs/remote-lead-product-designer-highlevel-1136841",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$120k-$160k",
        "job_type": "contract",
        "source_attribution": "RemoteOK",
        "publication_date": "2026-09-20T00:00:00",
    }


def _admin_contractor() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "admin-contract-1",
        "title": "Remote Administrative Support Contractor",
        "company_name": "Lakeview Ops LLC",
        "description": (
            "B2B vendor / independent contractor engagement. Administrative support including "
            "CRM data organization, document preparation, meeting summaries, calendar follow-ups, "
            "and reporting. AI tools allowed for drafting. Statement of work. No membership fee. "
            "No upfront fee. Agencies/vendors welcome."
        ),
        "source_url": "https://remotive.com/remote-jobs/lakeview-admin-contractor",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$45/hr",
        "job_type": "contract",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-21T00:00:00",
    }


def _spreadsheet_contractor() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "sheet-contract-1",
        "title": "Spreadsheet Analyst Contractor",
        "company_name": "Clearledger Partners",
        "description": (
            "Freelance contractor / business vendor welcome. Spreadsheet work: Excel and Google Sheets "
            "data cleaning, reconciliation spreadsheet, data transformation, and reporting dashboards. "
            "AI tools allowed for analysis support. Fixed-price project possible. No membership fee."
        ),
        "source_url": "https://remotive.com/remote-jobs/clearledger-spreadsheet",
        "geography": "Worldwide",
        "remote_status": "remote",
        "compensation_text": "$2,000 per project",
        "job_type": "freelance",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-21T00:00:00",
    }


def _w2_admin_employee() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "w2-admin-1",
        "title": "Remote Administrative Assistant",
        "company_name": "Staffing Co",
        "description": (
            "Full-time W-2 employee role with benefits and 401k. Administrative support, "
            "CRM notes, document preparation, and reporting for the internal team."
        ),
        "source_url": "https://remotive.com/remote-jobs/staffing-w2-admin",
        "geography": "USA",
        "remote_status": "remote",
        "compensation_text": "$55,000 salary",
        "job_type": "full_time",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-21T00:00:00",
    }


def _physical_onsite_role() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "onsite-wh-1",
        "title": "Warehouse Associate",
        "company_name": "Local Fulfillment Inc",
        "description": (
            "On-site warehouse associate. Must report in person daily. Physical labor, lifting, "
            "and shift work onsite. Full-time employee."
        ),
        "source_url": "https://remotive.com/remote-jobs/local-warehouse",
        "geography": "Dallas, TX",
        "remote_status": "on-site",
        "compensation_text": "$18/hr",
        "job_type": "full_time",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-21T00:00:00",
    }


def _licensed_clinical_role() -> dict:
    return {
        "provider_id": "remotive",
        "provider_identifier": "rn-1",
        "title": "Registered Nurse",
        "company_name": "CareNet Health",
        "description": (
            "Remote clinical triage RN. Active nursing license / RN license required. "
            "Medical diagnosis support and patient care judgments."
        ),
        "source_url": "https://remotive.com/remote-jobs/carenet-rn",
        "geography": "USA",
        "remote_status": "remote",
        "compensation_text": "$40/hr",
        "job_type": "contract",
        "source_attribution": "Remotive",
        "publication_date": "2026-09-21T00:00:00",
    }


def test_product_designer_sop_never_qualifies():
    text = (
        "Lead Product Designer. Document SOP handoffs for design systems. "
        "Collaborate with engineers on product UX."
    )
    fit = capability_fit(text, title="Lead Product Designer")
    assert fit["fit"] is False
    assert not any(row["capability_id"] == "administrative_operations" for row in fit["capabilities"])
    matches = capability_matches(text, title="Lead Product Designer")
    assert all(row["capability_id"] != "administrative_operations" for row in matches)

    qual = qualify_live_job(_highlevel_product_designer())
    assert qual["qualification_status"] in {OUTCOME_NOT_QUALIFIED, OUTCOME_NEEDS_OWNER_REVIEW}
    assert qual["qualification_status"] != OUTCOME_QUALIFIED


def test_weak_sop_token_alone_does_not_match_admin_capability():
    matches = capability_matches("Please update the SOP tomorrow.", title="General Task")
    assert all(row["capability_id"] != "administrative_operations" for row in matches)
    fit = capability_fit("Please update the SOP tomorrow.", title="General Task")
    assert fit["fit"] is False


def test_admin_contractor_with_crm_docs_reporting_can_qualify():
    qual = qualify_live_job(_admin_contractor())
    assert qual["qualification_status"] == OUTCOME_QUALIFIED
    assert qual["capability_fit"] is True
    caps = {row["capability_id"] for row in (qual.get("matched_capabilities") or [])}
    assert "administrative_operations" in caps or qual.get("capability_fit")


def test_spreadsheet_contractor_cleanup_reporting_can_qualify():
    qual = qualify_live_job(_spreadsheet_contractor())
    assert qual["qualification_status"] == OUTCOME_QUALIFIED
    assert qual["capability_fit"] is True


def test_w2_employee_admin_not_qualified():
    qual = qualify_live_job(_w2_admin_employee())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "employee_w2_staff_role" in (qual.get("blockers") or [])


def test_physical_onsite_role_not_qualified():
    qual = qualify_live_job(_physical_onsite_role())
    assert qual["qualification_status"] == OUTCOME_NOT_QUALIFIED


def test_concrete_email_crm_report_phrases_match_admin_capability():
    text = (
        "Prepare email drafts, organize CRM notes, and summarize reports. "
        "Email writing, CRM, reporting."
    )
    matches = capability_matches(text, title="Approval gate role")
    ids = {row["capability_id"] for row in matches}
    assert "administrative_operations" in ids
    fit = capability_fit(text, title="Approval gate role")
    assert fit["fit"] is True
    strong = matches[0]["strong_matched_terms"]
    assert any(" " in term for term in strong)


def test_weekly_reporting_phrase_is_strong_not_weak_token_alone():
    assert capability_fit("Need reporting.", title="Ops helper")["fit"] is False
    assert capability_fit(
        "Remote weekly reporting for the operations team with spreadsheet cleanup.",
        title="Reporting contractor",
    )["fit"] is True
