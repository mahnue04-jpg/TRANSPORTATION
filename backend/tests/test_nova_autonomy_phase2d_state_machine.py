"""Phase 2D supervised multi-step state machine. No worker or Phase 2 flag."""
from __future__ import annotations

import ast
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.models import (
    NovaAutonomyExecutionAttempt,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
)
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
AUTONOMY = ROOT / "app" / "core" / "nova" / "autonomy"
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


def _create(client: TestClient, headers: dict[str, str], **extra):
    body = {
        "workflow_type": extra.pop("workflow_type", "research_draft_task"),
        "initiating_module": extra.pop("initiating_module", "today"),
        "source_ref_id": extra.pop("source_ref_id", f"p2d-{uuid4()[:10]}"),
    }
    body.update(extra)
    return client.post("/api/nova/autonomy/v2/workflows", headers=headers, json=body)


def _approve_workflow(client: TestClient, headers: dict[str, str], workflow_id: str, **params):
    return client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve",
        headers=headers,
        params=params,
    )


def _approve_step(client: TestClient, headers: dict[str, str], workflow_id: str, step_id: str):
    return client.post(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}/steps/{step_id}/approve",
        headers=headers,
    )


def _ordered(body: dict) -> list[dict]:
    return sorted(body["steps"], key=lambda row: row["sequence_number"])


def _insert_current_step(
    workflow_id: str,
    organization_id: str,
    *,
    action_type: str,
    risk_class: str,
    step_id: str,
) -> None:
    with SessionLocal() as db:
        db.add(
            NovaAutonomyWorkflowStep(
                step_id=step_id,
                workflow_id=workflow_id,
                organization_id=organization_id,
                sequence_number=1,
                source_module="autonomy",
                target_module="autonomy",
                action_type=action_type,
                risk_class=risk_class,
                status="waiting",
                idempotency_key=f"{workflow_id}-{action_type}-{step_id[-6:]}",
                created_at=now(),
                updated_at=now(),
            )
        )
        row = db.get(NovaAutonomyWorkflow, workflow_id)
        assert row is not None
        row.status = "waiting"
        row.current_step = step_id
        db.commit()


def test_two_step_supervised_workflow_and_no_skip() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, step_count=2, source_ref_id=f"two-{uuid4()[:8]}")
    assert created.status_code == 200, created.text
    assert created.json()["status"] == "proposed"
    assert created.json()["steps"] == []
    workflow_id = created.json()["workflow_id"]
    approved = _approve_workflow(client, owner, workflow_id)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "waiting"
    steps = _ordered(approved.json())
    assert len(steps) == 2
    first, second = steps
    assert approved.json()["current_step"] == first["step_id"]
    assert first["status"] == "waiting"
    assert second["status"] == "proposed"
    skipped = _approve_step(client, owner, workflow_id, second["step_id"])
    assert skipped.status_code == 409
    parked = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert parked.json()["current_step"] == first["step_id"]
    assert _ordered(parked.json())[1]["status"] == "proposed"
    first_done = _approve_step(client, owner, workflow_id, first["step_id"])
    assert first_done.status_code == 200, first_done.text
    assert first_done.json()["status"] == "waiting"
    assert first_done.json()["current_step"] == second["step_id"]
    after_first = _ordered(first_done.json())
    assert after_first[0]["status"] == "completed"
    assert after_first[0]["result_ref_id"].startswith("INT-")
    assert after_first[1]["status"] == "waiting"
    assert first_done.json()["executed"] is True
    replay = _approve_step(client, owner, workflow_id, first["step_id"])
    assert replay.status_code == 200
    assert _ordered(replay.json())[0]["result_ref_id"] == after_first[0]["result_ref_id"]
    assert replay.json()["current_step"] == second["step_id"]
    again = _approve_step(client, owner, workflow_id, first["step_id"])
    assert again.status_code == 200
    assert _ordered(again.json())[0]["result_ref_id"] == after_first[0]["result_ref_id"]
    with SessionLocal() as db:
        attempts = (
            db.query(NovaAutonomyExecutionAttempt)
            .filter(
                NovaAutonomyExecutionAttempt.workflow_id == workflow_id,
                NovaAutonomyExecutionAttempt.step_id == first["step_id"],
            )
            .all()
        )
        assert len(attempts) == 1
    finished = _approve_step(client, owner, workflow_id, second["step_id"])
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"
    assert _ordered(finished.json())[1]["result_ref_id"].startswith("INT-")


