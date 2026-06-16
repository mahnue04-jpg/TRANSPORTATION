"""
Deployment readiness module for Amicor production staging.

Provides:
- environment validation
- production config checks
- structured deployment report
- API health monitoring hooks
"""
from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("amicor.deployment.readiness")

# ─── Required and recommended environment variables ───────────────────────────

_REQUIRED_ENV = [
    "DATABASE_URL",
    "SECRET_KEY",
    "JWT_SECRET",
]

_RECOMMENDED_ENV = [
    "ALLOWED_ORIGINS",
    "LOG_LEVEL",
    "APP_VERSION",
    "AMICOR_SEED_PASSWORD",
    "HEALTH_ISF_WS_MAX_ORG_CONNECTIONS",
]

_INSECURE_DEFAULTS = {
    "SECRET_KEY": {"changeme", "secret", "dev", "development"},
    "JWT_SECRET": {"changeme", "secret", "dev", "development"},
    "AMICOR_SEED_PASSWORD": {"password", "admin", "1234", "test"},
}


# ─── Checker ─────────────────────────────────────────────────────────────────

class DeploymentReadinessChecker:
    """Static deployment readiness validation — no DB access required."""

    @classmethod
    def run_env_validation(cls) -> dict[str, Any]:
        """
        Validate environment variable presence and known insecure defaults.
        Returns structured result with issues list.
        """
        issues: list[str] = []
        warnings: list[str] = []
        passed: list[str] = []

        for var in _REQUIRED_ENV:
            val = os.environ.get(var)
            if not val:
                issues.append(f"Missing required env var: {var}")
            elif var in _INSECURE_DEFAULTS and val.lower() in _INSECURE_DEFAULTS[var]:
                issues.append(f"Insecure default value detected for {var}")
            else:
                passed.append(var)

        for var in _RECOMMENDED_ENV:
            if not os.environ.get(var):
                warnings.append(f"Recommended env var not set: {var}")

        return {
            "required_present": len(issues) == 0,
            "issues": issues,
            "warnings": warnings,
            "passed": passed,
        }

    @classmethod
    def run_config_checks(cls) -> dict[str, Any]:
        """
        Validate production configuration patterns.
        Returns dict of check_name → {passed, detail}.
        """
        checks: dict[str, dict[str, Any]] = {}

        # CORS origins set to non-wildcard
        origins_raw = os.environ.get("ALLOWED_ORIGINS", "")
        checks["cors_not_wildcard"] = {
            "passed": "*" not in origins_raw or not origins_raw,
            "detail": (
                "ALLOWED_ORIGINS contains wildcard (*) — restrict before production"
                if "*" in origins_raw
                else "CORS origins appear restricted"
            ),
        }

        # Debug / reload flag not set
        debug_mode = os.environ.get("DEBUG", "").lower() in {"1", "true", "yes"}
        checks["debug_disabled"] = {
            "passed": not debug_mode,
            "detail": "DEBUG mode is enabled — disable in production" if debug_mode else "Debug mode off",
        }

        # Log level not DEBUG in production
        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        checks["log_level_appropriate"] = {
            "passed": log_level in {"INFO", "WARNING", "ERROR", "CRITICAL"},
            "detail": (
                f"LOG_LEVEL={log_level} is verbose for production — consider INFO or higher"
                if log_level == "DEBUG"
                else f"Log level {log_level} is appropriate"
            ),
        }

        # App version set
        app_version = os.environ.get("APP_VERSION", "")
        checks["app_version_set"] = {
            "passed": bool(app_version and app_version not in {"dev", "local"}),
            "detail": (
                "APP_VERSION not set or is a dev placeholder — set a release identifier"
                if not app_version or app_version in {"dev", "local"}
                else f"App version: {app_version}"
            ),
        }

        # Database URL points to non-SQLite source
        db_url = os.environ.get("DATABASE_URL", "")
        checks["production_database"] = {
            "passed": bool(db_url) and "sqlite" not in db_url.lower(),
            "detail": (
                "DATABASE_URL uses SQLite — not suitable for production"
                if "sqlite" in db_url.lower()
                else "Database URL points to production-grade data store" if db_url
                else "DATABASE_URL not configured"
            ),
        }

        return checks

    @classmethod
    def build_readiness_report(cls) -> dict[str, Any]:
        """
        Produce a full deployment readiness report without DB access.
        Suitable for /api/health/readiness endpoint.
        """
        env = cls.run_env_validation()
        config = cls.run_config_checks()

        # Score: env issues block, config failures deduct
        blocking_issues = len(env["issues"])
        config_failures = sum(1 for c in config.values() if not c["passed"])
        config_warnings = sum(1 for c in config.values() if c.get("passed") is False)

        if blocking_issues > 0:
            overall_status = "not_ready"
            score = max(0, 40 - blocking_issues * 15)
        elif config_failures > 0:
            overall_status = "staging_only"
            score = max(40, 80 - config_failures * 10)
        else:
            overall_status = "ready"
            score = 100 if not env["warnings"] else 90

        return {
            "overall_status": overall_status,
            "score": score,
            "environment": env,
            "config_checks": config,
            "summary": cls._compose_summary(overall_status, env, config_failures),
            "recommendations": cls._build_recommendations(env, config),
        }

    @classmethod
    def _compose_summary(
        cls,
        status: str,
        env: dict[str, Any],
        config_failures: int,
    ) -> str:
        if status == "ready":
            return "Deployment environment meets production readiness criteria."
        if status == "staging_only":
            return (
                f"Environment passes required checks but {config_failures} "
                "configuration item(s) should be addressed before production."
            )
        return (
            f"Deployment blocked: {len(env['issues'])} critical environment issue(s) must be resolved."
        )

    @classmethod
    def _build_recommendations(
        cls,
        env: dict[str, Any],
        config: dict[str, dict[str, Any]],
    ) -> list[str]:
        recs: list[str] = []
        for issue in env["issues"]:
            recs.append(f"Fix: {issue}")
        for name, check in config.items():
            if not check["passed"]:
                recs.append(f"Config: {check['detail']}")
        for warning in env.get("warnings", []):
            recs.append(f"Recommended: {warning}")
        return recs[:10]


# ─── Health monitoring hook ───────────────────────────────────────────────────

def build_health_monitoring_payload(db_ok: bool, ws_stats: dict[str, Any]) -> dict[str, Any]:
    """
    Build structured payload for API health monitoring endpoints.
    Consumed by /api/health/* routes.
    """
    return {
        "status": "healthy" if db_ok else "degraded",
        "checks": {
            "database": {"healthy": db_ok},
            "websocket": {
                "healthy": isinstance(ws_stats, dict),
                "active_connections": ws_stats.get("active_connections", 0),
            },
        },
        "environment": {
            "app_version": os.environ.get("APP_VERSION", "dev"),
            "log_level": os.environ.get("LOG_LEVEL", "INFO"),
        },
    }
