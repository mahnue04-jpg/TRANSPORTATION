"""Nova Work & Revenue Engine Phase 1. Local foundation. No Stripe. No external apply."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.capability_registry import CAPABILITIES, PROHIBITED
from app.core.nova.work_revenue.fixtures import simulated_opportunities
from app.core.nova.work_revenue.materials import generate_drafts
from app.core.nova.work_revenue.qualifier import qualify_opportunity
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.verified_profile import OWNER_INPUT_REQUIRED
from app.db.session import engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
WORK_HTML = (STATIC / "nova-work" / "index.html").read_text(encoding="utf-8")
WORK_JS = (STATIC / "nova-work" / "work.js").read_text(encoding="utf-8")
WORK_CSS = (STATIC / "nova-work" / "work.css").read_text(encoding="utf-8")
WORK_PY = ROOT / "app" / "core" / "nova" / "work_revenue"


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    ensure_work_revenue_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


def _create_opp(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "company_name": "Example Operations Co",
        "opportunity_title": "Remote administrative support contractor",
        "description": "Prepare email drafts, organize CRM notes, and summarize reports. Fully remote.",
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
    }
    body.update(overrides)
    response = client.post("/api/nova/work/opportunities", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_work_page_loads(client: TestClient) -> None:
    response = client.get("/nova/work")
    assert response.status_code == 200
    assert "Work &amp; Revenue Engine" in response.text or "Work & Revenue Engine" in response.text
    assert "WORK OPPORTUNITIES" in response.text
    assert "OWNER ACTION REQUIRED" in response.text
    assert "COMING IN LATER PHASE" in response.text
    assert "src=\"/static/nova-work/work.js\"" in response.text
    assert "Opportunity Inbox" in WORK_HTML
    assert "@media (max-width: 720px)" in WORK_CSS
    assert "escapeHtml" in WORK_JS


def test_signed_out_blocks_apis(client: TestClient) -> None:
    assert client.get("/api/nova/work/dashboard").status_code == 401
    assert client.post("/api/nova/work/opportunities", json={"company_name": "X", "opportunity_title": "Y"}).status_code == 401


def test_opportunity_creation_and_dashboard(client: TestClient) -> None:
    headers = _headers(client)
    created = _create_opp(client, headers)
    assert created["opportunity_id"].startswith("NWO-")
    assert created["status"] == "DISCOVERED"
    listed = client.get("/api/nova/work/opportunities", headers=headers)
    assert any(row["opportunity_id"] == created["opportunity_id"] for row in listed.json())
    dash = client.get("/api/nova/work/dashboard", headers=headers)
    assert dash.status_code == 200
    body = dash.json()
    assert body["revenue_placeholder"].startswith("COMING IN LATER PHASE")
    assert "not a human employee" in body["identity_disclaimer"].lower()
    assert body["counts"]["work_opportunities"] >= 1


def test_tenant_isolation(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = _create_opp(client, owner, opportunity_title="Dispatcher only opportunity")
    hidden = client.get(f"/api/nova/work/opportunities/{created['opportunity_id']}", headers=other)
    assert hidden.status_code == 404
    other_list = client.get("/api/nova/work/opportunities", headers=other)
    assert all(row["opportunity_id"] != created["opportunity_id"] for row in other_list.json())
    cross = client.get(
        "/api/nova/work/dashboard",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403


def test_qualification_digital_physical_credential_and_missing() -> None:
    admin = next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-admin-remote")
    warehouse = next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-warehouse")
    rn = next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-rn")
    missing = next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-missing")
    driver = next(item for item in simulated_opportunities() if item["fixture_id"] == "sim-driver")
    admin_q = qualify_opportunity(admin)
    assert admin_q["outcome"] == "NOVA_CAN_PERFORM"
    assert admin_q["deceptive_score_used"] is False
    warehouse_q = qualify_opportunity(warehouse)
    assert warehouse_q["physical_presence_required"] == "true"
    assert warehouse_q["outcome"] in {"HUMAN_REQUIRED", "NOT_SUITABLE"}
    rn_q = qualify_opportunity(rn)
    assert rn_q["licenses_required"] is True
    assert rn_q["outcome"] in {"HUMAN_REQUIRED", "NOT_SUITABLE"}
    missing_q = qualify_opportunity(missing)
    assert missing_q["outcome"] == "INSUFFICIENT_INFORMATION"
    assert "description" in missing_q["missing_information"]
    driver_q = qualify_opportunity(driver)
    assert driver_q["driving_required"] is True
    assert driver_q["outcome"] == "NOT_SUITABLE"
    cpa = {
        "opportunity_title": "Remote CPA",
        "description": "Licensed CPA required for audit opinions.",
        "skills_required": ["reporting"],
        "credentials_required": ["CPA"],
        "physical_presence_required": "false",
        "compensation_type": "hourly",
        "compensation_amount": 90,
    }
    cpa_q = qualify_opportunity(cpa)
    assert cpa_q["licenses_required"] is True
    assert cpa_q["outcome"] in {"HUMAN_REQUIRED", "NOT_SUITABLE"}


def test_capability_registry_does_not_claim_prohibited_work() -> None:
    ids = {item["capability_id"]: item["availability"] for item in CAPABILITIES}
    assert ids["DRIVING"] == PROHIBITED
    assert ids["LICENSED_PROFESSIONAL_PRACTICE"] == PROHIBITED
    assert ids["AUTONOMOUS_APPLICATION_SUBMISSION"] == PROHIBITED
    assert ids["CAPTCHA_OR_IDENTITY_BYPASS"] == PROHIBITED
    assert ids["FINANCIAL_TRANSACTIONS"] == PROHIBITED
    assert ids["EMAIL_DRAFTING"] != PROHIBITED


def test_no_fabricated_credentials_in_drafts() -> None:
    drafts = generate_drafts(
        {
            "opportunity_title": "Remote admin",
            "company_name": "Example Co",
            "description": "Need a Harvard MBA and 12 years of enterprise sales awards.",
        }
    )
    joined = "\n".join(item["body"] for item in drafts)
    assert OWNER_INPUT_REQUIRED in joined
    assert "UNTRUSTED SOURCE TEXT" in joined
    assert "Nova is not a human" in joined or "not a human employee" in joined.lower()
    for banned in ("Bachelor of", "certified public", "I have 12 years", "Harvard MBA holder"):
        assert banned not in joined
    assert "12 years of enterprise sales awards" in joined


def test_owner_approval_required_and_no_external_submit(client: TestClient) -> None:
    headers = _headers(client)
    created = _create_opp(client, headers, opportunity_title="Approval gate role")
    qualified = client.post(f"/api/nova/work/opportunities/{created['opportunity_id']}/qualify", headers=headers)
    assert qualified.status_code == 200, qualified.text
    assert qualified.json()["outcome"] in {"NOVA_CAN_PERFORM", "NOVA_WITH_OWNER_REVIEW"}
    app_resp = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": created["opportunity_id"], "applicant_party": "AMICOR"},
    )
    assert app_resp.status_code == 200, app_resp.text
    application = app_resp.json()
    assert application["approval_state"] == "DRAFT"
    assert application["approved_for_future_submission"] is False
    assert application["externally_submitted"] is False
    assert any(OWNER_INPUT_REQUIRED in item["body"] for item in application["materials"])
    submit = client.post(f"/api/nova/work/applications/{application['application_id']}/submit", headers=headers)
    assert submit.status_code == 409
    assert "FUTURE_SUBMISSION" in submit.json()["detail"]
    manual = client.post(
        f"/api/nova/work/applications/{application['application_id']}/record-manual-submission",
        headers=headers,
    )
    assert manual.status_code == 409
    ready = client.post(
        f"/api/nova/work/applications/{application['application_id']}/ready-for-review",
        headers=headers,
    )
    assert ready.status_code == 200
    assert ready.json()["approval_state"] == "READY_FOR_OWNER_REVIEW"
    approved = client.post(
        f"/api/nova/work/applications/{application['application_id']}/decision",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    assert approved.status_code == 200
    assert approved.json()["approval_state"] == "APPROVED"
    assert approved.json()["approved_for_future_submission"] is True
    still_blocked = client.post(
        f"/api/nova/work/applications/{application['application_id']}/submit",
        headers=headers,
    )
    assert still_blocked.status_code == 409
    assert "FUTURE_SUBMISSION" in still_blocked.json()["detail"]
    recorded = client.post(
        f"/api/nova/work/applications/{application['application_id']}/record-manual-submission",
        headers=headers,
    )
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["manual_submission_recorded"] is True
    assert recorded.json()["externally_submitted"] is False


def test_owner_action_escalation_and_audit(client: TestClient) -> None:
    headers = _headers(client)
    created = _create_opp(
        client,
        headers,
        opportunity_title="Identity gated writing role",
        description=(
            "Remote email drafting and reporting. Identity verification, background check, "
            "and a live interview are required. CAPTCHA on the application portal."
        ),
        skills_required=["email", "reporting"],
        physical_presence_required="false",
    )
    qualified = client.post(f"/api/nova/work/opportunities/{created['opportunity_id']}/qualify", headers=headers)
    assert qualified.status_code == 200, qualified.text
    body = qualified.json()
    assert "CAPTCHA" in body["owner_actions"]
    assert "IDENTITY_VERIFICATION" in body["owner_actions"]
    assert "LIVE_INTERVIEW" in body["owner_actions"]
    actions = client.get("/api/nova/work/owner-actions", headers=headers)
    assert actions.status_code == 200
    types = {row["action_type"] for row in actions.json() if row["opportunity_id"] == created["opportunity_id"]}
    assert "CAPTCHA" in types
    assert all(row["display_label"] == "OWNER ACTION REQUIRED" for row in actions.json() if row["opportunity_id"] == created["opportunity_id"])
    audit = client.get("/api/nova/work/audit", headers=headers)
    events = {row["event_type"] for row in audit.json()}
    assert "OPPORTUNITY_CREATED" in events
    assert "OPPORTUNITY_QUALIFIED" in events
    assert "OWNER_ACTION_REQUIRED" in events
    assert all("ssn" not in row["summary"].lower() or "omitted" in row["summary"].lower() for row in audit.json())


def test_status_transitions_and_tracker(client: TestClient) -> None:
    headers = _headers(client)
    created = _create_opp(client, headers, opportunity_title="Tracker role")
    client.post(f"/api/nova/work/opportunities/{created['opportunity_id']}/qualify", headers=headers)
    app_resp = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": created["opportunity_id"]},
    )
    application_id = app_resp.json()["application_id"]
    client.post(f"/api/nova/work/applications/{application_id}/ready-for-review", headers=headers)
    client.post(
        f"/api/nova/work/applications/{application_id}/decision",
        headers=headers,
        json={"decision": "APPROVED"},
    )
    client.post(f"/api/nova/work/applications/{application_id}/record-manual-submission", headers=headers)
    moved = client.patch(
        f"/api/nova/work/applications/{application_id}/status",
        headers=headers,
        json={"status": "FOLLOW_UP_DUE"},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["status"] == "FOLLOW_UP_DUE"
    illegal = client.patch(
        f"/api/nova/work/applications/{application_id}/status",
        headers=headers,
        json={"status": "WON"},
    )
    assert illegal.status_code == 400
    tracker = client.get(f"/api/nova/work/opportunities/{created['opportunity_id']}/tracker", headers=headers)
    assert tracker.status_code == 200
    history = tracker.json()["status_history"]
    assert any(item["to_status"] == "DISCOVERED" for item in history)
    assert tracker.json()["approval_state"] == "APPROVED"


def test_simulated_ingest_and_today_summary(client: TestClient) -> None:
    headers = _headers(client)
    ingested = client.post("/api/nova/work/ingest/simulated", headers=headers)
    assert ingested.status_code == 200, ingested.text
    assert len(ingested.json()) >= 5
    summary = client.get("/api/nova/work/today-summary", headers=headers)
    assert summary.status_code == 200
    body = summary.json()
    assert body["href"] == "/nova/work"
    assert body["work_opportunities"] >= 5
    providers = client.get("/api/nova/work/providers", headers=headers)
    ids = {row["provider_id"] for row in providers.json()}
    assert "manual" in ids
    assert "simulated" in ids
    assert any(row["provider_id"] == "career_page" and row["phase1_enabled"] is False for row in providers.json())


def test_work_module_has_no_stripe_or_lifesaver_imports() -> None:
    for path in WORK_PY.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        assert "import stripe" not in lowered
        assert "from stripe" not in lowered
        assert "app.modules.lifesaver" not in lowered
        assert "app.core.nova.payments" not in lowered
        assert "sk_live" not in lowered
        assert "sk_test" not in lowered
        assert "whsec_" not in text
