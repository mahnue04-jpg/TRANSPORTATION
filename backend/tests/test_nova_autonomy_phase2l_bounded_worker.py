"""Phase 2L bounded supervised process-batch. Finite ticks only. No background runner."""
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
from app.core.nova.autonomy.v2_jobs import (
    DEFAULT_BATCH_MAX_JOBS,
    HARD_BATCH_MAX_JOBS,
    LOCK_STALE_SECONDS,
    MAX_JOB_ATTEMPTS,
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
        "source_ref_id": extra.pop("source_ref_id", f"p2l-{uuid4()[:10]}"),
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


def _process_batch(client: TestClient, headers: dict[str, str], **params):
    return client.post("/api/nova/autonomy/v2/jobs/process-batch", headers=headers, params=params)


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


def test_owner_admin_can_process_bounded_batch() -> None:
    client = _client()
    owner = _login(client)
    first = _queue_internal(client, owner, source_ref_id=f"ok-a-{uuid4()[:8]}")
    second = _queue_internal(client, owner, source_ref_id=f"ok-b-{uuid4()[:8]}")
    _enable_phase2(first["org_id"])
    result = _process_batch(client, owner, max_jobs=2)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["requested_max_jobs"] == 2
    assert body["processed_count"] == 2
    assert body["succeeded_count"] == 2
    assert body["failed_count"] == 0
    assert body["blocked_count"] == 0
    assert body["mutated_external"] is False
    assert set(body["processed_job_ids"]) == {first["job"]["job_id"], second["job"]["job_id"]}
    assert all(row["status"] == "succeeded" for row in body["jobs"])
    assert all(row["verification_result"] == "verified" for row in body["jobs"])
    assert all(row["mutated_external"] is False for row in body["jobs"])


def test_unauthorized_caller_blocked() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"role-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    dispatcher = _login(client, "dispatcher@amicor.local")
    denied = _process_batch(client, dispatcher, max_jobs=1)
    assert denied.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_phase2_flag_off_blocks_batch() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"flag-{uuid4()[:8]}")
    blocked = _process_batch(client, owner, max_jobs=1)
    assert blocked.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_emergency_stop_blocks_before_first_job() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"stop-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"], emergency_stop=True)
    blocked = _process_batch(client, owner, max_jobs=3)
    assert blocked.status_code == 403
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_emergency_stop_between_jobs_stops_remaining() -> None:
    from app.core.nova.autonomy import v2_jobs

    client = _client()
    owner = _login(client)
    first = _queue_internal(client, owner, source_ref_id=f"mid-a-{uuid4()[:8]}")
    second = _queue_internal(client, owner, source_ref_id=f"mid-b-{uuid4()[:8]}")
    _enable_phase2(first["org_id"])
    original = v2_jobs.run_job

    def _flip(db, job_id, *, user, requested_org=None):
        ran = original(db, job_id, user=user, requested_org=requested_org)
        with SessionLocal() as session:
            flag = session.get(NovaAutonomyOrgFlag, first["org_id"])
            assert flag is not None
            flag.emergency_stop = True
            session.commit()
        return ran

    v2_jobs.run_job = _flip  # type: ignore[method-assign]
    try:
        result = _process_batch(client, owner, max_jobs=5)
        assert result.status_code == 200, result.text
        body = result.json()
        assert body["processed_count"] == 1
        assert body["succeeded_count"] == 1
        assert body["stopped_reason"] == "emergency_stop"
        remaining = {first["job"]["job_id"], second["job"]["job_id"]} - set(body["processed_job_ids"])
        assert len(remaining) == 1
        parked = client.get(f"/api/nova/autonomy/v2/jobs/{next(iter(remaining))}", headers=owner)
        assert parked.json()["status"] == "queued"
    finally:
        v2_jobs.run_job = original  # type: ignore[method-assign]


