"""Tests for distributed operational synchronization event fabric."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.modules.health_isf import operational_event_bus as event_bus_module
from app.modules.health_isf.models import HealthISFOrganization, HealthISFWorkflowAuditLog
from app.modules.health_isf.operational_event_bus import OperationalEventBus
from app.modules.health_isf.operational_event_models import OperationalEvent, OperationalEventType
from app.modules.health_isf.operational_replay_service import OperationalReplayService
from app.modules.health_isf.operational_sync_engine import OperationalSynchronizationEngine
from app.modules.health_isf.operational_timeline import OperationalTimelineEngine
from app.modules.health_isf.operational_workflow_orchestration import publish_phase16_operational_event


def _event(org_id: str, event_type: OperationalEventType, nonce: str | None = None, emitted_at: datetime | None = None) -> OperationalEvent:
    return OperationalEvent(
        organization_id=org_id,
        event_id=str(uuid4()),
        event_type=event_type,
        role_scope=["dispatcher", "driver"],
        payload={"sample": True},
        emitted_at=emitted_at or datetime.utcnow(), # type: ignore
        source_nonce=nonce,
    )


def test_event_bus_orders_sequences():
    bus = OperationalEventBus()
    org = "org-sync-order"

    accepted1, _, e1 = bus.publish(_event(org, OperationalEventType.INCIDENT, nonce="a"))
    accepted2, _, e2 = bus.publish(_event(org, OperationalEventType.DRIVER_STATE, nonce="b"))

    assert accepted1 is True and e1 is not None
    assert accepted2 is True and e2 is not None
    assert e1.sequence == 1
    assert e2.sequence == 2


def test_event_bus_rejects_stale_and_duplicates():
    bus = OperationalEventBus()
    org = "org-sync-stale"

    stale = _event(org, OperationalEventType.INCIDENT, nonce="stale", emitted_at=datetime.utcnow() - timedelta(minutes=10)) # type: ignore
    accepted_stale, reason_stale, _ = bus.publish(stale, stale_after_seconds=120)
    assert accepted_stale is False
    assert reason_stale == "stale_event_rejected"

    fresh = _event(org, OperationalEventType.INCIDENT, nonce="dup")
    accepted_1, reason_1, _ = bus.publish(fresh)
    assert accepted_1 is True
    assert reason_1 in {"published", "published_memory_only", "published_persisted"}

    accepted_2, reason_2, _ = bus.publish(_event(org, OperationalEventType.INCIDENT, nonce="dup"))
    assert accepted_2 is False
    assert reason_2 == "duplicate_event_rejected"


def test_sync_engine_publish_is_governed_and_tenant_scoped():
    org = "org-sync-governed"
    result = OperationalSynchronizationEngine.publish_event(
        organization_id=org,
        event_type=OperationalEventType.OPERATIONAL_ALERT,
        payload={"alert_count": 2},
        role_scope=["dispatcher", "provider"],
        source_nonce=f"alert:{org}:2",
    )

    assert result["accepted"] is True
    assert result["approval_governed"] is True
    assert result["tenant_scoped"] is True
    assert result["backend_authoritative"] is True


def _seed_organization(org_id: str) -> None:
    with SessionLocal() as db:
        existing = db.query(HealthISFOrganization).filter(HealthISFOrganization.id == org_id).first()
        if existing is not None:
            return
        db.add(
            HealthISFOrganization(
                id=org_id,
                name=f"Deferred Publish {org_id[-8:]}",
                code=f"DP-{org_id[-8:]}",
                is_active=True,
            )
        )
        db.commit()


def test_phase16_events_persist_only_after_outer_commit():
    org = f"org-phase16-commit-{uuid4()}"
    correlation_id = f"corr-{uuid4()}"
    _seed_organization(org)

    with SessionLocal() as db:
        queued = publish_phase16_operational_event(
            db=db,
            organization_id=org,
            event_name="ride_requested",
            payload={"sample": True},
            correlation_id=correlation_id,
            role_scope=["dispatcher"],
            source_nonce=f"nonce:{org}",
        )
        assert queued["status"] == "queued_after_commit"

        before_commit = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == org)
            .filter(HealthISFWorkflowAuditLog.event_type.like("operational.event_bus.%"))
            .count()
        )
        assert before_commit == 0
        db.commit()

    with SessionLocal() as db:
        persisted = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == org)
            .filter(HealthISFWorkflowAuditLog.event_type == "operational.event_bus.ride_requested")
            .count()
        )
        assert persisted == 1


def test_phase16_deferred_publish_does_not_create_duplicate_events():
    org = f"org-phase16-dup-{uuid4()}"
    source_nonce = f"nonce:{org}"
    _seed_organization(org)

    with SessionLocal() as db:
        publish_phase16_operational_event(
            db=db,
            organization_id=org,
            event_name="workflow_transition",
            payload={"step": 1},
            correlation_id=f"corr-a-{uuid4()}",
            role_scope=["dispatcher"],
            source_nonce=source_nonce,
        )
        publish_phase16_operational_event(
            db=db,
            organization_id=org,
            event_name="workflow_transition",
            payload={"step": 1},
            correlation_id=f"corr-b-{uuid4()}",
            role_scope=["dispatcher"],
            source_nonce=source_nonce,
        )
        db.commit()

    with SessionLocal() as db:
        persisted = (
            db.query(HealthISFWorkflowAuditLog)
            .filter(HealthISFWorkflowAuditLog.organization_id == org)
            .filter(HealthISFWorkflowAuditLog.event_type == "operational.event_bus.workflow_transition")
            .count()
        )
        assert persisted == 1


def test_replay_integrity_reports_ordering():
    org = "org-sync-replay"
    OperationalSynchronizationEngine.publish_event(
        organization_id=org,
        event_type=OperationalEventType.GEOSPATIAL_UPDATE,
        payload={"driver_positions": 1},
        role_scope=["dispatcher", "driver"],
        source_nonce=f"geo:{org}:1",
    )
    OperationalSynchronizationEngine.publish_event(
        organization_id=org,
        event_type=OperationalEventType.DISPATCH_RECOMMENDATION,
        payload={"recommendation_count": 3},
        role_scope=["dispatcher", "driver", "provider"],
        source_nonce=f"dispatch:{org}:3",
    )

    replay = OperationalReplayService.replay(organization_id=org, after_sequence=0, role="dispatcher")
    integrity = OperationalReplayService.replay_integrity(org)

    assert replay["tenant_scoped"] is True
    assert replay["approval_governed"] is True
    assert replay["backend_authoritative"] is True
    assert integrity["integrity_ok"] is True
    assert integrity["ordered"] is True
    assert integrity["no_duplicates"] is True


def test_persisted_replay_skips_malformed_rows_without_breaking_continuity(monkeypatch):
    class _FakeRow:
        def __init__(self, payload: str) -> None:
            self.payload = payload

    class _FakeSession:
        def __init__(self) -> None:
            self._rows = [
                _FakeRow(
                    json.dumps(
                        {
                            "sequence": 1,
                            "event_type": "workflow_transition",
                            "role_scope": "dispatcher",
                            "payload": "malformed-payload-fragment",
                            "emitted_at": datetime.utcnow().isoformat(), # type: ignore
                        }
                    )
                ),
                _FakeRow(
                    json.dumps(
                        {
                            "sequence": 2,
                            "event_type": "workflow_transition",
                            "role_scope": ["dispatcher"],
                            "payload": {"ok": True},
                            "emitted_at": datetime.utcnow().isoformat(), # type: ignore
                        }
                    )
                ),
            ]

        def query(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def all(self):
            return self._rows

        def close(self):
            return None

    monkeypatch.setattr(event_bus_module, "SessionLocal", lambda: _FakeSession())

    bus = OperationalEventBus()
    replay = bus.replay("org-sync-mixed", after_sequence=0, limit=10)

    assert len(replay) == 2
    assert replay[0].sequence == 1
    assert replay[0].payload == {"value": "malformed-payload-fragment"}
    assert replay[0].role_scope == ["dispatcher"]
    assert replay[1].sequence == 2
    assert replay[1].payload == {"ok": True}


def test_timeline_timestamp_parser_falls_back_for_malformed_values():
    parsed = OperationalTimelineEngine._parse_recorded_at("not-a-timestamp")
    assert parsed == datetime.min.replace(tzinfo=timezone.utc)
