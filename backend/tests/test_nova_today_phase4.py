"""Nova V2 Phase 4 connector mailbox and result verification."""
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


def _add_account(user_id: str, *, provider: str = "gmail", expired: bool = False, account_id: str | None = None):
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
                token_expires_at=now() - timedelta(hours=2) if expired else now() + timedelta(hours=2),
            )
        )
        db.commit()
    return row_id


def test_nova_today_phase4_ui_connector_and_verification_copy() -> None:
    assert "connector-health" in TODAY_HTML
    assert "connector_health" in TODAY_JS
    assert "verification_label" in TODAY_JS
    assert "Mailbox state" in TODAY_JS
    assert "/api/nova/today/send" not in TODAY_JS
    assert "/send" not in TODAY_JS


def test_nova_today_phase4_connector_available(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, user_id = _login(client)
    account_id = _add_account(user_id)
    try:
        _phase4_connector_available_body(client, owner, account_id, monkeypatch)
    finally:
        _cleanup_accounts(user_id)


def _phase4_connector_available_body(client, owner, account_id, monkeypatch):
    monkeypatch.setattr(
        "app.core.nova.today.mailbox.fetch_provider_messages",
        lambda account, limit=12: [
            {
                "id": "ext-important-1",
                "subject": "Phase 4 important invoice",
                "from": "billing@example.com",
                "date": now().isoformat(),
                "snippet": "Please review the invoice.",
                "important": True,
                "unread": True,
            },
            {
                "id": "ext-unread-2",
                "subject": "Phase 4 unread note",
                "from": "ops@example.com",
                "date": now().isoformat(),
                "snippet": "Status update.",
                "important": False,
                "unread": True,
            },
        ],
    )
    mailbox = client.get("/api/nova/today/mailbox", headers=owner)
    assert mailbox.status_code == 200, mailbox.text
    body = mailbox.json()
    assert body["connector_health"]["status"] in {"connected", "degraded"}
    assert body["connector_health"]["connector_account_id"] == account_id
    subjects = [row["subject"] for row in body["items"]]
    assert subjects[0] == "Phase 4 important invoice"
    assert body["items"][0]["sender"] == "billing@example.com"
    assert body["items"][0]["unread"] is True
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert dash.status_code == 200
    comms = dash.json()["communications"]
    assert any(row["subject"] == "Phase 4 important invoice" for row in comms)
    assert dash.json()["connector_health"]["status"] in {"connected", "degraded"}


def test_nova_today_phase4_connector_unavailable_and_disconnected(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    staff, _staff_id = _login(client, "staff@amicor.local")
    empty = client.get("/api/nova/today/mailbox", headers=staff)
    assert empty.status_code == 200
    assert empty.json()["connector_health"]["status"] == "disconnected"
    assert empty.json()["items"] == []

    owner, user_id = _login(client)
    _add_account(user_id, provider="gmail")
    try:
        def boom(*_args, **_kwargs):
            raise RuntimeError("provider unavailable")

        monkeypatch.setattr("app.core.nova.today.mailbox.fetch_provider_messages", boom)
        broken = client.get("/api/nova/today/mailbox", headers=owner)
        assert broken.status_code == 200
        assert broken.json()["connector_health"]["status"] == "unavailable"
        dash = client.get("/api/nova/today/dashboard", headers=owner)
        assert dash.status_code == 200
        assert "communications" in dash.json()
    finally:
        _cleanup_accounts(user_id)


def test_nova_today_phase4_stale_connector(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, user_id = _login(client)
    _add_account(user_id, expired=True)
    try:
        def expired_token(*_args, **_kwargs):
            raise RuntimeError("token expired")

        monkeypatch.setattr("app.core.nova.today.mailbox.fetch_provider_messages", expired_token)
        stale = client.get("/api/nova/today/mailbox", headers=owner)
        assert stale.status_code == 200
        assert stale.json()["connector_health"]["status"] == "stale"
        assert stale.json()["items"] == []
    finally:
        _cleanup_accounts(user_id)


def test_nova_today_phase4_draft_and_task_verification(client: TestClient) -> None:
    owner, _user_id = _login(client)
    draft_action = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "communications",
            "source_ref_id": f"phase4-draft-{uuid4().hex[:8]}",
            "title": "Phase 4 create draft",
            "recommended_action": "create_draft",
        },
    )
    drafted = client.post(
        f"/api/nova/today/actions/{draft_action.json()['action_id']}/approve",
        headers=owner,
        json={"draft_subject": "Phase 4 draft", "draft_body": "Draft only.", "draft_to": ["a@example.com"]},
    )
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["draft_id"]
    assert drafted.json()["verification_status"] == "verified"
    history = client.get("/api/nova/today/history", headers=owner)
    draft_row = next(row for row in history.json() if row["action_id"] == draft_action.json()["action_id"])
    assert draft_row["verification_status"] == "verified"
    assert "verified" in (draft_row["verification_label"] or "").lower()

    from app.db.models import EmailDraftRecord
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.query(EmailDraftRecord).filter(EmailDraftRecord.id == drafted.json()["draft_id"]).delete()
        db.commit()
    missing_draft = client.get(f"/api/nova/today/actions/{draft_action.json()['action_id']}", headers=owner)
    assert missing_draft.json()["verification_status"] == "missing"
    assert missing_draft.json()["result_ref_id"] == drafted.json()["draft_id"]

    task_action = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "government",
            "source_ref_id": f"phase4-task-{uuid4().hex[:8]}",
            "title": "Phase 4 create task",
            "recommended_action": "create_task",
        },
    )
    tasked = client.post(
        f"/api/nova/today/actions/{task_action.json()['action_id']}/approve",
        headers=owner,
        json={"task_title": "Phase 4 verified task"},
    )
    assert tasked.status_code == 200, tasked.text
    assert tasked.json()["verification_status"] == "verified"
    from app.core.nova.business.models import NovaBusinessTask
    from app.db.session import SessionLocal as SessionLocal2

    with SessionLocal2() as db:
        db.query(NovaBusinessTask).filter(NovaBusinessTask.task_id == tasked.json()["task_id"]).delete()
        db.commit()
    missing_task = client.get(f"/api/nova/today/actions/{task_action.json()['action_id']}", headers=owner)
    assert missing_task.json()["verification_status"] == "missing"


