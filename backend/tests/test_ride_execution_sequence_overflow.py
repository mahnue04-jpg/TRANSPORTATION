"""Regression: monotonic-derived sequence numbers must fit PostgreSQL INTEGER."""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.auth import ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.modules.health_isf import service as hs
from app.modules.health_isf.models import HealthISFDriver, HealthISFRide, HealthISFRideExecutionAction, RideStatus
from app.modules.health_isf.ride_execution_engine import (
    _PG_INT_MAX,
    _normalize_execution_sequence_number,
    RideLifecycleManager,
)


@pytest.fixture(scope="module", autouse=True)
def _seed() -> None:
    ensure_auth_schema()
    seed_default_users()


def test_normalize_execution_sequence_number_clamps_monotonic_overflow() -> None:
    ride = SimpleNamespace(id="ride-1", organization_id="org-1")
    db = SimpleNamespace(query=lambda *_args, **_kwargs: SimpleNamespace(
        filter=lambda *_a, **_k: SimpleNamespace(
            order_by=lambda *_a, **_k: SimpleNamespace(first=lambda: None)
        )
    ))

    overflow = _PG_INT_MAX + 1
    normalized = _normalize_execution_sequence_number(db, ride, overflow, None)
    assert normalized is not None
    assert normalized <= _PG_INT_MAX


def test_normalize_execution_sequence_number_uses_last_seq_when_monotonic_overflow() -> None:
    ride = SimpleNamespace(id="ride-1", organization_id="org-1")
    last = SimpleNamespace(sequence_number=42)
    db = SimpleNamespace(query=lambda *_args, **_kwargs: SimpleNamespace(
        filter=lambda *_a, **_k: SimpleNamespace(
            order_by=lambda *_a, **_k: SimpleNamespace(first=lambda: last)
        )
    ))

    normalized = _normalize_execution_sequence_number(
        db,
        ride,
        None,
        (_PG_INT_MAX / 1000) + 10,
    )
    assert normalized == 43


def test_transition_ride_persists_when_monotonic_sequence_overflows(monkeypatch: pytest.MonkeyPatch) -> None:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user and user.organization_id
        org_id = str(user.organization_id)
        provider = (
            db.query(hs.HealthISFProvider)
            .filter(hs.HealthISFProvider.organization_id == org_id)
            .first()
        )
        assert provider is not None
        driver = (
            db.query(HealthISFDriver)
            .filter(
                HealthISFDriver.organization_id == org_id,
                HealthISFDriver.name.ilike("James Smith"),
            )
            .first()
        )
        assert driver is not None
        ride_id = str(uuid4())
        ride = HealthISFRide(
            id=ride_id,
            organization_id=org_id,
            provider_id=str(provider.id),
            passenger_name="Overflow Probe",
            passenger_phone="646-555-0001",
            pickup_address="1 Test Ave",
            dropoff_address="2 Clinic Rd",
            service_type="medical_transport",
            status=RideStatus.ACCEPTED,
            lifecycle_state=RideStatus.ASSIGNED.value,
            driver_id=str(driver.id),
        )
        db.add(ride)
        db.commit()

    monkeypatch.setattr(time, "monotonic", lambda: (_PG_INT_MAX / 1000) + 100)

    with SessionLocal() as db:
        ride = db.query(HealthISFRide).filter(HealthISFRide.id == ride_id).first()
        assert ride is not None
        accepted = RideLifecycleManager.transition_ride(
            db,
            ride,
            target_state=RideStatus.DRIVER_EN_ROUTE.value,
            action_type="driver_en_route_pickup",
            monotonic_ts=time.monotonic(),
            event_id=str(uuid4()),
            source="test_overflow",
        )
        assert accepted is True
        db.commit()
        action = (
            db.query(HealthISFRideExecutionAction)
            .filter(HealthISFRideExecutionAction.ride_id == ride_id)
            .order_by(HealthISFRideExecutionAction.created_at.desc())
            .first()
        )
        assert action is not None
        assert action.sequence_number is not None
        assert action.sequence_number <= _PG_INT_MAX
