"""Disposable PostgreSQL rehearsal for receptionist Alembic migration + runtime.

Skipped unless NOVA_GA_PG_TEST_URL (or DATABASE_URL pointing at postgres) is set.
Never targets shared/production databases — callers must pass a disposable URL.

Critical invariant: receptionist tables must appear via Alembic revision
``20261116_nova_ga_receptionist`` (or heads through that revision). ORM
``ensure_growth_agent_schema`` / ``create_all`` must not conceal migration omissions.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("TESTING", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_ENABLED", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_DEMO_MODE", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_VOICE_SIMULATOR", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_CALENDAR_SYNC_WORKER", "true")
os.environ.setdefault("NOVA_GROWTH_AGENT_OWNER_NOTIFY_WORKER", "true")
os.environ.setdefault("AMICOR_ENVIRONMENT", "test")
os.environ.setdefault("APP_ENV", "test")

RECEPTIONIST_TABLES = (
    "nova_ga_calendar_oauth_states",
    "nova_ga_calendar_connections",
    "nova_ga_calendar_sync_jobs",
    "nova_ga_owner_notifications",
    "nova_ga_handoff_requests",
    "nova_ga_voice_agent_mappings",
    "nova_ga_voice_webhook_events",
    "nova_ga_voice_sessions",
)

RECEPTIONIST_REVISION = "20261116_nova_ga_receptionist"
UTC = timezone.utc
WEBHOOK_URL = "https://example.test/voice/inbound"


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
    if not any(tok in dbname for tok in ("test", "dispos", "ci", "nova_ga")):
        raise RuntimeError(
            f"Database name must look disposable (test/dispos/ci/nova_ga): {dbname}"
        )


pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="Set NOVA_GA_PG_TEST_URL to a disposable Postgres DSN to run these tests",
)


def _table_names(engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _drop_receptionist_tables(engine) -> None:
    """Remove receptionist tables so Alembic must recreate them (disposable only)."""
    existing = _table_names(engine)
    with engine.begin() as conn:
        for name in reversed(RECEPTIONIST_TABLES):
            if name in existing:
                conn.execute(text(f'DROP TABLE IF EXISTS "{name}" CASCADE'))


def _current_alembic_revision(engine) -> str | None:
    if "alembic_version" not in inspect(engine).get_table_names():
        return None
    with engine.connect() as conn:
        row = conn.execute(text("SELECT version_num FROM alembic_version")).fetchone()
    return row[0] if row else None


def _apply_receptionist_alembic(engine, pg_url: str) -> dict[str, Any]:
    """Prefer targeted upgrade; fall back to heads on empty disposable DBs.

    Drops receptionist tables first so a prior ORM ``ensure`` in the same disposable
    DB cannot conceal a missing Alembic revision.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", pg_url)
    notes: list[str] = []

    _drop_receptionist_tables(engine)
    assert not set(RECEPTIONIST_TABLES).intersection(_table_names(engine)), (
        "Receptionist tables still present after disposable drop — cannot rehearse Alembic"
    )

    current = _current_alembic_revision(engine)
    # If already at/after receptionist, stamp parent so upgrade() re-applies DDL.
    if current == RECEPTIONIST_REVISION:
        command.stamp(cfg, "20261112_nova_ga_retention")
        notes.append(f"stamped parent from {current}")

    try:
        command.upgrade(cfg, RECEPTIONIST_REVISION)
        return {"mode": "upgrade_target", "revision": RECEPTIONIST_REVISION, "notes": notes}
    except Exception as exc:  # noqa: BLE001
        notes.append(f"upgrade {RECEPTIONIST_REVISION} failed: {exc}")

    # Isolated empty DBs may not tolerate the full prior Health/ISF chain cleanly;
    # still try heads before any ORM ensure for receptionist tables.
    try:
        command.upgrade(cfg, "heads")
        return {"mode": "upgrade_heads", "revision": "heads", "notes": notes}
    except Exception as exc:  # noqa: BLE001
        notes.append(f"upgrade heads failed: {exc}")

    # Disposable-only escape hatch: stamp parent revision then apply receptionist DDL.
    try:
        command.stamp(cfg, "20261112_nova_ga_retention")
        command.upgrade(cfg, RECEPTIONIST_REVISION)
        return {
            "mode": "stamp_parent_then_upgrade",
            "revision": RECEPTIONIST_REVISION,
            "notes": notes,
        }
    except Exception as exc:  # noqa: BLE001
        notes.append(f"stamp+upgrade failed: {exc}")
        raise RuntimeError(
            "Alembic could not create receptionist tables on disposable Postgres: "
            + "; ".join(notes)
        ) from exc


