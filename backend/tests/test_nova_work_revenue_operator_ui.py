"""Block 2 operator surfaces: queue, reconciliation, fact status, and filter safety."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def _eng(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "client_name": "Block2 Operator Client",
        "service": "Internal operator visibility",
        "frequency": "one_time",
        "priority": "normal",
        "source": "manual",
    }
    body.update(overrides)
    response = client.post("/api/nova/work/engagements", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _queue(http: TestClient, headers: dict[str, str], **params) -> dict:
    response = http.get("/api/nova/work/queue", headers=headers, params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, dict)
    assert isinstance(body.get("items"), list)
    return body


def test_operator_ui_has_queue_and_reconciliation_only() -> None:
    assert 'data-tab="queue"' in WORK_HTML
    assert 'data-tab="reconciliation"' in WORK_HTML
    assert "Internal work queue" in WORK_HTML
    assert "Internal reconciliation" in WORK_HTML
    assert "OWNER CONFIRMED RECEIVED" in WORK_HTML
    assert "INVOICE SUPPORT" in WORK_HTML
    assert "/api/nova/work/queue" in WORK_JS
    assert "/api/nova/work/reconciliation" in WORK_JS
    assert "escapeHtml(row.client_name" in WORK_JS
    assert "escapeHtml(body.disclaimer)" in WORK_JS
    lowered = WORK_JS.lower()
    assert "live apply" not in lowered
    assert "submit application" not in WORK_JS
    assert "create checkout" not in lowered
    assert "payout" not in lowered
    assert "webhook" not in lowered
    assert "deploy" not in lowered
    assert "stripe.confirm" not in lowered


def test_queue_happy_path_and_empty_filter(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block2 Happy Path LLC")
    page = _queue(client, headers, client="Block2 Happy Path LLC")
    assert page["empty"] is False
    assert page["executes_externally"] is False
    assert page["live_discovery_enabled"] is False
    assert page["external_submit_enabled"] is False
    assert page["client_contact_enabled"] is False
    assert page["financial_execution_enabled"] is False
    assert page["guardrails"]["APPROVED_EQUALS_SUBMITTED"] is False
    match = next(item for item in page["items"] if item["engagement_id"] == engagement["engagement_id"])
    assert match["queue_status"] == "NEW"
    assert match["priority"] == "normal"
    assert match["executes_externally"] is False
    assert match["organization_id"]
    assert match["owner_user_id"]
    empty = _queue(client, headers, client="NO-SUCH-BLOCK2-QUEUE-CLIENT")
    assert empty["empty"] is True
    assert empty["items"] == []
    assert empty["total_matched"] == 0


def test_queue_filter_sort_and_pagination_validation(client: TestClient) -> None:
    headers = _headers(client)
    created = [
        _eng(client, headers, client_name=f"Block2 Page {index}", priority="high")
        for index in range(3)
    ]
    assert client.get("/api/nova/work/queue", headers=headers, params={"status": "SUBMITTED"}).status_code == 400
    assert client.get("/api/nova/work/queue", headers=headers, params={"sort": "hacked"}).status_code == 400
    assert client.get("/api/nova/work/queue", headers=headers, params={"order": "sideways"}).status_code == 400
    assert client.get("/api/nova/work/queue", headers=headers, params={"priority": "critical"}).status_code == 400
    assert client.get("/api/nova/work/queue", headers=headers, params={"attention": "hacked"}).status_code == 400
    first = _queue(client, headers, client="Block2 Page", sort="priority", order="desc", limit=1, offset=0)
    assert first["limit"] == 1
    assert first["offset"] == 0
    assert len(first["items"]) == 1
    assert first["total_matched"] >= 3
    second = _queue(client, headers, client="Block2 Page", sort="priority", order="desc", limit=1, offset=1)
    assert second["offset"] == 1
    assert len(second["items"]) == 1
    assert first["items"][0]["engagement_id"] != second["items"][0]["engagement_id"]
    capped = _queue(client, headers, client="Block2 Page", limit=500)
    assert capped["limit"] <= 200
    assert len(capped["items"]) <= 200
    ids = {item["engagement_id"] for item in _queue(client, headers, client="Block2 Page")["items"]}
    assert {item["engagement_id"] for item in created}.issubset(ids)


def test_queue_overdue_blocked_and_owner_action_states(client: TestClient) -> None:
    headers = _headers(client)
    overdue = _eng(
        client,
        headers,
        client_name="Block2 Overdue Client",
        due_date=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
    )
    blocked = _eng(client, headers, client_name="Block2 Blocked Client")
    owner = _eng(client, headers, client_name="Block2 Owner Action Client")
    moved_blocked = client.patch(
        f"/api/nova/work/engagements/{blocked['engagement_id']}",
        headers=headers,
        json={"status": "BLOCKED", "blockers": "Waiting on owner fact"},
    )
    assert moved_blocked.status_code == 200
    moved_owner = client.patch(
        f"/api/nova/work/engagements/{owner['engagement_id']}",
        headers=headers,
        json={"status": "OWNER_ACTION_REQUIRED"},
    )
    assert moved_owner.status_code == 200
    overdue_page = _queue(client, headers, attention="overdue", client="Block2 Overdue")
    assert any(item["engagement_id"] == overdue["engagement_id"] for item in overdue_page["items"])
    assert all(item["overdue"] is True for item in overdue_page["items"])
    blocked_page = _queue(client, headers, attention="blocked", client="Block2 Blocked")
    assert any(item["engagement_id"] == blocked["engagement_id"] for item in blocked_page["items"])
    assert all(item["queue_status"] == "BLOCKED" for item in blocked_page["items"])
    owner_page = _queue(client, headers, attention="owner_action", client="Block2 Owner Action")
    match = next(item for item in owner_page["items"] if item["engagement_id"] == owner["engagement_id"])
    assert match["owner_action_required"] is True
    assert match["attention_state"] == "OWNER_ACTION_REQUIRED"


def test_reconciliation_display_and_received_boundary(client: TestClient) -> None:
    headers = _headers(client)
    before = client.get("/api/nova/work/reconciliation", headers=headers)
    assert before.status_code == 200
    before_body = before.json()
    engagement = _eng(client, headers, client_name="Block2 Recon Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement["engagement_id"], "stage": "ESTIMATED", "amount": 75, "currency": "USD"},
    )
    assert created.status_code == 200
    entry_id = created.json()["entry_id"]
    after_get = client.get("/api/nova/work/reconciliation", headers=headers)
    assert after_get.status_code == 200
    body = after_get.json()
    assert body["tracking_kind"] == "INTERNAL_ONLY"
    assert body["processor_confirmed_payment"] is False
    assert body["stripe_confirmed_payment"] is False
    assert body["can_auto_mark_received"] is False
    assert body["rules"]["APPROVED_EQUALS_SUBMITTED"] is False
    assert body["rules"]["INVOICE_SUPPORT_EQUALS_INVOICE_SENT"] is False
    assert body["rules"]["OWNER_CONFIRMED_RECEIVED_EQUALS_PROCESSOR_CONFIRMED"] is False
    assert body["estimated_amount"] >= before_body["estimated_amount"] + 75
    assert body["owner_confirmed_received_amount"] == before_body["owner_confirmed_received_amount"]
    assert any(item["entry_id"] == entry_id for item in body["entries"])
    refused = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": False},
    )
    assert refused.status_code == 400
    jump = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert jump.status_code == 400
    still = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert still["owner_confirmed_received_amount"] == before_body["owner_confirmed_received_amount"]
    assert still["processor_confirmed_payment"] is False
    omitted = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={},
    )
    assert omitted.status_code == 400
    client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/stage",
        headers=headers,
        params={"stage": "QUOTED"},
    )
    client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/stage",
        headers=headers,
        params={"stage": "CONTRACTED"},
    )
    contracted_paid = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert contracted_paid.status_code == 400
    client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/stage",
        headers=headers,
        params={"stage": "PAYMENT_PENDING"},
    )
    first_confirm = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert first_confirm.status_code == 200, first_confirm.text
    repeat = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True},
    )
    assert repeat.status_code == 409
    after_confirm = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert after_confirm["processor_confirmed_payment"] is False
    assert after_confirm["stripe_confirmed_payment"] is False


def test_queue_get_does_not_duplicate_records(client: TestClient) -> None:
    headers = _headers(client)
    engagement = _eng(client, headers, client_name="Block2 Dedupe Client")
    first = _queue(client, headers, client="Block2 Dedupe Client")
    second = _queue(client, headers, client="Block2 Dedupe Client")
    first_ids = [item["engagement_id"] for item in first["items"] if item["engagement_id"] == engagement["engagement_id"]]
    second_ids = [item["engagement_id"] for item in second["items"] if item["engagement_id"] == engagement["engagement_id"]]
    assert first_ids == [engagement["engagement_id"]]
    assert second_ids == first_ids
    assert first["total_matched"] == second["total_matched"]


def test_tenant_isolation_for_queue_recon_and_facts(client: TestClient) -> None:
    owner = _headers(client)
    other = _headers(client, "staff@amicor.local")
    engagement = _eng(client, owner, client_name="Block2 Isolation Client")
    created = client.post(
        "/api/nova/work/revenue-entries",
        headers=owner,
        json={"engagement_id": engagement["engagement_id"], "stage": "CONTRACTED", "amount": 40, "currency": "USD"},
    )
    assert created.status_code == 200
    fact = client.put(
        "/api/nova/work/owner-facts/service_areas",
        headers=owner,
        json={"value_status": "PROVIDED", "value_display": "Owner-only Block2 area"},
    )
    assert fact.status_code == 200
    hidden_queue = _queue(client, other, client="Block2 Isolation Client")
    assert all(item["engagement_id"] != engagement["engagement_id"] for item in hidden_queue["items"])
    hidden_recon = client.get("/api/nova/work/reconciliation", headers=other).json()
    assert all(item.get("entry_id") != created.json()["entry_id"] for item in hidden_recon.get("entries") or [])
    hidden_eng = client.get(f"/api/nova/work/engagements/{engagement['engagement_id']}", headers=other)
    assert hidden_eng.status_code == 404
    other_facts = client.get("/api/nova/work/owner-facts", headers=other).json()
    other_row = next(item for item in other_facts["facts"] if item["fact_id"] == "service_areas")
    # Master Work Profile is org-scoped: same-org operators share the business profile.
    # Queue/engagement/revenue isolation above remains per-owner.
    assert other_row["value_display"] == "Owner-only Block2 area"
    assert other_row["value_status"] == "PROVIDED"
    foreign = client.get("/api/nova/work/queue", headers=owner, params={"organization_id": "org-not-the-caller"})
    assert foreign.status_code == 403


def test_malicious_text_is_not_trusted_in_operator_surfaces(client: TestClient) -> None:
    headers = _headers(client)
    hostile = _eng(client, headers, client_name="<script>alert(1)</script> Block2")
    page = _queue(client, headers, client="Block2")
    match = next(item for item in page["items"] if item["engagement_id"] == hostile["engagement_id"])
    assert "<script>" in match["client_name"]
    assert "escapeHtml(row.client_name" in WORK_JS
    assert "innerHTML = listHtml(items" in WORK_JS


def test_owner_fact_status_is_safe_and_external_controls_stay_off(client: TestClient) -> None:
    headers = _headers(client)
    page = _queue(client, headers)
    facts = page["owner_fact_status"]
    assert facts["secrets_shown"] is False
    assert "verified" in facts
    assert "missing" in facts
    assert "expired" in facts
    assert "percentage_complete" in facts
    assert "sk_live" not in str(facts).lower()
    assert "whsec" not in str(facts).lower()
    recon = client.get("/api/nova/work/reconciliation", headers=headers).json()
    assert recon["owner_fact_status"]["secrets_shown"] is False
    assert recon["executes_externally"] is False
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["AUTONOMOUS_CLIENT_CONTACT_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert page["disclaimer"].startswith("Internal work queue")
