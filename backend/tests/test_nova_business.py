"""Nova Core Phase 5: Business OS. Operations only. No ledger, payroll, or autonomous send."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.business.schemas import OPP_STATUSES
from app.db.session import SessionLocal
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
BIZ_HTML = (STATIC / "nova-business" / "index.html").read_text(encoding="utf-8")
BIZ_JS = (STATIC / "nova-business" / "business.js").read_text(encoding="utf-8")
BIZ_CSS = (STATIC / "nova-business" / "business.css").read_text(encoding="utf-8")
HOME_HTML = (STATIC / "nova-home" / "index.html").read_text(encoding="utf-8")
WS_HTML = (STATIC / "nova-workspace" / "index.html").read_text(encoding="utf-8")
COMMS_HTML = (STATIC / "nova-communications" / "index.html").read_text(encoding="utf-8")
GOV_HTML = (STATIC / "nova-government" / "index.html").read_text(encoding="utf-8")
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


def test_nova_business_route_loads(client: TestClient) -> None:
    response = client.get("/nova/business")
    assert response.status_code == 200
    assert "Business OS" in response.text
    assert "Mrs. Nova Brain" in response.text
    assert "ops-shell.js" not in response.text
    assert 'src="/static/nova-business/business.js"' in response.text
    assert "Health ISF Workspace" not in response.text
    assert "NOT Accounting" in response.text


def test_nova_business_signed_out_blocks_apis(client: TestClient) -> None:
    assert client.get("/api/nova/business/dashboard").status_code == 401
    assert client.post("/api/nova/business/profiles", json={"business_name": "Blocked"}).status_code == 401
    assert client.post("/api/nova/business/ask", json={"action": "ask", "question": "blocked"}).status_code == 401


def test_nova_business_dashboard_and_profile_crud(client: TestClient) -> None:
    headers = _headers(client)
    dash = client.get("/api/nova/business/dashboard", headers=headers)
    assert dash.status_code == 200, dash.text
    body = dash.json()
    assert "pipeline" in body
    assert body["expense_label"] == "Operational Expense Tracking — NOT Accounting"
    assert "government_items" in body
    assert "communications_recent" in body
    created = client.post(
        "/api/nova/business/profiles",
        headers=headers,
        json={
            "business_name": "Example Operations Co",
            "legal_name": "Example Operations Company LLC",
            "dba": "Example Ops",
            "entity_type": "llc",
            "industry": "services",
            "ein_reference": "XX-REFONLY",
            "state_of_formation": "MN",
            "status": "active",
        },
    )
    assert created.status_code == 200, created.text
    profile_id = created.json()["profile_id"]
    assert profile_id.startswith("NB-")
    assert created.json()["ein_reference"] == "XX-REFONLY"
    listed = client.get("/api/nova/business/profiles", headers=headers)
    assert any(row["profile_id"] == profile_id for row in listed.json())
    patched = client.patch(
        f"/api/nova/business/profiles/{profile_id}",
        headers=headers,
        json={"status": "forming", "notes": "USER-SAVED INFORMATION"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "forming"
    html_text = BIZ_HTML.replace("&amp;", "&")
    for label in (
        "Overview",
        "Companies / Organizations",
        "Customers",
        "Leads",
        "Opportunities",
        "Projects",
        "Tasks",
        "Documents",
        "Communications",
        "Government / Compliance",
        "Revenue Pipeline",
        "Expenses Summary",
        "Vendors",
        "Contracts",
        "Meetings",
        "Deadlines",
        "Notes",
        "Recent Activity",
    ):
        assert label in html_text


def test_nova_business_customers_opportunities_and_pipeline(client: TestClient) -> None:
    headers = _headers(client)
    customer = client.post(
        "/api/nova/business/customers",
        headers=headers,
        json={
            "name": "Northside Clinic",
            "kind": "company",
            "relationship_type": "customer",
            "status": "active",
            "email": "ops@example.com",
            "next_follow_up": date.today().isoformat(),
        },
    )
    assert customer.status_code == 200, customer.text
    customer_id = customer.json()["customer_id"]
    assert customer_id.startswith("NBC-")
    open_opp = client.post(
        "/api/nova/business/opportunities",
        headers=headers,
        json={
            "title": "Operations support proposal",
            "customer_id": customer_id,
            "estimated_value": 1000,
            "probability": 50,
            "status": "qualified",
        },
    )
    assert open_opp.status_code == 200, open_opp.text
    opportunity_id = open_opp.json()["opportunity_id"]
    assert opportunity_id.startswith("NBO-")
    for status in OPP_STATUSES:
        patched = client.patch(
            f"/api/nova/business/opportunities/{opportunity_id}",
            headers=headers,
            json={"status": status},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["status"] == status
    client.patch(
        f"/api/nova/business/opportunities/{opportunity_id}",
        headers=headers,
        json={"status": "qualified", "estimated_value": 1000, "probability": 50},
    )
    won = client.post(
        "/api/nova/business/opportunities",
        headers=headers,
        json={"title": "Closed win", "estimated_value": 250, "probability": 100, "status": "won"},
    )
    assert won.status_code == 200
    pipe = client.get("/api/nova/business/pipeline", headers=headers)
    assert pipe.status_code == 200
    body = pipe.json()
    assert body["open_count"] >= 1
    assert body["won_count"] >= 1
    assert body["customer_count"] >= 1
    assert body["open_pipeline"] >= 1000
    assert body["won_pipeline"] >= 250
    assert body["expected_revenue"] >= 500
    assert "not an accounting ledger" in body["disclaimer"].lower()
    invalid = client.patch(
        f"/api/nova/business/opportunities/{opportunity_id}",
        headers=headers,
        json={"status": "invoiced_in_stripe"},
    )
    assert invalid.status_code == 422


def test_nova_business_tasks_vendors_documents_expenses_meetings(client: TestClient) -> None:
    headers = _headers(client)
    project = client.post("/api/nova/workspace/projects", headers=headers, json={"title": "Business ops board"})
    assert project.status_code == 200, project.text
    workspace_id = project.json()["workspace_id"]
    added = client.post(
        "/api/nova/workspace/files",
        headers=headers,
        json={
            "filename": "contract-note.txt",
            "content_type": "text/plain",
            "size_bytes": 12,
            "excerpt": "contract excerpt",
            "workspace_id": workspace_id,
        },
    )
    assert added.status_code == 200, added.text
    file_id = added.json()["file_id"]
    gov = client.post(
        "/api/nova/government/items",
        headers=headers,
        json={"title": "State license renewal", "category": "licensing", "government_level": "state"},
    )
    assert gov.status_code == 200, gov.text
    gov_id = gov.json()["item_id"]

    task = client.post(
        "/api/nova/business/tasks",
        headers=headers,
        json={
            "title": "Call the counterparty",
            "priority": "high",
            "due_date": (date.today() - timedelta(days=1)).isoformat(),
            "workspace_id": workspace_id,
            "government_item_id": gov_id,
        },
    )
    assert task.status_code == 200, task.text
    assert task.json()["task_id"].startswith("NBT-")
    completed = client.patch(
        f"/api/nova/business/tasks/{task.json()['task_id']}",
        headers=headers,
        json={"status": "completed"},
    )
    assert completed.status_code == 200
    assert completed.json()["completed_at"]

    vendor = client.post(
        "/api/nova/business/vendors",
        headers=headers,
        json={"vendor_name": "Paperclip Supply", "category": "office", "government_item_id": gov_id},
    )
    assert vendor.status_code == 200
    assert vendor.json()["vendor_id"].startswith("NBV-")

    document = client.post(
        "/api/nova/business/documents",
        headers=headers,
        json={
            "title": "Master services agreement",
            "kind": "contract",
            "status": "expiring",
            "expiration_date": (date.today() + timedelta(days=10)).isoformat(),
            "workspace_id": workspace_id,
            "file_id": file_id,
            "government_item_id": gov_id,
        },
    )
    assert document.status_code == 200, document.text
    assert document.json()["document_id"].startswith("NBD-")
    assert document.json()["file_id"] == file_id

    expense = client.post(
        "/api/nova/business/expenses",
        headers=headers,
        json={"vendor_name": "Paperclip Supply", "amount": 42.5, "description": "Office supplies", "workspace_id": workspace_id},
    )
    assert expense.status_code == 200, expense.text
    assert expense.json()["expense_id"].startswith("NBE-")
    assert expense.json()["label"] == "Operational Expense Tracking — NOT Accounting"

    start = datetime.now(timezone.utc) + timedelta(hours=3)
    meeting = client.post(
        "/api/nova/business/meetings",
        headers=headers,
        json={
            "title": "Customer kickoff",
            "start_time": start.isoformat(),
            "workspace_id": workspace_id,
            "create_follow_up_task": True,
        },
    )
    assert meeting.status_code == 200, meeting.text
    assert meeting.json()["meeting_id"].startswith("NBM-")
    assert meeting.json()["calendar_event_id"]
    events = client.get("/api/nova/communications/events", headers=headers)
    assert any("Customer kickoff" in row["title"] for row in events.json())
    tasks = client.get("/api/nova/business/tasks", headers=headers)
    assert any(row["title"].startswith("Follow up: Customer kickoff") for row in tasks.json())

    dash = client.get("/api/nova/business/dashboard", headers=headers)
    assert any(row["item_id"] == gov_id for row in dash.json()["government_items"])
    assert any(row["document_id"] == document.json()["document_id"] for row in dash.json()["documents_attention"])


def test_nova_business_communications_brain_activity_and_refusals(client: TestClient) -> None:
    headers = _headers(client)
    customer = client.post(
        "/api/nova/business/customers",
        headers=headers,
        json={"name": "Follow-up person", "kind": "individual"},
    ).json()
    draft = client.post(
        "/api/nova/business/draft",
        headers=headers,
        json={
            "to": ["follow@example.com"],
            "subject": "Business follow-up",
            "body": "Draft only",
            "customer_id": customer["customer_id"],
        },
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["sent"] is False
    assert draft.json()["draft"]["status"] == "draft"
    blocked_send = client.post("/api/nova/business/send", headers=headers)
    assert blocked_send.status_code == 403
    ledger = client.post("/api/nova/business/ledger", headers=headers)
    assert ledger.status_code == 403
    comms_send = client.post(
        "/api/nova/communications/send",
        headers=headers,
        json={"confirm_send": True, "to": ["follow@example.com"], "subject": "nope", "body": "nope"},
    )
    assert comms_send.status_code == 403
    for action in (
        "attention_today",
        "summarize_business",
        "overdue_followups",
        "top_opportunities",
        "summarize_pipeline",
        "summarize_expenses",
        "government_requirements",
        "next_work",
        "draft_followup",
        "operational_risks",
    ):
        asked = client.post(
            "/api/nova/business/ask",
            headers=headers,
            json={"action": action, "question": "Help organize today.", "customer_id": customer["customer_id"]},
        )
        assert asked.status_code == 200, asked.text
        assert asked.json()["answer"]
        assert "AI SUGGESTION" in asked.json()["fact_label"] or "USER-SAVED" in asked.json()["fact_label"]
    activity = client.get("/api/nova/business/activity", headers=headers)
    assert activity.status_code == 200
    assert activity.json()
    assert "/api/email/send" not in BIZ_JS
    assert "/api/nova/communications/send" not in BIZ_JS
    assert "general ledger" not in BIZ_JS.lower()
    assert "sk_live" not in BIZ_JS
    assert "pk_live" not in BIZ_JS


def test_nova_business_user_and_org_isolation(client: TestClient) -> None:
    owner = _headers(client, "dispatcher@amicor.local")
    other = _headers(client, "staff@amicor.local")
    created = client.post(
        "/api/nova/business/customers",
        headers=owner,
        json={"name": "Dispatcher only customer"},
    )
    assert created.status_code == 200
    customer_id = created.json()["customer_id"]
    hidden = client.get(f"/api/nova/business/customers/{customer_id}", headers=other)
    assert hidden.status_code == 404
    other_list = client.get("/api/nova/business/customers", headers=other)
    assert all(row["customer_id"] != customer_id for row in other_list.json())
    cross = client.get(
        "/api/nova/business/dashboard",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403


def test_nova_business_navigation_and_responsive() -> None:
    assert 'href="/nova/business" data-destination="business"' in HOME_HTML
    assert 'href="/nova/business">Business' in WS_HTML
    assert 'href="/nova/business">Business' in COMMS_HTML
    assert 'href="/nova/business">Business' in GOV_HTML
    assert 'href="/nova">Nova Home' in BIZ_HTML
    assert 'href="/nova/workspace">Nova Workspace' in BIZ_HTML
    assert 'href="/nova/communications">Communications' in BIZ_HTML
    assert 'href="/nova/government">Government' in BIZ_HTML
    assert 'href="/workspace">Health' in BIZ_HTML
    assert 'href="/app">Delivery' in BIZ_HTML
    assert 'href="/nova/freight">Freight' in BIZ_HTML
    assert 'name="viewport"' in BIZ_HTML
    assert "@media (max-width: 720px)" in BIZ_CSS
    assert "@media (min-width: 1280px)" in BIZ_CSS
    assert "@media (min-width: 1600px)" in BIZ_CSS
    assert "hardware" not in BIZ_JS.lower()


def test_nova_business_safety_and_frozen_products(client: TestClient) -> None:
    before = _counts()
    headers = _headers(client)
    client.get("/nova/business")
    client.get("/nova")
    client.get("/nova/workspace")
    client.get("/nova/communications")
    client.get("/nova/government")
    client.get("/workspace")
    client.post("/api/nova/business/customers", headers=headers, json={"name": "Isolation customer"})
    after = _counts()
    assert before == after
    bundle = BIZ_HTML + BIZ_JS + BIZ_CSS
    assert "Driver 001" not in bundle
    assert "DRV-001" not in bundle
    assert "sk_live" not in bundle
    assert "pk_live" not in bundle
    assert "nova-business" not in OPS_JS
    assert "nova-business" not in OPS_HTML
    assert "Health ISF Workspace" in HEALTH_HTML
    assert "/nova/business" not in HEALTH_HTML
    health = client.get("/workspace")
    assert health.status_code == 200
    assert "Health ISF Workspace" in health.text
    freight = client.get("/nova/freight")
    assert freight.status_code == 200
    assert "New Freight Request" in freight.text or "Freight / Logistics" in freight.text