@pytest.fixture(scope="module")
def pg_engine():
    assert PG_URL
    _assert_disposable_url(PG_URL)
    eng = create_engine(PG_URL, pool_pre_ping=True)

    alembic_meta = _apply_receptionist_alembic(eng, PG_URL)
    after_alembic = _table_names(eng)

    missing = [name for name in RECEPTIONIST_TABLES if name not in after_alembic]
    assert not missing, (
        f"Receptionist tables missing after Alembic ({alembic_meta['mode']}): {missing}. "
        "Do not use ensure_growth_agent_schema to conceal migration omissions."
    )
    # Tables were dropped before upgrade; presence after Alembic proves migration DDL.
    created_by_alembic = sorted(RECEPTIONIST_TABLES)
    assert set(RECEPTIONIST_TABLES).issubset(after_alembic)

    # Last-resort ORM ensure ONLY for non-receptionist Growth Agent tables
    # (appointments, profiles, etc.) needed by behavioral exercises when the
    # disposable DB was stamped past prior GA revisions.
    from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema

    ensured = ensure_growth_agent_schema(bind=eng)
    after_ensure = _table_names(eng)
    # Receptionist tables must already have been present; ensure must not be
    # the sole creator of any of them on this run.
    ensure_created = set(ensured.get("created") or [])
    receptionist_created_by_ensure = ensure_created.intersection(RECEPTIONIST_TABLES)
    assert not receptionist_created_by_ensure, (
        "ensure_growth_agent_schema created receptionist tables — migration rehearsal "
        f"is invalid: {sorted(receptionist_created_by_ensure)}"
    )

    eng._nova_ga_receptionist_alembic = alembic_meta  # type: ignore[attr-defined]
    eng._nova_ga_receptionist_created_by_alembic = created_by_alembic  # type: ignore[attr-defined]
    eng._nova_ga_ensure_created_non_receptionist = sorted(  # type: ignore[attr-defined]
        ensure_created - set(RECEPTIONIST_TABLES)
    )
    eng._nova_ga_tables_after_ensure = after_ensure  # type: ignore[attr-defined]
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


@dataclass
class FakeResponse:
    status_code: int
    _json: dict[str, Any] | None = None
    text: str = ""

    def json(self) -> Any:
        return self._json


@dataclass
class FakeHttpClient:
    responses: list[FakeResponse] = field(default_factory=list)
    calls: list[tuple[str, str, str | None]] = field(default_factory=list)
    call_index: int = 0

    def request(self, method, url, *, headers=None, data=None, timeout=None):
        self.calls.append((method, url, data))
        if self.call_index >= len(self.responses):
            return FakeResponse(500, None)
        resp = self.responses[self.call_index]
        self.call_index += 1
        return resp


def _transport(client: FakeHttpClient):
    from app.core.nova.growth_agent.providers.google_calendar_transport import (
        GoogleCalendarTransport,
    )

    return GoogleCalendarTransport(
        http_client=client,
        get_access_token=lambda _org: "fake-token",
    )


def _calendar_connection(db, org: str):
    from app.core.nova.growth_agent.models import GaCalendarConnection

    conn = GaCalendarConnection(
        id=str(uuid.uuid4()),
        organization_id=org,
        owner_user_id="owner-pg-rec",
        provider="google",
        status="connected",
        calendar_id="primary@example.invalid",
        scopes_json=["https://www.googleapis.com/auth/calendar.events"],
        meta_json={},
    )
    db.add(conn)
    db.flush()
    return conn


def _appointment(db, org: str, appt_id: str):
    from app.core.nova.growth_agent.models import GaAppointment

    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC).replace(tzinfo=None)
    end = datetime(2026, 11, 20, 16, 30, tzinfo=UTC).replace(tzinfo=None)
    row = GaAppointment(
        id=appt_id,
        organization_id=org,
        contact_id="contact-pg-rec",
        service_id="svc-1",
        starts_at_utc=start,
        ends_at_utc=end,
        status="confirmed",
        idempotency_key=f"idem-{appt_id}",
    )
    db.add(row)
    db.flush()
    return row


class MockVoiceOps:
    def __init__(self, org_id: str) -> None:
        self.org_id = org_id
        self.calls: list[tuple[str, dict]] = []

    def faq_answer(self, *, organization_id: str, question: str) -> dict[str, Any]:
        self.calls.append(("faq_answer", {"question": question}))
        return {"grounded": True, "answer": "9-5"}

    def capture_lead(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("capture_lead", kwargs))
        return {"contact_id": "contact-1"}

    def check_availability(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("check_availability", kwargs))
        return {"slots": ["2026-11-17T15:00:00Z"]}

    def book(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("book", kwargs))
        return {"appointment_id": "appt-authorized-1", "status": "confirmed"}

    def reschedule(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("reschedule", kwargs))
        return {"appointment_id": kwargs["appointment_id"], "status": "rescheduled"}

    def cancel(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("cancel", kwargs))
        return {"appointment_id": kwargs["appointment_id"], "status": "cancelled"}

    def create_handoff(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("create_handoff", kwargs))
        return {"handoff_id": "handoff-1"}


