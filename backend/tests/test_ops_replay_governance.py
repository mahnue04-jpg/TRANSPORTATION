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
    token = str(response.json().get("access_token") or "")
    assert token
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_task(client: TestClient, token: str, title_prefix: str = "phase29") -> str:
    response = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={
            "title": f"{title_prefix}-{uuid4().hex[:8]}",
            "description": "phase29 replay seed",
            "priority": "high",
            "category": "operations",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json().get("task_id"))


def _seed_replay_history(client: TestClient, token: str) -> tuple[str, str]:
    task_id = _create_task(client, token, "replay-history")
    requested = client.post(
        "/api/ops/orchestration/task/resolve",
        headers=_headers(token),
        json={"task_id": task_id, "reason": "replay seed resolution"},
    )
    assert requested.status_code == 200, requested.text

    scenario = client.post(
        "/api/ops/replay/scenario/create",
        headers=_headers(token),
        json={
            "scenario_name": "Replay Stability Check",
            "hypothesis": "Replay projection should remain deterministic.",
            "scenario_type": "operational_replay",
            "baseline_window": "historical",
        },
    )
    assert scenario.status_code == 200, scenario.text
    scenario_id = str(scenario.json().get("scenario_id") or "")
    assert scenario_id

    session = client.post(
        "/api/ops/replay/session/create",
        headers=_headers(token),
        json={
            "session_name": "Replay Session Alpha",
            "after_sequence": 0,
            "limit": 200,
            "scenario_id": scenario_id,
        },
    )
    assert session.status_code == 200, session.text
    session_id = str(session.json().get("replay_session_id") or "")
    assert session_id
    return session_id, scenario_id


def test_replay_deterministic_timeline_and_projection(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id, _ = _seed_replay_history(client, admin_token)

    timeline_one = client.get(
        "/api/ops/replay/timeline?after_sequence=0&limit=200",
        headers=_headers(admin_token),
    )
    timeline_two = client.get(
        "/api/ops/replay/timeline?after_sequence=0&limit=200",
        headers=_headers(admin_token),
    )
    assert timeline_one.status_code == 200, timeline_one.text
    assert timeline_two.status_code == 200, timeline_two.text

    payload_one = timeline_one.json()
    payload_two = timeline_two.json()
    assert payload_one["append_only"] is True
    assert payload_one["replay_safe"] is True
    assert payload_one["ordering"] == "deterministic_timestamp_eventid_ascending"
    assert [row["event_id"] for row in payload_one["events"]] == [row["event_id"] for row in payload_two["events"]]
    for row in payload_one["events"]:
        timestamp = row.get("timestamp")
        if timestamp:
            parsed = datetime.fromisoformat(str(timestamp))
            assert parsed.tzinfo is not None

    projection_one = client.get(
        f"/api/ops/replay/projection?after_sequence=0&limit=200&replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    projection_two = client.get(
        f"/api/ops/replay/projection?after_sequence=0&limit=200&replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    assert projection_one.status_code == 200, projection_one.text
    assert projection_two.status_code == 200, projection_two.text
    proj_one = projection_one.json()
    proj_two = projection_two.json()
    assert proj_one["advisory_only"] is True
    assert proj_one["execution_disabled"] is True
    assert proj_one["autonomous_execution"] is False
    assert [row["projection_sequence"] for row in proj_one["events"]] == sorted([row["projection_sequence"] for row in proj_one["events"]])
    assert [row["source_event_id"] for row in proj_one["events"]] == [row["source_event_id"] for row in proj_two["events"]]
    assert [row["source_event_type"] for row in proj_one["events"]] == [row["source_event_type"] for row in proj_two["events"]]


def test_replay_branch_lineage_and_continuity_validation(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id, scenario_id = _seed_replay_history(client, admin_token)

    branch = client.post(
        "/api/ops/replay/branch/generate",
        headers=_headers(admin_token),
        json={
            "replay_session_id": session_id,
            "branch_name": "Branch Alpha",
            "branch_type": "deterministic_replay",
            "scenario_id": scenario_id,
        },
    )
    assert branch.status_code == 200, branch.text
    branch_payload = branch.json()
    assert branch_payload["append_only"] is True
    assert branch_payload["replay_safe"] is True
    assert branch_payload["base_checksum"]
    assert branch_payload["branch_checksum"]

    comparison = client.get(
        f"/api/ops/replay/comparison?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    continuity = client.get(
        f"/api/ops/replay/continuity?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    evidence = client.get(
        "/api/ops/replay/evidence",
        headers=_headers(admin_token),
    )
    assert comparison.status_code == 200, comparison.text
    assert continuity.status_code == 200, continuity.text
    assert evidence.status_code == 200, evidence.text

    comparison_payload = comparison.json()
    continuity_payload = continuity.json()
    evidence_payload = evidence.json()
    assert comparison_payload["advisory_only"] is True
    assert len(comparison_payload.get("comparisons", [])) >= 1
    assert continuity_payload["advisory_only"] is True
    assert continuity_payload["append_only"] is True
    assert continuity_payload["replay_safe"] is True
    assert evidence_payload["bundle_checksum"]
    assert evidence_payload["payload"]["replay_reconstruction"]["ordering"] == "deterministic_timestamp_eventid_ascending"


def test_replay_export_integrity_and_compliance_integration(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    _seed_replay_history(client, admin_token)

    export_resp = client.get("/api/ops/replay/export-bundle", headers=_headers(admin_token))
    assert export_resp.status_code == 200, export_resp.text
    export_payload = export_resp.json()
    canonical = json.dumps(export_payload.get("payload", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
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
    assert "phase29_replay_evidence" in integrated_payload
    assert integrated_payload["phase29_replay_evidence"]["append_only"] is True


def test_replay_auth_boundaries_and_shell_fallback(client: TestClient) -> None:
    driver_token = _login(client, "driver@amicor.local")

    unauthorized_write = client.post(
        "/api/ops/replay/session/create",
        headers=_headers(driver_token),
        json={"session_name": "Nope"},
    )
    assert unauthorized_write.status_code in {401, 403}

    unauthorized_read = client.get("/api/ops/replay/timeline")
    assert unauthorized_read.status_code in {401, 403}

    shell = client.get("/operations/replay")
    assert shell.status_code == 200, shell.text
    assert "ops-shell.js" in shell.text
