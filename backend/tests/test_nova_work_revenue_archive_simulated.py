"""Safe bulk archive of canonical simulated/test Work opportunities."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.work_revenue.flags import engine_guardrails
from app.core.nova.work_revenue.schema_ensure import ensure_work_revenue_schema
from app.db.session import engine
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
WORK_HTML = (STATIC / "nova-work" / "index.html").read_text(encoding="utf-8")
WORK_JS = (STATIC / "nova-work" / "work.js").read_text(encoding="utf-8")


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


def _create_opp(client: TestClient, headers: dict[str, str], **overrides) -> dict:
    body = {
        "company_name": "Archive Cleanup Co",
        "opportunity_title": "Remote administrative support contractor",
        "description": "Prepare email drafts and CRM notes. Fully remote.",
        "location": "Remote",
        "remote_status": "remote",
        "engagement_type": "contract",
        "compensation_type": "hourly",
        "compensation_amount": 40,
        "compensation_period": "hour",
        "currency": "USD",
        "requirements": "Email writing, CRM, reporting.",
        "skills_required": ["email", "crm", "reporting"],
        "credentials_required": [],
        "physical_presence_required": "false",
        "source": "manual",
        "source_type": "manual",
    }
    body.update(overrides)
    response = client.post("/api/nova/work/opportunities", headers=headers, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _snapshot_app(row: dict) -> dict:
    return {
        "application_id": row["application_id"],
        "opportunity_id": row["opportunity_id"],
        "approval_state": row["approval_state"],
        "approved_for_future_submission": row.get("approved_for_future_submission"),
        "manual_submission_recorded": row.get("manual_submission_recorded"),
        "externally_submitted": row.get("externally_submitted"),
        "notes": row.get("notes"),
    }


def test_ui_exposes_simulated_cleanup_control() -> None:
    assert 'data-filter="simulated"' in WORK_HTML
    assert "Archive simulated/test records" in WORK_HTML
    assert "archive-simulated-btn" in WORK_HTML
    assert "simulated-cleanup-bar" in WORK_HTML
    assert "/api/nova/work/opportunities/archive-simulated" in WORK_JS
    assert "Archive all simulated/test opportunities? Real live/manual opportunities will not be changed." in WORK_JS
    assert "Archived " in WORK_JS and "simulated/test opportunities. Real opportunities were not changed." in WORK_JS


def test_bulk_archive_simulated_only_leaves_real_sources_untouched(client: TestClient) -> None:
    headers = _headers(client)

    simulated_a = _create_opp(
        client,
        headers,
        company_name="Sim Fixture A",
        opportunity_title="Delivery driver simulated/test fixture",
        source="simulated",
        source_type="simulated",
    )
    simulated_b = _create_opp(
        client,
        headers,
        company_name="Sim Fixture B",
        opportunity_title="Registered Nurse simulated/test fixture",
        source="simulated",
        source_type="simulated",
    )
    title_trap = _create_opp(
        client,
        headers,
        company_name="Title Trap Co",
        opportunity_title="Warehouse associate simulated/test fixture",
        source="manual",
        source_type="manual",
    )
    remotive = _create_opp(
        client,
        headers,
        company_name="Remotive Live Co",
        opportunity_title="Remote Remotive role",
        source="remotive",
        source_type="remotive",
        source_url="https://remotive.com/remote-jobs/example-role",
    )
    remoteok = _create_opp(
        client,
        headers,
        company_name="RemoteOK Live Co",
        opportunity_title="RemoteOK engineering role",
        source="remoteok",
        source_type="remoteok",
        source_url="https://remoteok.com/remote-jobs/example-role",
    )
    manual = _create_opp(
        client,
        headers,
        company_name="Manual Real Co",
        opportunity_title="Manual real opportunity",
        source="manual",
        source_type="manual",
    )

    sim_app = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": simulated_a["opportunity_id"]},
    )
    assert sim_app.status_code == 200, sim_app.text
    remotive_app = client.post(
        "/api/nova/work/applications",
        headers=headers,
        json={"opportunity_id": remotive["opportunity_id"]},
    )
    assert remotive_app.status_code == 200, remotive_app.text
    sim_app_before = _snapshot_app(sim_app.json())
    remotive_app_before = _snapshot_app(remotive_app.json())

    other = _headers(client, "staff@amicor.local")
    other_simulated = _create_opp(
        client,
        other,
        company_name="Other Tenant Sim Co",
        opportunity_title="Other owner simulated/test fixture",
        source="simulated",
        source_type="simulated",
    )

    def _get(opp_id: str, auth: dict[str, str] | None = None) -> dict:
        response = client.get(f"/api/nova/work/opportunities/{opp_id}", headers=auth or headers)
        assert response.status_code == 200, response.text
        return response.json()

    remotive_before = _get(remotive["opportunity_id"])
    remoteok_before = _get(remoteok["opportunity_id"])
    manual_before = _get(manual["opportunity_id"])
    title_trap_before = _get(title_trap["opportunity_id"])

    simulated_filter = client.get(
        "/api/nova/work/opportunities",
        headers=headers,
        params={"view_filter": "simulated", "limit": 100},
    )
    assert simulated_filter.status_code == 200
    simulated_ids = {row["opportunity_id"] for row in simulated_filter.json()}
    assert simulated_a["opportunity_id"] in simulated_ids
    assert simulated_b["opportunity_id"] in simulated_ids
    assert title_trap["opportunity_id"] not in simulated_ids
    assert remotive["opportunity_id"] not in simulated_ids
    assert remoteok["opportunity_id"] not in simulated_ids
    assert manual["opportunity_id"] not in simulated_ids

    first = client.post("/api/nova/work/opportunities/archive-simulated", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["archived_count"] >= 2
    assert simulated_a["opportunity_id"] in body["archived_ids"]
    assert simulated_b["opportunity_id"] in body["archived_ids"]
    assert title_trap["opportunity_id"] not in body["archived_ids"]
    assert remotive["opportunity_id"] not in body["archived_ids"]
    assert remoteok["opportunity_id"] not in body["archived_ids"]
    assert manual["opportunity_id"] not in body["archived_ids"]
    assert other_simulated["opportunity_id"] not in body["archived_ids"]
    assert body["external_submission"] is False
    assert body["client_contact"] is False
    assert body["contract_acceptance"] is False
    assert body["financial_execution"] is False
    assert body["stripe_action"] is False
    assert "Real opportunities were not changed" in body["message"]

    sim_a_after = _get(simulated_a["opportunity_id"])
    sim_b_after = _get(simulated_b["opportunity_id"])
    assert sim_a_after["archived"] is True
    assert sim_b_after["archived"] is True
    assert sim_a_after["status"] == "CLOSED"
    assert sim_b_after["status"] == "CLOSED"

    remotive_after = _get(remotive["opportunity_id"])
    remoteok_after = _get(remoteok["opportunity_id"])
    manual_after = _get(manual["opportunity_id"])
    title_trap_after = _get(title_trap["opportunity_id"])
    assert remotive_after["archived"] is False
    assert remotive_after["status"] == remotive_before["status"]
    assert remotive_after["source_type"] == "remotive"
    assert remotive_after["updated_at"] == remotive_before["updated_at"]
    assert remoteok_after["archived"] is False
    assert remoteok_after["status"] == remoteok_before["status"]
    assert remoteok_after["source_type"] == "remoteok"
    assert remoteok_after["updated_at"] == remoteok_before["updated_at"]
    assert manual_after["archived"] is False
    assert manual_after["status"] == manual_before["status"]
    assert manual_after["source_type"] == "manual"
    assert manual_after["updated_at"] == manual_before["updated_at"]
    assert title_trap_after["archived"] is False
    assert title_trap_after["source_type"] == "manual"
    assert title_trap_after["updated_at"] == title_trap_before["updated_at"]

    other_after = client.get(
        f"/api/nova/work/opportunities/{other_simulated['opportunity_id']}",
        headers=other,
    )
    assert other_after.status_code == 200
    assert other_after.json()["archived"] is False

    archived_view = client.get(
        "/api/nova/work/opportunities",
        headers=headers,
        params={"view_filter": "archived", "limit": 100},
    )
    assert archived_view.status_code == 200
    archived_ids = {row["opportunity_id"] for row in archived_view.json()}
    assert simulated_a["opportunity_id"] in archived_ids
    assert simulated_b["opportunity_id"] in archived_ids

    apps = {
        row["application_id"]: row
        for row in client.get("/api/nova/work/applications", headers=headers).json()
    }
    assert _snapshot_app(apps[sim_app_before["application_id"]]) == sim_app_before
    assert _snapshot_app(apps[remotive_app_before["application_id"]]) == remotive_app_before

    second = client.post("/api/nova/work/opportunities/archive-simulated", headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["archived_count"] == 0
    assert second.json()["archived_ids"] == []

    guards = engine_guardrails()
    assert guards.get("EXTERNAL_SUBMISSION_ENABLED") is False
    assert guards.get("FINANCIAL_ACTIONS_ENABLED") is False
    assert guards.get("AUTONOMOUS_CLIENT_CONTACT_ENABLED") is False


def test_archive_simulated_rejects_unauthenticated(client: TestClient) -> None:
    assert client.post("/api/nova/work/opportunities/archive-simulated").status_code == 401
