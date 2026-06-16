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


def test_governance_framework_mapping_supports_required_frameworks_and_export_integration(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    mapped = client.post(
        "/api/ops/governance/framework/map",
        headers=_headers(admin_token),
        json={"policy_scope": "governance_policy_constraints"},
    )
    frameworks = client.get("/api/ops/governance/frameworks", headers=_headers(admin_token))
    integrated = client.post(
        "/api/ops/compliance/exports/generate",
        headers=_headers(admin_token),
        json={"export_scope": "driver_regulatory_bundle"},
    )

    assert mapped.status_code == 200, mapped.text
    assert frameworks.status_code == 200, frameworks.text
    assert integrated.status_code == 200, integrated.text

    mapped_payload = mapped.json()
    frameworks_payload = frameworks.json()
    assert mapped_payload["frameworks"]
    assert mapped_payload["framework_rule_mappings"] == sorted(
        mapped_payload["framework_rule_mappings"],
        key=lambda row: (row["framework_name"], row["rule_code"], row["policy_id"]),
    )
    framework_names = {row["framework_name"] for row in frameworks_payload["frameworks"]}
    assert {
        "SOC2",
        "ISO27001",
        "HIPAA",
        "NIST",
        "GDPR",
        "PCI-DSS",
        "Internal Governance Policies",
    }.issubset(framework_names)
    integrated_payload = integrated.json()
    assert "phase32_governance_policy_evidence" in integrated_payload
    assert integrated_payload["phase32_governance_policy_evidence"]["append_only"] is True
