"""Nova V2 Phase 1 Today / Command Center. Additive. Does not rewrite frozen V1 hubs."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
TODAY_HTML = (STATIC / "nova-today" / "index.html").read_text(encoding="utf-8")
TODAY_JS = (STATIC / "nova-today" / "today.js").read_text(encoding="utf-8")
TODAY_CSS = (STATIC / "nova-today" / "today.css").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
HEALTH_HTML = (STATIC / "index.html").read_text(encoding="utf-8")
FROZEN_V1 = [
    STATIC / "nova-home" / "index.html",
    STATIC / "nova-home" / "home.js",
    STATIC / "nova-workspace" / "index.html",
    STATIC / "nova-workspace" / "workspace.js",
    STATIC / "nova-communications" / "index.html",
    STATIC / "nova-communications" / "communications.js",
    STATIC / "nova-government" / "index.html",
    STATIC / "nova-government" / "government.js",
    STATIC / "nova-business" / "index.html",
    STATIC / "nova-business" / "business.js",
    ROOT / "app" / "core" / "nova" / "router.py",
    ROOT / "app" / "core" / "nova" / "service.py",
]


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


def _counts() -> dict[str, int]:
    from app.core.nova.freight.models import NovaFreightShipment
    from app.modules.health_isf.models import HealthISFRide
    from app.modules.platform_ops.models import PlatformDriverOnboardingApplication

    with SessionLocal() as db:
        return {
            "freight": db.query(NovaFreightShipment).count(),
            "health_rides": db.query(HealthISFRide).count(),
            "driver_apps": db.query(PlatformDriverOnboardingApplication).count(),
            "driver_001": db.query(PlatformDriverOnboardingApplication)
            .filter(PlatformDriverOnboardingApplication.internal_driver_number == "DRV-001")
            .count(),
        }


def test_nova_today_route_loads(client: TestClient) -> None:
    response = client.get("/nova/today")
    assert response.status_code == 200
    assert "Today / Command Center" in response.text
    assert "Mrs. Nova Brain" in response.text
    assert "What needs attention now" in response.text
    assert "ACTION REQUIRES APPROVAL" in response.text
    assert "ops-shell.js" not in response.text
    assert "command-center" not in response.text
    assert 'src="/static/nova-today/today.js"' in response.text


def test_nova_today_trust_labels_and_responsive() -> None:
    for label in ("VERIFIED DATA", "USER-SAVED INFORMATION", "AI SUGGESTION", "ACTION REQUIRES APPROVAL"):
        assert label in TODAY_HTML
    assert "Mrs. Nova Brain" in TODAY_HTML
    assert "mrs-nova-avatar" in TODAY_HTML
    assert 'name="viewport"' in TODAY_HTML
    assert "@media (max-width: 720px)" in TODAY_CSS
    assert "@media (min-width: 1280px)" in TODAY_CSS
    assert "@media (min-width: 1600px)" in TODAY_CSS
    assert "min-height: 44px" in TODAY_CSS
    assert "Snooze 24h" in TODAY_JS
    assert "/actions/" in TODAY_JS and "snooze" in TODAY_JS
    assert "hardware" not in TODAY_JS.lower()
    assert "gpio" not in TODAY_JS.lower()
    assert "nfc" not in TODAY_JS.lower()
    assert "bluetooth" not in TODAY_JS.lower()
    assert "/api/nova/command-center" not in TODAY_JS
    assert "/api/nova/actions" not in TODAY_JS
    assert "/api/email/send" not in TODAY_JS
    assert "sk_live" not in TODAY_JS
    assert "pk_live" not in TODAY_JS


def test_nova_today_signed_out_blocks_apis(client: TestClient) -> None:
    assert client.get("/api/nova/today/dashboard").status_code == 401
    assert client.post("/api/nova/today/ask", json={"question": "blocked"}).status_code == 401


def test_nova_today_dashboard_and_brain(client: TestClient) -> None:
    headers = _headers(client)
    dash = client.get("/api/nova/today/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert "attention_now" in body
    assert "communications" in body
    assert "government" in body
    assert "business" in body
    assert "workspace" in body
    assert "product_links" in body
    assert "recommendations" in body
    assert "approval_queue" in body
    hrefs = {row["href"] for row in body["product_links"]}
    assert "/workspace" in hrefs
    assert "/app" in hrefs
    assert "/nova/freight" in hrefs
    asked = client.post(
        "/api/nova/today/ask",
        headers=headers,
        json={"question": "What needs attention now?"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"]
    assert "AI SUGGESTION" in asked.json()["fact_label"]


def test_nova_today_isolation_persistence_and_allowed_actions(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    overdue = (date.today() - timedelta(days=2)).isoformat()
    created = client.post(
        "/api/nova/government/items",
        headers=owner,
        json={"title": "Today isolation license", "due_date": overdue, "status": "renewal_due"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["item_id"]

    owner_dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert owner_dash.status_code == 200, owner_dash.text
    owner_refs = {row["source_ref_id"] for row in owner_dash.json()["government"]}
    assert item_id in owner_refs
    other_dash = client.get("/api/nova/today/dashboard", headers=other)
    assert other_dash.status_code == 200
    other_refs = {row["source_ref_id"] for row in other_dash.json()["government"]}
    assert item_id not in other_refs
    cross = client.get("/api/nova/today/dashboard", headers=owner, params={"organization_id": "org-not-the-caller"})
    assert cross.status_code == 403

    owner_action = next(row for row in owner_dash.json()["approval_queue"] if row["source_ref_id"] == item_id)
    hidden = client.post(
        f"/api/nova/today/actions/{owner_action['action_id']}/dismiss",
        headers=other,
    )
    assert hidden.status_code == 404

    dismissed = client.post(
        f"/api/nova/today/actions/{owner_action['action_id']}/dismiss",
        headers=owner,
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    again = client.get("/api/nova/today/dashboard", headers=owner)
    assert all(row["source_ref_id"] != item_id for row in again.json()["attention_now"])
    assert all(row["action_id"] != owner_action["action_id"] for row in again.json()["approval_queue"])
    listed = client.get("/api/nova/today/actions", headers=owner)
    kept = next(row for row in listed.json() if row["action_id"] == owner_action["action_id"])
    assert kept["status"] == "dismissed"

    proposed = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": "manual-task",
            "title": "Create a follow-up task",
            "recommended_action": "create_task",
            "href": "/nova/business",
        },
    )
    assert proposed.status_code == 200, proposed.text
    approved = client.post(
        f"/api/nova/today/actions/{proposed.json()['action_id']}/approve",
        headers=owner,
        json={"task_title": "Today approved follow-up"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["task_id"]
    tasks = client.get("/api/nova/business/tasks", headers=owner)
    assert any(row["task_id"] == approved.json()["task_id"] for row in tasks.json())

    draft_action = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "communications",
            "source_ref_id": "manual-draft",
            "title": "Draft a customer note",
            "recommended_action": "create_draft",
            "href": "/nova/communications",
        },
    )
    drafted = client.post(
        f"/api/nova/today/actions/{draft_action.json()['action_id']}/approve",
        headers=owner,
        json={"draft_subject": "Today draft", "draft_body": "Nothing was sent.", "draft_to": ["noreply@example.com"]},
    )
    assert drafted.status_code == 200, drafted.text
    assert drafted.json()["draft_id"]
    drafts = client.get("/api/nova/communications/drafts", headers=owner)
    assert any(row["draft_id"] == drafted.json()["draft_id"] for row in drafts.json())

    assert client.post("/api/nova/today/send", headers=owner).status_code == 403
    assert client.post("/api/nova/today/file", headers=owner).status_code == 403
    assert client.post("/api/nova/today/ledger", headers=owner).status_code == 403
    assert client.post("/api/nova/today/call", headers=owner).status_code == 403


def test_nova_today_does_not_mutate_frozen_products(client: TestClient) -> None:
    before = _counts()
    headers = _headers(client)
    client.get("/nova/today")
    client.get("/nova")
    client.get("/workspace")
    client.get("/nova/freight")
    client.get("/app")
    client.get("/api/nova/today/dashboard", headers=headers)
    after = _counts()
    assert before == after
    assert "Driver 001" not in TODAY_HTML + TODAY_JS
    assert "DRV-001" not in TODAY_HTML + TODAY_JS
    assert "Health ISF Workspace" in HEALTH_HTML
    assert "/nova/today" not in HEALTH_HTML
    assert "nova-today" not in OPS_HTML
    assert "nova-today" not in OPS_JS
    assert "Coming later" not in HOME_HTML or HOME_HTML.count("Coming later") == 0
    health = client.get("/workspace")
    assert health.status_code == 200
    assert "Health ISF Workspace" in health.text
    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    assert "Freight / Logistics" in freight.text or "New Freight Request" in freight.text
    delivery = client.get("/app")
    assert delivery.status_code == 200
    assert "AMICOR Delivery" in delivery.text


def test_nova_today_did_not_edit_frozen_v1_files() -> None:
    for path in FROZEN_V1:
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "nova_v2_command_actions" not in text
        assert "/api/nova/today" not in text


def test_nova_today_schema_ensure_is_additive_and_dialect_safe() -> None:
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema, snooze_column_sql
    from app.db.session import engine, init_platform_db
    from sqlalchemy import inspect

    assert "TIMESTAMPTZ" in snooze_column_sql("postgresql")
    assert "IF NOT EXISTS" in snooze_column_sql("postgresql")
    assert "DATETIME" in snooze_column_sql("sqlite")
    init_platform_db()
    ensure_nova_today_schema(engine)
    ensure_nova_today_schema(engine)
    columns = {col["name"] for col in inspect(engine).get_columns("nova_v2_command_actions")}
    assert "snoozed_until" in columns


def test_nova_today_rank_score_boosts_overdue() -> None:
    from app.core.nova.today.schemas import NovaTodayCard
    from app.core.nova.today.service import rank_score

    overdue = NovaTodayCard(
        source_module="government",
        source_ref_id="gov-overdue",
        title="Overdue: license",
        href="/nova/government",
        trust_label="USER-SAVED INFORMATION",
        priority=95,
        recommended_action="create_task",
    )
    workspace = NovaTodayCard(
        source_module="workspace",
        source_ref_id="ws-1",
        title="Project: notes",
        href="/nova/workspace",
        trust_label="USER-SAVED INFORMATION",
        priority=95,
        recommended_action="open_link",
    )
    assert rank_score(overdue) > rank_score(workspace)


def test_nova_today_snooze_hides_and_returns(client: TestClient) -> None:
    from datetime import timedelta

    from app.core.nova.today.models import NovaV2CommandAction
    from app.helpers import now

    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    overdue = (date.today() - timedelta(days=3)).isoformat()
    created = client.post(
        "/api/nova/government/items",
        headers=owner,
        json={"title": "Snooze ranking license", "due_date": overdue, "status": "renewal_due"},
    )
    assert created.status_code == 200, created.text
    item_id = created.json()["item_id"]

    dash = client.get("/api/nova/today/dashboard", headers=owner)
    assert dash.status_code == 200, dash.text
    titles = [row["title"] for row in dash.json()["attention_now"]]
    assert any(row["source_ref_id"] == item_id for row in dash.json()["attention_now"])
    assert titles[0].startswith("Overdue:")
    action = next(row for row in dash.json()["approval_queue"] if row["source_ref_id"] == item_id)

    hidden = client.post(
        f"/api/nova/today/actions/{action['action_id']}/snooze",
        headers=other,
        json={"hours": 24},
    )
    assert hidden.status_code == 404

    bad_hours = client.post(
        f"/api/nova/today/actions/{action['action_id']}/snooze",
        headers=owner,
        json={"hours": 7},
    )
    assert bad_hours.status_code == 422

    snoozed = client.post(
        f"/api/nova/today/actions/{action['action_id']}/snooze",
        headers=owner,
        json={"hours": 24},
    )
    assert snoozed.status_code == 200, snoozed.text
    assert snoozed.json()["status"] == "snoozed"
    assert snoozed.json()["snoozed_until"]

    after = client.get("/api/nova/today/dashboard", headers=owner)
    assert all(row["source_ref_id"] != item_id for row in after.json()["attention_now"])
    assert all(row["action_id"] != action["action_id"] for row in after.json()["approval_queue"])
    listed = client.get("/api/nova/today/actions", headers=owner)
    kept = next(row for row in listed.json() if row["action_id"] == action["action_id"])
    assert kept["status"] == "snoozed"

    with SessionLocal() as db:
        row = db.query(NovaV2CommandAction).filter(NovaV2CommandAction.action_id == action["action_id"]).one()
        row.snoozed_until = now() - timedelta(minutes=1)
        db.commit()

    woken = client.get("/api/nova/today/dashboard", headers=owner)
    assert any(row["source_ref_id"] == item_id for row in woken.json()["attention_now"])
    assert any(row["action_id"] == action["action_id"] for row in woken.json()["approval_queue"])
