"""Nova Core Phase 2: True Nova Workspace. Does not convert Health /workspace."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
WS_HTML = (STATIC / "nova-workspace" / "index.html").read_text(encoding="utf-8")
WS_JS = (STATIC / "nova-workspace" / "workspace.js").read_text(encoding="utf-8")
WS_CSS = (STATIC / "nova-workspace" / "workspace.css").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
FREIGHT_DIR = STATIC / "nova-freight"
HEALTH_HTML = (STATIC / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(client: TestClient, email: str = "dispatcher@amicor.local") -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, email)['access_token']}"}


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


def test_nova_workspace_route_loads(client: TestClient) -> None:
    response = client.get("/nova/workspace")
    assert response.status_code == 200
    assert "Nova Workspace" in response.text
    assert "Mrs. Nova Brain" in response.text
    assert "ops-shell.js" not in response.text
    assert 'src="/static/nova-workspace/workspace.js"' in response.text
    assert "Health ISF Workspace" not in response.text


def test_nova_workspace_signed_out_blocks_apis(client: TestClient) -> None:
    page = client.get("/nova/workspace")
    assert page.status_code == 200
    assert "Sign in to use Nova Workspace." in page.text
    assert client.get("/api/nova/workspace/dashboard").status_code == 401
    assert client.post(
        "/api/nova/workspace/projects",
        json={"title": "Should not persist"},
    ).status_code == 401


def test_nova_workspace_authenticated_dashboard_and_brain(client: TestClient) -> None:
    headers = _headers(client)
    dash = client.get("/api/nova/workspace/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert "recent_work" in body
    assert "active_projects" in body
    asked = client.post(
        "/api/nova/workspace/ask",
        headers=headers,
        json={"action": "ask", "question": "What should I work on next in Nova Workspace?"},
    )
    assert asked.status_code == 200, asked.text
    payload = asked.json()
    assert payload["answer"]
    assert payload["conversation_id"]
    assert "/api/nova/workspace/ask" in WS_JS
    assert "Mrs. Nova Brain" in WS_HTML


def test_nova_workspace_project_crud_and_archive(client: TestClient) -> None:
    headers = _headers(client)
    created = client.post(
        "/api/nova/workspace/projects",
        headers=headers,
        json={"title": "Launch notes", "description": "Nova-owned project only"},
    )
    assert created.status_code == 200, created.text
    workspace_id = created.json()["workspace_id"]
    assert workspace_id.startswith("NW-")
    assert created.json()["archived"] is False

    fetched = client.get(f"/api/nova/workspace/projects/{workspace_id}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "Launch notes"
    assert fetched.json()["last_opened_at"]

    updated = client.patch(
        f"/api/nova/workspace/projects/{workspace_id}",
        headers=headers,
        json={"title": "Launch notes v2", "status": "paused"},
    )
    assert updated.status_code == 200
    assert updated.json()["title"] == "Launch notes v2"
    assert updated.json()["status"] == "paused"

    archived = client.post(f"/api/nova/workspace/projects/{workspace_id}/archive", headers=headers)
    assert archived.status_code == 200
    assert archived.json()["archived"] is True
    listed = client.get("/api/nova/workspace/projects", headers=headers)
    assert all(row["workspace_id"] != workspace_id for row in listed.json())
    with_archived = client.get("/api/nova/workspace/projects?include_archived=true", headers=headers)
    assert any(row["workspace_id"] == workspace_id for row in with_archived.json())


def test_nova_workspace_user_and_org_isolation(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = client.post(
        "/api/nova/workspace/projects",
        headers=owner,
        json={"title": "Dispatcher only board"},
    )
    assert created.status_code == 200
    workspace_id = created.json()["workspace_id"]

    hidden = client.get(f"/api/nova/workspace/projects/{workspace_id}", headers=other)
    assert hidden.status_code == 404
    other_list = client.get("/api/nova/workspace/projects", headers=other)
    assert all(row["workspace_id"] != workspace_id for row in other_list.json())

    cross = client.get(
        f"/api/nova/workspace/projects/{workspace_id}",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403


def test_nova_workspace_file_and_conversation_association(client: TestClient) -> None:
    headers = _headers(client)
    project = client.post(
        "/api/nova/workspace/projects",
        headers=headers,
        json={"title": "File association project"},
    ).json()
    workspace_id = project["workspace_id"]
    added = client.post(
        "/api/nova/workspace/files",
        headers=headers,
        json={
            "filename": "briefing.txt",
            "content_type": "text/plain",
            "size_bytes": 12,
            "excerpt": "Nova workspace briefing notes",
            "workspace_id": workspace_id,
        },
    )
    assert added.status_code == 200, added.text
    assert added.json()["workspace_id"] == workspace_id
    files = client.get("/api/nova/workspace/files", headers=headers, params={"workspace_id": workspace_id})
    assert any(row["filename"] == "briefing.txt" for row in files.json())

    convo = client.post(
        "/api/nova/workspace/conversations",
        headers=headers,
        json={"title": "Planning thread", "workspace_id": workspace_id},
    )
    assert convo.status_code == 200, convo.text
    conversation_id = convo.json()["conversation_id"]
    asked = client.post(
        "/api/nova/workspace/ask",
        headers=headers,
        json={
            "action": "ask",
            "question": "Summarize this Nova project file work.",
            "workspace_id": workspace_id,
            "conversation_id": conversation_id,
        },
    )
    assert asked.status_code == 200
    detail = client.get(f"/api/nova/workspace/conversations/{conversation_id}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["messages"]) >= 2
    moved = client.patch(
        f"/api/nova/workspace/conversations/{conversation_id}",
        headers=headers,
        json={"workspace_id": workspace_id, "title": "Planning thread kept"},
    )
    assert moved.status_code == 200
    assert moved.json()["workspace_id"] == workspace_id


def test_nova_workspace_recent_work_and_search(client: TestClient) -> None:
    headers = _headers(client)
    created = client.post(
        "/api/nova/workspace/projects",
        headers=headers,
        json={"title": "Searchable Atlas", "description": "Unique nova workspace marker atlas"},
    )
    assert created.status_code == 200
    dash = client.get("/api/nova/workspace/dashboard", headers=headers)
    titles = [row["title"] for row in dash.json()["recent_work"]]
    assert any("Searchable Atlas" in title for title in titles)
    search = client.get("/api/nova/workspace/search", headers=headers, params={"q": "atlas"})
    assert search.status_code == 200, search.text
    assert search.json()["result_count"] >= 1
    assert any(hit["kind"] == "project" for hit in search.json()["hits"])
    assert "/api/search?" not in WS_JS


def test_nova_home_and_workspace_navigation() -> None:
    assert 'href="/nova/workspace" data-destination="workspace"' in HOME_HTML
    assert 'href="/nova">Nova Home' in WS_HTML
    assert 'href="/nova/communications">Communications' in WS_HTML
    assert 'href="/nova/government">Government' in WS_HTML
    assert 'href="/workspace">Health' in WS_HTML
    assert 'href="/app">Delivery' in WS_HTML
    assert 'href="/nova/freight">Freight' in WS_HTML
    assert 'href="/workspace"' in HOME_HTML


def test_nova_workspace_responsive_and_safety() -> None:
    bundle = WS_HTML + WS_JS + WS_CSS
    assert 'name="viewport"' in WS_HTML
    assert "width=device-width" in WS_HTML
    assert "@media (max-width: 720px)" in WS_CSS
    assert "@media (min-width: 1280px)" in WS_CSS
    assert "@media (min-width: 1600px)" in WS_CSS
    assert "Driver 001" not in bundle
    assert "DRV-001" not in bundle
    assert "sk_live" not in bundle
    assert "pk_live" not in bundle
    assert "stripe.com" not in bundle.lower()
    assert "hardware" not in WS_JS.lower()
    assert "nova-workspace" not in OPS_JS
    assert "nova-workspace" not in OPS_HTML
    assert "Health ISF Workspace" in HEALTH_HTML
    assert "/nova/workspace" not in HEALTH_HTML


def test_nova_workspace_does_not_mutate_frozen_products(client: TestClient) -> None:
    before = _counts()
    headers = _headers(client)
    client.get("/nova/workspace")
    client.get("/workspace")
    client.get("/nova")
    client.post(
        "/api/nova/workspace/projects",
        headers=headers,
        json={"title": "Isolation check project"},
    )
    after = _counts()
    assert before == after
    health = client.get("/workspace")
    assert health.status_code == 200
    assert "Health ISF Workspace" in health.text
    assert "nova-workspace/workspace.js" not in health.text
    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    assert "New Freight Request" in freight.text or "Freight / Logistics" in freight.text
    assert not any("workspace.js" in path.name for path in FREIGHT_DIR.glob("*"))
