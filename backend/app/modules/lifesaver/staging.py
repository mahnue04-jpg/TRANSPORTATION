"""Lifesaver staging isolation. Request-time gates; production path is unchanged."""
from __future__ import annotations

import os
from typing import Iterable

from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

STAGING_ENVIRONMENTS = frozenset({"lifesaver_staging", "lifesaver_isolated_staging"})
ISOLATION_FLAG = "AMICOR_LIFESAVER_STAGING_ISOLATED"
PRODUCTION_HOST_HINTS = ("amicor-health-isf", "amicor-health-isf-py")
PRODUCTION_DB_HINTS = ("amicor-health-isf", "amicor-health-isf-db")
FORBIDDEN_INTEGRATION_PREFIXES = ("STRIPE_", "TWILIO_", "SES_", "SENDGRID_", "SMTP_")
LOCAL_ONLY_PREFIXES = ("/api/lifesaver/mock-pi",)

ALLOWED_PREFIXES = (
    "/lifesaver",
    "/api/lifesaver",
    "/api/auth",
    "/static/lifesaver",
    "/static/ux",
    "/static/branding",
    "/api/health/live",
    "/favicon.ico",
)
AGENT_PREFIX = "/api/lifesaver/home-hub-agent"
AGENT_PUBLIC_GET = frozenset({"/api/lifesaver/home-hub-agent/health"})


def environment_name() -> str:
    return (os.getenv("AMICOR_ENVIRONMENT") or os.getenv("ENVIRONMENT") or "").strip().lower()


def isolation_flag_enabled() -> bool:
    return os.getenv(ISOLATION_FLAG, "").strip().lower() in {"1", "true", "yes", "on"}


def lifesaver_staging_isolated() -> bool:
    return isolation_flag_enabled() or environment_name() in STAGING_ENVIRONMENTS


def database_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def looks_like_production_database(url: str | None = None) -> bool:
    value = (url if url is not None else database_url()).lower()
    return any(hint in value for hint in PRODUCTION_DB_HINTS)


def looks_like_production_public_url(url: str | None = None) -> bool:
    value = (url or os.getenv("AMICOR_PUBLIC_URL") or "").strip().lower()
    return any(hint in value for hint in PRODUCTION_HOST_HINTS)


def has_signing_secret() -> bool:
    return bool((os.getenv("JWT_SECRET") or os.getenv("SECRET_KEY") or "").strip())


def cors_is_wildcard() -> bool:
    return "*" in (os.getenv("ALLOWED_ORIGINS") or "")


def path_allowed(path: str) -> bool:
    normalized = path or "/"
    if normalized == "/":
        return True
    return any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in ALLOWED_PREFIXES)


def local_only_path(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in LOCAL_ONLY_PREFIXES)


def agent_requires_auth(path: str, method: str) -> bool:
    if not path.startswith(AGENT_PREFIX):
        return False
    if method.upper() == "GET" and path.rstrip("/") in AGENT_PUBLIC_GET:
        return False
    return True


def forbidden_integration_keys() -> list[str]:
    found: list[str] = []
    for key, value in os.environ.items():
        upper = key.upper()
        if any(upper.startswith(prefix) for prefix in FORBIDDEN_INTEGRATION_PREFIXES) and (value or "").strip():
            found.append(key)
    return sorted(found)


def validate_isolated_runtime() -> list[str]:
    errors: list[str] = []
    if not lifesaver_staging_isolated():
        return errors
    if not database_url():
        errors.append("DATABASE_URL is required for Lifesaver staging.")
    if looks_like_production_database():
        errors.append("DATABASE_URL looks like the Health ISF production database.")
    if looks_like_production_public_url():
        errors.append("AMICOR_PUBLIC_URL points at the Health ISF production host.")
    if not has_signing_secret():
        errors.append("JWT_SECRET or SECRET_KEY is required for Lifesaver staging.")
    if cors_is_wildcard():
        errors.append("ALLOWED_ORIGINS must not be a wildcard on Lifesaver staging.")
    if os.getenv("TESTING", "").strip().lower() in {"1", "true", "yes"}:
        errors.append("TESTING must stay unset on Lifesaver staging.")
    if os.getenv("LIFESAVER_SMOKE_ALLOW_PRODUCTION", "").strip() == "1":
        errors.append("LIFESAVER_SMOKE_ALLOW_PRODUCTION must stay disabled.")
    for key in forbidden_integration_keys():
        errors.append(f"{key} must remain unset on Lifesaver staging.")
    return errors


