"""Owner-facing eligibility explanations on Work and Revenue surfaces.

The country match itself stays in international_match. These checks cover the
sentences and the AI-assisted translation label on search results, saved leads,
preparation drafts, and owner-review API responses.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.v3.kernel import NovaV3Kernel
from app.core.nova.v3.live_qualification import qualify_and_rank_live_jobs
from app.core.nova.v3.models import Opportunity
from app.core.nova.work_revenue.capability_first_discovery import score_discovery_candidate
from app.core.nova.work_revenue.international_match import (
    AI_ASSISTED_TRANSLATION_LABEL,
    assess_international_match,
)
from app.core.nova.work_revenue.materials import generate_drafts
from app.core.nova.work_revenue.qualifier import qualify_opportunity
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app

_US_PROFILE = {
    "residency": "United States",
    "citizenship": "United States",
    "work_permits": ["United States"],
}
_QUERY = "Worldwide remote B2B contractor for customer operations, CRM, and administrative support"


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _job(description: str, **extra: object) -> dict:
    job = {
        "title": "Remote Operations Assistant",
        "description": description,
        "geography": "Worldwide",
        "remote_status": "remote",
        "company_name": "Explanation Co",
        "provider_identifier": extra.pop("provider_identifier", "explanation"),
        "search_family": "administrative_operations",
    }
    job.update(extra)
    return job


def _explanations(description: str, facts: dict | None = None) -> dict:
    return assess_international_match(_job(description), facts=facts if facts is not None else _US_PROFILE)


def test_owner_explanations_name_the_country_and_fail_closed() -> None:
    uae = _explanations("Remote B2B CRM support. Must reside in the UAE. No upfront fee.")
    assert uae["eligibility_decision"] == "fail_closed"
    assert any(
        "Mandatory residency: United Arab Emirates." in line and "fails closed" in line
        for line in uae["eligibility_explanations"]
    )
    assert all("meets this requirement" not in line for line in uae["eligibility_explanations"])

    several = _explanations(
        "Remote B2B administrative support. Must reside in the United States, Canada, or the United Kingdom."
    )
    joined = " ".join(several["eligibility_explanations"])
    assert "United States" in joined and "Canada" in joined and "United Kingdom" in joined
    assert "meets this requirement" in joined
    assert several["eligibility_decision"] == "clear"

    france = _explanations(
        "Remote B2B administrative support. Must reside in the United States, Canada, or the United Kingdom.",
        {"residency": "France"},
    )
    assert france["eligibility_decision"] == "fail_closed"
    assert any("fails closed" in line for line in france["eligibility_explanations"])

    unread = _explanations("Remote CRM support. Residency required. Citizenship required. Work permit required.")
    unread_text = " ".join(unread["eligibility_explanations"])
    assert unread["eligibility_decision"] == "fail_closed"
    assert "Mandatory residency: the required country or region could not be read, so this fails closed." in unread_text
    assert "Mandatory citizenship: the required country or region could not be read, so this fails closed." in unread_text
    assert "Mandatory permit: the required country or permit type could not be read, so this fails closed." in unread_text


def test_permit_kind_and_preference_are_explained_without_a_fluency_claim() -> None:
    permit = _explanations("Remote CRM support. Work permit for Germany required. No upfront fee.")
    permit_text = " ".join(permit["eligibility_explanations"])
    assert "Mandatory work permit: Germany." in permit_text
    assert "fails closed" in permit_text
    assert "meets this requirement" not in permit_text

    visa = _explanations(
        "Remote CRM support. Must hold a valid UAE visa.",
        {"work_permits": ["United Arab Emirates"]},
    )
    visa_text = " ".join(visa["eligibility_explanations"])
    assert "Mandatory visa: United Arab Emirates." in visa_text
    assert visa["eligibility_decision"] == "fail_closed"

    held = _explanations("Remote CRM support. Must hold a valid UAE visa.", {"visas": ["UAE"]})
    assert held["eligibility_decision"] == "clear"
    assert any("meets this requirement" in line for line in held["eligibility_explanations"])

    preferred = _explanations(
        "Remote Arabic customer email. Location preference: United Arab Emirates. "
        "Prefer candidates based in the UAE. UAE residency preferred. "
        "Spanish preferred. No residency requirement. No upfront fee."
    )
    preferred_text = " ".join(preferred["eligibility_explanations"])
    assert preferred["eligibility_decision"] == "clear"
    assert preferred["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert "Preferred residency: United Arab Emirates. A preference is not a blocker." in preferred_text
    assert "Preferred language: Spanish. A preference is not a blocker." in preferred_text
    assert "fails closed" not in preferred_text
    assert preferred["native_fluency_claimed"] is False
    assert "native speaker" not in preferred["language_support_label"].lower()

    client_country = _explanations(
        "Remote B2B administrative support for a company based in Germany. "
        "Customers located in Dubai. English customer email. "
        "Visa sponsorship available. No residency requirement. No upfront fee.",
        {},
    )
    client_text = " ".join(client_country["eligibility_explanations"])
    assert "Mandatory residency" not in client_text
    assert "Mandatory work permit" not in client_text
    assert "Mandatory visa" not in client_text
    assert client_country["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert "This is not native fluency." in client_text


def test_language_rules_mark_ai_assistance_and_refuse_untested_or_native_claims() -> None:
    either = _explanations("Remote B2B administrative support. French or German required.")
    either_text = " ".join(either["eligibility_explanations"])
    assert either["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert "Mandatory language: French or German." in either_text
    assert "French is covered as AI-assisted translation." in either_text
    assert "German is covered" not in either_text
    assert "native fluency" in either_text
    assert either["native_speaker_capability"] is False

    german = _explanations("Remote B2B administrative support. German fluency required.")
    german_text = " ".join(german["eligibility_explanations"])
    assert german["eligibility_decision"] == "fail_closed"
    assert german["language_support_label"] == ""
    assert "Mandatory language: German." in german_text
    assert "No fluency is claimed." in german_text
    assert "Labeled AI-assisted translation" not in german_text

    native = _explanations("Remote B2B CRM support. Native French speaker required. Work from anywhere.")
    assert native["language_support_label"] == ""
    assert native["native_fluency_claimed"] is False
    assert any(
        line == (
            "Mandatory native fluency. AI-assisted translation does not satisfy native fluency, "
            "and no fluency is claimed."
        )
        for line in native["eligibility_explanations"]
    )
    assert "native speaker" not in " ".join(native["eligibility_explanations"]).lower()


def test_search_results_carry_explanations_and_keep_lane_and_fee_controls() -> None:
    ranked = qualify_and_rank_live_jobs(
        _QUERY,
        [
            _job(
                "Remote Arabic customer email. Must reside in the UAE. No upfront fee.",
                provider_identifier="uae-search",
            ),
            _job(
                "Worldwide remote B2B contractor for administrative support and CRM updates. "
                "French customer email. Work from anywhere. No residency requirement. "
                "No certification required. No upfront fee. No on-site work.",
                provider_identifier="french-search",
            ),
            _job(
                "Remote B2B CRM support. Application fee required. Pay to apply.",
                provider_identifier="fee-search",
            ),
        ],
    )
    by_id = {row["provider_identifier"]: row for row in ranked}
    blocked = by_id["uae-search"]
    assert blocked["eligibility_decision"] == "fail_closed"
    assert blocked["live_qualification"]["eligibility_decision"] == "fail_closed"
    assert any("United Arab Emirates" in line for line in blocked["eligibility_explanations"])
    assert "residency_required" in blocked["live_qualification"]["blockers"]
    assert any("United Arab Emirates" in reason for reason in blocked["live_qualification"]["reasons"])
    assert blocked["live_qualification"]["qualification_status"] == "NOT_QUALIFIED"

    matched = by_id["french-search"]
    assert matched["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert matched["live_qualification"]["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert matched["native_fluency_claimed"] is False
    assert matched["eligibility_decision"] == "clear"
    assert any("Labeled AI-assisted translation" in line for line in matched["eligibility_explanations"])

    fee = by_id["fee-search"]
    assert fee["discovery_band"] == "REJECT"
    assert "upfront_fee_required" in fee["live_qualification"]["blockers"]

    admin = score_discovery_candidate(
        _job(
            "Remote virtual assistant for inbox, calendar, and administrative support. No upfront fee.",
            title="Virtual Assistant",
        ),
        query="remote administrative support contractor",
    )
    research = score_discovery_candidate(
        _job(
            "Remote 1099 research assistant for internet research and competitor research. No upfront fee.",
            title="Research Assistant",
            search_family="research_analysis",
        ),
        query="remote research assistant contractor",
    )
    crm = score_discovery_candidate(
        _job(
            "Remote CRM support for contact updates and pipeline notes. No upfront fee.",
            title="CRM Support Specialist",
            search_family="crm_support",
        ),
        query="remote CRM support contractor",
    )
    for row in (admin, research, crm):
        assert row["eligibility_decision"] == "clear"
        assert row["residency_blocked"] is False
        assert row["permit_blocked"] is False
        assert row["upfront_fee_blocked"] is False


def test_saved_lead_preparation_and_kernel_review_show_the_same_decision() -> None:
    blocked = qualify_opportunity(
        {
            "opportunity_title": "Remote Operations Assistant",
            "company_name": "Blocked Co",
            "description": "Remote B2B CRM support. Must reside in the UAE. French customer email. No upfront fee.",
            "skills_required": ["crm", "email"],
            "physical_presence_required": "false",
            "compensation_type": "hourly",
            "compensation_amount": 40,
            "remote_status": "remote",
        }
    )
    assert blocked["outcome"] == "NOT_SUITABLE"
    assert blocked["eligibility_decision"] == "fail_closed"
    assert blocked["auto_prepare_allowed"] is False
    assert blocked["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert blocked["native_fluency_claimed"] is False
    assert any("United Arab Emirates" in line and "fails closed" in line for line in blocked["eligibility_explanations"])
    assert blocked["reasons"][0].startswith("Mandatory residency: United Arab Emirates.")

    clear = qualify_opportunity(
        {
            "opportunity_title": "Remote Operations Assistant",
            "company_name": "Clear Co",
            "description": (
                "Fully remote email drafting and CRM notes. French customer email. "
                "No residency requirement. No upfront fee."
            ),
            "skills_required": ["email", "crm"],
            "physical_presence_required": "false",
            "compensation_type": "hourly",
            "compensation_amount": 40,
            "remote_status": "remote",
        }
    )
    assert clear["outcome"] != "NOT_SUITABLE"
    assert clear["eligibility_decision"] == "clear"
    assert clear["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL

    drafts = generate_drafts(
        {
            "opportunity_title": "Remote Operations Assistant",
            "company_name": "Clear Co",
            "description": (
                "Fully remote email drafting and CRM notes. French customer email. "
                "No residency requirement. No upfront fee."
            ),
        }
    )
    cover = next(item["body"] for item in drafts if item["kind"] == "cover_letter")
    proposal = next(item["body"] for item in drafts if item["kind"] == "proposal")
    assert "Language support label: AI-assisted translation." in cover
    assert "Language support label: AI-assisted translation." in proposal
    assert "No native fluency is claimed." in cover
    assert "native speaker" not in cover.lower()

    kernel = NovaV3Kernel()
    opportunity = Opportunity(
        opportunity_id="V3OPP00001",
        organization_id="org-eligibility",
        owner_user_id="owner-eligibility",
        source_kind="job_board",
        provider_id="live_job_source",
        provider_identifier="french-review",
        title="Remote Operations Assistant",
        company_name="Clear Co",
        description="French customer email. No residency requirement.",
        source_url="https://example.com/jobs/french",
        source_evidence="test",
        fetched_at=datetime.now(timezone.utc),
        expires_at=None,
        compensation_amount=None,
        compensation_type="unknown",
        currency="USD",
        required_qualifications=[],
        geography="Worldwide",
        remote_status="remote",
        terms_restrictions="owner review required",
        login_required=False,
        captcha_required=False,
        human_verification_required=False,
        rate_limited=False,
        fingerprint="eligibility-french",
        provenance={
            "live": True,
            "live_qualification": {
                "qualification_status": "QUALIFIED",
                "language_support_label": AI_ASSISTED_TRANSLATION_LABEL,
                "eligibility_explanations": clear["eligibility_explanations"],
                "eligibility_decision": "clear",
                "native_fluency_claimed": False,
            },
        },
        classification="NOVA_CAN_PERFORM",
        score=1,
    )
    kernel.opportunities[opportunity.opportunity_id] = opportunity
    listed = kernel.opportunity_out(opportunity)
    assert listed["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert listed["eligibility_decision"] == "clear"
    assert listed["native_fluency_claimed"] is False
    proposal_row = kernel.prepare_proposal(
        opportunity.opportunity_id,
        organization_id="org-eligibility",
        owner_user_id="owner-eligibility",
    )
    assert "Language support label: AI-assisted translation." in proposal_row.body
    assert "No native fluency is claimed." in proposal_row.body
    assert proposal_row.externally_submitted is False


def test_screens_render_the_label_on_search_saved_leads_and_owner_review() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    script = (root / "static" / "nova-work" / "work.js").read_text(encoding="utf-8")
    style = (root / "static" / "nova-work" / "work.css").read_text(encoding="utf-8")
    assert "function eligibilityMarkup" in script
    assert script.count("eligibilityMarkup(") >= 4
    assert "language-support-label" in script
    assert "language-support-label" in style
    live = script.split("function liveJobItem", 1)[1].split("function setSignedIn", 1)[0]
    saved = script.split("function oppItem", 1)[1].split("function applicationItem", 1)[0]
    review = script.split("function applicationItem", 1)[1].split("function markActiveFilter", 1)[0]
    detail = script.split("async function loadDetail", 1)[1].split("async function refresh", 1)[0]
    assert "eligibilityMarkup(opp)" in live
    assert "eligibilityMarkup(row)" in saved
    assert "eligibilityMarkup(row)" in review
    assert "eligibilityMarkup(opp)" in detail


def test_saved_lead_and_owner_review_api_show_explanations(client: TestClient) -> None:
    headers = _headers(client)
    blocked = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "UAE Blocker Explanations Co",
            "opportunity_title": "Remote CRM support contractor",
            "description": "Remote B2B CRM support. Must reside in the UAE. No upfront fee.",
            "location": "Worldwide",
            "remote_status": "remote",
            "engagement_type": "contract",
            "compensation_type": "hourly",
            "compensation_amount": 40,
            "compensation_period": "hour",
            "currency": "USD",
            "requirements": "CRM updates.",
            "skills_required": ["crm"],
            "credentials_required": [],
            "physical_presence_required": "false",
        },
    )
    assert blocked.status_code == 200, blocked.text
    blocked_id = blocked.json()["opportunity_id"]
    qualified = client.post(f"/api/nova/work/opportunities/{blocked_id}/qualify", headers=headers)
    assert qualified.status_code == 200, qualified.text
    body = qualified.json()
    assert body["outcome"] == "NOT_SUITABLE"
    assert body["eligibility_decision"] == "fail_closed"
    assert body["native_fluency_claimed"] is False
    assert any("United Arab Emirates" in line and "fails closed" in line for line in body["eligibility_explanations"])
    saved = client.get(f"/api/nova/work/opportunities/{blocked_id}", headers=headers)
    assert saved.status_code == 200, saved.text
    saved_body = saved.json()
    assert saved_body["status"] == "NOT_QUALIFIED"
    assert saved_body["qualification"]["eligibility_decision"] == "fail_closed"
    assert any(
        "United Arab Emirates" in line
        for line in saved_body["qualification"]["eligibility_explanations"]
    )
    refused = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": blocked_id, "applicant_party": "AMICOR"},
    )
    assert refused.status_code == 400

    created = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "French Label Explanations Co",
            "opportunity_title": "Remote administrative support contractor",
            "description": (
                "Prepare email drafts, organize CRM notes, and summarize reports. Fully remote. "
                "French customer email. No residency requirement."
            ),
            "location": "Remote",
            "remote_status": "remote",
            "engagement_type": "contract",
            "compensation_type": "hourly",
            "compensation_amount": 40,
            "compensation_period": "hour",
            "currency": "USD",
            "requirements": "Email writing, CRM, reporting.",
            "skills_required": ["email", "crm", "reporting"],
            "credentials_required": [],
            "physical_presence_required": "false",
        },
    )
    assert created.status_code == 200, created.text
    opportunity_id = created.json()["opportunity_id"]
    clear = client.post(f"/api/nova/work/opportunities/{opportunity_id}/qualify", headers=headers)
    assert clear.status_code == 200, clear.text
    assert clear.json()["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert clear.json()["eligibility_decision"] == "clear"
    assert clear.json()["native_speaker_capability"] is False
    application = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": opportunity_id, "applicant_party": "AMICOR"},
    )
    assert application.status_code == 200, application.text
    prepared = application.json()
    assert prepared["approval_state"] == "DRAFT"
    assert prepared["externally_submitted"] is False
    assert prepared["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert prepared["eligibility_decision"] == "clear"
    assert prepared["native_fluency_claimed"] is False
    assert any("AI-assisted translation" in item["body"] for item in prepared["materials"])
    assert all("native speaker" not in item["body"].lower() for item in prepared["materials"])
    review = client.get(
        f"/api/nova/work/applications/{prepared['application_id']}/package-review",
        headers=headers,
    )
    assert review.status_code == 200, review.text
    assert review.json()["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert review.json()["eligibility_decision"] == "clear"
    assert review.json()["externally_submitted"] is False
    ready = client.post(
        f"/api/nova/work/applications/{prepared['application_id']}/ready-for-review",
        headers=headers,
    )
    assert ready.status_code == 200, ready.text
    owner_review = ready.json()
    assert owner_review["approval_state"] == "READY_FOR_OWNER_REVIEW"
    assert owner_review["language_support_label"] == AI_ASSISTED_TRANSLATION_LABEL
    assert any("Labeled AI-assisted translation" in line for line in owner_review["eligibility_explanations"])
    assert owner_review["approved_for_future_submission"] is False
    assert owner_review["externally_submitted"] is False
