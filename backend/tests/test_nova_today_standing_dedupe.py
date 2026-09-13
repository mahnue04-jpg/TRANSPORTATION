"""V2 Today standing-card uniqueness and smoke-row workflow hide."""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.policy import phase1_enabled
from app.main import app

STANDING = (
    ("business", "rec-attention", "acknowledge"),
    ("communications", "rec-drafts", "acknowledge"),
    ("link", "health", "open_link"),
    ("link", "delivery", "open_link"),
    ("link", "freight", "open_link"),
)
NOVA_TABS = (
    "/nova",
    "/nova/today",
    "/nova/workspace",
    "/nova/communications",
    "/nova/government",
    "/nova/business",
    "/nova/accounting",
    "/nova/accounting/aging",
    "/nova/accounting/trends",
    "/nova/payments/readiness",
    "/nova/freight",
    "/workspace",
    "/app",
)


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


def _count_logical(rows: list[dict], module: str, ref: str, action: str) -> int:
    return sum(
        1
        for row in rows
        if row.get("source_module") == module
        and row.get("source_ref_id") == ref
        and row.get("recommended_action") == action
    )


def test_same_org_second_viewer_does_not_mint_standing_cards(client: TestClient) -> None:
    assert phase1_enabled() is False
    dispatcher = _headers(client)
    admin = _headers(client, "admin@amicor.local")
    staff = _headers(client, "staff@amicor.local")
    overdue = (date.today() - timedelta(days=1)).isoformat()
    created = client.post(
        "/api/nova/government/items",
        headers=dispatcher,
        json={"title": "Standing-card seed license", "due_date": overdue, "status": "renewal_due"},
    )
    assert created.status_code == 200, created.text

    first = client.get("/api/nova/today/dashboard", headers=dispatcher)
    assert first.status_code == 200, first.text
    before = client.get("/api/nova/today/actions", headers=admin)
    assert before.status_code == 200
    before_counts = {key: _count_logical(before.json(), *key) for key in STANDING}
    for key, count in before_counts.items():
        assert count == 1, key

    second = client.get("/api/nova/today/dashboard", headers=admin)
    third = client.get("/api/nova/today/dashboard", headers=staff)
    assert second.status_code == 200
    assert third.status_code == 200
    after = client.get("/api/nova/today/actions", headers=admin)
    after_counts = {key: _count_logical(after.json(), *key) for key in STANDING}
    assert after_counts == before_counts

    admin_dash = second.json()
    for module, ref, action in STANDING:
        if module == "link":
            assert _count_logical(admin_dash["product_links"], module, ref, action) == 1
            assert _count_logical(admin_dash["approval_queue"], module, ref, action) == 0
        else:
            assert _count_logical(admin_dash["recommendations"], module, ref, action) == 1
            assert _count_logical(admin_dash["approval_queue"], module, ref, action) <= 1


def test_workflow_fixtures_hidden_from_today_but_kept_in_history(client: TestClient) -> None:
    owner = _headers(client)
    admin = _headers(client, "admin@amicor.local")
    proposed = client.post(
        "/api/nova/today/actions",
        headers=owner,
        json={
            "source_module": "business",
            "source_ref_id": "v2live-hide-from-workflow",
            "title": "Create live acceptance draft",
            "recommended_action": "acknowledge",
        },
    )
    assert proposed.status_code == 200, proposed.text
    action_id = proposed.json()["action_id"]
    dash = client.get("/api/nova/today/dashboard", headers=admin)
    assert dash.status_code == 200
    assert all(row.get("action_id") != action_id for row in dash.json()["approval_queue"])
    assert all(row.get("source_ref_id") != "v2live-hide-from-workflow" for row in dash.json()["attention_now"])
    approved = client.post(f"/api/nova/today/actions/{action_id}/approve", headers=owner, json={})
    assert approved.status_code == 200, approved.text
    history = client.get("/api/nova/today/history", headers=admin)
    assert history.status_code == 200
    assert any(row.get("action_id") == action_id for row in history.json())
    again = client.get("/api/nova/today/dashboard", headers=admin)
    assert all(row.get("action_id") != action_id for row in again.json()["recent_activity"])


def test_cross_org_and_routes_and_flag_off(client: TestClient) -> None:
    owner = _headers(client)
    assert phase1_enabled() is False
    assert client.get("/api/nova/autonomy/history", headers=owner).status_code == 404
    assert client.get("/api/nova/today/dashboard", headers=owner, params={"organization_id": "org-not-the-caller"}).status_code == 403
    passed = 0
    for path in NOVA_TABS:
        response = client.get(path, follow_redirects=True)
        assert response.status_code == 200, path
        passed += 1
    assert passed == 13
