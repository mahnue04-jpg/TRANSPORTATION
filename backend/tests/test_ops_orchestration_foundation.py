from __future__ import annotations

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


def _login(client: TestClient, email: str) -> dict:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": SEED_PASSWORD},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    token = str(payload.get("access_token") or "")
    assert token
    return payload


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _me(client: TestClient, token: str) -> dict:
    response = client.get("/api/auth/me", headers=_headers(token))
    assert response.status_code == 200, response.text
    return response.json()


def _create_task(client: TestClient, token: str, title: str) -> str:
    response = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={
            "title": title,
            "description": "supervised orchestration test task",
            "category": "queue",
            "priority": "high",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["task_id"])


def test_append_only_guarantees_and_immutable_timeline(client: TestClient) -> None:
    supervisor = _login(client, "supervisor@amicor.local")
    supervisor_token = supervisor["access_token"]
    supervisor_id = _me(client, supervisor_token)["user_id"]

    task_id = _create_task(client, supervisor_token, f"task-{uuid4().hex[:8]}")

    assigned = client.post(
        "/api/ops/orchestration/task/assign",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "assigned_to": supervisor_id,
            "assigned_to_role": "supervisor",
            "reason": "manual assignment",
        },
    )
    assert assigned.status_code == 200, assigned.text

    acknowledged = client.post(
        "/api/ops/orchestration/task/acknowledge",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "note": "acknowledged by supervisor",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text

    timeline = client.get("/api/ops/orchestration/timeline?after_sequence=0&limit=200", headers=_headers(supervisor_token))
    assert timeline.status_code == 200, timeline.text
    payload = timeline.json()
    assert payload["append_only"] is True
    assert payload["replay_safe"] is True
    assert payload["execution_disabled"] is True
    assert payload["autonomous_execution"] is False

    events = payload.get("events", [])
    sequences = [int(row.get("sequence", 0) or 0) for row in events]
    assert sequences == sorted(sequences)
    for row in events:
        assert row.get("immutable_audit_ref")


def test_escalation_ordering(client: TestClient) -> None:
    supervisor = _login(client, "supervisor@amicor.local")
    supervisor_token = supervisor["access_token"]
    supervisor_id = _me(client, supervisor_token)["user_id"]

    task_id = _create_task(client, supervisor_token, f"escalation-{uuid4().hex[:8]}")

    first = client.post(
        "/api/ops/orchestration/task/escalate",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "escalation_level": "level_2",
            "routed_to": supervisor_id,
            "routed_to_role": "supervisor",
            "reason": "manual escalation",
        },
    )
    assert first.status_code == 200, first.text

    regression = client.post(
        "/api/ops/orchestration/task/escalate",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "escalation_level": "level_1",
            "routed_to": supervisor_id,
            "routed_to_role": "supervisor",
            "reason": "regression should fail",
        },
    )
    assert regression.status_code == 409


def test_role_authorization_and_queue_visibility_isolation(client: TestClient) -> None:
    supervisor_token = _login(client, "supervisor@amicor.local")["access_token"]
    driver_payload = _login(client, "driversupport@amicor.local")
    driver_token = driver_payload["access_token"]
    compliance_token = _login(client, "compliance@amicor.local")["access_token"]
    medical_token = _login(client, "medical@amicor.local")["access_token"]

    driver_id = _me(client, driver_token)["user_id"]
    supervisor_id = _me(client, supervisor_token)["user_id"]

    driver_task = _create_task(client, supervisor_token, f"driver-task-{uuid4().hex[:8]}")
    other_task = _create_task(client, supervisor_token, f"other-task-{uuid4().hex[:8]}")

    assign_driver = client.post(
        "/api/ops/orchestration/task/assign",
        headers=_headers(supervisor_token),
        json={
            "task_id": driver_task,
            "assigned_to": driver_id,
            "assigned_to_role": "driver_support",
            "reason": "driver support assignment",
        },
    )
    assert assign_driver.status_code == 200, assign_driver.text

    assign_other = client.post(
        "/api/ops/orchestration/task/assign",
        headers=_headers(supervisor_token),
        json={
            "task_id": other_task,
            "assigned_to": supervisor_id,
            "assigned_to_role": "supervisor",
            "reason": "supervisor-owned assignment",
        },
    )
    assert assign_other.status_code == 200, assign_other.text

    denied_assign = client.post(
        "/api/ops/orchestration/task/assign",
        headers=_headers(driver_token),
        json={
            "task_id": other_task,
            "assigned_to": driver_id,
            "assigned_to_role": "driver_support",
            "reason": "should not allow",
        },
    )
    assert denied_assign.status_code == 403

    compliance_ack = client.post(
        "/api/ops/orchestration/task/acknowledge",
        headers=_headers(compliance_token),
        json={"task_id": other_task, "note": "compliance acknowledged"},
    )
    assert compliance_ack.status_code == 200, compliance_ack.text

    driver_queue = client.get("/api/ops/orchestration/queue", headers=_headers(driver_token))
    assert driver_queue.status_code == 200, driver_queue.text
    driver_tasks = {row.get("task_id") for row in driver_queue.json().get("tasks", [])}
    assert driver_task in driver_tasks
    assert other_task not in driver_tasks

    medical_queue = client.get("/api/ops/orchestration/queue", headers=_headers(medical_token))
    assert medical_queue.status_code == 200, medical_queue.text
    assert medical_queue.json().get("masked") is True
    assert medical_queue.json().get("tasks") == []


