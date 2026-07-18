"""Regression tests for executive proof harness stabilization."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf import service as hs
from app.modules.health_isf.financial_engine import TripFinancialEngine
from app.modules.health_isf.models import HealthISFDriver, HealthISFRide, RideStatus
from scripts.executive_proof_harness import (
    AuthSession,
    BASE,
    TRANSIENT_NAV_ERRORS,
    api_get_with_retry,
    db_financial_counts,
    ensure_fresh_token,
    verify_ride_financial_authoritative,
    wait_backend_healthy,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _org_id(email: str = "dispatcher@amicor.local") -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user and user.organization_id
        return str(user.organization_id)


def _complete_ride_financially(client: TestClient, ride_id: str, driver_id: str) -> None:
    with SessionLocal() as db:
        ride = hs.get_ride_by_id(db, ride_id)
        assert ride is not None
        ride.lifecycle_state = RideStatus.COMPLETED.value
        ride.status = RideStatus.COMPLETED.value
        ride.driver_id = driver_id
        db.commit()
        TripFinancialEngine.process_trip_completion(db, ride=ride, actor_user_id=None)
        db.commit()


def test_token_refresh_financial_retry_on_401() -> None:
    session = AuthSession()
    session.token = "stale-token"
    path = "/api/health-isf/drivers/x?organization_id=y"
    responses = iter(
        [
            MagicMock(status_code=401, **{"json.return_value": {"detail": "Token expired"}}),
            MagicMock(status_code=401, **{"json.return_value": {"detail": "Token expired"}}),
            MagicMock(status_code=200, **{"json.return_value": {"availability_state": "available"}}),
        ]
    )

    def fake_get(url, headers=None, timeout=30):
        return next(responses)

    with patch("scripts.executive_proof_harness.requests.get", side_effect=fake_get):
        with patch.object(AuthSession, "refresh", return_value="fresh-token") as refresh:
            result = api_get_with_retry(session, path)
            assert refresh.called
            assert result["status"] == 200
            assert len(result["auth_attempts"]) == 2


def test_ensure_fresh_token_probes_before_use() -> None:
    session = AuthSession()
    session.token = "valid"
    with patch("scripts.executive_proof_harness.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        token = ensure_fresh_token(session)
        assert token == "valid"
        mock_get.assert_called_once()


def test_db_financial_counts_exactly_one_per_completed_ride(client: TestClient) -> None:
    org_id = _org_id()
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike("Test Driver Four"))
            .first()
        )
        assert driver is not None
        driver_id = str(driver.id)
    suffix = uuid4()[:8]
    dispatcher = client.post("/api/auth/login", json={"email": "dispatcher@amicor.local", "password": SEED_PASSWORD})
    headers = {"Authorization": f"Bearer {dispatcher.json()['access_token']}"}
    rider = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    rider_headers = {"Authorization": f"Bearer {rider.json()['access_token']}"}
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Harness Fin {suffix}",
            "rider_phone": "646-555-1212",
            "pickup_address": "1 Harness Ave",
            "dropoff_address": "2 Harness Rd",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create.status_code == 201, create.text
    ride_id = create.json()["ride_id"]
    _complete_ride_financially(client, ride_id, driver_id)
    counts = db_financial_counts(ride_id)
    assert counts["handoffs"] == 1
    assert counts["payments"] == 1
    assert counts["payouts"] == 1


def test_verify_financial_authoritative_passes_for_single_set(client: TestClient) -> None:
    org_id = _org_id()
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike("Test Driver Four"))
            .first()
        )
        assert driver is not None
        driver_id = str(driver.id)
    suffix = uuid4()[:8]
    rider = client.post("/api/auth/login", json={"email": "rider@amicor.local", "password": SEED_PASSWORD})
    rider_headers = {"Authorization": f"Bearer {rider.json()['access_token']}"}
    create = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Harness Auth {suffix}",
            "rider_phone": "646-555-3434",
            "pickup_address": "3 Harness Ave",
            "dropoff_address": "4 Harness Rd",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    ride_id = create.json()["ride_id"]
    _complete_ride_financially(client, ride_id, driver_id)
    session = AuthSession()
    session.login()
    handoff_body = {
        "completed": True,
        "driver_pay_usd": 12.96,
        "platform_revenue_usd": 1.28,
    }
    with patch(
        "scripts.executive_proof_harness.api_get_with_retry",
        side_effect=lambda sess, path: (
            {"status": 200, "body": handoff_body}
            if "completion-handoff" in path
            else {"status": 200, "body": {}}
        ),
    ):
        proof = verify_ride_financial_authoritative(ride_id, session, require_delta=False)
    assert proof["ok"] is True
    assert proof["counts"]["handoffs"] == 1
    assert proof["counts"]["payments"] == 1
    assert proof["counts"]["payouts"] == 1


def test_backend_health_gate_requires_consecutive_ok() -> None:
    responses = iter(
        [
            MagicMock(status_code=503),
            MagicMock(status_code=200),
            MagicMock(status_code=200),
            MagicMock(status_code=200),
        ]
    )

    with patch("scripts.executive_proof_harness.requests.get", side_effect=lambda url, timeout=5: next(responses)):
        with patch("scripts.executive_proof_harness.time.sleep", return_value=None):
            result = wait_backend_healthy(consecutive=3, timeout_s=30)
    assert result["ok"] is True


def test_transient_navigation_errors_classified() -> None:
    msg = "Page.goto: net::ERR_NETWORK_IO_SUSPENDED"
    assert any(marker in msg for marker in TRANSIENT_NAV_ERRORS)


def test_completed_executive_ride_locator_reads_db(client: TestClient) -> None:
    from pathlib import Path

    from scripts.executive_proof_harness import locate_completed_ride_1

    org_id = _org_id()
    with SessionLocal() as db:
        driver = (
            db.query(HealthISFDriver)
            .filter(HealthISFDriver.organization_id == org_id, HealthISFDriver.name.ilike("Test Driver Four"))
            .first()
        )
        assert driver is not None
        driver_id = str(driver.id)
        from datetime import datetime, timezone

        ride = HealthISFRide(
            id=uuid4(),
            organization_id=org_id,
            driver_id=driver_id,
            passenger_name="Executive Revenue R1 harness-test",
            passenger_phone="6465550000",
            pickup_address="pickup",
            dropoff_address="dropoff",
            service_type="medical_transport",
            lifecycle_state=RideStatus.COMPLETED.value,
            status=RideStatus.COMPLETED.value,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(ride)
        db.commit()
        ride_id = str(ride.id)
    _complete_ride_financially(client, ride_id, driver_id)
    prev = os.environ.get("EXECUTIVE_RIDE_1_ID")
    os.environ["EXECUTIVE_RIDE_1_ID"] = ride_id
    try:
        found = locate_completed_ride_1(Path(__file__).resolve().parents[2])
        assert found is not None
        assert found["ride_id"] == ride_id
    finally:
        if prev is None:
            os.environ.pop("EXECUTIVE_RIDE_1_ID", None)
        else:
            os.environ["EXECUTIVE_RIDE_1_ID"] = prev


@pytest.mark.integration
def test_live_backend_health_endpoint() -> None:
    try:
        r = requests.get(f"{BASE}/api/health", timeout=5)
    except Exception:
        pytest.skip("backend not running")
    assert r.status_code == 200
