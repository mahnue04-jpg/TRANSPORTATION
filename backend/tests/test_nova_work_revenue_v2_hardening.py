"""V2 hardening: approval lifecycle, freeze, owner isolation, payment math, scheduler."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.core.nova.work_revenue.v2_idempotency import WEBHOOK_REUSE_CONTRACT, redact_secrets, secrets_rejected
from app.core.nova.work_revenue.v2_scheduler import period_key
from app.db.session import engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]


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


def _pending_entry(client: TestClient, headers: dict[str, str], amount: float = 100, name: str = "Pilot Client"):
    engagement = client.post(
        "/api/nova/work/engagements",
        headers=headers,
        json={"client_name": name, "service": "Internal tracking", "frequency": "one_time"},
    )
    assert engagement.status_code == 200, engagement.text
    entry = client.post(
        "/api/nova/work/revenue-entries",
        headers=headers,
        json={"engagement_id": engagement.json()["engagement_id"], "stage": "ESTIMATED", "amount": amount, "currency": "USD"},
    )
    assert entry.status_code == 200, entry.text
    entry_id = entry.json()["entry_id"]
    client.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": "QUOTED"})
    client.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": "CONTRACTED"})
    client.post(f"/api/nova/work/revenue-entries/{entry_id}/stage", headers=headers, params={"stage": "PAYMENT_PENDING"})
    return entry_id, engagement.json()["engagement_id"]


def _draft_action(client: TestClient, headers: dict[str, str], key: str, action_type: str = "APPROVE_REPORT_SEND"):
    created = client.post(
        "/api/nova/work/v2/actions",
        headers=headers,
        json={"action_type": action_type, "idempotency_key": key, "timezone": "America/Chicago"},
    )
    assert created.status_code == 200, created.text
    action_id = created.json()["supervised_action_id"]
    client.post(f"/api/nova/work/v2/actions/{action_id}/review", headers=headers, json={})
    return action_id


def test_approval_grant_revoke_expire_consume_replay(client: TestClient) -> None:
    headers = _headers(client)
    action_id = _draft_action(client, headers, "hard-approve-1")
    approved = client.post(f"/api/nova/work/v2/actions/{action_id}/approve", headers=headers, json={})
    assert approved.status_code == 200
    assert approved.json()["approval_status"] == "APPROVED"
    assert approved.json()["approval_equals_execution"] is False
    assert approved.json()["expires_at"]
    queued = client.post(f"/api/nova/work/v2/actions/{action_id}/queue", headers=headers, json={})
    assert queued.json()["status"] == "QUEUED"
    executed = client.post(f"/api/nova/work/v2/actions/{action_id}/execute", headers=headers, json={})
    assert executed.status_code == 200
    assert executed.json()["approval_status"] == "CONSUMED"
    assert executed.json()["status"] == "FAILED"
    assert executed.json()["safety"]["allowed"] is False
    replay = client.post(f"/api/nova/work/v2/actions/{action_id}/execute", headers=headers, json={})
    assert replay.status_code == 409


def test_approval_revoke_and_reject_and_expire(client: TestClient) -> None:
    headers = _headers(client)
    revoke_id = _draft_action(client, headers, "hard-revoke-1")
    client.post(f"/api/nova/work/v2/actions/{revoke_id}/approve", headers=headers, json={})
    revoked = client.post(f"/api/nova/work/v2/actions/{revoke_id}/revoke", headers=headers, json={"notes": "stop"})
    assert revoked.json()["approval_status"] == "REVOKED"
    assert client.post(f"/api/nova/work/v2/actions/{revoke_id}/execute", headers=headers, json={}).status_code == 409

    reject_id = _draft_action(client, headers, "hard-reject-1")
    rejected = client.post(f"/api/nova/work/v2/actions/{reject_id}/reject", headers=headers, json={"notes": "no"})
    assert rejected.json()["approval_status"] == "REJECTED"
    assert client.post(f"/api/nova/work/v2/actions/{reject_id}/execute", headers=headers, json={}).status_code == 409

    expire_id = _draft_action(client, headers, "hard-expire-1")
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    approved = client.post(
        f"/api/nova/work/v2/actions/{expire_id}/approve",
        headers=headers,
        json={"expires_at": past},
    )
    assert approved.status_code == 200
    blocked = client.post(f"/api/nova/work/v2/actions/{expire_id}/execute", headers=headers, json={})
    assert blocked.status_code == 409
    stale_id = _draft_action(client, headers, "hard-stale-1")
    client.post(f"/api/nova/work/v2/actions/{stale_id}/approve", headers=headers, json={})
    expired = client.post(f"/api/nova/work/v2/actions/{stale_id}/expire", headers=headers, json={})
    assert expired.json()["approval_status"] == "EXPIRED"
    assert client.post(f"/api/nova/work/v2/actions/{stale_id}/execute", headers=headers, json={}).status_code == 409


def test_missing_malformed_cross_owner_approval(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    missing = client.post("/api/nova/work/v2/actions/NWS-DOES-NOT-EXIST/execute", headers=owner, json={})
    assert missing.status_code in {404, 409}
    malformed = client.post(
        "/api/nova/work/v2/actions",
        headers=owner,
        json={"action_type": "NOT_A_TYPE", "idempotency_key": "bad"},
    )
    assert malformed.status_code == 400
    action_id = _draft_action(client, owner, "hard-cross-owner")
    hidden = client.post(f"/api/nova/work/v2/actions/{action_id}/approve", headers=other, json={})
    assert hidden.status_code in {403, 404}
    unsigned = client.post(
        "/api/nova/work/v2/actions",
        json={"action_type": "APPROVE_REPORT_SEND", "idempotency_key": "no-auth"},
    )
    assert unsigned.status_code == 401


def test_payment_math_partial_and_overpay(client: TestClient) -> None:
    headers = _headers(client)
    entry_id, _eng = _pending_entry(client, headers, 100, "Math Client")
    zero = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 0},
    )
    assert zero.status_code == 200
    assert zero.json()["stage"] == "PARTIALLY_PAID"
    assert zero.json()["amount"] == 0
    assert zero.json()["remaining_amount"] == 100
    forty = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert forty.json()["amount"] == 40
    assert forty.json()["remaining_amount"] == 60
    dup40 = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert dup40.status_code == 200
    assert dup40.json()["amount"] == 40
    assert dup40.json()["remaining_amount"] == 60
    sixty = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 60},
    )
    assert sixty.json()["amount"] == 60
    assert sixty.json()["remaining_amount"] == 40
    hundred = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 100},
    )
    assert hundred.json()["stage"] == "PAID"
    assert hundred.json()["amount"] == 100
    assert hundred.json()["remaining_amount"] == 0
    replay = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 100},
    )
    assert replay.status_code == 409
    over_id, _ = _pending_entry(client, headers, 100, "Overpay Client")
    over = client.post(
        f"/api/nova/work/revenue-entries/{over_id}/confirm",
        headers=headers,
        json={"owner_confirmed": True, "amount": 101},
    )
    assert over.status_code == 409
    assert "OVERPAYMENT_REQUIRES_OWNER_REVIEW" in str(over.json().get("detail") or over.text)


def test_archived_closed_cancelled_freeze_and_historical_correction(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    entry_id, engagement_id = _pending_entry(client, owner, 80, "Freeze Client")
    recon_before = client.get("/api/nova/work/reconciliation", headers=owner).json()
    current_before = recon_before["owner_confirmed_received"]
    archived = client.patch(f"/api/nova/work/engagements/{engagement_id}", headers=owner, json={"status": "ARCHIVED"})
    assert archived.status_code == 200, archived.text
    frozen = client.post(
        f"/api/nova/work/revenue-entries/{entry_id}/confirm",
        headers=owner,
        json={"owner_confirmed": True, "amount": 40},
    )
    assert frozen.status_code == 409
    cancel_id, cancel_eng = _pending_entry(client, owner, 70, "Cancel Client")
    cancelled = client.patch(f"/api/nova/work/engagements/{cancel_eng}", headers=owner, json={"status": "CANCELLED"})
    assert cancelled.status_code == 200, cancelled.text
    assert client.post(
        f"/api/nova/work/revenue-entries/{cancel_id}/confirm",
        headers=owner,
        json={"owner_confirmed": True, "amount": 10},
    ).status_code == 409
    opp = client.post(
        "/api/nova/work/opportunities",
        headers=owner,
        json={"company_name": "Closed Co", "opportunity_title": "Closed role", "source_url": "https://example.invalid/closed"},
    )
    assert opp.status_code == 200, opp.text
    opp_id = opp.json()["opportunity_id"]
    client.patch(f"/api/nova/work/opportunities/{opp_id}", headers=owner, json={"status": "CLOSED"})
    blocked_action = client.post(
        "/api/nova/work/v2/actions",
        headers=owner,
        json={
            "action_type": "APPROVE_APPLICATION",
            "idempotency_key": "frozen-opp-1",
            "timezone": "UTC",
            "ref_type": "opportunity",
            "ref_id": opp_id,
        },
    )
    assert blocked_action.status_code == 409
    correction = client.post(
        "/api/nova/work/v2/revenue/historical-corrections",
        headers=owner,
        json={
            "entry_id": entry_id,
            "engagement_id": engagement_id,
            "amount": 12,
            "idempotency_key": "hist-1",
            "reason": "Owner historical correction after archive",
        },
    )
    assert correction.status_code == 200, correction.text
    assert correction.json()["classification"] == "HISTORICAL"
    assert correction.json()["applied_to_current_totals"] is False
    hidden = client.post(
        "/api/nova/work/v2/revenue/historical-corrections",
        headers=other,
        json={
            "entry_id": entry_id,
            "amount": 12,
            "idempotency_key": "hist-other",
            "reason": "Cross-tenant historical correction attempt",
        },
    )
    assert hidden.status_code in {403, 404}
    recon_after = client.get("/api/nova/work/reconciliation", headers=owner).json()
    assert recon_after["owner_confirmed_received"] == current_before
    listed = client.get("/api/nova/work/v2/revenue/historical-corrections", headers=owner)
    assert listed.status_code == 200
    assert any(row["correction_id"] == correction.json()["correction_id"] for row in listed.json())


def test_payment_event_owner_isolation_and_immutable_duplicate(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    entry_id, _eng = _pending_entry(client, owner, 55, "Isolation Client")
    first = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=owner,
        json={"entry_id": entry_id, "amount": 55, "idempotency_key": "owner-key-1"},
    )
    assert first.status_code == 200, first.text
    event_id = first.json()["event_id"]
    replay = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=owner,
        json={"entry_id": entry_id, "amount": 99, "idempotency_key": "owner-key-1"},
    )
    assert replay.json()["duplicate"] is True
    assert replay.json()["event_id"] == event_id
    assert replay.json()["amount"] == 55
    other_same_key = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=other,
        json={"amount": 10, "idempotency_key": "owner-key-1"},
    )
    assert other_same_key.status_code == 200, other_same_key.text
    assert other_same_key.json()["event_id"] != event_id
    cross_entry = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=other,
        json={"entry_id": entry_id, "amount": 55, "idempotency_key": "staff-on-owner-entry"},
    )
    assert cross_entry.status_code in {403, 404}
    malformed = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        headers=owner,
        json={"entry_id": entry_id, "amount": 1},
    )
    assert malformed.status_code in {400, 422}
    unsigned = client.post(
        "/api/nova/work/v2/revenue/payment-events",
        json={"amount": 1, "idempotency_key": "no-owner"},
    )
    assert unsigned.status_code == 401


def test_scheduler_savepoint_dst_paused_archived(client: TestClient) -> None:
    headers = _headers(client)
    first = client.post(
        "/api/nova/work/v2/scheduler/prepare",
        headers=headers,
        json={"timezone": "America/Chicago", "kinds": ["FOLLOW_UP_REMINDER_PREPARE"]},
    )
    assert first.status_code == 200, first.text
    mixed = client.post(
        "/api/nova/work/v2/scheduler/prepare",
        headers=headers,
        json={"timezone": "America/Chicago", "kinds": ["FOLLOW_UP_REMINDER_PREPARE", "OPPORTUNITY_RECHECK_PREPARE"]},
    )
    assert mixed.status_code == 200
    assert any(item["reason"] == "duplicate_period" for item in mixed.json()["skipped"])
    dst = datetime(2026, 3, 8, 1, 30, tzinfo=ZoneInfo("America/Chicago"))
    after = datetime(2026, 3, 8, 3, 30, tzinfo=ZoneInfo("America/Chicago"))
    assert period_key("FOLLOW_UP_REMINDER_PREPARE", "America/Chicago", dst)
    assert period_key("FOLLOW_UP_REMINDER_PREPARE", "America/Chicago", after).startswith("FOLLOW_UP_REMINDER_PREPARE:")
    assert "-W" in period_key("REPORT_PREPARE", "America/Chicago", dst)
    assert period_key("INVOICE_PREPARE", "America/Chicago", dst).endswith("2026-03")
    engagement = client.post(
        "/api/nova/work/engagements",
        headers=headers,
        json={"client_name": "Paused Source", "service": "Internal", "frequency": "weekly"},
    )
    assert engagement.status_code == 200
    series = client.post(
        "/api/nova/work/recurring",
        headers=headers,
        json={"engagement_id": engagement.json()["engagement_id"], "title": "Weekly internal task", "frequency": "weekly"},
    )
    assert series.status_code == 200, series.text
    paused = client.post(
        f"/api/nova/work/recurring/{series.json()['series_id']}/pause",
        headers=headers,
    )
    assert paused.status_code == 200, paused.text
    archived = client.patch(
        f"/api/nova/work/engagements/{engagement.json()['engagement_id']}",
        headers=headers,
        json={"status": "ARCHIVED"},
    )
    assert archived.status_code == 200
    prepare = client.post(
        "/api/nova/work/v2/scheduler/prepare",
        headers=headers,
        json={"timezone": "UTC", "kinds": ["RECURRING_TASK_PREPARE", "INVOICE_PREPARE"]},
    )
    assert prepare.status_code == 200, prepare.text
    assert prepare.json()["continuous_worker"] is False
    jobs = client.get("/api/nova/work/v2/scheduler/jobs", headers=headers)
    assert jobs.status_code == 200
    other = _headers(client, "staff@amicor.local")
    foreign = client.get("/api/nova/work/v2/scheduler/jobs", headers=other)
    assert foreign.status_code == 200


def test_status_pilot_idempotency_contract_and_secrets(client: TestClient) -> None:
    headers = _headers(client)
    status = client.get("/api/nova/work/v2/status", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["live_execution_state"] == "DISABLED"
    assert body["continuous_worker"] is False
    assert body["secrets_exposed"] is False
    assert body["live_capabilities"]["EXTERNAL_SUBMISSION"] == "DISABLED"
    caps = client.get("/api/nova/work/v2/capabilities", headers=headers).json()
    assert caps["live_disabled"]["BACKGROUND_WORKER"] is False
    assert caps["core_readiness"]["approval_lifecycle"] is True
    assert caps["enabled"]["LIVE_DISCOVERY"] is False
    poisoned = client.post(
        "/api/nova/work/v2/actions",
        headers=headers,
        json={
            "action_type": "APPROVE_CLIENT_CONTACT",
            "title": "password supersecret sk_live_123",
            "summary": "api_key=abcd routing number 123",
            "idempotency_key": "secret-action-1",
            "timezone": "UTC",
        },
    )
    assert poisoned.status_code == 200
    assert "sk_live" not in poisoned.json()["title"]
    assert secrets_rejected("sk_live_abc")
    assert "omitted" in redact_secrets("Authorization: Bearer tok")
    contract = client.get("/api/nova/work/v2/idempotency/contract", headers=headers)
    assert contract.status_code == 200
    assert contract.json()["processor_events_never_apply_to_ledger_by_default"] is True
    assert WEBHOOK_REUSE_CONTRACT["stripe_objects_created"] is False
    pilot = client.get("/api/nova/work/v2/pilot/workflow", headers=headers)
    assert pilot.status_code == 200
    assert pilot.json()["nova_claims_external_submission"] is False
    header_enable = client.get(
        "/api/nova/work/v2/capabilities",
        headers={**headers, "X-NOVA-WR-ALLOW-LIVE-ACTIONS": "true"},
    )
    assert header_enable.json()["enabled"]["EXTERNAL_SUBMISSION"] is False
    html = (ROOT / "static" / "nova-work" / "index.html").read_text(encoding="utf-8")
    assert "OWNER ACTION REQUIRED" in html
    assert (ROOT / "migrations" / "versions" / "20260918_nova_work_revenue_v2_hardening.py").exists()

