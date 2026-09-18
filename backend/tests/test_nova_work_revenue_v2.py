"""Work & Revenue V2 core: config, safety, adapters, queue, scheduler, revenue prep."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.adapters.contracts import ADAPTER_KINDS, AdapterRequest
from app.core.nova.work_revenue.adapters.registry import clear_mock_adapters, get_adapter, use_mock_adapters
from app.core.nova.work_revenue.config import is_capability_enabled
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.safety import evaluate_live_action
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.v2_scheduler import period_key
from app.db.session import engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
WORK_HTML = (ROOT / "static" / "nova-work" / "index.html").read_text(encoding="utf-8")
WORK_JS = (ROOT / "static" / "nova-work" / "work.js").read_text(encoding="utf-8")


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


def test_v2_ui_surfaces_present() -> None:
    assert "Pending Owner Approval" in WORK_HTML
    assert "Partial Payments" in WORK_HTML
    assert "Historical / Archived" in WORK_HTML
    assert "NOT SENT BY NOVA" in WORK_HTML
    assert "RECEIVED CONFIRMED BY OWNER" in WORK_HTML
    assert "Approved / Waiting" in WORK_HTML
    assert "Audit Trail" in WORK_HTML
    assert "Capability status" in WORK_HTML
    assert "/api/nova/work/v2/actions/board" in WORK_JS
    assert "approval is not execution" in WORK_JS
    assert "window.open" not in WORK_JS


def test_missing_env_cannot_enable_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.startswith("NOVA_WR_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("AMICOR_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    assert is_capability_enabled("EXTERNAL_SUBMISSION") is False
    guards = engine_guardrails()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["EXTERNAL_SUBMISSION_ENABLED"] is False
    assert guards["FINANCIAL_ACTIONS_ENABLED"] is False
    assert guards["REPORT_SEND_ENABLED"] is False
    assert guards["INVOICE_SEND_ENABLED"] is False
    assert guards["AUTONOMOUS_CLIENT_CONTACT_ENABLED"] is False
    assert guards["CALENDAR_ACTIONS_ENABLED"] is False
    assert guards["NOTIFICATIONS_ENABLED"] is False
    assert guards["APPROVED_EQUALS_SUBMITTED"] is False
    assert guards["APPROVAL_EQUALS_EXECUTION"] is False


def test_capability_requires_master_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_WR_EXTERNAL_SUBMISSION", "true")
    monkeypatch.delenv("NOVA_WR_ALLOW_LIVE_ACTIONS", raising=False)
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    assert is_capability_enabled("EXTERNAL_SUBMISSION") is False
    monkeypatch.setenv("NOVA_WR_ALLOW_LIVE_ACTIONS", "true")
    assert is_capability_enabled("EXTERNAL_SUBMISSION") is True
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "production")
    assert is_capability_enabled("EXTERNAL_SUBMISSION") is False
    monkeypatch.setenv("NOVA_WR_PRODUCTION_LIVE_OVERRIDE", "OWNER_AUTHORIZED_PRODUCTION_LIVE")
    assert is_capability_enabled("EXTERNAL_SUBMISSION") is True
    monkeypatch.setenv("NOVA_WR_ALLOW_LIVE_ACTIONS", "maybe")
    assert is_capability_enabled("EXTERNAL_SUBMISSION") is False


def test_safety_policy_blocks_even_when_flags_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOVA_WR_ALLOW_LIVE_ACTIONS", "true")
    monkeypatch.setenv("NOVA_WR_EXTERNAL_SUBMISSION", "true")
    monkeypatch.setenv("AMICOR_ENVIRONMENT", "development")
    decision = evaluate_live_action(
        "EXTERNAL_SUBMISSION",
        tenant_authorized=True,
        owner_approved=True,
        adapter_implemented=True,
        required_facts_available=True,
        terms_policy_satisfied=True,
        not_duplicated=True,
        dry_run=False,
    )
    assert decision.allowed is False
    assert "adapter_implemented" in decision.blocked_reasons or "correct_environment" in decision.blocked_reasons


def test_capabilities_endpoint_hides_secrets(client: TestClient) -> None:
    headers = _headers(client)
    body = client.get("/api/nova/work/v2/capabilities", headers=headers).json()
    blob = str(body).lower()
    assert "sk_live" not in blob
    assert "password" not in blob
    assert body["secrets_exposed"] is False
    assert body["live_execution_implemented"] is False
    assert body["missing_env_means_off"] is True
    assert body["enabled"]["LIVE_DISCOVERY"] is False
    assert body["enabled"]["FINANCIAL_EXECUTION"] is False
    assert len(body["adapters"]) == len(ADAPTER_KINDS)
    assert all(row["live_implemented"] is False for row in body["adapters"])


def test_guardrails_surface_includes_v2_capabilities(client: TestClient) -> None:
    headers = _headers(client)
    guards = client.get("/api/nova/work/guardrails", headers=headers).json()
    assert guards["LIVE_DISCOVERY_ENABLED"] is False
    assert guards["CALENDAR_ACTIONS_ENABLED"] is False
    assert guards["NOTIFICATIONS_ENABLED"] is False
    assert guards["live_execution_implemented"] is False
    assert "EXTERNAL_SUBMISSION" in guards["capabilities"]


def test_disabled_adapters_do_not_execute() -> None:
    request = AdapterRequest(
        organization_id="org",
        owner_user_id="user",
        action_type="EXTERNAL_SUBMISSION",
        idempotency_key="idem-1",
        owner_approved=True,
        dry_run=False,
    )
    result = get_adapter("external_submission").execute(request)
    assert result.executed is False
    assert result.ok is False
    assert result.secrets_exposed is False
    dry = get_adapter("report_delivery", dry_run=True).execute(request)
    assert dry.executed is False
    assert dry.status in {"DRY_RUN", "OWNER_AUTHORIZATION_REQUIRED", "VALID"} or dry.ok is True


def test_mock_adapter_is_local_only_and_idempotent() -> None:
    use_mock_adapters(True)
    try:
        request = AdapterRequest(
            organization_id="org",
            owner_user_id="user",
            action_type="NOTIFICATIONS",
            idempotency_key="mock-dup",
            owner_approved=True,
        )
        first = get_adapter("notification").execute(request)
        second = get_adapter("notification").execute(request)
        assert first.executed is False
        assert second.duplicate is True
        assert "mock" in first.details
    finally:
        clear_mock_adapters()


def test_supervised_action_lifecycle_never_executes(client: TestClient) -> None:
    headers = _headers(client)
    created = client.post(
        "/api/nova/work/v2/actions",
        headers=headers,
        json={
            "action_type": "APPROVE_EXTERNAL_SUBMISSION",
            "title": "Approve application packet",
            "summary": "Owner review only.",
            "idempotency_key": "sup-submit-1",
            "timezone": "America/Chicago",
        },
    )
    assert created.status_code == 200, created.text
    action_id = created.json()["supervised_action_id"]
    assert created.json()["status"] == "DRAFT"
    assert created.json()["approval_equals_execution"] is False
    reviewed = client.post(f"/api/nova/work/v2/actions/{action_id}/review", headers=headers, json={})
    assert reviewed.json()["status"] == "READY_FOR_REVIEW"
    approved = client.post(f"/api/nova/work/v2/actions/{action_id}/approve", headers=headers, json={})
    assert approved.json()["status"] == "OWNER_APPROVED"
    assert approved.json()["owner_approved"] is True
    queued = client.post(f"/api/nova/work/v2/actions/{action_id}/queue", headers=headers, json={})
    assert queued.json()["status"] == "QUEUED"
    executed = client.post(f"/api/nova/work/v2/actions/{action_id}/execute", headers=headers, json={})
    assert executed.status_code == 200, executed.text
    body = executed.json()
    assert body["status"] == "FAILED"
    assert body["live_execution"] is False
    assert body["approval_status"] == "CONSUMED"
    assert body["consumed_at"]
    assert body["safety"]["allowed"] is False
    assert body["adapter"]["executed"] is False
    duplicate = client.post(f"/api/nova/work/v2/actions/{action_id}/execute", headers=headers, json={})
    assert duplicate.status_code in {409, 400}


def test_duplicate_idempotency_and_cancel_stops_queue(client: TestClient) -> None:
    headers = _headers(client)
    payload = {
        "action_type": "APPROVE_REPORT_SEND",
        "title": "Weekly report send",
        "idempotency_key": "sup-dup-1",
        "timezone": "America/Chicago",
    }
    first = client.post("/api/nova/work/v2/actions", headers=headers, json=payload)
    second = client.post("/api/nova/work/v2/actions", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 409
    action_id = first.json()["supervised_action_id"]
    client.post(f"/api/nova/work/v2/actions/{action_id}/review", headers=headers, json={})
    client.post(f"/api/nova/work/v2/actions/{action_id}/approve", headers=headers, json={})
    client.post(f"/api/nova/work/v2/actions/{action_id}/queue", headers=headers, json={})
    canceled = client.post(f"/api/nova/work/v2/actions/{action_id}/cancel", headers=headers, json={"notes": "revoked"})
    assert canceled.json()["status"] == "CANCELED"
    assert canceled.json()["approval_status"] == "REVOKED"
    blocked = client.post(f"/api/nova/work/v2/actions/{action_id}/execute", headers=headers, json={})
    assert blocked.status_code == 409


def test_action_board_and_audit(client: TestClient) -> None:
    headers = _headers(client)
    board = client.get("/api/nova/work/v2/actions/board", headers=headers)
    assert board.status_code == 200
    assert board.json()["approval_equals_execution"] is False
    assert "pending_owner_approval" in board.json()
    audit = client.get("/api/nova/work/v2/audit", headers=headers)
    assert audit.status_code == 200
    assert isinstance(audit.json(), list)


def test_invalid_timezone_and_malformed_action(client: TestClient) -> None:
    headers = _headers(client)
    bad_tz = client.post(
        "/api/nova/work/v2/actions",
        headers=headers,
        json={"action_type": "APPROVE_CALENDAR_ACTION", "idempotency_key": "tz-bad", "timezone": "Not/AZone"},
    )
    assert bad_tz.status_code == 400
    unknown = client.post(
        "/api/nova/work/v2/actions",
        headers=headers,
        json={"action_type": "LAUNCH_MISSILES", "idempotency_key": "bad-type", "timezone": "UTC"},
    )
    assert unknown.status_code == 400
    html = client.post(
        "/api/nova/work/v2/actions",
        headers=headers,
        json={
            "action_type": "APPROVE_CLIENT_CONTACT",
            "title": "<script>alert(1)</script>",
            "summary": "<img src=x onerror=alert(1)>",
            "idempotency_key": "html-1",
            "timezone": "UTC",
        },
    )
    assert html.status_code == 200
    assert "<script>" not in html.json()["title"]
    assert "<img" not in html.json()["summary"]


def test_tenant_isolation_on_v2_actions(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = client.post(
        "/api/nova/work/v2/actions",
        headers=owner,
        json={"action_type": "APPROVE_INVOICE_SEND", "idempotency_key": "tenant-1", "timezone": "UTC"},
    )
    assert created.status_code == 200
    action_id = created.json()["supervised_action_id"]
    hidden = client.post(f"/api/nova/work/v2/actions/{action_id}/approve", headers=other, json={})
    assert hidden.status_code in {403, 404}
    listed = client.get("/api/nova/work/v2/actions", headers=other)
    assert listed.status_code == 200
    assert all(row["supervised_action_id"] != action_id for row in listed.json())


def test_scheduler_prepare_is_idempotent_and_prepare_only(client: TestClient) -> None:
    headers = _headers(client)
    first = client.post(
        "/api/nova/work/v2/scheduler/prepare",
        headers=headers,
        json={"timezone": "America/Chicago", "kinds": ["REPORT_PREPARE", "INVOICE_PREPARE"]},
    )
    assert first.status_code == 200, first.text
    assert first.json()["send"] is False
    assert first.json()["client_contact"] is False
    assert first.json()["financial_action"] is False
    assert first.json()["continuous_worker"] is False
    second = client.post(
        "/api/nova/work/v2/scheduler/prepare",
        headers=headers,
        json={"timezone": "America/Chicago", "kinds": ["REPORT_PREPARE", "INVOICE_PREPARE"]},
    )
    assert second.json()["created"] == []
    assert len(second.json()["skipped"]) >= 2
    jobs = client.get("/api/nova/work/v2/scheduler/jobs", headers=headers)
    assert jobs.status_code == 200
    assert len(jobs.json()) <= 200
    chicago = period_key("REPORT_PREPARE", "America/Chicago")
    tokyo = period_key("REPORT_PREPARE", "Asia/Tokyo", datetime.now(timezone.utc))
    assert chicago.startswith("REPORT_PREPARE:")
    assert "W" in chicago
    assert tokyo.startswith("REPORT_PREPARE:")


def test_scheduler_rejects_unknown_kind_and_bad_timezone(client: TestClient) -> None:
    headers = _headers(client)
    bad = client.post("/api/nova/work/v2/scheduler/prepare", headers=headers, json={"kinds": ["SEND_REAL_EMAIL"]})
    assert bad.status_code == 400
    tz = client.post("/api/nova/work/v2/scheduler/prepare", headers=headers, json={"timezone": "Chicago"})
    assert tz.status_code == 400


def test_payment_event_does_not_mark_received(client: TestClient) -> None:
    headers = _headers(client)
    engagement = client.post(
        "/api/nova/work/engagements",
        headers=headers,
        json={"client_name": "V2 Ledger Client", "service": "Internal tracking", "frequency": "one_time"},
    )
    assert engagement.status_code == 200, engagement.text
    entry = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={
            "engagement_id": engagement.json()["engagement_id"],
            "stage": "ESTIMATED",
            "amount": 100,
            "currency": "USD",
        },
    )
    assert entry.status_code == 200, entry.text
    entry_id = entry.json()["entry_id"]
    client.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": "QUOTED"})
    client.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": "CONTRACTED"})
    client.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": "PAYMENT_PENDING"})
    event = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=headers,
        json={
            "entry_id": entry_id,
            "amount": 100,
            "idempotency_key": "pay-evt-1",
        },
    )
    assert event.status_code == 200, event.text
    assert event.json()["applied_to_ledger"] is False
    assert event.json()["stripe_object_created"] is False
    dup = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=headers,
        json={"entry_id": entry_id, "amount": 100, "idempotency_key": "pay-evt-1"},
    )
    assert dup.json()["duplicate"] is True
    stale = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=headers,
        json={
            "entry_id": entry_id,
            "amount": 40,
            "idempotency_key": "pay-evt-stale",
            "occurred_at": (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
        },
    )
    assert stale.status_code == 200
    assert stale.json()["stale"] is True or stale.json()["processor_status"] in {"STALE", "RECORDED"}
    prep = client.get("/api/nova/work/v2/revenue/preparation", headers=headers)
    assert prep.status_code == 200
    assert prep.json()["processor_confirmed_payment"] is False
    assert prep.json()["owner_confirmation_authoritative"] is True
    assert prep.json()["can_auto_mark_received"] is False
    confirm = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert confirm.status_code == 200, confirm.text
    assert confirm.json()["stage"] == "PARTIALLY_PAID"
    repeat = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert repeat.status_code in {200, 409}
    recon = client.get("/api/nova/work/reconciliation", headers=headers)
    assert recon.status_code == 200
    assert recon.json()["remaining_balance"] >= 0
    assert recon.json()["processor_confirmed_payment"] is False


def test_payment_event_cross_tenant_and_archived(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    engagement = client.post(
        "/api/nova/work/engagements",
        headers=owner,
        json={"client_name": "Archive Client", "service": "Internal", "frequency": "one_time"},
    )
    entry = client.post(
        "/api/nova/work/revenue-entries",
        headers=owner,
        json={"engagement_id": engagement.json()["engagement_id"], "stage": "ESTIMATED", "amount": 50, "currency": "USD"},
    )
    assert entry.status_code == 200, entry.text
    entry_id = entry.json()["entry_id"]
    hidden = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=other,
        json={"entry_id": entry_id, "amount": 50, "idempotency_key": "other-tenant-pay"},
    )
    assert hidden.status_code in {403, 404}
    archived = client.patch(
        f"/api/nova/work/engagements/{engagement.json()['engagement_id']}",
        headers=owner,
        json={"status": "ARCHIVED"},
    )
    assert archived.status_code == 200, archived.text
    archived_event = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=owner,
        json={"entry_id": entry_id, "amount": 50, "idempotency_key": "archived-pay"},
    )
    assert archived_event.status_code == 409
    detail = str(archived_event.json().get("detail") or archived_event.text)
    assert "Frozen" in detail or "ARCHIVED" in detail


def test_v1_live_routes_still_blocked(client: TestClient) -> None:
    headers = _headers(client)
    submit = client.post("/api/nova/work/applications/NO-SUCH/submit", headers=headers)
    assert submit.status_code == 409
    report = client.post("/api/nova/work/reports/NO-SUCH/send", headers=headers)
    assert report.status_code == 409
    invoice = client.post("/api/nova/work/invoice-support/NO-SUCH/send", headers=headers)
    assert invoice.status_code == 409


def test_list_bounds_and_unsigned(client: TestClient) -> None:
    assert client.get("/api/nova/work/v2/capabilities").status_code == 401
    headers = _headers(client)
    listed = client.get("/api/nova/work/v2/actions?limit=5000", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) <= 200


def test_unsafe_url_still_rejected(client: TestClient) -> None:
    headers = _headers(client)
    created = client.post(
        "/api/nova/work/opportunities",
        headers=headers,
        json={
            "company_name": "Unsafe URL Co",
            "opportunity_title": "Do not fetch",
            "source_url": "javascript:alert(1)",
        },
    )
    assert created.status_code in {400, 422}