def test_nova_today_phase4_ask_nova_and_prohibited(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, user_id = _login(client)
    _add_account(user_id)
    try:
        _phase4_ask_body(client, owner, monkeypatch)
    finally:
        _cleanup_accounts(user_id)


def _phase4_ask_body(client, owner, monkeypatch):
    monkeypatch.setattr(
        "app.core.nova.today.mailbox.fetch_provider_messages",
        lambda account, limit=12: [
            {
                "id": "ext-ask-1",
                "subject": "Phase 4 ask mailbox",
                "from": "ask@example.com",
                "date": now().isoformat(),
                "snippet": "Need a draft.",
                "unread": True,
            }
        ],
    )
    mailbox = client.get("/api/nova/today/mailbox", headers=owner)
    message_id = mailbox.json()["items"][0]["message_id"]
    asked = client.post(
        "/api/nova/today/ask",
        headers=owner,
        json={"question": "Summarize this mailbox item.", "source_ref_id": message_id},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["referenced_source_ref_id"] == message_id
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
            "source_ref_id": "phase4-send",
            "title": "Do not send",
            "recommended_action": "send_email",
        },
    )
    assert blocked.status_code == 422


def test_nova_today_phase4_tenant_isolation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    owner, owner_id = _login(client)
    staff, _staff_id = _login(client, "staff@amicor.local")
    account_id = _add_account(owner_id)
    try:
        _phase4_isolation_body(client, owner, staff, account_id, monkeypatch)
    finally:
        _cleanup_accounts(owner_id)


def _phase4_isolation_body(client, owner, staff, account_id, monkeypatch):
    monkeypatch.setattr(
        "app.core.nova.today.mailbox.fetch_provider_messages",
        lambda account, limit=12: [
            {
                "id": "ext-owner-only",
                "subject": "Owner mailbox only",
                "from": "secret@example.com",
                "date": now().isoformat(),
                "snippet": "Private.",
                "unread": True,
            }
        ],
    )
    owner_box = client.get("/api/nova/today/mailbox", headers=owner)
    assert owner_box.status_code == 200
    assert owner_box.json()["items"]
    staff_box = client.get("/api/nova/today/mailbox", headers=staff)
    assert staff_box.status_code == 200
    assert staff_box.json()["items"] == []
    denied = client.get(
        "/api/nova/today/mailbox",
        headers=staff,
        params={"connector_account_id": account_id},
    )
    assert denied.status_code == 403
    cross = client.get(
        "/api/nova/today/mailbox",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403
    message_id = owner_box.json()["items"][0]["message_id"]
    owner_dash = client.get("/api/nova/today/dashboard", headers=owner)
    staff_dash = client.get("/api/nova/today/dashboard", headers=staff)
    assert any(row["source_ref_id"] == message_id for row in owner_dash.json()["communications"])
    assert all(row["source_ref_id"] != message_id for row in staff_dash.json()["communications"])
