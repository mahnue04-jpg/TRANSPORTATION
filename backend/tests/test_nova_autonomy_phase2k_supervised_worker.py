"""Phase 2K single-shot supervised process-one tick. No background runner."""
from __future__ import annotations

import ast
import os
import threading
from datetime import timedelta
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
from app.core.nova.autonomy.v2_jobs import LOCK_STALE_SECONDS, MAX_JOB_ATTEMPTS
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
        for job in db.query(NovaAutonomyJob).filter(
            NovaAutonomyJob.status.in_(("queued", "claimed", "running"))
        ).all():
            job.status = "cancelled"
            job.locked_at = None
            job.updated_at = now()
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
        "source_ref_id": extra.pop("source_ref_id", f"p2k-{uuid4()[:10]}"),
    }
    body.update(extra)
    return client.post("/api/nova/autonomy/v2/workflows", headers=headers, json=body)


def _approve_workflow(client: TestClient, headers: dict[str, str], workflow_id: str):
    return client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=headers)


def _queue(client: TestClient, headers: dict[str, str], workflow_id: str, step_id: str, **params):
    return client.post(
        "/api/nova/autonomy/v2/jobs",
        headers=headers,
        json={"workflow_id": workflow_id, "step_id": step_id, **params},
    )


def _process_one(client: TestClient, headers: dict[str, str], **params):
    return client.post("/api/nova/autonomy/v2/jobs/process-one", headers=headers, params=params)


def _enable_phase2(organization_id: str, *, emergency_stop: bool = False) -> None:
    with SessionLocal() as db:
        flag = db.get(NovaAutonomyOrgFlag, organization_id)
        if flag is None:
            db.add(
                NovaAutonomyOrgFlag(
                    organization_id=organization_id,
                    phase2_enabled=True,
                    emergency_stop=emergency_stop,
                    updated_at=now(),
                )
            )
        else:
            flag.phase2_enabled = True
            flag.emergency_stop = emergency_stop
            flag.updated_at = now()
        db.commit()


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


def _queue_internal(client: TestClient, owner: dict[str, str], **extra) -> dict:
    created = _create(client, owner, **extra)
    assert created.status_code == 200, created.text
    approved = _approve_workflow(client, owner, created.json()["workflow_id"])
    assert approved.status_code == 200, approved.text
    queued = _queue(client, owner, created.json()["workflow_id"], approved.json()["current_step"])
    assert queued.status_code == 200, queued.text
    return {
        "org_id": created.json()["organization_id"],
        "owner_user_id": created.json()["owner_user_id"],
        "workflow_id": created.json()["workflow_id"],
        "step_id": approved.json()["current_step"],
        "job": queued.json(),
    }


def test_owner_admin_can_process_one_eligible_internal_job() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"ok-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    result = _process_one(client, owner)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["processed"] == 1
    assert body["mutated_external"] is False
    assert body["phase2_enabled"] is True
    assert body["verification_result"] == "verified"
    job = body["job"]
    assert job["job_id"] == seeded["job"]["job_id"]
    assert job["status"] == "succeeded"
    assert job["action_type"] == "internal_test"
    assert job["result_ref_id"].startswith("INT-")
    assert job["attempt_count"] == 1


def test_unauthorized_role_cannot_process_a_job() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"role-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    dispatcher = _login(client, "dispatcher@amicor.local")
    denied = _process_one(client, dispatcher)
    assert denied.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_phase2_flag_off_blocks_processing() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"flag-{uuid4()[:8]}")
    blocked = _process_one(client, owner)
    assert blocked.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_emergency_stop_blocks_processing() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"stop-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"], emergency_stop=True)
    blocked = _process_one(client, owner)
    assert blocked.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"
    with SessionLocal() as db:
        flag = db.get(NovaAutonomyOrgFlag, seeded["org_id"])
        assert flag is not None
        flag.emergency_stop = False
        flag.phase2_enabled = False
        db.commit()


def test_only_one_job_processed_per_request() -> None:
    client = _client()
    owner = _login(client)
    first = _queue_internal(client, owner, source_ref_id=f"one-a-{uuid4()[:8]}")
    second = _queue_internal(client, owner, source_ref_id=f"one-b-{uuid4()[:8]}")
    _enable_phase2(first["org_id"])
    result = _process_one(client, owner)
    assert result.status_code == 200, result.text
    assert result.json()["processed"] == 1
    processed_id = result.json()["job"]["job_id"]
    assert processed_id in {first["job"]["job_id"], second["job"]["job_id"]}
    other_id = first["job"]["job_id"] if processed_id == second["job"]["job_id"] else second["job"]["job_id"]
    other = client.get(f"/api/nova/autonomy/v2/jobs/{other_id}", headers=owner)
    assert other.json()["status"] == "queued"
    done = client.get(f"/api/nova/autonomy/v2/jobs/{processed_id}", headers=owner)
    assert done.json()["status"] == "succeeded"


