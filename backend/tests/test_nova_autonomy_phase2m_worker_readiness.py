"""Phase 2M fail-closed worker readiness. No Render worker, cron, or auto-start."""
from __future__ import annotations

import ast
import inspect
import os
import signal
import threading
from datetime import timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, UserContext, ensure_auth_schema, seed_default_users
from app.core.nova.autonomy.models import (
    NovaAutonomyApproval,
    NovaAutonomyJob,
    NovaAutonomyLedger,
    NovaAutonomyOrgFlag,
    NovaAutonomyWorkflow,
    NovaAutonomyWorkflowStep,
    new_approval_id,
)
from app.core.nova.autonomy.v2_jobs import HARD_BATCH_MAX_JOBS, LOCK_STALE_SECONDS, process_batch_jobs
from app.core.nova.autonomy.v2_worker import (
    MIN_POLL_INTERVAL_SECONDS,
    WORKER_ENABLED_ENV,
    AutonomyWorker,
    env_flag_enabled,
    main as worker_main,
)
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

    os.environ.pop(WORKER_ENABLED_ENV, None)
    os.environ.pop("NOVA_AUTONOMY_PHASE2", None)
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
        "initiating_module": extra.pop("initiating_module", "autonomy"),
        "source_ref_id": extra.pop("source_ref_id", f"p2m-{uuid4()[:10]}"),
    }
    body.update(extra)
    return client.post("/api/nova/autonomy/v2/workflows", headers=headers, json=body)


def _approve_workflow(client: TestClient, headers: dict[str, str], workflow_id: str):
    return client.post(f"/api/nova/autonomy/v2/workflows/{workflow_id}/approve", headers=headers)


def _queue(client: TestClient, headers: dict[str, str], workflow_id: str, step_id: str):
    return client.post(
        "/api/nova/autonomy/v2/jobs",
        headers=headers,
        json={"workflow_id": workflow_id, "step_id": step_id},
    )


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


def _insert_step(workflow_id: str, organization_id: str, *, action_type: str, risk_class: str, step_id: str, source_module: str = "today") -> None:
    with SessionLocal() as db:
        db.add(
            NovaAutonomyWorkflowStep(
                step_id=step_id,
                workflow_id=workflow_id,
                organization_id=organization_id,
                sequence_number=1,
                source_module=source_module,
                target_module=source_module,
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


def _actor(seeded: dict, role: str = "admin") -> UserContext:
    return UserContext(
        user_id=seeded["owner_user_id"],
        email="admin@amicor.local",
        role=role,
        organization_id=seeded["org_id"],
    )


def _worker(seeded: dict, **extra) -> AutonomyWorker:
    sleeps: list[float] = extra.pop("sleeps", [])
    return AutonomyWorker(
        enabled=extra.pop("enabled", True),
        organization_id=seeded["org_id"],
        user=extra.pop("user", _actor(seeded)),
        poll_interval_seconds=extra.pop("poll_interval_seconds", MIN_POLL_INTERVAL_SECONDS),
        max_jobs_per_cycle=extra.pop("max_jobs_per_cycle", 1),
        empty_backoff_seconds=extra.pop("empty_backoff_seconds", MIN_POLL_INTERVAL_SECONDS),
        error_backoff_seconds=extra.pop("error_backoff_seconds", MIN_POLL_INTERVAL_SECONDS),
        max_critical_failures=extra.pop("max_critical_failures", 3),
        sleeper=extra.pop("sleeper", sleeps.append),
        **extra,
    )


def test_worker_disabled_by_default() -> None:
    os.environ.pop(WORKER_ENABLED_ENV, None)
    assert env_flag_enabled(WORKER_ENABLED_ENV) is False
    worker = AutonomyWorker()
    assert worker.enabled is False
    assert worker_main() == 0


def test_disabled_worker_processes_zero_jobs() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"off-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    worker = _worker(seeded, enabled=False)
    assert worker.run(max_cycles=3) == 0
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "queued"


def test_worker_requires_phase2_enabled() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"p2-{uuid4()[:8]}")
    worker = _worker(seeded)
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    assert result.stopped_reason == "phase2_disabled"
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "queued"


def test_emergency_stop_prevents_processing() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"stop-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"], emergency_stop=True)
    worker = _worker(seeded)
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    assert result.stopped_reason == "emergency_stop"
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "queued"


