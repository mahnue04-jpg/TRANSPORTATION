"""Phase 2C supervised transitions and internal_test execution only."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.models import (
    NovaAutonomyExecutionAttempt,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
)
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = ROOT / "app" / "core" / "nova" / "autonomy"


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


def _create(client: TestClient, headers: dict[str, str], **extra):
    body = {
        "workflow_type": extra.pop("workflow_type", "research_draft_task"),
        "initiating_module": extra.pop("initiating_module", "today"),
        "source_ref_id": extra.pop("source_ref_id", f"p2c-{uuid4()[:10]}"),
    }
    body.update(extra)
    return client.post("/api/nova/autonomy/v2/workflows", headers=headers, json=body)


def test_owner_supervised_approve_then_internal_test_step() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    approved = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=owner)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "waiting"
    assert approved.json()["mutated_external"] is False
    assert len(approved.json()["steps"]) == 1
    step = approved.json()["steps"][0]
    assert step["action_type"] == "internal_test"
    assert step["status"] == "waiting"
    again = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=owner)
    assert again.status_code == 200
    assert again.json()["workflow_id"] == workflow_id
    assert again.json()["current_step"] == step["step_id"]
    executed = client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/steps/{step['step_id']}/approve",
        headers=owner,
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "completed"
    assert executed.json()["executed"] is True
    assert executed.json()["mutated_external"] is False
    assert executed.json()["steps"][0]["result_ref_id"].startswith("INT-")
    replay = client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/steps/{step['step_id']}/approve",
        headers=owner,
    )
    assert replay.status_code == 200
    assert replay.json()["steps"][0]["result_ref_id"] == executed.json()["steps"][0]["result_ref_id"]
    history = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}/history", headers=owner)
    actions = [row["action_type"] for row in history.json()]
    assert "approve_workflow" in actions
    assert "internal_test" in actions
    assert all(row.get("detail") != "secret" for row in history.json())
    with SessionLocal() as db:
        attempts = (
            db.query(NovaAutonomyExecutionAttempt)
            .filter(NovaAutonomyExecutionAttempt.workflow_id == workflow_id)
            .all()
        )
        assert len(attempts) == 1
        assert attempts[0].verification_status == "verified"


def test_dispatcher_cannot_mutate_same_org_read_ok() -> None:
    client = _client()
    owner = _login(client)
    dispatcher = _login(client, "dispatcher@amicor.local")
    created = _create(client, owner)
    workflow_id = created.json()["workflow_id"]
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=dispatcher).status_code == 403
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/cancel", headers=dispatcher).status_code == 403
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/pause", headers=dispatcher).status_code == 403
    assert client.post("/api/nova/autonomy/v2/emergency-stop", headers=dispatcher).status_code == 403
    visible = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=dispatcher)
    assert visible.status_code == 200
    assert visible.json()["status"] == "proposed"


def test_pause_resume_cancel_and_illegal_transition() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    workflow_id = created.json()["workflow_id"]
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/pause", headers=owner).status_code == 409
    approved = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=owner)
    assert approved.status_code == 200
    paused = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/pause", headers=owner)
    assert paused.status_code == 200, paused.text
    assert paused.json()["status"] == "paused"
    paused_again = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/pause", headers=owner)
    assert paused_again.json()["status"] == "paused"
    resumed = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/resume", headers=owner)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "waiting"
    cancelled = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/cancel", headers=owner)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=owner).status_code == 409
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/cancel", headers=owner).status_code == 200


def test_cross_org_mutations_denied() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    workflow_id = created.json()["workflow_id"]
    foreign = client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert foreign.status_code == 403
    missing = client.post("/api/nova/autonomy/v2/workflows/NWF-MISSING0001/approve", headers=owner)
    assert missing.status_code == 404
    assert "org-not" not in missing.text


def test_external_step_is_not_executed() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"ext-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    with SessionLocal() as db:
        db.add(
            NovaAutonomyWorkflowStep(
                step_id="NWS-EXTERNAL0001",
                workflow_id=workflow_id,
                organization_id=created.json()["organization_id"],
                sequence_number=1,
                source_module="communications",
                target_module="communications",
                action_type="create_draft",
                risk_class="LOW",
                status="waiting",
                idempotency_key=f"{workflow_id}-external-draft",
                created_at=now(),
                updated_at=now(),
            )
        )
        row = db.get(NovaAutonomyWorkflow, workflow_id)
        row.status = "waiting"
        row.current_step = "NWS-EXTERNAL0001"
        db.commit()
    blocked = client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/steps/NWS-EXTERNAL0001/approve",
        headers=owner,
    )
    assert blocked.status_code == 409
    stored = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert stored.json()["status"] == "waiting"
    assert stored.json()["executed"] is False
    assert stored.json()["mutated_external"] is False
    assert stored.json()["steps"][0]["result_ref_id"] is None


def test_emergency_stop_cancels_open_and_blocks_new_work() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    client = _client()
    owner = _login(client)
    first = _create(client, owner, source_ref_id=f"stop-a-{uuid4()[:8]}")
    second = _create(client, owner, source_ref_id=f"stop-b-{uuid4()[:8]}")
    assert first.status_code == 200 and second.status_code == 200
    client.post(f"/api/nova/autonomy/v2/workflows/{first.json()['workflow_id']}/approve", headers=owner)
    stopped = client.post("/api/nova/autonomy/v2/emergency-stop", headers=owner)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["emergency_stop"] is True
    assert stopped.json()["phase2_enabled"] is False
    assert stopped.json()["executed"] is False
    ids = set(stopped.json()["cancelled_workflow_ids"])
    assert first.json()["workflow_id"] in ids
    assert second.json()["workflow_id"] in ids
    flag = client.get("/api/nova/autonomy/v2/org-flag", headers=owner)
    assert flag.json()["emergency_stop"] is True
    assert flag.json()["phase2_enabled"] is False
    assert _create(client, owner, source_ref_id=f"stop-c-{uuid4()[:8]}").status_code == 403
    assert (
        client.post(
            f"/api/nova/autonomy/v2/workflows/{first.json()['workflow_id']}/approve",
            headers=owner,
        ).status_code
        == 403
    )
    with SessionLocal() as db:
        org_flag = db.get(NovaAutonomyOrgFlag, first.json()["organization_id"])
        assert org_flag is not None
        assert org_flag.phase2_enabled is False
        assert org_flag.emergency_stop is True
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    for path in AUTONOMY.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "apscheduler" not in text
        assert "celery" not in text
        assert "backgroundscheduler" not in text
        assert "while true" not in text
