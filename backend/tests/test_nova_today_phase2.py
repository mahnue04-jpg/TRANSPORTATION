"""Nova V2 Phase 2 owner command center. Additive Today tests only."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

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


def test_nova_today_phase2_ui_workflow_copy() -> None:
    assert "Attention Now" in TODAY_HTML
    assert "What needs attention now" in TODAY_HTML
    assert "Government / Compliance" in TODAY_HTML
    assert "Business / Operations" in TODAY_HTML
    assert "Approval Queue" in TODAY_HTML
    assert "Ask Nova" in TODAY_HTML
    assert "Owner workflow" in TODAY_HTML
    assert "Prepare draft" in TODAY_JS
    assert "if_approved" in TODAY_JS
    assert "will_not_happen" in TODAY_JS
    assert "data-review" in TODAY_JS
    assert "/api/nova/today/send" not in TODAY_JS
    assert "/send" not in TODAY_JS


def test_nova_today_phase2_empty_states_and_trust_labels(client: TestClient) -> None:
    headers = _headers(client, "staff@amicor.local")
    dash = client.get("/api/nova/today/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["attention_now"] == [] or isinstance(body["attention_now"], list)
    assert body["communications"] == [] or isinstance(body["communications"], list)
    assert "source_health" in body
    statuses = {row["source"]: row["status"] for row in body["source_health"]}
    for source in ("communications", "government", "business", "workspace"):
        assert statuses[source] in {"ok", "empty", "unavailable"}
    assert set(body["trust_labels"]) == {
        "VERIFIED DATA",
        "USER-SAVED INFORMATION",
        "AI SUGGESTION",
        "ACTION REQUIRES APPROVAL",
    }
    assert all(row["source_module"] != "link" for row in body["approval_queue"])


def test_nova_today_phase2_real_communications_and_draft_only(client: TestClient) -> None:
    owner = _headers(client)
    created = client.post(
        "/api/nova/communications/messages",
        headers=owner,
        json={
            "sender": "pilot@example.com",
            "subject": "Need a demo window",
            "body": "Can we review the supervised agent?",
            "important": True,
        },
    )
    assert created.status_code == 200, created.text
    message_id = created.json()["message_id"]
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert dash.status_code == 200, dash.text
    comms = dash.json()["communications"]
    card = next(row for row in comms if row["source_ref_id"] == message_id)
    assert card["sender"] == "pilot@example.com"
    assert card["subject"] == "Need a demo window"
    assert card["recommended_action"] == "create_draft"
    assert card["trust_label"] in {"USER-SAVED INFORMATION", "ACTION REQUIRES APPROVAL"}
    assert card["if_approved"]
    assert "email send" in (card["will_not_happen"] or "").lower()
    assert card["priority_band"] in {"critical", "high", "normal", "low"}

    action = next(row for row in dash.json()["approval_queue"] if row["source_ref_id"] == message_id)
    drafted = client.post(
        f"/api/nova/today/actions/{action['action_id']}/approve",
        headers=owner,
        json={"draft_subject": "Re: Need a demo window", "draft_body": "Draft only.", "draft_to": ["pilot@example.com"]},
    )
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["draft_id"]
    assert drafted.json()["task_id"] is None
    assert "not" in drafted.json()["message"].lower()


def test_nova_today_phase2_acknowledge_create_task_and_duplicates(client: TestClient) -> None:
    owner = _headers(client)
    other = _headers(client, "staff@amicor.local")
    proposed = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": "phase2-ack",
            "title": "Acknowledge launch reminder",
            "recommended_action": "acknowledge",
        },
    )
    assert proposed.status_code == 200, proposed.text
    action_id = proposed.json()["action_id"]
    again = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": "phase2-ack",
            "title": "Acknowledge launch reminder",
            "recommended_action": "acknowledge",
        },
    )
    assert again.status_code == 200
    assert again.json()["action_id"] == action_id

    hidden = client.get(f"/api/nova/today/actions/{action_id}", headers=other)
    assert hidden.status_code == 404

    visible = client.get(f"/api/nova/today/actions/{action_id}", headers=owner)
    assert visible.status_code == 200
    assert visible.json()["why_recommended"]
    assert visible.json()["if_approved"]
    assert visible.json()["will_not_happen"]

    acked = client.post(f"/api/nova/today/actions/{action_id}/approve", headers=owner, json={})
    assert acked.status_code == 200, acked.text
    assert acked.json()["draft_id"] is None
    assert acked.json()["task_id"] is None

    duplicate = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": "phase2-ack",
            "title": "Acknowledge launch reminder",
            "recommended_action": "acknowledge",
        },
    )
    assert duplicate.status_code == 409

    task_action = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "government",
            "source_ref_id": "phase2-task",
            "title": "Create compliance follow-up",
            "recommended_action": "create_task",
        },
    )
    tasked = client.post(
        f"/api/nova/today/actions/{task_action.json()['action_id']}/approve",
        headers=owner,
        json={"task_title": "Phase 2 compliance follow-up"},
    )
    assert tasked.status_code == 200, tasked.text
    assert tasked.json()["task_id"]
    assert tasked.json()["draft_id"] is None


def test_nova_today_phase2_admin_visibility_and_tenant_isolation(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    admin = _headers(client, "admin@amicor.local")
    other = _headers(client, "staff@amicor.local")
    overdue = (date.today() - timedelta(days=1)).isoformat()
    created = client.post(
        "/api/nova/government/items",
        headers=owner,
        json={"title": "Phase 2 admin visibility license", "due_date": overdue, "status": "renewal_due"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["item_id"]

    owner_dash = client.get("/api/nova/today/dashboard", headers=owner)
    admin_dash = client.get("/api/nova/today/dashboard", headers=admin)
    other_dash = client.get("/api/nova/today/dashboard", headers=other)
    assert owner_dash.status_code == 200
    assert admin_dash.status_code == 200
    assert item_id in {row["source_ref_id"] for row in owner_dash.json()["government"]}
    assert item_id in {row["source_ref_id"] for row in admin_dash.json()["government"]}
    assert item_id not in {row["source_ref_id"] for row in other_dash.json()["government"]}

    owner_action = next(row for row in owner_dash.json()["approval_queue"] if row["source_ref_id"] == item_id)
    admin_can_read = client.get(f"/api/nova/today/actions/{owner_action['action_id']}", headers=admin)
    assert admin_can_read.status_code == 200
    staff_blocked = client.get(f"/api/nova/today/actions/{owner_action['action_id']}", headers=other)
    assert staff_blocked.status_code == 404
    cross = client.get("/api/nova/today/dashboard", headers=owner, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403


def test_nova_today_phase2_prohibited_actions_blocked(client: TestClient) -> None:
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
                "source_ref_id": f"banned-{banned}",
                "title": f"Banned {banned}",
                "recommended_action": banned,
            },
        )
        assert blocked.status_code == 422, banned


def test_nova_today_phase2_source_failure_is_honest(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("communications unavailable")

    monkeypatch.setattr("app.core.nova.today.service.communications_dashboard", boom)
    headers = _headers(client)
    dash = client.get("/api/nova/today/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert body["communications"] == []
    health = {row["source"]: row for row in body["source_health"]}
    assert health["communications"]["status"] == "unavailable"
    assert "invent" in health["communications"]["detail"].lower()
    assert "attention_now" in body
    assert "approval_queue" in body


def test_nova_today_phase2_priority_and_ask_with_selected_item(client: TestClient) -> None:
    owner = _headers(client)
    overdue = (date.today() - timedelta(days=4)).isoformat()
    created = client.post(
        "/api/nova/government/items",
        headers=owner,
        json={"title": "Phase 2 ranking license", "due_date": overdue, "status": "renewal_due"},
    )
    assert created.status_code == 200, created.text
    dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert dash.status_code == 200
    attention = dash.json()["attention_now"]
    assert attention
    assert attention[0]["title"].startswith("Overdue:")
    action = next(row for row in dash.json()["approval_queue"] if row["source_ref_id"] == created.json()["item_id"])
    asked = client.post(
        "/api/nova/today/ask",
        headers=owner,
        json={"question": "What should I do with this item?", "action_id": action["action_id"]},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"]
    assert "AI SUGGESTION" in asked.json()["fact_label"]
