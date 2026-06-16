from __future__ import annotations

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
    response = client.post("/api/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    token = str(response.json().get("access_token") or "")
    assert token
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_governance_rationale_chain_and_lineage_preserve_deterministic_order(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")
    session = client.post(
        "/api/ops/replay/session/create",
        headers=_headers(admin_token),
        json={"session_name": "Phase32 Rationale Session", "after_sequence": 0, "limit": 200},
    )
    assert session.status_code == 200, session.text
    session_id = str(session.json().get("replay_session_id") or "")

    rationale = client.post(
        "/api/ops/governance/rationale/build",
        headers=_headers(admin_token),
        json={"replay_session_id": session_id},
    )
    assert rationale.status_code == 200, rationale.text
    decision_id = str(rationale.json().get("decision_id") or "")
    assert decision_id

    detail = client.get(f"/api/ops/governance/rationale/{decision_id}", headers=_headers(admin_token))
    lineage = client.get(f"/api/ops/governance/policy/lineage?replay_session_id={session_id}", headers=_headers(admin_token))

    assert detail.status_code == 200, detail.text
    assert lineage.status_code == 200, lineage.text

    chain_rows = detail.json()["rationale_chain"]
    assert chain_rows == sorted(chain_rows, key=lambda row: row["chain_order"])
    for row in chain_rows:
      parsed = datetime.fromisoformat(str(row["timestamp"]))
      assert parsed.tzinfo is not None

    trace_rows = detail.json()["decision_trace"]
    assert isinstance(trace_rows, list)
    assert lineage.json()["policy_lineage"]
    assert rationale.json()["advisory_only"] is True
    assert detail.json()["execution_disabled"] is True
    assert lineage.json()["append_only"] is True
    assert lineage.json()["replay_safe"] is True
