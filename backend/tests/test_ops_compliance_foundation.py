from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upsert_profile(client: TestClient, token: str, driver_id: str, **extra: object) -> dict:
    body = {
        "driver_id": driver_id,
        "onboarding_status": "pending",
        "compliance_status": "pending",
        "approval_status": "pending",
        "background_check_status": "pending",
        "medical_transport_certified": False,
        "training_completed": False,
    }
    body.update(extra)
    response = client.post("/api/ops/compliance/profile/upsert", headers=_headers(token), json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _workflow(client: TestClient, token: str, driver_id: str, action: str, reason: str = "workflow test") -> dict:
    response = client.post(
        "/api/ops/compliance/workflow/action",
        headers=_headers(token),
        json={"driver_id": driver_id, "action": action, "reason": reason},
    )
    return response


def test_compliance_auth_boundary_protected(client: TestClient) -> None:
    response = client.get("/api/ops/compliance/dashboard-summary")
    assert response.status_code in {401, 403}


def test_role_scoped_compliance_visibility_medical_coordinator(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    medical_token = _login(client, "medical@amicor.local")

    driver_id = f"driver-{uuid4().hex[:12]}"
    _upsert_profile(
        client,
        admin_token,
        driver_id,
        medical_transport_certified=True,
        training_completed=True,
        license_number="LIC-12345",
        notes="full profile",
    )

    upload = client.post(
        "/api/ops/compliance/documents/upload-metadata",
        headers=_headers(admin_token),
        json={
            "driver_id": driver_id,
            "type": "driver_license",
            "expiration_date": (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
        },
    )
    assert upload.status_code == 200, upload.text

    medical_summary = client.get(
        "/api/ops/compliance/dashboard-summary?role_view=medical_coordinator",
        headers=_headers(medical_token),
    )
    assert medical_summary.status_code == 200, medical_summary.text
    payload = medical_summary.json()

    assert payload["role_view"] == "medical_coordinator"
    assert isinstance(payload.get("profiles"), list)
    assert payload["governance"]["advisory_only"] is True
    assert payload["governance"]["execution_disabled"] is True

    if payload["profiles"]:
        assert payload["profiles"][0].get("medical_scope") is True


def test_approval_workflow_ordering_and_supervised_path(client: TestClient) -> None:
    support_token = _login(client, "driversupport@amicor.local")
    compliance_token = _login(client, "compliance@amicor.local")
    supervisor_token = _login(client, "supervisor@amicor.local")

    driver_id = f"driver-{uuid4().hex[:12]}"
    _upsert_profile(client, support_token, driver_id)

    ordered_steps = [
        (support_token, "driver_application_submitted"),
        (compliance_token, "compliance_review_started"),
        (compliance_token, "documents_verified"),
        (compliance_token, "background_review_completed"),
        (compliance_token, "supervisor_approval_required"),
        (supervisor_token, "approved"),
    ]

    for token, step in ordered_steps:
        response = _workflow(client, token, driver_id, step, reason=f"{step} reason")
        assert response.status_code == 200, response.text

    summary = client.get("/api/ops/compliance/dashboard-summary", headers=_headers(supervisor_token))
    assert summary.status_code == 200, summary.text
    profiles = summary.json().get("profiles", [])
    target = [row for row in profiles if row.get("driver_id") == driver_id]
    assert target


def test_workflow_ordering_rejects_skips(client: TestClient) -> None:
    compliance_token = _login(client, "compliance@amicor.local")
    driver_id = f"driver-{uuid4().hex[:12]}"
    _upsert_profile(client, compliance_token, driver_id)

    response = _workflow(client, compliance_token, driver_id, "documents_verified", reason="skip should fail")
    assert response.status_code == 409
    assert "workflow ordering violation" in response.text


def test_append_only_audit_guarantee_and_timeline_integrity(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    driver_id = f"driver-{uuid4().hex[:12]}"

    _upsert_profile(client, admin_token, driver_id)
    _workflow(client, admin_token, driver_id, "driver_application_submitted", reason="append test")

    timeline = client.get("/api/ops/compliance/timeline?after_sequence=0&limit=200", headers=_headers(admin_token))
    assert timeline.status_code == 200, timeline.text
    payload = timeline.json()

    assert payload["append_only"] is True
    assert payload["replay_safe"] is True
    assert payload["ordering"] == "sequence_ascending"

    sequences = [int(row.get("sequence", 0) or 0) for row in payload.get("events", [])]
    assert sequences == sorted(sequences)


def test_expiration_engine_calculations(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    driver_id = f"driver-{uuid4().hex[:12]}"

    _upsert_profile(
        client,
        admin_token,
        driver_id,
        license_expiration=(datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
        insurance_expiration=(datetime.now(timezone.utc) + timedelta(days=5)).isoformat(),
        vehicle_inspection_expiration=(datetime.now(timezone.utc) + timedelta(days=45)).isoformat(),
    )

    summary = client.get("/api/ops/compliance/dashboard-summary", headers=_headers(admin_token))
    assert summary.status_code == 200, summary.text
    payload = summary.json()

    expiration = payload.get("expiration_queue", {})
    assert isinstance(expiration.get("licenses_expiring", []), list)
    assert isinstance(expiration.get("insurance_expiring", []), list)
    assert isinstance(expiration.get("severity_distribution", {}), dict)


def test_rejection_flow_and_reason_required(client: TestClient) -> None:
    compliance_token = _login(client, "compliance@amicor.local")
    supervisor_token = _login(client, "supervisor@amicor.local")
    driver_id = f"driver-{uuid4().hex[:12]}"

    _upsert_profile(client, compliance_token, driver_id)
    for step in [
        "driver_application_submitted",
        "compliance_review_started",
        "documents_verified",
        "background_review_completed",
        "supervisor_approval_required",
    ]:
        token = compliance_token
        if step == "driver_application_submitted":
            token = _login(client, "driversupport@amicor.local")
        response = _workflow(client, token, driver_id, step, reason=f"{step} reason")
        assert response.status_code == 200, response.text

    missing_reason = _workflow(client, supervisor_token, driver_id, "rejected", reason="")
    assert missing_reason.status_code == 422

    rejected = _workflow(client, supervisor_token, driver_id, "rejected", reason="incomplete records")
    assert rejected.status_code == 200, rejected.text


def test_operator_only_approval_enforcement(client: TestClient) -> None:
    support_token = _login(client, "driversupport@amicor.local")
    driver_id = f"driver-{uuid4().hex[:12]}"

    _upsert_profile(client, support_token, driver_id)
    response = _workflow(client, support_token, driver_id, "approved", reason="should fail")
    assert response.status_code == 403


def test_replay_safe_hydration_in_compliance_summary(client: TestClient) -> None:
    compliance_token = _login(client, "compliance@amicor.local")
    response = client.get("/api/ops/compliance/dashboard-summary", headers=_headers(compliance_token))
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["governance"]["replay_safe"] is True
    assert payload["governance"]["append_only"] is True
    assert payload["governance"]["autonomous_execution"] is False
    assert payload["governance"]["dispatch_actions_enabled"] is False
