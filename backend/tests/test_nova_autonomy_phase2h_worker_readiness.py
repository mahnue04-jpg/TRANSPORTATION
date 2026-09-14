"""Phase 2H supervised job queue. No background runner, Phase 2 flag, or external writes."""
from __future__ import annotations

import ast
import os
import threading
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.models import (
    NovaAutonomyApproval,
    NovaAutonomyJob,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
    new_approval_id,
)
from app.core.nova.autonomy.v2_jobs import MAX_JOB_ATTEMPTS
from app.db.session import SessionLocal, engine, init_platform_db
from app.helpers import now, uuid4
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
AUTONOMY = ROOT / "app" / "core" / "nova" / "autonomy"
WORKER_MARKERS = ("apscheduler", "celery", "backgroundscheduler", "cron", "while true")
FORBIDDEN_MODULES = (
    "rider_checkout",
    "stripe_payments",
    "financial_engine",
    "health_isf",
    "app.modules.payments",
)
PROTECTED_PATH_MARKERS = (
    "ops-shell.js",
    "ops-shell.html",
    "rider_checkout.py",
    "stripe_payments.py",
    "financial_engine.py",
    "health_isf",
)


def _client() -> TestClient:
    from app.core.nova.autonomy.ledger import ensure_autonomy_schema
    from app.core.nova.today.schema_ensure import ensure_nova_today_schema

    ensure_auth_schema()
    seed_default_users()
    init_platform_db()
    ensure_nova_today_schema(engine)
    ensure_autonomy_schema(engine)
    with SessionLocal() as db:
        for flag in db.query(NovaAutonomyOrgFlag).all():
            flag.emergency_stop = False
            flag.phase2_enabled = False
        db.commit()
    return TestClient(app)


def _login(client: TestClient, email: str = "admin@amicor.local") -> dict[str, str]:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _create(client: TestClient, headers: dict[str, str], **extra):
    body = {
        "workflow_type": extra.pop("workflow_type", "research_draft_task"),
        "initiating_module": extra.pop("initiating_module", "today"),
        "source_ref_id": extra.pop("source_ref_id", f"p2h-{uuid4()[:10]}"),
    }
    body.update(extra)
    return client.post("/api/nova/autonomy/v2/workflows", headers=headers, json=body)


def _approve_workflow(client: TestClient, headers: dict[str, str], workflow_id: str):
    return client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=headers)


def _queue(client: TestClient, headers: dict[str, str], workflow_id: str, step_id: str, **params):
    return client.post(
        "/api/nova/autonomy/v2/jobs",
        headers=headers,
        params=params,
        json={"workflow_id": workflow_id, "step_id": step_id, **params},
    )