def test_pause_resume_same_step_and_cancel_blocks_later() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, step_count=2, source_ref_id=f"pause-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    approved = _approve_workflow(client, owner, workflow_id)
    first, second = _ordered(approved.json())
    first_done = _approve_step(client, owner, workflow_id, first["step_id"])
    assert first_done.json()["current_step"] == second["step_id"]
    first_ref = _ordered(first_done.json())[0]["result_ref_id"]
    paused = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/pause", headers=owner)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert paused.json()["current_step"] == second["step_id"]
    blocked = _approve_step(client, owner, workflow_id, second["step_id"])
    assert blocked.status_code == 409
    resumed = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/resume", headers=owner)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "waiting"
    assert resumed.json()["current_step"] == second["step_id"]
    assert _ordered(resumed.json())[0]["result_ref_id"] == first_ref
    cancelled = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/cancel", headers=owner)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    later = _approve_step(client, owner, workflow_id, second["step_id"])
    assert later.status_code == 409
    history = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}/history", headers=owner)
    assert history.status_code == 200
    assert any(row["action_type"] == "internal_test" and row.get("step_id") == first["step_id"] for row in history.json())
    stored = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert _ordered(stored.json())[0]["result_ref_id"] == first_ref


def test_retry_failed_unverified_but_not_verified_or_over_limit() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"retry-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    approved = _approve_workflow(client, owner, workflow_id)
    step_id = approved.json()["steps"][0]["step_id"]
    with SessionLocal() as db:
        workflow = db.get(NovaAutonomyWorkflow, workflow_id)
        step = db.get(NovaAutonomyWorkflowStep, step_id)
        assert workflow is not None and step is not None
        workflow.status = "failed"
        step.status = "failed"
        step.executed_at = now()
        step.verified_at = None
        step.result_ref_id = None
        db.commit()
    retried = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/retry", headers=owner)
    assert retried.status_code == 200, retried.text
    assert retried.json()["status"] == "waiting"
    assert retried.json()["current_step"] == step_id
    assert retried.json()["retry_count"] == 1
    recovered = _approve_step(client, owner, workflow_id, step_id)
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "completed"
    assert recovered.json()["steps"][0]["result_ref_id"].startswith("INT-")
    verified_retry = client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/retry", headers=owner)
    assert verified_retry.status_code == 409

    limited = _create(client, owner, source_ref_id=f"limit-{uuid4()[:8]}")
    limited_id = limited.json()["workflow_id"]
    limited_approved = _approve_workflow(client, owner, limited_id)
    limited_step = limited_approved.json()["steps"][0]["step_id"]
    first = client.post(f"/api/nova/autonomy/v2/workflows/{limited_id}/retry", headers=owner)
    second = client.post(f"/api/nova/autonomy/v2/workflows/{limited_id}/retry", headers=owner)
    assert first.status_code == 200
    assert second.status_code == 200
    third = client.post(f"/api/nova/autonomy/v2/workflows/{limited_id}/retry", headers=owner)
    assert third.status_code == 409
    parked = client.get(f"/api/nova/autonomy/v2/workflows/{limited_id}", headers=owner)
    assert parked.json()["status"] == "waiting"
    assert parked.json()["current_step"] == limited_step
    assert parked.json()["executed"] is False


def test_invalid_transition_and_verification_required_before_advance() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, step_count=2, source_ref_id=f"verify-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    assert client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/pause", headers=owner).status_code == 409
    approved = _approve_workflow(client, owner, workflow_id)
    first, second = _ordered(approved.json())
    with SessionLocal() as db:
        step = db.get(NovaAutonomyWorkflowStep, first["step_id"])
        workflow = db.get(NovaAutonomyWorkflow, workflow_id)
        assert step is not None and workflow is not None
        step.status = "completed"
        step.result_ref_id = "INT-UNVERIFIED01"
        step.executed_at = now()
        step.verified_at = None
        workflow.current_step = second["step_id"]
        db.commit()
    skipped = _approve_step(client, owner, workflow_id, second["step_id"])
    assert skipped.status_code == 409
    parked = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert parked.json()["status"] == "waiting"
    assert _ordered(parked.json())[1]["status"] == "proposed"
    assert _ordered(parked.json())[1]["result_ref_id"] is None


