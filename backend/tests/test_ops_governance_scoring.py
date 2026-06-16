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


def _seed_session(client: TestClient, token: str) -> str:
    scenario = client.post(
        "/api/ops/replay/scenario/create",
        headers=_headers(token),
        json={
            "scenario_name": "Phase32 Score Seed",
            "hypothesis": "Weighted governance scores must remain deterministic under replay.",
            "scenario_type": "operational_replay",
            "baseline_window": "historical",
        },
    )
    assert scenario.status_code == 200, scenario.text
    session = client.post(
        "/api/ops/replay/session/create",
        headers=_headers(token),
        json={"session_name": "Phase32 Score Session", "after_sequence": 0, "limit": 200, "scenario_id": scenario.json()["scenario_id"]},
    )
    assert session.status_code == 200, session.text
    session_id = str(session.json().get("replay_session_id") or "")
    predictive = client.post(
        "/api/ops/predictive/governance",
        headers=_headers(token),
        json={"replay_session_id": session_id, "prediction_scope": "governance"},
    )
    assert predictive.status_code == 200, predictive.text
    return session_id


def test_governance_policy_scoring_is_explainable_and_deterministic(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id = _seed_session(client, admin_token)

    evaluation = client.post(
        "/api/ops/governance/policy/evaluate",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id},
    )
    score_one = client.post(
        "/api/ops/governance/policy/score",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "policy_scope": "governance_policy_constraints"},
    )
    score_two = client.post(
        "/api/ops/governance/policy/score",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "policy_scope": "governance_policy_constraints"},
    )
    risk = client.post(
        "/api/ops/governance/risk/evaluate",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id},
    )
    session_score = client.get(f"/api/ops/governance/score/{session_id}", headers=_headers(admin_token))

    assert evaluation.status_code == 200, evaluation.text
    assert score_one.status_code == 200, score_one.text
    assert score_two.status_code == 200, score_two.text
    assert risk.status_code == 200, risk.text
    assert session_score.status_code == 200, session_score.text

    payload_one = score_one.json()
    payload_two = score_two.json()
    assert payload_one["weighted_score"] == payload_two["weighted_score"]
    assert payload_one["score_status"] == payload_two["score_status"]
    snapshot = payload_one["score_snapshot"]
    assert set(snapshot["score_parts"]).issuperset(
        {
            "severity",
            "operational_impact",
            "replay_evidence_quality",
            "lineage_confidence",
            "rationale_completeness",
            "framework_priority",
            "policy_criticality",
            "historical_governance_consistency",
        }
    )
    assert set(snapshot["explainable"]["weights"]) == set(snapshot["score_parts"])
    assert payload_one["advisory_only"] is True
    assert payload_one["execution_disabled"] is True
    assert payload_one["autonomous_execution"] is False
    assert payload_one["append_only"] is True
    assert payload_one["replay_safe"] is True
    assert risk.json()["recommendations"]
    assert session_score.json()["weighted_score"] == payload_one["weighted_score"]
