from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.auth import SEED_PASSWORD, ensure_auth_schema, seed_default_users
from app.main import app
from app.middleware import should_skip_expected_ops_monitoring_audit

REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_SHELL = REPO_ROOT / "backend" / "static" / "ops-shell.js"
RENDER_YAML = REPO_ROOT / "render.yaml"


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


def test_ops_shell_gates_enterprise_hydration_to_authorized_roles_and_screens() -> None:
    source = OPS_SHELL.read_text(encoding="utf-8")
    assert "function shouldScheduleEnterpriseMonitoringHydration()" in source
    assert "if (!shouldScheduleEnterpriseMonitoringHydration()) return;" in source
    assert "markEnterpriseOpsAuthorizationBackoff" in source
    assert "protectedOpsForbidden" in source

    for role in (
        "admin",
        "supervisor",
        "compliance_officer",
        "driver_support",
        "medical_coordinator",
    ):
        assert f"{role}: true" in source

    for unauthorized in ("dispatcher", "rider", "driver", "staff", "billing"):
        assert f"{unauthorized}: true" not in source.split("ENTERPRISE_OPS_AUTHORIZED_ROLES")[1].split(
            "ENTERPRISE_OPS_ALLOWED_ROUTES"
        )[0]

    allowed_block = source.split("ENTERPRISE_OPS_ALLOWED_ROUTES")[1].split("ENTERPRISE_OPS_AUTH_BACKOFF_MS")[0]
    for route in ("home", "dashboard", "analytics", "alerts"):
        assert f"{route}: true" in allowed_block
    for blocked in ("dispatch", "billing", "riders", "drivers", "mobile"):
        assert f"{blocked}: true" not in allowed_block


def test_render_yaml_keeps_one_uvicorn_worker_and_reduced_pool() -> None:
    text = RENDER_YAML.read_text(encoding="utf-8")
    assert "startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT" in text
    assert "--workers" not in text
    assert "gunicorn" not in text.lower()
    assert 'key: DB_POOL_SIZE' in text
    assert 'value: "5"' in text
    assert 'key: DB_MAX_OVERFLOW' in text
    pool_idx = text.index("DB_POOL_SIZE")
    overflow_idx = text.index("DB_MAX_OVERFLOW")
    pool_slice = text[pool_idx : pool_idx + 80]
    overflow_slice = text[overflow_idx : overflow_idx + 80]
    assert 'value: "5"' in pool_slice
    assert 'value: "5"' in overflow_slice


def test_expected_ops_monitoring_403_audit_skip_helper() -> None:
    assert should_skip_expected_ops_monitoring_audit("/api/ops/orchestration/queue", 403) is True
    assert should_skip_expected_ops_monitoring_audit("/api/ops/governance/history", 403) is True
    assert should_skip_expected_ops_monitoring_audit("/api/ops/predictive/drift", 403) is True
    assert should_skip_expected_ops_monitoring_audit("/api/ops/replay/timeline", 403) is True
    assert should_skip_expected_ops_monitoring_audit("/api/ops/federation/health", 403) is True

    assert should_skip_expected_ops_monitoring_audit("/api/ops/orchestration/queue", 401) is False
    assert should_skip_expected_ops_monitoring_audit("/api/ops/orchestration/queue", 500) is False
    assert should_skip_expected_ops_monitoring_audit("/api/ops/dashboard-summary", 403) is False
    assert should_skip_expected_ops_monitoring_audit("/api/auth/login", 401) is False
    assert should_skip_expected_ops_monitoring_audit("/api/health-isf/dispatch/queue", 403) is False


def test_dispatcher_orchestration_403_does_not_write_audit_row(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[tuple] = []

    def _capture(*args, **kwargs) -> None:
        writes.append(args)

    monkeypatch.setattr("app.middleware._write_audit_log", _capture)
    token = _login(client, "dispatcher@amicor.local")
    response = client.get("/api/ops/orchestration/queue", headers=_headers(token))
    assert response.status_code == 403
    assert writes == []


def test_rider_and_driver_protected_ops_remain_forbidden(client: TestClient) -> None:
    rider = _login(client, "rider@amicor.local")
    driver = _login(client, "driver@amicor.local")
    staff = _login(client, "staff@amicor.local")
    for token in (rider, driver, staff):
        response = client.get("/api/ops/replay/timeline", headers=_headers(token))
        assert response.status_code == 403


def test_admin_and_supervisor_enterprise_ops_remain_authorized(client: TestClient) -> None:
    admin = _login(client, "admin@amicor.local")
    supervisor = _login(client, "supervisor@amicor.local")
    for token in (admin, supervisor):
        queue = client.get("/api/ops/orchestration/queue", headers=_headers(token))
        replay = client.get("/api/ops/replay/timeline?after_sequence=0&limit=20", headers=_headers(token))
        assert queue.status_code == 200, queue.text
        assert replay.status_code == 200, replay.text


def test_unauthenticated_ops_still_rejected(client: TestClient) -> None:
    response = client.get("/api/ops/orchestration/queue")
    assert response.status_code in {401, 403}


def test_failed_login_still_writes_audit_row(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    writes: list[tuple] = []

    def _capture(*args, **kwargs) -> None:
        writes.append(args)

    monkeypatch.setattr("app.middleware._write_audit_log", _capture)
    response = client.post(
        "/api/auth/login",
        json={"email": "nobody@amicor.local", "password": "wrong-password-value"},
    )
    assert response.status_code in {401, 422}
    assert writes, "login failures must still generate an audit-row write"
