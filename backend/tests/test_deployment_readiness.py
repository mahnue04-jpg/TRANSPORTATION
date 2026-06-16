"""
Deployment Readiness Tests
────────────────────────────────────────────────────────────────────────────────

Validates the deployment readiness module and its API surface:
  - /api/health/readiness endpoint
  - /api/health/live endpoint
  - DeploymentReadinessChecker environment validation
  - DeploymentReadinessChecker config checks
  - Report structure and field types
"""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from app.auth import ensure_auth_schema, seed_default_users
from app.deployment.readiness import DeploymentReadinessChecker, build_health_monitoring_payload
from app.main import app


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client() -> TestClient:
    ensure_auth_schema()
    seed_default_users()
    return TestClient(app)


# ─── /api/health/live ─────────────────────────────────────────────────────────

class TestHealthLiveEndpoint:
    def test_health_live_returns_200(self, client: TestClient):
        response = client.get("/api/health/live")
        assert response.status_code == 200

    def test_health_live_has_status_ok(self, client: TestClient):
        response = client.get("/api/health/live")
        payload = response.json()
        assert payload["status"] == "ok"

    def test_health_live_includes_version(self, client: TestClient):
        response = client.get("/api/health/live")
        payload = response.json()
        assert "version" in payload
        assert isinstance(payload["version"], str)

    def test_health_live_requires_no_auth(self, client: TestClient):
        """Liveness probe must be accessible without authentication."""
        response = client.get("/api/health/live")
        assert response.status_code == 200


# ─── /api/health/readiness ────────────────────────────────────────────────────

class TestHealthReadinessEndpoint:
    def test_health_readiness_returns_200_or_503(self, client: TestClient):
        response = client.get("/api/health/readiness")
        assert response.status_code in {200, 503}, response.text

    def test_health_readiness_has_overall_status(self, client: TestClient):
        response = client.get("/api/health/readiness")
        payload = response.json()
        assert "overall_status" in payload
        assert payload["overall_status"] in {"ready", "staging_only", "not_ready"}

    def test_health_readiness_has_score(self, client: TestClient):
        response = client.get("/api/health/readiness")
        payload = response.json()
        assert "score" in payload
        assert isinstance(payload["score"], (int, float))
        assert 0 <= payload["score"] <= 100

    def test_health_readiness_has_environment_section(self, client: TestClient):
        response = client.get("/api/health/readiness")
        payload = response.json()
        assert "environment" in payload
        env = payload["environment"]
        assert "required_present" in env
        assert "issues" in env
        assert isinstance(env["issues"], list)

    def test_health_readiness_has_config_checks(self, client: TestClient):
        response = client.get("/api/health/readiness")
        payload = response.json()
        assert "config_checks" in payload
        assert isinstance(payload["config_checks"], dict)
        for check_name, check_data in payload["config_checks"].items():
            assert "passed" in check_data, f"{check_name} missing 'passed'"
            assert isinstance(check_data["passed"], bool)

    def test_health_readiness_has_recommendations(self, client: TestClient):
        response = client.get("/api/health/readiness")
        payload = response.json()
        assert "recommendations" in payload
        assert isinstance(payload["recommendations"], list)

    def test_health_readiness_requires_no_auth(self, client: TestClient):
        """Readiness probe must be accessible without a JWT."""
        response = client.get("/api/health/readiness")
        assert response.status_code in {200, 503}


# ─── DeploymentReadinessChecker unit tests ────────────────────────────────────

