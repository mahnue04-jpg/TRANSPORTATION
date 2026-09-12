"""Nova V2 Phase 3 audit history, deep links, and communications readiness."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
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


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def test_nova_today_phase3_ui_audit_and_source_copy() -> None:
    assert "Recent Activity" in TODAY_HTML
    assert "source-health" in TODAY_HTML
    assert "Open source" in TODAY_JS
    assert "related_history" in TODAY_JS
    assert "why_surfaced" in TODAY_JS
    assert "source_href" in TODAY_JS
    assert "/api/nova/today/send" not in TODAY_JS
    assert "/send" not in TODAY_JS


def test_nova_today_phase3_history_from_real_decisions(client: TestClient) -> None:
    owner = _headers(client)
    ref = _unique("phase3-history")
    created = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": ref,
            "title": "Phase 3 acknowledge history",
            "recommended_action": "acknowledge",
        },
    )
    assert created.status_code == 200, created.text
    action_id = created.json()["action_id"]
    approved = client.post(f"/api/nova/today/actions/{action_id}/approve", headers=owner, json={})
    assert approved.status_code == 200, approved.text

    history = client.get("/api/nova/today/history", headers=owner)
    assert history.status_code == 200, history.text
    item = next(row for row in history.json() if row["action_id"] == action_id)
    assert item["prior_status"] == "proposed"
    assert item["resulting_status"] == "done"
    assert item["result_type"] == "acknowledged"
    assert item["source_module"] == "business"
    assert item["source_ref_id"] == ref
    assert item["actor_user_id"]
    assert item["decided_at"]
    assert item["recommended_action"] == "acknowledge"
    assert item["trust_label"]
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert dash.status_code == 200
    assert any(row["action_id"] == action_id for row in dash.json()["recent_activity"])


def test_nova_today_phase3_deep_links_valid_and_missing(client: TestClient) -> None:
    owner = _headers(client)
    created = client.post(
        "/api/nova/communications/messages",
        headers=owner,
        json={"sender": "phase3@example.com", "subject": "Phase 3 deep link", "body": "Real saved message."},
    )
    assert created.status_code == 200, created.text
    message_id = created.json()["message_id"]
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    card = next(row for row in dash.json()["communications"] if row["source_ref_id"] == message_id)
    assert card["source_href"] == "/nova/communications"
    assert card["href"] == "/nova/communications"
    assert card["sender"] == "phase3@example.com"
    assert card["received_at"]

    missing = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": _unique("missing-source"),
            "title": "Missing source should not invent a URL",
            "recommended_action": "acknowledge",
        },
    )
    assert missing.status_code == 200, missing.text
    reviewed = client.get(f"/api/nova/today/actions/{missing.json()['action_id']}", headers=owner)
    assert reviewed.status_code == 200
    assert reviewed.json()["source_href"] is None
    assert reviewed.json()["source_details"] is None


def test_nova_today_phase3_communications_connector_states(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _headers(client)
    created = client.post(
        "/api/nova/communications/messages",
        headers=owner,
        json={
            "sender": "local@example.com",
            "subject": "Phase 3 local only",
            "body": "Saved locally.",
            "important": True,
        },
    )
    assert created.status_code == 200, created.text
    disconnected = client.get("/api/nova/today/dashboard", headers=owner)
    health = {row["source"]: row for row in disconnected.json()["source_health"]}
    assert health["communications"]["status"] in {"ok", "partial", "empty"}
    assert health["communications"]["connector"] == "disconnected"
    if health["communications"]["status"] == "partial":
        assert "no mailbox connector" in health["communications"]["detail"].lower()

    monkeypatch.setattr("app.core.nova.communications.service._connected", lambda *_args, **_kwargs: True)
    connected = client.get("/api/nova/today/dashboard", headers=owner)
    connected_health = {row["source"]: row for row in connected.json()["source_health"]}
    assert connected_health["communications"]["connector"] == "connected"
    assert connected_health["communications"]["status"] in {"ok", "empty"}

    def boom(*_args, **_kwargs):
        raise RuntimeError("mailbox unavailable")

    monkeypatch.setattr("app.core.nova.today.service.communications_dashboard", boom)
    broken = client.get("/api/nova/today/dashboard", headers=owner)
    assert broken.status_code == 200
    broken_health = {row["source"]: row for row in broken.json()["source_health"]}
    assert broken_health["communications"]["status"] == "unavailable"
    assert broken.json()["communications"] == []
    assert "attention_now" in broken.json()


def test_nova_today_phase3_ask_nova_action_and_source_context(client: TestClient) -> None:
    owner = _headers(client)
    created = client.post(
        "/api/nova/communications/messages",
        headers=owner,
        json={"sender": "ask@example.com", "subject": "Phase 3 ask context", "body": "Need a draft only."},
    )
    message_id = created.json()["message_id"]
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    action = next(row for row in dash.json()["approval_queue"] if row["source_ref_id"] == message_id)
    asked_action = client.post(
        "/api/nova/today/ask",
        headers=owner,
        json={"question": "What should I do with this action?", "action_id": action["action_id"]},
    )
    assert asked_action.status_code == 200, asked_action.text
    assert asked_action.json()["referenced_action_id"] == action["action_id"]
    assert asked_action.json()["referenced_source_ref_id"] == message_id
    assert asked_action.json()["source_href"] in {None, "/nova/communications"}
    assert "does not execute" in asked_action.json()["fact_label"].lower()

    asked_source = client.post(
        "/api/nova/today/ask",
        headers=owner,
        json={"question": "Summarize this source record.", "source_ref_id": message_id},
    )
    assert asked_source.status_code == 200, asked_source.text
    assert asked_source.json()["referenced_source_ref_id"] == message_id
    assert asked_source.json()["answer"]


def test_nova_today_phase3_review_panel_fields_and_related_history(client: TestClient) -> None:
    owner = _headers(client)
    overdue = (date.today() - timedelta(days=2)).isoformat()
    item = client.post(
        "/api/nova/government/items",
        headers=owner,
        json={"title": "Phase 3 review license", "due_date": overdue, "status": "renewal_due"},
    )
    assert item.status_code == 200, item.text
    item_id = item.json()["item_id"]
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    action = next(row for row in dash.json()["approval_queue"] if row["source_ref_id"] == item_id)
    reviewed = client.get(f"/api/nova/today/actions/{action['action_id']}", headers=owner)
    body = reviewed.json()
    assert body["why_surfaced"]
    assert body["if_approved"]
    assert body["will_not_happen"]
    assert body["source_href"] == "/nova/government"
    assert body["source_details"]
    assert body["source_details"]["title"]
    assert isinstance(body["related_history"], list)

    client.post(f"/api/nova/today/actions/{action['action_id']}/dismiss", headers=owner)
    again = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "government",
            "source_ref_id": item_id,
            "title": "Phase 3 review license again",
            "recommended_action": "acknowledge",
        },
    )
    assert again.status_code == 200, again.text
    related = client.get(f"/api/nova/today/actions/{again.json()['action_id']}", headers=owner)
    assert any(row["action_id"] == action["action_id"] for row in related.json()["related_history"])


def test_nova_today_phase3_prohibited_actions_still_blocked(client: TestClient) -> None:
    owner = _headers(client)
    assert client.post("/api/nova/today/send", headers=owner).status_code == 403
    assert client.post("/api/nova/today/file", headers=owner).status_code == 403
    assert client.post("/api/nova/today/ledger", headers=owner).status_code == 403
    assert client.post("/api/nova/today/call", headers=owner).status_code == 403
    for banned in ("send_email", "submit_form", "payment", "stripe", "ledger", "call"):
        blocked = client.post(
            "/api/nova/today/actions",
            headers=owner,
            json={
                "source_module": "business",
                "source_ref_id": _unique(f"banned-{banned}"),
                "title": f"Banned {banned}",
                "recommended_action": banned,
            },
        )
        assert blocked.status_code == 422, banned


def test_nova_today_phase3_tenant_isolation_history_and_links(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    staff = _headers(client, "staff@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    created = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "workspace",
            "source_ref_id": _unique("phase3-iso"),
            "title": "Owner-only history item",
            "recommended_action": "acknowledge",
        },
    )
    action_id = created.json()["action_id"]
    client.post(f"/api/nova/today/actions/{action_id}/approve", headers=owner, json={})

    owner_history = {row["action_id"] for row in client.get("/api/nova/today/history", headers=owner).json()}
    staff_history = {row["action_id"] for row in client.get("/api/nova/today/history", headers=staff).json()}
    admin_history = {row["action_id"] for row in client.get("/api/nova/today/history", headers=admin).json()}
    assert action_id in owner_history
    assert action_id not in staff_history
    assert action_id in admin_history
    assert client.get(f"/api/nova/today/actions/{action_id}", headers=staff).status_code == 404
    assert client.get("/api/nova/today/history", headers=owner, params={"organization_id": "org-not-the-caller"}).status_code == 403
    assert client.get("/api/nova/today/dashboard", headers=owner, params={"organization_id": "org-not-the-caller"}).status_code == 403


def test_nova_today_phase3_empty_and_duplicate_safe(client: TestClient) -> None:
    staff = _headers(client, "staff@amicor.local")
    dash = client.get("/api/nova/today/dashboard", headers=staff)
    assert dash.status_code == 200
    assert isinstance(dash.json()["recent_activity"], list)
    statuses = {row["source"]: row["status"] for row in dash.json()["source_health"]}
    for source in ("communications", "government", "business", "workspace"):
        assert statuses[source] in {"ok", "empty", "unavailable", "partial"}

    owner = _headers(client)
    ref = _unique("phase3-dup")
    first = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": ref,
            "title": "Phase 3 duplicate",
            "recommended_action": "acknowledge",
        },
    )
    second = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": ref,
            "title": "Phase 3 duplicate",
            "recommended_action": "acknowledge",
        },
    )
    assert first.json()["action_id"] == second.json()["action_id"]
    client.post(f"/api/nova/today/actions/{first.json()['action_id']}/approve", headers=owner, json={})
    third = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": ref,
            "title": "Phase 3 duplicate",
            "recommended_action": "acknowledge",
        },
    )
    assert third.status_code == 409


def test_nova_today_phase3_source_health_partial_helper() -> None:
    from app.core.nova.today.links import module_page, source_href
    from app.core.nova.today.service import _health

    empty_disconnected = _health("communications", "ok", count=0, email_connected=False)
    assert empty_disconnected.status == "empty"
    assert empty_disconnected.connector == "disconnected"
    partial = _health("communications", "ok", count=2, email_connected=False)
    assert partial.status == "partial"
    connected = _health("communications", "ok", count=2, email_connected=True)
    assert connected.status == "ok"
    assert connected.connector == "connected"
    assert module_page("communications") == "/nova/communications"
    assert module_page("unknown") is None
    assert callable(source_href)
