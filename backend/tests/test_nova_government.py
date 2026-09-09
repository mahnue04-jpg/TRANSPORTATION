"""Nova Core Phase 4: Government Services Hub. Organization only. No agency filing."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.government.schemas import GOV_STATUSES, VERIFICATION_STATES
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
GOV_HTML = (STATIC / "nova-government" / "index.html").read_text(encoding="utf-8")
GOV_JS = (STATIC / "nova-government" / "government.js").read_text(encoding="utf-8")
GOV_CSS = (STATIC / "nova-government" / "government.css").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
WS_HTML = (STATIC / "nova-workspace" / "index.html").read_text(encoding="utf-8")
COMMS_HTML = (STATIC / "nova-communications" / "index.html").read_text(encoding="utf-8")
OPS_HTML = (STATIC / "ops-shell.html").read_text(encoding="utf-8")
OPS_JS = (STATIC / "ops-shell.js").read_text(encoding="utf-8")
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


def _create_item(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    payload = {
        "title": "Minnesota business registration research",
        "agency": "Minnesota Secretary of State",
        "government_level": "state",
        "state": "MN",
        "county": "Hennepin",
        "city": "Minneapolis",
        "category": "business_registration",
        "description": "USER-SAVED INFORMATION: find registration page.",
        "source_reference": "https://example.gov/mn-registration",
        "status": "researching",
        "filing_status": "not_filed",
        "notes": "Organizational research only.",
    }
    payload.update(overrides)
    created = client.post("/api/nova/government/items", headers=headers, json=payload)
    assert created.status_code == 200, created.text
    return created.json()


def test_nova_government_route_loads(client: TestClient) -> None:
    response = client.get("/nova/government")
    assert response.status_code == 200
    assert "Government Services" in response.text
    assert "Mrs. Nova Brain" in response.text
    assert "ops-shell.js" not in response.text
    assert 'src="/static/nova-government/government.js"' in response.text
    assert "Health ISF Workspace" not in response.text
    assert "not connected to live agency filing systems" in response.text


def test_nova_government_signed_out_blocks_apis(client: TestClient) -> None:
    assert client.get("/api/nova/government/dashboard").status_code == 401
    assert client.post(
        "/api/nova/government/items",
        json={"title": "Blocked without JWT"},
    ).status_code == 401
    assert client.post(
        "/api/nova/government/ask",
        json={"action": "ask", "question": "blocked"},
    ).status_code == 401


def test_nova_government_dashboard_sections(client: TestClient) -> None:
    headers = _headers(client)
    dash = client.get("/api/nova/government/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    keys = {row["key"] for row in body["sections"]}
    for expected in (
        "federal",
        "state",
        "county",
        "city",
        "licensing",
        "taxes",
        "grants",
        "certifications",
        "transportation",
        "business_registration",
        "compliance",
        "benefits",
        "forms",
    ):
        assert expected in keys
    assert "saved_work" in body
    assert "upcoming_deadlines" in body
    assert "renewals" in body
    assert "overdue" in body
    assert "waiting_response" in body
    assert "recently_completed" in body
    html_text = GOV_HTML.replace("&amp;", "&")
    for label in (
        "Federal",
        "State",
        "County",
        "City / Local",
        "Licensing & Permits",
        "Taxes",
        "Grants & Funding",
        "Certifications",
        "Transportation / DOT",
        "Business Registration",
        "Compliance",
        "Benefits / Public Services",
        "Forms & Documents",
        "Deadlines",
        "Saved Government Work",
    ):
        assert label in html_text


def test_nova_government_work_item_crud_statuses_and_jurisdiction(client: TestClient) -> None:
    headers = _headers(client)
    created = _create_item(client, headers)
    item_id = created["item_id"]
    assert item_id.startswith("NG-")
    assert created["government_level"] == "state"
    assert created["state"] == "MN"
    assert created["county"] == "Hennepin"
    assert created["city"] == "Minneapolis"
    assert created["agency"] == "Minnesota Secretary of State"
    assert created["status"] == "researching"
    assert created["filing_status"] == "not_filed"
    assert created["created_at"]
    assert created["updated_at"]

    listed = client.get("/api/nova/government/items", headers=headers)
    assert any(row["item_id"] == item_id for row in listed.json())
    detail = client.get(f"/api/nova/government/items/{item_id}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["title"] == created["title"]

    for status in GOV_STATUSES:
        patched = client.patch(
            f"/api/nova/government/items/{item_id}",
            headers=headers,
            json={"status": status, "government_level": "federal", "category": "licensing"},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["status"] == status
        assert patched.json()["government_level"] == "federal"

    invalid = client.patch(
        f"/api/nova/government/items/{item_id}",
        headers=headers,
        json={"status": "filed_with_irs"},
    )
    assert invalid.status_code == 422


def test_nova_government_deadlines_renewals_and_calendar_link(client: TestClient) -> None:
    headers = _headers(client)
    due = date.today() + timedelta(days=10)
    renewal = date.today() + timedelta(days=30)
    overdue = date.today() - timedelta(days=3)
    current = _create_item(
        client,
        headers,
        title="License renewal window",
        category="licensing",
        due_date=due.isoformat(),
        renewal_date=renewal.isoformat(),
        status="renewal_due",
    )
    waiting = _create_item(
        client,
        headers,
        title="Agency response pending",
        status="waiting_response",
        due_date=overdue.isoformat(),
    )
    completed = _create_item(
        client,
        headers,
        title="Closed research note",
        status="closed",
    )
    dash = client.get("/api/nova/government/dashboard", headers=headers)
    body = dash.json()
    assert any(row["item_id"] == current["item_id"] for row in body["upcoming_deadlines"])
    assert any(row["item_id"] == current["item_id"] for row in body["renewals"])
    assert any(row["item_id"] == waiting["item_id"] for row in body["overdue"])
    assert any(row["item_id"] == waiting["item_id"] for row in body["waiting_response"])
    assert any(row["item_id"] == completed["item_id"] for row in body["recently_completed"])

    linked = client.post(f"/api/nova/government/items/{current['item_id']}/calendar", headers=headers)
    assert linked.status_code == 200, linked.text
    assert linked.json()["calendar_event_id"]
    events = client.get("/api/nova/communications/events", headers=headers)
    assert any("License renewal window" in row["title"] for row in events.json())


def test_nova_government_checklist_and_workspace_file_link(client: TestClient) -> None:
    headers = _headers(client)
    project = client.post(
        "/api/nova/workspace/projects",
        headers=headers,
        json={"title": "Government evidence folder"},
    )
    assert project.status_code == 200, project.text
    workspace_id = project.json()["workspace_id"]
    added = client.post(
        "/api/nova/workspace/files",
        headers=headers,
        json={
            "filename": "ein-letter.txt",
            "content_type": "text/plain",
            "size_bytes": 18,
            "excerpt": "USER-SAVED EIN letter reference",
            "workspace_id": workspace_id,
        },
    )
    assert added.status_code == 200, added.text
    file_id = added.json()["file_id"]
    convo = client.post(
        "/api/nova/workspace/conversations",
        headers=headers,
        json={"title": "Government research thread", "workspace_id": workspace_id},
    )
    assert convo.status_code == 200, convo.text
    conversation_id = convo.json()["conversation_id"]

    item = _create_item(
        client,
        headers,
        title="EIN and formation checklist",
        workspace_id=workspace_id,
        file_id=file_id,
        conversation_id=conversation_id,
    )
    assert item["workspace_id"] == workspace_id
    assert item["file_id"] == file_id
    assert item["conversation_id"] == conversation_id

    check = client.post(
        f"/api/nova/government/items/{item['item_id']}/checklist",
        headers=headers,
        json={"label": "EIN letter", "document_type": "ein", "file_id": file_id},
    )
    assert check.status_code == 200, check.text
    assert check.json()["file_id"] == file_id
    assert check.json()["completed"] is False
    listed = client.get(f"/api/nova/government/items/{item['item_id']}/checklist", headers=headers)
    assert any(row["label"] == "EIN letter" for row in listed.json())
    toggled = client.post(
        f"/api/nova/government/checklist/{check.json()['checklist_id']}/complete",
        headers=headers,
        params={"completed": True},
    )
    assert toggled.status_code == 200
    assert toggled.json()["completed"] is True
    missing = client.post(
        f"/api/nova/government/items/{item['item_id']}/checklist",
        headers=headers,
        json={"label": "Ghost file", "file_id": "NWF-DOESNOTEXIST"},
    )
    assert missing.status_code == 404


def test_nova_government_sources_verification_and_programs(client: TestClient) -> None:
    headers = _headers(client)
    item = _create_item(client, headers, title="DOT insurance filing research", category="transportation")
    for status in VERIFICATION_STATES:
        source = client.post(
            f"/api/nova/government/items/{item['item_id']}/sources",
            headers=headers,
            json={
                "agency_name": "FMCSA",
                "page_title": f"Insurance filing page ({status})",
                "source_url": "https://example.gov/fmcsa",
                "jurisdiction": "federal",
                "verification_status": status,
                "notes": "Research note only.",
            },
        )
        assert source.status_code == 200, source.text
        assert source.json()["verification_status"] == status
        assert source.json()["source_id"].startswith("NGS-")
    sources = client.get(f"/api/nova/government/items/{item['item_id']}/sources", headers=headers)
    assert {row["verification_status"] for row in sources.json()} == set(VERIFICATION_STATES)

    program = client.post(
        "/api/nova/government/programs",
        headers=headers,
        json={
            "program_name": "Example small business grant",
            "agency": "Example agency",
            "eligibility": "Organizational notes only",
            "amount_range": "unknown",
            "status": "researching",
        },
    )
    assert program.status_code == 200, program.text
    assert program.json()["program_id"].startswith("NGP-")
    programs = client.get("/api/nova/government/programs", headers=headers)
    assert any(row["program_name"] == "Example small business grant" for row in programs.json())


def test_nova_government_communications_link_and_no_send_or_file(client: TestClient) -> None:
    headers = _headers(client)
    item = _create_item(client, headers, title="Agency inquiry draft")
    draft = client.post(
        f"/api/nova/government/items/{item['item_id']}/draft",
        headers=headers,
        json={
            "to": ["agency@example.gov"],
            "subject": "Inquiry about registration requirements",
            "body": "Draft only. Do not send.",
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["sent"] is False
    assert draft.json()["draft"]["status"] == "draft"
    assert draft.json()["item"]["draft_id"]

    filed = client.post(f"/api/nova/government/items/{item['item_id']}/file", headers=headers)
    assert filed.status_code == 403
    assert "does not submit" in filed.json()["detail"].lower() or "not submit" in filed.json()["detail"].lower()

    blocked = client.post(
        "/api/nova/communications/send",
        headers=headers,
        json={
            "confirm_send": True,
            "to": ["agency@example.gov"],
            "subject": "Must not send from government tests",
            "body": "nope",
        },
    )
    assert blocked.status_code == 403
    assert "/api/email/send" not in GOV_JS
    assert "/api/nova/communications/send" not in GOV_JS
    assert "smtp" not in GOV_JS.lower()


def test_nova_government_brain_actions_and_search(client: TestClient) -> None:
    headers = _headers(client)
    item = _create_item(client, headers, title="Open licensing research", category="licensing")
    for action in (
        "explain_requirement",
        "summarize_letter",
        "find_agency",
        "missing_documents",
        "build_checklist",
        "next_step",
        "compare_levels",
        "identify_deadlines",
        "summarize_open_work",
        "prepare_email",
        "search_prior_work",
    ):
        asked = client.post(
            "/api/nova/government/ask",
            headers=headers,
            json={
                "action": action,
                "question": "What should I prepare next?",
                "item_id": item["item_id"],
            },
        )
        assert asked.status_code == 200, asked.text
        body = asked.json()
        assert body["answer"]
        assert "AI SUGGESTION" in body["fact_label"] or "USER-SAVED" in body["fact_label"]
        assert "official government ruling" in body["fact_label"].lower()
    checks = client.get(f"/api/nova/government/items/{item['item_id']}/checklist", headers=headers)
    labels = {row["label"] for row in checks.json()}
    assert "EIN letter" in labels
    refreshed = client.get(f"/api/nova/government/items/{item['item_id']}", headers=headers)
    assert refreshed.json()["draft_id"]

    search = client.post(
        "/api/nova/government/search",
        headers=headers,
        json={"query": "licensing research", "government_level": "state", "category": "licensing", "state": "MN"},
    )
    assert search.status_code == 200, search.text
    assert "web" in search.json()
    assert any(row["item_id"] == item["item_id"] for row in search.json()["saved_work"])
    assert "not official" in search.json()["disclaimer"].lower()
    assert "new search engine" not in GOV_JS.lower()
    assert "/api/nova/government/search" in GOV_JS


def test_nova_government_user_and_org_isolation(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = _create_item(client, owner, title="Dispatcher only government note")
    item_id = created["item_id"]
    hidden = client.get(f"/api/nova/government/items/{item_id}", headers=other)
    assert hidden.status_code == 404
    other_list = client.get("/api/nova/government/items", headers=other)
    assert all(row["item_id"] != item_id for row in other_list.json())
    cross = client.get(
        "/api/nova/government/dashboard",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403


def test_nova_government_navigation_and_responsive() -> None:
    assert 'href="/nova/government" data-destination="government"' in HOME_HTML
    assert 'href="/nova/government">Government' in WS_HTML
    assert 'href="/nova/government">Government' in COMMS_HTML
    assert 'href="/nova">Nova Home' in GOV_HTML
    assert 'href="/nova/workspace">Nova Workspace' in GOV_HTML
    assert 'href="/nova/communications">Communications' in GOV_HTML
    assert 'href="/nova/business">Business' in GOV_HTML
    assert 'href="/nova#web-search">Web / Search' in GOV_HTML
    assert 'href="/nova/workspace#files">Files' in GOV_HTML
    assert 'href="/workspace">Voice' in GOV_HTML
    assert 'href="/workspace">Tools' in GOV_HTML
    assert 'href="/workspace">Health' in GOV_HTML
    assert 'href="/app">Delivery' in GOV_HTML
    assert 'href="/nova/freight">Freight' in GOV_HTML
    assert 'name="viewport"' in GOV_HTML
    assert "width=device-width" in GOV_HTML
    assert "@media (max-width: 720px)" in GOV_CSS
    assert "@media (min-width: 1280px)" in GOV_CSS
    assert "@media (min-width: 1600px)" in GOV_CSS
    assert "hardware" not in GOV_JS.lower()
    assert "gpio" not in GOV_JS.lower()


def test_nova_government_safety_and_frozen_products(client: TestClient) -> None:
    before = _counts()
    headers = _headers(client)
    client.get("/nova/government")
    client.get("/nova")
    client.get("/nova/workspace")
    client.get("/nova/communications")
    client.get("/workspace")
    _create_item(client, headers, title="Isolation government record")
    after = _counts()
    assert before == after
    bundle = GOV_HTML + GOV_JS + GOV_CSS
    assert "Driver 001" not in bundle
    assert "DRV-001" not in bundle
    assert "sk_live" not in bundle
    assert "pk_live" not in bundle
    assert "client_secret" not in GOV_JS
    assert "nova-government" not in OPS_JS
    assert "nova-government" not in OPS_HTML
    assert "Health ISF Workspace" in HEALTH_HTML
    assert "/nova/government" not in HEALTH_HTML
    health = client.get("/workspace")
    assert health.status_code == 200
    assert "Health ISF Workspace" in health.text
    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    assert "New Freight Request" in freight.text or "Freight / Logistics" in freight.text