def test_worker_reuses_process_batch() -> None:
    source = inspect.getsource(AutonomyWorker.run_cycle)
    assert "process_batch_jobs(" in source
    assert "should_claim" in source
    assert process_batch_jobs.__name__ == "process_batch_jobs"


def test_hard_max_five_jobs_per_cycle() -> None:
    client = _client()
    owner = _login(client)
    seeded = [_queue_internal(client, owner, source_ref_id=f"cap-{i}-{uuid4()[:4]}") for i in range(6)]
    _enable_phase2(seeded[0]["org_id"])
    worker = _worker(seeded[0], max_jobs_per_cycle=99)
    assert worker.max_jobs_per_cycle == HARD_BATCH_MAX_JOBS == 5
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 5
    remaining = [row["job"]["job_id"] for row in seeded if row["job"]["job_id"] not in result.processed_job_ids]
    assert len(remaining) == 1
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{remaining[0]}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_owner_approved_low_internal_only() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"low-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    worker = _worker(seeded)
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 1
    assert result.succeeded_count == 1
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["action_type"] == "internal_test"
    assert stored.json()["status"] == "succeeded"


def test_medium_remains_parked() -> None:
    client = _client()
    owner = _login(client)
    medium = _create(client, owner, source_ref_id=f"med-{uuid4()[:8]}")
    med_step = f"NWS-P2MMED{uuid4()[:5].upper()}"
    _insert_step(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        action_type="send_email",
        risk_class="MEDIUM",
        step_id=med_step,
        source_module="communications",
    )
    _insert_approval(medium.json()["workflow_id"], medium.json()["organization_id"], med_step, medium.json()["owner_user_id"])
    assert _queue(client, owner, medium.json()["workflow_id"], med_step).status_code == 409
    job_id = f"NWJ-P2MMED{uuid4()[:5].upper()}"
    with SessionLocal() as db:
        db.add(
            NovaAutonomyJob(
                job_id=job_id,
                organization_id=medium.json()["organization_id"],
                workflow_id=medium.json()["workflow_id"],
                step_id=med_step,
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
    _enable_phase2(medium.json()["organization_id"])
    worker = _worker({"org_id": medium.json()["organization_id"], "owner_user_id": medium.json()["owner_user_id"]})
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{job_id}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_high_blocked() -> None:
    client = _client()
    owner = _login(client)
    high = _create(client, owner, source_ref_id=f"high-{uuid4()[:8]}")
    high_step = f"NWS-P2MHI{uuid4()[:6].upper()}"
    _insert_step(
        high.json()["workflow_id"],
        high.json()["organization_id"],
        action_type="payout",
        risk_class="HIGH",
        step_id=high_step,
        source_module="payments_readiness",
    )
    _insert_approval(high.json()["workflow_id"], high.json()["organization_id"], high_step, high.json()["owner_user_id"])
    blocked = _queue(client, owner, high.json()["workflow_id"], high_step)
    assert blocked.json()["status"] == "blocked"
    _enable_phase2(high.json()["organization_id"])
    worker = _worker({"org_id": high.json()["organization_id"], "owner_user_id": high.json()["owner_user_id"]})
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{blocked.json()['job_id']}", headers=owner)
    assert stored.json()["status"] == "blocked"


def test_prohibited_blocked() -> None:
    client = _client()
    owner = _login(client)
    prohibited = _create(client, owner, source_ref_id=f"proh-{uuid4()[:8]}")
    step_id = f"NWS-P2MPR{uuid4()[:6].upper()}"
    _insert_step(
        prohibited.json()["workflow_id"],
        prohibited.json()["organization_id"],
        action_type="driver_001",
        risk_class="PROHIBITED",
        step_id=step_id,
    )
    _insert_approval(prohibited.json()["workflow_id"], prohibited.json()["organization_id"], step_id, prohibited.json()["owner_user_id"])
    blocked = _queue(client, owner, prohibited.json()["workflow_id"], step_id)
    assert blocked.json()["status"] == "blocked"
    _enable_phase2(prohibited.json()["organization_id"])
    worker = _worker({"org_id": prohibited.json()["organization_id"], "owner_user_id": prohibited.json()["owner_user_id"]})
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{blocked.json()['job_id']}", headers=owner)
    assert stored.json()["status"] == "blocked"


def test_external_mutation_blocked() -> None:
    from app.core.nova.autonomy import v2_adapters

    calls: list[str] = []
    original = v2_adapters.invoke

    def _blocked(*_args, **_kwargs):
        calls.append("invoke")
        raise AssertionError("adapter invoke must not run from Phase 2M worker")

    v2_adapters.invoke = _blocked  # type: ignore[method-assign]
    try:
        client = _client()
        owner = _login(client)
        seeded = _queue_internal(client, owner, source_ref_id=f"ext-{uuid4()[:8]}")
        _enable_phase2(seeded["org_id"])
        worker = _worker(seeded)
        with SessionLocal() as db:
            result = worker.run_cycle(db)
        assert result.mutated_external is False
        assert result.jobs[0].mutated_external is False
        assert calls == []
    finally:
        v2_adapters.invoke = original  # type: ignore[method-assign]


def test_tenant_isolation_preserved() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"ten-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    other = _actor(seeded)
    other.organization_id = "org-not-the-caller"
    worker = _worker(seeded, user=other)
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 0
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_idempotency_preserved() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"idemp-{uuid4()[:8]}")
    again = _queue(client, owner, seeded["workflow_id"], seeded["step_id"])
    assert again.json()["job_id"] == seeded["job"]["job_id"]
    _enable_phase2(seeded["org_id"])
    worker = _worker(seeded)
    with SessionLocal() as db:
        first = worker.run_cycle(db)
        second = worker.run_cycle(db)
    assert first.processed_count == 1
    assert second.processed_count == 0
    assert second.stopped_reason == "no_eligible_jobs"
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "succeeded"
    assert stored.json()["attempt_count"] == 1


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
    worker = _worker(seeded)
    with SessionLocal() as db:
        result = worker.run_cycle(db)
    assert result.processed_count == 1
    assert result.jobs[0].status == "succeeded"


def test_safe_empty_queue_backoff() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"empty-{uuid4()[:8]}")
    seeded = {"org_id": created.json()["organization_id"], "owner_user_id": created.json()["owner_user_id"]}
    _enable_phase2(seeded["org_id"])
    sleeps: list[float] = []
    worker = _worker(seeded, sleeps=sleeps, empty_backoff_seconds=MIN_POLL_INTERVAL_SECONDS + 2)
    assert worker.run(max_cycles=1) == 0
    assert worker.last_stopped_reason == "no_eligible_jobs"
    assert sleeps
    assert sleeps[0] >= MIN_POLL_INTERVAL_SECONDS + 2