def test_tenant_isolation_holds() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"xorg-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    denied = _process_one(client, owner, organization_id="org-not-the-caller")
    assert denied.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_duplicate_idempotent_jobs_are_not_re_executed() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"idemp-{uuid4()[:8]}")
    again = _queue(client, owner, seeded["workflow_id"], seeded["step_id"])
    assert again.json()["job_id"] == seeded["job"]["job_id"]
    _enable_phase2(seeded["org_id"])
    first = _process_one(client, owner)
    assert first.status_code == 200, first.text
    ref = first.json()["job"]["result_ref_id"]
    second = _process_one(client, owner)
    assert second.status_code == 404
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "succeeded"
    assert stored.json()["result_ref_id"] == ref
    assert stored.json()["attempt_count"] == 1


def test_retry_limit_is_enforced() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id="job-fail-closed")
    _enable_phase2(seeded["org_id"])
    job_id = seeded["job"]["job_id"]
    for _ in range(MAX_JOB_ATTEMPTS):
        ran = _process_one(client, owner)
        assert ran.status_code == 200, ran.text
        assert ran.json()["job"]["status"] == "failed"
        retried = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/retry", headers=owner)
        if ran.json()["job"]["attempt_count"] >= MAX_JOB_ATTEMPTS:
            assert retried.status_code == 409
        else:
            assert retried.status_code == 200
    denied = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/retry", headers=owner)
    assert denied.status_code == 409
    missing = _process_one(client, owner)
    assert missing.status_code == 404


def test_stale_lock_recovery_works() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"stale-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    with SessionLocal() as db:
        job = db.get(NovaAutonomyJob, seeded["job"]["job_id"])
        assert job is not None
        job.status = "claimed"
        job.locked_at = now() - timedelta(seconds=LOCK_STALE_SECONDS + 30)
        db.commit()
    result = _process_one(client, owner)
    assert result.status_code == 200, result.text
    assert result.json()["processed"] == 1
    assert result.json()["released_stale_locks"] >= 1
    assert result.json()["job"]["status"] == "succeeded"
    assert result.json()["job"]["job_id"] == seeded["job"]["job_id"]


def test_low_internal_allowed_medium_high_prohibited_blocked() -> None:
    client = _client()
    owner = _login(client)
    history = _create(client, owner, source_ref_id=f"hist-{uuid4()[:8]}")
    org_id = history.json()["organization_id"]
    _insert_step(
        history.json()["workflow_id"],
        org_id,
        action_type="history",
        risk_class="LOW",
        step_id="NWS-P2KHISTORY01",
        source_module="today",
    )
    _insert_approval(history.json()["workflow_id"], org_id, "NWS-P2KHISTORY01", history.json()["owner_user_id"])
    queued_history = _queue(client, owner, history.json()["workflow_id"], "NWS-P2KHISTORY01")
    assert queued_history.status_code == 200, queued_history.text
    _enable_phase2(org_id)
    low = _process_one(client, owner)
    assert low.status_code == 200, low.text
    assert low.json()["job"]["action_type"] == "history"
    assert low.json()["job"]["status"] == "succeeded"
    assert low.json()["job"]["mutated_external"] is False
    assert low.json()["verification_result"] == "verified"

    medium = _create(client, owner, source_ref_id=f"med-{uuid4()[:8]}")
    _insert_step(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        action_type="send_email",
        risk_class="MEDIUM",
        step_id="NWS-P2KMEDIUM001",
        source_module="communications",
    )
    _insert_approval(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        "NWS-P2KMEDIUM001",
        medium.json()["owner_user_id"],
    )
    parked = _queue(client, owner, medium.json()["workflow_id"], "NWS-P2KMEDIUM001")
    assert parked.status_code == 409
    with SessionLocal() as db:
        db.add(
            NovaAutonomyJob(
                job_id="NWJ-P2KMEDIUM001",
                organization_id=medium.json()["organization_id"],
                workflow_id=medium.json()["workflow_id"],
                step_id="NWS-P2KMEDIUM001",
                correlation_id=medium.json()["correlation_id"],
                action_type="send_email",
                target_module="communications",
                risk_class="MEDIUM",
                status="queued",
                attempt_count=0,
                created_at=now(),
                updated_at=now(),
                available_at=now(),
            )
        )
        db.commit()
    skipped = _process_one(client, owner)
    assert skipped.status_code == 404
    medium_job = client.get("/api/nova/autonomy/v2/jobs/NWJ-P2KMEDIUM001", headers=owner)
    assert medium_job.status_code == 200
    assert medium_job.json()["status"] == "queued"
    assert medium_job.json()["result_ref_id"] is None

    high = _create(client, owner, source_ref_id=f"high-{uuid4()[:8]}")
    _insert_step(
        high.json()["workflow_id"],
        high.json()["organization_id"],
        action_type="payout",
        risk_class="HIGH",
        step_id="NWS-P2KHIGH00001",
        source_module="payments_readiness",
    )
    _insert_approval(
        high.json()["workflow_id"],
        high.json()["organization_id"],
        "NWS-P2KHIGH00001",
        high.json()["owner_user_id"],
    )
    blocked_high = _queue(client, owner, high.json()["workflow_id"], "NWS-P2KHIGH00001")
    assert blocked_high.status_code == 200
    assert blocked_high.json()["status"] == "blocked"
    tick_high = _process_one(client, owner)
    assert tick_high.status_code == 404
    assert blocked_high.json()["status"] == "blocked"

    prohibited = _create(client, owner, source_ref_id=f"proh-{uuid4()[:8]}")
    _insert_step(
        prohibited.json()["workflow_id"],
        prohibited.json()["organization_id"],
        action_type="driver_001",
        risk_class="PROHIBITED",
        step_id="NWS-P2KPROHIB001",
        source_module="today",
    )
    _insert_approval(
        prohibited.json()["workflow_id"],
        prohibited.json()["organization_id"],
        "NWS-P2KPROHIB001",
        prohibited.json()["owner_user_id"],
    )
    blocked_proh = _queue(client, owner, prohibited.json()["workflow_id"], "NWS-P2KPROHIB001")
    assert blocked_proh.json()["status"] == "blocked"
    tick_proh = _process_one(client, owner)
    assert tick_proh.status_code == 404


