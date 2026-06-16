from __future__ import annotations

import hashlib
import json
from datetime import datetime

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


def _seed_governance_history(client: TestClient, token: str) -> str:
    task = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={
            "title": "phase31-governance-seed",
            "description": "phase31 governance seed",
            "priority": "high",
            "category": "operations",
        },
    )
    assert task.status_code == 200, task.text
    task_id = str(task.json().get("task_id") or "")
    assert task_id

    resolved = client.post(
        "/api/ops/orchestration/task/resolve",
        headers=_headers(token),
        json={"task_id": task_id, "reason": "governance provenance seed"},
    )
    assert resolved.status_code == 200, resolved.text

    scenario = client.post(
        "/api/ops/replay/scenario/create",
        headers=_headers(token),
        json={
            "scenario_name": "Governance Provenance Seed",
            "hypothesis": "Governance lineage should remain deterministic and explainable.",
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
            "session_name": "Governance Session Alpha",
            "after_sequence": 0,
            "limit": 200,
            "scenario_id": scenario_id,
        },
    )
    assert session.status_code == 200, session.text
    session_id = str(session.json().get("replay_session_id") or "")
    assert session_id

    predictive = client.post(
        "/api/ops/predictive/governance",
        headers=_headers(token),
        json={"replay_session_id": session_id, "prediction_scope": "governance"},
    )
    assert predictive.status_code == 200, predictive.text
    return session_id


def test_governance_provenance_deterministic_and_explainable(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id = _seed_governance_history(client, admin_token)

    provenance_one = client.post(
        "/api/ops/governance/provenance",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "decision_scope": "governance_decision"},
    )
    provenance_two = client.post(
        "/api/ops/governance/provenance",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "decision_scope": "governance_decision"},
    )
    explanations = client.post(
        "/api/ops/governance/explanations",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "explanation_scope": "governance_explanation"},
    )
    reasoning = client.post(
        "/api/ops/governance/reasoning",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "reasoning_scope": "advisory_reasoning"},
    )
    memory = client.post(
        "/api/ops/governance/memory",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "memory_window": "long_horizon", "trend_window": "long_horizon"},
    )

    assert provenance_one.status_code == 200, provenance_one.text
    assert provenance_two.status_code == 200, provenance_two.text
    assert explanations.status_code == 200, explanations.text
    assert reasoning.status_code == 200, reasoning.text
    assert memory.status_code == 200, memory.text

    payload_one = provenance_one.json()
    payload_two = provenance_two.json()
    assert payload_one["advisory_only"] is True
    assert payload_one["execution_disabled"] is True
    assert payload_one["autonomous_execution"] is False
    assert payload_one["append_only"] is True
    assert payload_one["replay_safe"] is True
    assert payload_one["decision_scope"] == payload_two["decision_scope"]
    assert payload_one["provenance_score"] == payload_two["provenance_score"]

    explanation_payload = explanations.json()
    assert explanation_payload["explanation"]["summary"]
    assert explanation_payload["explanation_confidence"] >= 0

    reasoning_payload = reasoning.json()
    steps = reasoning_payload.get("rationale_steps", [])
    assert isinstance(steps, list)
    assert steps == sorted(steps, key=lambda row: row["rationale_json"].get("depth", 0))
    for row in steps:
        parsed = datetime.fromisoformat(str(row["timestamp"]))
        assert parsed.tzinfo is not None

    memory_payload = memory.json()
    assert memory_payload["memory"]["advisory_only"] is True
    assert memory_payload["trends"]["append_only"] is True
    assert memory_payload["decision_context"]["execution_disabled"] is True


def test_governance_ancestry_lineage_history_trends_and_export_integrity(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id = _seed_governance_history(client, admin_token)

    ancestry = client.get(f"/api/ops/governance/ancestry?replay_session_id={session_id}", headers=_headers(admin_token))
    lineage = client.get(f"/api/ops/governance/lineage?replay_session_id={session_id}", headers=_headers(admin_token))
    history = client.get(f"/api/ops/governance/history?replay_session_id={session_id}", headers=_headers(admin_token))
    trends = client.get(f"/api/ops/governance/trends?replay_session_id={session_id}", headers=_headers(admin_token))
    export_bundle = client.get(f"/api/ops/governance/export-bundle?replay_session_id={session_id}", headers=_headers(admin_token))

    assert ancestry.status_code == 200, ancestry.text
    assert lineage.status_code == 200, lineage.text
    assert history.status_code == 200, history.text
    assert trends.status_code == 200, trends.text
    assert export_bundle.status_code == 200, export_bundle.text

    ancestry_payload = ancestry.json()
    lineage_payload = lineage.json()
    history_payload = history.json()
    trends_payload = trends.json()
    export_payload = export_bundle.json()

    trace = ancestry_payload.get("ancestry_trace", [])
    assert trace == sorted(trace, key=lambda row: row["ancestry_depth"])
    for row in trace:
        parsed = datetime.fromisoformat(str(row["timestamp"]))
        assert parsed.tzinfo is not None

    lineage_steps = ((lineage_payload.get("lineage") or {}).get("lineage_steps") or [])
    assert lineage_steps == sorted(lineage_steps, key=lambda row: row["depth"])
    assert history_payload["advisory_only"] is True
    assert trends_payload["append_only"] is True

    canonical = json.dumps(export_payload.get("payload", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected_checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert export_payload.get("bundle_checksum") == expected_checksum
    assert export_payload.get("payload", {}).get("governance_reconstruction", {}).get("ordering") == "deterministic_timestamp_eventid_ascending"

    integrated = client.post(
        "/api/ops/compliance/exports/generate",
        headers=_headers(admin_token),
        json={"export_scope": "driver_regulatory_bundle"},
    )
    assert integrated.status_code == 200, integrated.text
    integrated_payload = integrated.json()
    assert "phase31_governance_provenance" in integrated_payload
    assert integrated_payload["phase31_governance_provenance"]["append_only"] is True


def test_governance_auth_boundaries_and_shell_fallback(client: TestClient) -> None:
    driver_token = _login(client, "driver@amicor.local")

    unauthorized_write = client.post(
        "/api/ops/governance/provenance",
        headers=_headers(driver_token),
        json={"decision_scope": "governance_decision"},
    )
    assert unauthorized_write.status_code in {401, 403}

    unauthorized_read = client.get("/api/ops/governance/ancestry")
    assert unauthorized_read.status_code in {401, 403}

    shell = client.get("/operations/governance")
    assert shell.status_code == 200, shell.text
    assert "ops-shell.js" in shell.text
