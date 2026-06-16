import json

from fastapi.testclient import TestClient
import pytest

from app.auth import ensure_auth_schema, seed_default_users
from app.db.models import User as PlatformUser
from app.db.session import SessionLocal
from app.helpers import uuid4
from app.main import app
from app.modules.health_isf.models import HealthISFCustomerRideRequest, HealthISFProvider, SecurityAuditAction


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login_dispatcher(client: TestClient) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": "dispatcher@amicor.local", "password": "Amicor123!"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload.get("access_token")
    return payload


def _dispatcher_context() -> tuple[str, str]:
    with SessionLocal() as db:
        user = db.query(PlatformUser).filter(PlatformUser.email == "dispatcher@amicor.local").first()
        assert user is not None
        assert user.organization_id is not None
        return str(user.id), str(user.organization_id)


def _ensure_provider(organization_id: str) -> str:
    with SessionLocal() as db:
        existing = (
            db.query(HealthISFProvider)
            .filter(HealthISFProvider.organization_id == organization_id)
            .order_by(HealthISFProvider.created_at.desc())
            .first()
        )
        if existing:
            return str(existing.id)

        provider = HealthISFProvider(
            id=uuid4(),
            organization_id=organization_id,
            name=f"Day2 Provider {uuid4()[:6]}",
            address="600 Day2 Ave",
            phone="212-555-6299",
            service_type="clinic",
            is_active=True,
        )
        db.add(provider)
        db.commit()
        return str(provider.id)


def _create_request(client: TestClient, headers: dict, suffix: str) -> dict:
    response = client.post(
        "/api/health-isf/customer-requests",
        headers=headers,
        json={
            "rider_name": f"Day2 Rider {suffix}",
            "rider_phone": f"+1 917-555-{suffix}",
            "pickup_address": f"{suffix} Intake St",
            "dropoff_address": f"{suffix} Care Ave",
            "ride_type": "healthcare",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pending_request_blocked_for_manual_assignment_and_auto_dispatch(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _, organization_id = _dispatcher_context()
    _ensure_provider(organization_id)
    request_payload = _create_request(client, headers, "6201")
    with SessionLocal() as db:
        row = db.query(HealthISFCustomerRideRequest).filter(HealthISFCustomerRideRequest.id == request_payload["id"]).first()
        assert row is not None
        row.dispatch_status = "pending"
        db.commit()

    assign_response = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_payload['id']}/assign-driver",
        headers=headers,
        json={"driver_id": "drv-day2-placeholder"},
    )
    assert assign_response.status_code == 409, assign_response.text

    auto_response = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{request_payload['id']}/auto-dispatch",
        headers=headers,
        json={"offer_timeout_seconds": 90},
    )
    assert auto_response.status_code == 409, auto_response.text


def test_customer_request_queue_prioritizes_dispatch_ready_work_over_pending(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    _, organization_id = _dispatcher_context()
    _ensure_provider(organization_id)

    approved_candidate = _create_request(client, headers, "6202")
    pending_candidate = _create_request(client, headers, "6203")

    approve_response = client.post(
        f"/api/health-isf/dispatcher/customer-requests/{approved_candidate['id']}/approve",
        headers=headers,
        json={},
    )
    assert approve_response.status_code == 200, approve_response.text

    prioritized = client.get(
        "/api/health-isf/customer-requests",
        headers=headers,
        params={"prioritize": "true", "limit": 25},
    )
    assert prioritized.status_code == 200, prioritized.text
    prioritized_rows = prioritized.json()

    approved_index = next(i for i, row in enumerate(prioritized_rows) if row["id"] == approved_candidate["id"])
    pending_index = next(i for i, row in enumerate(prioritized_rows) if row["id"] == pending_candidate["id"])
    assert approved_index < pending_index

    chronological = client.get(
        "/api/health-isf/customer-requests",
        headers=headers,
        params={"prioritize": "false", "limit": 25},
    )
    assert chronological.status_code == 200, chronological.text
    chronological_rows = chronological.json()

    approved_index_chron = next(i for i, row in enumerate(chronological_rows) if row["id"] == approved_candidate["id"])
    pending_index_chron = next(i for i, row in enumerate(chronological_rows) if row["id"] == pending_candidate["id"])
    assert pending_index_chron < approved_index_chron


def test_workflow_escalation_writes_security_audit_record(client: TestClient) -> None:
    auth = _login_dispatcher(client)
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    actor_user_id, organization_id = _dispatcher_context()

    with SessionLocal() as db:
        before = (
            db.query(SecurityAuditAction)
            .filter(
                SecurityAuditAction.organization_id == organization_id,
                SecurityAuditAction.action_type == "workflow_escalated",
                SecurityAuditAction.actor_user_id == actor_user_id,
            )
            .count()
        )

    _ensure_provider(organization_id)
    request_payload = _create_request(client, headers, "6204")

    response = client.post(
        "/api/health-isf/workflows/escalate",
        headers=headers,
        json={
            "organization_id": organization_id,
            "ride_id": request_payload["ride_id"],
            "summary": "Day2 escalation audit validation",
            "severity": "high",
            "target_role": "supervisor",
            "escalation_level": 2,
            "details": {"source": "day2_contract"},
        },
    )
    assert response.status_code == 200, response.text

    with SessionLocal() as db:
        rows = (
            db.query(SecurityAuditAction)
            .filter(
                SecurityAuditAction.organization_id == organization_id,
                SecurityAuditAction.action_type == "workflow_escalated",
                SecurityAuditAction.actor_user_id == actor_user_id,
            )
            .all()
        )
    assert len(rows) == before + 1
    latest = max(rows, key=lambda row: row.created_at)
    details = json.loads(latest.details or "{}")
    assert details.get("summary") == "Day2 escalation audit validation"
    assert details.get("target_role") == "supervisor"
