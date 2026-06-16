from __future__ import annotations

import hashlib
import json
from datetime import datetime
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
    payload = response.json()
    token = str(payload.get("access_token") or "")
    assert token
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_task(client: TestClient, token: str, title_prefix: str = "phase27") -> str:
    response = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={
            "title": f"{title_prefix}-{uuid4().hex[:8]}",
            "description": "phase27 supervised task",
            "priority": "high",
            "category": "operations",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json().get("task_id"))


def test_dual_approval_enforcement_and_supervisor_requirement(client: TestClient) -> None:
    supervisor_token = _login(client, "supervisor@amicor.local")
    compliance_token = _login(client, "compliance@amicor.local")

    task_id = _create_task(client, supervisor_token, "resolve-dual")

    requested = client.post(
        "/api/ops/orchestration/task/resolve",
        headers=_headers(supervisor_token),
        json={"task_id": task_id, "reason": "ready for supervised closure"},
    )
    assert requested.status_code == 200, requested.text
    assert requested.json()["append_only"] is True

    first_approval = client.post(
        "/api/ops/orchestration/task/approve-resolution",
        headers=_headers(compliance_token),
        json={"task_id": task_id, "reason": "compliance confirms"},
    )
    assert first_approval.status_code == 200, first_approval.text
    first_payload = first_approval.json()
    assert first_payload["closure_achieved"] is False
    assert first_payload["dual_approval_satisfied"] is False
    assert first_payload["supervisor_approval_present"] is False

    second_approval = client.post(
        "/api/ops/orchestration/task/approve-resolution",
        headers=_headers(supervisor_token),
        json={"task_id": task_id, "reason": "supervisor approves closure"},
    )
    assert second_approval.status_code == 200, second_approval.text
    second_payload = second_approval.json()
    assert second_payload["closure_achieved"] is True
    assert second_payload["dual_approval_satisfied"] is True
    assert second_payload["supervisor_approval_present"] is True

    no_more_changes = client.post(
        "/api/ops/orchestration/task/reject-resolution",
        headers=_headers(supervisor_token),
        json={"task_id": task_id, "reason": "should be blocked after closure"},
    )
    assert no_more_changes.status_code == 409


def test_replay_projection_ordering_and_utc_normalization(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    task_id = _create_task(client, admin_token, "projection")
    resolve = client.post(
        "/api/ops/orchestration/task/resolve",
        headers=_headers(admin_token),
        json={"task_id": task_id, "reason": "projection check"},
    )
    assert resolve.status_code == 200, resolve.text

    projection = client.get(
        "/api/ops/orchestration/live-stream?after_sequence=0&limit=200",
        headers=_headers(admin_token),
    )
    assert projection.status_code == 200, projection.text
    payload = projection.json()

    assert payload["append_only"] is True
    assert payload["replay_safe"] is True
    assert payload["execution_disabled"] is True
    assert payload["autonomous_execution"] is False
    assert payload["ordering"] == "deterministic_timestamp_eventid_ascending"

    events = payload.get("events", [])
    projection_sequences = [int(row.get("projection_sequence", 0) or 0) for row in events]
    assert projection_sequences == sorted(projection_sequences)
    for row in events:
                timestamp = row.get("timestamp")
                if timestamp:
                        parsed = datetime.fromisoformat(str(timestamp))
                        assert parsed.tzinfo is not None

    replay = client.get(
        "/api/ops/orchestration/live-stream?after_sequence=0&limit=200",
        headers=_headers(admin_token),
    )
    assert replay.status_code == 200, replay.text
    replay_events = replay.json().get("events", [])
    assert [row.get("event_id") for row in events] == [row.get("event_id") for row in replay_events]


def test_live_stream_masking_for_medical_coordinator(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    medical_token = _login(client, "medical@amicor.local")

    task_id = _create_task(client, admin_token, "medical-mask")
    requested = client.post(
        "/api/ops/orchestration/task/resolve",
        headers=_headers(admin_token),
        json={"task_id": task_id, "reason": "masking validation"},
    )
    assert requested.status_code == 200, requested.text

    masked_projection = client.get(
        "/api/ops/orchestration/live-stream?after_sequence=0&limit=50",
        headers=_headers(medical_token),
    )
    assert masked_projection.status_code == 200, masked_projection.text
    events = masked_projection.json().get("events", [])
    assert events
    assert all(str(row.get("task_id")) == "masked" for row in events)


def test_sla_snapshot_queue_congestion_advisory_only(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    for _ in range(22):
        _create_task(client, admin_token, "sla-load")

    sla = client.get("/api/ops/orchestration/sla", headers=_headers(admin_token))
    assert sla.status_code == 200, sla.text
    payload = sla.json()

    assert payload["advisory_only"] is True
    assert payload["execution_disabled"] is True
    assert payload["autonomous_execution"] is False
    assert payload["advisory_limitations"]["escalation_actions_automatic"] is False

    metrics = payload.get("metrics", {})
    assert int(metrics.get("queue_congestion", 0) or 0) >= 20


def test_export_bundle_integrity_and_compliance_integration(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    export_resp = client.get("/api/ops/orchestration/export-bundle", headers=_headers(admin_token))
    assert export_resp.status_code == 200, export_resp.text
    export_payload = export_resp.json()

    bundle_payload = export_payload.get("payload", {})
    canonical = json.dumps(bundle_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected_checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert export_payload.get("bundle_checksum") == expected_checksum
    assert export_payload.get("append_only") is True
    assert export_payload.get("replay_safe") is True

    integrated = client.post(
        "/api/ops/compliance/exports/generate",
        headers=_headers(admin_token),
        json={"export_scope": "driver_regulatory_bundle"},
    )
    assert integrated.status_code == 200, integrated.text
    integrated_payload = integrated.json()
    assert "phase27_orchestration_evidence" in integrated_payload
    assert integrated_payload["phase27_orchestration_evidence"]["append_only"] is True


def test_authorization_boundaries_and_hydration_fallback(client: TestClient) -> None:
    for path in [
        "/api/ops/orchestration/task/resolve",
        "/api/ops/orchestration/task/approve-resolution",
        "/api/ops/orchestration/task/reject-resolution",
    ]:
        response = client.post(path, json={"task_id": "x", "reason": "x"})
        assert response.status_code in {401, 403}

    for path in [
        "/api/ops/orchestration/live-stream",
        "/api/ops/orchestration/sla",
        "/api/ops/orchestration/queue-health",
        "/api/ops/orchestration/export-bundle",
    ]:
        response = client.get(path)
        assert response.status_code in {401, 403}

    shell = client.get("/operations/live")
    assert shell.status_code == 200, shell.text
    assert "ops-shell.js" in shell.text
