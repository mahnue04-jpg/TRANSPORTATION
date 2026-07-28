"""Driver Mobile read path must stay read-only and driver-scoped."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.main import app
from app.modules.health_isf import service as hs


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str = "dispatcher@amicor.local") -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _driver_session(client: TestClient, phone: str = "917-555-1004") -> tuple[str, dict[str, str]]:
    login = client.post("/api/health-isf/drivers/mobile-login", json={"phone": phone})
    assert login.status_code == 200, login.text
    body = login.json()
    driver_id = str(body["driver_id"])
    headers = {"X-Driver-Session-Token": str(body["session_token"])}
    return driver_id, headers


@pytest.mark.parametrize(
    "path_suffix",
    [
        "active-ride",
        "active-offer",
        "live-workspace",
        "assigned-rides?limit=15",
    ],
)
def test_driver_read_endpoints_skip_org_maintenance(client: TestClient, path_suffix: str) -> None:
    driver_id, headers = _driver_session(client)
    maintenance_targets = [
        "app.modules.health_isf.service._prepare_driver_mobile_workspace_read",
        "app.modules.health_isf.service.expire_stale_dispatch_offers",
        "app.modules.health_isf.service.promote_pending_immediate_customer_requests",
        "app.modules.health_isf.service._sweep_stale_assignment_rows_for_organization",
        "app.modules.health_isf.service._offer_newest_queue_ride_to_driver",
        "app.modules.health_isf.service.get_driver_active_offer",
        "app.modules.health_isf.service.get_driver_live_workspace_data",
        "app.modules.health_isf.service.get_driver_active_ride_data",
        "app.modules.health_isf.service.list_driver_assigned_rides",
    ]
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = {target: stack.enter_context(patch(target)) for target in maintenance_targets}
        response = client.get(
            f"/api/health-isf/drivers/{driver_id}/{path_suffix}",
            headers=headers,
        )
    assert response.status_code == 200, response.text
    mocks["app.modules.health_isf.service._prepare_driver_mobile_workspace_read"].assert_not_called()
    mocks["app.modules.health_isf.service.expire_stale_dispatch_offers"].assert_not_called()
    mocks["app.modules.health_isf.service.promote_pending_immediate_customer_requests"].assert_not_called()
    mocks["app.modules.health_isf.service._sweep_stale_assignment_rows_for_organization"].assert_not_called()
    mocks["app.modules.health_isf.service._offer_newest_queue_ride_to_driver"].assert_not_called()
    mocks["app.modules.health_isf.service.get_driver_active_offer"].assert_not_called()
    mocks["app.modules.health_isf.service.get_driver_live_workspace_data"].assert_not_called()
    mocks["app.modules.health_isf.service.get_driver_active_ride_data"].assert_not_called()
    mocks["app.modules.health_isf.service.list_driver_assigned_rides"].assert_not_called()


def test_driver_read_snapshot_returns_quickly(client: TestClient) -> None:
    import time

    driver_id, headers = _driver_session(client)
    timings: dict[str, float] = {}
    for label, suffix in [
        ("active_ride", "active-ride"),
        ("active_offer", "active-offer"),
        ("live_workspace", "live-workspace"),
        ("assigned_rides", "assigned-rides?limit=15"),
    ]:
        started = time.perf_counter()
        response = client.get(
            f"/api/health-isf/drivers/{driver_id}/{suffix}",
            headers=headers,
        )
        timings[label] = time.perf_counter() - started
        assert response.status_code == 200, response.text

    # Local sqlite/dev threshold — production verified separately.
    for label, seconds in timings.items():
        assert seconds < 5.0, f"{label} took {seconds:.2f}s locally"


def test_throttled_dispatch_maintenance_skips_within_interval() -> None:
    from app.modules.health_isf.dispatch_maintenance import maybe_run_organization_dispatch_maintenance

    org_id = "test-org-throttle"
    with SessionLocal() as db:
        first = maybe_run_organization_dispatch_maintenance(
            db,
            organization_id=org_id,
            force=True,
        )
        assert first.get("skipped") is False
        second = maybe_run_organization_dispatch_maintenance(db, organization_id=org_id)
        assert second.get("skipped") is True
        assert second.get("reason") == "throttled"
