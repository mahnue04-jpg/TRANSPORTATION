"""Concurrency, recovery, shared rate limit, retention, and worker tests."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ["NOVA_GROWTH_AGENT_DEMO_MODE"] = "true"
os.environ.setdefault("TESTING", "true")

from app.core.nova.growth_agent.errors import GrowthAgentError
from app.core.nova.growth_agent.models import (
    GaConversationMessage,
    GaDeliveryAttempt,
    GaUsageEvent,
)
from app.core.nova.growth_agent.rate_limit import check_and_increment, current_count
from app.core.nova.growth_agent.retention import execute_retention, preview_retention
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.core.nova.growth_agent.service import GrowthAgentService
from app.core.nova.growth_agent.worker import MockDeliveryWorker


@pytest.fixture(autouse=True)
def _enable_mock_worker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_BACKGROUND_WORKER", "true")


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ensure_growth_agent_schema(bind=eng)
    return eng


@pytest.fixture()
def Session(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture()
def db(Session):
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _activate(svc: GrowthAgentService, org: str):
    return svc.upsert_profile(
        org,
        "owner-1",
        {
            "business_name": "Worker Biz",
            "website": "https://worker.example",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [{"code": "consult", "name": "Consult", "duration_minutes": 30}],
            "faqs": [{"id": "f1", "question": "Hours?", "keywords": ["hours"], "answer": "9-5"}],
            "contact_email": "o@worker.example",
            "handoff_phone": "+15555550100",
            "escalation_settings": {},
            "quiet_hours": {"enabled": False},
        },
        activate=True,
    )


def test_shared_rate_limit_concurrent_and_restart(Session, db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-rate")
    # Seed installation id used as bucket
    widget = svc.create_widget_installation("org-rate", domain="worker.example")
    install_id = widget["installation_id"]
    bucket = f"widget:{install_id}"
    limit = 5

    def hit(_i: int):
        local = Session()
        try:
            check_and_increment(
                local,
                organization_id="org-rate",
                bucket_key=bucket,
                limit=limit,
                commit=True,
            )
            return "ok"
        except GrowthAgentError as exc:
            return exc.code
        finally:
            local.close()

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = [pool.submit(hit, i) for i in range(12)]
        for fut in as_completed(futs):
            results.append(fut.result())

    assert results.count("ok") == limit
    assert results.count("RATE_LIMITED") == 12 - limit
    assert current_count(db, organization_id="org-rate", bucket_key=bucket) == limit

    # Restart simulation: new session still sees durable counter.
    db2 = Session()
    try:
        with pytest.raises(GrowthAgentError) as exc:
            check_and_increment(
                db2,
                organization_id="org-rate",
                bucket_key=bucket,
                limit=limit,
                commit=True,
            )
        assert exc.value.code == "RATE_LIMITED"
    finally:
        db2.close()


def test_worker_claim_process_duplicate_and_tenant_isolation(Session, db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-w1")
    _activate(svc, "org-w2")
    c1 = svc._upsert_contact(
        "org-w1",
        name="A",
        email="a@w1.example",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    c2 = svc._upsert_contact(
        "org-w2",
        name="B",
        email="b@w2.example",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()

    p1 = svc.preview_workflow("org-w1", workflow_code="inquiry_ack", contact_id=c1.id)
    # Leave queued (worker flag on → execute defers)
    e1 = svc.approve_and_execute_workflow(
        "org-w1",
        run_id=p1["run_id"],
        dry_run=True,
        idempotency_key="w1-exec",
    )
    assert e1.get("mock_worker_deferred") is True
    assert any(a.get("status") == "queued" for a in e1["attempts"])

    p2 = svc.preview_workflow("org-w2", workflow_code="inquiry_ack", contact_id=c2.id)
    svc.approve_and_execute_workflow(
        "org-w2",
        run_id=p2["run_id"],
        dry_run=True,
        idempotency_key="w2-exec",
    )

    worker = MockDeliveryWorker(Session, organization_id="org-w1", worker_id="test-w1")
    out = worker.run_once(limit=10)
    assert out["live_send"] is False
    assert out["mock_only"] is True
    assert out["processed"] >= 1
    assert all(r.get("status") in {"sent_mock", "suppressed"} for r in out["results"])

    # Tenant isolation: org-w1 worker must not complete org-w2 jobs
    remaining_w2 = (
        db.query(GaDeliveryAttempt)
        .filter_by(organization_id="org-w2", status="queued")
        .count()
    )
    assert remaining_w2 >= 1

    # Duplicate protection: re-run should not double-send completed idempotency keys
    again = worker.run_once(limit=10)
    assert again["claimed"] == 0 or all(r.get("status") != "sent_mock" or r.get("deduped") for r in again["results"])


def test_worker_restart_reclaims_stale_lease(Session, db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-lease")
    contact = svc._upsert_contact(
        "org-lease",
        name="Lease",
        email="lease@example.com",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    preview = svc.preview_workflow("org-lease", workflow_code="inquiry_ack", contact_id=contact.id)
    svc.approve_and_execute_workflow(
        "org-lease",
        run_id=preview["run_id"],
        dry_run=True,
        idempotency_key="lease-exec",
    )
    row = (
        db.query(GaDeliveryAttempt)
        .filter_by(organization_id="org-lease", status="queued")
        .one()
    )
    # Simulate crashed worker holding a stale lease.
    row.status = "running"
    row.claimed_by = "dead-worker"
    row.claimed_at = datetime.utcnow() - timedelta(minutes=10)
    row.lease_expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()

    worker = MockDeliveryWorker(Session, organization_id="org-lease", worker_id="reclaimer")
    out = worker.run_once()
    assert out["processed"] == 1
    assert out["results"][0]["status"] == "sent_mock"


def test_worker_respects_opt_out_and_pause(Session, db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-gate")
    contact = svc._upsert_contact(
        "org-gate",
        name="Gate",
        email="gate@example.com",
        consent_transactional=True,
        consent_marketing=True,
        channel="email",
        source="test",
    )
    db.commit()
    preview = svc.preview_workflow(
        "org-gate",
        workflow_code="post_service_followup",
        contact_id=contact.id,
    )
    svc.approve_and_execute_workflow(
        "org-gate",
        run_id=preview["run_id"],
        dry_run=True,
        idempotency_key="mkt-exec",
    )
    svc.record_consent(
        "org-gate",
        contact_id=contact.id,
        channel="email",
        purpose="marketing",
        status="opted_out",
        collection_source="owner_opt_out",
        actor_user_id="owner-1",
    )
    worker = MockDeliveryWorker(Session, organization_id="org-gate", worker_id="gate-w")
    out = worker.run_once()
    assert out["processed"] == 1
    assert out["results"][0]["status"] == "suppressed"


def test_retention_preview_and_gated_delete(db, monkeypatch):
    svc = GrowthAgentService(db)
    _activate(svc, "org-ret")
    # Old message eligible for cleanup
    old = datetime.utcnow() - timedelta(days=400)
    msg = GaConversationMessage(
        id="old-msg-1",
        organization_id="org-ret",
        conversation_id="conv-missing-ok",
        role="visitor",
        content="old",
        created_at=old,
    )
    usage = GaUsageEvent(
        id="old-usage-1",
        organization_id="org-ret",
        meter="email",
        quantity=1,
        unit_cost_usd=0.0,
        provider="mock",
        created_at=old,
    )
    db.add(msg)
    db.add(usage)
    db.commit()

    preview = preview_retention(db, "org-ret", batch_limit=50)
    assert preview["dry_run"] is True
    assert preview["categories"]["conversation_messages"]["eligible_count"] >= 1
    assert "consent_records" in preview["retain_always"]

    monkeypatch.delenv("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED", raising=False)
    with pytest.raises(GrowthAgentError) as exc:
        execute_retention(db, "org-ret", batch_limit=50)
    assert exc.value.code == "RETENTION_DELETE_DISABLED"

    monkeypatch.setenv("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED", "true")
    # Force re-read via force_enabled for deterministic test even if flag cache-ish
    result = execute_retention(db, "org-ret", batch_limit=50, force_enabled=True)
    assert result["dry_run"] is False
    assert result["deleted_counts"]["conversation_messages"] >= 1
    assert result["total_deleted"] >= 1
    assert db.query(GaConversationMessage).filter_by(id="old-msg-1").count() == 0


def test_diagnostics_distinguishes_mock(db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-diag")
    diag = svc.diagnostics("org-diag")
    assert diag["mock_processing_only"] is True
    assert diag["live_delivery"] is False
    assert diag["worker"]["live_worker"] is False
    assert "retention_preview" in diag
    assert "retention_schedule" in diag
    assert diag["retention_schedule"]["dry_run_default"] is True
    assert diag["retention_schedule"]["mode"] == "dry_run"
    assert diag["distinction"]["real"]


def test_scheduled_retention_dry_run_default_and_duplicate_guard(Session, db, monkeypatch):
    from app.core.nova.growth_agent.models import GaRetentionScheduleRun
    from app.core.nova.growth_agent.retention_schedule import RetentionScheduler, current_window_key

    monkeypatch.delenv("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED", raising=False)
    monkeypatch.setenv("NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED", "true")
    svc = GrowthAgentService(db)
    _activate(svc, "org-sched")
    old = datetime.utcnow() - timedelta(days=400)
    db.add(
        GaConversationMessage(
            id="sched-old-msg",
            organization_id="org-sched",
            conversation_id="conv-sched",
            role="visitor",
            content="old",
            created_at=old,
        )
    )
    db.commit()

    scheduler = RetentionScheduler(Session, organization_id="org-sched", scheduler_id="sched-test")
    window = current_window_key()
    first = scheduler.run_once(window_key=window)
    assert first["mode"] == "dry_run"
    assert first["delete_enabled"] is False
    assert first["processed"] == 1
    assert first["results"][0]["status"] == "completed"
    assert first["results"][0]["mode"] == "dry_run"
    # Dry-run must not delete
    assert db.query(GaConversationMessage).filter_by(id="sched-old-msg").count() == 1

    # Duplicate protection: same window cannot create a second durable run
    again = scheduler.run_once(window_key=window)
    assert again["claimed"] == 0
    assert (
        db.query(GaRetentionScheduleRun)
        .filter_by(organization_id="org-sched", window_key=window)
        .count()
        == 1
    )


def test_scheduled_retention_reclaims_expired_lease(Session, db, monkeypatch):
    from app.core.nova.growth_agent.models import GaRetentionScheduleRun
    from app.core.nova.growth_agent.retention_schedule import RetentionScheduler, current_window_key

    monkeypatch.setenv("NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED", "true")
    monkeypatch.delenv("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED", raising=False)
    svc = GrowthAgentService(db)
    _activate(svc, "org-lease-ret")
    window = current_window_key()
    row = GaRetentionScheduleRun(
        id="lease-ret-1",
        organization_id="org-lease-ret",
        window_key=window,
        status="running",
        mode="dry_run",
        claimed_by="dead-scheduler",
        claimed_at=datetime.utcnow() - timedelta(minutes=10),
        lease_expires_at=datetime.utcnow() - timedelta(minutes=5),
        available_at=datetime.utcnow() - timedelta(minutes=5),
        attempt_number=1,
        max_attempts=5,
        batch_limit=50,
        result_json={},
    )
    db.add(row)
    db.commit()

    scheduler = RetentionScheduler(
        Session, organization_id="org-lease-ret", scheduler_id="reclaimer-ret"
    )
    out = scheduler.run_once(window_key=window, ensure=False)
    assert out["processed"] == 1
    assert out["results"][0]["status"] == "completed"
    db.refresh(row)
    assert row.status == "completed"
    assert row.claimed_by is None


def test_scheduled_retention_delete_requires_separate_flag(Session, db, monkeypatch):
    from app.core.nova.growth_agent.retention_schedule import RetentionScheduler, current_window_key

    monkeypatch.setenv("NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED", "true")
    monkeypatch.setenv("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED", "true")
    svc = GrowthAgentService(db)
    _activate(svc, "org-del-sched")
    old = datetime.utcnow() - timedelta(days=400)
    db.add(
        GaConversationMessage(
            id="del-sched-msg",
            organization_id="org-del-sched",
            conversation_id="conv-del",
            role="visitor",
            content="old",
            created_at=old,
        )
    )
    db.commit()
    scheduler = RetentionScheduler(
        Session, organization_id="org-del-sched", scheduler_id="del-sched"
    )
    out = scheduler.run_once(window_key=current_window_key())
    assert out["mode"] == "delete"
    assert out["processed"] == 1
    assert db.query(GaConversationMessage).filter_by(id="del-sched-msg").count() == 0


def test_graceful_shutdown_releases_unprocessed(Session, db):
    svc = GrowthAgentService(db)
    _activate(svc, "org-stop")
    contact = svc._upsert_contact(
        "org-stop",
        name="Stop",
        email="stop@example.com",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    # Queue two jobs
    for i in range(2):
        preview = svc.preview_workflow("org-stop", workflow_code="inquiry_ack", contact_id=contact.id)
        # Force distinct idempotency by unique run
        svc.approve_and_execute_workflow(
            "org-stop",
            run_id=preview["run_id"],
            dry_run=True,
            idempotency_key=f"stop-{i}-{preview['run_id']}",
        )

    worker = MockDeliveryWorker(Session, organization_id="org-stop", worker_id="stopper")
    worker.request_shutdown()
    out = worker.run_once(limit=10)
    # With stop already set, claimed jobs are released back to queued without processing.
    assert out["processed"] == 0
    queued = (
        db.query(GaDeliveryAttempt)
        .filter_by(organization_id="org-stop", status="queued")
        .count()
    )
    assert queued >= 1