def test_receptionist_alembic_tables_present(pg_engine):
    tables = _table_names(pg_engine)
    for name in RECEPTIONIST_TABLES:
        assert name in tables
    meta = pg_engine._nova_ga_receptionist_alembic  # type: ignore[attr-defined]
    assert meta["mode"] in {
        "upgrade_target",
        "upgrade_heads",
        "stamp_parent_then_upgrade",
    }
    # Prove inspect path (not ORM ensure) saw the tables after Alembic.
    with pg_engine.connect() as conn:
        pg_tables = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                    "AND tablename LIKE 'nova_ga_%'"
                )
            )
        }
    for name in RECEPTIONIST_TABLES:
        assert name in pg_tables


def test_pg_calendar_connection_and_sync_with_fake_transport(db):
    from app.core.nova.growth_agent.calendar_sync import enqueue_sync, process_sync_batch
    from app.core.nova.growth_agent.models import GaCalendarSyncJob
    from app.core.nova.growth_agent.providers.google_calendar_requests import event_id_for

    org = _uid("org-pg-cal")
    conn = _calendar_connection(db, org)
    appt_id = _uid("appt")
    _appointment(db, org, appt_id)
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    enqueued = enqueue_sync(
        db,
        org_id=org,
        appointment_id=appt_id,
        action="create",
        starts_at=start,
        ends_at=end,
        connection=conn,
    )
    db.commit()
    assert enqueued["status"] == "pending"

    eid = event_id_for(org, appt_id)
    client = FakeHttpClient(
        responses=[
            FakeResponse(
                201,
                {
                    "id": eid,
                    "etag": "etag-pg-1",
                    "start": {"dateTime": "2026-11-20T16:00:00Z"},
                    "end": {"dateTime": "2026-11-20T16:30:00Z"},
                },
            )
        ]
    )
    batch = process_sync_batch(
        db,
        worker_id=_uid("pg-sync-w"),
        limit=5,
        transport=_transport(client),
        organization_id=org,
    )
    db.commit()
    assert batch["claimed"] == 1
    assert batch["results"][0]["status"] == "confirmed"
    row = db.query(GaCalendarSyncJob).filter_by(organization_id=org).one()
    assert row.status == "confirmed"
    assert row.confirmed_at is not None
    assert len(client.calls) >= 1


def test_pg_owner_notification_enqueue_and_process(db):
    from app.core.nova.growth_agent.owner_notifications import (
        enqueue_owner_notification,
        list_owner_notifications,
        process_owner_notifications,
    )
    from app.core.nova.growth_agent.providers.mock_email import MockEmailAdapter

    org = _uid("org-pg-notify")
    enqueue_owner_notification(
        db,
        org_id=org,
        event_type="appointment.booked",
        idempotency_key=_uid("idem-notify"),
        payload_redacted={"subject": "Booked", "to": "owner@pg.example"},
    )
    db.commit()
    batch = process_owner_notifications(
        db,
        worker_id=_uid("pg-notify-w"),
        limit=5,
        email_adapter=MockEmailAdapter(),
    )
    db.commit()
    assert batch["claimed"] >= 1
    assert batch["results"][0]["status"] == "provider_accepted"
    rows = list_owner_notifications(db, org)
    assert rows and rows[0]["status"] == "provider_accepted"


def test_pg_handoff_create_and_ack(db):
    from app.core.nova.growth_agent.handoff_queue import (
        acknowledge_handoff,
        create_handoff,
        list_handoffs,
    )

    org = _uid("org-pg-handoff")
    created = create_handoff(
        db,
        org_id=org,
        reason="unknown_intent",
        summary="Caller asked for a human; phone +15555550123",
        contact_id="contact-pg",
        conversation_id="conv-pg",
    )
    db.commit()
    assert created["status"] == "open"
    ack = acknowledge_handoff(db, org, created["id"], "owner-pg")
    db.commit()
    assert ack["status"] == "acknowledged"
    assert ack["acknowledged_by"] == "owner-pg"
    assert list_handoffs(db, org, status="acknowledged")


