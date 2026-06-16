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
    payload = response.json()
    token = str(payload.get("access_token") or "")
    assert token
    return token


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_task(client: TestClient, token: str, title_prefix: str = "phase28") -> str:
    response = client.post(
        "/api/ops/orchestration/task/create",
        headers=_headers(token),
        json={
            "title": f"{title_prefix}-{uuid4().hex[:8]}",
            "description": "phase28 federated supervised task",
            "priority": "high",
            "category": "operations",
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json().get("task_id"))


def _register_region(client: TestClient, token: str, code: str, name: str) -> dict:
    response = client.post(
        "/api/ops/federation/register-region",
        headers=_headers(token),
        json={"region_code": code, "region_name": name, "region_id": f"region-{code}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_register_region_and_list_regions(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    created = _register_region(client, admin_token, f"n{uuid4().hex[:4]}", "North Operations")
    assert created["governance_scope"] == "isolated"
    assert created["append_only"] is True

    listed = client.get("/api/ops/federation/regions", headers=_headers(admin_token))
    assert listed.status_code == 200, listed.text
    payload = listed.json()
    assert payload["regional_isolation"] is True
    assert payload["advisory_only"] is True
    assert isinstance(payload.get("regions"), list)


def test_cross_region_handoff_lineage_and_utc(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    code_a = f"e{uuid4().hex[:4]}"
    code_b = f"w{uuid4().hex[:4]}"
    region_a = _register_region(client, admin_token, code_a, "East Region")
    region_b = _register_region(client, admin_token, code_b, "West Region")
    task_id = _create_task(client, admin_token, "handoff")

    handoff = client.post(
        "/api/ops/federation/handoff/create",
        headers=_headers(admin_token),
        json={
            "task_id": task_id,
            "source_region_id": region_a["region_id"],
            "target_region_id": region_b["region_id"],
            "reason": "manual balancing",
        },
    )
    assert handoff.status_code == 200, handoff.text
    payload = handoff.json()

    assert payload["append_only"] is True
    assert payload["replay_safe"] is True
    assert payload["replay_lineage_ref"].startswith("cross-region-lineage-")
    parsed = datetime.fromisoformat(str(payload["timestamp"]))
    assert parsed.tzinfo is not None


def test_federated_capacity_continuity_advisory_safety(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    capacity = client.get("/api/ops/federation/capacity", headers=_headers(admin_token))
    continuity = client.get("/api/ops/federation/continuity", headers=_headers(admin_token))
    health = client.get("/api/ops/federation/health", headers=_headers(admin_token))

    assert capacity.status_code == 200, capacity.text
    assert continuity.status_code == 200, continuity.text
    assert health.status_code == 200, health.text

    cap_payload = capacity.json()
    con_payload = continuity.json()
    health_payload = health.json()

    assert cap_payload["advisory_only"] is True
    assert cap_payload["execution_disabled"] is True
    assert cap_payload["autonomous_execution"] is False

    assert con_payload["advisory_only"] is True
    assert con_payload["append_only"] is True
    assert con_payload["replay_safe"] is True

    assert health_payload["regional_isolation"] is True


def test_federated_export_bundle_integrity_and_compliance_integration(client: TestClient) -> None:
    admin_token = _login(client, "admin@amicor.local")

    exported = client.get("/api/ops/federation/export-bundle", headers=_headers(admin_token))
    assert exported.status_code == 200, exported.text
    payload = exported.json()

    canonical = json.dumps(payload.get("payload", {}), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    expected_checksum = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert payload.get("bundle_checksum") == expected_checksum
    assert payload.get("append_only") is True
    assert payload.get("replay_safe") is True

    integrated = client.post(
        "/api/ops/compliance/exports/generate",
        headers=_headers(admin_token),
        json={"export_scope": "driver_regulatory_bundle"},
    )
    assert integrated.status_code == 200, integrated.text
    integrated_payload = integrated.json()
    assert "phase28_federated_evidence" in integrated_payload
    assert integrated_payload["phase28_federated_evidence"]["append_only"] is True


def test_federation_auth_boundaries_and_shell_fallback(client: TestClient) -> None:
    driver_token = _login(client, "driver@amicor.local")

    unauth_read = client.get("/api/ops/federation/queues")
    assert unauth_read.status_code in {401, 403}

    unauthorized_write = client.post(
        "/api/ops/federation/register-region",
        headers=_headers(driver_token),
        json={"region_code": "x1", "region_name": "No Access"},
    )
    assert unauthorized_write.status_code in {401, 403}

    shell = client.get("/operations/federation")
    assert shell.status_code == 200, shell.text
    assert "ops-shell.js" in shell.text