def _insert_step(
    workflow_id: str,
    organization_id: str,
    *,
    action_type: str,
    risk_class: str,
    step_id: str,
    source_module: str = "today",
    target_module: str | None = None,
) -> None:
    with SessionLocal() as db:
        db.add(
            NovaAutonomyWorkflowStep(
                step_id=step_id,
                workflow_id=workflow_id,
                organization_id=organization_id,
                sequence_number=1,
                source_module=source_module,
                target_module=target_module or source_module,
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


def _insert_approval(workflow_id: str, organization_id: str, step_id: str, approver_user_id: str) -> None:
    with SessionLocal() as db:
        db.add(
            NovaAutonomyApproval(
                approval_id=new_approval_id(),
                workflow_id=workflow_id,
                step_id=step_id,
                organization_id=organization_id,
                approver_user_id=approver_user_id,
                approval_scope="step",
                status="granted",
                created_at=now(),
            )
        )
        db.commit()


def test_approved_low_internal_step_can_be_queued() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    assert created.status_code == 200, created.text
    workflow_id = created.json()["workflow_id"]
    approved = _approve_workflow(client, owner, workflow_id)
    assert approved.status_code == 200, approved.text
    step_id = approved.json()["current_step"]
    queued = _queue(client, owner, workflow_id, step_id)
    assert queued.status_code == 200, queued.text
    body = queued.json()
    assert body["status"] == "queued"
    assert body["workflow_id"] == workflow_id
    assert body["step_id"] == step_id
    assert body["action_type"] == "internal_test"
    assert body["risk_class"] == "LOW"
    assert body["approval_id"]
    assert body["attempt_count"] == 0
    assert body["organization_id"] == created.json()["organization_id"]
    listed = client.get("/api/nova/autonomy/v2/jobs", headers=owner)
    assert listed.status_code == 200
    assert any(row["job_id"] == body["job_id"] for row in listed.json())
    fetched = client.get(f"/api/nova/autonomy/v2/jobs/{body['job_id']}", headers=owner)
    assert fetched.status_code == 200
    assert fetched.json()["job_id"] == body["job_id"]


def test_unapproved_step_cannot_be_queued() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    workflow_id = created.json()["workflow_id"]
    org_id = created.json()["organization_id"]
    _insert_step(
        workflow_id,
        org_id,
        action_type="internal_test",
        risk_class="LOW",
        step_id="NWS-P2HUNAPPROV1",
        source_module="autonomy",
    )
    denied = _queue(client, owner, workflow_id, "NWS-P2HUNAPPROV1")
    assert denied.status_code == 409
    dispatcher = _login(client, "dispatcher@amicor.local")
    approved = _create(client, owner, source_ref_id=f"disp-{uuid4()[:8]}")
    approved_wf = _approve_workflow(client, owner, approved.json()["workflow_id"])
    blocked = _queue(
        client,
        dispatcher,
        approved.json()["workflow_id"],
        approved_wf.json()["current_step"],
    )
    assert blocked.status_code == 403


def test_high_action_blocked() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"high-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    org_id = created.json()["organization_id"]
    _insert_step(
        workflow_id,
        org_id,
        action_type="payout",
        risk_class="HIGH",
        step_id="NWS-P2HHIGH00001",
        source_module="payments_readiness",
    )
    _insert_approval(workflow_id, org_id, "NWS-P2HHIGH00001", created.json()["owner_user_id"])
    blocked = _queue(client, owner, workflow_id, "NWS-P2HHIGH00001")
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "blocked"
    assert blocked.json()["last_error"] == "high_or_prohibited"
    claim = client.post(f"/api/nova/autonomy/v2/jobs/{blocked.json()['job_id']}/claim", headers=owner)
    assert claim.status_code == 409
    run = client.post(f"/api/nova/autonomy/v2/jobs/{blocked.json()['job_id']}/run", headers=owner)
    assert run.status_code == 409


def test_prohibited_action_blocked() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"proh-{uuid4()[:8]}")
    workflow_id = created.json()["workflow_id"]
    org_id = created.json()["organization_id"]
    _insert_step(
        workflow_id,
        org_id,
        action_type="driver_001",
        risk_class="PROHIBITED",
        step_id="NWS-P2HPROHIB001",
        source_module="today",
    )
    _insert_approval(workflow_id, org_id, "NWS-P2HPROHIB001", created.json()["owner_user_id"])
    blocked = _queue(client, owner, workflow_id, "NWS-P2HPROHIB001")
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["status"] == "blocked"
    medium = _create(client, owner, source_ref_id=f"med-{uuid4()[:8]}")
    _insert_step(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        action_type="send_email",
        risk_class="MEDIUM",
        step_id="NWS-P2HMEDIUM001",
        source_module="communications",
    )
    _insert_approval(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        "NWS-P2HMEDIUM001",
        medium.json()["owner_user_id"],
    )
    parked = _queue(client, owner, medium.json()["workflow_id"], "NWS-P2HMEDIUM001")
    assert parked.status_code == 409


def test_cross_org_queue_access_denied() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    denied = _queue(
        client,
        owner,
        created.json()["workflow_id"],
        approved.json()["current_step"],
        organization_id="org-not-the-caller",
    )
    assert denied.status_code == 403
    listed = client.get(
        "/api/nova/autonomy/v2/jobs",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert listed.status_code == 403


def test_cross_org_claim_denied() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    assert queued.status_code == 200, queued.text
    job_id = queued.json()["job_id"]
    claim = client.post(
        f"/api/nova/autonomy/v2/jobs/{job_id}/claim",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert claim.status_code == 403
    run = client.post(
        f"/api/nova/autonomy/v2/jobs/{job_id}/run",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert run.status_code == 403
    retry = client.post(
        f"/api/nova/autonomy/v2/jobs/{job_id}/retry",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert retry.status_code == 403
    cancel = client.post(
        f"/api/nova/autonomy/v2/jobs/{job_id}/cancel",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert cancel.status_code == 403
    fetched = client.get(
        f"/api/nova/autonomy/v2/jobs/{job_id}",
        headers=owner,
        params={"organization_id": "org-not-the-caller"},
    )
    assert fetched.status_code == 403


def test_duplicate_idempotent_queue_creation() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"idemp-{uuid4()[:8]}")
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    step_id = approved.json()["current_step"]
    first = _queue(client, owner, created.json()["workflow_id"], step_id)
    second = _queue(client, owner, created.json()["workflow_id"], step_id)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["job_id"] == second.json()["job_id"]
    with SessionLocal() as db:
        rows = (
            db.query(NovaAutonomyJob)
            .filter(
                NovaAutonomyJob.organization_id == created.json()["organization_id"],
                NovaAutonomyJob.workflow_id == created.json()["workflow_id"],
                NovaAutonomyJob.step_id == step_id,
            )
            .all()
        )
        assert len(rows) == 1


def test_successful_internal_test_job_transitions() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"ok-{uuid4()[:8]}")
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    assert queued.json()["status"] == "queued"
    claimed = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/claim", headers=owner)
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["status"] == "claimed"
    assert claimed.json()["locked_at"] is not None
    ran = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/run", headers=owner)
    assert ran.status_code == 200, ran.text
    assert ran.json()["status"] == "succeeded"
    assert ran.json()["result_ref_id"].startswith("INT-")
    assert ran.json()["attempt_count"] == 1
    assert ran.json()["completed_at"] is not None
    assert ran.json()["locked_at"] is None
    assert ran.json()["mutated_external"] is False
    replay = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/run", headers=owner)
    assert replay.status_code == 200
    assert replay.json()["result_ref_id"] == ran.json()["result_ref_id"]


def test_failed_job_records_error_and_attempt() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id="job-fail-closed")
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/claim", headers=owner)
    failed = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/run", headers=owner)
    assert failed.status_code == 200, failed.text
    assert failed.json()["status"] == "failed"
    assert failed.json()["last_error"]
    assert failed.json()["attempt_count"] == 1
    assert failed.json()["completed_at"] is None


def test_retry_limit_enforced() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id="job-fail-closed")
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    job_id = queued.json()["job_id"]
    for _ in range(MAX_JOB_ATTEMPTS):
        client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/claim", headers=owner)
        failed = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/run", headers=owner)
        assert failed.json()["status"] == "failed"
        retried = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/retry", headers=owner)
        if failed.json()["attempt_count"] >= MAX_JOB_ATTEMPTS:
            assert retried.status_code == 409
        else:
            assert retried.status_code == 200, retried.text
            assert retried.json()["status"] == "queued"
    denied = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/retry", headers=owner)
    assert denied.status_code == 409


def test_cancelled_job_cannot_execute() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner)
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    cancelled = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/cancel", headers=owner)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    claim = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/claim", headers=owner)
    assert claim.status_code == 409
    run = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/run", headers=owner)
    assert run.status_code == 409
    retry = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/retry", headers=owner)
    assert retry.status_code == 409


