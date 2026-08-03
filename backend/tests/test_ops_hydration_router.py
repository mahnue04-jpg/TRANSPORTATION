from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_ops_dashboard_requires_auth() -> None:
    client = TestClient(app)
    response = client.get("/api/ops/dashboard-summary")
    assert response.status_code in {401, 403}


def test_ops_dashboard_dispatcher_payload_shape(client: TestClient) -> None:
    token = _login(client, "dispatcher@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/ops/dashboard-summary", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert "dashboard" in payload
    assert "rides" in payload
    assert "alerts" in payload
    assert payload["governance"]["execution_disabled"] is True
    assert payload["governance"]["advisory_only"] is True
    assert payload["audit_metadata"]["replay_safe"] is True
    assert isinstance(payload.get("assistant_recommendations"), list)


def test_ops_dashboard_driver_is_role_masked(client: TestClient) -> None:
    token = _login(client, "driver@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    summary_response = client.get("/api/ops/dashboard-summary", headers=headers)
    assert summary_response.status_code == 200, summary_response.text
    summary = summary_response.json()

    assert summary["visibility"]["show_driver_metrics"] is False
    assert summary["visibility"]["show_provider_metrics"] is False
    assert summary["drivers"]["masked"] is True
    assert summary["providers"]["masked"] is True

    timeline_response = client.get("/api/ops/timeline", headers=headers)
    assert timeline_response.status_code == 200, timeline_response.text
    timeline = timeline_response.json()
    assert timeline["append_only"] is True
    for event in timeline.get("events", []):
        assert event.get("description") == "masked_for_role"


def test_ops_timeline_cursor_contract(client: TestClient) -> None:
    token = _login(client, "dispatcher@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get("/api/ops/timeline?after_sequence=0&limit=20", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["append_only"] is True
    assert payload["replay_safe"] is True
    assert payload["ordering"] == "sequence_ascending"
    assert payload["next_cursor"] >= 0


def test_shell_dashboard_and_favicon_smoke(client: TestClient) -> None:
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200, dashboard.text
    body = dashboard.text
    assert "AMICOR" in body
    assert "Transport. Care. Connect." in body
    assert "amicor-mark.png" in body
    assert "ops-shell.js" in body
    assert 'option value="admin"' in body
    assert 'option value="rider"' in body
    assert 'option value="driver"' in body
    assert 'option value="provider"' in body
    assert 'option value="compliance_officer"' in body
    assert 'option value="supervisor"' in body
    assert 'option value="driver_support"' in body
    assert 'option value="medical_coordinator"' in body
    assert 'option value="operations"' not in body
    assert body.index('option value="admin"') < body.index('option value="rider"')
    assert body.index('option value="rider"') < body.index('option value="driver"')
    assert body.index('option value="driver"') < body.index('option value="provider"')

    favicon = client.get("/favicon.ico")
    assert favicon.status_code in {200, 204}


def test_workspace_activation_medical_modules_and_actions(client: TestClient) -> None:
    token = _login(client, "medical@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    response = client.get(
        "/api/ops/workspace/activation?role_view=medical_coordinator",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["role_view"] == "medical_coordinator"
    modules = payload.get("workspace_modules", {})
    assert "patient_ride_coordination_queue" in modules
    assert "recurring_medical_schedule" in modules
    assert "appointment_pickup_dropoff_risk" in modules
    assert "provider_facility_coordination" in modules
    assert "patient_support_escalation" in modules

    allowed_actions = {
        str(item.get("action_type") or "").strip().lower()
        if isinstance(item, dict)
        else str(item or "").strip().lower()
        for item in list(payload.get("allowed_actions", []))
    }
    assert "medical_coordinator.review_appointment_risk" in allowed_actions
    assert "medical_coordinator.coordinate_facility" in allowed_actions
    assert "medical_coordinator.escalate_patient_support" in allowed_actions
    assert "supervisor.approve_override" not in allowed_actions


def test_workspace_action_medical_allowed_submits_supervised_event(client: TestClient) -> None:
    token = _login(client, "medical@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    baseline = client.get("/api/ops/timeline?after_sequence=0&limit=1", headers=headers)
    assert baseline.status_code == 200, baseline.text
    after_sequence = int(baseline.json().get("next_cursor", 0) or 0)

    action_response = client.post(
        "/api/ops/workspace/action?role_view=medical_coordinator",
        headers=headers,
        json={
            "action_type": "medical_coordinator.review_appointment_risk",
            "payload": {"task_id": "appt-risk-1"},
        },
    )
    assert action_response.status_code == 200, action_response.text
    action_payload = action_response.json()
    action_record = action_payload.get("action_record", {})
    assert action_record.get("status") in {
        "submitted_for_supervised_workflow",
        "submitted_and_executed_via_supervised_gateway",
    }
    assert action_record.get("append_only") is True
    assert action_record.get("replay_safe") is True

    timeline_response = client.get(
        f"/api/ops/timeline?after_sequence={after_sequence}&limit=50",
        headers=headers,
    )
    assert timeline_response.status_code == 200, timeline_response.text
    new_events = timeline_response.json().get("events", [])
    assert any(
        str(event.get("metadata", {}).get("action_type") or "")
        == "medical_coordinator.review_appointment_risk"
        and str(event.get("title") or "") == "Role workspace action submitted"
        for event in new_events
    )


def test_workspace_action_driver_support_denied_audited(client: TestClient) -> None:
    token = _login(client, "driversupport@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    baseline = client.get("/api/ops/timeline?after_sequence=0&limit=1", headers=headers)
    assert baseline.status_code == 200, baseline.text
    after_sequence = int(baseline.json().get("next_cursor", 0) or 0)

    denied_response = client.post(
        "/api/ops/workspace/action?role_view=driver_support",
        headers=headers,
        json={
            "action_type": "supervisor.approve_override",
            "payload": {"task_id": "override-1"},
        },
    )
    assert denied_response.status_code == 403, denied_response.text

    timeline_response = client.get(
        f"/api/ops/timeline?after_sequence={after_sequence}&limit=50",
        headers=headers,
    )
    assert timeline_response.status_code == 200, timeline_response.text
    new_events = timeline_response.json().get("events", [])
    assert any(
        str(event.get("metadata", {}).get("status") or "") == "denied"
        and str(event.get("metadata", {}).get("action_type") or "")
        == "supervisor.approve_override"
        and str(event.get("title") or "") == "Role workspace action denied"
        for event in new_events
    )


def test_workspace_action_driver_accept_records_execution_timeline(client: TestClient) -> None:
    dispatcher_token = _login(client, "dispatcher@amicor.local")["access_token"]
    dispatcher_headers = {"Authorization": f"Bearer {dispatcher_token}"}

    activation = client.get(
        "/api/ops/workspace/activation?role_view=dispatcher",
        headers=dispatcher_headers,
    )
    assert activation.status_code == 200, activation.text
    modules = activation.json().get("workspace_modules", {})
    queue = modules.get("trip_unassigned_queue", [])
    drivers = modules.get("trip_driver_availability", [])
    assert queue, "expected at least one unassigned trip"
    assert drivers, "expected at least one driver in availability board"

    trip_id = str((queue[0] or {}).get("trip_id") or (queue[0] or {}).get("ride_id") or "")
    driver_id = str((drivers[0] or {}).get("driver_id") or "")
    assert trip_id
    assert driver_id

    assign_response = client.post(
        "/api/ops/workspace/action?role_view=dispatcher",
        headers=dispatcher_headers,
        json={
            "action_type": "dispatch.assign_driver",
            "payload": {"trip_id": trip_id, "driver_id": driver_id},
        },
    )
    assert assign_response.status_code == 200, assign_response.text

    driver_token = _login(client, "driver@amicor.local")["access_token"]
    driver_headers = {"Authorization": f"Bearer {driver_token}"}
    baseline = client.get("/api/ops/timeline?after_sequence=0&limit=1", headers=driver_headers)
    assert baseline.status_code == 200, baseline.text
    after_sequence = int(baseline.json().get("next_cursor", 0) or 0)

    action_response = client.post(
        "/api/ops/workspace/action?role_view=driver",
        headers=driver_headers,
        json={
            "action_type": "driver.accept_assignment",
            "payload": {"trip_id": trip_id, "driver_id": driver_id},
        },
    )
    assert action_response.status_code == 200, action_response.text
    action_payload = action_response.json()
    execution_result = action_payload.get("action_record", {}).get("execution_result", {})
    assert execution_result.get("workflow") == "driver_accept_assignment"
    assert execution_result.get("trip_id") == trip_id

    timeline_response = client.get(
        f"/api/ops/timeline?after_sequence={after_sequence}&limit=50",
        headers=driver_headers,
    )
    assert timeline_response.status_code == 200, timeline_response.text
    new_events = timeline_response.json().get("events", [])
    assert any(
        str(event.get("title") or "") == "Driver execution step completed"
        and str(event.get("metadata", {}).get("action_type") or "") == "driver.accept_assignment"
        and str(event.get("metadata", {}).get("trip_id") or "") == trip_id
        for event in new_events
    )


def test_workspace_action_compliance_expiration_scan_records_execution(client: TestClient) -> None:
    token = _login(client, "compliance@amicor.local")["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    baseline = client.get("/api/ops/timeline?after_sequence=0&limit=1", headers=headers)
    assert baseline.status_code == 200, baseline.text
    after_sequence = int(baseline.json().get("next_cursor", 0) or 0)

    action_response = client.post(
        "/api/ops/workspace/action?role_view=compliance_officer",
        headers=headers,
        json={
            "action_type": "compliance.flag_document_expiration",
            "payload": {},
        },
    )
    assert action_response.status_code == 200, action_response.text
    action_payload = action_response.json()
    execution_result = action_payload.get("action_record", {}).get("execution_result", {})
    assert execution_result.get("workflow") == "compliance_expiration_scan"
    assert execution_result.get("status") == "expiration_alerts_refreshed"

    timeline_response = client.get(
        f"/api/ops/timeline?after_sequence={after_sequence}&limit=50",
        headers=headers,
    )
    assert timeline_response.status_code == 200, timeline_response.text
    new_events = timeline_response.json().get("events", [])
    assert any(
        str(event.get("title") or "") == "Compliance expiration scan executed"
        and str(event.get("metadata", {}).get("action_type") or "") == "compliance.flag_document_expiration"
        for event in new_events
    )