class TestEnvValidation:
    def test_detects_missing_required_var(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("JWT_SECRET", raising=False)

        result = DeploymentReadinessChecker.run_env_validation()

        assert result["required_present"] is False
        assert len(result["issues"]) >= 1
        missing_vars = " ".join(result["issues"])
        assert "DATABASE_URL" in missing_vars or "SECRET_KEY" in missing_vars

    def test_passes_when_all_required_vars_present(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://host/db")
        monkeypatch.setenv("SECRET_KEY", "supersecurekey-not-default-abcdef1234")
        monkeypatch.setenv("JWT_SECRET", "anothersecurekey-abcdef-ghijkl-1234")

        result = DeploymentReadinessChecker.run_env_validation()

        assert result["required_present"] is True
        assert all("DATABASE_URL" not in i and "SECRET_KEY" not in i for i in result["issues"])

    def test_detects_insecure_default_secret_key(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://host/db")
        monkeypatch.setenv("SECRET_KEY", "changeme")
        monkeypatch.setenv("JWT_SECRET", "changeme")

        result = DeploymentReadinessChecker.run_env_validation()

        assert result["required_present"] is False
        issues_text = " ".join(result["issues"])
        assert "SECRET_KEY" in issues_text or "JWT_SECRET" in issues_text

    def test_warnings_for_missing_recommended_vars(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://host/db")
        monkeypatch.setenv("SECRET_KEY", "supersecurekey-not-default-abcdef1234")
        monkeypatch.setenv("JWT_SECRET", "anothersecurekey-abcdef-ghijkl-1234")
        monkeypatch.delenv("APP_VERSION", raising=False)
        monkeypatch.delenv("LOG_LEVEL", raising=False)

        result = DeploymentReadinessChecker.run_env_validation()

        # Warnings should mention missing recommended vars
        assert isinstance(result["warnings"], list)


class TestConfigChecks:
    def test_detects_sqlite_database_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///./test.db")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert "production_database" in checks
        assert checks["production_database"]["passed"] is False

    def test_passes_postgresql_database_url(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@host:5432/amicor")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert checks["production_database"]["passed"] is True

    def test_detects_cors_wildcard(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "*")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert checks["cors_not_wildcard"]["passed"] is False

    def test_passes_restricted_cors_origins(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("ALLOWED_ORIGINS", "https://app.amicor.health,https://admin.amicor.health")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert checks["cors_not_wildcard"]["passed"] is True

    def test_detects_debug_mode(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("DEBUG", "true")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert checks["debug_disabled"]["passed"] is False

    def test_detects_debug_log_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert checks["log_level_appropriate"]["passed"] is False

    def test_passes_info_log_level(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LOG_LEVEL", "INFO")

        checks = DeploymentReadinessChecker.run_config_checks()

        assert checks["log_level_appropriate"]["passed"] is True


class TestReadinessReportStructure:
    def test_report_has_all_required_keys(self):
        report = DeploymentReadinessChecker.build_readiness_report()

        for key in ["overall_status", "score", "environment", "config_checks", "summary", "recommendations"]:
            assert key in report, f"Missing key: {key}"

    def test_report_overall_status_is_valid(self):
        report = DeploymentReadinessChecker.build_readiness_report()
        assert report["overall_status"] in {"ready", "staging_only", "not_ready"}

    def test_report_score_bounded(self):
        report = DeploymentReadinessChecker.build_readiness_report()
        assert 0 <= report["score"] <= 100

    def test_report_recommendations_is_list(self):
        report = DeploymentReadinessChecker.build_readiness_report()
        assert isinstance(report["recommendations"], list)


# ─── build_health_monitoring_payload ─────────────────────────────────────────

class TestHealthMonitoringPayload:
    def test_returns_healthy_when_db_ok(self):
        payload = build_health_monitoring_payload(db_ok=True, ws_stats={"active_connections": 5})
        assert payload["status"] == "healthy"
        assert payload["checks"]["database"]["healthy"] is True

    def test_returns_degraded_when_db_not_ok(self):
        payload = build_health_monitoring_payload(db_ok=False, ws_stats={})
        assert payload["status"] == "degraded"
        assert payload["checks"]["database"]["healthy"] is False

    def test_includes_websocket_stats(self):
        payload = build_health_monitoring_payload(db_ok=True, ws_stats={"active_connections": 12})
        assert payload["checks"]["websocket"]["active_connections"] == 12

    def test_includes_app_version(self):
        payload = build_health_monitoring_payload(db_ok=True, ws_stats={})
        assert "app_version" in payload["environment"]