def test_audit_history_records_queue_transitions() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"audit-{uuid4()[:8]}")
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    job_id = queued.json()["job_id"]
    client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/claim", headers=owner)
    client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/run", headers=owner)
    history = client.get(
        f"/api/nova/autonomy/v2/workflows/{created.json()['workflow_id']}/history",
        headers=owner,
    )
    assert history.status_code == 200
    details = [str(row.get("detail") or "") for row in history.json()]
    assert any(f"job_id={job_id}" in detail and "old=none new=queued" in detail for detail in details)
    assert any("old=queued new=claimed" in detail for detail in details)
    assert any("old=claimed new=running" in detail for detail in details)
    assert any("old=running new=succeeded" in detail for detail in details)
    with SessionLocal() as db:
        rows = (
            db.query(NovaAutonomyLedger)
            .filter(NovaAutonomyLedger.workflow_id == created.json()["workflow_id"])
            .all()
        )
        job_rows = [row for row in rows if job_id in str(row.detail or "")]
        assert job_rows
        assert all(row.organization_id == created.json()["organization_id"] for row in job_rows)
        assert all(row.correlation_id for row in job_rows)
        assert all(row.step_id for row in job_rows)
        assert all("secret" not in str(row.detail or "").lower() for row in rows)
        assert all("sk_" not in str(row.detail or "") for row in rows)


