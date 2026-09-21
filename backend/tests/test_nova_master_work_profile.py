"""Focused Master Work Profile readiness + persistence/readback regression tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.v3.live_qualification import (
    OUTCOME_NOT_QUALIFIED,
    OUTCOME_QUALIFIED,
    qualify_live_job,
)
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.materials import generate_drafts
from app.core.nova.work_revenue.models import NovaWorkBusinessFact
from app.core.nova.work_revenue.owner_facts import (
    FACT_DEFINITIONS,
    OWNER_APPROVED_SAFE_FACTS,
    OWNER_INPUT_REQUIRED,
    fact_catalog,
    system_verified_technology_capability,
)
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import SessionLocal, engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
WORK_JS = (ROOT / "static" / "nova-work" / "work.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    login = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def _put(client: TestClient, headers: dict[str, str], key: str, **payload):
    return client.put(f"/api/nova/work/owner-facts/{key}", headers=headers, json=payload)


def _by_id(body: dict) -> dict[str, dict]:
    return {row["fact_id"]: row for row in body["facts"]}


def test_owner_approved_safe_facts_persist_and_round_trip(client: TestClient) -> None:
    headers = _headers(client, "dispatcher@amicor.local")
    applied = client.post("/api/nova/work/owner-facts/apply-owner-approved", headers=headers)
    assert applied.status_code == 200, applied.text
    body = applied.json()
    assert body.get("owner_approved_facts_persisted")
    by_id = _by_id(body)
    for fact_id, expected in OWNER_APPROVED_SAFE_FACTS.items():
        assert by_id[fact_id]["value_status"] in {"PROVIDED", "VERIFIED", "NOT_APPLICABLE"}
        assert by_id[fact_id]["value_display"] == expected
    tech = by_id["technology_capability"]
    assert tech["value_status"] == "VERIFIED"
    assert tech["value_display"] == system_verified_technology_capability()
    assert "Research support" in tech["value_display"]
    # Still-open optional fields remain missing.
    for fact_id in ("dba", "certifications", "references", "financial_information", "tax_identifiers"):
        assert by_id[fact_id]["value_status"] == "MISSING"
        assert by_id[fact_id]["value_display"] == OWNER_INPUT_REQUIRED
    second = client.get("/api/nova/work/owner-facts", headers=headers)
    assert second.status_code == 200
    again = _by_id(second.json())
    assert again["legal_business_name"]["value_display"] == "Amicor Health, LLC"
    assert again["service_areas"]["value_display"] == OWNER_APPROVED_SAFE_FACTS["service_areas"]
    assert again["licenses"]["value_status"] == "NOT_APPLICABLE"
    assert again["insurance"]["value_display"] == "OWNER_SAYS_NOT_READY"
    assert again["w9_readiness"]["value_display"] == "w9_ready"
    assert again["banking_payment_readiness"]["value_display"] == "banking_ready"
    ready = second.json()["readiness"]
    assert ready["externally_ready"] is False
    assert ready["external_submission_enabled"] is False
    assert ready["financial_actions_enabled"] is False
    assert ready["missing_facts"] == 0
    assert ready["percentage_complete"] == 100


def test_apply_owner_approved_endpoint_is_idempotent(client: TestClient) -> None:
    headers = _headers(client, "dispatcher@amicor.local")
    first = client.post("/api/nova/work/owner-facts/apply-owner-approved", headers=headers)
    assert first.status_code == 200, first.text
    second = client.post("/api/nova/work/owner-facts/apply-owner-approved", headers=headers)
    assert second.status_code == 200
    assert second.json()["readiness"]["percentage_complete"] == first.json()["readiness"]["percentage_complete"]
    assert second.json().get("executes_externally") is False


def test_persisted_master_profile_survives_reload_and_org_wide_read(client: TestClient) -> None:
    """Regression: persisted owner facts must survive GET reload and cross-user org read."""
    writer = _headers(client, "dispatcher@amicor.local")
    reader = _headers(client, "admin@amicor.local")

    # Ensure approved baseline is in the org DB (MISSING-only; never overwrites).
    applied = client.post("/api/nova/work/owner-facts/apply-owner-approved", headers=writer)
    assert applied.status_code == 200, applied.text

    expected = {
        "legal_business_name": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["legal_business_name"]),
        "address": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["address"]),
        "business_email": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["business_email"]),
        "business_phone": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["business_phone"]),
        "authorized_signer": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["authorized_signer"]),
        "ownership": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["ownership"]),
        "service_areas": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["service_areas"]),
        "industries_served": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["industries_served"]),
        "relevant_experience": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["relevant_experience"]),
        "pricing": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["pricing"]),
        "rates": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["rates"]),
        "availability": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["availability"]),
        "workforce": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["workforce"]),
        "equipment": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["equipment"]),
        "licenses": ("NOT_APPLICABLE", "NOT_APPLICABLE"),
        "ai_use_disclosure_decision": ("PROVIDED", OWNER_APPROVED_SAFE_FACTS["ai_use_disclosure_decision"]),
        "subcontractor_disclosure_decision": (
            "PROVIDED",
            OWNER_APPROVED_SAFE_FACTS["subcontractor_disclosure_decision"],
        ),
        "w9_readiness": ("PROVIDED", "w9_ready"),
        "banking_payment_readiness": ("PROVIDED", "banking_ready"),
        "insurance": ("PROVIDED", "OWNER_SAYS_NOT_READY"),
    }

    # First GET (writer) and second GET (admin / org-wide) must both show persisted values.
    for headers in (writer, reader):
        for _ in range(2):  # reload must not revert to MISSING
            resp = client.get("/api/nova/work/owner-facts", headers=headers)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            by_id = _by_id(body)
            for fact_id, (status, value) in expected.items():
                assert by_id[fact_id]["value_status"] == status, fact_id
                assert by_id[fact_id]["value_display"] == value, fact_id
            assert by_id["technology_capability"]["value_status"] == "VERIFIED"
            ready = body["readiness"]
            assert ready["percentage_complete"] == 100
            assert ready["missing_facts"] == 0
            assert ready["external_submission_enabled"] is False
            assert ready["financial_actions_enabled"] is False
            assert ready["externally_ready"] is False

    # Empty MISSING placeholder rows must not wipe approved soft/persisted values.
    db = SessionLocal()
    try:
        org_id = None
        row = db.query(NovaWorkBusinessFact).filter(NovaWorkBusinessFact.fact_key == "legal_business_name").first()
        assert row is not None
        org_id = row.organization_id
        shell = NovaWorkBusinessFact(
            fact_record_id="NWBF-SHELLTEST001",
            organization_id=org_id,
            owner_user_id=row.owner_user_id,
            fact_key="dba",
            display_label="DBA / trade name",
            value_status="MISSING",
            value_display=OWNER_INPUT_REQUIRED,
        )
        db.add(shell)
        db.commit()
    finally:
        db.close()

    after = client.get("/api/nova/work/owner-facts", headers=reader)
    assert after.status_code == 200
    by_id = _by_id(after.json())
    assert by_id["legal_business_name"]["value_status"] == "PROVIDED"
    assert by_id["legal_business_name"]["value_display"] == "Amicor Health, LLC"
    assert by_id["dba"]["value_status"] == "MISSING"
    assert after.json()["readiness"]["percentage_complete"] == 100


def test_missing_overlay_does_not_wipe_soft_defaults() -> None:
    catalog = fact_catalog(
        stored={
            "legal_business_name": {
                "value_status": "MISSING",
                "value_display": OWNER_INPUT_REQUIRED,
                "source": "OWNER",
            },
            "technology_capability": {
                "value_status": "MISSING",
                "value_display": OWNER_INPUT_REQUIRED,
                "source": "OWNER",
            },
        }
    )
    by_id = _by_id(catalog)
    assert by_id["legal_business_name"]["value_status"] == "PROVIDED"
    assert by_id["legal_business_name"]["value_display"] == "Amicor Health, LLC"
    assert by_id["technology_capability"]["value_status"] == "VERIFIED"
    assert catalog["readiness"]["percentage_complete"] == 100


def test_ui_loads_owner_facts_endpoint_and_surfaces_errors() -> None:
    assert "/api/nova/work/owner-facts" in WORK_JS
    assert "Master Work Profile could not be loaded" in WORK_JS
    assert "renderFacts" in WORK_JS


def test_materials_use_master_profile_and_capability_matching() -> None:
    catalog = fact_catalog()
    drafts = generate_drafts(
        {
            "opportunity_title": "B2B reporting project",
            "company_name": "Example Client LLC",
            "description": "Research and reporting support.",
        },
        owner_facts=catalog,
    )
    kinds = {item["kind"] for item in drafts}
    assert {"resume", "cover_letter", "proposal", "capability_statement"} <= kinds
    resume = next(item for item in drafts if item["kind"] == "resume")
    cover = next(item for item in drafts if item["kind"] == "cover_letter")
    proposal = next(item for item in drafts if item["kind"] == "proposal")
    assert "Amicor Health, LLC" in resume["body"]
    assert "Master work profile" in cover["body"] or "MASTER VERIFIED" in resume["body"]
    assert "Amicor Health, LLC" in cover["body"] or "service areas" in cover["body"].lower() or "Master work profile" in cover["body"]
    assert "DRAFT" in proposal["body"]
    assert "ein" not in resume["body"].lower()
    assert "routing" not in resume["body"].lower()


def test_live_qualification_blocks_remain_enforced() -> None:
    fee = qualify_live_job(
        {
            "provider_id": "remotive",
            "provider_identifier": "fee-1",
            "title": "Freelance Writer",
            "company_name": "IAPWE",
            "description": "Applicants to this job signaled that accessing some writing tasks may require payment.",
            "source_url": "https://remotive.com/remote-jobs/writing/freelance-writer-1185979",
            "compensation_text": "$50/hr",
            "job_type": "freelance",
            "source_attribution": "Remotive",
        }
    )
    assert fee["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "upfront_fee_or_paid_membership" in fee["blockers"]
    assert fee["auto_prepare_allowed"] is False
    assert fee["external_submission"] is False
    assert fee["financial_execution"] is False

    specialist = qualify_live_job(
        {
            "provider_id": "remotive",
            "provider_identifier": "ateam-1",
            "title": "Senior Independent AI Engineer / Architect",
            "company_name": "A.Team",
            "description": "A.Team is an invite-only network of senior AI engineers. Tell us what you've built.",
            "source_url": "https://remotive.com/remote-jobs/software-development/senior-independent-ai-engineer-architect-1919266",
            "compensation_text": "$120/hr",
            "job_type": "contract",
            "source_attribution": "Remotive",
        }
    )
    assert specialist["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "individual_specialist_or_talent_network" in specialist["blockers"]

    employee = qualify_live_job(
        {
            "provider_id": "remotive",
            "provider_identifier": "emp-1",
            "title": "Remote Office Assistant",
            "company_name": "Coalition Technologies",
            "description": "Full-time staff position. Join our team as an employee with benefits package and 401k. W-2 employment.",
            "source_url": "https://remotive.com/remote-jobs/coalition-remote-office-assistant",
            "compensation_text": "$40,000",
            "job_type": "full_time",
            "source_attribution": "Remotive",
        }
    )
    assert employee["qualification_status"] == OUTCOME_NOT_QUALIFIED
    assert "employee_w2_staff_role" in employee["blockers"]

    b2b = qualify_live_job(
        {
            "provider_id": "remotive",
            "provider_identifier": "b2b-1",
            "title": "B2B Data Reporting Project",
            "company_name": "Northwind Analytics LLC",
            "description": (
                "Vendor / B2B project-based engagement. Independent contractor or business vendor welcome. "
                "Deliverables: research, data analysis, and reporting documentation. AI tools allowed. "
                "No membership fee. No upfront fee."
            ),
            "source_url": "https://remotive.com/remote-jobs/northwind-b2b-reporting",
            "compensation_text": "$2,500 per project",
            "job_type": "contract",
            "source_attribution": "Remotive",
        }
    )
    assert b2b["qualification_status"] == OUTCOME_QUALIFIED
    assert b2b["auto_prepare_allowed"] is True


def test_profile_field_inventory_and_guardrails() -> None:
    assert len(FACT_DEFINITIONS) == 27
    catalog = fact_catalog()
    ready = catalog["readiness"]
    # licenses soft-defaults to NOT_APPLICABLE → 15 required slots, all owner-approved.
    assert ready["total_required_facts"] == 15
    assert ready["provided_facts"] == 15
    assert ready["percentage_complete"] == 100
    assert ready["missing_facts"] == 0
    guards = engine_guardrails()
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