def test_external_mutation_blocked_and_audit_verification() -> None:
    from app.core.nova.autonomy import v2_adapters

    calls: list[str] = []
    original = v2_adapters.invoke

    def _blocked(*_args, **_kwargs):
        calls.append("invoke")
        raise AssertionError("adapter invoke must not run from Phase 2K process-one")

    v2_adapters.invoke = _blocked  # type: ignore[method-assign]
    try:
        client = _client()
        owner = _login(client)
        seeded = _queue_internal(client, owner, source_ref_id=f"adp-{uuid4()[:8]}")
        _enable_phase2(seeded["org_id"])
        result = _process_one(client, owner)
        assert result.status_code == 200, result.text
        assert result.json()["mutated_external"] is False
        assert result.json()["verification_result"] == "verified"
        assert result.json()["job"]["result_ref_id"].startswith("INT-")
        assert calls == []
        with SessionLocal() as db:
            rows = (
                db.query(NovaAutonomyLedger)
                .filter(NovaAutonomyLedger.workflow_id == seeded["workflow_id"])
                .all()
            )
            details = [str(row.detail or "") for row in rows]
            results = [row.result for row in rows]
            assert any(seeded["job"]["job_id"] in detail for detail in details)
            assert "process_one_tick" in results
            assert "job_succeeded" in results
            assert any(row.verification_result == "verified" for row in rows)
            assert all("secret" not in str(row.detail or "").lower() for row in rows)
    finally:
        v2_adapters.invoke = original  # type: ignore[method-assign]


def test_no_loop_cron_scheduler_or_background_worker() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    before = threading.active_count()
    from app.core.nova.autonomy import v2_jobs

    client = _client()
    owner = _login(client)
    flag = client.get("/api/nova/autonomy/v2/org-flag", headers=owner)
    assert flag.json()["phase2_enabled"] is False
    assert threading.active_count() <= before + 1
    assert not hasattr(v2_jobs, "start")
    assert not hasattr(v2_jobs, "start_worker")
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/api/nova/autonomy/v2/jobs/process-one" in routes
    assert "/api/nova/autonomy/v2/jobs/run-continuously" not in routes
    assert "/api/nova/autonomy/v2/jobs/start-worker" not in routes
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
    assert render.exists()
    render_text = render.read_text(encoding="utf-8").lower()
    assert "type: worker" not in render_text
    assert "nova-autonomy-worker" not in render_text
    jobs_text = (AUTONOMY / "v2_jobs.py").read_text(encoding="utf-8")
    assert "process_one_job" in jobs_text
    assert "ops-shell.js" not in jobs_text
    assert "workflow_runner" not in jobs_text
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