def test_medium_stays_parked_high_and_prohibited_blocked() -> None:
    client = _client()
    owner = _login(client)
    medium = _create(client, owner, source_ref_id=f"med-{uuid4()[:8]}")
    medium_id = medium.json()["workflow_id"]
    _insert_current_step(
        medium_id,
        medium.json()["organization_id"],
        action_type="send_email",
        risk_class="MEDIUM",
        step_id="NWS-MEDIUM000001",
    )
    parked = _approve_step(client, owner, medium_id, "NWS-MEDIUM000001")
    assert parked.status_code == 200, parked.text
    assert parked.json()["status"] == "waiting"
    assert parked.json()["executed"] is False
    assert parked.json()["mutated_external"] is False
    assert parked.json()["steps"][0]["status"] == "awaiting_approval"
    assert parked.json()["steps"][0]["result_ref_id"] is None

    high = _create(client, owner, source_ref_id=f"high-{uuid4()[:8]}")
    high_id = high.json()["workflow_id"]
    _insert_current_step(
        high_id,
        high.json()["organization_id"],
        action_type="payout",
        risk_class="HIGH",
        step_id="NWS-HIGH00000001",
    )
    blocked = _approve_step(client, owner, high_id, "NWS-HIGH00000001")
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "blocked_by_policy"
    assert blocked.json()["executed"] is False
    assert blocked.json()["steps"][0]["status"] == "blocked_by_policy"
    assert blocked.json()["steps"][0]["result_ref_id"] is None

    prohibited = _create(client, owner, source_ref_id=f"proh-{uuid4()[:8]}")
    prohibited_id = prohibited.json()["workflow_id"]
    _insert_current_step(
        prohibited_id,
        prohibited.json()["organization_id"],
        action_type="delete",
        risk_class="PROHIBITED",
        step_id="NWS-PROHIB000001",
    )
    denied = _approve_step(client, owner, prohibited_id, "NWS-PROHIB000001")
    assert denied.status_code == 200, denied.text
    assert denied.json()["status"] == "blocked_by_policy"
    assert denied.json()["executed"] is False


def test_cross_org_read_and_approve_denied() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"xorg-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    foreign_read = client.get(
        f"/api/nova/autonomy/v2/workflows/{workflow_id}",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert foreign_read.status_code == 403
    foreign_approve = _approve_workflow(
        client, owner, workflow_id, organization_id="org-not-the-caller"
    )
    assert foreign_approve.status_code == 403
    visible = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert visible.status_code == 200
    assert visible.json()["status"] == "proposed"


def test_ledger_is_append_only_and_records_transitions() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, step_count=2, source_ref_id=f"led-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    first_history = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}/history", headers=owner)
    assert first_history.status_code == 200
    first_ids = [row["audit_id"] for row in first_history.json()]
    assert first_ids
    approved = _approve_workflow(client, owner, workflow_id)
    step_id = _ordered(approved.json())[0]["step_id"]
    executed = _approve_step(client, owner, workflow_id, step_id)
    assert executed.status_code == 200
    later = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}/history", headers=owner)
    later_ids = [row["audit_id"] for row in later.json()]
    assert later_ids[: len(first_ids)] == first_ids
    assert len(later_ids) > len(first_ids)
    required = {
        "organization_id",
        "workflow_id",
        "correlation_id",
        "action_type",
        "approval_state",
        "executed",
        "actor_user_id",
        "timestamp",
    }
    assert all(required.issubset(row) for row in later.json())
    assert any(row.get("step_id") == step_id and row.get("result_ref_id") for row in later.json())
    assert all(row.get("detail") != "secret" for row in later.json())
    with SessionLocal() as db:
        rows = (
            db.query(NovaAutonomyLedger)
            .filter(NovaAutonomyLedger.workflow_id == workflow_id)
            .order_by(NovaAutonomyLedger.created_at.asc())
            .all()
        )
        assert len(rows) == len(later_ids)
        assert {row.audit_id for row in rows} == set(later_ids)


def test_emergency_stop_prevents_progression() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    client = _client()
    owner = _login(client)
    created = _create(client, owner, step_count=2, source_ref_id=f"estop-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    approved = _approve_workflow(client, owner, workflow_id)
    first = _ordered(approved.json())[0]
    stopped = client.post("/api/nova/autonomy/v2/emergency-stop", headers=owner)
    assert stopped.status_code == 200, stopped.text
    assert stopped.json()["emergency_stop"] is True
    assert stopped.json()["phase2_enabled"] is False
    assert stopped.json()["executed"] is False
    blocked = _approve_step(client, owner, workflow_id, first["step_id"])
    assert blocked.status_code == 403
    assert _create(client, owner, source_ref_id=f"estop-new-{uuid4()[:8]}").status_code == 403
    stored = client.get(f"/api/nova/autonomy/v2/workflows/{workflow_id}", headers=owner)
    assert stored.status_code == 200
    assert stored.json()["status"] == "cancelled"
    with SessionLocal() as db:
        flag = db.get(NovaAutonomyOrgFlag, created.json()["organization_id"])
        assert flag is not None
        assert flag.emergency_stop is True
        assert db.get(NovaAutonomyWorkflow, workflow_id) is not None
        assert (
            db.query(NovaAutonomyLedger)
            .filter(NovaAutonomyLedger.workflow_id == workflow_id)
            .count()
            >= 1
        )
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    for path in AUTONOMY.glob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert all(marker not in text for marker in WORKER_MARKERS), path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = ",".join(alias.name for alias in node.names)
            else:
                continue
            assert "apscheduler" not in module
            assert "celery" not in module