def test_transient_error_backoff() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"tmp-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    sleeps: list[float] = []
    worker = _worker(seeded, sleeps=sleeps, error_backoff_seconds=MIN_POLL_INTERVAL_SECONDS + 3)

    def _boom(_db):
        raise TimeoutError("transient")

    worker.run_cycle = _boom  # type: ignore[method-assign]
    assert worker.run(max_cycles=1) == 0
    assert worker.last_stopped_reason == "transient_error"
    assert worker.last_error == "TimeoutError"
    assert sleeps[0] >= MIN_POLL_INTERVAL_SECONDS + 3


def test_repeated_critical_failure_fails_closed() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"crit-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    worker = _worker(seeded, max_critical_failures=2)

    def _boom(_db):
        raise RuntimeError("critical")

    worker.run_cycle = _boom  # type: ignore[method-assign]
    code = worker.run(max_cycles=5)
    assert code == 2
    assert worker.fail_closed is True
    assert worker.shutdown_requested is True
    assert worker.critical_failures >= 2
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "queued"


def test_sigterm_safe_shutdown() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"term-{uuid4()[:8]}")
    worker = _worker(seeded)
    worker.install_signal_handlers()
    worker.handle_signal(signal.SIGTERM)
    assert worker.shutdown_requested is True
    assert worker.run(max_cycles=3) == 0
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "queued"


def test_sigint_safe_shutdown() -> None:
    worker = AutonomyWorker(enabled=True, organization_id="org-x", user=_actor({"org_id": "org-x", "owner_user_id": "u1"}))
    worker.handle_signal(signal.SIGINT)
    assert worker.shutdown_requested is True
    health = worker.health()
    assert health.shutdown_requested is True
    assert health.alive is False


