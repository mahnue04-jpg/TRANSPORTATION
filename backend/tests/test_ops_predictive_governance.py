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


def _seed_predictive_history(client: TestClient, token: str) -> str:
    task = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={
            "title": "phase30-predictive-seed",
            "description": "phase30 predictive seed",
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
        json={"task_id": task_id, "reason": "predictive seed resolution"},
    )
    assert resolved.status_code == 200, resolved.text

    scenario = client.post(
        "/api/ops/replay/scenario/create",
        headers=_headers(token),
        json={
            "scenario_name": "Predictive Governance Seed",
            "hypothesis": "Predictive governance should remain advisory-only and deterministic.",
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
            "session_name": "Predictive Session Alpha",
            "after_sequence": 0,
            "limit": 200,
            "scenario_id": scenario_id,
        },
    )
    assert session.status_code == 200, session.text
    session_id = str(session.json().get("replay_session_id") or "")
    assert session_id
    return session_id


def test_predictive_deterministic_predictions_and_anomaly_projection(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id = _seed_predictive_history(client, admin_token)

    governance_one = client.post(
        "/api/ops/predictive/governance",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "prediction_scope": "governance"},
    )
    governance_two = client.post(
        "/api/ops/predictive/governance",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "prediction_scope": "governance"},
    )
    anomaly_resp = client.post(
        "/api/ops/predictive/anomaly",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "anomaly_scope": "operational_anomaly"},
    )
    assert governance_one.status_code == 200, governance_one.text
    assert governance_two.status_code == 200, governance_two.text
    assert anomaly_resp.status_code == 200, anomaly_resp.text

    gov_one = governance_one.json()
    gov_two = governance_two.json()
    assert gov_one["advisory_only"] is True
    assert gov_one["execution_disabled"] is True
    assert gov_one["autonomous_execution"] is False
    assert gov_one["append_only"] is True
    assert gov_one["replay_safe"] is True
    assert gov_one["prediction_label"] == gov_two["prediction_label"]
    assert gov_one["governance_score"] == gov_two["governance_score"]
    assert gov_one["prediction_scope"] == gov_two["prediction_scope"]
    assert gov_one["prediction_json"]["snapshot"]["event_count"] >= 0

    anomaly_payload = anomaly_resp.json()
    anomalies = anomaly_payload.get("anomalies", [])
    assert isinstance(anomalies, list)
    assert len(anomalies) >= 1
    assert [row["anomaly_score"] for row in anomalies] == sorted([row["anomaly_score"] for row in anomalies], reverse=True)
    for row in anomalies:
        parsed = datetime.fromisoformat(str(row["timestamp"]))
        assert parsed.tzinfo is not None

    capacity_resp = client.post(
        "/api/ops/predictive/capacity",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "capacity_scope": "capacity_pressure"},
    )
    risk_resp = client.post(
        "/api/ops/predictive/risk",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "risk_domain": "governance_risk"},
    )
    constraints_resp = client.post(
        "/api/ops/predictive/constraints",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id, "constraint_domain": "operational_constraints"},
    )
    assert capacity_resp.status_code == 200, capacity_resp.text
    assert risk_resp.status_code == 200, risk_resp.text
    assert constraints_resp.status_code == 200, constraints_resp.text
    assert capacity_resp.json()["advisory_only"] is True
    assert risk_resp.json()["advisory_only"] is True
    assert constraints_resp.json()["advisory_only"] is True


def test_predictive_drift_recommendations_trends_and_export_integrity(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session_id = _seed_predictive_history(client, admin_token)

    drift_resp = client.get(
        f"/api/ops/predictive/drift?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    recommendations_resp = client.get(
        f"/api/ops/predictive/recommendations?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    trends_resp = client.get(
        f"/api/ops/predictive/trends?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    evidence_resp = client.get(
        f"/api/ops/predictive/evidence?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    export_resp = client.get(
        f"/api/ops/predictive/export-bundle?replay_session_id={session_id}",
        headers=_headers(admin_token),
    )
    assert drift_resp.status_code == 200, drift_resp.text
    assert recommendations_resp.status_code == 200, recommendations_resp.text
    assert trends_resp.status_code == 200, trends_resp.text
    assert evidence_resp.status_code == 200, evidence_resp.text
    assert export_resp.status_code == 200, export_resp.text

    drift_payload = drift_resp.json()
    recommendations_payload = recommendations_resp.json()
    trends_payload = trends_resp.json()
    evidence_payload = evidence_resp.json()
    export_payload = export_resp.json()

    assert drift_payload["advisory_only"] is True
    assert recommendations_payload["advisory_only"] is True
    assert trends_payload["advisory_only"] is True
    assert export_payload["advisory_only"] is True
    assert drift_payload["drift_events"] == sorted(
        drift_payload["drift_events"],
        key=lambda row: (row["drift_score"], row["drift_dimension"]),
        reverse=True,
    )
    assert recommendations_payload["recommendations"] == sorted(
        recommendations_payload["recommendations"],
        key=lambda row: row["recommendation_rank"],
    )
    assert trends_payload["trends"] == sorted(
        trends_payload["trends"],
        key=lambda row: (abs(row["trend_slope"]), row["trend_metric"]),
        reverse=True,
    )

    export_canonical = json.dumps(export_payload.get("payload", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    export_expected_checksum = hashlib.sha256(export_canonical.encode("utf-8")).hexdigest()
    evidence_canonical = json.dumps(evidence_payload.get("payload", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    evidence_expected_checksum = hashlib.sha256(evidence_canonical.encode("utf-8")).hexdigest()
    assert export_payload.get("bundle_checksum") == export_expected_checksum
    assert evidence_payload.get("bundle_checksum") == evidence_expected_checksum
    assert export_payload.get("payload", {}).get("predictive_reconstruction", {}).get("ordering") == "deterministic_timestamp_eventid_ascending"


def test_predictive_role_authorization_and_shell_fallback(client: TestClient) -> None:
    driver_token = _login(client, "driver@amicor.local")

    unauthorized_write = client.post(
        "/api/ops/predictive/governance",
        headers=_headers(driver_token),
        json={"prediction_scope": "governance"},
    )
    assert unauthorized_write.status_code in {401, 403}

    unauthorized_read = client.get("/api/ops/predictive/drift")
    assert unauthorized_read.status_code in {401, 403}

    shell = client.get("/operations/predictive")
    assert shell.status_code == 200, shell.text
    assert "ops-shell.js" in shell.text