def test_handoff_sequencing_and_notification_lineage(client: TestClient) -> None:
    supervisor_token = _login(client, "supervisor@amicor.local")["access_token"]
    target_user = _me(client, supervisor_token)["user_id"]

    task_id = _create_task(client, supervisor_token, f"handoff-{uuid4().hex[:8]}")

    step1 = client.post(
        "/api/ops/orchestration/task/handoff",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "stage": "handoff_pending",
            "to_user_id": target_user,
            "to_role": "supervisor",
            "note": "pending handoff",
        },
    )
    assert step1.status_code == 200, step1.text

    step2 = client.post(
        "/api/ops/orchestration/task/handoff",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "stage": "handoff_complete",
            "to_user_id": target_user,
            "to_role": "supervisor",
            "note": "handoff complete",
        },
    )
    assert step2.status_code == 200, step2.text

    regression = client.post(
        "/api/ops/orchestration/task/handoff",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "stage": "assigned",
            "to_user_id": target_user,
            "to_role": "supervisor",
            "note": "regression should fail",
        },
    )
    assert regression.status_code == 409

    notification = client.post(
        "/api/ops/orchestration/notifications/append",
        headers=_headers(supervisor_token),
        json={
            "task_id": task_id,
            "notification_type": "handoff_notice",
            "message": "handoff completed under supervision",
            "metadata": {"scope": "phase26"},
        },
    )
    assert notification.status_code == 200, notification.text

    feed = client.get("/api/ops/orchestration/notifications", headers=_headers(supervisor_token))
    assert feed.status_code == 200, feed.text
    entries = feed.json().get("notifications", [])
    assert any(row.get("task_id") == task_id for row in entries)
    assert all(bool(row.get("immutable_audit_ref")) for row in entries[:5])


def test_utc_timestamp_normalization_and_replay_safe_hydration(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")["access_token"]

    task_id = _create_task(client, admin_token, f"utc-{uuid4().hex[:8]}")
    assign = client.post(
        "/api/ops/orchestration/task/assign",
        headers=_headers(admin_token),
        json={
            "task_id": task_id,
            "assigned_to": _me(client, admin_token)["user_id"],
            "assigned_to_role": "admin",
            "reason": "utc test",
        },
    )
    assert assign.status_code == 200, assign.text

    assign_ts = assign.json().get("timestamp")
    assert assign_ts
    parsed = datetime.fromisoformat(str(assign_ts))
    assert parsed.tzinfo is not None

    timeline = client.get("/api/ops/orchestration/timeline?after_sequence=0&limit=50", headers=_headers(admin_token))
    assert timeline.status_code == 200, timeline.text
    t_payload = timeline.json()
    assert t_payload["advisory_only"] is True
    assert t_payload["execution_disabled"] is True
    assert t_payload["autonomous_execution"] is False
    assert t_payload["append_only"] is True
    assert t_payload["replay_safe"] is True

    queue = client.get("/api/ops/orchestration/queue", headers=_headers(admin_token))
    assert queue.status_code == 200, queue.text
    q_payload = queue.json()
    assert q_payload["advisory_only"] is True
    assert q_payload["execution_disabled"] is True
    assert q_payload["autonomous_execution"] is False
    assert q_payload["append_only"] is True
    assert q_payload["replay_safe"] is True


def test_fallback_hydration_safety_auth_boundary(client: TestClient) -> None:
    queue = client.get("/api/ops/orchestration/queue")
    timeline = client.get("/api/ops/orchestration/timeline?after_sequence=0&limit=20")
    notifications = client.get("/api/ops/orchestration/notifications")

    assert queue.status_code in {401, 403}
    assert timeline.status_code in {401, 403}
    assert notifications.status_code in {401, 403}