def test_no_new_claims_after_shutdown_request() -> None:
    from app.core.nova.autonomy import v2_jobs

    client = _client()
    owner = _login(client)
    first = _queue_internal(client, owner, source_ref_id=f"shut-a-{uuid4()[:8]}")
    second = _queue_internal(client, owner, source_ref_id=f"shut-b-{uuid4()[:8]}")
    _enable_phase2(first["org_id"])
    worker = _worker(first, max_jobs_per_cycle=2)
    original = v2_jobs.run_job

    def _flip(db, job_id, *, user, requested_org=None):
        ran = original(db, job_id, user=user, requested_org=requested_org)
        worker.request_shutdown()
        return ran

    v2_jobs.run_job = _flip  # type: ignore[method-assign]
    try:
        with SessionLocal() as db:
            result = worker.run_cycle(db)
        assert result.processed_count == 1
        assert result.stopped_reason == "shutdown_requested"
        remaining = {first["job"]["job_id"], second["job"]["job_id"]} - set(result.processed_job_ids)
        assert len(remaining) == 1
        parked = client.get(f"/api/nova/autonomy/v2/jobs/{next(iter(remaining))}", headers=owner)
        assert parked.json()["status"] == "queued"
    finally:
        v2_jobs.run_job = original  # type: ignore[method-assign]


def test_worker_cycle_audit_record_written() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"aud-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    worker = _worker(seeded, instance_id="NWW-TESTCYCLE01")
    assert worker.run(max_cycles=1) == 0
    with SessionLocal() as db:
        rows = (
            db.query(NovaAutonomyLedger)
            .filter(
                NovaAutonomyLedger.organization_id == seeded["org_id"],
                NovaAutonomyLedger.result == "worker_cycle",
                NovaAutonomyLedger.source_ref_id == "NWW-TESTCYCLE01",
            )
            .all()
        )
        assert rows
        detail = str(rows[0].detail or "")
        assert "processed=" in detail
        assert "succeeded=" in detail
        assert "failed=" in detail
        assert "blocked=" in detail
        assert "stopped=" in detail
        assert "duration_ms=" in detail
        assert "NWW-TESTCYCLE01" in detail
        assert "secret" not in detail.lower()


def test_worker_health_readiness_state_accurate() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"hlth-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    worker = _worker(seeded)
    before = worker.health()
    assert before.enabled is True
    assert before.alive is False
    assert before.jobs_processed == 0
    assert before.shutdown_requested is False
    assert worker.run(max_cycles=1) == 0
    after = worker.health()
    assert after.jobs_processed == 1
    assert after.last_successful_cycle_at is not None
    assert after.last_error is None
    assert after.cycles_completed == 1
    ready = worker.readiness()
    assert ready["jobs_processed"] == 1
    assert ready["last_error"] is None
    assert ready["shutdown_requested"] is False
    worker.request_shutdown()
    assert worker.health().shutdown_requested is True


def test_no_cron_scheduler_or_background_worker() -> None:
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
    assert env_flag_enabled(WORKER_ENABLED_ENV) is False
    before = threading.active_count()
    from app.core.nova.autonomy import v2_worker

    client = _client()
    _login(client)
    assert threading.active_count() <= before + 1
    assert not hasattr(v2_worker, "start")
    assert not hasattr(v2_worker, "start_worker")
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
    jobs_text = (AUTONOMY / "v2_jobs.py").read_text(encoding="utf-8")
    worker_text = (AUTONOMY / "v2_worker.py").read_text(encoding="utf-8")
    assert "while not self.shutdown_requested" in worker_text
    assert "process_batch_jobs" in worker_text
    assert "ops-shell.js" not in worker_text
    assert "workflow_runner" not in worker_text
    assert "apscheduler" not in jobs_text.lower()


def test_render_yaml_untouched() -> None:
    render = REPO / "render.yaml"
    assert render.exists()
    text = render.read_text(encoding="utf-8").lower()
    assert "type: worker" not in text
    assert "nova-autonomy-worker" not in text
    assert "v2_worker" not in text


def test_web_process_does_not_auto_start_worker() -> None:
    main_text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "v2_worker" not in main_text
    assert "AutonomyWorker" not in main_text
    from app.core.nova.autonomy import v2_worker

    assert v2_worker.main is not None
    assert worker_main() == 0
