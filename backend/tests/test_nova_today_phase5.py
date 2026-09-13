"""Nova V2 Phase 5 connector hardening, owner re-check, and readiness."""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.helpers import now, uuid4 as helper_uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TODAY_HTML = (STATIC / "nova-today" / "index.html").read_text(encoding="utf-8")
TODAY_JS = (STATIC / "nova-today" / "today.js").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema
    from app.db.session import engine, init_platform_db

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> tuple[dict[str, str], str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"Authorization": f"Bearer {body['access_token']}"}, body["user_id"]


def _cleanup_accounts(user_id: str) -> None:
    from app.db.models import IntegrationAccount
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.query(IntegrationAccount).filter(IntegrationAccount.user_id == user_id).delete()
        db.commit()


def _add_account(
    user_id: str,
    *,
    provider: str = "gmail",
    expired: bool = False,
    account_id: str | None = None,
    refresh_token: str | None = "refresh-token",
):
    from app.db.models import IntegrationAccount
    from app.db.session import SessionLocal

    row_id = account_id or helper_uuid4()
    with SessionLocal() as db:
        db.add(
            IntegrationAccount(
                id=row_id,
                user_id=user_id,
                service="email",
                provider=provider,
                account_email=f"{provider}-owner@example.com",
                access_token="test-token",
                refresh_token=refresh_token,
                token_expires_at=now() - timedelta(hours=2) if expired else now() + timedelta(hours=2),
            )
        )
        db.commit()
    return row_id


def test_nova_today_phase5_ui_freshness_and_recheck_copy() -> None:
    assert "recheck-mailbox" in TODAY_HTML
    assert "Re-check a source" in TODAY_HTML
    assert "/api/nova/today/recheck" in TODAY_JS
    assert "freshness" in TODAY_JS
    assert "last_success_at" in TODAY_JS
    assert "data-recheck" in TODAY_JS
    assert "/api/nova/today/send" not in TODAY_JS


def test_nova_today_phase5_gmail_expired_has_no_refresh_helper(client: TestClient) -> None:
    owner, user_id = _login(client)
    _add_account(user_id, provider="gmail", expired=True)
    try:
        mailbox = client.get("/api/nova/today/mailbox", headers=owner)
        assert mailbox.status_code == 200, mailbox.text
        health = mailbox.json()["connector_health"]
        assert health["status"] == "stale"
        assert health["freshness"] in {"unknown", "stale", "aging"}
        assert mailbox.json()["items"] == []
        assert health["recheck_available"] == "yes"
        assert health["last_attempted_at"]
    finally:
        _cleanup_accounts(user_id)


def test_nova_today_phase5_outlook_refresh_reuse(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, user_id = _login(client)
    account_id = _add_account(user_id, provider="outlook", expired=True)
    calls: list[str] = []

    def fake_refresh(account):
        calls.append(account.id)
        return "outlook-refreshed-token"

    monkeypatch.setattr("app.ecosystem._refresh_outlook_if_needed", fake_refresh)
    monkeypatch.setattr(
        "app.ecosystem._outlook_inbox",
        lambda token, limit=12: [
            {
                "id": "outlook-1",
                "subject": "Outlook refreshed item",
                "from": "outlook@example.com",
                "date": now().isoformat(),
                "snippet": "Refreshed.",
                "unread": True,
            }
        ],
    )
    try:
        mailbox = client.get("/api/nova/today/mailbox", headers=owner)
        assert mailbox.status_code == 200, mailbox.text
        assert calls == [account_id]
        assert mailbox.json()["items"][0]["subject"] == "Outlook refreshed item"
        assert mailbox.json()["connector_health"]["status"] in {"connected", "degraded"}
        assert mailbox.json()["connector_health"]["freshness"] in {"fresh", "aging"}
        assert mailbox.json()["connector_health"]["last_success_at"]
    finally:
        _cleanup_accounts(user_id)


def test_nova_today_phase5_owner_recheck_and_audit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, user_id = _login(client)
    account_id = _add_account(user_id, provider="gmail")
    monkeypatch.setattr(
        "app.core.nova.today.mailbox.fetch_provider_messages",
        lambda account, limit=12: [
            {
                "id": "ext-recheck-1",
                "subject": "Phase 5 recheck mail",
                "from": "recheck@example.com",
                "date": now().isoformat(),
                "snippet": "Please review.",
                "unread": True,
            }
        ],
    )
    try:
        checked = client.post("/api/nova/today/recheck", headers=owner, json={})
        assert checked.status_code == 200, checked.text
        body = checked.json()
        assert body["mutated_external"] is False
        assert body["recheck_id"].startswith("NVR-")
        assert body["connector_health"]["status"] in {"connected", "degraded"}
        assert body["connector_health"]["connector_account_id"] == account_id
        assert "nothing was sent" in body["message"].lower()
        history = client.get("/api/nova/today/history", headers=owner)
        assert history.status_code == 200
        rec = next(row for row in history.json() if row["result_type"] == "source_rechecked")
        assert rec["actor_user_id"]
        assert rec["recommended_action"] == "recheck_source"
        dash = client.get("/api/nova/today/dashboard", headers=owner)
        assert dash.json()["connector_health"]["freshness"]
        assert dash.json()["connector_health"]["recheck_available"] == "yes"
    finally:
        _cleanup_accounts(user_id)


def test_nova_today_phase5_cross_owner_and_org_recheck_denied(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, owner_id = _login(client)
    staff, _staff_id = _login(client, "staff@amicor.local")
    account_id = _add_account(owner_id)
    monkeypatch.setattr(
        "app.core.nova.today.mailbox.fetch_provider_messages",
        lambda account, limit=12: [],
    )
    try:
        denied = client.post(
            "/api/nova/today/recheck",
            headers=staff,
            json={"connector_account_id": account_id},
        )
        assert denied.status_code == 403
        cross = client.post(
            "/api/nova/today/recheck",
            headers=owner,
            json={"organization_id": "org-not-the-caller"},
        )
        assert cross.status_code == 403
        staff_box = client.get("/api/nova/today/mailbox", headers=staff)
        assert staff_box.status_code == 200
        assert staff_box.json()["items"] == []
    finally:
        _cleanup_accounts(owner_id)


def test_nova_today_phase5_draft_and_task_reverification(client: TestClient) -> None:
    owner, _user_id = _login(client)
    draft_action = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "communications",
            "source_ref_id": f"phase5-draft-{uuid4().hex[:8]}",
            "title": "Phase 5 draft recheck",
            "recommended_action": "create_draft",
        },
    )
    drafted = client.post(
        f"/api/nova/today/actions/{draft_action.json()['action_id']}/approve",
        headers=owner,
        json={"draft_subject": "Phase 5 draft", "draft_body": "Draft only.", "draft_to": ["a@example.com"]},
    )
    assert drafted.json()["verification_status"] == "verified"
    draft_id = drafted.json()["draft_id"]
    checked = client.post(
        "/api/nova/today/recheck",
        headers=owner,
        json={"action_id": draft_action.json()["action_id"]},
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["verification_status"] == "verified"
    assert checked.json()["prior_verification"] == "verified"
    assert checked.json()["mutated_external"] is False

    from app.db.models import EmailDraftRecord
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.query(EmailDraftRecord).filter(EmailDraftRecord.id == draft_id).delete()
        db.commit()
    missing = client.post(
        "/api/nova/today/recheck",
        headers=owner,
        json={"action_id": draft_action.json()["action_id"]},
    )
    assert missing.json()["verification_status"] == "missing"
    assert missing.json()["result_ref_id"] == draft_id
    still_gone = client.get(f"/api/nova/today/actions/{draft_action.json()['action_id']}", headers=owner)
    assert still_gone.json()["result_ref_id"] == draft_id
    assert still_gone.json()["verification_status"] == "missing"

    task_action = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "government",
            "source_ref_id": f"phase5-task-{uuid4().hex[:8]}",
            "title": "Phase 5 task recheck",
            "recommended_action": "create_task",
        },
    )
    tasked = client.post(
        f"/api/nova/today/actions/{task_action.json()['action_id']}/approve",
        headers=owner,
        json={"task_title": "Phase 5 verified task"},
    )
    assert tasked.json()["verification_status"] == "verified"
    from app.core.nova.business.models import NovaBusinessTask

    with SessionLocal() as db:
        db.query(NovaBusinessTask).filter(NovaBusinessTask.task_id == tasked.json()["task_id"]).delete()
        db.commit()
    missing_task = client.post(
        "/api/nova/today/recheck",
        headers=owner,
        json={"action_id": task_action.json()["action_id"]},
    )
    assert missing_task.json()["verification_status"] == "missing"


