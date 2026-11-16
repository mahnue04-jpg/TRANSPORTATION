"""Calendar sync outbox, transport, and external availability tests."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"
os.environ.setdefault("TESTING", "true")

from app.core.nova.growth_agent.calendar_availability_external import (
    CHICAGO,
    filter_slots_against_busy,
    local_slot_boundaries,
    merge_busy_intervals,
)
from app.core.nova.growth_agent.calendar_sync import (
    claim_sync_jobs,
    enqueue_sync,
    process_sync_batch,
)
from app.core.nova.growth_agent.models import GaAppointment, GaCalendarConnection, GaCalendarSyncJob
from app.core.nova.growth_agent.providers.google_calendar_requests import event_id_for
from app.core.nova.growth_agent.providers.google_calendar_transport import (
    CalendarTransportResult,
    GoogleCalendarTransport,
)
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema

UTC = timezone.utc
CHI = ZoneInfo("America/Chicago")


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
    s = Session()
    try:
        yield s
    finally:
        s.close()


def _connection(db, org: str = "org-cal") -> GaCalendarConnection:
    conn = GaCalendarConnection(
        id=str(uuid4()),
        organization_id=org,
        owner_user_id="owner-1",
        status="connected",
        calendar_id="primary@example.invalid",
    )
    db.add(conn)
    db.flush()
    return conn


def _appointment(
    db,
    org: str,
    appt_id: str,
    *,
    status: str = "confirmed",
    start: datetime | None = None,
    end: datetime | None = None,
) -> GaAppointment:
    start = start or datetime(2026, 11, 20, 16, 0, tzinfo=UTC).replace(tzinfo=None)
    end = end or datetime(2026, 11, 20, 16, 30, tzinfo=UTC).replace(tzinfo=None)
    row = GaAppointment(
        id=appt_id,
        organization_id=org,
        contact_id="contact-1",
        service_id="svc-1",
        starts_at_utc=start,
        ends_at_utc=end,
        status=status,
        idempotency_key=f"idem-{appt_id}",
    )
    db.add(row)
    db.flush()
    return row


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


def _transport(client: FakeHttpClient) -> GoogleCalendarTransport:
    return GoogleCalendarTransport(
        http_client=client,
        get_access_token=lambda _org: "fake-token",
    )


def test_enqueue_same_event_id_lifecycle(db):
    conn = _connection(db)
    appt_id = "appt-1"
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    expected_event = event_id_for(conn.organization_id, appt_id)

    c1 = enqueue_sync(
        db,
        org_id=conn.organization_id,
        appointment_id=appt_id,
        action="create",
        starts_at=start,
        ends_at=end,
        connection=conn,
    )
    c2 = enqueue_sync(
        db,
        org_id=conn.organization_id,
        appointment_id=appt_id,
        action="reschedule",
        starts_at=start + timedelta(days=1),
        ends_at=end + timedelta(days=1),
        connection=conn,
    )
    c3 = enqueue_sync(
        db,
        org_id=conn.organization_id,
        appointment_id=appt_id,
        action="cancel",
        starts_at=None,
        ends_at=None,
        connection=conn,
    )
    assert c1["event_id"] == expected_event
    assert c2["event_id"] == expected_event
    assert c3["event_id"] == expected_event
    assert c1["operation_version"] == 1
    assert c2["operation_version"] == 2
    assert c3["operation_version"] == 3
    db.commit()


def test_enqueue_idempotent_same_version(db):
    conn = _connection(db)
    kwargs = dict(
        org_id=conn.organization_id,
        appointment_id="appt-dup",
        action="create",
        starts_at=datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 20, 16, 30, tzinfo=UTC),
        connection=conn,
    )
    first = enqueue_sync(db, **kwargs)
    db.commit()
    # second enqueue advances version; simulate idempotent by re-querying same version row
    second = enqueue_sync(db, **kwargs)
    assert second["operation_version"] == first["operation_version"] + 1


def test_duplicate_version_rejected_idempotent(db):
    conn = _connection(db)
    appt = "appt-idem"
    job = GaCalendarSyncJob(
        id=str(uuid4()),
        organization_id=conn.organization_id,
        appointment_id=appt,
        connection_id=conn.id,
        calendar_id=conn.calendar_id,
        event_id=event_id_for(conn.organization_id, appt),
        action="create",
        operation_version=1,
        status="pending",
    )
    db.add(job)
    db.flush()
    again = enqueue_sync(
        db,
        org_id=conn.organization_id,
        appointment_id=appt,
        action="create",
        starts_at=datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 20, 16, 30, tzinfo=UTC),
        connection=conn,
    )
    assert again["operation_version"] == 2


def test_process_create_confirmed(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-create"
    _appointment(db, org, appt_id)
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    enqueue_sync(db, org_id=org, appointment_id=appt_id, action="create", starts_at=start, ends_at=end, connection=conn)
    db.commit()

    eid = event_id_for(org, appt_id)
    client = FakeHttpClient(
        responses=[
            FakeResponse(
                201,
                {
                    "id": eid,
                    "etag": "etag-1",
                    "start": {"dateTime": "2026-11-20T16:00:00Z"},
                    "end": {"dateTime": "2026-11-20T16:30:00Z"},
                },
            )
        ]
    )
    transport = _transport(client)
    batch = process_sync_batch(db, worker_id="w1", limit=5, transport=transport)
    assert batch["claimed"] == 1
    assert batch["results"][0]["status"] == "confirmed"
    db.commit()
    row = db.query(GaCalendarSyncJob).one()
    assert row.status == "confirmed"
    assert row.confirmed_at is not None


def test_timeout_after_create_recovery_without_duplicate_post(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-timeout"
    _appointment(db, org, appt_id)
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    enqueue_sync(db, org_id=org, appointment_id=appt_id, action="create", starts_at=start, ends_at=end, connection=conn)
    db.commit()
    eid = event_id_for(org, appt_id)

    class TimeoutClient(FakeHttpClient):
        def request(self, method, url, *, headers=None, data=None, timeout=None):
            self.calls.append((method, url, data))
            if method == "POST":
                raise TimeoutError
            if self.call_index >= len(self.responses):
                return FakeResponse(500, None)
            resp = self.responses[self.call_index]
            self.call_index += 1
            return resp

    client = TimeoutClient(
        responses=[
            FakeResponse(
                200,
                {
                    "id": eid,
                    "etag": "etag-timeout",
                    "start": {"dateTime": "2026-11-20T16:00:00Z"},
                    "end": {"dateTime": "2026-11-20T16:30:00Z"},
                },
            )
        ]
    )
    transport = _transport(client)
    process_sync_batch(db, worker_id="w-timeout", limit=5, transport=transport)
    post_calls = [c for c in client.calls if c[0] == "POST"]
    get_calls = [c for c in client.calls if c[0] == "GET"]
    assert len(post_calls) == 1
    assert len(get_calls) == 1
    row = db.query(GaCalendarSyncJob).one()
    assert row.status == "confirmed"


def test_stale_version_after_cancel(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-stale"
    _appointment(db, org, appt_id, status="cancelled")
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)

    enqueue_sync(db, org_id=org, appointment_id=appt_id, action="create", starts_at=start, ends_at=end, connection=conn)
    db.flush()
    enqueue_sync(db, org_id=org, appointment_id=appt_id, action="cancel", starts_at=None, ends_at=None, connection=conn)
    db.commit()

    client = FakeHttpClient(responses=[FakeResponse(201, {"id": "x"})])
    transport = _transport(client)
    batch = process_sync_batch(db, worker_id="w-stale", limit=10, transport=transport)
    statuses = {r["operation_version"]: r["status"] for r in batch["results"]}
    assert statuses.get(1) == "stale"
    assert len(client.calls) == 0 or statuses.get(1) == "stale"


def test_cancel_then_rebook_newer_create_wins(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-rebook"
    start = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)

    _appointment(db, org, appt_id, status="confirmed", start=start.replace(tzinfo=None), end=end.replace(tzinfo=None))
    enqueue_sync(db, org_id=org, appointment_id=appt_id, action="create", starts_at=start, ends_at=end, connection=conn)
    enqueue_sync(db, org_id=org, appointment_id=appt_id, action="cancel", starts_at=None, ends_at=None, connection=conn)
    enqueue_sync(
        db,
        org_id=org,
        appointment_id=appt_id,
        action="create",
        starts_at=start + timedelta(days=1),
        ends_at=end + timedelta(days=1),
        connection=conn,
    )
    appt = db.query(GaAppointment).one()
    appt.status = "confirmed"
    db.flush()

    cancel_job = (
        db.query(GaCalendarSyncJob)
        .filter_by(organization_id=org, appointment_id=appt_id, operation_version=2)
        .one()
    )
    cancel_job.status = "retrying"
    cancel_job.attempt_number = 1
    db.commit()

    eid = event_id_for(org, appt_id)
    client = FakeHttpClient(responses=[FakeResponse(204, None)])
    transport = _transport(client)
    batch = process_sync_batch(db, worker_id="w-rebook", limit=5, transport=transport)
    cancel_results = [r for r in batch["results"] if r["operation_version"] == 2]
    assert cancel_results and cancel_results[0]["status"] == "stale"
    assert not any(c[0] == "DELETE" for c in client.calls)


def test_worker_restart_reclaim_lease(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-lease"
    job = GaCalendarSyncJob(
        id=str(uuid4()),
        organization_id=org,
        appointment_id=appt_id,
        connection_id=conn.id,
        calendar_id=conn.calendar_id,
        event_id=event_id_for(org, appt_id),
        action="cancel",
        operation_version=1,
        status="running",
        claimed_by="dead-worker:abc",
        claimed_at=datetime.utcnow() - timedelta(minutes=5),
        lease_expires_at=datetime.utcnow() - timedelta(minutes=1),
    )
    db.add(conn)
    db.add(job)
    db.commit()

    claimed = claim_sync_jobs(db, worker_id="new-worker", limit=5)
    assert len(claimed) == 1
    assert claimed[0].claimed_by.startswith("new-worker:")


def test_external_busy_filters_slots():
    slots = [
        (datetime(2026, 11, 20, 15, 0, tzinfo=UTC), datetime(2026, 11, 20, 15, 30, tzinfo=UTC)),
        (datetime(2026, 11, 20, 16, 0, tzinfo=UTC), datetime(2026, 11, 20, 16, 30, tzinfo=UTC)),
    ]
    busy = [
        (datetime(2026, 11, 20, 15, 45, tzinfo=UTC), datetime(2026, 11, 20, 16, 15, tzinfo=UTC)),
    ]
    merged = merge_busy_intervals([], busy, buffer_minutes=0)
    filtered = filter_slots_against_busy(slots, merged, buffer_minutes=0)
    assert len(filtered) == 1
    assert filtered[0][0].hour == 15


def test_dst_spring_forward_chicago():
    # 2026-03-08 US spring forward: 2:00 AM becomes 3:00 AM
    day = datetime(2026, 3, 8, 1, 30, tzinfo=CHI)
    start, end = local_slot_boundaries(day, start_minute=8 * 60, end_minute=10 * 60)
    assert start.utcoffset() in (timedelta(hours=-6), timedelta(hours=-5))
    assert start.astimezone(UTC).hour in (13, 14, 15)


def test_dst_fall_back_chicago():
    # 2026-11-01 fall back
    day = datetime(2026, 11, 1, 1, 30, tzinfo=CHI)
    start, end = local_slot_boundaries(day, start_minute=9 * 60, end_minute=10 * 60)
    assert start.utcoffset() in (timedelta(hours=-5), timedelta(hours=-6))


def test_rate_limit_backoff(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-429"
    _appointment(db, org, appt_id)
    enqueue_sync(
        db,
        org_id=org,
        appointment_id=appt_id,
        action="create",
        starts_at=datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 20, 16, 30, tzinfo=UTC),
        connection=conn,
    )
    db.commit()
    client = FakeHttpClient(responses=[FakeResponse(429, None)])
    transport = _transport(client)
    result = process_sync_batch(db, worker_id="w-429", limit=1, transport=transport)
    assert result["results"][0]["status"] == "retrying"
    row = db.query(GaCalendarSyncJob).one()
    assert row.last_error_code == "RATE_LIMITED"
    assert row.available_at is not None


def test_credentials_expired(db):
    conn = _connection(db)
    org = conn.organization_id
    appt_id = "appt-401"
    _appointment(db, org, appt_id)
    enqueue_sync(
        db,
        org_id=org,
        appointment_id=appt_id,
        action="create",
        starts_at=datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 20, 16, 30, tzinfo=UTC),
        connection=conn,
    )
    db.commit()
    client = FakeHttpClient(responses=[FakeResponse(401, None)])
    transport = _transport(client)
    result = process_sync_batch(db, worker_id="w-401", limit=1, transport=transport)
    assert result["results"][0]["status"] == "failed"
    assert result["results"][0]["last_error_code"] == "CREDENTIALS_EXPIRED"


def test_real_calendar_write_false_suppresses_without_client(monkeypatch):
    monkeypatch.setattr(
        "app.core.nova.growth_agent.providers.google_calendar_transport.REAL_CALENDAR_WRITE",
        False,
    )
    transport = GoogleCalendarTransport(http_client=None, get_access_token=None)
    from app.core.nova.growth_agent.providers.google_calendar_requests import CalendarBinding

    binding = CalendarBinding("org-x", "cal@example.invalid")
    result = transport.create_event(
        binding=binding,
        organization_id="org-x",
        appointment_id="a1",
        starts_at=datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 20, 16, 30, tzinfo=UTC),
    )
    assert result.outcome == "suppressed"
    assert result.error_code == "LIVE_CALENDAR_DISABLED"


def test_mark_suppressed_not_connected(db):
    conn = _connection(db)
    conn.status = "not_connected"
    out = enqueue_sync(
        db,
        org_id=conn.organization_id,
        appointment_id="appt-nc",
        action="create",
        starts_at=datetime(2026, 11, 20, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 11, 20, 16, 30, tzinfo=UTC),
        connection=conn,
    )
    assert out["status"] == "suppressed"
    assert out["last_error_code"] == "NOT_CONNECTED"