"""Block 5 close-out: remaining V1 queue, owner-fact upsert, and revenue-safety proofs."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.flags import engine_guardrails
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
        "client_name": "Block5 Queue Client",
        "service": "Internal close-out work",
        "frequency": "one_time",
        "priority": "normal",
        "source": "manual",
    }
    body.update(overrides)
    response = http.post("/api/nova/work/engagements", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _queue(http: TestClient, headers: dict[str, str], **params) -> dict:
    response = http.get("/api/nova/work/queue", headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _advance(http: TestClient, headers: dict[str, str], engagement_id: str, *statuses: str) -> dict:
    body = {}
    for status in statuses:
        moved = http.patch(
            f"/api/nova/work/engagements/{engagement_id}",
            headers=headers,
            json={"status": status},
        )
        assert moved.status_code == 200, moved.text
        body = moved.json()
    return body


def _to_payment_pending(http: TestClient, headers: dict[str, str], entry_id: str) -> None:
    for stage in ("QUOTED", "CONTRACTED", "PAYMENT_PENDING"):
        moved = http.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": stage})
        assert moved.status_code == 200, moved.text


def test_block5_ui_default_queue_excludes_historical() -> None:
    assert "Active queue" in WORK_HTML
    assert 'option value="ALL"' in WORK_HTML
    assert "All including archived" in WORK_HTML
    assert "page.active_count" in WORK_JS
    assert "Archived and complete work are excluded from default active counts" in WORK_JS
    assert "live apply" not in WORK_JS.lower()
    assert "create checkout" not in WORK_JS.lower()


def test_default_active_queue_excludes_archived_and_complete(client: TestClient) -> None:
    headers = _headers(client)
    active = _eng(client, headers, client_name="Block5Q-Active Count LLC")
    complete = _eng(client, headers, client_name="Block5Q-Complete Count LLC")
    archived = _eng(client, headers, client_name="Block5Q-Archived Count LLC")
    _advance(client, headers, complete["engagement_id"], "READY", "ACTIVE", "COMPLETE")
    archived_row = _advance(client, headers, archived["engagement_id"], "ARCHIVED")
    assert archived_row["status"] == "ARCHIVED"

    default_page = _queue(client, headers, client="Block5Q-")
    default_ids = {item["engagement_id"] for item in default_page["items"]}
    assert active["engagement_id"] in default_ids
    assert complete["engagement_id"] not in default_ids
    assert archived["engagement_id"] not in default_ids
    assert default_page["historical_excluded"] is True
    assert default_page["active_count"] == default_page["total_matched"]
    assert all(item["queue_status"] not in {"COMPLETE", "ARCHIVED"} for item in default_page["items"])

    all_page = _queue(client, headers, client="Block5Q-", status="ALL")
    all_ids = {item["engagement_id"] for item in all_page["items"]}
    assert {active["engagement_id"], complete["engagement_id"], archived["engagement_id"]}.issubset(all_ids)
    assert all_page["historical_excluded"] is False
    assert all_page["total_matched"] > all_page["active_count"]
    assert all_page["active_count"] == default_page["active_count"]

    archived_only = _queue(client, headers, client="Block5Q-Archived Count", status="ARCHIVED")
    assert any(item["engagement_id"] == archived["engagement_id"] for item in archived_only["items"])
    assert all(item["queue_status"] == "ARCHIVED" for item in archived_only["items"])
    complete_only = _queue(client, headers, client="Block5Q-Complete Count", attention="complete")
    assert any(item["engagement_id"] == complete["engagement_id"] for item in complete_only["items"])


def test_owner_fact_put_is_create_or_update(client: TestClient) -> None:
    headers = _headers(client)
    first = client.put(
        "/api/nova/work/owner-facts/business_age",
        headers=headers,
        json={"value_status": "PROVIDED", "value_display": "Block5 age first"},
    )
    assert first.status_code == 200, first.text
    repeat = client.put(
        "/api/nova/work/owner-facts/business_age",
        headers=headers,
        json={"value_status": "PROVIDED", "value_display": "Block5 age first"},
    )
    assert repeat.status_code == 200, repeat.text
    updated = client.put(
        "/api/nova/work/owner-facts/business_age",
        headers=headers,
        json={"value_status": "PROVIDED", "value_display": "Block5 age updated"},
    )
    assert updated.status_code == 200, updated.text
    row = next(item for item in updated.json()["facts"] if item["fact_id"] == "business_age")
    assert row["value_display"] == "Block5 age updated"
    other = _headers(client, "staff@amicor.local")
    conflict = client.put(
        "/api/nova/work/owner-facts/business_age",
        headers=other,
        json={"value_status": "PROVIDED", "value_display": "Staff should not clobber"},
    )
    assert conflict.status_code == 409
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert first.json().get("executes_externally") is False


def test_partial_payment_and_owner_confirmation_boundaries(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block5 Partial Confirm LLC")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 100, "currency": "USD"},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]
    denied = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert denied.status_code in {400, 409, 422}
    jump = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/stage",
        headers=headers,
        params={"stage": "PAID"},
    )
    assert jump.status_code == 400
    _to_payment_pending(client, headers, entry_id)
    missing_confirm = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": False, "amount": 40},
    )
    assert missing_confirm.status_code == 400
    partial = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert partial.status_code == 200, partial.text
    body = partial.json()
    assert body["stage"] == "PARTIALLY_PAID"
    assert body["amount"] == 40
    assert body["remaining_amount"] == 60
    assert body["owner_confirmed"] is True
    assert body.get("processor_confirmed") is False


def test_archived_revenue_and_double_count_still_safe(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block5 Archive Revenue LLC")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 25, "currency": "USD"},
    )
    entry_id = created.json()["entry_id"]
    _to_payment_pending(client, headers, entry_id)
    paid = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert paid.json()["stage"] == "PAID"
    before = client.get("/api/nova/work/reconciliation", headers=headers).json()
    archived = client.patch(
        f"/api/nova/work/engagements/{engagement['engagement_id']}",
        headers=headers,
        json={"status": "ARCHIVED"},
    )
    assert archived.status_code == 200
    after = client.get("/api/nova/work/reconciliation", headers=headers).json()
    analytics = client.get("/api/nova/work/analytics", headers=headers, params={"period": "all"}).json()
    match = next(item for item in after["entries"] if item["entry_id"] == entry_id)
    assert match["historical"] is True
    assert match["included_in_current_totals"] is False
    assert after["owner_confirmed_received"] == before["owner_confirmed_received"] - 25
    assert after["historical_archived"]["owner_confirmed_received"] >= 25
    assert analytics["received_revenue"] == after["owner_confirmed_received"]
    assert analytics["historical_archived_received"] >= 25
    opp = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "Block5 Context Co",
            "opportunity_title": "Client context only",
            "description": "Remote bookkeeping",
        },
    )
    assert opp.status_code == 200
    client.patch(
        f"/api/nova/work/opportunities/{opp.json()['opportunity_id']}",
        headers=headers,
        json={"amount_received": 999, "owner_confirmed_payment_received": True},
    )
    recon = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert recon["owner_confirmed_received"] == after["owner_confirmed_received"]
    assert recon["double_counted"] is False
    assert recon["authoritative_source"] == "nova_work_revenue_entries"


def test_tenant_isolation_pagination_and_platform_guards(client: TestClient) -> None:
    headers = _headers(client)
    other = _headers(client, "staff@amicor.local")
    engagement = _eng(client, headers, client_name="Block5 Isolation LLC")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 12, "currency": "USD"},
    )
    assert created.status_code == 200
    hidden = client.get("/api/nova/work/reconciliation", headers=other).json()
    assert all(item.get("entry_id") != created.json()["entry_id"] for item in hidden.get("entries") or [])
    hidden_queue = _queue(client, other, client="Block5 Isolation LLC")
    assert all(item.get("engagement_id") != engagement["engagement_id"] for item in hidden_queue["items"])
    foreign = client.get("/api/nova/work/queue", headers=headers, params={"organization_id": "org-not-the-caller"})
    assert foreign.status_code == 403
    capped = _queue(client, headers, limit=500)
    assert capped["limit"] <= 200
    assert len(capped["items"]) <= 200
    policy = client.post(
        "/api/nova/work/platform-policies",
        headers=headers,
        json={
            "source_label": "Block5 platform",
            "login_required": False,
            "captcha_required": False,
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
        json={"company_name": "Block5 Policy Co", "opportunity_title": "Remote policy", "description": "Remote"},
    )
    client.post(f"/api/nova/work/opportunities/{opp.json()['opportunity_id']}/qualify", headers=headers)
    app_resp = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": opp.json()["opportunity_id"], "applicant_party": "AMICOR"},
    )
    assert app_resp.status_code == 200
    submit = client.post(f"/api/nova/work/applications/{app_resp.json()['application_id']}/submit", headers=headers)
    assert submit.status_code == 409
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["AUTONOMOUS_CLIENT_CONTACT_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert "sk_live" not in str(body).lower()
    assert "sk_test" not in str(body).lower()