def test_nova_today_phase5_source_unavailable_and_ask(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, user_id = _login(client)
    _add_account(user_id)

    def boom(*_args, **_kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr("app.core.nova.today.mailbox.fetch_provider_messages", boom)
    try:
        mailbox = client.get("/api/nova/today/mailbox", headers=owner)
        assert mailbox.status_code == 200
        assert mailbox.json()["connector_health"]["status"] == "unavailable"
        dash = client.get("/api/nova/today/dashboard", headers=owner)
        assert dash.status_code == 200
        asked = client.post(
            "/api/nova/today/ask",
            headers=owner,
            json={"question": "Is this connector stale or unavailable?"},
        )
        assert asked.status_code == 200, asked.text
        assert "does not execute" in asked.json()["fact_label"].lower()
        assert client.post("/api/nova/today/send", headers=owner).status_code == 403
        assert client.post("/api/nova/today/file", headers=owner).status_code == 403
        assert client.post("/api/nova/today/ledger", headers=owner).status_code == 403
        assert client.post("/api/nova/today/call", headers=owner).status_code == 403
        blocked = client.post(
            "/api/nova/today/actions",
            headers=owner,
            json={
                "source_module": "communications",
                "source_ref_id": "phase5-send",
                "title": "Do not send",
                "recommended_action": "send_email",
            },
        )
        assert blocked.status_code == 422
    finally:
        _cleanup_accounts(user_id)


def test_nova_today_phase5_readiness_and_recheck_action(client: TestClient) -> None:
    owner, _user_id = _login(client)
    ready = client.get("/api/nova/today/readiness", headers=owner)
    assert ready.status_code == 200, ready.text
    keys = {row["key"] for row in ready.json()["items"]}
    assert {
        "tenant_isolation",
        "connector_isolation",
        "prohibited_actions",
        "connector_freshness",
        "draft_verification",
        "task_verification",
        "no_production_deployment",
        "signed_in_owner_ui",
    } <= keys
    assert all(row["status"] in {"PASS", "BLOCKED", "NOT TESTED"} for row in ready.json()["items"])
    created = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "communications",
            "source_ref_id": f"phase5-recheck-{uuid4().hex[:8]}",
            "title": "Phase 5 recheck action",
            "recommended_action": "recheck_source",
        },
    )
    assert created.status_code == 200, created.text
    approved = client.post(
        f"/api/nova/today/actions/{created.json()['action_id']}/approve",
        headers=owner,
        json={},
    )
    assert approved.status_code == 200, approved.text
    assert "nothing was sent" in approved.json()["message"].lower() or "re-checked" in approved.json()["message"].lower()