def test_default_max_jobs_is_one() -> None:
    client = _client()
    owner = _login(client)
    first = _queue_internal(client, owner, source_ref_id=f"def-a-{uuid4()[:8]}")
    second = _queue_internal(client, owner, source_ref_id=f"def-b-{uuid4()[:8]}")
    _enable_phase2(first["org_id"])
    result = _process_batch(client, owner)
    assert result.status_code == 200, result.text
    body = result.json()
    assert DEFAULT_BATCH_MAX_JOBS == 1
    assert body["requested_max_jobs"] == 1
    assert body["processed_count"] == 1
    assert body["stopped_reason"] == "max_jobs_reached"
    other_id = (
        second["job"]["job_id"]
        if body["processed_job_ids"][0] == first["job"]["job_id"]
        else first["job"]["job_id"]
    )
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{other_id}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_max_jobs_cannot_exceed_five() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"cap-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    denied = _process_batch(client, owner, max_jobs=HARD_BATCH_MAX_JOBS + 1)
    assert denied.status_code == 400
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_exactly_requested_eligible_jobs_processed() -> None:
    client = _client()
    owner = _login(client)
    seeded = [_queue_internal(client, owner, source_ref_id=f"n-{i}-{uuid4()[:6]}") for i in range(4)]
    _enable_phase2(seeded[0]["org_id"])
    result = _process_batch(client, owner, max_jobs=3)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["processed_count"] == 3
    assert body["succeeded_count"] == 3
    assert len(body["processed_job_ids"]) == 3
    remaining = [row["job"]["job_id"] for row in seeded if row["job"]["job_id"] not in body["processed_job_ids"]]
    assert len(remaining) == 1
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{remaining[0]}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_empty_queue_stops_cleanly() -> None:
    client = _client()
    owner = _login(client)
    created = _create(client, owner, source_ref_id=f"empty-{uuid4()[:8]}")
    _enable_phase2(created.json()["organization_id"])
    result = _process_batch(client, owner, max_jobs=3)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["processed_count"] == 0
    assert body["succeeded_count"] == 0
    assert body["stopped_reason"] == "no_eligible_jobs"
    assert body["processed_job_ids"] == []


def test_tenant_isolation_holds() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id=f"xorg-{uuid4()[:8]}")
    _enable_phase2(seeded["org_id"])
    denied = _process_batch(client, owner, max_jobs=1, organization_id="org-not-the-caller")
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
    first = _process_batch(client, owner, max_jobs=2)
    assert first.status_code == 200, first.text
    assert first.json()["processed_count"] == 1
    ref = first.json()["jobs"][0]["verification_result"]
    second = _process_batch(client, owner, max_jobs=2)
    assert second.status_code == 200, second.text
    assert second.json()["processed_count"] == 0
    assert second.json()["stopped_reason"] == "no_eligible_jobs"
    stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
    assert stored.json()["status"] == "succeeded"
    assert stored.json()["attempt_count"] == 1
    assert ref == "verified"


def test_retry_limit_is_enforced() -> None:
    client = _client()
    owner = _login(client)
    seeded = _queue_internal(client, owner, source_ref_id="job-fail-closed")
    _enable_phase2(seeded["org_id"])
    job_id = seeded["job"]["job_id"]
    for _ in range(MAX_JOB_ATTEMPTS):
        ran = _process_batch(client, owner, max_jobs=1)
        assert ran.status_code == 200, ran.text
        assert ran.json()["jobs"][0]["status"] == "failed"
        retried = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/retry", headers=owner)
        if ran.json()["jobs"][0]["status"] == "failed":
            stored = client.get(f"/api/nova/autonomy/v2/jobs/{job_id}", headers=owner)
            if stored.json()["attempt_count"] >= MAX_JOB_ATTEMPTS:
                assert retried.status_code == 409
            else:
                assert retried.status_code == 200
    denied = client.post(f"/api/nova/autonomy/v2/jobs/{job_id}/retry", headers=owner)
    assert denied.status_code == 409
    missing = _process_batch(client, owner, max_jobs=1)
    assert missing.status_code == 200
    assert missing.json()["processed_count"] == 0


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
    result = _process_batch(client, owner, max_jobs=1)
    assert result.status_code == 200, result.text
    assert result.json()["processed_count"] == 1
    assert result.json()["released_stale_locks"] >= 1
    assert result.json()["jobs"][0]["status"] == "succeeded"
    assert result.json()["jobs"][0]["job_id"] == seeded["job"]["job_id"]


