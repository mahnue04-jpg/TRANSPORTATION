"""Owner notification outbox and human handoff queue (mock / transactional only)."""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ["NOVA_GROWTH_AGENT_ENABLED"] = "true"

from app.core.nova.growth_agent.errors import CrossTenantError, GrowthAgentError
from app.core.nova.growth_agent.handoff_queue import (
    acknowledge_handoff,
    create_handoff,
    list_handoffs,
    resolve_handoff,
)
from app.core.nova.growth_agent.models import GaOwnerNotification
from app.core.nova.growth_agent.owner_notifications import (
    enqueue_owner_notification,
    list_owner_notifications,
    process_owner_notifications,
)
from app.core.nova.growth_agent.owner_notifications import _claim_notifications
from app.core.nova.growth_agent.providers.base import DeliveryResult
from app.core.nova.growth_agent.providers.mock_email import MockEmailAdapter
from app.core.nova.growth_agent.schema_ensure import ensure_growth_agent_schema
from app.db.session import Base


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    ensure_growth_agent_schema(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_enqueue_owner_notification_idempotent(db):
    org = "org-notify-1"
    payload = {"subject": "Appointment booked", "contact_email": "lead@example.com"}
    first = enqueue_owner_notification(
        db,
        org_id=org,
        event_type="appointment.booked",
        idempotency_key="idem-1",
        payload_redacted=payload,
    )
    second = enqueue_owner_notification(
        db,
        org_id=org,
        event_type="appointment.booked",
        idempotency_key="idem-1",
        payload_redacted=payload,
    )
    db.commit()
    assert first["id"] == second["id"]
    assert second.get("idempotent") is True
    assert first["purpose"] == "transactional"
    assert first["status"] == "queued"
    assert first["provider"] == "mock_email"
    assert first["payload_redacted_json"]["contact_email"] == "[REDACTED]"
    assert list_owner_notifications(db, org) == list_owner_notifications(db, org, limit=10)


def test_marketing_purpose_rejected(db):
    with pytest.raises(GrowthAgentError) as exc:
        enqueue_owner_notification(
            db,
            org_id="org-mkt",
            event_type="promo",
            idempotency_key="mkt-1",
            payload_redacted={"purpose": "marketing", "subject": "Sale"},
        )
    assert exc.value.code == "MARKETING_NOT_ALLOWED"
    with pytest.raises(GrowthAgentError) as exc2:
        enqueue_owner_notification(
            db,
            org_id="org-mkt",
            event_type="promo",
            idempotency_key="mkt-2",
            payload_redacted={"subject": "Sale"},
            purpose="marketing",
        )
    assert exc2.value.code == "MARKETING_NOT_ALLOWED"


def test_process_owner_notification_provider_accepted(db):
    org = "org-ok"
    enqueue_owner_notification(
        db,
        org_id=org,
        event_type="appointment.reminder",
        idempotency_key="ok-1",
        payload_redacted={"subject": "Reminder", "to": "owner@test.example"},
    )
    db.commit()
    batch = process_owner_notifications(
        db,
        worker_id="notify-worker",
        limit=5,
        email_adapter=MockEmailAdapter(),
    )
    db.commit()
    assert batch["claimed"] == 1
    assert batch["results"][0]["status"] == "provider_accepted"
    assert batch["results"][0]["inbox_delivered"] is False
    assert batch["results"][0]["provider_message_id"]
    rows = list_owner_notifications(db, org)
    assert rows[0]["status"] == "provider_accepted"


class FailingEmailAdapter:
    name = "mock_email"
    live = False

    def send(self, *, channel: str, payload: dict) -> DeliveryResult:
        return DeliveryResult(
            status="failed",
            provider=self.name,
            error_code="SMTP_DOWN",
        )


def test_process_owner_notification_fail_then_retry(db):
    org = "org-fail"
    enqueue_owner_notification(
        db,
        org_id=org,
        event_type="appointment.cancelled",
        idempotency_key="fail-1",
        payload_redacted={"subject": "Cancelled"},
    )
    db.commit()
    batch = process_owner_notifications(
        db,
        worker_id="w-fail",
        limit=1,
        email_adapter=FailingEmailAdapter(),
    )
    db.commit()
    assert batch["results"][0]["status"] == "retrying"
    assert batch["results"][0]["error_code"] == "SMTP_DOWN"


def test_owner_notification_lease_reclaim(db):
    org = "org-lease"
    row = GaOwnerNotification(
        id=str(uuid4()),
        organization_id=org,
        channel="email",
        purpose="transactional",
        event_type="appointment.booked",
        idempotency_key="lease-1",
        status="running",
        provider="mock_email",
        claimed_by="dead-worker:abc",
        claimed_at=datetime.utcnow() - timedelta(minutes=5),
        lease_expires_at=datetime.utcnow() - timedelta(minutes=1),
        payload_redacted_json={"subject": "Hi"},
    )
    db.add(row)
    db.commit()
    claimed = _claim_notifications(db, worker_id="new-worker", limit=5)
    assert len(claimed) == 1
    assert claimed[0].claimed_by.startswith("new-worker:")


def test_handoff_lifecycle_and_pii_redaction(db):
    org = "org-handoff"
    created = create_handoff(
        db,
        org_id=org,
        reason="unknown_intent",
        summary="Caller asked about billing; email was caller@example.com",
        contact_id="contact-1",
        conversation_id="conv-1",
    )
    db.commit()
    assert created["status"] == "open"
    assert created["payload_redacted_json"]["summary"] == (
        "Caller asked about billing; email was [REDACTED_EMAIL]"
    )
    ack = acknowledge_handoff(db, org, created["id"], "user-a")
    db.commit()
    assert ack["status"] == "acknowledged"
    assert ack["acknowledged_by"] == "user-a"
    resolved = resolve_handoff(db, org, created["id"], "user-a")
    db.commit()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"]
    open_rows = list_handoffs(db, org, status="open")
    assert open_rows == []
    resolved_rows = list_handoffs(db, org, status="resolved")
    assert len(resolved_rows) == 1


def test_handoff_cross_tenant_denied(db):
    org_a = "org-a"
    org_b = "org-b"
    created = create_handoff(
        db,
        org_id=org_a,
        reason="escalation",
        summary="Need human",
    )
    db.commit()
    with pytest.raises(CrossTenantError):
        acknowledge_handoff(db, org_b, created["id"], "user-b")
    with pytest.raises(CrossTenantError):
        resolve_handoff(db, org_b, created["id"], "user-b")