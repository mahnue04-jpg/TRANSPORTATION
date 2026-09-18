"""Block 3 AMICOR vs client revenue labeling, mismatch, and double-count protection."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.revenue_labels import AUTHORITATIVE_SOURCE, expected_amicor_revenue, labeling_rules
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app
from tests.test_nova_work_revenue import WORK_HTML, WORK_JS


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


def _eng(http: TestClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "client_name": "Block3 Label Client",
        "service": "Internal labeling work",
        "frequency": "one_time",
        "priority": "normal",
        "source": "manual",
    }
    body.update(overrides)
    response = http.post("/api/nova/work/engagements", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_ui_labels_amicor_versus_client() -> None:
    assert "AMICOR EXPECTED" in WORK_HTML
    assert "CLIENT BILLED" in WORK_HTML
    assert "CLIENT/OPP CONTRACT" in WORK_HTML
    assert "AMICOR vs client revenue" in WORK_HTML
    assert "AMICOR ledger" in WORK_JS
    assert "client billed draft" in WORK_JS.lower()
    assert "Sources are not added together" in WORK_JS
    assert "mismatch flagged between AMICOR ledger" in WORK_JS
    assert "historical/archived, not in current totals" in WORK_JS
    rules = labeling_rules()
    assert rules["authoritative_source"] == AUTHORITATIVE_SOURCE
    assert rules["double_count_opportunity_into_amicor"] is False
    assert expected_amicor_revenue(estimated=10, quoted=20, contracted=30) == 30
    assert expected_amicor_revenue(estimated=10, quoted=20, contracted=0) == 20


def test_authoritative_source_and_duplicate_prevention(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block3 Auth Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 80, "currency": "USD"},
    )
    assert created.status_code == 200
    recon = client.get("/api/nova/work/reconciliation", headers=headers)
    assert recon.status_code == 200
    body = recon.json()
    assert body["authoritative_source"] == AUTHORITATIVE_SOURCE
    assert body["double_counted"] is False
    assert body["amicor"]["party"] == "AMICOR"
    assert body["client_context"]["party"] == "CLIENT_CONTEXT"
    assert body["amicor"]["estimated"]["amount"] >= 80
    assert body["amicor"]["estimated"]["authoritative"] is True
    assert body["client_context"]["billed_amount"]["authoritative"] is False
    assert body["amicor"]["owner_confirmed_received"]["amount"] == body["owner_confirmed_received"]
    dash = client.get("/api/nova/work/dashboard", headers=headers).json()
    assert dash["revenue_summary"]["authoritative_source"] == AUTHORITATIVE_SOURCE
    assert dash["revenue_summary"]["estimated_pipeline"] == body["estimated_amount"]
    assert dash["revenue_summary"]["owner_confirmed_received"] == body["owner_confirmed_received"]
    listed = client.get("/api/nova/work/revenue-entries", headers=headers, params={"limit": 1})
    assert listed.status_code == 200
    assert len(listed.json()) <= 1
    for row in listed.json():
        assert row["party"] == "AMICOR"
        assert row["authoritative"] is True
        assert row["processor_confirmed"] is False


def test_opportunity_and_invoice_support_are_not_added_into_amicor(client: TestClient) -> None:
    headers = _headers(client)
    before = client.get("/api/nova/work/reconciliation", headers=headers).json()
    opp = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "Block3 Context Co",
            "opportunity_title": "Context-only contract",
            "estimated_value": 999,
            "description": "Remote reporting support",
            "skills_required": ["reporting"],
        },
    )
    assert opp.status_code == 200, opp.text
    patched = client.patch(
        f"/api/nova/work/opportunities/{opp.json()['opportunity_id']}",
        headers=headers,
        json={
            "quoted_amount": 888,
            "contract_amount": 777,
            "amount_received": 666,
            "owner_confirmed_payment_received": True,
        },
    )
    assert patched.status_code == 200, patched.text
    engagement = _eng(client, headers, client_name="Block3 Invoice Client")
    invoice = client.post(
        "/api/nova/work/invoice-support",
        headers=headers,
        json={
            "engagement_id": engagement["engagement_id"],
            "work_period_start": "2026-09-01T00:00:00+00:00",
            "work_period_end": "2026-09-07T00:00:00+00:00",
            "quantity": 2,
            "rate": 50,
        },
    )
    assert invoice.status_code == 200, invoice.text
    assert invoice.json()["party"] == "CLIENT_CONTEXT"
    assert invoice.json()["authoritative_for_amicor_revenue"] is False
    after = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert after["owner_confirmed_received"] == before["owner_confirmed_received"]
    assert after["estimated_amount"] == before["estimated_amount"]
    assert after["client_context"]["billed_amount"]["amount"] >= before["client_context"]["billed_amount"]["amount"] + 100
    assert after["client_context"]["contract_opportunity_amount"]["amount"] >= 777
    assert after["double_counted"] is False
    analytics = client.get("/api/nova/work/analytics", headers=headers, params={"period": "all"})
    assert analytics.status_code == 200
    assert analytics.json()["received_revenue"] == after["owner_confirmed_received"]
    assert analytics.json()["double_counted"] is False


def test_mismatch_and_owner_confirmed_received_boundary(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block3 Mismatch Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 40, "currency": "USD"},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]
    opp = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "Block3 Mismatch Co",
            "opportunity_title": "Mismatch context role",
            "estimated_value": 400,
            "description": "Remote mismatch comparison",
        },
    )
    assert opp.status_code == 200, opp.text
    client.patch(
        f"/api/nova/work/opportunities/{opp.json()['opportunity_id']}",
        headers=headers,
        json={"amount_received": 400, "owner_confirmed_payment_received": True},
    )
    recon = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert recon["processor_confirmed_payment"] is False
    assert recon["can_auto_mark_received"] is False
    assert recon["mismatch"]["has_mismatch"] is True
    assert recon["mismatch"]["opportunity_received_vs_amicor_received"] is True
    omitted = client.post(f"/api/nova/work/revenue-entries/{entry_id}/confirm", headers=headers, json={})
    assert omitted.status_code == 400
    jump = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert jump.status_code == 400
    still = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert still["owner_confirmed_received"] == recon["owner_confirmed_received"]
    assert still["mismatch"]["invoice_support_is_not_received"] is True


def test_negative_values_and_tenant_isolation(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block3 Isolation Client")
    negative = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": -5, "currency": "USD"},
    )
    assert negative.status_code == 422
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "CONTRACTED", "amount": 25, "currency": "USD"},
    )
    assert created.status_code == 200
    other = _headers(client, "staff@amicor.local")
    hidden = client.get("/api/nova/work/reconciliation", headers=other).json()
    assert all(item.get("entry_id") != created.json()["entry_id"] for item in hidden.get("entries") or [])
    hidden_list = client.get("/api/nova/work/revenue-entries", headers=other)
    assert hidden_list.status_code == 200
    assert all(item.get("entry_id") != created.json()["entry_id"] for item in hidden_list.json())
    foreign = client.get("/api/nova/work/reconciliation", headers=headers, params={"organization_id": "org-not-the-caller"})
    assert foreign.status_code == 403
    guards = engine_guardrails()
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["AUTONOMOUS_CLIENT_CONTACT_ENABLED"] is False


def _to_payment_pending(http: TestClient, headers: dict[str, str], entry_id: str) -> None:
    for stage in ("QUOTED", "CONTRACTED", "PAYMENT_PENDING"):
        moved = http.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": stage})
        assert moved.status_code == 200, moved.text


def test_paid_ledger_and_opportunity_received_are_not_double_counted(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block3 Paid Ledger Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 50, "currency": "USD"},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]
    _to_payment_pending(client, headers, entry_id)
    paid = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert paid.status_code == 200, paid.text
    assert paid.json()["stage"] == "PAID"
    before = client.get("/api/nova/work/reconciliation", headers=headers).json()
    opp = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "Block3 Double Count Co",
            "opportunity_title": "Client context received only",
            "description": "Remote bookkeeping",
        },
    )
    assert opp.status_code == 200, opp.text
    patched = client.patch(
        f"/api/nova/work/opportunities/{opp.json()['opportunity_id']}",
        headers=headers,
        json={"amount_received": 999, "owner_confirmed_payment_received": True},
    )
    assert patched.status_code == 200, patched.text
    after = client.get("/api/nova/work/reconciliation", headers=headers).json()
    analytics = client.get("/api/nova/work/analytics", headers=headers, params={"period": "all"}).json()
    assert after["owner_confirmed_received"] == before["owner_confirmed_received"]
    assert analytics["received_revenue"] == after["owner_confirmed_received"]
    assert after["client_context"]["opportunity_received_amount"]["amount"] >= 999
    assert after["double_counted"] is False
    assert analytics["double_counted"] is False


def test_partial_payment_keeps_remaining_expected(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block3 Partial Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 100, "currency": "USD"},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]
    _to_payment_pending(client, headers, entry_id)
    before = client.get("/api/nova/work/reconciliation", headers=headers).json()
    partial = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert partial.status_code == 200, partial.text
    body = partial.json()
    assert body["stage"] == "PARTIALLY_PAID"
    assert body["display_stage"] == "PARTIALLY_PAID"
    assert body["amount"] == 40
    assert body["remaining_amount"] == 60
    assert body["owner_confirmed"] is True
    recon = client.get("/api/nova/work/reconciliation", headers=headers).json()
    analytics = client.get("/api/nova/work/analytics", headers=headers, params={"period": "all"}).json()
    listed = [item for item in recon.get("entries") or [] if item.get("entry_id") == entry_id]
    assert listed
    assert listed[0]["amount"] == 40
    assert listed[0]["remaining_amount"] == 60
    assert listed[0]["stage"] == "PARTIALLY_PAID"
    assert recon["owner_confirmed_received"] == before["owner_confirmed_received"] + 40
    assert recon["owner_confirmed_received"] != before["owner_confirmed_received"] + 100
    assert analytics["received_revenue"] == recon["owner_confirmed_received"]


def test_platform_policy_false_login_captcha_cannot_bypass_guards(client: TestClient) -> None:
    headers = _headers(client)
    catalog = client.get("/api/nova/work/platform-policies/catalog", headers=headers)
    assert catalog.status_code == 200
    assert catalog.json()["live_submit_enabled"] is False
    policy = client.post(
        "/api/nova/work/platform-policies",
        headers=headers,
        json={
            "source_label": "open public board",
            "login_required": False,
            "captcha_required": False,
            "human_submission_only": False,
            "terms_restrict_automation": False,
            "manual_review_required": False,
        },
    )
    assert policy.status_code == 200, policy.text
    body = policy.json()
    assert body["LOGIN_REQUIRED"] is False
    assert body["CAPTCHA_REQUIRED"] is False
    assert body["HUMAN_SUBMISSION_ONLY"] is True
    assert body["TERMS_RESTRICT_AUTOMATION"] is True
    assert body["MANUAL_REVIEW_REQUIRED"] is True
    assert body["bypass_allowed"] is False
    opp = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={"company_name": "Policy Guard Co", "opportunity_title": "Remote policy check", "description": "Remote"},
    )
    assert opp.status_code == 200
    client.post(f"/api/nova/work/opportunities/{opp.json()['opportunity_id']}/qualify", headers=headers)
    app_resp = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": opp.json()["opportunity_id"], "applicant_party": "AMICOR"},
    )
    assert app_resp.status_code == 200, app_resp.text
    submit = client.post(f"/api/nova/work/applications/{app_resp.json()['application_id']}/submit", headers=headers)
    assert submit.status_code == 409
    guards = engine_guardrails()
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["LIVE_DISCOVERY_ENABLED"] is False


def test_archived_engagement_revenue_is_historical_not_current(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block3 Archive Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 25, "currency": "USD"},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]
    _to_payment_pending(client, headers, entry_id)
    paid = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert paid.status_code == 200, paid.text
    before = client.get("/api/nova/work/reconciliation", headers=headers).json()
    archived = client.patch(
        f"/api/nova/work/engagements/{engagement['engagement_id']}",
        headers=headers,
        json={"status": "ARCHIVED"},
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "ARCHIVED"
    after = client.get("/api/nova/work/reconciliation", headers=headers).json()
    analytics = client.get("/api/nova/work/analytics", headers=headers, params={"period": "all"}).json()
    assert after["owner_confirmed_received"] == before["owner_confirmed_received"] - 25
    assert after["historical_archived"]["owner_confirmed_received"] >= 25
    assert after["historical_archived"]["included_in_current_totals"] is False
    listed = [item for item in after.get("entries") or [] if item.get("entry_id") == entry_id]
    assert listed
    assert listed[0]["historical"] is True
    assert listed[0]["included_in_current_totals"] is False
    assert listed[0]["amount"] == 25
    assert analytics["received_revenue"] == after["owner_confirmed_received"]
    assert analytics["historical_archived_received"] >= 25