def test_low_internal_allowed_medium_high_prohibited_blocked() -> None:
    client = _client()
    owner = _login(client)
    history = _create(client, owner, source_ref_id=f"hist-{uuid4()[:8]}")
    org_id = history.json()["organization_id"]
    step_id = f"NWS-P2LHIST{uuid4()[:4].upper()}"
    _insert_step(
        history.json()["workflow_id"],
        org_id,
        action_type="history",
        risk_class="LOW",
        step_id=step_id,
        source_module="today",
    )
    _insert_approval(history.json()["workflow_id"], org_id, step_id, history.json()["owner_user_id"])
    queued_history = _queue(client, owner, history.json()["workflow_id"], step_id)
    assert queued_history.status_code == 200, queued_history.text
    _enable_phase2(org_id)
    low = _process_batch(client, owner, max_jobs=1)
    assert low.status_code == 200, low.text
    stored_low = client.get(f"/api/nova/autonomy/v2/jobs/{queued_history.json()['job_id']}", headers=owner)
    assert stored_low.json()["action_type"] == "history"
    assert stored_low.json()["status"] == "succeeded"
    assert stored_low.json()["mutated_external"] is False

    medium = _create(client, owner, source_ref_id=f"med-{uuid4()[:8]}")
    med_step = f"NWS-P2LMED{uuid4()[:5].upper()}"
    _insert_step(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        action_type="send_email",
        risk_class="MEDIUM",
        step_id=med_step,
        source_module="communications",
    )
    _insert_approval(
        medium.json()["workflow_id"],
        medium.json()["organization_id"],
        med_step,
        medium.json()["owner_user_id"],
    )
    parked = _queue(client, owner, medium.json()["workflow_id"], med_step)
    assert parked.status_code == 409
    medium_job_id = f"NWJ-P2LMED{uuid4()[:5].upper()}"
    with SessionLocal() as db:
        db.add(
            NovaAutonomyJob(
                job_id=medium_job_id,
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
    skipped = _process_batch(client, owner, max_jobs=1)
    assert skipped.status_code == 200
    assert skipped.json()["processed_count"] == 0
    medium_job = client.get(f"/api/nova/autonomy/v2/jobs/{medium_job_id}", headers=owner)
    assert medium_job.json()["status"] == "queued"
    assert medium_job.json()["result_ref_id"] is None

    high = _create(client, owner, source_ref_id=f"high-{uuid4()[:8]}")
    high_step = f"NWS-P2LHI{uuid4()[:6].upper()}"
    _insert_step(
        high.json()["workflow_id"],
        high.json()["organization_id"],
        action_type="payout",
        risk_class="HIGH",
        step_id=high_step,
        source_module="payments_readiness",
    )
    _insert_approval(
        high.json()["workflow_id"],
        high.json()["organization_id"],
        high_step,
        high.json()["owner_user_id"],
    )
    blocked_high = _queue(client, owner, high.json()["workflow_id"], high_step)
    assert blocked_high.status_code == 200
    assert blocked_high.json()["status"] == "blocked"
    tick_high = _process_batch(client, owner, max_jobs=1)
    assert tick_high.status_code == 200
    assert tick_high.json()["processed_count"] == 0
    assert client.get(f"/api/nova/autonomy/v2/jobs/{blocked_high.json()['job_id']}", headers=owner).json()["status"] == "blocked"

    prohibited = _create(client, owner, source_ref_id=f"proh-{uuid4()[:8]}")
    proh_step = f"NWS-P2LPR{uuid4()[:6].upper()}"
    _insert_step(
        prohibited.json()["workflow_id"],
        prohibited.json()["organization_id"],
        action_type="driver_001",
        risk_class="PROHIBITED",
        step_id=proh_step,
        source_module="today",
    )
    _insert_approval(
        prohibited.json()["workflow_id"],
        prohibited.json()["organization_id"],
        proh_step,
        prohibited.json()["owner_user_id"],
    )
    blocked_proh = _queue(client, owner, prohibited.json()["workflow_id"], proh_step)
    assert blocked_proh.json()["status"] == "blocked"
    tick_proh = _process_batch(client, owner, max_jobs=1)
    assert tick_proh.json()["processed_count"] == 0


def test_external_mutation_blocked_and_audit_verification() -> None:
    from app.core.nova.autonomy import v2_adapters

    calls: list[str] = []
    original = v2_adapters.invoke

    def _blocked(*_args, **_kwargs):
        calls.append("invoke")
        raise AssertionError("adapter invoke must not run from Phase 2L process-batch")

    v2_adapters.invoke = _blocked  # type: ignore[method-assign]
    try:
        client = _client()
        owner = _login(client)
        seeded = _queue_internal(client, owner, source_ref_id=f"adp-{uuid4()[:8]}")
        _enable_phase2(seeded["org_id"])
        result = _process_batch(client, owner, max_jobs=1)
        assert result.status_code == 200, result.text
        assert result.json()["mutated_external"] is False
        assert result.json()["jobs"][0]["mutated_external"] is False
        assert result.json()["jobs"][0]["verification_result"] == "verified"
        assert calls == []
        stored = client.get(f"/api/nova/autonomy/v2/jobs/{seeded['job']['job_id']}", headers=owner)
        assert stored.json()["result_ref_id"].startswith("INT-")
        with SessionLocal() as db:
            rows = (
                db.query(NovaAutonomyLedger)
                .filter(NovaAutonomyLedger.workflow_id == seeded["workflow_id"])
                .all()
            )
            details = [str(row.detail or "") for row in rows]
            results = [row.result for row in rows]
            assert any(seeded["job"]["job_id"] in detail for detail in details)
            assert "process_batch_tick" in results
            assert "job_succeeded" in results
            assert any(row.verification_result == "verified" for row in rows)
            assert all("secret" not in str(row.detail or "").lower() for row in rows)
    finally:
        v2_adapters.invoke = original  # type: ignore[method-assign]


def test_verification_failure_stops_batch() -> None:
    client = _client()
    owner = _login(client)
    failing = _queue_internal(client, owner, source_ref_id="job-fail-closed")
    later = _queue_internal(client, owner, source_ref_id=f"after-{uuid4()[:8]}")
    _enable_phase2(failing["org_id"])
    result = _process_batch(client, owner, max_jobs=5)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["processed_count"] == 1
    assert body["failed_count"] == 1
    assert body["stopped_reason"] == "verification_failure"
    assert body["processed_job_ids"] == [failing["job"]["job_id"]]
    parked = client.get(f"/api/nova/autonomy/v2/jobs/{later['job']['job_id']}", headers=owner)
    assert parked.json()["status"] == "queued"


def test_audit_record_exists_for_every_attempted_tick() -> None:
    client = _client()
    owner = _login(client)
    first = _queue_internal(client, owner, source_ref_id=f"aud-a-{uuid4()[:8]}")
    second = _queue_internal(client, owner, source_ref_id=f"aud-b-{uuid4()[:8]}")
    _enable_phase2(first["org_id"])
    result = _process_batch(client, owner, max_jobs=2)
    assert result.status_code == 200, result.text
    with SessionLocal() as db:
        ticks = (
            db.query(NovaAutonomyLedger)
            .filter(NovaAutonomyLedger.result == "process_batch_tick")
            .all()
        )
        job_ids = {row.source_ref_id for row in ticks}
        assert first["job"]["job_id"] in job_ids
        assert second["job"]["job_id"] in job_ids
        assert len(ticks) >= 2


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
    assert "/api/nova/autonomy/v2/jobs/process-batch" in routes
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
    assert "process_batch_jobs" in jobs_text
    assert "for _tick in range(requested)" in jobs_text
    assert "ops-shell.js" not in jobs_text
    assert "workflow_runner" not in jobs_text
    assert (os.getenv("NOVA_AUTONOMY_PHASE2") or "").strip().lower() not in {"1", "true", "on", "yes"}