def test_pg_voice_mapping_and_signed_simulator_webhook(db, monkeypatch):
    monkeypatch.setenv("NOVA_GROWTH_AGENT_VOICE_SIMULATOR", "true")
    from app.core.nova.growth_agent.models import GaVoiceAgentMapping, GaVoiceWebhookEvent
    from app.core.nova.growth_agent.voice.inbound import receive_inbound_webhook
    from app.core.nova.growth_agent.voice.simulator import craft_signed_simulator_webhook

    org = _uid("org-pg-voice")
    number = f"+1555{uuid.uuid4().hex[:7]}"
    db.add(
        GaVoiceAgentMapping(
            id=str(uuid.uuid4()),
            organization_id=org,
            provider="twilio",
            external_number=number,
            agent_label="receptionist",
            active=True,
            kill_switch=False,
            daily_call_limit=50,
            meta_json={},
        )
    )
    db.commit()

    crafted = craft_signed_simulator_webhook(
        url=WEBHOOK_URL,
        to_number=number,
        event_type="faq_answer",
        extra={"question": "hours?", "event_id": _uid("evt-sim")},
    )
    assert crafted["meta"]["simulated"] is True
    out = receive_inbound_webhook(
        db,
        url=WEBHOOK_URL,
        params=crafted["params"],
        signature_header=crafted["signature"],
        auth_token=crafted["auth_token"],
        growth_ops=MockVoiceOps(org),
        simulator_mode=True,
    )
    db.commit()
    assert out["status"] == "processed"
    assert out["organization_id"] == org
    assert (
        db.query(GaVoiceWebhookEvent).filter_by(organization_id=org).count() >= 1
    )


def test_pg_tenant_isolation_sync_and_notifications(db):
    from app.core.nova.growth_agent.calendar_sync import claim_sync_jobs, enqueue_sync
    from app.core.nova.growth_agent.models import GaCalendarSyncJob
    from app.core.nova.growth_agent.owner_notifications import (
        enqueue_owner_notification,
        list_owner_notifications,
    )

    org_a = _uid("org-pg-a")
    org_b = _uid("org-pg-b")
    conn_a = _calendar_connection(db, org_a)
    conn_b = _calendar_connection(db, org_b)
    appt_a = _uid("appt-a")
    appt_b = _uid("appt-b")
    _appointment(db, org_a, appt_a)
    _appointment(db, org_b, appt_b)
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    enqueue_sync(
        db,
        org_id=org_a,
        appointment_id=appt_a,
        action="create",
        starts_at=start,
        ends_at=end,
        connection=conn_a,
    )
    enqueue_sync(
        db,
        org_id=org_b,
        appointment_id=appt_b,
        action="create",
        starts_at=start,
        ends_at=end,
        connection=conn_b,
    )
    enqueue_owner_notification(
        db,
        org_id=org_a,
        event_type="appointment.booked",
        idempotency_key=_uid("idem-a"),
        payload_redacted={"subject": "A"},
    )
    enqueue_owner_notification(
        db,
        org_id=org_b,
        event_type="appointment.booked",
        idempotency_key=_uid("idem-b"),
        payload_redacted={"subject": "B"},
    )
    db.commit()

    claimed_a = claim_sync_jobs(
        db, worker_id=_uid("w-a"), limit=10, organization_id=org_a
    )
    assert claimed_a
    assert all(j.organization_id == org_a for j in claimed_a)
    assert (
        db.query(GaCalendarSyncJob)
        .filter_by(organization_id=org_b, status="pending")
        .count()
        >= 1
    )

    notes_a = list_owner_notifications(db, org_a)
    notes_b = list_owner_notifications(db, org_b)
    assert notes_a and all(n["organization_id"] == org_a for n in notes_a)
    assert notes_b and all(n["organization_id"] == org_b for n in notes_b)
    assert {n["id"] for n in notes_a}.isdisjoint({n["id"] for n in notes_b})


def test_pg_restart_recovery_reclaim_expired_sync_lease(db):
    from app.core.nova.growth_agent.calendar_sync import claim_sync_jobs
    from app.core.nova.growth_agent.models import GaCalendarSyncJob
    from app.core.nova.growth_agent.providers.google_calendar_requests import event_id_for

    org = _uid("org-pg-lease")
    conn = _calendar_connection(db, org)
    appt_id = _uid("appt-lease")
    job = GaCalendarSyncJob(
        id=str(uuid.uuid4()),
        organization_id=org,
        appointment_id=appt_id,
        connection_id=conn.id,
        calendar_id=conn.calendar_id or "primary@example.invalid",
        event_id=event_id_for(org, appt_id),
        action="cancel",
        operation_version=1,
        status="running",
        attempt_number=1,
        max_attempts=8,
        claimed_by="dead-worker:abc",
        claimed_at=datetime.utcnow() - timedelta(minutes=10),
        lease_expires_at=datetime.utcnow() - timedelta(minutes=5),
        payload_json={},
        result_json={},
    )
    db.add(job)
    db.commit()

    new_worker = _uid("pg-reclaim")
    claimed = claim_sync_jobs(db, worker_id=new_worker, limit=5, organization_id=org)
    db.commit()
    assert len(claimed) == 1
    assert claimed[0].claimed_by.startswith(f"{new_worker}:")
    refreshed = db.query(GaCalendarSyncJob).filter_by(id=job.id).one()
    assert refreshed.status == "running"
    assert refreshed.claimed_by.startswith(f"{new_worker}:")
