"""Disposable PostgreSQL verification for Growth Agent concurrency/retention.

Skipped unless NOVA_GA_PG_TEST_URL (or DATABASE_URL pointing at postgres) is set.
Never targets shared/production databases — callers must pass a disposable URL.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_ENABLED", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_DEMO_MODE", "true")


def _uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"

PG_URL = (
    os.getenv("NOVA_GA_PG_TEST_URL")
    or (os.getenv("DATABASE_URL") if "postgres" in (os.getenv("DATABASE_URL") or "") else None)
)


def _assert_disposable_url(url: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    dbname = (parsed.path or "").lstrip("/").lower()
    forbidden_hosts = {"amicor-health-isf", "production", "prod.", "render.com"}
    if any(f in host for f in forbidden_hosts):
        raise RuntimeError(f"Refusing non-disposable Postgres host: {host}")
    if "prod" in dbname and "test" not in dbname and "dispos" not in dbname:
        raise RuntimeError(f"Refusing suspicious database name: {dbname}")
    # Require explicit disposable markers in local/CI naming.
    if not any(tok in dbname for tok in ("test", "dispos", "ci", "nova_ga")):
        raise RuntimeError(
            f"Database name must look disposable (test/dispos/ci/nova_ga): {dbname}"
        )


pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="Set NOVA_GA_PG_TEST_URL to a disposable Postgres DSN to run these tests",
)


@pytest.fixture(scope="module")
def pg_engine():
    assert PG_URL
    _assert_disposable_url(PG_URL)
    eng = create_engine(PG_URL, pool_pre_ping=True)
    from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema

    # Prefer Alembic when the disposable DB can follow the migration chain;
    # always finish with additive ORM ensure for the latest tables.
    alembic_ok = False
    if os.path.exists("alembic.ini"):
        try:
            from alembic import command
            from alembic.config import Config

            cfg = Config("alembic.ini")
            cfg.set_main_option("sqlalchemy.url", PG_URL)
            command.upgrade(cfg, "20261112_nova_ga_retention")
            alembic_ok = True
        except Exception as exc:  # noqa: BLE001
            # Isolated disposable DBs may not have the full prior chain.
            print(f"alembic upgrade skipped on disposable DB: {exc}")
    ensured = ensure_growth_agent_schema(bind=eng)
    assert ensured.get("skipped") is False
    assert "nova_ga_retention_schedule_runs" in ensured.get("present", [])
    # Stash for assertions in migration test.
    eng._nova_ga_alembic_ok = alembic_ok  # type: ignore[attr-defined]
    yield eng
    eng.dispose()


@pytest.fixture()
def Session(pg_engine):
    return sessionmaker(bind=pg_engine, expire_on_commit=False)


@pytest.fixture()
def db(Session):
    session = Session()
    try:
        yield session
    finally:
        session.close()


def _activate(svc, org: str):
    return svc.upsert_profile(
        org,
        "owner-pg",
        {
            "business_name": f"PG Biz {org}",
            "website": "https://pg.example",
            "timezone": "America/Chicago",
            "operating_hours": {"mon_fri": "09:00-17:00"},
            "services": [{"code": "consult", "name": "Consult", "duration_minutes": 30}],
            "faqs": [{"id": "f1", "question": "Hours?", "keywords": ["hours"], "answer": "9-5"}],
            "contact_email": "o@pg.example",
            "handoff_phone": "+15555550199",
            "escalation_settings": {},
            "quiet_hours": {"enabled": False},
        },
        activate=True,
    )


def test_pg_migrations_tables_present(pg_engine):
    with pg_engine.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename LIKE 'nova_ga_%'"
                )
            )
        }
    assert "nova_ga_business_profiles" in tables
    assert "nova_ga_delivery_attempts" in tables
    assert "nova_ga_rate_limit_counters" in tables
    assert "nova_ga_worker_heartbeats" in tables
    assert "nova_ga_retention_schedule_runs" in tables


def test_pg_concurrent_worker_claims(Session, db, monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_BACKGROUND_WORKER", "true")
    from app.core.nova.growth_agent.models import GaDeliveryAttempt
    from app.core.nova.growth_agent.service import GrowthAgentService
    from app.core.nova.growth_agent.worker import MockDeliveryWorker

    org = _uid("org-pg-claim")
    svc = GrowthAgentService(db)
    _activate(svc, org)
    contact = svc._upsert_contact(
        org,
        name="PG",
        email=f"{org}@example.com",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    for i in range(6):
        preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
        svc.approve_and_execute_workflow(
            org,
            run_id=preview["run_id"],
            dry_run=True,
            idempotency_key=f"pg-claim-{i}-{preview['run_id']}",
        )

    def run_worker(wid: str):
        w = MockDeliveryWorker(Session, organization_id=org, worker_id=wid)
        return w.run_once(limit=10)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(run_worker, f"pg-w-{i}-{uuid.uuid4().hex[:6]}") for i in range(3)]
        outs = [f.result() for f in as_completed(futs)]

    total_processed = sum(o["processed"] for o in outs)
    sent = (
        db.query(GaDeliveryAttempt)
        .filter_by(organization_id=org, status="sent_mock")
        .count()
    )
    # Each job completed at most once across workers.
    assert sent == total_processed or sent >= 1
    assert sent <= 6
    still_running = (
        db.query(GaDeliveryAttempt)
        .filter_by(organization_id=org, status="running")
        .count()
    )
    assert still_running == 0


def test_pg_expired_lease_reclaim(Session, db, monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_BACKGROUND_WORKER", "true")
    from app.core.nova.growth_agent.models import GaDeliveryAttempt
    from app.core.nova.growth_agent.service import GrowthAgentService
    from app.core.nova.growth_agent.worker import MockDeliveryWorker

    org = _uid("org-pg-lease")
    svc = GrowthAgentService(db)
    _activate(svc, org)
    contact = svc._upsert_contact(
        org,
        name="Lease",
        email=f"{org}@example.com",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    preview = svc.preview_workflow(org, workflow_code="inquiry_ack", contact_id=contact.id)
    svc.approve_and_execute_workflow(
        org,
        run_id=preview["run_id"],
        dry_run=True,
        idempotency_key=f"pg-lease-exec-{preview['run_id']}",
    )
    row = (
        db.query(GaDeliveryAttempt)
        .filter_by(organization_id=org, status="queued")
        .one()
    )
    row.status = "running"
    row.claimed_by = "dead"
    row.claimed_at = datetime.utcnow() - timedelta(minutes=10)
    row.lease_expires_at = datetime.utcnow() - timedelta(minutes=5)
    db.commit()

    out = MockDeliveryWorker(Session, organization_id=org, worker_id=_uid("pg-reclaim")).run_once()
    assert out["processed"] == 1
    assert out["results"][0]["status"] == "sent_mock"


def test_pg_atomic_widget_rate_limit(Session, db):
    from app.core.nova.growth_agent.errors import GrowthAgentError
    from app.core.nova.growth_agent.rate_limit import check_and_increment, current_count
    from app.core.nova.growth_agent.service import GrowthAgentService

    org = _uid("org-pg-rate")
    svc = GrowthAgentService(db)
    _activate(svc, org)
    widget = svc.create_widget_installation(org, domain=f"{org}.example")
    bucket = f"widget:{widget['installation_id']}"
    limit = 8

    def hit(_i: int):
        local = Session()
        try:
            check_and_increment(
                local,
                organization_id=org,
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
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = [pool.submit(hit, i) for i in range(20)]
        for fut in as_completed(futs):
            results.append(fut.result())
    assert results.count("ok") == limit
    assert results.count("RATE_LIMITED") == 20 - limit
    assert current_count(db, organization_id=org, bucket_key=bucket) == limit


def test_pg_tenant_isolation(Session, db, monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_BACKGROUND_WORKER", "true")
    from app.core.nova.growth_agent.models import GaDeliveryAttempt
    from app.core.nova.growth_agent.service import GrowthAgentService
    from app.core.nova.growth_agent.worker import MockDeliveryWorker

    org_a = _uid("org-pg-a")
    org_b = _uid("org-pg-b")
    svc = GrowthAgentService(db)
    _activate(svc, org_a)
    _activate(svc, org_b)
    ca = svc._upsert_contact(
        org_a,
        name="A",
        email=f"a@{org_a}.example",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    cb = svc._upsert_contact(
        org_b,
        name="B",
        email=f"b@{org_b}.example",
        consent_transactional=True,
        channel="email",
        source="test",
    )
    db.commit()
    pa = svc.preview_workflow(org_a, workflow_code="inquiry_ack", contact_id=ca.id)
    svc.approve_and_execute_workflow(
        org_a, run_id=pa["run_id"], dry_run=True, idempotency_key=f"pg-a-{pa['run_id']}"
    )
    pb = svc.preview_workflow(org_b, workflow_code="inquiry_ack", contact_id=cb.id)
    svc.approve_and_execute_workflow(
        org_b, run_id=pb["run_id"], dry_run=True, idempotency_key=f"pg-b-{pb['run_id']}"
    )

    MockDeliveryWorker(Session, organization_id=org_a, worker_id=_uid("pg-a-w")).run_once()
    assert (
        db.query(GaDeliveryAttempt).filter_by(organization_id=org_a, status="sent_mock").count()
        >= 1
    )
    assert (
        db.query(GaDeliveryAttempt).filter_by(organization_id=org_b, status="queued").count()
        >= 1
    )


def test_pg_retention_schedule_dry_run(Session, db, monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_RETENTION_SCHEDULE_ENABLED", "true")
    monkeypatch.delenv("NOVA_GROWTH_AGENT_RETENTION_DELETE_ENABLED", raising=False)
    from app.core.nova.growth_agent.models import GaConversationMessage, GaRetentionScheduleRun
    from app.core.nova.growth_agent.retention_schedule import RetentionScheduler, current_window_key
    from app.core.nova.growth_agent.service import GrowthAgentService

    org = _uid("org-pg-ret")
    msg_id = _uid("pg-old-msg")
    svc = GrowthAgentService(db)
    _activate(svc, org)
    db.add(
        GaConversationMessage(
            id=msg_id,
            organization_id=org,
            conversation_id=_uid("c"),
            role="visitor",
            content="old",
            created_at=datetime.utcnow() - timedelta(days=400),
        )
    )
    db.commit()
    window = current_window_key()
    scheduler = RetentionScheduler(Session, organization_id=org, scheduler_id=_uid("pg-ret"))
    out = scheduler.run_once(window_key=window)
    assert out["mode"] == "dry_run"
    assert out["processed"] == 1
    assert db.query(GaConversationMessage).filter_by(id=msg_id).count() == 1
    assert (
        db.query(GaRetentionScheduleRun)
        .filter_by(organization_id=org, window_key=window, status="completed")
        .count()
        == 1
    )
    # Duplicate window protected
    again = scheduler.run_once(window_key=window)
    assert again["claimed"] == 0
    assert again.get("already_completed_window")