def identity() -> dict[str, object]:
    isolated = lifesaver_staging_isolated()
    return {
        "environment": environment_name() or "unspecified",
        "staging_isolated": isolated,
        "simulated_device_mode": True,
        "home_hub_public": False,
        "stripe_enabled": False,
        "twilio_enabled": False,
        "email_sending_enabled": False,
        "emergency_services_enabled": False,
        "alembic_heads_allowed": False,
    }


def initialize_auth_minimum() -> list[str]:
    """Create only the auth tables Lifesaver login needs. No Nova/Health/Freight tables."""
    if looks_like_production_database():
        raise RuntimeError("Refusing Lifesaver schema init against a production-looking DATABASE_URL.")
    from sqlalchemy import inspect

    from app.auth import ensure_auth_schema
    from app.db.models import RefreshToken, User
    from app.db.session import engine

    Base = User.__table__.metadata
    Base.create_all(bind=engine, tables=[User.__table__, RefreshToken.__table__])
    ensure_auth_schema()
    names = set(inspect(engine).get_table_names())
    return sorted(name for name in ("platform_users", "platform_refresh_tokens") if name in names)


def initialize_lifesaver_schema() -> list[str]:
    """Create missing lifesaver_* tables only. Does not run Alembic heads."""
    if looks_like_production_database():
        raise RuntimeError("Refusing Lifesaver schema init against a production-looking DATABASE_URL.")
    from sqlalchemy import inspect

    from app.db.session import engine
    from app.modules.lifesaver.models import LIFESAVER_MODELS, ensure_lifesaver_schema

    ensure_lifesaver_schema()
    names = set(inspect(engine).get_table_names())
    present = sorted(model.__tablename__ for model in LIFESAVER_MODELS if model.__tablename__ in names)
    if not present:
        raise RuntimeError("Lifesaver schema initialization produced no lifesaver_* tables.")
    return present


def initialize_isolated_staging_runtime() -> dict[str, list[str]]:
    auth_tables = initialize_auth_minimum()
    lifesaver_tables = initialize_lifesaver_schema()
    return {"auth_tables": auth_tables, "lifesaver_tables": lifesaver_tables}


def refuse_alembic_heads(command: Iterable[str] | str) -> None:
    parts = list(command) if not isinstance(command, str) else command.split()
    blob = " ".join(parts).lower()
    if "upgrade" in blob and "heads" in blob:
        raise RuntimeError("alembic upgrade heads is forbidden for Lifesaver staging.")


async def staging_isolation_middleware(request, call_next):
    if not lifesaver_staging_isolated():
        return await call_next(request)

    path = request.url.path or "/"
    method = request.method.upper()
    if path == "/":
        return RedirectResponse("/lifesaver", status_code=307)

    if local_only_path(path) or not path_allowed(path):
        return JSONResponse(
            {"error": "Lifesaver staging only. This hostname does not serve Nova, Health ISF, Delivery, or payments."},
            status_code=404,
        )

    runtime_errors = validate_isolated_runtime()
    if runtime_errors:
        return JSONResponse(
            {"error": "Lifesaver staging configuration is incomplete.", "blockers": runtime_errors},
            status_code=503,
        )

    if agent_requires_auth(path, method):
        auth = request.headers.get("authorization") or ""
        if not auth.lower().startswith("bearer "):
            return JSONResponse(
                {"error": "Home Hub agent routes require a signed-in Lifesaver session on staging."},
                status_code=401,
            )

    response = await call_next(request)
    response.headers["X-Amicor-Lifesaver-Staging"] = "isolated"
    return response


class LifesaverStagingIsolationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        return await staging_isolation_middleware(request, call_next)
