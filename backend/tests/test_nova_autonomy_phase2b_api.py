"""Phase 2B tenant-scoped workflow CRUD. No execution, worker, or Phase 2 flag."""
from __future__ import annotations

import ast
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.models import NovaAutonomyOrgFlag, NovaAutonomyWorkflow, new_workflow_id
from app.core.nova.autonomy.v2_templates import WORKFLOW_TYPES
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = ROOT / "app" / "core" / "nova" / "autonomy"
FORBIDDEN_MODULES = (
    "rider_checkout",
    "stripe_payments",
    "financial_engine",
    "health_isf",
    "app.modules.payments",
)
WORKER_MARKERS = ("apscheduler", "celery", "backgroundscheduler", "cron", "while true")


def _client() -> TestClient:
    from app.core.nova.autonomy.ledger import ensure_autonomy_schema
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    return TestClient(app)


def _login(client: TestClient, email: str = "admin@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _org(client: TestClient, headers: dict[str, str]) -> str:
    me = client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    org_id = me.json()["organization_id"]
    assert org_id
    return org_id


def _create_body(**extra) -> dict:
    body = {
        "workflow_type": extra.pop("workflow_type", "research_draft_task"),
        "initiating_module": extra.pop("initiating_module", "today"),
        "source_ref_id": extra.pop("source_ref_id", f"p2b-{uuid4()[:10]}"),
    }
    body.update(extra)
    return body


def _create(client: TestClient, headers: dict[str, str], **extra):
    request_headers = dict(headers)
    key = extra.pop("idempotency_key", None)
    if key:
        request_headers["Idempotency-Key"] = key
    return client.post("/api/nova/autonomy/v2/workflows", headers=request_headers, json=_create_body(**extra))


def test_owner_admin_can_create_header_only_workflow() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, workflow_type="research_draft_task", initiating_module="today")
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["workflow_id"].startswith("NWF-")
    assert body["correlation_id"].startswith("NWC-")
    assert body["status"] == "proposed"
    assert body["executed"] is False
    assert body["mutated_external"] is False
    assert body["steps"] == []
    assert body["approvals"] == []
    assert body["organization_id"] == _org(client, owner)
    history = client.get(f"/api/nova/autonomy/v2/workflows/{body['workflow_id']}/history", headers=owner)
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 1
    assert rows[0]["executed"] is False
    assert rows[0]["action_type"] == "propose_workflow"
    assert "secret" not in str(rows[0]).lower()
    assert rows[0].get("detail") == "header_only"


def test_dispatcher_create_denied_same_org_get_allowed() -> None:
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    denied = _create(client, dispatcher)
    assert denied.status_code == 403
    created = _create(client, owner, source_ref_id=f"disp-read-{uuid4()[:8]}")
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    visible = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=dispatcher)
    assert visible.status_code == 200, visible.text
    assert visible.json()["workflow_id"] == workflow_id
    assert visible.json()["executed"] is False


def test_same_org_get_and_list_do_not_leak_foreign_org() -> None:
    client = _client()
    owner = _login(client)
    org_id = _org(client, owner)
    mine = _create(client, owner, source_ref_id=f"mine-{uuid4()[:8]}")
    assert mine.status_code == 200, mine.text
    foreign_id = new_workflow_id()
    with SessionLocal() as db:
        db.add(
            NovaAutonomyWorkflow(
                workflow_id=foreign_id,
                organization_id="org-foreign-phase2b",
                owner_user_id="foreign-owner",
                correlation_id="NWC-FOREIGN0001",
                workflow_type="research_draft_task",
                initiating_module="today",
                source_ref_id="foreign-source",
                status="proposed",
                created_at=now(),
                updated_at=now(),
            )
        )
        db.commit()
    listed = client.get("/api/nova/autonomy/v2/workflows", headers=owner)
    assert listed.status_code == 200, listed.text
    ids = {row["workflow_id"] for row in listed.json()}
    assert mine.json()["workflow_id"] in ids
    assert foreign_id not in ids
    assert all(row["organization_id"] == org_id for row in listed.json())
    missing = client.get(f"/api/nova/autonomy/v2/workflows/{foreign_id}", headers=owner)
    assert missing.status_code == 404
    assert "org-foreign" not in missing.text
    cross = client.get(
        f"/api/nova/autonomy/v2/workflows/{mine.json()['workflow_id']}",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cross.status_code == 403
    create_cross = _create(client, owner, organization_id="org-not-the-caller")
    assert create_cross.status_code == 403


def test_unknown_workflow_type_and_module_action_rejected() -> None:
    client = _client()
    owner = _login(client)
    unknown_type = _create(client, owner, workflow_type="invented_autonomous_loop")
    assert unknown_type.status_code == 400
    bad_combo = _create(
        client,
        owner,
        workflow_type="gov_opportunity_response",
        initiating_module="communications",
        action_type="create_draft",
    )
    assert bad_combo.status_code == 400
    bad_action = _create(
        client,
        owner,
        workflow_type="research_draft_task",
        initiating_module="today",
        action_type="payout",
    )
    assert bad_action.status_code == 400
    assert WORKFLOW_TYPES == {
        "research_draft_task",
        "gov_opportunity_response",
        "customer_inquiry_response",
        "business_lead_outreach",
        "ops_issue_recommend",
    }


def test_idempotent_create_returns_same_workflow() -> None:
    client = _client()
    owner = _login(client)
    key = f"p2b-once-{uuid4()[:10]}"
    first = _create(client, owner, idempotency_key=key, source_ref_id="same-source")
    second = _create(client, owner, idempotency_key=key, source_ref_id="same-source")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["workflow_id"] == second.json()["workflow_id"]
    assert first.json()["correlation_id"] == second.json()["correlation_id"]
    listed = client.get("/api/nova/autonomy/v2/workflows", headers=owner).json()
    matching = [row for row in listed if row["workflow_id"] == first.json()["workflow_id"]]
    assert len(matching) == 1


def test_no_external_action_flag_stays_off_and_no_worker() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    client = _client()
    owner = _login(client)
    created = _create(client, owner, workflow_type="ops_issue_recommend", initiating_module="link")
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    flag = client.get("/api/nova/autonomy/v2/org-flag", headers=owner)
    assert flag.status_code == 200, flag.text
    assert flag.json()["phase2_enabled"] is False
    assert flag.json()["emergency_stop"] is False
    approvals = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approvals", headers=owner)
    assert approvals.status_code == 200
    assert approvals.json() == []
    again = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert again.json()["status"] == "proposed"
    assert again.json()["executed"] is False
    assert again.json()["mutated_external"] is False
    assert again.json()["steps"] == []
    with SessionLocal() as db:
        stored = db.get(NovaAutonomyWorkflow, workflow_id)
        assert stored is not None
        assert stored.status == "proposed"
        org_flag = db.get(NovaAutonomyOrgFlag, stored.organization_id)
        assert org_flag is None or org_flag.phase2_enabled is False
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    for path in AUTONOMY.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert all(marker not in text for marker in WORKER_MARKERS), path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            assert all(banned not in module for banned in FORBIDDEN_MODULES), f"{path.name} imports {module}"
