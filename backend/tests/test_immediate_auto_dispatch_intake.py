"""Immediate customer-request intake should auto-dispatch without manual dispatcher approval."""
from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import (
    CustomerRequestStatus,
    DispatchAssignmentState,
    DriverStatus,
    HealthISFDispatchAssignment,
    HealthISFDispatchLog,
    HealthISFDriver,
    HealthISFProvider,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def _org_id_for(email: str) -> str:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == email).first()
        assert user is not None and user.organization_id is not None
        return str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        provider = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if provider:
            return str(provider.id)
        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Auto Dispatch Provider {uuid4()[:6]}",
            address="500 Auto Dispatch Avenue",
            phone="212-555-0700",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _ensure_available_driver(organization_id: str) -> str:
    with SessionLocal() as db:
        driver = HealthISFDriver(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Auto Dispatch Driver {uuid4()[:6]}",
            phone=f"917-555-{str(uuid4()).replace('-', '')[:4]}",
            vehicle_type="sedan",
            vehicle_plate=f"AD-{uuid4()[:5].upper()}",
            status=DriverStatus.AVAILABLE,
            availability_state="available",
            is_active=True,
            is_online=True,
            auth_state="active",
            rating=4.9,
        )
        db.add(driver)
        db.commit()
        return str(driver.id)


def test_immediate_customer_request_auto_dispatches_in_background(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEALTH_ISF_AUTO_DISPATCH_ENABLED", "1")
    rider_auth = _login(client, "rider@amicor.local")
    rider_headers = {"Authorization": f"Bearer {rider_auth['access_token']}"}
    org_id = _org_id_for("rider@amicor.local")
    _ensure_provider(org_id)
    driver_id = _ensure_available_driver(org_id)
    suffix = uuid4()[:8]

    create_resp = client.post(
        "/api/health-isf/customer-requests",
        headers=rider_headers,
        json={
            "rider_name": f"Immediate Auto {suffix}",
            "rider_phone": f"646-555-{suffix[:4]}",
            "pickup_address": f"10 Immediate Pickup {suffix}, New York, NY",
            "dropoff_address": f"20 Immediate Dropoff {suffix}, New York, NY",
            "ride_type": "healthcare",
            "recurring": False,
        },
    )
    assert create_resp.status_code == 201, create_resp.text
    created = create_resp.json()
    ride_id = created["ride_id"]
    request_id = created["id"]

    deadline = time.time() + 20
    assignment = None
    request_status = created.get("dispatch_status")
    while time.time() < deadline:
        with SessionLocal() as db:
            assignment = (
                db.query(HealthISFDispatchAssignment)
                .filter(HealthISFDispatchAssignment.ride_id == ride_id)
                .order_by(HealthISFDispatchAssignment.created_at.desc())
                .first()
            )
            from app.modules.health_isf.models import HealthISFCustomerRideRequest

            request_row = db.query(HealthISFCustomerRideRequest).filter(HealthISFCustomerRideRequest.id == request_id).first()
            request_status = getattr(request_row, "dispatch_status", request_status)
            audit_actions = [
                str(row.action)
                for row in db.query(HealthISFDispatchLog)
                .filter(HealthISFDispatchLog.ride_id == ride_id)
                .all()
            ]
        if assignment and str(assignment.assignment_state) == DispatchAssignmentState.OFFERED.value:
            break
        if "auto_dispatch_completed" in audit_actions:
            break
        time.sleep(0.5)

    assert assignment is not None, "expected dispatch assignment after intake automation"
    assert str(assignment.assignment_state) == DispatchAssignmentState.OFFERED.value
    assert str(assignment.driver_id) == driver_id
    assert request_status in {
        CustomerRequestStatus.ASSIGNED.value,
        CustomerRequestStatus.DISPATCHABLE.value,
        CustomerRequestStatus.ACCEPTED.value,
    }
    assert "auto_dispatch_requested" in audit_actions
    assert "auto_dispatch_started" in audit_actions
    assert "auto_dispatch_completed" in audit_actions
