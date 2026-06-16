from __future__ import annotations

import hashlib
import json

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


def test_governance_constraint_replay_export_and_auth_boundaries(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session = client.post(
        "/api/ops/replay/session/create",
        headers=_headers(admin_token),
        json={"session_name": "Phase32 Constraint Replay", "after_sequence": 0, "limit": 200},
    )
    assert session.status_code == 200, session.text
    session_id = str(session.json().get("replay_session_id") or "")

    assert client.post("/api/ops/governance/policy/matrix", headers=_headers(admin_token), json={"replay_session_id": session_id}).status_code == 200
    assert client.post("/api/ops/governance/policy/evaluate", headers=_headers(admin_token), json={"replay_session_id": session_id}).status_code == 200
    assert client.post("/api/ops/governance/policy/score", headers=_headers(admin_token), json={"replay_session_id": session_id}).status_code == 200
    assert client.post("/api/ops/governance/rationale/build", headers=_headers(admin_token), json={"replay_session_id": session_id}).status_code == 200

    export_bundle = client.get(f"/api/ops/governance/export-bundle?replay_session_id={session_id}", headers=_headers(admin_token))
    assert export_bundle.status_code == 200, export_bundle.text
    export_payload = export_bundle.json()
    canonical = json.dumps(export_payload.get("payload", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected_checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert export_payload.get("bundle_checksum") == expected_checksum
    event_types = {row["event_type"] for row in export_payload.get("payload", {}).get("governance_events", [])}
    assert {"policy_constraint", "constraint_evaluation", "policy_score_snapshot", "governance_rationale_chain"}.issubset(event_types)
    assert export_payload.get("payload", {}).get("governance_reconstruction", {}).get("ordering") == "deterministic_timestamp_eventid_ascending"

    driver_token = _login(client, "driver@amicor.local")
    unauthorized_write = client.post(
        "/api/ops/governance/policy/evaluate",
        headers=_headers(driver_token),
        json={"replay_session_id": session_id},
    )
    assert unauthorized_write.status_code in {401, 403}

    unauthorized_read = client.get("/api/ops/governance/policy/history")
    assert unauthorized_read.status_code in {401, 403}

    shell = client.get("/operations/governance")
    assert shell.status_code == 200, shell.text
    assert "ops-shell.js" in shell.text