def test_no_real_external_adapter_execution() -> None:
    from app.core.nova.autonomy import v2_adapters

    calls: list[str] = []
    original = v2_adapters.invoke

    def _blocked(*_args, **_kwargs):
        calls.append("invoke")
        raise AssertionError("adapter invoke must not run from Phase 2H jobs")

    v2_adapters.invoke = _blocked  # type: ignore[method-assign]
    try:
        client = _client()
        owner = _login(client)
        created = _create(client, owner, source_ref_id=f"adp-{uuid4()[:8]}")
        approved = _approve_workflow(client, owner, created.json()["workflow_id"])
        queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
        client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/claim", headers=owner)
        ran = client.post(f"/api/nova/autonomy/v2/jobs/{queued.json()['job_id']}/run", headers=owner)
        assert ran.status_code == 200, ran.text
        assert ran.json()["status"] == "succeeded"
        assert ran.json()["mutated_external"] is False
        assert calls == []
    finally:
        v2_adapters.invoke = original  # type: ignore[method-assign]


def test_phase2_flag_off_no_background_runner_protected_paths() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    before = threading.active_count()
    from app.core.nova.autonomy import v2_jobs

    client = _client()
    owner = _login(client)
    flag = client.get("/api/nova/autonomy/v2/org-flag", headers=owner)
    assert flag.status_code == 200
    assert flag.json()["phase2_enabled"] is False
    assert flag.json()["emergency_stop"] is False
    assert threading.active_count() <= before + 1
    assert not hasattr(v2_jobs, "start")
    assert not hasattr(v2_jobs, "start_worker")
    routes = {getattr(route, "path", "") for route in app.routes}
    forbidden_routes = (
        "/api/nova/autonomy/v2/jobs/run-continuously",
        "/api/nova/autonomy/v2/jobs/auto-execute",
        "/api/nova/autonomy/v2/jobs/start-worker",
        "/api/nova/autonomy/v2/enable-autonomy",
    )
    assert not any(path in routes for path in forbidden_routes)
    jobs_text = (AUTONOMY / "v2_jobs.py").read_text(encoding="utf-8").lower()
    assert all(marker not in jobs_text for marker in PROTECTED_PATH_MARKERS)
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
            else:
                continue
            assert all(banned not in module for banned in FORBIDDEN_MODULES), f"{path.name} imports {module}"
    render = REPO / "render.yaml"
    if render.exists():
        render_text = render.read_text(encoding="utf-8").lower()
        assert "nova-autonomy-worker" not in render_text
        assert "phase2h" not in render_text
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}


def test_emergency_stop_prevents_claim_and_execution() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"stop-{uuid4()[:8]}")
    org_id = created.json()["organization_id"]
    try:
        approved = _approve_workflow(client, owner, created.json()["workflow_id"])
        queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
        assert queued.status_code == 200, queued.text
        job_id = queued.json()["job_id"]
        stopped = client.post("/api/nova/autonomy/v2/emergency-stop", headers=owner)
        assert stopped.status_code == 200, stopped.text
        assert stopped.json()["emergency_stop"] is True
        claim = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/claim", headers=owner)
        assert claim.status_code == 403
        run = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/run", headers=owner)
        assert run.status_code == 403
        nxt = client.post("/api/nova/autonomy/v2/jobs/claim-next", headers=owner)
        assert nxt.status_code == 403
        parked = client.get(f"/api/nova/autonomy/v2/jobs/{job_id}", headers=owner)
        assert parked.status_code == 200
        assert parked.json()["status"] == "queued"
        another = _create(client, owner, source_ref_id=f"after-{uuid4()[:8]}")
        assert another.status_code == 403
        with SessionLocal() as db:
            rows = (
                db.query(NovaAutonomyLedger)
                .filter(NovaAutonomyLedger.source_ref_id == job_id)
                .all()
            )
            assert any(row.result == "emergency_stop_blocked" for row in rows)
            org_flag = db.get(NovaAutonomyOrgFlag, org_id)
            assert org_flag is not None
            assert org_flag.emergency_stop is True
            assert org_flag.phase2_enabled is False
    finally:
        with SessionLocal() as db:
            flag = db.get(NovaAutonomyOrgFlag, org_id)
            if flag is not None:
                flag.emergency_stop = False
                db.commit()
