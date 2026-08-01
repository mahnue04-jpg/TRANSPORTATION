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

from app.deployment.release_version import resolve_app_version

logger = logging.getLogger("amicor.deployment.readiness")

# ─── Required and recommended environment variables ───────────────────────────

_REQUIRED_ENV = [
    "DATABASE_URL",
    "SECRET_KEY",
    "JWT_SECRET",
]

_PRODUCTION_REQUIRED_ENV = [
    "DATABASE_URL",
    "SECRET_KEY",
    "JWT_SECRET",
    "ALLOWED_ORIGINS",
    "AMICOR_PUBLIC_URL",
    "APP_VERSION",
]

_RECOMMENDED_ENV = [
    "LOG_LEVEL",
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
    """Static deployment readiness validation — optional DB connectivity probe."""

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
    def run_production_env_validation(cls) -> dict[str, Any]:
        """Validate all production/staging required variables."""
        issues: list[str] = []
        passed: list[str] = []

        for var in _PRODUCTION_REQUIRED_ENV:
            val = os.environ.get(var, "").strip()
            if not val:
                issues.append(f"Missing production env var: {var}")
                continue
            if var in _INSECURE_DEFAULTS and val.lower() in _INSECURE_DEFAULTS[var]:
                issues.append(f"Insecure default value detected for {var}")
                continue
            if var == "APP_VERSION" and val.lower() in {"dev", "local", "test"}:
                issues.append(f"APP_VERSION must be a release identifier, not '{val}'")
                continue
            passed.append(var)

        return {
            "required_present": len(issues) == 0,
            "issues": issues,
            "passed": passed,
            "required_vars": list(_PRODUCTION_REQUIRED_ENV),
        }

    @classmethod
    def run_config_checks(cls) -> dict[str, Any]:
        """
        Validate production configuration patterns.
        Returns dict of check_name → {passed, detail}.
        """
        checks: dict[str, dict[str, Any]] = {}

        origins_raw = os.environ.get("ALLOWED_ORIGINS", "")
        checks["cors_not_wildcard"] = {
            "passed": bool(origins_raw) and "*" not in origins_raw,
            "detail": (
                "ALLOWED_ORIGINS is missing"
                if not origins_raw
                else (
                    "ALLOWED_ORIGINS contains wildcard (*) — restrict before production"
                    if "*" in origins_raw
                    else "CORS origins appear restricted"
                )
            ),
        }

        debug_mode = os.environ.get("DEBUG", "").lower() in {"1", "true", "yes"}
        checks["debug_disabled"] = {
            "passed": not debug_mode,
            "detail": "DEBUG mode is enabled — disable in production" if debug_mode else "Debug mode off",
        }

        log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        checks["log_level_appropriate"] = {
            "passed": log_level in {"INFO", "WARNING", "ERROR", "CRITICAL"},
            "detail": (
                f"LOG_LEVEL={log_level} is verbose for production — consider INFO or higher"
                if log_level == "DEBUG"
                else f"Log level {log_level} is appropriate"
            ),
        }

        app_version = resolve_app_version()
        checks["app_version_set"] = {
            "passed": bool(app_version and app_version not in {"dev", "local"}),
            "detail": (
                "APP_VERSION not set or is a dev placeholder — set a release identifier"
                if not app_version or app_version in {"dev", "local"}
                else f"App version: {app_version}"
            ),
        }

        db_url = os.environ.get("DATABASE_URL", "")
        checks["production_database"] = {
            "passed": bool(db_url) and "sqlite" not in db_url.lower(),
            "detail": (
                "DATABASE_URL uses SQLite — not suitable for production"
                if db_url and "sqlite" in db_url.lower()
                else "Database URL points to production-grade data store" if db_url
                else "DATABASE_URL not configured"
            ),
        }

        public_url = os.environ.get("AMICOR_PUBLIC_URL", "").strip()
        checks["public_url_set"] = {
            "passed": bool(public_url) and public_url.startswith("https://"),
            "detail": (
                "AMICOR_PUBLIC_URL not set"
                if not public_url
                else (
                    "AMICOR_PUBLIC_URL must use https:// in production"
                    if not public_url.startswith("https://")
                    else f"Public URL configured: {public_url}"
                )
            ),
        }

        return checks

    @classmethod
    def _build_blocked_reasons(
        cls,
        env: dict[str, Any],
        production_env: dict[str, Any],
        config: dict[str, dict[str, Any]],
        *,
        db_ok: bool,
    ) -> list[str]:
        reasons: list[str] = []

        for issue in production_env.get("issues", []):
            if issue.startswith("Missing production env var:"):
                var = issue.split(":", 1)[1].strip()
                reasons.append(f"Set {var} before promoting to production (see STAGING_PRODUCTION_ENV_CHECKLIST.md).")
            else:
                reasons.append(issue)

        for issue in env.get("issues", []):
            if issue not in reasons:
                reasons.append(issue)

        for name, check in config.items():
            if not check.get("passed"):
                reasons.append(f"{name}: {check.get('detail', 'failed')}")

        if not db_ok:
            reasons.append(
                "Database connectivity check failed — verify DATABASE_URL, network access, and credentials."
            )

        return reasons

    @classmethod
    def build_readiness_report(cls, *, db_ok: bool | None = None) -> dict[str, Any]:
        """
        Produce a full deployment readiness report.
        Returns overall_status=ready only when production env, config, and DB checks pass.
        """
        env = cls.run_env_validation()
        production_env = cls.run_production_env_validation()
        config = cls.run_config_checks()

        db_detail: dict[str, Any] = {}
        if db_ok is None:
            try:
                from app.db.session import check_db_connection_detail
                db_detail = check_db_connection_detail()
                db_ok = bool(db_detail.get("connected"))
            except Exception as exc:
                db_ok = False
                db_detail = {
                    "connected": False,
                    "error_class": type(exc).__name__,
                    "blocker_category": "connectivity_failure",
                    "detail": "Database connectivity check failed",
                }

        blocked_reasons = cls._build_blocked_reasons(
            env,
            production_env,
            config,
            db_ok=bool(db_ok),
        )

        config_failures = sum(1 for c in config.values() if not c["passed"])
        production_ready = (
            production_env["required_present"]
            and config_failures == 0
            and bool(db_ok)
        )

        if production_ready:
            overall_status = "ready"
            score = 100 if not env.get("warnings") else 95
        elif production_env["required_present"] and bool(db_ok):
            overall_status = "staging_only"
            score = max(40, 80 - config_failures * 10)
        else:
            overall_status = "not_ready"
            score = max(0, 40 - len(blocked_reasons) * 8)

        return {
            "overall_status": overall_status,
            "score": score,
            "environment": env,
            "production_environment": production_env,
            "config_checks": config,
            "database": {
                "connected": bool(db_ok),
                "detail": "Database reachable" if db_ok else db_detail.get("detail", "Database unreachable"),
                **(
                    {}
                    if db_ok
                    else {
                        k: v
                        for k, v in {
                            "error_class": db_detail.get("error_class"),
                            "blocker_category": db_detail.get("blocker_category"),
                        }.items()
                        if v
                    }
                ),
            },
            "blocked_reasons": blocked_reasons,
            "summary": cls._compose_summary(overall_status, blocked_reasons),
            "recommendations": cls._build_recommendations(env, config, blocked_reasons),
        }

    @classmethod
    def _compose_summary(cls, status: str, blocked_reasons: list[str]) -> str:
        if status == "ready":
            return "Deployment environment meets production readiness criteria."
        if status == "staging_only":
            return (
                "Core environment variables are present and database is reachable, "
                "but one or more production configuration checks still need attention."
            )
        if not blocked_reasons:
            return "Deployment blocked: unknown readiness failure."
        return "Deployment blocked: " + "; ".join(blocked_reasons[:4])

    @classmethod
    def _build_recommendations(
        cls,
        env: dict[str, Any],
        config: dict[str, dict[str, Any]],
        blocked_reasons: list[str],
    ) -> list[str]:
        recs = list(blocked_reasons[:8])
        for warning in env.get("warnings", []):
            recs.append(f"Recommended: {warning}")
        for name, check in config.items():
            if not check["passed"] and check.get("detail") not in recs:
                recs.append(f"Config ({name}): {check['detail']}")
        return recs[:12]


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
            "app_version": resolve_app_version(),
            "log_level": os.environ.get("LOG_LEVEL", "INFO"),
        },
    }
