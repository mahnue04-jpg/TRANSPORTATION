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


def _login(client: TestClient, email: str) -> str:
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = str(response.json().get("access_token") or "")
    assert token
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _seed_phase32_history(client: TestClient, token: str) -> str:
    task = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={"title": "phase32-policy-seed", "description": "phase32 policy seed", "priority": "high", "category": "operations"},
    )
    assert task.status_code == 200, task.text
    task_id = str(task.json().get("task_id") or "")
    assert task_id

    resolved = client.post(
        "/api/ops/orchestration/task/resolve",
        headers=_headers(token),
        json={"task_id": task_id, "reason": "phase32 policy seed"},
    )
    assert resolved.status_code == 200, resolved.text

    scenario = client.post(
        "/api/ops/replay/scenario/create",
        headers=_headers(token),
        json={
            "scenario_name": "Phase32 Governance Policy Seed",
            "hypothesis": "Policy governance must remain explainable, deterministic, and advisory-only.",
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
        json={"session_name": "Phase32 Policy Session", "after_sequence": 0, "limit": 200, "scenario_id": scenario_id},
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


def test_governance_policy_matrix_and_constraint_catalog_are_deterministic(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id = _seed_phase32_history(client, admin_token)

    matrix_one = client.post(
        "/api/ops/governance/policy/matrix",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "policy_scope": "governance_policy_constraints"},
    )
    matrix_two = client.post(
        "/api/ops/governance/policy/matrix",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "policy_scope": "governance_policy_constraints"},
    )
    constraints = client.get("/api/ops/governance/constraints", headers=_headers(admin_token))
    frameworks = client.get("/api/ops/governance/frameworks", headers=_headers(admin_token))

    assert matrix_one.status_code == 200, matrix_one.text
    assert matrix_two.status_code == 200, matrix_two.text
    assert constraints.status_code == 200, constraints.text
    assert frameworks.status_code == 200, frameworks.text

    rows_one = matrix_one.json()["policy_matrix"]
    rows_two = matrix_two.json()["policy_matrix"]
    assert rows_one and rows_two
    assert [(row["framework_name"], row["policy_id"], row["rule_code"]) for row in rows_one] == [
        (row["framework_name"], row["policy_id"], row["rule_code"]) for row in rows_two
    ]
    assert matrix_one.json()["advisory_only"] is True
    assert matrix_one.json()["execution_disabled"] is True
    assert matrix_one.json()["autonomous_execution"] is False
    assert matrix_one.json()["append_only"] is True
    assert matrix_one.json()["replay_safe"] is True

    constraint_rows = constraints.json()["constraints"]
    assert constraint_rows == sorted(
        constraint_rows,
        key=lambda row: (-row["severity_weight"], row["framework_name"], row["policy_id"], row["rule_code"]),
    )
    framework_names = {row["framework_name"] for row in frameworks.json()["frameworks"]}
    assert {
        "SOC2",
        "ISO27001",
        "HIPAA",
        "NIST",
        "GDPR",
        "PCI-DSS",
        "Internal Governance Policies",
    }.issubset(framework_names)
